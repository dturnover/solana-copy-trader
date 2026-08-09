// Screens CANDIDATE wallets from their on-chain history, before spending a
// tracking slot on them.
//
// Why this exists. Tracking a wallet is expensive and the cost is not obvious:
// every tracked wallet costs ~43,200 RPC calls/day whether it trades or not,
// and that budget is the binding constraint on the whole experiment -- the
// collector runs at near-continuous RateLimitExceeded, which is what produces
// the ~17s detection lag that dominates every result. So "add wallets and see
// which ones work" is not free discovery; it degrades the measurements you are
// using to judge them, and it is how 15 of 29 tracked wallets ended up
// consuming 52% of the poll budget for <=2 trades each in five days.
//
// It is also statistically backwards. Adding N wallets and keeping whichever
// look good is N simultaneous experiments with the top tail retained -- the
// same selection error as picking off a daily leaderboard, just slower. At
// these fat tails several will look excellent by luck alone.
//
// A candidate's history is already on chain. This walks it directly: no
// tracking slot, no poll budget, and 100+ closed trades available immediately
// instead of after days of waiting. Only survivors earn a slot.
//
// WALLET-SIDE ONLY, deliberately. This answers "does this wallet make money",
// which is prior to and independent of "could we copy it". Simulating our fill
// would need the bonding curve as it stood at each historical moment, which is
// a different and much harder job (see the replay work); nothing here reads a
// curve, so nothing here depends on latency at all.
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
#include "rpc/rpc_client.h"
#include "solana/pubkey.h"
#include "util/logging.h"

namespace {

constexpr double kLamportsPerSol = 1'000'000'000.0;

// Marks these rows as screened-from-history rather than collected live. Kept
// far away from the collector's 1/2/3 so the two can never be pooled by
// accident: our_* columns are not populated here, and a scorecard run that
// silently mixed the two would be comparing different things.
constexpr int kScreenedVersion = 1000;

struct OpenPosition {
    int64_t opened_at_ms = 0;
    int buy_count = 0;
    uint64_t token_amount = 0;
    int64_t lamports_spent = 0;
};

void append_row(const std::string& path, const std::string& row) {
    std::error_code ec;
    auto size = std::filesystem::file_size(path, ec);
    bool need_header = ec || size == 0;
    std::ofstream f(path, std::ios::app);
    if (!f.is_open()) {
        LOG_WARN("Could not open " + path);
        return;
    }
    if (need_header) {
        // Deliberately the column names wallet_scorecard.py already reads, so
        // screening results go through exactly the same statistics as live
        // data with no second implementation to drift.
        f << "epoch_ms,wallet_label,mint,sell_signature,buy_count,hold_duration_ms,"
             "wallet_token_amount,wallet_lamports_spent,wallet_lamports_received,wallet_pnl_sol,"
             "collector_version\n";
    }
    f << row << "\n";
}

} // namespace

