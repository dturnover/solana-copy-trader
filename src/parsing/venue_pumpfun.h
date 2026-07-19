#pragma once

#include <cstdint>
#include <optional>
#include <vector>

#include "parsing/trade_event.h"
#include "solana/pubkey.h"

// Pump.fun bonding-curve buy/sell decoding.
//
// Program ID and discriminators below were cross-checked against two
// independent sources during planning and are high-confidence. The mint
// account index (kMintAccountIndex) is lower-confidence: pump.fun's account
// list has grown over time (a 2025 update appended several rewards/fee
// accounts to `buy`), and while every source agreed the first three accounts
// are always [global, fee_recipient, mint], this has NOT been re-verified
// against a live on-chain IDL as of writing. If tx_parser's cross-check
// against pre/post token balances (see tx_parser.cpp) ever disagrees with
// the mint this file extracts, trust the token-balance-derived mint and
// re-verify this index against current pump-fun/pump-public-docs.
namespace parsing::pumpfun {

extern const solana::Pubkey kProgramId; // 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P

struct DecodedInstruction {
    parsing::Direction direction;
    uint64_t amount = 0;    // buy: exact token amount out. sell: exact token amount in.
    uint64_t sol_bound = 0; // buy: max_sol_cost. sell: min_sol_output. (lamports)
    solana::Pubkey mint;
    solana::Pubkey bonding_curve; // accounts[3] -- same confidence caveat as kMintAccountIndex above
};

// `data` is the raw instruction data (discriminator + borsh-encoded args).
// `accounts` is this instruction's account list already resolved to Pubkeys,
// in on-chain order. Returns nullopt if the discriminator doesn't match a
// known pump.fun instruction, or if the data/account list is too short to be
// a valid buy/sell -- callers must never guess past a failed decode.
std::optional<DecodedInstruction> try_decode(const std::vector<uint8_t>& data,
                                              const std::vector<solana::Pubkey>& accounts);

// Bonding curve account state (for reading live reserves, e.g. to price a
// hypothetical trade). Account discriminator [23,183,248,55,96,216,172,96],
// verified against public IDL. The account grew from 49 to 256 bytes in a
// 2025 update that appended a `creator` pubkey and reserved space; this only
// reads the original 49-byte prefix (5 u64 reserves + a bool), which is
// still valid on the current layout -- the fields this decode cares about
// haven't moved.
struct BondingCurveState {
    uint64_t virtual_token_reserves = 0;
    uint64_t virtual_sol_reserves = 0;
    uint64_t real_token_reserves = 0;
    uint64_t real_sol_reserves = 0;
    uint64_t token_total_supply = 0;
    bool complete = false;
};

// Returns nullopt if the account is too short or the discriminator doesn't
// match -- e.g. if kMintAccountIndex/bonding_curve's assumed account index
// turns out to be wrong for a given transaction, this is how that gets
// caught rather than silently reading garbage.
std::optional<BondingCurveState> decode_bonding_curve(const std::vector<uint8_t>& account_data);

// Constant-product (x*y=k) pricing helpers against virtual reserves,
// ignoring the protocol fee -- fine for comparative/simulation purposes
// (paper trading, lag-cost estimation), not precise enough for building a
// real execution instruction later.

// SOL cost to acquire exactly `token_amount_out` tokens via a buy. Returns
// a negative value if the request would drain more tokens than the curve
// currently holds (invalid).
double simulate_buy_sol_cost(const BondingCurveState& state, double token_amount_out);

// SOL proceeds from selling exactly `token_amount_in` tokens via a sell.
double simulate_sell_sol_proceeds(const BondingCurveState& state, double token_amount_in);

} // namespace parsing::pumpfun
