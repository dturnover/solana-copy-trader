#include "rpc/rpc_client.h"

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

RpcClient::RpcClient(std::string endpoint) : endpoint_(std::move(endpoint)) {}

nlohmann::json RpcClient::call(const std::string& method, const nlohmann::json& params) {
    nlohmann::json request = {
        {"jsonrpc", "2.0"},
        {"id", 1},
        {"method", method},
        {"params", params},
    };
    std::string body = request.dump();
    std::string response;

    CURL* curl = curl_easy_init();
    if (!curl) {
        throw std::runtime_error("curl_easy_init failed");
    }

    struct curl_slist* headers = nullptr;
    headers = curl_slist_append(headers, "Content-Type: application/json");

    curl_easy_setopt(curl, CURLOPT_URL, endpoint_.c_str());
    curl_easy_setopt(curl, CURLOPT_POST, 1L);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body.c_str());
    curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, static_cast<long>(body.size()));
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_callback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 15L);

    CURLcode res = curl_easy_perform(curl);
    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);

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

} // namespace rpc
