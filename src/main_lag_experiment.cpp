// Measures how much a hypothetical buy's price degrades between detecting a
// pump.fun buy and executing some milliseconds later -- i.e. the actual cost
// of copy-trading lag, using live bonding-curve reserves rather than
// theorizing about it.
//
// Two modes:
//  - tracked-wallet mode: sample only buys from configured wallets
//  - firehose mode (lag_experiment.firehose=true): poll the pump.fun program
//    itself and sample ANY sufficiently-fresh buy. Lag cost doesn't depend on
//    who traded, only on how the curve moves afterward, so this collects far
//    more samples, far fresher, with no wallet-picking required.
//
// This is deliberately a separate tool from copytrader: it's a research
// instrument whose output should inform whether paying for the real-time
// gRPC engine (and eventually live execution) is worth it.
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <deque>
#include <filesystem>
#include <fstream>
#include <numeric>
#include <optional>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
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

// Constant-product (x*y=k) fill simulation against pump.fun's virtual
// reserves -- ignores the protocol fee, which is fine here since the same
// approximation is applied at both measurement points and mostly cancels
// out in the relative comparison this tool cares about.
double simulate_effective_price(uint64_t virtual_sol_reserves, uint64_t virtual_token_reserves, double sol_in) {
    double new_sol = static_cast<double>(virtual_sol_reserves) + sol_in;
    if (new_sol <= 0) return -1.0;
    double tokens_out = static_cast<double>(virtual_token_reserves) -
                         (static_cast<double>(virtual_sol_reserves) * static_cast<double>(virtual_token_reserves)) /
                             new_sol;
    if (tokens_out <= 0) return -1.0;
    return sol_in / tokens_out;
}

double mean_of(const std::vector<double>& v) {
    if (v.empty()) return 0.0;
    return std::accumulate(v.begin(), v.end(), 0.0) / static_cast<double>(v.size());
}

// Median is the headline stat: bonding-curve moves are heavy-tailed (one
// 300% rug/pump sample would swamp a mean built from fifty 1% samples).
double median_of(std::vector<double> v) {
    if (v.empty()) return 0.0;
    std::sort(v.begin(), v.end());
    size_t mid = v.size() / 2;
    if (v.size() % 2 == 1) return v[mid];
    return (v[mid - 1] + v[mid]) / 2.0;
}

struct LagStats {
    std::vector<double> pct_price_change; // positive = price got worse for a buyer
};

int64_t now_wall_ms() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
               std::chrono::system_clock::now().time_since_epoch())
        .count();
}

