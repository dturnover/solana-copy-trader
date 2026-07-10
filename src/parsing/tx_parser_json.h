#pragma once

#include <cstdint>
#include <optional>
#include <string>

#include <nlohmann/json.hpp>

#include "parsing/trade_event.h"
#include "solana/pubkey.h"

namespace parsing {

// Parses a Solana JSON-RPC getTransaction result (encoding=jsonParsed) into a
// TradeEvent, reusing the same venue decoders (venue_pumpfun.cpp) as the
// protobuf-based geyser path in tx_parser.cpp -- only the wire-format
// adaptation differs between the two ingestion engines.
//
// Unlike the geyser path, the caller already knows which tracked wallet this
// transaction belongs to (the polling engine fetches signatures per-wallet
// via getSignaturesForAddress), so it's passed in directly rather than
// re-derived from the transaction's signer list.
std::optional<TradeEvent> parse_json_transaction(const nlohmann::json& tx_result, const solana::Pubkey& wallet,
                                                  const std::string& wallet_label,
                                                  const std::string& signature_base58, int64_t detected_at_micros);

} // namespace parsing
