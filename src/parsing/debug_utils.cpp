#include "parsing/debug_utils.h"

#include <vector>

#include "solana/base58.h"

namespace parsing {

namespace {
constexpr const char* kComputeBudgetProgramId = "ComputeBudget111111111111111111111111111111";
constexpr uint8_t kSetComputeUnitPriceDiscriminator = 3;

uint64_t read_u64_le(const uint8_t* p) {
    uint64_t v = 0;
    for (int i = 7; i >= 0; --i) v = (v << 8) | p[i];
    return v;
}
} // namespace

std::string extract_program_ids(const nlohmann::json& tx_result) {
    std::vector<std::string> ids;
    auto collect = [&](const nlohmann::json& ixs) {
        for (const auto& ix : ixs) {
            if (ix.contains("programId") && ix["programId"].is_string()) {
                ids.push_back(ix["programId"].get<std::string>());
            } else if (ix.contains("program") && ix["program"].is_string()) {
                ids.push_back(ix["program"].get<std::string>() + "(parsed)");
            }
        }
    };
    if (tx_result.contains("transaction") && tx_result["transaction"].contains("message") &&
        tx_result["transaction"]["message"].contains("instructions")) {
        collect(tx_result["transaction"]["message"]["instructions"]);
    }
    if (tx_result.contains("meta") && tx_result["meta"].contains("innerInstructions")) {
        for (const auto& inner : tx_result["meta"]["innerInstructions"]) {
            if (inner.contains("instructions")) collect(inner["instructions"]);
        }
    }
    std::string out;
    for (size_t i = 0; i < ids.size(); ++i) {
        if (i) out += ", ";
        out += ids[i];
    }
    return out;
}

std::optional<uint64_t> extract_total_fee_lamports(const nlohmann::json& tx_result) {
    if (tx_result.contains("meta") && tx_result["meta"].contains("fee") && tx_result["meta"]["fee"].is_number()) {
        return tx_result["meta"]["fee"].get<uint64_t>();
    }
    return std::nullopt;
}

std::optional<uint64_t> extract_priority_fee_micro_lamports(const nlohmann::json& tx_result) {
    if (!tx_result.contains("transaction") || !tx_result["transaction"].contains("message")) {
        return std::nullopt;
    }
    const auto& message = tx_result["transaction"]["message"];
    if (!message.contains("instructions")) return std::nullopt;

    // ComputeBudget instructions are always top-level (never invoked via
    // CPI), so there's no need to walk inner instructions here.
    for (const auto& ix : message["instructions"]) {
        if (!ix.contains("programId") || !ix["programId"].is_string()) continue;
        if (ix["programId"].get<std::string>() != kComputeBudgetProgramId) continue;
        if (!ix.contains("data") || !ix["data"].is_string()) continue;

        std::vector<uint8_t> data;
        if (!solana::base58_decode(ix["data"].get<std::string>(), data)) continue;
        if (data.size() < 9 || data[0] != kSetComputeUnitPriceDiscriminator) continue;

        return read_u64_le(data.data() + 1);
    }
    return std::nullopt;
}

std::optional<int64_t> extract_wallet_sol_delta(const nlohmann::json& tx_result, const solana::Pubkey& wallet) {
    if (!tx_result.contains("transaction") || !tx_result["transaction"].contains("message")) {
        return std::nullopt;
    }
    const auto& msg = tx_result["transaction"]["message"];
    if (!msg.contains("accountKeys") || !msg["accountKeys"].is_array()) return std::nullopt;
    const auto& keys = msg["accountKeys"];

    int wallet_index = -1;
    for (size_t i = 0; i < keys.size(); ++i) {
        if (!keys[i].is_object() || !keys[i].contains("pubkey") || !keys[i]["pubkey"].is_string()) continue;
        solana::Pubkey pk;
        if (solana::Pubkey::from_base58(keys[i]["pubkey"].get<std::string>(), pk) && pk == wallet) {
            wallet_index = static_cast<int>(i);
            break;
        }
    }
    if (wallet_index < 0) return std::nullopt;

    if (!tx_result.contains("meta")) return std::nullopt;
    const auto& meta = tx_result["meta"];
    if (!meta.contains("preBalances") || !meta.contains("postBalances")) return std::nullopt;
    if (!meta["preBalances"].is_array() || !meta["postBalances"].is_array()) return std::nullopt;
    if (wallet_index >= static_cast<int>(meta["preBalances"].size()) ||
        wallet_index >= static_cast<int>(meta["postBalances"].size())) {
        return std::nullopt;
    }

    int64_t pre = meta["preBalances"][wallet_index].get<int64_t>();
    int64_t post = meta["postBalances"][wallet_index].get<int64_t>();
    return post - pre;
}

} // namespace parsing
