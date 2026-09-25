#include "parsing/tx_parser_json.h"

#include <algorithm>
#include <array>
#include <vector>

#include "parsing/venue_pumpfun.h"
#include "solana/base58.h"
#include "solana/base64.h"
#include "solana/pda.h"
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

// pump.fun's TradeEvent, as it appears base64-encoded after "Program data: "
// in the logs: sha256("event:TradeEvent")[:8], then mint(32) sol_amount(u64)
// token_amount(u64) is_buy(u8) user(32) ... Same offsets the replay decoder
// has matched against the collector's own records since 2026-09.
constexpr std::array<uint8_t, 8> kTradeEventDiscriminator = {189, 219, 127, 211, 78, 230, 97, 238};
constexpr size_t kEvMint = 8, kEvSol = 40, kEvToken = 48, kEvIsBuy = 56, kEvUser = 57, kEvMinLen = 89;

uint64_t read_u64_le(const uint8_t* p) {
    uint64_t v = 0;
    for (int i = 7; i >= 0; --i) v = (v << 8) | p[i];
    return v;
}

// The wallet's own trade, from the event pump.fun emits for EVERY trade no
// matter which instruction produced it. The instruction path below only knows
// the original `buy` and `sell`; from 2026-09 Sheep's sells go 10/10 through
// `sell_v2` and ~90% of its buys through a newer buy instruction, so the
// collector saw buys and essentially never a sell -- every position stayed
// open. Returns false when the logs hold no TradeEvent for this wallet.
bool own_trade_from_logs(const nlohmann::json& tx_result, const solana::Pubkey& wallet, bool& is_buy,
                         solana::Pubkey& mint, uint64_t& token_amount) {
    if (!tx_result.contains("meta") || !tx_result["meta"].contains("logMessages")) return false;
    static const std::string kPrefix = "Program data: ";
    for (const auto& line : tx_result["meta"]["logMessages"]) {
        if (!line.is_string()) continue;
        const std::string& l = line.get_ref<const std::string&>();
        if (l.compare(0, kPrefix.size(), kPrefix) != 0) continue;
        std::vector<uint8_t> ev = solana::base64_decode(l.substr(kPrefix.size()));
        if (ev.size() < kEvMinLen) continue;
        if (!std::equal(kTradeEventDiscriminator.begin(), kTradeEventDiscriminator.end(), ev.begin())) continue;
        if (solana::Pubkey::from_bytes(ev.data() + kEvUser) != wallet) continue;
        is_buy = ev[kEvIsBuy] == 1;
        mint = solana::Pubkey::from_bytes(ev.data() + kEvMint);
        token_amount = read_u64_le(ev.data() + kEvToken);
        return true;
    }
    return false;
}

} // namespace

std::optional<solana::Pubkey> pumpfun_bonding_curve(const solana::Pubkey& mint) {
    static const std::vector<uint8_t> kSeed = {'b', 'o', 'n', 'd', 'i', 'n', 'g', '-', 'c', 'u', 'r', 'v', 'e'};
    std::vector<uint8_t> m(mint.bytes().begin(), mint.bytes().end());
    return solana::find_program_address({kSeed, m}, pumpfun::kProgramId);
}

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

    // No instruction the decoder knows. Fall back to the event log, which
    // covers sell_v2 and every newer buy variant. The bonding curve is derived
    // from the mint (the chain's own PDA rule) rather than read from an
    // account position: the new instructions moved it, and the cheaper
    // heuristics tested against live trades were right only 85-95% of the time.
    //
    // What this path cannot recover is the wallet's slippage bound -- the
    // event records the fill, not the limit -- so has_sol_bound is false and
    // the would-revert checks are skipped rather than evaluated against 0.
    bool is_buy = false;
    solana::Pubkey mint;
    uint64_t token_amount = 0;
    if (!own_trade_from_logs(tx_result, wallet, is_buy, mint, token_amount)) return std::nullopt;
    auto curve = pumpfun_bonding_curve(mint);
    if (!curve) return std::nullopt;

    TradeEvent event;
    event.venue = Venue::PumpFunBondingCurve;
    event.direction = is_buy ? Direction::Buy : Direction::Sell;
    event.wallet = wallet;
    event.wallet_label = wallet_label;
    event.mint = mint;
    event.bonding_curve = *curve;
    event.token_amount = token_amount;
    event.sol_amount = 0;
    event.has_sol_bound = false;
    event.slot = tx_result.value("slot", 0ull);
    event.signature_base58 = signature_base58;
    event.detected_at_micros = detected_at_micros;
    event.parsed_at_micros = util::now_micros();
    return event;
}

} // namespace parsing
