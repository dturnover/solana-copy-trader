#pragma once

#include <string>
#include <vector>

#include "solana/pubkey.h"

namespace app {

struct TrackedWalletConfig {
    std::string label;
    solana::Pubkey pubkey;
};

struct AppConfig {
    // "poll" (free, seconds-latency, via plain RPC) or "geyser" (paid,
    // sub-second, via Yellowstone gRPC streaming). Same TradeEvent/callback
    // shape either way -- this is the only thing that decides which engine
    // main.cpp wires up.
    std::string engine = "poll";

    std::string geyser_endpoint; // required if engine == "geyser"
    std::string geyser_x_token;  // required if engine == "geyser"

    std::string rpc_endpoint; // required if engine == "poll", also used by lag_experiment
    int poll_interval_seconds = 5;

    // lag_experiment tool only: how many milliseconds of simulated execution
    // lag to test, and what hypothetical SOL order size to price against
    // live bonding-curve reserves.
    std::vector<int> lag_scenarios_ms = {500, 2000};
    double lag_experiment_sol_in = 0.5;

    std::vector<TrackedWalletConfig> tracked_wallets;
};

// Loads and validates config from a JSON file (see config/config.example.json
// for the shape). Throws std::runtime_error with a descriptive message on any
// parse/validation failure -- fail loudly at startup rather than silently
// running with a misconfigured wallet list or missing credentials.
AppConfig load_config(const std::string& path);

} // namespace app