int main(int argc, char** argv) {
    std::string config_path = argc > 1 ? argv[1] : "config/config.json";
    std::string out_path = argc > 2 ? argv[2] : "screened_wallets.csv";
    int days = argc > 3 ? std::stoi(argv[3]) : 14;

    app::AppConfig config;
    try {
        config = app::load_config(config_path);
    } catch (const std::exception& e) {
        LOG_ERROR(std::string("Config error: ") + e.what());
        return 1;
    }
    if (config.rpc_endpoint.empty()) {
        LOG_ERROR("screen_wallets requires config.rpc.endpoint");
        return 1;
    }
    if (config.tracked_wallets.empty()) {
        LOG_ERROR("screen_wallets reads candidates from tracked_wallets");
        return 1;
    }

    int64_t cutoff_unix = std::chrono::duration_cast<std::chrono::seconds>(
                              std::chrono::system_clock::now().time_since_epoch())
                              .count() -
                          static_cast<int64_t>(days) * 86400;

    LOG_INFO("Screening " + std::to_string(config.tracked_wallets.size()) + " candidate(s) over " +
             std::to_string(days) + " day(s) of history -> " + out_path);

    rpc::RpcClient client(config.rpc_endpoint);

    for (const auto& wallet : config.tracked_wallets) {
        const std::string address = wallet.pubkey.to_base58();

        // Page backwards to the cutoff. Standard RPCs keep limited history, so
        // a short page run here usually means retention, not inactivity --
        // reported so a wallet is never rejected for an absence we caused.
        std::vector<rpc::SignatureInfo> history;
        std::string before;
        bool hit_cutoff = false;
        for (int page = 0; page < 40 && !hit_cutoff; ++page) {
            auto batch = client.get_signatures_before(address, before, 100);
            if (batch.empty()) break;
            for (const auto& s : batch) {
                if (s.block_time != 0 && s.block_time < cutoff_unix) {
                    hit_cutoff = true;
                    break;
                }
                history.push_back(s);
            }
            before = batch.back().signature;
            std::this_thread::sleep_for(std::chrono::milliseconds(150)); // free-tier courtesy
        }

        if (!hit_cutoff) {
            LOG_WARN(wallet.label + ": history ran out before the " + std::to_string(days) +
                     "-day cutoff -- the node's retention may be shorter than the window, so a "
                     "low trade count here is not evidence of inactivity");
        }

        // Oldest-first, so buys open positions before their sells close them.
        std::reverse(history.begin(), history.end());

        std::unordered_map<std::string, OpenPosition> open;
        int closed = 0;
        double total_pnl = 0.0;

        for (const auto& sig_info : history) {
            if (sig_info.has_error) continue;

            std::optional<nlohmann::json> tx;
            try {
                tx = client.get_transaction(sig_info.signature);
            } catch (const std::exception& e) {
                LOG_WARN("getTransaction failed for " + sig_info.signature + ": " + e.what());
                continue;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(120));
            if (!tx) continue;

            auto trade = parsing::parse_json_transaction(*tx, wallet.pubkey, wallet.label,
                                                          sig_info.signature, 0);
            if (!trade) continue;

            auto delta = parsing::extract_wallet_sol_delta(*tx, wallet.pubkey);
            if (!delta) continue;

            int64_t block_ms = sig_info.block_time * 1000;
            const std::string key = trade->mint.to_base58();

            if (trade->direction == parsing::Direction::Buy) {
                if (*delta >= 0) continue; // a buy that did not cost SOL is not a buy we understand
                auto& pos = open[key];
                if (pos.buy_count == 0) pos.opened_at_ms = block_ms;
                pos.buy_count += 1;
                pos.token_amount += trade->token_amount;
                pos.lamports_spent += -*delta;
            } else {
                auto it = open.find(key);
                if (it == open.end()) continue; // sold something we never saw bought
                if (*delta <= 0) continue;

                const OpenPosition pos = it->second;
                open.erase(it);

                double pnl = (*delta - pos.lamports_spent) / kLamportsPerSol;
                closed += 1;
                total_pnl += pnl;

                append_row(out_path,
                           std::to_string(block_ms) + "," + wallet.label + "," + key + "," +
                               sig_info.signature + "," + std::to_string(pos.buy_count) + "," +
                               std::to_string(block_ms - pos.opened_at_ms) + "," +
                               std::to_string(pos.token_amount) + "," + std::to_string(pos.lamports_spent) + "," +
                               std::to_string(*delta) + "," + std::to_string(pnl) + "," +
                               std::to_string(kScreenedVersion));
            }
        }

        LOG_INFO(wallet.label + ": " + std::to_string(history.size()) + " signature(s) scanned, " +
                 std::to_string(closed) + " closed round trip(s), P&L " + std::to_string(total_pnl) +
                 " SOL, " + std::to_string(open.size()) + " still open at scan end");
    }

    LOG_INFO("Done. Score with: python3 reports/wallet_scorecard.py " + out_path + " screened_scorecard.csv");
    return 0;
}
