#pragma once

#include <string>

#include <nlohmann/json.hpp>

namespace parsing {

// Diagnostic-only: lists the program IDs a getTransaction (jsonParsed)
// result actually invoked, so "nothing detected" can be told apart from
// "detected but not a venue we decode yet" (e.g. Jupiter/Raydium routing
// instead of calling pump.fun directly).
std::string extract_program_ids(const nlohmann::json& tx_result);

} // namespace parsing