// In firehose mode the transaction wasn't fetched via a known wallet, so the
// "wallet" for the sample is the transaction's fee payer (first signer in
// jsonParsed accountKeys).
std::optional<solana::Pubkey> extract_fee_payer(const nlohmann::json& tx_result) {
    if (!tx_result.contains("transaction") || !tx_result["transaction"].contains("message")) {
        return std::nullopt;
    }
    const auto& msg = tx_result["transaction"]["message"];
    if (!msg.contains("accountKeys") || !msg["accountKeys"].is_array()) return std::nullopt;
    for (const auto& key : msg["accountKeys"]) {
        if (key.is_object() && key.value("signer", false) && key.contains("pubkey")) {
            solana::Pubkey pk;
            if (solana::Pubkey::from_base58(key["pubkey"].get<std::string>(), pk)) {
                return pk;
            }
        }
    }
    return std::nullopt;
}

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
        f << "epoch_ms,label,signature,mint,on_chain_age_ms,target_lag_ms,actual_elapsed_ms,"
             "baseline_price,later_price,pct_change\n";
    }
    f << row << "\n";
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
        LOG_ERROR("lag_experiment requires config.rpc.endpoint (used for polling + live account reads) "
                  "even if \"engine\" is set to \"geyser\"");
        return 1;
    }

    std::vector<int> lag_scenarios_ms = config.lag_scenarios_ms;
    std::sort(lag_scenarios_ms.begin(), lag_scenarios_ms.end());
    double sol_in = config.lag_experiment_sol_in;

    struct Source {
        solana::Pubkey address;
        std::string label;
    };
    std::vector<Source> sources;
    if (config.lag_firehose) {
        sources.push_back({parsing::pumpfun::kProgramId, "firehose"});
    } else {
        for (const auto& w : config.tracked_wallets) {
            sources.push_back({w.pubkey, w.label});
        }
    }

    std::string scenarios_str;
    for (int ms : lag_scenarios_ms) scenarios_str += std::to_string(ms) + "ms ";
    LOG_INFO("Lag-cost experiment: hypothetical order size " + std::to_string(sol_in) +
             " SOL, lag scenarios: " + scenarios_str);
    if (config.lag_firehose) {
        LOG_INFO("Mode: FIREHOSE -- sampling any pump.fun buy" +
                 std::string(config.lag_max_tx_age_ms > 0
                                  ? " fresher than " + std::to_string(config.lag_max_tx_age_ms) + "ms"
                                  : "") +
                 (config.lag_csv_path.empty() ? "" : ", logging samples to " + config.lag_csv_path));
    } else {
        LOG_INFO("Mode: tracked wallets (" + std::to_string(sources.size()) + "), pump.fun buys only.");
    }

    rpc::RpcClient client(config.rpc_endpoint);
    std::unordered_map<solana::Pubkey, std::string, solana::PubkeyHash> last_seen_signature; // tracked-wallet cursor
    std::unordered_map<solana::Pubkey, bool, solana::PubkeyHash> primed;
    std::unordered_map<int, LagStats> stats_by_lag;

    // Firehose-mode dedup: pump.fun's total transaction volume outpaces any
    // sane per-poll `limit`, so an incremental `until` cursor (fine for a
    // single wallet's modest volume) just falls further behind a growing
    // backlog forever -- which is exactly what produced 100% staleness.
    // Instead, every poll asks for the newest N signatures unconditionally
    // and skips ones already seen, sampling a representative slice of
    // *current* activity instead of exhaustively draining history.
    std::deque<std::string> seen_order;
    std::unordered_set<std::string> seen_set;
    constexpr size_t kSeenCap = 1000;
    auto mark_seen = [&](const std::string& sig) {
        seen_set.insert(sig);
        seen_order.push_back(sig);
        if (seen_order.size() > kSeenCap) {
            seen_set.erase(seen_order.front());
            seen_order.pop_front();
        }
    };

    while (true) {
        for (const auto& source : sources) {
            std::string address = source.address.to_base58();

            std::vector<rpc::SignatureInfo> new_sigs;
            try {
                if (config.lag_firehose) {
                    new_sigs = client.get_signatures_for_address(address, "", 15);
                } else {
                    std::string until;
                    auto seen_it = last_seen_signature.find(source.address);
                    if (seen_it != last_seen_signature.end()) until = seen_it->second;
                    new_sigs = client.get_signatures_for_address(address, until, 15);
                }
            } catch (const std::exception& e) {
                LOG_WARN("Poll failed for " + source.label + ": " + e.what());
                continue;
            }
            if (new_sigs.empty()) continue;

            if (!config.lag_firehose) {
                last_seen_signature[source.address] = new_sigs.back().signature;
            }

            // First batch is a snapshot of recent history, not live flow --
            // mark it all seen and start sampling from the next poll so
            // every processed tx is genuinely fresh.
            if (config.lag_firehose && !primed[source.address]) {
                primed[source.address] = true;
                for (const auto& s : new_sigs) mark_seen(s.signature);
                LOG_INFO("Firehose primed with " + std::to_string(new_sigs.size()) + " signature(s), sampling begins");
                continue;
            }

            int scanned = 0, buys = 0, stale = 0, sampled = 0, deduped = 0;
            std::vector<int64_t> stale_ages;

            for (const auto& sig_info : new_sigs) {
                if (config.lag_firehose) {
                    if (seen_set.count(sig_info.signature)) {
                        ++deduped;
                        continue;
                    }
                    mark_seen(sig_info.signature);
                }
                if (sig_info.has_error) continue;
                ++scanned;

                // Throttle getTransaction bursts -- Shyft's free tier allows
                // ~10 req/sec and a firehose batch can be 15 signatures.
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

                int64_t on_chain_age_ms = -1;
                if (tx_result->contains("blockTime") && (*tx_result)["blockTime"].is_number()) {
                    on_chain_age_ms = now_wall_ms() - (*tx_result)["blockTime"].get<int64_t>() * 1000;
                }

                // Freshness gate: a stale baseline measures ambient drift,
                // not lag cost, so skip anything the poll caught too late.
                if (config.lag_max_tx_age_ms > 0 && on_chain_age_ms > config.lag_max_tx_age_ms) {
                    ++stale;
                    stale_ages.push_back(on_chain_age_ms);
                    continue;
                }

                solana::Pubkey wallet;
                std::string wallet_label = source.label;
                if (config.lag_firehose) {
                    auto payer = extract_fee_payer(*tx_result);
                    if (!payer) continue;
                    wallet = *payer;
                } else {
                    wallet = source.address;
                }

                auto trade = parsing::parse_json_transaction(*tx_result, wallet, wallet_label,
                                                              sig_info.signature, detected_at);
                if (!trade) {
                    if (!config.lag_firehose) {
                        LOG_DEBUG("sig=" + sig_info.signature + " matched no known venue -- programs invoked: [" +
                                  parsing::extract_program_ids(*tx_result) + "]");
                    }
                    continue;
                }
                if (trade->direction != parsing::Direction::Buy) continue;
                if (trade->bonding_curve == solana::Pubkey{}) continue;
                ++buys;

                std::string bonding_curve_b58 = trade->bonding_curve.to_base58();

                // Throttle before every getAccountInfo call, not just
                // getTransaction -- a burst of buys in one poll cycle can
                // otherwise fire several of these back-to-back and trip the
                // free tier's rate limit.
                std::this_thread::sleep_for(std::chrono::milliseconds(100));
                std::optional<std::vector<uint8_t>> baseline_bytes;
                try {
                    baseline_bytes = client.get_account_info(bonding_curve_b58);
                } catch (const std::exception& e) {
                    LOG_WARN("getAccountInfo failed for bonding curve " + bonding_curve_b58 + ": " + e.what());
                    continue;
                }
                if (!baseline_bytes) continue;
                auto baseline_state = parsing::pumpfun::decode_bonding_curve(*baseline_bytes);
                if (!baseline_state) {
                    LOG_WARN("Bonding curve account for mint=" + trade->mint.to_base58() +
                             " didn't match the expected layout -- the assumed account index (3) may be "
                             "wrong for this transaction, skipping sample");
                    continue;
                }
                if (baseline_state->complete) continue; // already migrated, curve is dead

                double baseline_price = simulate_effective_price(
                    baseline_state->virtual_sol_reserves, baseline_state->virtual_token_reserves, sol_in);
                if (baseline_price <= 0) continue;

                LOG_INFO(wallet_label + " BUY mint=" + trade->mint.to_base58() +
                         " age_ms=" + std::to_string(on_chain_age_ms) +
                         " baseline_price=" + std::to_string(baseline_price));

                int64_t baseline_us = util::now_micros();
                for (int target_lag_ms : lag_scenarios_ms) {
                    int64_t target_us = baseline_us + static_cast<int64_t>(target_lag_ms) * 1000;
                    int64_t now_us = util::now_micros();
                    if (target_us > now_us) {
                        std::this_thread::sleep_for(std::chrono::microseconds(target_us - now_us));
                    }

                    std::this_thread::sleep_for(std::chrono::milliseconds(100));
                    std::optional<std::vector<uint8_t>> later_bytes;
                    try {
                        later_bytes = client.get_account_info(bonding_curve_b58);
                    } catch (const std::exception& e) {
                        LOG_WARN("getAccountInfo failed for bonding curve " + bonding_curve_b58 + ": " + e.what());
                        continue;
                    }
                    if (!later_bytes) continue;
                    auto later_state = parsing::pumpfun::decode_bonding_curve(*later_bytes);
                    if (!later_state || later_state->complete) continue;

                    double later_price = simulate_effective_price(
                        later_state->virtual_sol_reserves, later_state->virtual_token_reserves, sol_in);
                    if (later_price <= 0) continue;

                    int64_t actual_elapsed_ms = (util::now_micros() - baseline_us) / 1000;
                    double pct_change = (later_price - baseline_price) / baseline_price * 100.0;

                    auto& stats = stats_by_lag[target_lag_ms];
                    stats.pct_price_change.push_back(pct_change);
                    ++sampled;

                    LOG_INFO("  lag=" + std::to_string(target_lag_ms) +
                             "ms elapsed=" + std::to_string(actual_elapsed_ms) +
                             "ms change=" + std::to_string(pct_change) + "% | n=" +
                             std::to_string(stats.pct_price_change.size()) +
                             " median=" + std::to_string(median_of(stats.pct_price_change)) +
                             "% mean=" + std::to_string(mean_of(stats.pct_price_change)) + "%");

                    if (!config.lag_csv_path.empty()) {
                        append_csv_row(config.lag_csv_path,
                                       std::to_string(now_wall_ms()) + "," + wallet_label + "," +
                                           sig_info.signature + "," + trade->mint.to_base58() + "," +
                                           std::to_string(on_chain_age_ms) + "," + std::to_string(target_lag_ms) +
                                           "," + std::to_string(actual_elapsed_ms) + "," +
                                           std::to_string(baseline_price) + "," + std::to_string(later_price) +
                                           "," + std::to_string(pct_change));
                    }
                }
            }

            if (config.lag_firehose && scanned > 0) {
                std::string age_info;
                if (!stale_ages.empty()) {
                    int64_t min_age = *std::min_element(stale_ages.begin(), stale_ages.end());
                    int64_t max_age = *std::max_element(stale_ages.begin(), stale_ages.end());
                    age_info = " stale_age_ms=[min=" + std::to_string(min_age) + " max=" + std::to_string(max_age) +
                               " median=" + std::to_string(static_cast<int64_t>(median_of(
                                                std::vector<double>(stale_ages.begin(), stale_ages.end())))) + "]";
                }
                LOG_INFO("cycle: scanned=" + std::to_string(scanned) + " deduped=" + std::to_string(deduped) +
                         " fresh_buys=" + std::to_string(buys) + " stale_skipped=" + std::to_string(stale) +
                         " samples_taken=" + std::to_string(sampled) + age_info);
            }
        }

        std::this_thread::sleep_for(std::chrono::seconds(config.poll_interval_seconds));
    }
}
