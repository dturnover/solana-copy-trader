// Answers two related questions with real on-chain data instead of theory:
//   1. Is a tracked wallet's own trading actually profitable? (ground truth,
//      from their real balance deltas)
//   2. If we copied their buys and sells at an assumed execution lag, would
//      WE have been profitable on the same round trips?
//
// Tracks open positions per (wallet, mint): a buy opens/adds to a position,
// a matching sell closes it and logs both the wallet's real P&L and our
// simulated P&L for that round trip. This is a research instrument, same
// spirit as lag_experiment -- not part of the live trading path.
//
// Important caveat baked into every result from this tool while running on
// the free `poll` engine: the RPC's own detection lag (measured elsewhere
// at a median of ~17s) is layered UNDERNEATH whatever execution_lag_ms is
// configured here, same as lag_experiment. This tool isolates the
// buy/hold/sell round-trip economics; it doesn't remove the free tier's
// detection floor.
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <optional>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#include "config.h"
#include "parsing/debug_utils.h"
#include "parsing/tx_parser_json.h"
#include "parsing/venue_pumpfun.h"
#include "rpc/rpc_client.h"
#include "solana/pubkey.h"
#include "util/logging.h"
#include "util/time.h"

namespace {

constexpr double kLamportsPerSol = 1'000'000'000.0;

int64_t now_wall_ms() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
               std::chrono::system_clock::now().time_since_epoch())
        .count();
}

struct OpenPosition {
    int64_t opened_at_ms = 0;
    int buy_count = 0;
    uint64_t wallet_token_amount = 0;
    int64_t wallet_lamports_spent = 0; // ground truth, cumulative
    double our_lamports_spent = 0.0;   // simulated at execution_lag_ms, cumulative
    solana::Pubkey bonding_curve;
    // True if ANY buy making up this position would have reverted on-chain
    // for a copy tx reusing the wallet's own max_sol_cost bound -- the price
    // had already moved past that bound by the time our lag elapsed. Recorded
    // rather than skipped; see the buy path for why.
    bool would_have_reverted = false;
};

struct WalletStats {
    int closed_trades = 0;
    int wallet_wins = 0;
    int our_wins = 0;
    double sum_wallet_pnl_sol = 0.0;
    double sum_our_pnl_sol = 0.0;
    int abandoned = 0;
};

void report_stats(const std::string& label, const WalletStats& s) {
    if (s.closed_trades == 0) return;
    LOG_INFO("  [" + label + "] closed=" + std::to_string(s.closed_trades) + " wallet_win_rate=" +
             std::to_string(100.0 * s.wallet_wins / s.closed_trades) + "% our_win_rate=" +
             std::to_string(100.0 * s.our_wins / s.closed_trades) +
             "% wallet_total_pnl=" + std::to_string(s.sum_wallet_pnl_sol) +
             "SOL our_total_pnl=" + std::to_string(s.sum_our_pnl_sol) +
             "SOL abandoned=" + std::to_string(s.abandoned));
}

// Stamped on every row so censored and complete data can never be pooled by
// accident. v1 (implicit -- the column does not exist in those files) silently
// dropped any buy whose lag-delayed cost exceeded the wallet's max_sol_cost
// bound, so v1 rows are a favourable-fills-only sample. v2 records those buys
// and flags them via would_have_reverted, so v2 is the complete population.
// Bump this whenever a change alters WHICH round trips get written, not merely
// what is computed for them.
constexpr int kCollectorVersion = 2;

void append_csv_row(const std::string& path, const std::string& row) {
    std::error_code ec;
    auto size = std::filesystem::file_size(path, ec);
    bool need_header = ec || size == 0;

    std::ofstream f(path, std::ios::app);
    if (!f.is_open()) {
        LOG_WARN("Could not open CSV file for append: " + path);
        return;
    }
    if (need_header) {
        f << "epoch_ms,wallet_label,mint,sell_signature,buy_count,hold_duration_ms,wallet_token_amount,"
             "wallet_lamports_spent,wallet_lamports_received,wallet_pnl_sol,"
             "our_lamports_spent,our_lamports_received,our_pnl_sol,"
             "would_have_reverted,collector_version\n";
    }
    f << row << "\n";
}

