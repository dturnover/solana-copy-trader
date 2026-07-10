#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace solana {

// Bitcoin-alphabet base58 (same alphabet Solana uses for pubkeys/keypairs).
// No maintained vcpkg port exists for this, so it's vendored here rather than
// pulled in as a dependency.
std::string base58_encode(const uint8_t* data, size_t len);
bool base58_decode(const std::string& s, std::vector<uint8_t>& out);

} // namespace solana
