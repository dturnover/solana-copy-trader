"""
Scores tracked wallets on whether their edge looks like skill or like variance.

Total P&L is close to useless for this on its own. Memecoin round trips are
fat-tailed -- win rates sit near 40% and a single trade routinely carries a
wallet's whole result -- so over a few days the ranking is mostly noise, and
a daily leaderboard (which is how these wallets get picked) selects whoever
just got lucky. That is not a hypothetical: the 9 wallets added from
kolscan's leaderboard on 2026-07-31 went on to lose 362.80 SOL while the
original set made 37.89 over the same days, losing on three days when the
originals made money.

So this reports four things total P&L cannot tell you:

  tail dependence  -- how much of the result is one or three trades. A wallet
                      whose P&L collapses without its best trade has shown
                      you one good trade, not an edge.
  consistency      -- share of active days in profit. Skill shows up as
                      showing up; luck arrives once and leaves.
  persistence      -- first half of their history vs second half. The single
                      most direct skill test available: an edge should
                      survive being cut in half, a hot streak should not.
  p_luck           -- bootstrap over their own trades: the share of resamples
                      where a wallet this good or better nets <= 0. High
                      means their record is consistent with having no edge.

And it refuses to rank wallets with too few trades, because at these tails
a 20-trade sample cannot separate a good trader from a lucky one, and
pretending otherwise is how you end up buying the leaderboard.

Scores WALLET-side P&L (their own real on-chain trading), not our simulated
copy: whether a wallet is worth following is a separate question from whether
we can execute on it. Note the caveat in --help about collector versions.
"""

import argparse
import sys

import numpy as np
import pandas as pd

MIN_TRADES = 30      # below this, variance swamps everything -- report, don't rank
MIN_DAYS = 3         # a single session is one regime, not a track record
N_BOOTSTRAP = 10000
RNG_SEED = 0         # fixed so a rerun on unchanged data gives an unchanged scorecard


