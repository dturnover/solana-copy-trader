"""
Does the KOL buy signal make money if we stop following the KOL's sell?

Background. Copying a pump.fun wallet buy-and-sell loses even at the best
reachable speed (first in the next block): every tracked wallet and almost
every kolscan.io KOL is negative there. Part of that loss is the exit -- we
sell after the wallet has already dumped (median exit at 0.81x our entry at
~4s). This keeps the wallet's BUY as the signal and replaces its SELL with
our own exit rule, on the same entries:

  follow       sell when the wallet first sells (the current strategy)
  hold N       sell N slots after our entry (~0.4s per slot)
  TP x / SL y  sell at the first checkpoint where the copy is up x% or down
               y%; give up at the last checkpoint

Entry is first in the next block after the wallet's buy (the best a copier
can do). The curve after our entry is read at fixed slot checkpoints from
pump.fun's TradeEvents, exactly as replay_slot_lag.py reads it, so TP/SL is
evaluated on that grid -- a copier acting on slot-level data could do no
finer. 0.25 SOL fixed size, measured fees.

Overfitting warning. Many rules are scored on the same trades, so the best
one is biased upward. A rule only counts if it stays positive on later
days' data it was not picked on -- the daily run is that test.
"""

import argparse
import collections
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from discover_wallets import sol_events  # noqa: E402
from probe_instructions import bonding_curve_pda  # noqa: E402
from replay_same_block import TX_OPTS, b58encode, rpc  # noqa: E402
from replay_slot_lag import SIZE_SOL, curve_sigs_after, state_at  # noqa: E402
from size_sweep import SCENARIOS  # noqa: E402

LAMPORTS = 1e9
# Slots after our entry at which the curve is read (~0.4s each): 0.4s .. 60s.
CHECKPOINTS = [1, 2, 3, 5, 8, 12, 18, 25, 35, 50, 75, 100, 150]
HOLDS = [1, 3, 5, 12, 25, 50, 75, 150]
TP_SL = [(0.10, 0.10), (0.20, 0.10), (0.30, 0.15), (0.50, 0.25), (1.00, 0.30)]


def copy_value(vs_in, vt_in, vs_now, vt_now, prop, fixed):
    """Return on a SIZE_SOL copy bought at one curve state and sold at another."""
    S = SIZE_SOL * LAMPORTS
    spend = S / (1 + prop)
    tokens = vt_in - (vs_in * vt_in) / (vs_in + spend)
    if tokens <= 0:
        return None
    gross = vs_now - (vs_now * vt_now) / (vt_now + tokens)
    return ((gross * (1 - prop) - S) / LAMPORTS - fixed) / SIZE_SOL


def evaluate_rules(entry, path, wallet_exit, prop, fixed):
    """Returns {rule: return} for one copy.

    entry       (vsol, vtok) we bought against
    path        [(slots_after_entry, vsol, vtok)] at CHECKPOINTS, in order
    wallet_exit (vsol, vtok) at our exit after the wallet's first sell, or None
    """
    rets = [(k, copy_value(*entry, vs, vt, prop, fixed)) for k, vs, vt in path]
    rets = [(k, r) for k, r in rets if r is not None]
    out = {}
    if wallet_exit:
        r = copy_value(*entry, *wallet_exit, prop, fixed)
        if r is not None:
            out["follow wallet"] = r
    by_k = dict(rets)
    for h in HOLDS:
        if h in by_k:
            out[f"hold {h} slots"] = by_k[h]
    if rets:
        for tp, sl in TP_SL:
            hit = next((r for _, r in rets if r >= tp or r <= -sl), rets[-1][1])
            out[f"TP {int(tp * 100)}% / SL {int(sl * 100)}%"] = hit
    return out


