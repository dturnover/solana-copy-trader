#include "parsing/trade_event.h"

namespace parsing {

const char* to_string(Venue v) {
    switch (v) {
        case Venue::PumpFunBondingCurve: return "pumpfun";
        case Venue::PumpSwap: return "pumpswap";
        case Venue::RaydiumAmmV4: return "raydium_v4";
    }
    return "unknown_venue";
}

const char* to_string(Direction d) {
    switch (d) {
        case Direction::Buy: return "buy";
        case Direction::Sell: return "sell";
    }
    return "unknown_direction";
}

} // namespace parsing
