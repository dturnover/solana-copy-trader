"""
Can the free RPC show every trade on a coin in the blocks right after a
wallet's trade?

That is what simulating a gRPC-speed copy needs. A fill N slots after the
wallet is priced by the curve as it stood N slots later, and pump.fun's
TradeEvent on each intervening trade carries exactly that. The one open
question is whether the endpoint lists those transactions: an earlier replay
(replay_lag.py) found no signature history for bonding-curve accounts, but
it was asking about trades days old. This asks about recent ones, by both
the bonding curve and the mint, and reports what comes back.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import pandas as pd  # noqa: E402
from replay_same_block import TX_OPTS, decode_trade_events, rpc  # noqa: E402

DATASET = "reports/paper_trades_final.csv"


def between(endpoint, address, newer_sig, older_sig, cap=2000):
    """Signatures on `address` strictly between two of its transactions."""
    out, before = [], newer_sig
    while len(out) < cap:
        opts = {"limit": 1000, "until": older_sig, "commitment": "confirmed"}
        if before:
            opts["before"] = before
        page = rpc(endpoint, "getSignaturesForAddress", [address, opts]) or []
        if not page:
            break
        out += page
        before = page[-1]["signature"]
        if len(page) < 1000:
            break
    return out


def main():
    endpoint = os.environ["RPC_ENDPOINT"]
    d = pd.read_csv(DATASET)
    d = d[(d["entry_on_chain_age_ms"] < 60_000) & d["sell_signature"].notna()]
    d = d.sort_values("epoch_ms", ascending=False).head(8)
    ok = 0
    for _, r in d.iterrows():
        print(f"=== {r['wallet_label']} mint={r['mint'][:8]} hold={r['hold_duration_ms'] / 1000:.0f}s")
        entry = rpc(endpoint, "getTransaction", [r["entry_signature"], TX_OPTS])
        if not entry:
            print("  entry tx not retained")
            continue
        s0 = entry["slot"]
        for label, addr in (("curve", r["bonding_curve"]), ("mint", r["mint"])):
            sigs = between(endpoint, addr, r["sell_signature"], r["entry_signature"])
            slots = sorted(s["slot"] - s0 for s in sigs)
            print(f"  by {label}: {len(sigs)} txs between entry and exit; slot offsets {slots[:12]}"
                  f"{' ...' if len(slots) > 12 else ''}")
            if label == "curve" and sigs:
                # Do those transactions carry decodable reserves for this mint?
                first = min(sigs, key=lambda s: s["slot"])
                tx = rpc(endpoint, "getTransaction", [first["signature"], TX_OPTS]) or {}
                ev = [e for e in decode_trade_events(tx) if e["mint"] == r["mint"]]
                print(f"  first later tx (slot +{first['slot'] - s0}): "
                      f"{len(ev)} TradeEvent(s) on this mint, vsol={ev[0]['virtual_sol'] if ev else None}")
                ok += bool(ev)
    print(f"\n{ok} of {len(d)} round trips had later trades with readable reserves")


if __name__ == "__main__":
    main()
