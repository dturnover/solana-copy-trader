#pragma once

#include <functional>
#include <string>
#include <vector>

#include "parsing/trade_event.h"
#include "solana/pubkey.h"

namespace geyser_client {

struct TrackedWallet {
    solana::Pubkey pubkey;
    std::string label;
};

struct Config {
    std::string endpoint; // e.g. "your-shyft-endpoint.example.com:443"
    std::string x_token;  // provider auth token, sent as "x-token" gRPC metadata
    std::vector<TrackedWallet> tracked_wallets;
};

using TradeCallback = std::function<void(const parsing::TradeEvent&)>;

// Blocking: connects, subscribes to transactions naming any tracked wallet,
// and invokes on_trade for each classified buy/sell until the process exits.
// Reconnects with exponential backoff on stream drops -- this is expected to
// run for the process lifetime, not a single call-and-return.
void run(const Config& config, TradeCallback on_trade);

} // namespace geyser_client
