#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

namespace rpc {

struct SignatureInfo {
    std::string signature;
    uint64_t slot = 0;
    bool has_error = false;
};

// Thin JSON-RPC client over a plain Solana REST endpoint (e.g. Shyft's
// free-tier "https://rpc.shyft.to?api_key=..." or the public
// mainnet-beta endpoint). This is what the polling engine uses as a $0
// stand-in for real-time Geyser gRPC streaming -- same purpose, much higher
// latency (seconds, not sub-second) -- and it's the only thing that changes
// if the RPC provider is swapped out later.
class RpcClient {
public:
    explicit RpcClient(std::string endpoint);

    // Returns signatures newer than `until_signature` (exclusive),
    // oldest-first. The RPC itself returns newest-first; this reverses that
    // so callers process trades in the order they actually happened. An
    // empty `until_signature` returns up to `limit` most recent signatures.
    std::vector<SignatureInfo> get_signatures_for_address(const std::string& address_base58,
                                                            const std::string& until_signature, int limit = 20);

    // Returns the "result" object for a confirmed transaction (encoding
    // jsonParsed), or nullopt if the node doesn't have it yet (too fresh) or
    // it doesn't exist.
    std::optional<nlohmann::json> get_transaction(const std::string& signature_base58);

    // Returns the raw account data bytes for a pubkey (encoding base64,
    // commitment "processed" for the freshest possible read), or nullopt if
    // the account doesn't exist.
    std::optional<std::vector<uint8_t>> get_account_info(const std::string& pubkey_base58);

private:
    nlohmann::json call(const std::string& method, const nlohmann::json& params);

    std::string endpoint_;
};

} // namespace rpc
