// Measures how much a hypothetical buy's price degrades between detecting a
// tracked wallet's pump.fun buy and executing some milliseconds later --
// i.e. the actual cost of copy-trading lag, using live bonding-curve
// reserves rather than theorizing about it. This is deliberately a separate
// tool from copytrader: it's a research/validation instrument, not part of
// the live trading path, and its output should inform whether paying for
// the real-time gRPC engine (and eventually live execution) is worth it.
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <numeric>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#include "config.h"
#include "parsing/debug_utils.h"
#include "parsing/tx_parser_json.h"
#include "parsing/venue_pumpfun.h"
#include "rpc/rpc_client.h"
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

struct LagStats {
    std::vector<double> pct_price_change; // positive = price got worse for a buyer
};

void report_running_average(int lag_ms, const LagStats& stats) {
    double sum = std::accumulate(stats.pct_price_change.begin(), stats.pct_price_change.end(), 0.0);
    double mean = sum / static_cast<double>(stats.pct_price_change.size());
    LOG_INFO("  lag~" + std::to_string(lag_ms) + "ms: n=" + std::to_string(stats.pct_price_change.size()) +
             " running_avg_price_change=" + std::to_string(mean) + "%");
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

    std::string scenarios_str;
    for (int ms : lag_scenarios_ms) scenarios_str += std::to_string(ms) + "ms ";
    LOG_INFO("Lag-cost experiment: hypothetical order size " + std::to_string(sol_in) +
             " SOL, lag scenarios: " + scenarios_str);
    LOG_INFO("Tracking " + std::to_string(config.tracked_wallets.size()) + " wallet(s) for pump.fun buys only.");

    rpc::RpcClient client(config.rpc_endpoint);
    std::unordered_map<solana::Pubkey, std::string, solana::PubkeyHash> last_seen_signature;
    std::unordered_map<int, LagStats> stats_by_lag;

    while (true) {
        for (const auto& wallet : config.tracked_wallets) {
            std::string address = wallet.pubkey.to_base58();
            std::string until;
            auto seen_it = last_seen_signature.find(wallet.pubkey);
            if (seen_it != last_seen_signature.end()) until = seen_it->second;

            std::vector<rpc::SignatureInfo> new_sigs;
            try {
                new_sigs = client.get_signatures_for_address(address, until, 20);
            } catch (const std::exception& e) {
                LOG_WARN("Poll failed for " + wallet.label + ": " + e.what());
                continue;
            }

            if (!new_sigs.empty()) {
                LOG_DEBUG("Found " + std::to_string(new_sigs.size()) + " new signature(s) for " + wallet.label);
            }

            for (const auto& sig_info : new_sigs) {
                last_seen_signature[wallet.pubkey] = sig_info.signature;
                if (sig_info.has_error) continue;

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
                if (!trade) {
                    LOG_DEBUG("sig=" + sig_info.signature + " matched no known venue -- programs invoked: [" +
                              parsing::extract_program_ids(*tx_result) + "]");
                    continue;
                }
                if (trade->direction != parsing::Direction::Buy) {
                    LOG_DEBUG("sig=" + sig_info.signature + " was a pump.fun SELL -- skipping (this experiment "
                              "only measures buy-side lag cost for now)");
                    continue;
                }

                int64_t on_chain_age_ms = -1;
                if (tx_result->contains("blockTime") && (*tx_result)["blockTime"].is_number()) {
                    int64_t block_time_s = (*tx_result)["blockTime"].get<int64_t>();
                    int64_t now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                                         std::chrono::system_clock::now().time_since_epoch())
                                         .count();
                    on_chain_age_ms = now_ms - block_time_s * 1000;
                }

                std::string bonding_curve_b58 = trade->bonding_curve.to_base58();
                auto baseline_bytes = client.get_account_info(bonding_curve_b58);
                if (!baseline_bytes) {
                    LOG_WARN("Could not read bonding curve account for mint=" + trade->mint.to_base58() +
                             " -- skipping sample");
                    continue;
                }
                auto baseline_state = parsing::pumpfun::decode_bonding_curve(*baseline_bytes);
                if (!baseline_state) {
                    LOG_WARN("Bonding curve account for mint=" + trade->mint.to_base58() +
                             " didn't match the expected layout -- the assumed account index (3) may be "
                             "wrong for this transaction, skipping sample");
                    continue;
                }

                double baseline_price =
                    simulate_effective_price(baseline_state->virtual_sol_reserves, baseline_state->virtual_token_reserves, sol_in);
                if (baseline_price <= 0) {
                    LOG_WARN("Could not simulate a baseline price for mint=" + trade->mint.to_base58() +
                             " (drained/invalid reserves?) -- skipping sample");
                    continue;
                }

                LOG_INFO(wallet.label + " BUY detected mint=" + trade->mint.to_base58() +
                         " on_chain_age_ms=" + std::to_string(on_chain_age_ms) +
                         " baseline_price_lamports_per_token=" + std::to_string(baseline_price));

                int64_t baseline_us = util::now_micros();
                for (int target_lag_ms : lag_scenarios_ms) {
                    int64_t target_us = baseline_us + static_cast<int64_t>(target_lag_ms) * 1000;
                    int64_t now_us = util::now_micros();
                    if (target_us > now_us) {
                        std::this_thread::sleep_for(std::chrono::microseconds(target_us - now_us));
                    }

                    auto later_bytes = client.get_account_info(bonding_curve_b58);
                    if (!later_bytes) continue;
                    auto later_state = parsing::pumpfun::decode_bonding_curve(*later_bytes);
                    if (!later_state) continue;

                    double later_price =
                        simulate_effective_price(later_state->virtual_sol_reserves, later_state->virtual_token_reserves, sol_in);
                    if (later_price <= 0) continue;

                    int64_t actual_elapsed_ms = (util::now_micros() - baseline_us) / 1000;
                    double pct_change = (later_price - baseline_price) / baseline_price * 100.0;

                    stats_by_lag[target_lag_ms].pct_price_change.push_back(pct_change);
                    LOG_INFO("  target_lag=" + std::to_string(target_lag_ms) +
                             "ms actual_elapsed=" + std::to_string(actual_elapsed_ms) +
                             "ms price_change=" + std::to_string(pct_change) + "%");
                    report_running_average(target_lag_ms, stats_by_lag[target_lag_ms]);
                }
            }
        }

        std::this_thread::sleep_for(std::chrono::seconds(config.poll_interval_seconds));
    }
}
