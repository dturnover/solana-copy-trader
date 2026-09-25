"""
Which pump.fun instructions do our wallets actually trade through?

src/parsing/venue_pumpfun.cpp recognizes exactly two instruction
discriminators, `buy` and `sell`. From 2026-09-24 the collector saw buys and
almost no sells: ~30 buys to 1 close, then 14 to 0, then 3 to 0 with zero RPC
failures. A sell sent through any other pump.fun instruction would be
invisible to it while the position stays open forever.

This does not guess which instructions exist. For every recent pump.fun
transaction of each tracked wallet it takes the program's own TradeEvent from
the logs -- which says buy or sell regardless of which instruction produced
it -- and tallies it against the discriminator of each pump.fun instruction in
that transaction, marking which ones the collector's parser knows.
"""

import argparse
import base64
import hashlib
import json
import os
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from replay_same_block import B58, TX_OPTS, decode_trade_events, rpc  # noqa: E402

CONFIG = "config/config.paper_trade.ci.json"
PUMPFUN = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

# What venue_pumpfun.cpp matches, and names for anything else we can identify.
KNOWN_TO_PARSER = {"buy", "sell"}
CANDIDATE_NAMES = ["buy", "sell", "buy_exact_sol_in", "sell_exact_in", "buy_exact_in",
                   "sell_exact_out", "buy_v2", "sell_v2", "create", "create_v2",
                   "extend_account", "collect_creator_fee", "migrate"]
NAME_BY_DISC = {hashlib.sha256(f"global:{n}".encode()).digest()[:8].hex(): n for n in CANDIDATE_NAMES}


def b58decode(s):
    n = 0
    for ch in s:
        n = n * 58 + B58.index(ch)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\0" * (len(s) - len(s.lstrip("1"))) + raw


P = 2**255 - 19
D = (-121665 * pow(121666, P - 2, P)) % P


def on_curve(b):
    y = int.from_bytes(b, "little") & ((1 << 255) - 1)
    if y >= P:
        return False
    x2 = (y * y - 1) * pow(D * y * y + 1, P - 2, P) % P
    return x2 == 0 or pow(x2, (P - 1) // 2, P) == 1


def bonding_curve_pda(mint):
    """Program-derived address, computed from first principles so the rules
    below are checked against something the transaction itself cannot fake."""
    prog = b58decode(PUMPFUN)
    for bump in range(255, -1, -1):
        h = hashlib.sha256(b"bonding-curve" + b58decode(mint) + bytes([bump]) + prog
                           + b"ProgramDerivedAddress").digest()
        if not on_curve(h):
            return h
    return None


def curve_rules(tx, event):
    """Which cheap rules would find the bonding curve for this trade?"""
    pda = bonding_curve_pda(event["mint"])
    msg = tx["transaction"]["message"]
    keys = [k["pubkey"] for k in msg["accountKeys"]]
    meta = tx["meta"]
    out = {}
    ixs = list(msg.get("instructions") or [])
    for inner in meta.get("innerInstructions") or []:
        ixs += inner.get("instructions") or []
    pump = [ix for ix in ixs if ix.get("programId") == PUMPFUN and len(ix.get("accounts") or []) > 3
            and ix["accounts"][2] == event["mint"]]
    out["ix accounts[3] is curve"] = bool(pump) and all(b58decode(ix["accounts"][3]) == pda for ix in pump)
    import struct
    for ix in pump:
        raw = b58decode(ix["data"])
        name = NAME_BY_DISC.get(raw[:8].hex(), "unknown:" + raw[:8].hex())
        if len(raw) >= 24:
            amt, bound = struct.unpack_from("<QQ", raw, 8)
            out[f"{name}: arg0 == token_amount"] = amt == event["token_amount"]
            out[f"{name}: arg1 is a sol bound"] = (bound >= event["sol_amount"]) if event["is_buy"] \
                else (bound <= event["sol_amount"])
            out[f"{name}: arg0 == sol_amount"] = amt == event["sol_amount"]
        out[f"{name}: data length {len(raw)}"] = True
    deltas = [post - pre for pre, post in zip(meta["preBalances"], meta["postBalances"])]
    want = event["sol_amount"] if event["is_buy"] else -event["sol_amount"]
    hits = [keys[i] for i, dl in enumerate(deltas) if dl == want]
    out["unique lamport delta = sol_amount is curve"] = len(hits) == 1 and b58decode(hits[0]) == pda
    return out


def pump_discriminators(tx):
    msg = (tx.get("transaction") or {}).get("message") or {}
    ixs = list(msg.get("instructions") or [])
    for inner in (tx.get("meta") or {}).get("innerInstructions") or []:
        ixs += inner.get("instructions") or []
    out = []
    for ix in ixs:
        if ix.get("programId") == PUMPFUN and isinstance(ix.get("data"), str):
            d = b58decode(ix["data"])[:8].hex()
            out.append(NAME_BY_DISC.get(d, f"unknown:{d}"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100, help="signatures per wallet")
    args = ap.parse_args()
    endpoint = os.environ["RPC_ENDPOINT"]
    wallets = json.load(open(CONFIG))["tracked_wallets"]

    # (wallet, event side, instruction name) -> count
    tally = Counter()
    rules = Counter()
    per_wallet = defaultdict(Counter)
    for w in wallets:
        sigs = rpc(endpoint, "getSignaturesForAddress",
                   [w["pubkey"], {"limit": args.limit, "commitment": "confirmed"}]) or []
        for s in sigs:
            if s.get("err") is not None:
                continue
            time.sleep(0.2)
            try:
                tx = rpc(endpoint, "getTransaction", [s["signature"], TX_OPTS])
            except Exception as e:
                per_wallet[w["label"]]["fetch-error"] += 1
                print(f"  fetch failed: {e}")
                continue
            if not tx:
                continue
            names = pump_discriminators(tx)
            if not names:
                per_wallet[w["label"]]["not pump.fun"] += 1
                continue
            events = [e for e in decode_trade_events(tx) if e["user"] == w["pubkey"]]
            for e in events:
                for rule, ok in curve_rules(tx, e).items():
                    rules[(rule, "buy" if e["is_buy"] else "sell", ok)] += 1
            sides = {("buy" if e["is_buy"] else "sell") for e in events} or {"no-own-event"}
            for side in sides:
                for n in set(names):
                    tally[(w["label"], side, n)] += 1
            per_wallet[w["label"]][f"v{tx.get('version')}"] += 1

    print("\nPer wallet:", {k: dict(v) for k, v in per_wallet.items()})
    print("\nwallet    side          instruction                parser knows it?  n")
    for (w, side, n), c in sorted(tally.items()):
        known = "yes" if n in KNOWN_TO_PARSER else "NO"
        print(f"{w:<9} {side:<13} {n:<26} {known:<17} {c}")

    print("\nBonding-curve rules vs the derived PDA  (rule, side, holds?): n")
    for k, c in sorted(rules.items()):
        print(f"  {k}: {c}")
    trades = {k: c for k, c in tally.items() if k[1] in ("buy", "sell")}
    unseen = sum(c for k, c in trades.items() if k[2] not in KNOWN_TO_PARSER)
    print(f"\n{unseen} wallet trade(s) went through instructions the collector does not recognize")
    if not trades:
        sys.exit("FAIL: no wallet trades found -- nothing measured")


if __name__ == "__main__":
    main()
