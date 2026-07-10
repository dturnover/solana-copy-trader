#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <unordered_map>

#include "parsing/trade_event.h"
#include "solana/pubkey.h"

// Forward declaration -- avoids leaking the generated protobuf header into
// every file that includes tx_parser.h. Only tx_parser.cpp needs geyser.pb.h.
namespace geyser {
class SubscribeUpdateTransaction;
}

namespace parsing {

class TxParser {
public:
    explicit TxParser(std::unordered_map<solana::Pubkey, std::string, solana::PubkeyHash> tracked_wallets);

    // Returns a decoded TradeEvent if this transaction is a classifiable
    // buy/sell by one of the tracked wallets on a known venue. Returns
    // nullopt for everything else -- including partially-matched or
    // unrecognized instructions. Per the project's risk policy, an
    // unclassified signal is dropped, never guessed at.
    std::optional<TradeEvent> parse(const geyser::SubscribeUpdateTransaction& update,
                                     int64_t detected_at_micros);

private:
    std::unordered_map<solana::Pubkey, std::string, solana::PubkeyHash> tracked_wallets_;
};

} // namespace parsing