def bootstrap_p_luck(pnl, rng):
    """Share of resamples of this wallet's own trades that net <= 0.

    Resampling their actual trade distribution keeps the fat tail intact,
    which a t-test on the mean would not.
    """
    if len(pnl) < 2:
        return float("nan")
    draws = rng.choice(pnl, size=(N_BOOTSTRAP, len(pnl)), replace=True).sum(axis=1)
    return float((draws <= 0).mean())


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Caveat: rows from collector v1/v2 are a censored sample (see "
               "src/main_paper_trade.cpp). The censoring dropped trades whose price ran "
               "away during our execution lag, which correlates with the wallet's own "
               "outcome -- so wallet-side figures from those rows are biased too. Use "
               "--min-collector-version to score only complete data once enough exists.")
    ap.add_argument("csv", nargs="?", default="reports/paper_trades_final.csv")
    ap.add_argument("out", nargs="?", default="reports/wallet_scorecard.csv")
    ap.add_argument("--min-collector-version", type=int, default=None,
                    help="default: the highest version present in the data")
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    if "collector_version" not in df.columns:
        df["collector_version"] = 1

    # Default to the newest collector version present rather than everything.
    # Earlier versions dropped whole round trips, and the drop rate tracks how
    # volatile each wallet's tokens are -- so pooling versions does not merely
    # add noise, it reorders the ranking this script exists to produce. Mixing
    # them silently is how every headline number in this repo came out wrong.
    available = sorted(int(v) for v in df["collector_version"].unique())
    floor = args.min_collector_version if args.min_collector_version is not None else available[-1]
    df = df[df["collector_version"] >= floor]
    if df.empty:
        sys.exit(f"No rows at collector_version >= {floor}")

    if floor < 3:
        present = ", ".join("v%d" % v for v in available)
        print(
            f"!! Scoring collector v{floor}+ -- a CENSORED sample. v1 dropped reverting buys AND\n"
            f"!! sells; v2 still dropped reverting sells. The drop rate varies by wallet, so these\n"
            f"!! rankings are distorted, not merely noisy. Provisional until v3 data exists.\n"
            f"!! (versions present: {present})\n",
            file=sys.stderr,
        )

    df["dt"] = pd.to_datetime(df["epoch_ms"], unit="ms")
    df["day"] = df["dt"].dt.date

    # A wallet that made money on a day everyone made money has shown you the
    # market, not skill. Subtracting the cross-wallet median for each day
    # leaves what they did that their peers did not.
    day_median = df.groupby("day")["wallet_pnl_sol"].median()
    df["excess_sol"] = df["wallet_pnl_sol"] - df["day"].map(day_median)

    rng = np.random.default_rng(RNG_SEED)
    rows = []
    for label, sub in df.groupby("wallet_label"):
        sub = sub.sort_values("epoch_ms")
        pnl = sub["wallet_pnl_sol"].to_numpy()
        total = float(pnl.sum())
        n, days = len(sub), sub["day"].nunique()

        by_day = sub.groupby("day")["wallet_pnl_sol"].sum()
        days_positive = float((by_day > 0).mean())

        # Tail dependence: what survives without their best trades.
        ordered = np.sort(pnl)
        ex_top1 = float(ordered[:-1].sum()) if n > 1 else float("nan")
        ex_top3 = float(ordered[:-3].sum()) if n > 3 else float("nan")

        # Persistence: does the first half of their record predict the second?
        mid = n // 2
        first = float(pnl[:mid].mean()) if mid else float("nan")
        second = float(pnl[mid:].mean()) if n - mid else float("nan")
        persists = bool(n >= MIN_TRADES and np.sign(first) == np.sign(second) and second > 0)

        p_luck = bootstrap_p_luck(pnl, rng)

        if n < MIN_TRADES or days < MIN_DAYS:
            verdict = "INSUFFICIENT"
        elif total <= 0:
            verdict = "LOSING"
        elif p_luck > 0.10:
            verdict = "UNPROVEN"          # positive, but consistent with no edge
        elif not persists:
            verdict = "UNSTABLE"          # positive overall, did not hold up across halves
        elif ex_top3 <= 0:
            verdict = "TAIL-DEPENDENT"    # the whole result is three trades
        else:
            verdict = "CONSISTENT"

        rows.append({
            "wallet": label, "trades": n, "days": days,
            "total_sol": round(total, 2),
            "excess_sol": round(float(sub["excess_sol"].sum()), 2),
            "mean_sol": round(float(pnl.mean()), 4),
            "median_sol": round(float(np.median(pnl)), 4),
            "win_rate": round(float((pnl > 0).mean()), 3),
            "days_positive": round(days_positive, 3),
            "total_ex_top1": round(ex_top1, 2),
            "total_ex_top3": round(ex_top3, 2),
            "first_half_mean": round(first, 4),
            "second_half_mean": round(second, 4),
            "p_luck": round(p_luck, 3),
            "verdict": verdict,
        })

    out = pd.DataFrame(rows).sort_values(["verdict", "total_sol"], ascending=[True, False])
    out.to_csv(args.out, index=False)

    order = ["CONSISTENT", "TAIL-DEPENDENT", "UNSTABLE", "UNPROVEN", "LOSING", "INSUFFICIENT"]
    quality = "complete" if floor >= 3 else "CENSORED -- provisional"
    print(f"Scored {len(out)} wallets over {df['day'].nunique()} days "
          f"(collector v{floor}+, {len(df)} trades, {quality})\n")
    for v in order:
        grp = out[out["verdict"] == v]
        if grp.empty:
            continue
        print(f"--- {v} ({len(grp)}) ---")
        print(grp[["wallet", "trades", "days", "total_sol", "excess_sol", "win_rate",
                   "days_positive", "total_ex_top3", "p_luck"]].to_string(index=False))
        print()
    print(f"Wrote {args.out}")
    print(f"INSUFFICIENT = fewer than {MIN_TRADES} trades or {MIN_DAYS} active days; "
          "not a judgement, just not enough evidence yet.")


if __name__ == "__main__":
    main()
