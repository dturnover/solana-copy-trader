"""
Finds wallets worth a tracking slot, from pump.fun's own trade events.

Why now. Collection works again (2026-09-25) but only Sheep trades often
enough to matter: ~1 closed round trip an hour across four tracked wallets,
which is too slow to answer anything. And the wallets removed as "inactive"
were judged by a parser that could not read sell_v2, the newer buy
instructions, or version-1 transactions -- some of that inactivity was ours.

Method. Everything is read from the TradeEvent pump.fun emits for every
trade, whichever instruction produced it, so nothing here depends on the
instruction decoder that failed before.

  1. Discover: sample recent pump.fun program transactions and collect the
     wallets behind the SOL-quoted trade events in them.
  2. Profile: for each candidate (discovered + previously removed + tracked),
     read its recent history, pair its own buys and sells per mint (FIFO),
     and measure what matters for a slot:
       - closed round trips per day      (data volume -- the bottleneck)
       - median hold                      (copyable at our ~4s fill? needs >> 4s)
       - its own SOL P&L and win rate     (is there anything to copy)
  Non-SOL-quoted trades (sol_amount = 0) are skipped: we cannot price them.

Output is a ranking, not a decision. Nothing is promoted on looking good
over a few days of fat-tailed data; this only says who is worth watching.
"""

import argparse
import collections
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from replay_same_block import TX_OPTS, decode_trade_events, rpc  # noqa: E402

PUMPFUN = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
CONFIG = "config/config.paper_trade.ci.json"
REMOVED = "config/REMOVED_WALLETS.md"
LAMPORTS = 1e9

# A hold this short is gone before our ~2.4s detection + 1.5s fill lands.
MIN_COPYABLE_HOLD_S = 10.0


def sol_events(tx):
    """SOL-quoted TradeEvents in a transaction, with the block time attached."""
    out = []
    for e in decode_trade_events(tx):
        if e["sol_amount"] > 0 and e["virtual_sol"] > 0:
            e["t"] = tx.get("blockTime") or 0
            out.append(e)
    return out


def discover(endpoint, pages, sample_every, sleep):
    """Wallets behind recent SOL-quoted pump.fun trades, by how often seen."""
    seen = collections.Counter()
    before = None
    fetched = 0
    for _ in range(pages):
        opts = {"limit": 1000, "commitment": "confirmed"}
        if before:
            opts["before"] = before
        sigs = rpc(endpoint, "getSignaturesForAddress", [PUMPFUN, opts]) or []
        if not sigs:
            break
        before = sigs[-1]["signature"]
        for s in sigs[::sample_every]:
            if s.get("err") is not None:
                continue
            time.sleep(sleep)
            try:
                tx = rpc(endpoint, "getTransaction", [s["signature"], TX_OPTS])
            except Exception:
                continue
            fetched += 1
            for e in sol_events(tx or {}):
                seen[e["user"]] += 1
    print(f"discover: {fetched} program transactions sampled, {len(seen)} distinct traders")
    return seen


def pair_round_trips(events):
    """FIFO-pair one wallet's buys and sells per mint into round trips.

    A sell closes the oldest open buy lots first; a sell with no open lots
    (bought before the window) is ignored rather than guessed at. Partial
    sells close only the tokens they sold.
    """
    events = sorted(events, key=lambda e: e["t"])
    lots = collections.defaultdict(collections.deque)  # mint -> [tokens, cost, t]
    trips = []
    for e in events:
        if e["is_buy"]:
            lots[e["mint"]].append([e["token_amount"], e["sol_amount"], e["t"]])
            continue
        remaining, cost, first_t = e["token_amount"], 0.0, None
        q = lots[e["mint"]]
        while remaining > 0 and q:
            tok, c, t = q[0]
            take = min(tok, remaining)
            cost += c * take / tok
            first_t = t if first_t is None else first_t
            q[0][0] -= take
            q[0][1] -= c * take / tok
            remaining -= take
            if q[0][0] <= 0:
                q.popleft()
        if first_t is not None and cost > 0:
            matched = e["token_amount"] - remaining
            trips.append({"pnl": (e["sol_amount"] * matched / e["token_amount"] - cost) / LAMPORTS,
                          "hold_s": e["t"] - first_t})
    return trips


