#include "parsing/tx_parser_json.h"

#include <vector>

#include "parsing/venue_pumpfun.h"
#include "solana/base58.h"
#include "util/time.h"

namespace parsing {

namespace {

// Returns false for "parsed" (known-program, e.g. system/token) instruction
// shapes, which never apply to pump.fun/PumpSwap/Raydium since those aren't
// programs the RPC's jsonParsed encoding knows how to decode -- only the
// raw {programId, accounts, data} shape is relevant here.
bool decode_instruction(const nlohmann::json& ix, solana::Pubkey& program_id, std::vector<solana::Pubkey>& accounts,
                         std::vector<uint8_t>& data) {
    if (!ix.contains("programId") || !ix.contains("accounts") || !ix.contains("data")) {
        return false;
    }
    if (!ix["data"].is_string()) return false;
    if (!solana::Pubkey::from_base58(ix["programId"].get<std::string>(), program_id)) return false;

    accounts.clear();
    for (const auto& acc : ix["accounts"]) {
        solana::Pubkey pk;
        if (acc.is_string() && solana::Pubkey::from_base58(acc.get<std::string>(), pk)) {
            accounts.push_back(pk);
        }
    }

    return solana::base58_decode(ix["data"].get<std::string>(), data);
}

} // namespace

std::optional<TradeEvent> parse_json_transaction(const nlohmann::json& tx_result, const solana::Pubkey& wallet,
                                                  const std::string& wallet_label,
                                                  const std::string& signature_base58, int64_t detected_at_micros) {
    if (!tx_result.contains("transaction") || !tx_result["transaction"].contains("message")) {
        return std::nullopt;
    }
    const auto& message = tx_result["transaction"]["message"];
    if (!message.contains("instructions")) return std::nullopt;

    std::vector<nlohmann::json> all_ixs;
    for (const auto& ix : message["instructions"]) {
        all_ixs.push_back(ix);
    }
    if (tx_result.contains("meta") && tx_result["meta"].contains("innerInstructions")) {
        for (const auto& inner : tx_result["meta"]["innerInstructions"]) {
            if (!inner.contains("instructions")) continue;
            for (const auto& ix : inner["instructions"]) {
                all_ixs.push_back(ix);
            }
        }
    }

    for (const auto& ix : all_ixs) {
        solana::Pubkey program_id;
        std::vector<solana::Pubkey> accounts;
        std::vector<uint8_t> data;
        if (!decode_instruction(ix, program_id, accounts, data)) continue;

        if (program_id == pumpfun::kProgramId) {
            auto decoded = pumpfun::try_decode(data, accounts);
            if (!decoded) continue;

            TradeEvent event;
            event.venue = Venue::PumpFunBondingCurve;
            event.direction = decoded->direction;
            event.wallet = wallet;
            event.wallet_label = wallet_label;
            event.mint = decoded->mint;
            event.bonding_curve = decoded->bonding_curve;
            event.token_amount = decoded->amount;
            event.sol_amount = decoded->sol_bound;
            event.slot = tx_result.value("slot", 0ull);
            event.signature_base58 = signature_base58;
            event.detected_at_micros = detected_at_micros;
            event.parsed_at_micros = util::now_micros();
            return event;
        }
        // PumpSwap / Raydium decoders are added in later phases (Phase 3).
    }

    return std::nullopt;
}

} // namespace parsing
