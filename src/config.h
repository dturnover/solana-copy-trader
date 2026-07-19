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

    // Firehose mode: instead of tracked wallets, poll the pump.fun program
    // itself and sample ANY buy as a lag-cost data point. Lag cost doesn't
    // depend on who traded -- only on how the curve moves afterward -- so
    // this yields orders of magnitude more samples than waiting on specific
    // wallets, and fresher ones (see lag_max_tx_age_ms).
    bool lag_firehose = false;
    // Skip transactions older than this (per blockTime) so the baseline
    // reserve read still approximates the state right after the trade.
    // 0 disables the filter.
    int lag_max_tx_age_ms = 0;
    // Append one row per sample here for offline analysis. Empty disables.
    std::string lag_csv_path;

    // paper_trade tool only: always uses tracked_wallets (not firehose) --
    // "is this wallet profitable, and would copying it at our assumed
    // execution lag still be profitable" is inherently a per-wallet
    // question. execution_lag_ms is the single assumed lag applied to both
    // the entry and exit simulation.
    int64_t paper_trade_execution_lag_ms = 1500;
    std::string paper_trade_csv_path;
    int paper_trade_position_timeout_minutes = 180;

    std::vector<TrackedWalletConfig> tracked_wallets;
};

// Loads and validates config from a JSON file (see config/config.example.json
// for the shape). Throws std::runtime_error with a descriptive message on any
// parse/validation failure -- fail loudly at startup rather than silently
// running with a misconfigured wallet list or missing credentials.
AppConfig load_config(const std::string& path);

} // namespace app
