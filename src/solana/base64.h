#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace solana {

// Standard base64 decode -- needed for getAccountInfo's "base64" encoding
// option (the only reliable encoding for account data over ~128 bytes;
// Solana's RPC rejects "base58" encoding above that size).
std::vector<uint8_t> base64_decode(const std::string& encoded);

} // namespace solana
