#include "solana/pda.h"

#include <array>
#include <memory>
#include <string_view>

#include <openssl/bn.h>
#include <openssl/sha.h>

namespace solana {

namespace {

using BnPtr = std::unique_ptr<BIGNUM, decltype(&BN_free)>;
using CtxPtr = std::unique_ptr<BN_CTX, decltype(&BN_CTX_free)>;

BnPtr bn() { return BnPtr(BN_new(), &BN_free); }

// Is `h` the compressed encoding of a point on edwards25519? Decompression
// needs x^2 = (y^2 - 1) / (d*y^2 + 1) mod p to be a square (or zero).
bool is_on_curve(const std::array<uint8_t, 32>& h) {
    CtxPtr ctx(BN_CTX_new(), &BN_CTX_free);
    BnPtr p = bn(), d = bn(), y = bn(), y2 = bn(), u = bn(), v = bn(), vinv = bn(), x2 = bn(), e = bn(),
          leg = bn(), tmp = bn();

    // p = 2^255 - 19
    BN_set_bit(p.get(), 255);
    BN_sub_word(p.get(), 19);
    // d = -121665 / 121666 mod p
    BN_set_word(tmp.get(), 121666);
    BN_mod_inverse(d.get(), tmp.get(), p.get(), ctx.get());
    BN_set_word(tmp.get(), 121665);
    BN_mod_mul(d.get(), d.get(), tmp.get(), p.get(), ctx.get());
    BN_sub(d.get(), p.get(), d.get());

    std::array<uint8_t, 32> le = h;
    le[31] &= 0x7f; // top bit is the sign of x, not part of y
    BN_lebin2bn(le.data(), static_cast<int>(le.size()), y.get());
    if (BN_cmp(y.get(), p.get()) >= 0) return false;

    BN_mod_sqr(y2.get(), y.get(), p.get(), ctx.get());
    BN_copy(u.get(), y2.get());
    BN_sub_word(u.get(), 1);                                   // y^2 - 1 (y2 < p, may go to -1)
    BN_nnmod(u.get(), u.get(), p.get(), ctx.get());
    BN_mod_mul(v.get(), d.get(), y2.get(), p.get(), ctx.get());
    BN_add_word(v.get(), 1);
    BN_nnmod(v.get(), v.get(), p.get(), ctx.get());
    if (!BN_mod_inverse(vinv.get(), v.get(), p.get(), ctx.get())) return false;
    BN_mod_mul(x2.get(), u.get(), vinv.get(), p.get(), ctx.get());
    if (BN_is_zero(x2.get())) return true;

    // Euler's criterion: x2^((p-1)/2) == 1 iff x2 is a nonzero square.
    BN_copy(e.get(), p.get());
    BN_sub_word(e.get(), 1);
    BN_rshift1(e.get(), e.get());
    BN_mod_exp(leg.get(), x2.get(), e.get(), p.get(), ctx.get());
    return BN_is_one(leg.get());
}

} // namespace

std::optional<Pubkey> find_program_address(const std::vector<std::vector<uint8_t>>& seeds,
                                           const Pubkey& program_id) {
    static constexpr std::string_view kMarker = "ProgramDerivedAddress";
    for (int bump = 255; bump >= 0; --bump) {
        // One-shot SHA256(): the Init/Update/Final API is deprecated in OpenSSL 3.
        std::vector<uint8_t> buf;
        for (const auto& s : seeds) buf.insert(buf.end(), s.begin(), s.end());
        buf.push_back(static_cast<uint8_t>(bump));
        buf.insert(buf.end(), program_id.bytes().begin(), program_id.bytes().end());
        buf.insert(buf.end(), kMarker.begin(), kMarker.end());
        std::array<uint8_t, 32> h{};
        SHA256(buf.data(), buf.size(), h.data());
        if (!is_on_curve(h)) return Pubkey(h);
    }
    return std::nullopt;
}

} // namespace solana
