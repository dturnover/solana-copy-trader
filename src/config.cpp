#include "config.h"

#include <fstream>
#include <stdexcept>

#include <nlohmann/json.hpp>

namespace app {

AppConfig load_config(const std::string& path) {
    std::ifstream file(path);
    if (!file.is_open()) {
        throw std::runtime_error("Could not open config file: " + path);
    }

    nlohmann::json j;
    try {
        file >> j;
    } catch (const std::exception& e) {
        throw std::runtime_error(std::string("Failed to parse config JSON: ") + e.what());
    }

    AppConfig config;
    if (j.contains("engine")) {
        config.engine = j["engine"].get<std::string>();
    }
    if (config.engine != "poll" && config.engine != "geyser") {
        throw std::runtime_error("config.json 'engine' must be \"poll\" or \"geyser\", got: " + config.engine);
    }

    if (config.engine == "geyser") {
        if (!j.contains("geyser") || !j["geyser"].contains("endpoint") || !j["geyser"].contains("x_token")) {
            throw std::runtime_error("config.json must contain geyser.endpoint and geyser.x_token when engine is \"geyser\"");
        }
        config.geyser_endpoint = j["geyser"]["endpoint"].get<std::string>();
        config.geyser_x_token = j["geyser"]["x_token"].get<std::string>();
    } else if (!j.contains("rpc") || !j["rpc"].contains("endpoint")) {
        throw std::runtime_error("config.json must contain rpc.endpoint when engine is \"poll\"");
    }

    // rpc.endpoint is parsed regardless of `engine` (not just when
    // required above) since the lag_experiment tool always needs it for
    // getAccountInfo/getSignaturesForAddress even if the main bot is
    // configured for the geyser engine.
    if (j.contains("rpc") && j["rpc"].contains("endpoint")) {
        config.rpc_endpoint = j["rpc"]["endpoint"].get<std::string>();
    }
    if (j.contains("poll_interval_seconds")) {
        config.poll_interval_seconds = j["poll_interval_seconds"].get<int>();
    }

    if (j.contains("lag_experiment")) {
        const auto& lag = j["lag_experiment"];
        if (lag.contains("lag_scenarios_ms") && lag["lag_scenarios_ms"].is_array()) {
            config.lag_scenarios_ms.clear();
            for (const auto& ms : lag["lag_scenarios_ms"]) {
                config.lag_scenarios_ms.push_back(ms.get<int>());
            }
        }
        if (lag.contains("hypothetical_sol_in")) {
            config.lag_experiment_sol_in = lag["hypothetical_sol_in"].get<double>();
        }
    }

    if (!j.contains("tracked_wallets") || !j["tracked_wallets"].is_array() ||
        j["tracked_wallets"].empty()) {
        throw std::runtime_error("config.json must contain a non-empty tracked_wallets array");
    }

    for (const auto& entry : j["tracked_wallets"]) {
        if (!entry.contains("label") || !entry.contains("pubkey")) {
            throw std::runtime_error("each tracked_wallets entry needs a label and a pubkey");
        }

        TrackedWalletConfig w;
        w.label = entry["label"].get<std::string>();
        std::string pubkey_str = entry["pubkey"].get<std::string>();
        if (!solana::Pubkey::from_base58(pubkey_str, w.pubkey)) {
            throw std::runtime_error("Invalid base58 pubkey for tracked wallet '" + w.label +
                                      "': " + pubkey_str);
        }
        config.tracked_wallets.push_back(std::move(w));
    }

    return config;
}

} // namespace app
