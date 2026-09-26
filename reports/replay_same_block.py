"""
Prices every round trip as if we had filled in the SAME BLOCK as the wallet.

This is the best case. Copying means reacting, so we can never land before the
wallet's transaction; landing immediately after it, in the same block, is the
floor on execution lag that no infrastructure purchase can go below. If the
strategy loses money here, latency is not what is wrong with it, and gRPC
cannot rescue it. That makes this the number the gRPC decision actually turns
on -- and unlike the lag sweep, it is answerable on the free RPC we already
have.

WHY NOT replay_lag.py

That tool reconstructs the curve at an arbitrary lag by walking backwards
through the curve account's transaction history. It does not work here: the
endpoint serves no signature history for these bonding curves (half the probed
curves returned an empty first page, the rest one page and then nothing), so
there is nothing to page through and no cap that fixes it. See its docstring.

Nothing needs reconstructing for the same-block case. The wallet's own
transaction already contains the curve state immediately after their trade, in
pump.fun's TradeEvent log -- which is exactly the state we would be buying
into. One getTransaction per leg, by signatures the collector already records.

DECODING IS VALIDATED, NOT ASSUMED

The TradeEvent layout is read from the base64 blob in `Program data:` log
lines. Rather than trust the field offsets, every decode is checked against
facts recorded independently by the collector from balance deltas:

  * the event's mint must equal the row's mint
  * is_buy must match the leg being priced
  * the event's token_amount must equal the collector's wallet_token_amount
  * where the event carries real reserves, virtual - real must equal the
    offsets already verified across 1,480 collector snapshots

A decode that fails these is discarded, and the run aborts if the match rate
is low -- because a plausible-looking wrong offset is precisely the failure
mode that has produced five silent defects in this repo already.

FEES ARE MEASURED, NOT ASSUMED

The collector's simulate_buy_sol_cost applies no fee, while the wallet's
recorded lamports come from its actual SOL balance delta and therefore include
pump.fun's fee. Comparing the two directly flatters us by whatever that fee
is. So the fee is measured here from the gap between the event's sol_amount
and the collector's wallet_lamports_spent, reported, and applied.
"""

import argparse
import base64
import collections
import json
import os
import struct
import sys
import time
import urllib.request

import pandas as pd

# Verified across 1,480 collector snapshots that logged real and virtual
# reserves side by side (see replay_lag.py validate_offsets). Used here only as
# an independent check on the decoded event layout.
VIRTUAL_SOL_OFFSET = 30_000_000_000
VIRTUAL_TOKEN_OFFSET = 279_900_000_000_000

LAMPORTS_PER_SOL = 1_000_000_000.0

# Exactly what src/rpc/rpc_client.cpp sends. The collector fetched every one of
# these transactions successfully at the time, so anything it can do, this can.
TX_OPTS = {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1,
           "commitment": "confirmed"}

# How many rows, spread across the dataset's span, to test before pricing.
# getTransaction returns null for a transaction the endpoint no longer retains,
# and null is indistinguishable from a bad request -- so the horizon gets
# measured rather than discovered as a wall of failures.
RETENTION_PROBE_ROWS = 8

# Field offsets within the base64 `Program data:` blob, after the 8-byte event
# discriminator. Treated as a hypothesis that every decode must earn.
OFF_MINT = 8
OFF_SOL_AMOUNT = 40
OFF_TOKEN_AMOUNT = 48
OFF_IS_BUY = 56
OFF_USER = 57
OFF_TIMESTAMP = 89
OFF_VIRTUAL_SOL = 97
OFF_VIRTUAL_TOKEN = 105
OFF_REAL_SOL = 113
OFF_REAL_TOKEN = 121
MIN_EVENT_LEN = 113          # through virtual_token_reserves
EXTENDED_EVENT_LEN = 129     # through real_token_reserves, when present

# Below this share of decodes matching the collector's independently recorded
# token amounts, the layout hypothesis is wrong and nothing may be priced.
MIN_DECODE_MATCH_RATE = 0.90

