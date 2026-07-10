#pragma once

#include <cstdint>
#include <string>

#include "solana/pubkey.h"

namespace parsing {

enum class Venue { PumpFunBondingCurve, PumpSwap, RaydiumAmmV4 };
enum class Direction { Buy, Sell };

struct TradeEvent {
    Venue venue = Venue::PumpFunBondingCurve;
    Direction direction = Direction::Buy;

    solana::Pubkey wallet;
    std::string wallet_label;
    solana::Pubkey mint;
    solana::Pubkey bonding_curve; // pump.fun venue only -- for reading live reserves post-detection

    // Raw values straight from the instruction args -- venue-specific
    // meaning (e.g. pump.fun buy: amount=exact token amount out,
    // sol_amount=max_sol_cost bound, NOT necessarily the actual fill price).
    uint64_t token_amount = 0;
    uint64_t sol_amount = 0;

    uint64_t slot = 0;
    std::string signature_base58;

    int64_t detected_at_micros = 0; // when the Geyser update was received
    int64_t parsed_at_micros = 0;   // when parsing/classification completed
};

const char* to_string(Venue v);
const char* to_string(Direction d);

} // namespace parsing
