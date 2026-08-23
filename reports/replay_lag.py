"""
Re-prices recorded round trips at ANY execution lag, from transaction history.

This is the tool paper_trade was always supposed to be. paper_trade prices a
fill by sleeping execution_lag_ms from the moment IT noticed the trade and then
reading the bonding curve as it stands right then -- so on the free poll engine,
where noticing already takes ~17s, a config of 1500ms produces fills priced
~18.5s after the wallet actually traded. No configuration changes that: the
tool can only ever measure the latency its own poller happened to have.

Nothing about answering "would this work at 1.5s?" requires having 1.5s
infrastructure. The chain records what happened. Given a wallet's buy, we can
reconstruct what the curve looked like one second later and price a fill
against it, at leisure, on a free RPC. That is what this does, and sweeping the
target lag produces the curve that actually decides whether paying for gRPC is
worth anything.

HOW THE CURVE IS RECONSTRUCTED

Not from raw account balances. The bonding curve account's lamport balance
includes its rent-exempt minimum, which is not part of real_sol_reserves, and
guessing that constant is exactly the class of assumption that has produced
four silent data defects in this repo already.

Instead it walks from a KNOWN state using DIFFERENCES, in which any such
constant cancels:

  1. The collector logged the curve's exact reserves at a known moment
     (entry_*_reserves, read from account data at entry_block_time_ms +
     entry_on_chain_age_ms + execution_lag_ms).
  2. Every transaction touching the curve between the target time and that
     moment changed its balances by an amount visible as a pre/post delta.
  3. Subtract those deltas from the known state to get the state at the target.

Virtual reserves come from real ones by a fixed offset. That is not assumed --
it is verified against the collector's own paired readings on startup, and
measured at 30 SOL and 279,900,000e6 across 1,088 of 1,089 v3 rows.

STATUS: THE WALK DOES NOT REACH ITS WINDOWS YET

Three runs have produced a lag curve, and none of them measured lag. The
2026-08-23 run settled it: 100% of windows contained no curve transactions,
at every lag from 1s to 20s, which cannot be true -- these are pump.fun
tokens seconds after a tracked wallet bought them, and a 17-second window on
one is never empty. Every lag was reconstructing the same state, so the
identical fill ratios were arithmetic, not a result.

Wall-clock says where it breaks: 720 window lookups finished in 148 seconds,
about one RPC call each, when reaching a window days in the past should cost
many pages of backward walking. The loop was giving up on its first page and
reporting that as "no trades happened".

So the walk now reports whether it actually got back past the start of its
window, and a row it did not reach is skipped instead of priced. That turns a
confident wrong number into a visible gap -- which is the whole of the fix so
far. Making the walk reach the window is a separate problem, and paging
backwards from the present may simply be the wrong shape for it: the cost
scales with everything the token did after the trade, which for a token that
went on to run is unbounded.
"""

import argparse
import collections
import json
import os
import sys
import time
import urllib.request

import pandas as pd

# Verified against 1,089 collector readings that logged real and virtual
# reserves side by side (see validate_offsets). Checked, not assumed -- if a
# future pump.fun revision changes them, the check fails loudly rather than
# silently mispricing every fill.
VIRTUAL_SOL_OFFSET = 30_000_000_000
VIRTUAL_TOKEN_OFFSET = 279_900_000_000_000

DEFAULT_LAGS_MS = [200, 500, 1000, 1500, 3000, 5000, 10000, 20000]

# getSignaturesForAddress pages backwards from the newest transaction, so
# reaching a window that sits days in the past costs one call per 100
# transactions the curve has seen since. A popular token can outrun any cap;
# what matters is that hitting the cap is reported rather than priced as zero.
MAX_PAGES = 20

# reached=False means the walk never got back to the start of the window, so
# the deltas describe a shorter span than asked for and the row is unusable.
Window = collections.namedtuple(
    "Window", "d_lamports d_tokens n_tx reached pages no_blocktime")


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
        except Exception as e:
            if attempt == retries - 1:
                raise
            # The free tier rate-limits aggressively; back off rather than
            # dropping the observation.
            time.sleep(1.5 * (attempt + 1))
    return None


