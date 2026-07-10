#include "rpc/poll_client.h"

#include <chrono>
#include <stdexcept>
#include <thread>
#include <unordered_map>

#include "parsing/debug_utils.h"
#include "parsing/tx_parser_json.h"
#include "rpc/rpc_client.h"
#include "util/logging.h"
#include "util/time.h"

namespace poll_client {

void run(const Config& config, TradeCallback on_trade) {
    rpc::RpcClient client(config.rpc_endpoint);

    // Tracks the newest signature already processed per wallet, so each poll
    // only asks the RPC for what's new since last time (via the `until`
    // param) instead of re-fetching and re-filtering a fixed window.
    std::unordered_map<solana::Pubkey, std::string, solana::PubkeyHash> last_seen_signature;

    LOG_INFO("Polling " + std::to_string(config.tracked_wallets.size()) + " tracked wallet(s) every " +
             std::to_string(config.poll_interval_seconds) + "s via " + config.rpc_endpoint);

    while (true) {
        for (const auto& wallet : config.tracked_wallets) {
            std::string address = wallet.pubkey.to_base58();

            std::string until;
            auto seen_it = last_seen_signature.find(wallet.pubkey);
            if (seen_it != last_seen_signature.end()) {
                until = seen_it->second;
            }

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
                if (sig_info.has_error) continue; // failed transactions aren't trades

                int64_t detected_at = util::now_micros();
                std::optional<nlohmann::json> tx_result;
                try {
                    tx_result = client.get_transaction(sig_info.signature);
                } catch (const std::exception& e) {
                    LOG_WARN("getTransaction failed for " + sig_info.signature + ": " + e.what());
                    continue;
                }
                if (!tx_result) continue; // not yet available at this commitment level

                auto trade = parsing::parse_json_transaction(*tx_result, wallet.pubkey, wallet.label,
                                                              sig_info.signature, detected_at);
                if (trade) {
                    on_trade(*trade);
                } else {
                    LOG_DEBUG("sig=" + sig_info.signature + " matched no known venue -- programs invoked: [" +
                              parsing::extract_program_ids(*tx_result) + "]");
                }
            }
        }

        std::this_thread::sleep_for(std::chrono::seconds(config.poll_interval_seconds));
    }
}

} // namespace poll_client