def profile(endpoint, wallet, limit, sleep):
    sigs = rpc(endpoint, "getSignaturesForAddress", [wallet, {"limit": limit, "commitment": "confirmed"}]) or []
    sigs = [s for s in sigs if s.get("err") is None]
    events = []
    for s in sigs:
        time.sleep(sleep)
        try:
            tx = rpc(endpoint, "getTransaction", [s["signature"], TX_OPTS])
        except Exception:
            continue
        events += [e for e in sol_events(tx or {}) if e["user"] == wallet]
    times = [s.get("blockTime") for s in sigs if s.get("blockTime")]
    span_days = max((max(times) - min(times)) / 86400, 1 / 24) if len(times) > 1 else None

    trips = pair_round_trips(events)
    holds = [t["hold_s"] for t in trips]
    return {
        "wallet": wallet,
        "sigs_scanned": len(sigs),
        "span_days": round(span_days, 2) if span_days else None,
        "sol_trades": len(events),
        "round_trips": len(trips),
        "trips_per_day": round(len(trips) / span_days, 1) if span_days else 0,
        "median_hold_s": round(statistics.median(holds), 1) if holds else None,
        "copyable_share": round(sum(h >= MIN_COPYABLE_HOLD_S for h in holds) / len(holds), 2) if holds else None,
        "win_rate": round(sum(t["pnl"] > 0 for t in trips) / len(trips), 2) if trips else None,
        "pnl_sol": round(sum(t["pnl"] for t in trips), 3),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=2, help="pages of 1000 program signatures to sample")
    ap.add_argument("--sample-every", type=int, default=5)
    ap.add_argument("--top", type=int, default=25, help="discovered wallets to profile")
    ap.add_argument("--history", type=int, default=100, help="signatures of history per wallet")
    ap.add_argument("--sleep", type=float, default=0.15)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    endpoint = os.environ["RPC_ENDPOINT"]

    tracked = {w["pubkey"]: w["label"] for w in json.load(open(CONFIG))["tracked_wallets"]}
    removed = dict((pk, name) for name, pk in re.findall(r"`([^`]+)` \(([1-9A-HJ-NP-Za-km-z]{32,44})\)",
                                                          open(REMOVED).read()))
    seen = discover(endpoint, args.pages, args.sample_every, args.sleep)
    # Seen more than once in a thin sample = trades often. Skip the tracked
    # and removed here; they are profiled below under their own names.
    found = [w for w, n in seen.most_common() if n >= 2 and w not in tracked and w not in removed][:args.top]

    cands = [(w, tracked[w], "tracked") for w in tracked]
    cands += [(w, removed[w], "removed") for w in removed]
    cands += [(w, w[:6], f"discovered x{seen[w]}") for w in found]
    rows = []
    for w, label, source in cands:
        try:
            r = profile(endpoint, w, args.history, args.sleep)
        except Exception as e:
            print(f"  {label}: failed ({e})")
            continue
        r.update(label=label, source=source)
        rows.append(r)
        print(f"  {label:<12} {source:<14} trips/day={r['trips_per_day']:<6} hold={r['median_hold_s']}s "
              f"copyable={r['copyable_share']} win={r['win_rate']} pnl={r['pnl_sol']} SOL")

    import pandas as pd
    df = pd.DataFrame(rows)
    # Worth a slot = trades often AND holds long enough to copy. Profit is
    # shown, not ranked on: a few days of it says little.
    df["copyable_trips_per_day"] = (df["trips_per_day"] * df["copyable_share"].fillna(0)).round(1)
    df = df.sort_values("copyable_trips_per_day", ascending=False)
    out = args.out or f"reports/screened/discovered_{datetime.now(timezone.utc):%Y%m%d}.csv"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    df.to_csv(out, index=False)
    cols = ["label", "source", "copyable_trips_per_day", "trips_per_day", "median_hold_s",
            "copyable_share", "win_rate", "pnl_sol", "span_days"]
    print("\nRanked by copyable round trips per day (hold >= %.0fs):" % MIN_COPYABLE_HOLD_S)
    print(df[cols].head(30).to_string(index=False))
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