def validate_offsets(df):
    """Confirm virtual = real + constant on the collector's own paired readings.

    Refuses to proceed if it does not hold: every reconstructed price depends
    on this, so a silent change here would misprice everything downstream.
    """
    have = df[df["entry_real_sol_reserves"].notna() & (df["entry_virtual_sol_reserves"] > 0)]
    if have.empty:
        sys.exit("No rows with a logged curve snapshot -- cannot validate reserve offsets.")

    sol_off = (have["entry_virtual_sol_reserves"] - have["entry_real_sol_reserves"]).value_counts()
    tok_off = (have["entry_virtual_token_reserves"] - have["entry_real_token_reserves"]).value_counts()
    sol_ok = sol_off.index[0] == VIRTUAL_SOL_OFFSET and sol_off.iloc[0] / len(have) > 0.99
    tok_ok = tok_off.index[0] == VIRTUAL_TOKEN_OFFSET and tok_off.iloc[0] / len(have) > 0.99

    print(f"Reserve offsets over {len(have)} logged snapshots:")
    print(f"  virtual_sol - real_sol     : {int(sol_off.index[0]):,} "
          f"({100 * sol_off.iloc[0] / len(have):.1f}% of rows) {'OK' if sol_ok else 'MISMATCH'}")
    print(f"  virtual_token - real_token : {int(tok_off.index[0]):,} "
          f"({100 * tok_off.iloc[0] / len(have):.1f}% of rows) {'OK' if tok_ok else 'MISMATCH'}")
    if not (sol_ok and tok_ok):
        sys.exit("Reserve offsets are not what this script assumes -- refusing to price anything.")


