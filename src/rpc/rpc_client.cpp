#include "rpc/rpc_client.h"

#include "util/logging.h"

#include <algorithm>
#include <stdexcept>

#include <curl/curl.h>

#include "solana/base64.h"

namespace rpc {

namespace {

size_t write_callback(char* ptr, size_t size, size_t nmemb, void* userdata) {
    auto* out = static_cast<std::string*>(userdata);
    out->append(ptr, size * nmemb);
    return size * nmemb;
}

} // namespace

RpcClient::RpcClient(std::string endpoint) : endpoint_(std::move(endpoint)) {
    curl_ = curl_easy_init();
    if (!curl_) throw std::runtime_error("curl_easy_init failed");
}

RpcClient::~RpcClient() {
    if (curl_) curl_easy_cleanup(curl_);
}

nlohmann::json RpcClient::call(const std::string& method, const nlohmann::json& params) {
    nlohmann::json request = {
        {"jsonrpc", "2.0"},
        {"id", 1},
        {"method", method},
        {"params", params},
    };
    std::string body = request.dump();
    std::string response;

    struct curl_slist* headers = nullptr;
    headers = curl_slist_append(headers, "Content-Type: application/json");
    headers = curl_slist_append(headers, "Connection: keep-alive");

    curl_easy_setopt(curl_, CURLOPT_URL, endpoint_.c_str());
    curl_easy_setopt(curl_, CURLOPT_POST, 1L);
    curl_easy_setopt(curl_, CURLOPT_POSTFIELDS, body.c_str());
    curl_easy_setopt(curl_, CURLOPT_POSTFIELDSIZE, static_cast<long>(body.size()));
    curl_easy_setopt(curl_, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl_, CURLOPT_WRITEFUNCTION, write_callback);
    curl_easy_setopt(curl_, CURLOPT_WRITEDATA, &response);

    // These two numbers set the collector's detection lag, and the old value
    // of 15 seconds IS the "~17s free-tier latency" this project spent weeks
    // treating as a property of the RPC. Under load the endpoint holds a
    // connection open instead of refusing it, so a poll that would normally
    // answer in ~200ms sat here for the full fifteen seconds, once per cycle,
    // blocking every other wallet behind it. The 2026-09-04 collector log is
    // an unbroken run of timeouts spaced 17.4-17.6s apart.
    //
    // A copy trade that has not been detected within a few seconds is worth
    // nothing anyway, so waiting longer buys nothing and costs the poll loop
    // everything. Fail fast and get on with the next wallet.
    curl_easy_setopt(curl_, CURLOPT_TIMEOUT, 4L);
    curl_easy_setopt(curl_, CURLOPT_CONNECTTIMEOUT, 3L);
    curl_easy_setopt(curl_, CURLOPT_TCP_KEEPALIVE, 1L);

    CURLcode res = curl_easy_perform(curl_);
    curl_slist_free_all(headers);

    if (res != CURLE_OK) {
        throw std::runtime_error(std::string("RPC request failed: ") + curl_easy_strerror(res));
    }

    nlohmann::json parsed = nlohmann::json::parse(response, nullptr, false);
    if (parsed.is_discarded()) {
        throw std::runtime_error("RPC response was not valid JSON: " + response);
    }
    if (parsed.contains("error")) {
        throw std::runtime_error("RPC error: " + parsed["error"].dump());
    }
    return parsed;
}

std::vector<SignatureInfo> RpcClient::get_signatures_for_address(const std::string& address_base58,
                                                                   const std::string& until_signature, int limit) {
    nlohmann::json options = {{"limit", limit}};
    if (!until_signature.empty()) {
        options["until"] = until_signature;
    }
    nlohmann::json params = nlohmann::json::array({address_base58, options});

    nlohmann::json response = call("getSignaturesForAddress", params);

    std::vector<SignatureInfo> out;
    if (!response.contains("result") || !response["result"].is_array()) {
        return out;
    }
    for (const auto& entry : response["result"]) {
        SignatureInfo info;
        info.signature = entry.value("signature", "");
        info.slot = entry.value("slot", 0ull);
        info.has_error = entry.contains("err") && !entry["err"].is_null();
        if (entry.contains("blockTime") && entry["blockTime"].is_number()) {
            info.block_time = entry["blockTime"].get<int64_t>();
        }
        if (!info.signature.empty()) {
            out.push_back(std::move(info));
        }
    }
    // The RPC returns newest-first; reverse so callers process trades in the
    // order they actually happened.
    std::reverse(out.begin(), out.end());
    return out;
}

std::optional<nlohmann::json> RpcClient::get_transaction(const std::string& signature_base58) {
    nlohmann::json options = {
        {"encoding", "jsonParsed"},
        {"maxSupportedTransactionVersion", 0},
        {"commitment", "confirmed"},
    };
    nlohmann::json params = nlohmann::json::array({signature_base58, options});

    nlohmann::json response = call("getTransaction", params);
    if (!response.contains("result") || response["result"].is_null()) {
        return std::nullopt;
    }
    return response["result"];
}

std::optional<std::vector<uint8_t>> RpcClient::get_account_info(const std::string& pubkey_base58) {
    nlohmann::json options = {
        {"encoding", "base64"},
        {"commitment", "processed"},
    };
    nlohmann::json params = nlohmann::json::array({pubkey_base58, options});

    nlohmann::json response = call("getAccountInfo", params);
    if (!response.contains("result") || response["result"].is_null()) return std::nullopt;
    const auto& result = response["result"];
    if (!result.contains("value") || result["value"].is_null()) return std::nullopt;
    const auto& value = result["value"];
    if (!value.contains("data") || !value["data"].is_array() || value["data"].empty()) return std::nullopt;
    if (!value["data"][0].is_string()) return std::nullopt;

    return solana::base64_decode(value["data"][0].get<std::string>());
}

std::vector<SignatureInfo> RpcClient::get_signatures_before(const std::string& address_base58,
                                                             const std::string& before_signature, int limit) {
    nlohmann::json options = {{"limit", limit}};
    if (!before_signature.empty()) options["before"] = before_signature;
    nlohmann::json params = nlohmann::json::array({address_base58, options});

    std::vector<SignatureInfo> out;
    nlohmann::json response;
    try {
        response = call("getSignaturesForAddress", params);
    } catch (const std::exception& e) {
        LOG_WARN(std::string("getSignaturesForAddress(before) failed for ") + address_base58 + ": " + e.what());
        return out;
    }
    if (!response.contains("result") || !response["result"].is_array()) return out;

    for (const auto& entry : response["result"]) {
        SignatureInfo info;
        info.signature = entry.value("signature", "");
        info.slot = entry.value("slot", 0ull);
        info.has_error = entry.contains("err") && !entry["err"].is_null();
        if (entry.contains("blockTime") && entry["blockTime"].is_number()) {
            info.block_time = entry["blockTime"].get<int64_t>();
        }
        if (!info.signature.empty()) out.push_back(std::move(info));
    }
    return out; // newest-first, as returned
}

std::vector<uint64_t> RpcClient::get_token_largest_accounts(const std::string& mint_base58) {
    std::vector<uint64_t> amounts;
    nlohmann::json params = nlohmann::json::array({mint_base58, {{"commitment", "processed"}}});

    nlohmann::json response;
    try {
        response = call("getTokenLargestAccounts", params);
    } catch (const std::exception& e) {
        // Rate limits are routine on the free tier. A missing risk figure is
        // recoverable; losing the observation is not.
        LOG_WARN(std::string("getTokenLargestAccounts failed for ") + mint_base58 + ": " + e.what());
        return amounts;
    }
    if (!response.contains("result") || response["result"].is_null()) return amounts;
    const auto& result = response["result"];
    if (!result.contains("value") || !result["value"].is_array()) return amounts;

    for (const auto& entry : result["value"]) {
        if (!entry.contains("amount") || !entry["amount"].is_string()) continue;
        try {
            amounts.push_back(std::stoull(entry["amount"].get<std::string>()));
        } catch (const std::exception&) {
            continue; // malformed entry, skip it rather than abandoning the rest
        }
    }
    return amounts;
}

} // namespace rpc