# ...but a RATE means nothing on a handful of rows. Two odd transactions out of
# fifteen is 86.7%, which tripped this gate on 2026-09-23 and refused to price
# thirteen perfectly good round trips. With collection at a few trades a day and
# a two-day retention window, small samples are the normal case, not the
# exception. The gate now needs enough rows to be a rate at all.
MIN_ROWS_FOR_LAYOUT_VERDICT = 30

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(raw):
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + out


def rpc(endpoint, method, params, retries=4):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for attempt in range(retries):
        try:
            req = urllib.request.Request(endpoint, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                out = json.loads(r.read())
            if "error" in out:
                raise RuntimeError(out["error"])
            return out.get("result")
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))
    return None


def decode_trade_events(tx):
    """Every TradeEvent-shaped blob in a transaction's logs, decoded.

    Returns dicts; validity is the caller's job, since only the caller knows
    what the event is supposed to say.
    """
    events = []
    for line in (tx.get("meta") or {}).get("logMessages") or []:
        if not line.startswith("Program data: "):
            continue
        try:
            raw = base64.b64decode(line[len("Program data: "):])
        except Exception:
            continue
        if len(raw) < MIN_EVENT_LEN:
            continue
        e = {
            "mint": b58encode(raw[OFF_MINT:OFF_MINT + 32]),
            "sol_amount": struct.unpack_from("<Q", raw, OFF_SOL_AMOUNT)[0],
            "token_amount": struct.unpack_from("<Q", raw, OFF_TOKEN_AMOUNT)[0],
            "is_buy": raw[OFF_IS_BUY] == 1,
            "user": b58encode(raw[OFF_USER:OFF_USER + 32]),
            "virtual_sol": struct.unpack_from("<Q", raw, OFF_VIRTUAL_SOL)[0],
            "virtual_token": struct.unpack_from("<Q", raw, OFF_VIRTUAL_TOKEN)[0],
            "real_sol": None,
            "real_token": None,
        }
        if len(raw) >= EXTENDED_EVENT_LEN:
            e["real_sol"] = struct.unpack_from("<Q", raw, OFF_REAL_SOL)[0]
            e["real_token"] = struct.unpack_from("<Q", raw, OFF_REAL_TOKEN)[0]
        events.append(e)
    return events


def offsets_ok(e):
    """virtual - real equals the constants verified across 1,480 snapshots.

    An independent check on the field offsets, available per event: getting
    them wrong would not reproduce two exact constants by chance.
    """
    return (
        e["real_sol"] is not None
        and e["virtual_sol"] - e["real_sol"] == VIRTUAL_SOL_OFFSET
        and e["virtual_token"] - e["real_token"] == VIRTUAL_TOKEN_OFFSET
    )


def pick_event(tx, mint, is_buy, token_amount, checks, leg):
    """The wallet's own trade event on this mint, or None.

    On the BUY leg the token amount must match what the collector derived
    independently from balance deltas -- that agreement is what confirms the
    field offsets are right, so it stays strict.

    On the SELL leg it must not. We mirror the wallet's buy size, but the
    wallet is free to exit a different amount than it entered (that is what
    incomplete_position flags), and their exit size has no bearing on ours: we
    sell OUR tokens into the curve as it stands after their sell, whatever size
    theirs was. Requiring the two to be equal rejected real partial exits as
    decode failures -- it discarded 8 of 25 rows and read as a layout problem.
    """
    found = decode_trade_events(tx)
    if not found:
        checks[f"{leg}: no TradeEvent in logs"] += 1
        return None

    candidates = [e for e in found if e["mint"] == mint and e["is_buy"] == is_buy]
    if not candidates:
        checks[f"{leg}: no event on this mint/side"] += 1
        return None

    exact = [e for e in candidates if e["token_amount"] == token_amount]
    if is_buy:
        if not exact:
            checks["buy: token_amount disagrees with collector (layout suspect)"] += 1
            return None
        e = dict(exact[0])
    else:
        # Largest sell on the mint is the wallet's own; a co-landing bot's sell
        # would be a separate, smaller event.
        e = dict(exact[0] if exact else max(candidates, key=lambda x: x["token_amount"]))
        e["size_differs"] = not exact

    e["offsets_ok"] = offsets_ok(e)
    if not e["offsets_ok"]:
        checks[f"{leg}: reserve offsets wrong (layout suspect)"] += 1
        return None
    return e