def first_buys(endpoint, wallet, history, per_wallet, sleep):
    """The wallet's most recent SOL-curve buys, one per mint, newest first."""
    sigs = rpc(endpoint, "getSignaturesForAddress", [wallet, {"limit": history, "commitment": "confirmed"}]) or []
    events = []
    for s in sigs:
        if s.get("err") is not None:
            continue
        time.sleep(sleep)
        try:
            tx = rpc(endpoint, "getTransaction", [s["signature"], TX_OPTS])
        except Exception:
            continue
        events += [e for e in sol_events(tx or {}) if e["user"] == wallet]
    events.sort(key=lambda e: e["slot"] or 0)
    buys, sells = {}, collections.defaultdict(list)
    for e in events:
        if e["is_buy"]:
            buys.setdefault(e["mint"], e)       # first buy of each mint
        else:
            sells[e["mint"]].append(e)
    out = []
    for mint, b in buys.items():
        first_sell = next((s for s in sells[mint] if s["slot"] > b["slot"]), None)
        out.append((b, first_sell))
    out.sort(key=lambda bs: bs[0]["slot"], reverse=True)
    return out[:per_wallet]


def replay_buy(endpoint, buy, sell, prop, fixed):
    curve = b58encode(bonding_curve_pda(buy["mint"]))
    sigs = curve_sigs_after(endpoint, curve, buy["sig"])
    if sigs is None:
        return None
    cache = {}
    b0 = (buy["virtual_sol"], buy["virtual_token"])
    entry = state_at(endpoint, sigs, buy["mint"], buy["slot"], b0, cache)  # first in next block
    entry_slot = buy["slot"] + 1
    path = []
    state = entry
    for k in CHECKPOINTS:
        state = state_at(endpoint, sigs, buy["mint"], entry_slot + k - 1, state, cache)
        path.append((k, *state))
    wallet_exit = None
    if sell and sell["slot"] > buy["slot"]:
        wallet_exit = state_at(endpoint, sigs, buy["mint"], sell["slot"],
                               (sell["virtual_sol"], sell["virtual_token"]), cache)
    return evaluate_rules(entry, path, wallet_exit, prop, fixed)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wallets-json", default="reports/screened/kolscan_wallets.json")
    ap.add_argument("--history", type=int, default=100)
    ap.add_argument("--per-wallet", type=int, default=5)
    ap.add_argument("--sleep", type=float, default=0.1)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    endpoint = os.environ["RPC_ENDPOINT"]
    prop, fixed = SCENARIOS["measured"]

    wallets = json.load(open(args.wallets_json))
    rows = []
    for w in wallets:
        label = w.get("label") or w["pubkey"][:6]
        try:
            pairs = first_buys(endpoint, w["pubkey"], args.history, args.per_wallet, args.sleep)
        except Exception as e:
            print(f"  {label}: history failed ({e})")
            continue
        for b, s in pairs:
            try:
                res = replay_buy(endpoint, b, s, prop, fixed)
            except Exception:
                res = None
            if not res:
                continue
            for rule, ret in res.items():
                rows.append({"wallet": w["pubkey"], "label": label, "mint": b["mint"],
                             "buy_sig": b["sig"], "rule": rule, "ret": ret})
        print(f"  {label}: {len({r['buy_sig'] for r in rows if r['wallet'] == w['pubkey']})} copies priced")

    if not rows:
        print("Nothing priced today -- not an error.")
        return
    import pandas as pd
    df = pd.DataFrame(rows)
    path = args.out or f"reports/exit_rules/{datetime.now(timezone.utc):%Y%m%d}.csv"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)

    def se(x):
        return statistics.stdev(x) / len(x) ** 0.5 if len(x) > 1 else float("nan")
    summary = df.groupby("rule")["ret"].agg(n="size", mean="mean", median="median",
                                           win=lambda x: (x > 0).mean(), se=se)
    summary["s.e. above 0"] = summary["mean"] / summary["se"]
    summary = summary.sort_values("mean", ascending=False)
    print(f"\n{df['buy_sig'].nunique()} KOL buys from {df['wallet'].nunique()} wallets, entered first in the "
          f"next block, 0.25 SOL, measured fees. Return per copy by exit rule:")
    print((summary.assign(mean=summary["mean"] * 100, median=summary["median"] * 100, se=summary["se"] * 100)
           .round(2).to_string()))
    print("\n(Best-of-many is biased upward: a rule counts only if it holds on later days.)")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
