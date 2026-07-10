#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <string>

namespace solana {

class Pubkey {
public:
    static constexpr size_t kSize = 32;

    Pubkey() = default;
    explicit Pubkey(const std::array<uint8_t, kSize>& bytes) : bytes_(bytes) {}

    // Parses a base58-encoded pubkey string. Returns false (leaving `out`
    // untouched) on malformed input rather than throwing -- config loading is
    // the main caller and wants to report a clean error, not crash.
    static bool from_base58(const std::string& s, Pubkey& out);

    // `data` must point to at least kSize readable bytes.
    static Pubkey from_bytes(const uint8_t* data);

    std::string to_base58() const;
    const std::array<uint8_t, kSize>& bytes() const { return bytes_; }

    bool operator==(const Pubkey& other) const { return bytes_ == other.bytes_; }
    bool operator!=(const Pubkey& other) const { return !(*this == other); }
    bool operator<(const Pubkey& other) const { return bytes_ < other.bytes_; }

private:
    std::array<uint8_t, kSize> bytes_{};
};

// Pubkeys are ed25519 curve points / PDA hash outputs, i.e. already
// uniformly distributed -- a plain FNV-1a over the raw bytes is sufficient
// and avoids pulling in a hashing library just for an unordered_map key.
struct PubkeyHash {
    size_t operator()(const Pubkey& pk) const noexcept {
        size_t h = 1469598103934665603ull;
        for (uint8_t b : pk.bytes()) {
            h ^= b;
            h *= 1099511628211ull;
        }
        return h;
    }
};

} // namespace solana
