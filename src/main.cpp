#include <string>

#include "config.h"
#include "geyser/geyser_client.h"
#include "parsing/trade_event.h"
#include "rpc/poll_client.h"
#include "util/logging.h"

namespace {

// Shared by both engines so switching between them (via config's "engine"
// field) doesn't change what gets logged or how latency is measured.
void log_trade(const parsing::TradeEvent& trade) {
    int64_t latency_us = trade.parsed_at_micros - trade.detected_at_micros;
    LOG_INFO(trade.wallet_label + " " + parsing::to_string(trade.direction) + " on " +
             parsing::to_string(trade.venue) + " mint=" + trade.mint.to_base58() +
             " token_amount=" + std::to_string(trade.token_amount) +
             " sol_bound=" + std::to_string(trade.sol_amount) + " slot=" + std::to_string(trade.slot) +
             " sig=" + trade.signature_base58 + " parse_latency_us=" + std::to_string(latency_us));
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

    LOG_INFO("Loaded " + std::to_string(config.tracked_wallets.size()) + " tracked wallet(s):");
    for (const auto& w : config.tracked_wallets) {
        LOG_INFO("  " + w.label + " -> " + w.pubkey.to_base58());
    }

    // Phase 1: detection + logging only. No keypair, no execution -- this
    // validates signal quality and measures detection latency before any
    // capital is put at risk.
    if (config.engine == "geyser") {
        LOG_INFO("Engine: geyser (real-time gRPC streaming)");
        geyser_client::Config gconfig;
        gconfig.endpoint = config.geyser_endpoint;
        gconfig.x_token = config.geyser_x_token;
        for (const auto& w : config.tracked_wallets) {
            gconfig.tracked_wallets.push_back({w.pubkey, w.label});
        }
        geyser_client::run(gconfig, log_trade);
    } else {
        LOG_INFO("Engine: poll (free, seconds-latency -- validation only, not for live trading)");
        poll_client::Config pconfig;
        pconfig.rpc_endpoint = config.rpc_endpoint;
        pconfig.poll_interval_seconds = config.poll_interval_seconds;
        for (const auto& w : config.tracked_wallets) {
            pconfig.tracked_wallets.push_back({w.pubkey, w.label});
        }
        poll_client::run(pconfig, log_trade);
    }

    return 0;
}
