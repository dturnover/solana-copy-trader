"""
Checks that live pump.fun transactions still have the shape our parsers read.

Why this exists. On 2026-09-23 Solana began producing version-1 transactions.
getTransaction with maxSupportedTransactionVersion 0 rejects them outright, so
from about 14:00 UTC that day every fetch the collector made failed, it
recorded nothing, and every run still reported success. Raising the version
cap makes the RPC return them; it does not make our parsers understand them.
This fetches real recent transactions at the new cap and checks, field by
field, what src/parsing/tx_parser_json.cpp, src/parsing/debug_utils.cpp and
reports/replay_same_block.py actually read -- on v1 transactions specifically.

Exits non-zero if no v1 transaction was found or any of them is missing a
field a parser needs, so a green run is evidence and not an absence of it.
"""

import argparse
import base64
import json
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))
from replay_same_block import TX_OPTS, decode_trade_events, rpc  # noqa: E402

CONFIG = "config/config.paper_trade.ci.json"
PUMPFUN = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

NO_EVENT = "no TradeEvent in meta.logMessages"
NO_PUMP = "no pump.fun instruction with programId"


def shape_problems(tx):
    """Fields a parser reads that this transaction lacks. Empty = parseable."""
    p = []
    msg = (tx.get("transaction") or {}).get("message") or {}
    meta = tx.get("meta") or {}
    ixs = list(msg.get("instructions") or [])
    for inner in meta.get("innerInstructions") or []:
        ixs += inner.get("instructions") or []
    if "instructions" not in msg:
        p.append("transaction.message.instructions")
    pump = [ix for ix in ixs if ix.get("programId") == PUMPFUN]
    if not pump:
        p.append(NO_PUMP)
    for ix in pump:
        if not isinstance(ix.get("data"), str) or not isinstance(ix.get("accounts"), list) \
                or not all(isinstance(a, str) for a in ix["accounts"]):
            p.append("pump.fun instruction not in raw {programId, accounts[str], data[str]} shape")
            break
    keys = msg.get("accountKeys")
    if not isinstance(keys, list) or not all(isinstance(k, dict) and "pubkey" in k for k in keys):
        p.append("transaction.message.accountKeys[].pubkey")
    elif len(meta.get("preBalances") or []) != len(keys) or len(meta.get("postBalances") or []) != len(keys):
        p.append("meta.pre/postBalances not aligned with accountKeys")
    if not isinstance(meta.get("fee"), int):
        p.append("meta.fee")
    if not decode_trade_events(tx):
        p.append(NO_EVENT)
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()
    endpoint = os.environ["RPC_ENDPOINT"]

    # The program itself for volume, plus the wallets we copy, since theirs are
    # the transactions that actually have to parse.
    wallets = [w["pubkey"] for w in json.load(open(CONFIG))["tracked_wallets"]]
    sigs = []
    for addr in [PUMPFUN] + wallets:
        try:
            got = rpc(endpoint, "getSignaturesForAddress",
                      [addr, {"limit": args.limit, "commitment": "confirmed"}]) or []
        except Exception as e:
            print(f"  getSignaturesForAddress failed for {addr[:8]}: {e}")
            continue
        sigs += [g["signature"] for g in got if g.get("err") is None and g["signature"] not in sigs]
    print(f"TX_OPTS = {TX_OPTS}")
    print(f"{len(sigs)} recent successful signatures (pump.fun program + tracked wallets)\n")

    versions, bad, example = Counter(), [], None
    for sig in sigs:
        time.sleep(0.25)
        try:
            tx = rpc(endpoint, "getTransaction", [sig, TX_OPTS])
        except Exception as e:
            versions["fetch-error"] += 1
            print(f"  fetch failed {sig[:16]}: {e}")
            continue
        if not tx:
            versions["null"] += 1
            continue
        v = str(tx.get("version"))
        versions[v] += 1
        probs = shape_problems(tx)
        if v == "1":
            example = example or tx
            if probs:
                bad.append((sig, probs))
        print(f"  v{v:<6} {sig[:16]}  {'OK' if not probs else '; '.join(probs)}")

    print(f"\nversions: {dict(versions)}")
    if example:
        print("\nTop-level shape of one v1 transaction:")
        print(json.dumps({k: (sorted(v) if isinstance(v, dict) else type(v).__name__)
                          for k, v in example.items()}, indent=1))
        print("message keys:", sorted(example["transaction"]["message"]))
        print("meta keys:", sorted(example.get("meta") or {}))

    # A structural gap (instructions, keys, balances, fee) breaks every
    # transaction, so one is a failure. A missing TradeEvent alone can be a
    # legitimate non-trade (a bare create, a migration), so that is judged as a
    # rate over the v1 transactions that touch pump.fun at all.
    pump_v1 = versions["1"] - sum(NO_PUMP in p for _, p in bad)
    structural = [(s, p) for s, p in bad if [x for x in p if x not in (NO_PUMP, NO_EVENT)]]
    no_event = sum(p == [NO_EVENT] for _, p in bad)
    if versions["1"] == 0 or pump_v1 == 0:
        sys.exit("FAIL: no v1 pump.fun transaction seen -- nothing verified")
    if structural:
        for s, p in structural:
            print(f"FAIL {s}: {p}")
        sys.exit(f"FAIL: {len(structural)} of {versions['1']} v1 transactions are missing parser fields")
    if no_event > pump_v1 / 2:
        sys.exit(f"FAIL: TradeEvent decoded on only {pump_v1 - no_event} of {pump_v1} v1 pump.fun transactions")
    print(f"\nPASS: {versions['1']} v1 transactions carry every field the parsers read")


if __name__ == "__main__":
    main()
