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

    // Decision-time snapshot: the bonding curve exactly as it stood when we
    // would have entered, captured on the FIRST buy only. Everything a
    // "should we copy this?" model is allowed to know is fixed at that
    // instant -- anything sampled later (including at close) leaks the
    // outcome. Raw reserves are logged rather than derived ratios so the
    // feature layer can define liquidity / curve progress / impact without
    // this file hardcoding pump.fun's migration constants.
    bool entry_captured = false;
    uint64_t entry_virtual_sol_reserves = 0;
    uint64_t entry_virtual_token_reserves = 0;
    uint64_t entry_real_sol_reserves = 0;
    uint64_t entry_real_token_reserves = 0;
    uint64_t entry_token_total_supply = 0;
    double entry_our_cost_lamports = 0.0;  // first buy only; our_lamports_spent is cumulative

    // Holder concentration at entry -- the rug indicator that actually
    // applies to a bonding-curve token, unlike LP-burn or mint-authority
    // checks (no LP token exists pre-migration, and pump.fun renounces mint
    // and freeze authority at creation, so those are constants).
    // -1 means "not measured": the RPC call failed, and a failed risk check
    // must be distinguishable from a genuinely unconcentrated token.
    double entry_top10_holder_pct = -1.0;

    // Staleness of the wallet's buy when we caught it. Added to
    // execution_lag_ms, this is the real latency the fill was simulated at.
    // -1 if blockTime was unavailable.
    int64_t entry_on_chain_age_ms = -1;

    // Identity and on-chain time of the FIRST buy. With the sell's, this is
    // everything an offline replay needs to re-price the round trip at ANY
    // target lag from transaction history -- which is how the sub-second
    // question gets answered without owning sub-second infrastructure. The
    // live-account fill simulated in this file is stuck at whatever latency
    // the poller happened to have; a replay is not.
    std::string entry_signature;
    int64_t entry_block_time_ms = -1;
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
// and flags them via would_have_reverted -- but still dropped entire round
// trips whose SELL fell through the wallet's min_sol_output bound, leaving the
// position to age out as "abandoned". Those were the losing exits, so v2 is
// still optimistic. v3 records them too, via sell_would_have_reverted, and is
// the first genuinely complete population.
// Bump this whenever a change alters WHICH round trips get written, not merely
// what is computed for them -- so adding the entry_* feature columns below did
// NOT bump it: the same rows are written, with more recorded about each.
constexpr int kCollectorVersion = 3;

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
             "would_have_reverted,sell_would_have_reverted,"
             "entry_virtual_sol_reserves,entry_virtual_token_reserves,entry_real_sol_reserves,"
             "entry_real_token_reserves,entry_token_total_supply,entry_our_cost_lamports,"
             "entry_top10_holder_pct,incomplete_position,entry_on_chain_age_ms,"
             "sell_on_chain_age_ms,entry_signature,entry_block_time_ms,sell_block_time_ms,"
             "bonding_curve,collector_version\n";
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

                // How stale the trade already was when we caught it. This is
                // the number that decides what execution lag a row actually
                // represents, and paper_trade was not recording it while
                // lag_experiment was -- which is why every row here has been
                // read as "1.5s lag" when the true figure is
                // on_chain_age_ms + execution_lag_ms.
                int64_t block_time_ms = -1;
                int64_t on_chain_age_ms = -1;
                if (tx_result->contains("blockTime") && (*tx_result)["blockTime"].is_number()) {
                    block_time_ms = (*tx_result)["blockTime"].get<int64_t>() * 1000;
                    on_chain_age_ms = now_wall_ms() - block_time_ms;
                }

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

                    if (!pos.entry_captured) {
                        pos.entry_captured = true;
                        pos.entry_virtual_sol_reserves = state->virtual_sol_reserves;
                        pos.entry_virtual_token_reserves = state->virtual_token_reserves;
                        pos.entry_real_sol_reserves = state->real_sol_reserves;
                        pos.entry_real_token_reserves = state->real_token_reserves;
                        pos.entry_token_total_supply = state->token_total_supply;
                        pos.entry_our_cost_lamports = our_cost;
                        pos.entry_on_chain_age_ms = on_chain_age_ms;
                        pos.entry_signature = sig_info.signature;
                        pos.entry_block_time_ms = block_time_ms;

                        // One extra RPC call, on the first buy of a position
                        // only. Costs ~0.015% on top of the polling loop's
                        // ~950k calls/day, so the rate-limit pressure this
                        // job suffers comes from polling 22 wallets every 2s,
                        // not from here.
                        auto largest = client.get_token_largest_accounts(trade->mint.to_base58());
                        if (!largest.empty() && state->token_total_supply > 0) {
                            uint64_t top10 = 0;
                            for (size_t k = 0; k < largest.size() && k < 10; ++k) top10 += largest[k];
                            pos.entry_top10_holder_pct =
                                100.0 * static_cast<double>(top10) / static_cast<double>(state->token_total_supply);
                        }
                    }

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

                    // trade->sol_amount is the wallet's own on-chain
                    // min_sol_output bound for this exact sell. If our
                    // lag-delayed proceeds fall short of it, a copy tx reusing
                    // that bound would revert and we would still be holding.
                    //
                    // This used to `continue`, leaving the position open --
                    // which meant the round trip was NEVER written at all; it
                    // just aged out as "abandoned". Same one-sided censoring
                    // as the buy path, and strictly worse: a sell reverts
                    // exactly when the price fell through the wallet's floor
                    // during our lag, so the exits being dropped were the
                    // losing exits. Every bad exit silently left the dataset.
                    //
                    // Record and flag it. Filtering these back out reproduces
                    // the old bound-respecting behaviour; keeping them shows
                    // what a bot that actually had to get out would have
                    // eaten.
                    bool sell_would_revert = our_proceeds < static_cast<double>(trade->sol_amount);
                    if (sell_would_revert) {
                        LOG_INFO(wallet.label + " SELL mint=" + trade->mint.to_base58() +
                                 " would have REVERTED on-chain at the wallet's own min_sol_output bound "
                                 "(price fell past it during our lag) -- recorded and flagged, not skipped");
                    }

                    OpenPosition pos = it->second; // treats any sell as fully closing -- see file header caveat

                    // If they are selling materially MORE tokens than we saw
                    // them buy, we missed buys -- routine, since rate-limited
                    // polls drop signatures constantly. The damage is not a
                    // missing row, it is a WRONG one: the full sale proceeds
                    // get divided by only the fraction of the position we
                    // recorded, manufacturing enormous phantom profits. On
                    // data to 2026-08-05 this inflated 188 of 2422 rows by
                    // +394 SOL against a true total of -92, i.e. every
                    // positive headline in the dataset was this artifact.
                    // Flagged, not dropped, per the rule the rest of this
                    // file follows.
                    bool incomplete_position =
                        pos.wallet_token_amount > 0 &&
                        trade->token_amount > pos.wallet_token_amount + pos.wallet_token_amount / 20;
                    if (incomplete_position) {
                        LOG_INFO(wallet.label + " SELL mint=" + trade->mint.to_base58() + " sold " +
                                 std::to_string(trade->token_amount) + " tokens but we only tracked buys for " +
                                 std::to_string(pos.wallet_token_amount) + " -- missed buys, P&L for this row is "
                                 "computed against a partial position and is not trustworthy");
                    }
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
                                (sell_would_revert ? "1" : "0") + "," +
                                std::to_string(pos.entry_virtual_sol_reserves) + "," +
                                std::to_string(pos.entry_virtual_token_reserves) + "," +
                                std::to_string(pos.entry_real_sol_reserves) + "," +
                                std::to_string(pos.entry_real_token_reserves) + "," +
                                std::to_string(pos.entry_token_total_supply) + "," +
                                std::to_string(pos.entry_our_cost_lamports) + "," +
                                std::to_string(pos.entry_top10_holder_pct) + "," +
                                (incomplete_position ? "1" : "0") + "," +
                                std::to_string(pos.entry_on_chain_age_ms) + "," +
                                std::to_string(on_chain_age_ms) + "," + pos.entry_signature + "," +
                                std::to_string(pos.entry_block_time_ms) + "," + std::to_string(block_time_ms) + "," +
                                pos.bonding_curve.to_base58() + "," + std::to_string(kCollectorVersion));
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
