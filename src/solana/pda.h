#pragma once

#include <optional>
#include <string>
#include <vector>

#include "solana/pubkey.h"

namespace solana {

// Solana's find_program_address: the first bump from 255 down whose
// sha256(seeds || bump || program_id || "ProgramDerivedAddress") is NOT a
// valid ed25519 point. Exact -- the same derivation the chain itself uses.
std::optional<Pubkey> find_program_address(const std::vector<std::vector<uint8_t>>& seeds,
                                           const Pubkey& program_id);

} // namespace solana
