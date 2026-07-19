#include "parsing/venue_pumpfun.h"

#include <algorithm>
#include <array>

namespace parsing::pumpfun {

namespace {

constexpr std::array<uint8_t, 8> kBuyDiscriminator = {102, 6, 61, 18, 1, 218, 235, 234};
constexpr std::array<uint8_t, 8> kSellDiscriminator = {51, 230, 133, 164, 1, 127, 131, 173};
constexpr std::array<uint8_t, 8> kBondingCurveDiscriminator = {23, 183, 248, 55, 96, 216, 172, 96};
constexpr size_t kMintAccountIndex = 2;         // [global, fee_recipient, mint, ...] -- see header comment
constexpr size_t kBondingCurveAccountIndex = 3; // [global, fee_recipient, mint, bonding_curve, ...]

uint64_t read_u64_le(const uint8_t* p) {
    uint64_t v = 0;
    for (int i = 7; i >= 0; --i) {
        v = (v << 8) | p[i];
    }
    return v;
}

bool starts_with(const std::vector<uint8_t>& data, const std::array<uint8_t, 8>& disc) {
    if (data.size() < disc.size()) return false;
    return std::equal(disc.begin(), disc.end(), data.begin());
}

} // namespace

const solana::Pubkey kProgramId = [] {
    solana::Pubkey pk;
    solana::Pubkey::from_base58("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P", pk);
    return pk;
}();

std::optional<DecodedInstruction> try_decode(const std::vector<uint8_t>& data,
                                              const std::vector<solana::Pubkey>& accounts) {
    // 8-byte discriminator + amount:u64 + sol bound:u64.
    if (data.size() < 8 + 8 + 8) return std::nullopt;

    parsing::Direction direction;
    if (starts_with(data, kBuyDiscriminator)) {
        direction = parsing::Direction::Buy;
    } else if (starts_with(data, kSellDiscriminator)) {
        direction = parsing::Direction::Sell;
    } else {
        return std::nullopt;
    }

    if (accounts.size() <= kMintAccountIndex) return std::nullopt;

    DecodedInstruction out;
    out.direction = direction;
    out.amount = read_u64_le(data.data() + 8);
    out.sol_bound = read_u64_le(data.data() + 16);
    out.mint = accounts[kMintAccountIndex];
    if (accounts.size() > kBondingCurveAccountIndex) {
        out.bonding_curve = accounts[kBondingCurveAccountIndex];
    }
    return out;
}

std::optional<BondingCurveState> decode_bonding_curve(const std::vector<uint8_t>& account_data) {
    // disc(8) + 5x u64(40) + bool(1) = 49 bytes minimum, still valid on the
    // current (grown to 256 byte) layout since new fields were appended, not
    // inserted before these.
    if (account_data.size() < 49) return std::nullopt;
    if (!std::equal(kBondingCurveDiscriminator.begin(), kBondingCurveDiscriminator.end(), account_data.begin())) {
        return std::nullopt;
    }

    BondingCurveState state;
    state.virtual_token_reserves = read_u64_le(account_data.data() + 8);
    state.virtual_sol_reserves = read_u64_le(account_data.data() + 16);
    state.real_token_reserves = read_u64_le(account_data.data() + 24);
    state.real_sol_reserves = read_u64_le(account_data.data() + 32);
    state.token_total_supply = read_u64_le(account_data.data() + 40);
    state.complete = account_data[48] != 0;
    return state;
}

double simulate_buy_sol_cost(const BondingCurveState& state, double token_amount_out) {
    double v_sol = static_cast<double>(state.virtual_sol_reserves);
    double v_tok = static_cast<double>(state.virtual_token_reserves);
    if (token_amount_out <= 0 || token_amount_out >= v_tok) return -1.0;
    double new_tok = v_tok - token_amount_out;
    double new_sol = (v_sol * v_tok) / new_tok;
    return new_sol - v_sol;
}

double simulate_sell_sol_proceeds(const BondingCurveState& state, double token_amount_in) {
    double v_sol = static_cast<double>(state.virtual_sol_reserves);
    double v_tok = static_cast<double>(state.virtual_token_reserves);
    if (token_amount_in <= 0) return -1.0;
    double new_tok = v_tok + token_amount_in;
    double new_sol = (v_sol * v_tok) / new_tok;
    return v_sol - new_sol;
}

} // namespace parsing::pumpfun