// Blocking: sleeps until execution_lag_ms has elapsed since `since_us`, then
// reads and decodes the bonding curve account. Wrapped try/catch at the call
// site handles transient RPC errors (rate limits, etc.) without crashing --
// learned the hard way in lag_experiment.
std::optional<parsing::pumpfun::BondingCurveState> read_curve_after_lag(rpc::RpcClient& client,
                                                                          const std::string& bonding_curve_b58,
                                                                          int64_t since_us, int64_t lag_ms) {
    int64_t target_us = since_us + lag_ms * 1000;
    int64_t now_us = util::now_micros();
    if (target_us > now_us) {
        std::this_thread::sleep_for(std::chrono::microseconds(target_us - now_us));
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(100)); // throttle, same reasoning as lag_experiment

    auto bytes = client.get_account_info(bonding_curve_b58);
    if (!bytes) return std::nullopt;
    return parsing::pumpfun::decode_bonding_curve(*bytes);
}

} // namespace

int main(int argc, char** argv) {
    std::string config_path = argc > 1 ? argv[1] : "config/config.json";

    app::AppConfig config;
    try {
        config = app::load_config(config_path);
    } catch (const std::exception& e) {
        LOG_ERROR(std::string("Config error: ") + e.what());
        return 1;
    }

    if (config.rpc_endpoint.empty()) {
        LOG_ERROR("paper_trade requires config.rpc.endpoint");
        return 1;
    }
    if (config.tracked_wallets.empty()) {
        LOG_ERROR("paper_trade requires a non-empty tracked_wallets list (always per-wallet, no firehose mode)");
        return 1;
    }

    LOG_INFO("Paper trade experiment: execution_lag_ms=" + std::to_string(config.paper_trade_execution_lag_ms) +
             " position_timeout_minutes=" + std::to_string(config.paper_trade_position_timeout_minutes) +
             " tracking " + std::to_string(config.tracked_wallets.size()) + " wallet(s)");

    rpc::RpcClient client(config.rpc_endpoint);
    std::unordered_map<solana::Pubkey, std::string, solana::PubkeyHash> last_seen_signature;
    std::unordered_map<std::string, OpenPosition> open_positions; // key: "<wallet_b58>|<mint_b58>"
    std::unordered_map<std::string, WalletStats> stats_by_wallet;
    WalletStats overall_stats;

    int64_t last_timeout_sweep_ms = now_wall_ms();

    while (true) {
        for (const auto& wallet : config.tracked_wallets) {
            std::string address = wallet.pubkey.to_base58();
            std::string until;
            auto seen_it = last_seen_signature.find(wallet.pubkey);
            if (seen_it != last_seen_signature.end()) until = seen_it->second;

            std::vector<rpc::SignatureInfo> new_sigs;
            try {
                new_sigs = client.get_signatures_for_address(address, until, 15);
            } catch (const std::exception& e) {
                LOG_WARN("Poll failed for " + wallet.label + ": " + e.what());
                continue;
            }
            if (new_sigs.empty()) continue;
            last_seen_signature[wallet.pubkey] = new_sigs.back().signature;

            for (const auto& sig_info : new_sigs) {
                if (sig_info.has_error) continue;

                std::this_thread::sleep_for(std::chrono::milliseconds(120));

                int64_t detected_at = util::now_micros();
                std::optional<nlohmann::json> tx_result;
                try {
                    tx_result = client.get_transaction(sig_info.signature);
                } catch (const std::exception& e) {
                    LOG_WARN("getTransaction failed for " + sig_info.signature + ": " + e.what());
                    continue;
                }
                if (!tx_result) continue;

                auto trade = parsing::parse_json_transaction(*tx_result, wallet.pubkey, wallet.label,
                                                              sig_info.signature, detected_at);
                if (!trade) continue;
                if (trade->bonding_curve == solana::Pubkey{}) continue;

                std::string position_key = address + "|" + trade->mint.to_base58();
                std::string bonding_curve_b58 = trade->bonding_curve.to_base58();

                auto wallet_delta = parsing::extract_wallet_sol_delta(*tx_result, wallet.pubkey);
                if (!wallet_delta) {
                    LOG_WARN("Could not find wallet balance delta for sig=" + sig_info.signature + ", skipping");
                    continue;
                }

                if (trade->direction == parsing::Direction::Buy) {
                    if (*wallet_delta >= 0) {
                        LOG_WARN("Buy tx for " + wallet.label + " showed non-negative SOL delta (" +
                                 std::to_string(*wallet_delta) + " lamports) -- unexpected, skipping");
                        continue;
                    }
                    int64_t spent = -*wallet_delta;

                    std::optional<parsing::pumpfun::BondingCurveState> state;
                    try {
                        state = read_curve_after_lag(client, bonding_curve_b58, detected_at,
                                                      config.paper_trade_execution_lag_ms);
                    } catch (const std::exception& e) {
                        LOG_WARN("getAccountInfo failed for bonding curve " + bonding_curve_b58 + ": " + e.what());
                        continue;
                    }
                    if (!state || state->complete) continue;

                    double our_cost = parsing::pumpfun::simulate_buy_sol_cost(
                        *state, static_cast<double>(trade->token_amount));
                    if (our_cost <= 0) continue;

                    // trade->sol_amount is the wallet's own on-chain
                    // max_sol_cost bound for this exact buy. If our
                    // lag-delayed price exceeds it, a copy transaction reusing
                    // that same bound would revert rather than fill worse.
                    //
                    // This used to `continue` here, dropping the buy entirely.
                    // That silently censored the dataset in one direction:
                    // adverse fills (price ran away during our lag) vanished
                    // while favourable ones were kept, so 86% of recorded
                    // fills came in CHEAPER than the wallet's -- impossible
                    // for a bot buying ~18s after someone else pushed the
                    // price up a bonding curve, and enough to make our
                    // simulated copy "outperform" the wallets it copies.
                    //
                    // Record it and flag it instead. A row flagged here is the
                    // counterfactual for a bot with a wider slippage bound
                    // than the wallet's; filtering them back out reproduces
                    // the old, bound-respecting strategy. Both are now
                    // answerable from the data, and the skip RATE is finally
                    // measurable at all.
                    bool buy_would_revert = our_cost > static_cast<double>(trade->sol_amount);
                    if (buy_would_revert) {
                        LOG_INFO(wallet.label + " BUY mint=" + trade->mint.to_base58() +
                                 " would have REVERTED on-chain at the wallet's own max_sol_cost bound "
                                 "(price moved past it during our lag) -- recorded and flagged, not skipped");
                    }

                    auto& pos = open_positions[position_key];
                    if (pos.buy_count == 0) pos.opened_at_ms = now_wall_ms();
                    pos.buy_count += 1;
                    pos.wallet_token_amount += trade->token_amount;
                    pos.wallet_lamports_spent += spent;
                    pos.our_lamports_spent += our_cost;
                    pos.bonding_curve = trade->bonding_curve;
                    pos.would_have_reverted = pos.would_have_reverted || buy_would_revert;

                    LOG_INFO(wallet.label + " BUY mint=" + trade->mint.to_base58() +
                             " (position buy #" + std::to_string(pos.buy_count) + ")");

                } else { // Sell
                    auto it = open_positions.find(position_key);
                    if (it == open_positions.end()) {
                        LOG_DEBUG(wallet.label + " sold mint=" + trade->mint.to_base58() +
                                  " with no tracked open position (pre-existing holdings or missed buy) -- skipping");
                        continue;
                    }
                    if (*wallet_delta <= 0) {
                        LOG_WARN("Sell tx for " + wallet.label + " showed non-positive SOL delta -- unexpected, skipping");
                        continue;
                    }

                    std::optional<parsing::pumpfun::BondingCurveState> state;
                    try {
                        state = read_curve_after_lag(client, bonding_curve_b58, detected_at,
                                                      config.paper_trade_execution_lag_ms);
                    } catch (const std::exception& e) {
                        LOG_WARN("getAccountInfo failed for bonding curve " + bonding_curve_b58 + ": " + e.what());
                        continue;
                    }
                    if (!state) continue; // curve gone/migrated is fine for a sell read, complete is not fatal here

                    double our_proceeds = parsing::pumpfun::simulate_sell_sol_proceeds(
                        *state, static_cast<double>(trade->token_amount));
                    if (our_proceeds <= 0) continue;

                    // Ground truth, not a heuristic: trade->sol_amount is the
                    // wallet's own on-chain min_sol_output bound for this
                    // exact sell. If our lag-delayed proceeds would fall
                    // short of it, a real copy transaction using the same
                    // bound would revert -- we'd still be holding the
                    // position, not exiting at a terrible price. Leave the
                    // position open (don't close it) rather than record a
                    // nonsensical proceeds figure.
                    if (our_proceeds < static_cast<double>(trade->sol_amount)) {
                        LOG_INFO(wallet.label + " SELL mint=" + trade->mint.to_base58() +
                                 " would have FAILED on-chain (price moved past their min_sol_output bound) -- "
                                 "position stays open");
                        continue;
                    }

                    OpenPosition pos = it->second; // treats any sell as fully closing -- see file header caveat
                    open_positions.erase(it);

                    int64_t hold_ms = now_wall_ms() - pos.opened_at_ms;
                    double wallet_pnl_sol = (*wallet_delta - pos.wallet_lamports_spent) / kLamportsPerSol;
                    double our_pnl_sol = (our_proceeds - pos.our_lamports_spent) / kLamportsPerSol;

                    auto& wstats = stats_by_wallet[wallet.label];
                    wstats.closed_trades += 1;
                    if (wallet_pnl_sol > 0) wstats.wallet_wins += 1;
                    if (our_pnl_sol > 0) wstats.our_wins += 1;
                    wstats.sum_wallet_pnl_sol += wallet_pnl_sol;
                    wstats.sum_our_pnl_sol += our_pnl_sol;

                    overall_stats.closed_trades += 1;
                    if (wallet_pnl_sol > 0) overall_stats.wallet_wins += 1;
                    if (our_pnl_sol > 0) overall_stats.our_wins += 1;
                    overall_stats.sum_wallet_pnl_sol += wallet_pnl_sol;
                    overall_stats.sum_our_pnl_sol += our_pnl_sol;

                    LOG_INFO(wallet.label + " CLOSED mint=" + trade->mint.to_base58() +
                             " hold_ms=" + std::to_string(hold_ms) + " wallet_pnl=" +
                             std::to_string(wallet_pnl_sol) + "SOL our_pnl=" + std::to_string(our_pnl_sol) + "SOL");
                    report_stats(wallet.label, wstats);
                    report_stats("OVERALL", overall_stats);

                    if (!config.paper_trade_csv_path.empty()) {
                        // sig_info.signature (the closing sell's signature) is
                        // globally unique on-chain -- lets offline analysis
                        // dedupe rows even though separate CI runs start with
                        // no persisted cursor and can re-detect the same
                        // historical close more than once.
                        append_csv_row(
                            config.paper_trade_csv_path,
                            std::to_string(now_wall_ms()) + "," + wallet.label + "," + trade->mint.to_base58() +
                                "," + sig_info.signature + "," + std::to_string(pos.buy_count) + "," +
                                std::to_string(hold_ms) + "," + std::to_string(pos.wallet_token_amount) + "," +
                                std::to_string(pos.wallet_lamports_spent) + "," + std::to_string(*wallet_delta) +
                                "," + std::to_string(wallet_pnl_sol) + "," + std::to_string(pos.our_lamports_spent) +
                                "," + std::to_string(static_cast<int64_t>(our_proceeds)) + "," +
                                std::to_string(our_pnl_sol) + "," + (pos.would_have_reverted ? "1" : "0") + "," +
                                std::to_string(kCollectorVersion));
                    }
                }
            }
        }

        // Bound memory + surface positions a wallet never closed out during
        // our observation window (still holding, or we missed the sell).
        int64_t now_ms = now_wall_ms();
        if (now_ms - last_timeout_sweep_ms > 60'000) {
            last_timeout_sweep_ms = now_ms;
            int64_t timeout_ms = static_cast<int64_t>(config.paper_trade_position_timeout_minutes) * 60'000;
            for (auto it = open_positions.begin(); it != open_positions.end();) {
                if (now_ms - it->second.opened_at_ms > timeout_ms) {
                    LOG_INFO("Abandoning stale open position: " + it->first + " (open " +
                             std::to_string((now_ms - it->second.opened_at_ms) / 60'000) + " min, no sell seen)");
                    overall_stats.abandoned += 1;
                    it = open_positions.erase(it);
                } else {
                    ++it;
                }
            }
        }

        std::this_thread::sleep_for(std::chrono::seconds(config.poll_interval_seconds));
    }
}
