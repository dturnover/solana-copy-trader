#pragma once

#include <functional>
#include <string>
#include <vector>

#include "parsing/trade_event.h"
#include "solana/pubkey.h"

namespace poll_client {

struct TrackedWallet {
    solana::Pubkey pubkey;
    std::string label;
};

struct Config {
    std::string rpc_endpoint; // e.g. Shyft's free-tier REST endpoint with ?api_key=...
    std::vector<TrackedWallet> tracked_wallets;
    int poll_interval_seconds = 5;
};

using TradeCallback = std::function<void(const parsing::TradeEvent&)>;

// Blocking, $0 stand-in for geyser_client::run: polls
// getSignaturesForAddress per tracked wallet on a fixed interval instead of
// streaming in real time. Multi-second detection latency instead of
// sub-second -- good enough to validate the whole detection/parsing
// pipeline and a wallet's actual activity before paying for real-time
// Geyser gRPC access. Emits the same TradeEvent shape via the same callback
// signature as geyser_client::run, so main.cpp can swap between the two
// engines purely via config.
void run(const Config& config, TradeCallback on_trade);

} // namespace poll_client
