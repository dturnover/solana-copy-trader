#include "solana/base64.h"

#include <array>

namespace solana {

namespace {

constexpr int8_t kInvalid = -1;

std::array<int8_t, 256> build_decode_table() {
    std::array<int8_t, 256> table{};
    table.fill(kInvalid);
    const char* alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    for (int i = 0; i < 64; ++i) {
        table[static_cast<unsigned char>(alphabet[i])] = static_cast<int8_t>(i);
    }
    return table;
}

} // namespace

std::vector<uint8_t> base64_decode(const std::string& encoded) {
    static const std::array<int8_t, 256> table = build_decode_table();

    std::vector<uint8_t> out;
    out.reserve(encoded.size() / 4 * 3);

    int value = 0;
    int bits = -8;
    for (unsigned char c : encoded) {
        if (c == '=' || c == '\n' || c == '\r') continue;
        int8_t decoded = table[c];
        if (decoded == kInvalid) continue;

        value = (value << 6) + decoded;
        bits += 6;
        if (bits >= 0) {
            out.push_back(static_cast<uint8_t>((value >> bits) & 0xFF));
            bits -= 8;
        }
    }
    return out;
}

} // namespace solana
