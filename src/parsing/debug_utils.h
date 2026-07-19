#pragma once

#include <cstdint>
#include <optional>
#include <string>

#include <nlohmann/json.hpp>

#include "solana/pubkey.h"

namespace parsing {

// Diagnostic-only: lists the program IDs a getTransaction (jsonParsed)
// result actually invoked, so "nothing detected" can be told apart from
// "detected but not a venue we decode yet" (e.g. Jupiter/Raydium routing
// instead of calling pump.fun directly).
std::string extract_program_ids(const nlohmann::json& tx_result);

// Total fee actually paid for this transaction, in lamports (base fee +
// priority fee combined) -- straight from meta.fee, ground truth for what
// landed.
std::optional<uint64_t> extract_total_fee_lamports(const nlohmann::json& tx_result);

// Priority fee rate in micro-lamports per compute unit, read from a
// ComputeBudget "SetComputeUnitPrice" instruction if the transaction
// includes one (nullopt if absent, which just means the sender paid no
// priority fee at all). This is what's actually comparable across
// transactions with different compute-unit totals -- unlike total fee,
// which scales with how much compute a transaction used.
std::optional<uint64_t> extract_priority_fee_micro_lamports(const nlohmann::json& tx_result);

// Ground-truth lamport balance change for `wallet` in this transaction,
// found by matching its pubkey in accountKeys and diffing
// meta.preBalances/postBalances at that index. Positive = wallet gained
// lamports (a sell), negative = wallet spent lamports (a buy) -- includes
// the ~5000 lamport network fee folded in as minor, usually-negligible
// noise. nullopt if the wallet isn't found in this transaction's accounts.
std::optional<int64_t> extract_wallet_sol_delta(const nlohmann::json& tx_result, const solana::Pubkey& wallet);

} // namespace parsing
