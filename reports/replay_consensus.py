"""
Does a coin go up after SEVERAL KOLs buy it within a few minutes?

Background. Copying any single KOL loses at the best reachable speed (first
in the next block): -18.8% following their sell, -3.8% with the best exit of
our own, over 2,926 buys / 230 wallets / 41 days (replay_exit_rules.py).
That's one KOL's buy as the signal. This asks whether agreement between
KOLs is a better one: when the K-th distinct KOL buys a mint within WINDOW
of the first, we buy first in the next block after that K-th buy.

Same entry model, exit rules, size (0.25 SOL) and measured fees as
replay_exit_rules.py, so the numbers compare directly. The "follow wallet"
rule doesn't apply (there's no single wallet to follow).

Coverage caveat. Each KOL's buys come from its newest --history signatures,
which spans hours for a busy wallet and weeks for a quiet one. A KOL buy
outside that span is invisible, so some consensus events are missed and
some are signalled later than they really were (the true K-th buy may be
hidden). Both make this conservative about how often the signal fires, not
about its return once it does.

Each signal is one (mint, K) pair. The same mint shows up for K=2 and K=3
at different entries, so pool within one K, not across them.
"""

import argparse
import json
import os
import statistics
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from replay_exit_rules import first_buys, replay_buy  # noqa: E402
from size_sweep import SCENARIOS  # noqa: E402

KS = [2, 3, 4]
# Window from the first KOL's buy to the K-th, in slots (~0.4s each). The
# analysis can tighten it after the fact with the lag_slots column.
WINDOW_SLOTS = 1500  # ~10 minutes


def consensus_signals(buys, ks=KS, window_slots=WINDOW_SLOTS):
    """Finds the K-th distinct KOL buy of each mint.

    buys   iterable of (wallet, buy_event); buy_event has mint, slot, sig
    Returns [(k, mint, kth_buy_event, lag_slots, wallets_in_order)] where
    lag_slots is the K-th buy's slot minus the first KOL buy's slot. Only
    a wallet's FIRST buy of a mint counts, so one KOL buying twice is not
    agreement.
    """
    by_mint = {}
    for wallet, b in buys:
        firsts = by_mint.setdefault(b["mint"], {})
        if wallet not in firsts or b["slot"] < firsts[wallet]["slot"]:
            firsts[wallet] = b
    out = []
    for mint, firsts in by_mint.items():
        order = sorted(firsts.items(), key=lambda wb: wb[1]["slot"])
        t0 = order[0][1]["slot"]
        for k in ks:
            if len(order) < k:
                break
            wallet_k, b_k = order[k - 1]
            lag = b_k["slot"] - t0
            if lag > window_slots:
                break  # later K's are later still
            out.append((k, mint, b_k, lag, [w for w, _ in order[:k]]))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wallets-json", default="reports/screened/kolscan_wallets.json")
    ap.add_argument("--history", type=int, default=150)
    ap.add_argument("--sleep", type=float, default=0.1)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    endpoint = os.environ["RPC_ENDPOINT"]
    prop, fixed = SCENARIOS["measured"]

    wallets = json.load(open(args.wallets_json))
    labels = {w["pubkey"]: (w.get("label") or w["pubkey"][:6]) for w in wallets}
    buys = []
    for w in wallets:
        try:
            pairs = first_buys(endpoint, w["pubkey"], args.history, 10**6, args.sleep)
        except Exception as e:
            print(f"  {labels[w['pubkey']]}: history failed ({e})")
            continue
        buys += [(w["pubkey"], b) for b, _ in pairs]
        print(f"  {labels[w['pubkey']]}: {len(pairs)} mints bought")

    signals = consensus_signals(buys)
    print(f"\n{len(buys)} KOL first-buys, {len({b['mint'] for _, b in buys})} mints; "
          f"consensus signals: " + ", ".join(f"K={k}: {sum(s[0] == k for s in signals)}" for k in KS))

    rows = []
    for k, mint, b, lag, ws in signals:
        try:
            res = replay_buy(endpoint, b, None, prop, fixed)
        except Exception:
            res = None
        if not res:
            continue
        for rule, ret in res.items():
            rows.append({"k": k, "mint": mint, "signal_sig": b["sig"], "signal_slot": b["slot"],
                         "lag_slots": lag, "wallets": "|".join(labels.get(x, x[:6]) for x in ws),
                         "rule": rule, "ret": ret})

    if not rows:
        print("Nothing priced today -- not an error.")
        return
    import pandas as pd
    df = pd.DataFrame(rows)
    path = args.out or f"reports/consensus/{datetime.now(timezone.utc):%Y%m%d}.csv"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)

    def se(x):
        return statistics.stdev(x) / len(x) ** 0.5 if len(x) > 1 else float("nan")
    for k, g in df.groupby("k"):
        s = g.groupby("rule")["ret"].agg(n="size", mean="mean", win=lambda x: (x > 0).mean(), se=se)
        s["s.e. above 0"] = s["mean"] / s["se"]
        s = s.sort_values("mean", ascending=False)
        print(f"\nK={k}: buy first in the next block after the {k}th KOL buys within ~10 min. Return per trade:")
        print(s.assign(mean=s["mean"] * 100, se=s["se"] * 100).round(2).to_string())
    print("\nBaseline (one KOL, replay_exit_rules.py, 41 days): best rule -3.8% +/- 0.2%.")
    print("Best-of-many is biased upward: a rule counts only if it holds on later days.")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
