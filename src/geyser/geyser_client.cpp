#include "geyser/geyser_client.h"

#include <algorithm>
#include <chrono>
#include <memory>
#include <thread>
#include <unordered_map>

#include <grpcpp/grpcpp.h>

#include "geyser.grpc.pb.h"
#include "parsing/tx_parser.h"
#include "util/logging.h"
#include "util/time.h"

namespace geyser_client {

namespace {

std::unique_ptr<geyser::Geyser::Stub> make_stub(const std::string& endpoint) {
    grpc::ChannelArguments args;
    args.SetMaxReceiveMessageSize(64 * 1024 * 1024);
    auto channel =
        grpc::CreateCustomChannel(endpoint, grpc::SslCredentials(grpc::SslCredentialsOptions()), args);
    return geyser::Geyser::NewStub(channel);
}

geyser::SubscribeRequest build_subscribe_request(const Config& config) {
    geyser::SubscribeRequest req;
    auto& filter = (*req.mutable_transactions())["tracked_wallets"];
    filter.set_vote(false);
    filter.set_failed(false);
    for (const auto& wallet : config.tracked_wallets) {
        filter.add_account_include(wallet.pubkey.to_base58());
    }
    return req;
}

} // namespace

void run(const Config& config, TradeCallback on_trade) {
    std::unordered_map<solana::Pubkey, std::string, solana::PubkeyHash> tracked_map;
    for (const auto& w : config.tracked_wallets) {
        tracked_map[w.pubkey] = w.label;
    }
    parsing::TxParser parser(std::move(tracked_map));

    int backoff_ms = 500;
    constexpr int kMaxBackoffMs = 15000;

    while (true) {
        LOG_INFO("Connecting to geyser endpoint: " + config.endpoint);
        auto stub = make_stub(config.endpoint);

        grpc::ClientContext context;
        context.AddMetadata("x-token", config.x_token);

        auto stream = stub->Subscribe(&context);
        auto request = build_subscribe_request(config);

        if (!stream->Write(request)) {
            LOG_WARN("Failed to write initial subscribe request, retrying in " +
                     std::to_string(backoff_ms) + "ms");
            stream->WritesDone();
            std::this_thread::sleep_for(std::chrono::milliseconds(backoff_ms));
            backoff_ms = std::min(backoff_ms * 2, kMaxBackoffMs);
            continue;
        }

        LOG_INFO("Subscribed to " + std::to_string(config.tracked_wallets.size()) +
                  " tracked wallet(s), waiting for updates...");
        backoff_ms = 500; // reset once a connection has actually succeeded

        geyser::SubscribeUpdate update;
        while (stream->Read(&update)) {
            int64_t detected_at = util::now_micros();
            if (update.update_oneof_case() == geyser::SubscribeUpdate::kTransaction) {
                auto trade = parser.parse(update.transaction(), detected_at);
                if (trade) {
                    on_trade(*trade);
                }
            }
            // Other update types (ping/pong, account, slot, block) are
            // ignored for now -- only transaction updates matter for
            // detecting a tracked wallet's trades.
        }

        auto status = stream->Finish();
        LOG_WARN("Geyser stream ended (" + status.error_message() + "), reconnecting in " +
                  std::to_string(backoff_ms) + "ms");
        std::this_thread::sleep_for(std::chrono::milliseconds(backoff_ms));
        backoff_ms = std::min(backoff_ms * 2, kMaxBackoffMs);
    }
}

} // namespace geyser_client
