#include "solana/pubkey.h"

#include <algorithm>
#include <cstring>
#include <vector>

#include "solana/base58.h"

namespace solana {

bool Pubkey::from_base58(const std::string& s, Pubkey& out) {
    std::vector<uint8_t> decoded;
    if (!base58_decode(s, decoded)) return false;
    if (decoded.size() != kSize) return false;

    std::array<uint8_t, kSize> bytes{};
    std::copy(decoded.begin(), decoded.end(), bytes.begin());
    out = Pubkey(bytes);
    return true;
}

Pubkey Pubkey::from_bytes(const uint8_t* data) {
    std::array<uint8_t, kSize> bytes{};
    std::memcpy(bytes.data(), data, kSize);
    return Pubkey(bytes);
}

std::string Pubkey::to_base58() const {
    return base58_encode(bytes_.data(), bytes_.size());
}

} // namespace solana
