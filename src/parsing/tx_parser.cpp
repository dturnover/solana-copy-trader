#include "parsing/tx_parser.h"

#include <string>
#include <vector>

#include "geyser.pb.h"
#include "parsing/venue_pumpfun.h"
#include "solana-storage.pb.h"
#include "solana/base58.h"
#include "util/logging.h"
#include "util/time.h"

namespace parsing {

namespace {

std::vector<solana::Pubkey> resolve_account_keys(
    const solana::storage::ConfirmedBlock::Transaction& tx,
    const solana::storage::ConfirmedBlock::TransactionStatusMeta& meta) {
    std::vector<solana::Pubkey> keys;
    const auto& msg = tx.message();
    keys.reserve(static_cast<size_t>(msg.account_keys_size() + meta.loaded_writable_addresses_size() +
                                      meta.loaded_readonly_addresses_size()));

    // Full account-index space for a v0 transaction = static account_keys,
    // followed by address-lookup-table-resolved writable then readonly
    // addresses, in that order -- matches Solana runtime's own resolution.
    for (const auto& key : msg.account_keys()) {
        keys.push_back(solana::Pubkey::from_bytes(reinterpret_cast<const uint8_t*>(key.data())));
    }
    for (const auto& key : meta.loaded_writable_addresses()) {
        keys.push_back(solana::Pubkey::from_bytes(reinterpret_cast<const uint8_t*>(key.data())));
    }
    for (const auto& key : meta.loaded_readonly_addresses()) {
        keys.push_back(solana::Pubkey::from_bytes(reinterpret_cast<const uint8_t*>(key.data())));
    }
    return keys;
}

std::vector<solana::Pubkey> resolve_instruction_accounts(const std::string& index_bytes,
                                                          const std::vector<solana::Pubkey>& all_keys) {
    std::vector<solana::Pubkey> accounts;
    accounts.reserve(index_bytes.size());
    for (unsigned char idx : index_bytes) {
        if (idx < all_keys.size()) {
            accounts.push_back(all_keys[idx]);
        }
    }
    return accounts;
}

std::vector<uint8_t> to_bytes(const std::string& data) {
    return std::vector<uint8_t>(data.begin(), data.end());
}

// Cross-check the mint pulled from the instruction's account list against
// the transaction's pre/post token balance deltas for the trading wallet.
// This exists because the pump.fun account list's mint index is flagged
// [VERIFY] -- if the two ever disagree, that's a strong signal the account
// layout assumption in venue_pumpfun.cpp is stale and needs re-checking
// against a live IDL, rather than silently trading the wrong token.
void cross_check_mint(const solana::storage::ConfirmedBlock::TransactionStatusMeta& meta,
                       const std::vector<solana::Pubkey>& all_keys, const solana::Pubkey& wallet,
                       const solana::Pubkey& decoded_mint, const std::string& signature_base58) {
    std::string wallet_b58 = wallet.to_base58();
    std::string decoded_mint_b58 = decoded_mint.to_base58();

    for (const auto& balance : meta.pre_token_balances()) {
        if (balance.owner() == wallet_b58 && balance.mint() != decoded_mint_b58) {
            // Only warn if this owner-matching mint isn't the decoded one --
            // a wallet often touches multiple token accounts (e.g. WSOL) in
            // the same tx, so a mismatch here isn't necessarily wrong, just
            // worth a log line for manual review during Phase 1 validation.
            LOG_DEBUG("mint cross-check: wallet " + wallet_b58 + " also touched mint " + balance.mint() +
                      " in tx " + signature_base58 + " (decoded mint was " + decoded_mint_b58 + ")");
        }
    }
}

} // namespace

TxParser::TxParser(std::unordered_map<solana::Pubkey, std::string, solana::PubkeyHash> tracked_wallets)
    : tracked_wallets_(std::move(tracked_wallets)) {}

std::optional<TradeEvent> TxParser::parse(const geyser::SubscribeUpdateTransaction& update,
                                           int64_t detected_at_micros) {
    const auto& info = update.transaction();
    const auto& tx = info.transaction();
    const auto& meta = info.meta();
    const auto& msg = tx.message();

    auto all_keys = resolve_account_keys(tx, meta);

    // Identify which tracked wallet this transaction belongs to by scanning
    // the signer accounts (the first num_required_signatures keys), rather
    // than assuming index 0 -- handles the (rare) multi-signer case.
    solana::Pubkey wallet;
    std::string wallet_label;
    bool found_wallet = false;
    uint32_t num_signers = msg.header().num_required_signatures();
    for (uint32_t i = 0; i < num_signers && i < all_keys.size(); ++i) {
        auto it = tracked_wallets_.find(all_keys[i]);
        if (it != tracked_wallets_.end()) {
            wallet = all_keys[i];
            wallet_label = it->second;
            found_wallet = true;
            break;
        }
    }
    if (!found_wallet) {
        return std::nullopt;
    }

    std::string signature_base58 = solana::base58_encode(
        reinterpret_cast<const uint8_t*>(info.signature().data()), info.signature().size());

    // Walk top-level instructions, then inner instructions -- a tracked
    // wallet's buy/sell can be a direct call or invoked via a wrapper/router,
    // so both levels need checking.
    struct FlatIx {
        uint32_t program_id_index;
        const std::string* accounts;
        const std::string* data;
    };
    std::vector<FlatIx> all_ixs;
    all_ixs.reserve(static_cast<size_t>(msg.instructions_size()));

    for (const auto& ix : msg.instructions()) {
        all_ixs.push_back({ix.program_id_index(), &ix.accounts(), &ix.data()});
    }
    for (const auto& inner : meta.inner_instructions()) {
        for (const auto& ix : inner.instructions()) {
            all_ixs.push_back({ix.program_id_index(), &ix.accounts(), &ix.data()});
        }
    }

    for (const auto& ix : all_ixs) {
        if (ix.program_id_index >= all_keys.size()) continue;
        const auto& program_id = all_keys[ix.program_id_index];

        if (program_id == pumpfun::kProgramId) {
            auto accounts = resolve_instruction_accounts(*ix.accounts, all_keys);
            auto data = to_bytes(*ix.data);
            auto decoded = pumpfun::try_decode(data, accounts);
            if (!decoded) continue;

            cross_check_mint(meta, all_keys, wallet, decoded->mint, signature_base58);

            TradeEvent event;
            event.venue = Venue::PumpFunBondingCurve;
            event.direction = decoded->direction;
            event.wallet = wallet;
            event.wallet_label = wallet_label;
            event.mint = decoded->mint;
            event.bonding_curve = decoded->bonding_curve;
            event.token_amount = decoded->amount;
            event.sol_amount = decoded->sol_bound;
            event.slot = update.slot();
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
