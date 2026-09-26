// Runs the collector's real JSON parser over real transactions captured from
// the tracked wallets (tests/fixtures, recorded by reports/probe_instructions.py).
//
// The collector went from recording round trips to recording almost none
// because pump.fun wallets moved to instructions the parser did not know
// (sell_v2 for every Sheep sell, a newer buy for ~90% of its buys). Nothing
// failed: the transactions simply parsed to "not a trade". These fixtures make
// that a build failure instead of a silent week without data.
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>

#include <nlohmann/json.hpp>

#include "parsing/tx_parser_json.h"
#include "parsing/venue_pumpfun.h"

namespace {

int failures = 0;

void check(bool ok, const std::string& what) {
    std::cout << (ok ? "  ok   " : "  FAIL ") << what << "\n";
    if (!ok) ++failures;
}

void fixture(const std::string& dir, const std::string& name) {
    std::ifstream f(dir + "/" + name);
    if (!f) {
        check(false, name + ": fixture missing");
        return;
    }
    nlohmann::json fx = nlohmann::json::parse(f);
    solana::Pubkey wallet;
    solana::Pubkey::from_base58(fx["wallet"].get<std::string>(), wallet);
    auto ev = parsing::parse_json_transaction(fx["result"], wallet, "fixture", fx["signature"].get<std::string>(), 0);
    const auto& want = fx["expect"];
    check(ev.has_value(), name + ": parsed as a trade");
    if (!ev) return;
    bool is_buy = ev->direction == parsing::Direction::Buy;
    check(is_buy == (want["direction"] == "buy"), name + ": direction " + want["direction"].get<std::string>());
    check(ev->mint.to_base58() == want["mint"].get<std::string>(), name + ": mint");
    check(ev->token_amount == want["token_amount"].get<uint64_t>(), name + ": token amount");
    check(ev->bonding_curve.to_base58() == want["bonding_curve"].get<std::string>(), name + ": bonding curve");
}

} // namespace

int main(int argc, char** argv) {
    std::string dir = argc > 1 ? argv[1] : "tests/fixtures";

    std::cout << "bonding-curve PDA vs curves the collector recorded\n";
    const char* pairs[][2] = {
        {"D5hFKHEfQCcrpBo3CAUSDSA8n667JMaJ3M88ynstpump", "3XDhjGWq7uZJ2SDAkUSVuNAsfBjkssVTCZLQTuzftV5G"},
        {"9PkbS6NnkSJ9rdYmHWw1vB1MQb7iG6aqVbNnskBFpump", "3eJaNmr3UjSWEKiG68xF4khY1bYhBDHVRWVcQST74FpX"},
        {"7URSx87Wu2EzbbuPNXZrw4APmpYaevLFPVR7LSaapump", "55cM9duUbyKmyb61C61mowmWDSgj2xxryUipVEAL8TJs"},
    };
    for (const auto& p : pairs) {
        solana::Pubkey mint;
        solana::Pubkey::from_base58(p[0], mint);
        auto curve = parsing::pumpfun_bonding_curve(mint);
        check(curve && curve->to_base58() == p[1], std::string(p[0]).substr(0, 8) + "...");
    }

    std::cout << "SOL vs other-quote curves (reserves read from chain, 2026-09-26)\n";
    parsing::pumpfun::BondingCurveState sol_curve, quote_curve;
    sol_curve.virtual_sol_reserves = 30'077'118'162;          // FN9ktFiz...: SOL-quoted
    sol_curve.virtual_token_reserves = 1'070'248'825'424'186;
    quote_curve.virtual_sol_reserves = 578'167'476;           // MJCRxKf3...: quoted in another token
    quote_curve.virtual_token_reserves = 1'072'872'693'259'863;
    check(parsing::pumpfun::is_standard_sol_curve(sol_curve), "SOL curve accepted");
    check(!parsing::pumpfun::is_standard_sol_curve(quote_curve), "non-SOL curve rejected");

    std::cout << "real transactions\n";
    fixture(dir, "pumpfun_sell_v2.json");
    fixture(dir, "pumpfun_buy_new_instruction.json");
    fixture(dir, "pumpfun_buy_legacy_with_create.json");

    std::cout << (failures ? "FAILED" : "PASSED") << " (" << failures << " failure(s))\n";
    return failures ? EXIT_FAILURE : EXIT_SUCCESS;
}