def curve_deltas_between(endpoint, curve, t_from_ms, t_to_ms, cache):
    """Net (lamport, token) change to the curve over (t_from, t_to].

    Uses pre/post balance DIFFERENCES only, so the account's rent-exempt
    minimum -- which is not part of real_sol_reserves -- cancels out and never
    has to be guessed.
    """
    # Exact ms in the key. Second-truncation here would silently merge windows
    # that differ only in sub-second lag -- which is the very thing being
    # measured, and would manufacture the appearance of lag having no effect.
    key = (curve, t_from_ms, t_to_ms)
    if key in cache:
        return cache[key]

    # `reached` records whether the walk actually got back past the start of
    # the window. Without it, "paged back to the window and found no trades"
    # and "never got there at all" both end as an empty sig list and price as
    # zero change -- which is exactly how the first two replay runs produced a
    # confident flat lag curve out of 720 lookups that found nothing.
    sigs, before, reached, pages, no_bt = [], None, False, 0, 0
    for _ in range(MAX_PAGES):
        page = rpc(endpoint, "getSignaturesForAddress", [curve, {"limit": 100, **({"before": before} if before else {})}])
        if not page:
            # History ran out. Only counts as covering the window if we had
            # already walked back into it; on the first page it means the RPC
            # returned nothing for this account at all.
            break
        pages += 1
        stop = False
        for s in page:
            raw_bt = s.get("blockTime")
            if not raw_bt:
                # A signature with no blockTime cannot be placed in or out of
                # the window. Treating it as time 0 would look older than any
                # window and stop the walk immediately -- silently, on the
                # first page -- so it is counted and skipped instead.
                no_bt += 1
                continue
            bt = raw_bt * 1000
            if bt <= t_from_ms:
                reached = True
                stop = True
                break
            if bt <= t_to_ms and not s.get("err"):
                sigs.append(s["signature"])
        if stop:
            break
        before = page[-1]["signature"]

    d_lamports = d_tokens = 0
    for sig in sigs:
        tx = rpc(endpoint, "getTransaction",
                 [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
        if not tx or "meta" not in tx:
            continue
        meta, msg = tx["meta"], tx["transaction"]["message"]
        keys = [k["pubkey"] if isinstance(k, dict) else k for k in msg.get("accountKeys", [])]
        if curve not in keys:
            continue
        i = keys.index(curve)
        pre, post = meta.get("preBalances", []), meta.get("postBalances", [])
        if i < len(pre) and i < len(post):
            d_lamports += post[i] - pre[i]
        pre_t = {b["accountIndex"]: b for b in meta.get("preTokenBalances", []) if b.get("owner") == curve}
        post_t = {b["accountIndex"]: b for b in meta.get("postTokenBalances", []) if b.get("owner") == curve}
        for idx, b in post_t.items():
            after = int(b["uiTokenAmount"]["amount"])
            before_amt = int(pre_t[idx]["uiTokenAmount"]["amount"]) if idx in pre_t else 0
            d_tokens += after - before_amt

    # n_tx is the diagnostic that separates "lag genuinely costs nothing here"
    # from "the lookup silently found nothing". A flat lag curve means the
    # first only if windows actually contained transactions -- and `reached`
    # is what makes an empty window trustworthy rather than merely empty.
    cache[key] = Window(d_lamports, d_tokens, len(sigs), reached, pages, no_bt)
    return cache[key]


def constant_product_buy_cost(v_sol, v_tok, tokens_out):
    if tokens_out <= 0 or tokens_out >= v_tok:
        return None
    return (v_sol * v_tok) / (v_tok - tokens_out) - v_sol


def constant_product_sell_proceeds(v_sol, v_tok, tokens_in):
    if tokens_in <= 0:
        return None
    return v_sol - (v_sol * v_tok) / (v_tok + tokens_in)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="?", default="reports/paper_trades_final.csv")
    ap.add_argument("out", nargs="?", default="reports/replay_lag_curve.csv")
    ap.add_argument("--endpoint", default=os.environ.get("RPC_ENDPOINT", ""))
    ap.add_argument("--lags", default=",".join(str(x) for x in DEFAULT_LAGS_MS))
    ap.add_argument("--limit", type=int, default=200, help="round trips to replay (RPC cost scales with this)")
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument("--probe", type=int, default=0, metavar="N",
                    help="dump what the signature walk actually saw for the first N curves")
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    if "collector_version" not in df.columns:
        sys.exit("No collector_version column -- this CSV predates replay support.")
    df = df[df["collector_version"] >= 3]
    if df.empty:
        sys.exit("No collector v3+ rows. Only v3 records the buy signature and block times a replay needs.")

    validate_offsets(df)
    if args.validate_only:
        return

    if not args.endpoint:
        sys.exit("Set --endpoint or RPC_ENDPOINT.")

    # Rows a replay can actually use: both legs identified and timed, and an
    # entry snapshot to walk back from.
    usable = df[
        df["entry_signature"].notna() & (df["entry_signature"] != "")
        & (df["entry_block_time_ms"] > 0) & (df["sell_block_time_ms"] > 0)
        & df["bonding_curve"].notna() & (df["bonding_curve"] != "")
        & (df["entry_real_sol_reserves"] > 0)
    ].head(args.limit)
    print(f"\nReplaying {len(usable)} of {len(df)} v3 round trips at "
          f"{args.lags.replace(',', ', ')} ms\n")

    lags = [int(x) for x in args.lags.split(",")]
    cache, rows = {}, []
    skipped = collections.Counter()
    probes_left = args.probe

    for _, r in usable.iterrows():
        # The moment the collector read the curve, which is the state we walk
        # back from: the trade's block time, plus how stale it already was when
        # detected, plus the configured execution lag.
        snap_ms = int(r["entry_block_time_ms"]) + int(r.get("entry_on_chain_age_ms") or 0) + 1500
        for lag in lags:
            target_ms = int(r["entry_block_time_ms"]) + lag
            if target_ms >= snap_ms:
                continue  # the snapshot is already at or before this lag
            try:
                w = curve_deltas_between(args.endpoint, r["bonding_curve"], target_ms, snap_ms, cache)
            except Exception as e:
                print(f"  skip {r['entry_signature'][:12]}… lag={lag}: {e}")
                skipped["rpc error"] += 1
                continue

            if probes_left and lag == lags[0]:
                probes_left -= 1
                print(f"  probe {r['bonding_curve'][:12]}… window {target_ms}..{snap_ms} "
                      f"({(snap_ms - target_ms) / 1000:.1f}s): pages={w.pages} txs={w.n_tx} "
                      f"reached={w.reached} sigs_without_blocktime={w.no_blocktime}")

            # A window the walk never reached describes a shorter span than
            # asked for. Pricing it anyway is what produced a flat lag curve
            # from 720 lookups that had found nothing.
            if not w.reached:
                skipped["window not reached"] += 1
                continue

            real_sol = float(r["entry_real_sol_reserves"]) - w.d_lamports
            real_tok = float(r["entry_real_token_reserves"]) - w.d_tokens
            v_sol, v_tok = real_sol + VIRTUAL_SOL_OFFSET, real_tok + VIRTUAL_TOKEN_OFFSET
            cost = constant_product_buy_cost(v_sol, v_tok, float(r["wallet_token_amount"]))
            if cost is None or cost <= 0:
                continue
            rows.append({
                "entry_signature": r["entry_signature"], "wallet_label": r["wallet_label"],
                "target_lag_ms": lag, "our_cost_lamports": cost,
                "wallet_cost_lamports": float(r["wallet_lamports_spent"]),
                "curve_txs_in_window": w.n_tx,
                "fill_ratio": cost / float(r["wallet_lamports_spent"]) if r["wallet_lamports_spent"] else float("nan"),
            })

    if skipped:
        print("\nSkipped: " + ", ".join(f"{n} {why}" for why, n in skipped.most_common()))
    if not rows:
        sys.exit("Replay produced no priced fills -- nothing to summarise. "
                 "If these are mostly 'window not reached', the walk never paged back "
                 "far enough (or the RPC returned no history for the curve); rerun with "
                 "--probe 5 to see what it saw.")

    out = pd.DataFrame(rows)
    curve = out.groupby("target_lag_ms").agg(
        fills=("fill_ratio", "size"),
        median_fill_ratio=("fill_ratio", "median"),
        mean_fill_ratio=("fill_ratio", "mean"),
        pct_worse_than_wallet=("fill_ratio", lambda s: 100.0 * (s > 1).mean()),
        mean_txs_in_window=("curve_txs_in_window", "mean"),
        pct_windows_empty=("curve_txs_in_window", lambda s: 100.0 * (s == 0).mean()),
    ).reset_index()
    curve.to_csv(args.out, index=False)

    # The diagnostic columns print alongside the ratios, not only into the CSV.
    # The first diagnostic run wrote them to an artifact and printed the ratios
    # alone, so the log showed a flat curve with no way to tell whether it meant
    # anything -- which is the exact question the diagnostic was added to settle.
    print("Entry cost vs the wallet's, by simulated lag "
          "(ratio > 1 = we pay more than they did):")
    for _, c in curve.iterrows():
        print(f"  {int(c['target_lag_ms']):>6} ms  n={int(c['fills']):>5}  "
              f"median {c['median_fill_ratio']:.4f}x  mean {c['mean_fill_ratio']:.4f}x  "
              f"worse-than-wallet {c['pct_worse_than_wallet']:.1f}%  "
              f"curve txs/window {c['mean_txs_in_window']:.2f}  "
              f"empty {c['pct_windows_empty']:.1f}%")

    # A lag curve is only evidence if the windows it prices across actually
    # contained trades. If they did not, every lag reconstructs the same state
    # and the flat result says nothing about lag.
    empty = float(curve["pct_windows_empty"].min())
    if empty > 95.0:
        print(f"\n!! {empty:.1f}% of windows contained NO curve transactions at every lag.\n"
              "!! This curve is NOT evidence that lag is cheap -- each lag reconstructed the\n"
              "!! same state, so identical ratios are arithmetic, not a measurement. Either\n"
              "!! these curves genuinely sat idle, or the signature lookup is finding nothing.\n"
              "!! Do not quote these numbers as a lag result.", file=sys.stderr)
    elif empty > 50.0:
        print(f"\n!  {empty:.1f}% of windows were empty; the curve is thin evidence at best.",
              file=sys.stderr)

    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
