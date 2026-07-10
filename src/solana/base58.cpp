#include "solana/base58.h"

#include <array>

namespace solana {

namespace {

constexpr char kAlphabet[] = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";

int8_t decode_char(unsigned char c) {
    static const std::array<int8_t, 256> table = [] {
        std::array<int8_t, 256> t{};
        t.fill(-1);
        for (int i = 0; i < 58; ++i) {
            t[static_cast<unsigned char>(kAlphabet[i])] = static_cast<int8_t>(i);
        }
        return t;
    }();
    return table[c];
}

} // namespace

std::string base58_encode(const uint8_t* data, size_t len) {
    size_t zeros = 0;
    while (zeros < len && data[zeros] == 0) ++zeros;

    // log(256)/log(58) ~= 1.365, +1 for rounding slack.
    std::vector<uint8_t> b58((len - zeros) * 138 / 100 + 1, 0);
    size_t length = 0;

    for (size_t i = zeros; i < len; ++i) {
        int carry = data[i];
        size_t j = 0;
        for (auto it = b58.rbegin(); (carry != 0 || j < length) && it != b58.rend(); ++it, ++j) {
            carry += 256 * static_cast<int>(*it);
            *it = static_cast<uint8_t>(carry % 58);
            carry /= 58;
        }
        length = j;
    }

    auto it = b58.begin() + static_cast<long>(b58.size() - length);
    while (it != b58.end() && *it == 0) ++it;

    std::string result;
    result.reserve(zeros + static_cast<size_t>(b58.end() - it));
    result.append(zeros, '1');
    for (; it != b58.end(); ++it) {
        result.push_back(kAlphabet[*it]);
    }
    return result;
}

bool base58_decode(const std::string& s, std::vector<uint8_t>& out) {
    size_t zeros = 0;
    while (zeros < s.size() && s[zeros] == '1') ++zeros;

    // log(58)/log(256) ~= 0.733, +1 for rounding slack.
    std::vector<uint8_t> b256((s.size() - zeros) * 733 / 1000 + 1, 0);
    size_t length = 0;

    for (size_t i = zeros; i < s.size(); ++i) {
        int8_t val = decode_char(static_cast<unsigned char>(s[i]));
        if (val < 0) return false;

        int carry = val;
        size_t j = 0;
        for (auto it = b256.rbegin(); (carry != 0 || j < length) && it != b256.rend(); ++it, ++j) {
            carry += 58 * static_cast<int>(*it);
            *it = static_cast<uint8_t>(carry % 256);
            carry /= 256;
        }
        length = j;
    }

    auto it = b256.begin() + static_cast<long>(b256.size() - length);
    while (it != b256.end() && *it == 0) ++it;

    out.clear();
    out.reserve(zeros + static_cast<size_t>(b256.end() - it));
    out.insert(out.end(), zeros, 0);
    out.insert(out.end(), it, b256.end());
    return true;
}

} // namespace solana
