#include "parsing/debug_utils.h"

#include <vector>

namespace parsing {

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

} // namespace parsing