def layout_verdict(priced, attempted, offsets_confirmed):
    """'price', 'price-small-sample', 'price-offsets-confirmed' or 'abort'.

    A low match rate only indicts the TradeEvent layout when the sample is big
    enough for a rate to mean anything AND the decodes that did succeed fail to
    reproduce the reserve constants. Pure, so it is unit-tested directly -- the
    previous inline version refused to price 13 good round trips out of 15.
    """
    rate = priced / attempted if attempted else 0.0
    if rate >= MIN_DECODE_MATCH_RATE:
        return "price"
    if attempted < MIN_ROWS_FOR_LAYOUT_VERDICT:
        return "price-small-sample"
    if offsets_confirmed == priced:
        return "price-offsets-confirmed"
    return "abort"


def buy_cost(v_sol, v_tok, tokens_out):
    if tokens_out <= 0 or tokens_out >= v_tok:
        return None
    return (v_sol * v_tok) / (v_tok - tokens_out) - v_sol


def sell_proceeds(v_sol, v_tok, tokens_in):
    if tokens_in <= 0:
        return None
    return v_sol - (v_sol * v_tok) / (v_tok + tokens_in)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="?", default="reports/paper_trades_final.csv")
    ap.add_argument("out", nargs="?", default="reports/same_block_trades.csv")
    ap.add_argument("--endpoint", default=os.environ.get("RPC_ENDPOINT", ""))
    ap.add_argument("--limit", type=int, default=300,
                    help="round trips to price (2 RPC calls each)")
    ap.add_argument("--fee-bps", type=int, default=None,
                    help="override the fee measured from the data, in basis points")
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    if "collector_version" not in df.columns:
        sys.exit("No collector_version column -- this CSV predates same-block replay.")
    df = df[df["collector_version"] >= 3]
    if df.empty:
        sys.exit("No collector v3+ rows. Only v3 records the signatures this needs.")

    # Single-buy positions only. With buy_count > 1 the collector recorded one
    # entry signature but a token total accumulated over several buys, so
    # pricing the whole position at the first buy's curve state would understate
    # the cost -- later buys pushed the price up. Excluded rather than fudged.
    usable = df[
        df["entry_signature"].notna() & (df["entry_signature"] != "")
        & df["sell_signature"].notna() & (df["sell_signature"] != "")
        & (df["buy_count"] == 1)
        & (df["wallet_token_amount"] > 0)
    ]
    excluded_multi = int((df["buy_count"] > 1).sum())
    # Non-standard curves (e.g. quoted in another token, whose events carry no
    # SOL reserves) would fail the offset check and read as a layout fault.
    # They are not one; leave them out before the layout gate sees them.
    if "nonstandard_curve" in usable.columns:
        n_quote = int(usable["nonstandard_curve"].fillna(0).astype(int).sum())
        usable = usable[usable["nonstandard_curve"].fillna(0).astype(int) == 0]
        if n_quote:
            print(f"Skipping {n_quote} round trip(s) on non-standard curves")

    # Newest first. The dataset is time-ordered, so head() silently selected the
    # oldest rows -- the ones an RPC is least likely to still retain, which is
    # how the first run got null for all 25.
    usable = usable.sort_values("epoch_ms", ascending=False).head(args.limit)

    if not args.endpoint:
        sys.exit("Set --endpoint or RPC_ENDPOINT.")

    span = pd.to_datetime(usable["epoch_ms"], unit="ms")
    print(f"Pricing {len(usable)} single-buy round trips at same-block execution "
          f"({excluded_multi} multi-buy positions excluded)")
    print(f"Selected rows span {span.min():%Y-%m-%d} to {span.max():%Y-%m-%d}\n")

    # Measure how far back the endpoint still serves transactions, before
    # spending the budget. A transaction it no longer retains comes back as a
    # null result, not an error, so an unmeasured horizon looks like a bug.
    all_rows = df[df["entry_signature"].notna() & (df["entry_signature"] != "")]
    all_rows = all_rows.sort_values("epoch_ms")
    probe_idx = [int(i * (len(all_rows) - 1) / (RETENTION_PROBE_ROWS - 1))
                 for i in range(RETENTION_PROBE_ROWS)]
    now_ms = pd.Timestamp.now("UTC").value // 1_000_000
    print("Retention probe (can the endpoint still serve these?):")
    newest_missing = None
    served = {}
    for i in probe_idx:
        row = all_rows.iloc[i]
        age_d = (now_ms - int(row["epoch_ms"])) / 86_400_000
        try:
            got = rpc(args.endpoint, "getTransaction", [row["entry_signature"], TX_OPTS])
        except Exception as e:
            print(f"  {age_d:5.1f}d old  ERROR {type(e).__name__}")
            continue
        ok = got is not None
        served[i] = ok
        print(f"  {age_d:5.1f}d old  {'served' if ok else 'NOT RETAINED (null)'}")
        if not ok:
            newest_missing = age_d if newest_missing is None else min(newest_missing, age_d)
    # Bisect between the oldest transaction still served and the newest one
    # already gone, to turn "somewhere between 0.1 and 8.8 days" into a usable
    # number. One RPC call per step, and the answer is a project deadline: past
    # this age a recorded round trip can never be re-priced by anything.
    lo = max((i for i in probe_idx if served.get(i)), default=None)   # oldest served
    hi = min((i for i in probe_idx if served.get(i) is False), default=None)
    if lo is not None and hi is not None and lo > hi:
        # Bisecting on row INDEX, not on time. With a non-uniform time
        # distribution six steps could not close a 1,476-row gap, so
        # served_age stayed at the newest probe (0.2 days) and the filter threw
        # away every row that was actually still retained -- the 2026-09-10 run
        # priced 1 round trip instead of roughly a dozen. Enough steps to
        # converge fully costs a handful of extra calls and is worth it.
        for _ in range(14):
            mid = (lo + hi) // 2
            if mid == lo or mid == hi:
                break
            row = all_rows.iloc[mid]
            try:
                got = rpc(args.endpoint, "getTransaction", [row["entry_signature"], TX_OPTS])
            except Exception:
                break
            if got is not None:
                lo = mid
            else:
                hi = mid
        served_age = (now_ms - int(all_rows.iloc[lo]["epoch_ms"])) / 86_400_000
        gone_age = (now_ms - int(all_rows.iloc[hi]["epoch_ms"])) / 86_400_000
        print(f"  -> retention horizon is between {served_age:.1f} and {gone_age:.1f} days")
        ages_d = (now_ms - all_rows["epoch_ms"]) / 86_400_000
        replayable = int((ages_d <= served_age).sum())
        print(f"  -> {replayable} of {len(all_rows)} recorded round trips are still "
              f"young enough to replay; the rest are permanently unpriceable")

        # Drop rows past the horizon before spending calls on them. They come
        # back null, and counting those as decode failures would trip the
        # layout guard -- which exists to catch a wrong offset, not an expired
        # transaction. Keeping them apart is what lets the guard stay strict.
        keep = (now_ms - usable["epoch_ms"]) / 86_400_000 <= served_age
        dropped_old = int((~keep).sum())
        usable = usable[keep]
        if dropped_old:
            print(f"  -> dropping {dropped_old} selected row(s) already past the horizon")
        if usable.empty:
            # Not a fault. On a slow collection day there is simply nothing
            # young enough to price, and a daily job that exits non-zero for
            # that emails a failure notice for a normal outcome. Reserve
            # failure for things that are actually wrong.
            print("Nothing young enough to price today -- every selected round trip "
                  "is past the retention horizon. Not an error.")
            sys.exit(0)
    elif newest_missing is not None:
        print(f"  -> history is gone by {newest_missing:.1f} days; only fresher "
              f"round trips can be replayed at all")
    print()

    checks = collections.Counter()
    offsets_confirmed = 0
    rows, fee_samples = [], []
    partial_exits = 0

    for _, r in usable.iterrows():
        mint = r["mint"]
        try:
            buy_tx = rpc(args.endpoint, "getTransaction",
                         [r["entry_signature"], TX_OPTS])
            sell_tx = rpc(args.endpoint, "getTransaction",
                          [r["sell_signature"], TX_OPTS])
        except Exception as e:
            checks[f"rpc error: {type(e).__name__}"] += 1
            continue
        if not buy_tx or not sell_tx:
            checks["transaction not returned"] += 1
            continue

        tokens = int(r["wallet_token_amount"])
        be = pick_event(buy_tx, mint, True, tokens, checks, "buy")
        se = pick_event(sell_tx, mint, False, tokens, checks, "sell")
        if not be or not se:
            continue
        offsets_confirmed += 1  # pick_event already rejected any event failing the check
        partial_exits += int(bool(se.get("size_differs")))

        # The wallet's recorded lamports include the fee; the event's
        # sol_amount is the trade itself. The gap is the fee, measured.
        if be["sol_amount"] > 0:
            fee_samples.append(float(r["wallet_lamports_spent"]) / be["sol_amount"] - 1.0)

        # Post-trade reserves: exactly the curve we would be trading into one
        # slot behind them, on both legs.
        cost = buy_cost(float(be["virtual_sol"]), float(be["virtual_token"]), float(tokens))
        proceeds = sell_proceeds(float(se["virtual_sol"]), float(se["virtual_token"]), float(tokens))
        if cost is None or proceeds is None or cost <= 0:
            checks["curve maths out of range"] += 1
            continue

        rows.append({
            "wallet_label": r["wallet_label"], "mint": mint,
            "epoch_ms": r["epoch_ms"],
            "entry_signature": r["entry_signature"],
            "wallet_pnl_sol": float(r["wallet_pnl_sol"]),
            "lagged_pnl_sol": float(r["our_pnl_sol"]),
            "raw_cost_lamports": cost,
            "raw_proceeds_lamports": proceeds,
            "wallet_cost_lamports": float(r["wallet_lamports_spent"]),
            # The curve itself, just after each of the wallet's legs. With these
            # saved, any copy size can be re-priced offline forever -- after the
            # RPC has long forgotten the transactions. Without them, the
            # fixed-size sweep has to reconstruct them from the constant-product
            # invariant (see size_sweep.py).
            "buy_vs": float(be["virtual_sol"]),
            "sell_vs": float(se["virtual_sol"]),
        })

    if checks:
        print("Decode/fetch outcomes:")
        for why, n in checks.most_common():
            print(f"  {n:>5}  {why}")
        print()

    if not rows:
        # Distinguish "no input" from "input we could not decode". The first is
        # a quiet day; the second means the layout is broken and must be loud.
        decode_failures = sum(n for why, n in checks.items() if "disagree" in why or "layout" in why)
        if decode_failures:
            sys.exit(f"Nothing priced and {decode_failures} decode failure(s) -- the "
                     "TradeEvent field offsets in this script are likely wrong. Fix "
                     "those rather than relaxing the check.")
        print("Nothing priced -- no usable round trips reached the pricing stage "
              "(see the outcomes above). Not a decode problem.")
        sys.exit(0)

    attempted = len(rows) + sum(checks.values())
    match_rate = len(rows) / attempted if attempted else 0.0
    print(f"Decoded and validated {len(rows)} of {attempted} round trips "
          f"({100 * match_rate:.1f}%)")
    print(f"Reserve offsets independently confirmed on {offsets_confirmed} of {len(rows)} "
          f"({100 * offsets_confirmed / len(rows):.1f}%)")
    print(f"Wallet exited a different size than it entered on {partial_exits} "
          f"({100 * partial_exits / len(rows):.1f}%) -- ours is priced at our own size regardless")
    # Two independent signals, and only their combination indicts the layout:
    # a low match rate, AND a sample big enough for that rate to mean something.
    # A third signal exonerates it outright -- if every decode that succeeded
    # also reproduced both reserve constants, the field offsets are provably
    # right and the failures are individual odd transactions (a different
    # program version, a venue we do not model), not a systemic break.
    verdict = layout_verdict(len(rows), attempted, offsets_confirmed)
    if verdict != "price":
        if verdict == "price-small-sample":
            print(f"\n!  Match rate {100 * match_rate:.1f}% on only {attempted} attempted "
                  f"round trips -- too few for that rate to indict the layout. Pricing "
                  f"the {len(rows)} that decoded cleanly.", file=sys.stderr)
        elif verdict == "price-offsets-confirmed":
            print(f"\n!  Match rate {100 * match_rate:.1f}%, but all {len(rows)} successful "
                  "decodes reproduced both reserve constants -- the offsets are right and "
                  "the failures are per-transaction, not systemic. Pricing anyway.",
                  file=sys.stderr)
        else:
            sys.exit(f"\nMatch rate {100 * match_rate:.1f}% over {attempted} round trips, "
                     f"and the successful decodes do not all confirm the reserve "
                     f"constants -- the layout hypothesis is not holding up. Refusing to "
                     "price on a decode this shaky.")

    out = pd.DataFrame(rows)

    # Fee, measured rather than assumed.
    fee_series = pd.Series(fee_samples)
    measured_bps = float(fee_series.median() * 10_000)
    fee_bps = args.fee_bps if args.fee_bps is not None else round(measured_bps)
    print(f"\nFee measured from wallet lamports vs event sol_amount: "
          f"median {measured_bps:.1f} bps "
          f"(p25 {fee_series.quantile(0.25) * 10000:.1f}, "
          f"p75 {fee_series.quantile(0.75) * 10000:.1f}); applying {fee_bps} bps per leg")

    f = fee_bps / 10_000.0
    out["our_cost_lamports"] = out["raw_cost_lamports"] * (1 + f)
    out["our_proceeds_lamports"] = out["raw_proceeds_lamports"] * (1 - f)
    out["same_block_pnl_sol"] = (out["our_proceeds_lamports"] - out["our_cost_lamports"]) / LAMPORTS_PER_SOL
    out["fill_ratio"] = out["our_cost_lamports"] / out["wallet_cost_lamports"]
    out.to_csv(args.out, index=False)

    n = len(out)
    same_block = out["same_block_pnl_sol"].sum()
    lagged = out["lagged_pnl_sol"].sum()
    wallet = out["wallet_pnl_sol"].sum()

    print(f"\n=== {n} round trips, same-block execution vs what we recorded ===\n")
    print(f"  wallet's own P&L         {wallet:+10.2f} SOL")
    print(f"  ours at same-block       {same_block:+10.2f} SOL   "
          f"(win rate {100 * (out['same_block_pnl_sol'] > 0).mean():.1f}%)")
    print(f"  ours at recorded ~18.5s  {lagged:+10.2f} SOL   "
          f"(win rate {100 * (out['lagged_pnl_sol'] > 0).mean():.1f}%)")
    print(f"\n  cost of latency          {same_block - lagged:+10.2f} SOL "
          f"-- the most any speed purchase could recover")
    print(f"  median fill vs wallet    {out['fill_ratio'].median():10.4f}x")

    print("\nBy wallet, same-block:")
    g = out.groupby("wallet_label").agg(
        trades=("same_block_pnl_sol", "size"),
        same_block_sol=("same_block_pnl_sol", "sum"),
        lagged_sol=("lagged_pnl_sol", "sum"),
        wallet_sol=("wallet_pnl_sol", "sum"),
    ).sort_values("same_block_sol", ascending=False).round(2)
    print(g.to_string())

    print(f"\nWrote {args.out}")
    # This sentence decided the gRPC question once. It should not be printed
    # off a handful of round trips, and it must not be printed off a sample
    # dominated by one wallet -- the original verdict came from 57 rows of
    # which 38 were a single wallet since removed as a conclusive loser.
    top_share = out["wallet_label"].value_counts(normalize=True).iloc[0]
    if same_block <= 0 and n >= 40 and top_share <= 0.5:
        print("\nSame-block execution still loses money. Latency is not the binding "
              "problem, and no infrastructure purchase changes this -- it is the floor.")
    elif same_block <= 0:
        print(f"\nSame-block is negative here, but this sample cannot settle it: "
              f"n={n}"
              + (f", and {100 * top_share:.0f}% of it is one wallet"
                 if top_share > 0.5 else "")
              + ". Not a verdict on latency.")


if __name__ == "__main__":
    main()
