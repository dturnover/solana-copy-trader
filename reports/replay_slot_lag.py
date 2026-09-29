"""
Prices every recorded round trip as if we had copied it N slots after the
wallet -- the speed a paid gRPC stream would give us -- using only free data.

Why. At the free tier's ~4s we lose ~23% a trade; at same-block we would
make ~17%. Everything that decides whether paying for speed is worth it
lies between those two points, and nothing measured it. A gRPC stream
shows a trade about one slot (~0.4s) after it lands, and our own
transaction lands one or two slots after that: a realistic copy fills 2-3
slots behind the wallet, not in its block and not four seconds later.

How. pump.fun emits a TradeEvent for every trade, carrying the curve's
virtual reserves right after it. The RPC lists every transaction on a
bonding curve (probe_slot_history.py, 2026-09-29: 13-465 per round trip,
slot by slot). So the curve at "N slots after the wallet" is the reserves
in the last TradeEvent on that curve at or before that slot:

  entry: our fixed-size buy against the curve at wallet_buy_slot + N
  exit:  our tokens sold against the curve at wallet_sell_slot + N

Choices, all conservative:
  - "At slot s" means after EVERY trade in slot s. Within a slot we cannot
    know where our transaction would land, and on a curve a copier is chasing
    the late position is the realistic one.
  - If the wallet has already sold by the time our entry would land, the
    copy never happened (recorded as missed, not as a loss or a win).
  - N = 0 is the wallet's own post-trade curve: the same-block ceiling,
    reachable only from inside the wallet's block.
  - N = 0.5 is first in the next block: after every trade in the wallet's
    slot, before any in the next. The best a real copier can do.

Size is fixed (0.25 SOL) and fees are the "measured" scenario from
size_sweep.py, so these numbers line up with the rest of the reports.
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
import pandas as pd  # noqa: E402
from replay_same_block import TX_OPTS, decode_trade_events, rpc  # noqa: E402
from size_sweep import SCENARIOS  # noqa: E402

# 0.5 = FIRST in the next block: the curve after every trade in the wallet's
# own slot, before anything in the next one. The best any bot without
# block-builder access can do (there is no public mempool to land in the
# wallet's own block), so it bounds the whole question from above.
OFFSETS = [0, 0.5, 1, 2, 3, 5, 10]
SIZE_SOL = 0.25
LAMPORTS = 1e9
MAX_PAGES = 6


def curve_sigs_after(endpoint, curve, after_sig, before_sig=None):
    """Successful signatures on `curve` after `after_sig`, oldest first.

    Paged backwards from `before_sig` (or now) down to `after_sig`. Returns
    None if the history is too long to reach it within MAX_PAGES.
    """
    out, before = [], before_sig
    for _ in range(MAX_PAGES):
        opts = {"limit": 1000, "until": after_sig, "commitment": "confirmed"}
        if before:
            opts["before"] = before
        page = rpc(endpoint, "getSignaturesForAddress", [curve, opts]) or []
        out += page
        if len(page) < 1000:
            return [s for s in reversed(out) if s.get("err") is None]
        before = page[-1]["signature"]
    return None


def state_at(endpoint, sigs, mint, slot, fallback, cache):
    """Curve reserves after every trade on `mint` up to and including `slot`.

    `sigs` is oldest-first. Walks back from the last signature at or before
    `slot` until one carries a TradeEvent on this mint (a transaction can
    touch the curve without trading). `fallback` is the state before them.
    """
    cand = [s for s in sigs if s["slot"] <= slot]
    for s in reversed(cand):
        sig = s["signature"]
        if sig not in cache:
            try:
                tx = rpc(endpoint, "getTransaction", [sig, TX_OPTS]) or {}
            except Exception:
                tx = {}
            # A transaction can hold several trades on the same curve; the
            # last one in it is the state after it.
            ev = [e for e in decode_trade_events(tx) if e["mint"] == mint and e["virtual_sol"] > 0]
            cache[sig] = ev[-1] if ev else None
        if cache[sig]:
            return cache[sig]["virtual_sol"], cache[sig]["virtual_token"]
    return fallback


def price(vs_in, vt_in, vs_out, vt_out, prop, fixed):
    """Return on capital of a fixed-size copy bought at one curve, sold at another."""
    S = SIZE_SOL * LAMPORTS
    spend = S / (1 + prop)
    tokens = vt_in - (vs_in * vt_in) / (vs_in + spend)
    if tokens <= 0:
        return None
    gross = vs_out - (vs_out * vt_out) / (vt_out + tokens)
    return ((gross * (1 - prop) - S) / LAMPORTS - fixed) / SIZE_SOL


def replay_row(endpoint, r, prop, fixed):
    buy_tx = rpc(endpoint, "getTransaction", [r["entry_signature"], TX_OPTS])
    sell_tx = rpc(endpoint, "getTransaction", [r["sell_signature"], TX_OPTS])
    if not buy_tx or not sell_tx:
        return None, "transaction not retained"
    wallet = r["wallet"]
    be = [e for e in decode_trade_events(buy_tx) if e["mint"] == r["mint"] and e["user"] == wallet and e["is_buy"]]
    se = [e for e in decode_trade_events(sell_tx) if e["mint"] == r["mint"] and e["user"] == wallet and not e["is_buy"]]
    if not be or not se or be[-1]["virtual_sol"] == 0:
        return None, "no SOL TradeEvent for the wallet"
    b_slot, s_slot = buy_tx["slot"], sell_tx["slot"]
    b0 = (be[-1]["virtual_sol"], be[-1]["virtual_token"])
    s0 = (se[-1]["virtual_sol"], se[-1]["virtual_token"])

    entry_sigs = curve_sigs_after(endpoint, r["bonding_curve"], r["entry_signature"], r["sell_signature"])
    exit_sigs = curve_sigs_after(endpoint, r["bonding_curve"], r["sell_signature"])
    if entry_sigs is None or exit_sigs is None:
        return None, "curve history too long to page"
    cache = {}
    out = []
    for n in OFFSETS:
        row = {"offset_slots": n}
        if n >= 1 and b_slot + n >= s_slot:
            row["status"] = "missed: wallet sold before our entry landed"
        else:
            # n = 0.5 -> end of the wallet's own slot; n >= 1 -> end of slot + n.
            k = 0 if n == 0.5 else n
            vin = b0 if n == 0 else state_at(endpoint, entry_sigs, r["mint"], b_slot + k, b0, cache)
            vout = s0 if n == 0 else state_at(endpoint, exit_sigs, r["mint"], s_slot + k, s0, cache)
            ret = price(*vin, *vout, prop, fixed)
            row.update(status="priced" if ret is not None else "unpriceable", ret=ret,
                       entry_vsol=vin[0], exit_vsol=vout[0])
        out.append(row)
    return out, "ok"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default="reports/paper_trades_final.csv")
    ap.add_argument("--config", default="config/config.paper_trade.ci.json")
    ap.add_argument("--limit", type=int, default=120, help="newest round trips to replay")
    ap.add_argument("--out", default=None)
    ap.add_argument("--sleep", type=float, default=0.1)
    args = ap.parse_args()
    endpoint = os.environ["RPC_ENDPOINT"]
    prop, fixed = SCENARIOS["measured"]

    import json
    wallets = {w["label"]: w["pubkey"] for w in json.load(open(args.config))["tracked_wallets"]}
    d = pd.read_csv(args.csv)
    d = d[d["entry_signature"].notna() & d["sell_signature"].notna() & d["bonding_curve"].notna()]
    if "nonstandard_curve" in d:
        d = d[d["nonstandard_curve"].fillna(0) == 0]
    # Live entries only: a row found minutes late is not a copy of anything.
    d = d[d["entry_on_chain_age_ms"].between(0, 60_000)]
    d = d[d["wallet_label"].isin(wallets)].copy()
    d["wallet"] = d["wallet_label"].map(wallets)
    d = d.sort_values("epoch_ms", ascending=False).head(args.limit)
    print(f"Replaying {len(d)} round trips at slot offsets {OFFSETS}")

    rows, skipped = [], {}
    for _, r in d.iterrows():
        time.sleep(args.sleep)
        try:
            res, why = replay_row(endpoint, r, prop, fixed)
        except Exception as e:
            res, why = None, f"rpc error: {type(e).__name__}"
        if res is None:
            skipped[why] = skipped.get(why, 0) + 1
            continue
        for x in res:
            x.update(wallet_label=r["wallet_label"], mint=r["mint"], entry_signature=r["entry_signature"],
                     hold_s=r["hold_duration_ms"] / 1000)
            rows.append(x)
    if skipped:
        print("Skipped:", skipped)
    if not rows:
        print("Nothing replayable today (retention or quiet wallets) -- not an error.")
        return

    out = pd.DataFrame(rows)
    path = args.out or f"reports/slot_lag/{datetime.now(timezone.utc):%Y%m%d}.csv"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    out.to_csv(path, index=False)

    priced = out[out["status"] == "priced"]
    tab = priced.pivot_table(index="wallet_label", columns="offset_slots", values="ret", aggfunc="mean") * 100
    n = priced.pivot_table(index="wallet_label", columns="offset_slots", values="ret", aggfunc="size")
    missed = out[out["status"].str.startswith("missed")].groupby(["wallet_label", "offset_slots"]).size()
    print("\nMean return per copy at 0.25 SOL, measured fees, by slots behind the wallet (~0.4s/slot):")
    print(tab.round(1).to_string())
    print("\nPriced copies per cell:")
    print(n.to_string())
    if len(missed):
        print("\nMissed (wallet sold before our entry would land):")
        print(missed.unstack(fill_value=0).to_string())
    print(f"\nWrote {path}")


if __name__ == "__main__":
    main()
