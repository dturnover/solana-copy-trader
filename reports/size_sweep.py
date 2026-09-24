"""
Prices every same-block round trip at a range of FIXED copy sizes.

Why this exists. Every earlier copy simulation mirrored the wallet's own size:
if they bought 5 SOL of a token, so did we. On a bonding curve that is the
single biggest cost in the whole strategy, because we land immediately after
them on a curve they have just pushed. Across the first 27 same-block round
trips, log(position size) against log(fill ratio) correlates at +0.84: a
0.26 SOL wallet fills us at 1.007x their price, a 5 SOL wallet at 1.34x.

Nothing forces us to copy at their size. This sweeps our size independently
and reports return on capital per trade, per wallet, under explicit fee
scenarios for OUR costs -- not the wallet's, which include sniper-grade
priority fees and tips we would not necessarily pay.

It also splits each copy into entry price and exit price, because a good buy
fill says nothing about the exit. That split is what showed theo, who fills us
at 1.007x on the way in, to be uncopyable: we exit theo's trades at 0.82x of
our entry, selling into theo's own dump. Buy-side fill alone had it backwards.

CURVE STATE

Newer same-block files carry the curve reserves directly (buy_vs, sell_vs).
Older ones do not, so for those the reserves are reconstructed from the stored
cost and proceeds using pump.fun's constant-product invariant,
vsol * vtok = 30e9 * 1.073e15. That invariant is not assumed: it held to one
part in a million on 98.8% of 1,651 independent curve snapshots the collector
logged, and every reconstruction is cross-checked against the wallet's own
recorded SOL spend (median implied fee 233 bps, agreeing with the 146-243 bps
the replay measured from event data by a different route).

THE CEILING

Same-block is the best execution that exists, not the execution we have. A
wallet whose median hold is 2.8 seconds is only copyable if we can enter and
exit within a slot or two of it; at the collector's ~12s detection lag we
would enter after it has already sold. Treat these numbers as an upper bound
that says which wallets are worth the latency investment, not as expected P&L.
"""

import argparse
import glob
import sys

import numpy as np
import pandas as pd

K = 30_000_000_000 * 1_073_000_000_000_000   # pump.fun constant product (lamports x raw tokens)
V0 = 30_000_000_000                           # virtual SOL at launch
LAMPORTS = 1e9

SIZES_SOL = [0.05, 0.1, 0.25, 0.5, 1.0, 2.0]

# (proportional fee per leg, fixed SOL per round trip). The fixed part could not
# be fitted from 27 trades -- the regression intercept came out negative, i.e.
# not identifiable -- so it is swept as an explicit assumption instead.
SCENARIOS = {
    "optimistic":  (0.010, 0.0005),
    "measured":    (0.020, 0.0020),
    "pessimistic": (0.028, 0.0050),
}


def load(pattern, main_csv):
    files = sorted(glob.glob(pattern))
    if not files:
        sys.exit(f"No same-block files match {pattern}")
    d = pd.concat([pd.read_csv(f) for f in files]).drop_duplicates(subset=["entry_signature"])
    main = pd.read_csv(main_csv)[["entry_signature", "wallet_token_amount", "hold_duration_ms"]]
    d = d.merge(main, on="entry_signature", how="left")
    d = d[d["wallet_token_amount"] > 0].copy()
    T = d["wallet_token_amount"].astype(float)

    # Persisted reserves where the file has them; reconstruct otherwise.
    c, p = d["raw_cost_lamports"], d["raw_proceeds_lamports"]
    recon_buy = (-c * T + np.sqrt((c * T) ** 2 + 4 * T * c * K)) / (2 * T)
    recon_sell = (p * T + np.sqrt((p * T) ** 2 + 4 * T * p * K)) / (2 * T)
    d["buy_vs"] = d["buy_vs"].fillna(recon_buy) if "buy_vs" in d else recon_buy
    d["sell_vs"] = d["sell_vs"].fillna(recon_sell) if "sell_vs" in d else recon_sell

    # Cross-check against the wallet's independently recorded SOL spend. A
    # reconstruction that implies a nonsensical fee, or a curve outside the
    # range pump.fun can reach, is rejected rather than priced.
    pre_vt = K / d["buy_vs"] + T
    their_curve_cost = d["buy_vs"] - K / pre_vt
    d["their_fee_bps"] = (d["wallet_cost_lamports"] / their_curve_cost - 1) * 1e4
    real_sol = (d["buy_vs"] - V0) / LAMPORTS
    ok = real_sol.between(0, 90) & d["their_fee_bps"].between(50, 1000) & d["sell_vs"].notna()
    if (~ok).any():
        print(f"Rejected {int((~ok).sum())} trade(s) whose curve state failed reconstruction checks",
              file=sys.stderr)
    return d[ok], len(files)


def copy_trade(rows, size_sol, prop, fixed_sol):
    """Per-trade (return on capital, entry price, exit price) at a fixed copy size."""
    S = size_sol * LAMPORTS
    Sc = S / (1 + prop)                      # fee is charged on top of the curve amount
    vs, ws = rows["buy_vs"].values, rows["sell_vs"].values
    tokens = K / vs - K / (vs + Sc)          # buy just after the wallet's buy
    gross = ws - K / (K / ws + tokens)       # sell just after the wallet's sell
    ret = ((gross * (1 - prop) - S) / LAMPORTS - fixed_sol) / size_sol
    return ret, Sc / tokens, gross / tokens


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--same-block", default="reports/same_block/*.csv")
    ap.add_argument("--main", default="reports/paper_trades_final.csv")
    ap.add_argument("--out", default="reports/size_sweep.csv")
    args = ap.parse_args()

    d, nfiles = load(args.same_block, args.main)
    print(f"{len(d)} same-block round trips from {nfiles} daily file(s)\n")

    rows = []
    for scen, (prop, fx) in SCENARIOS.items():
        for w, g in list(d.groupby("wallet_label")) + [("ALL", d)]:
            for s in SIZES_SOL:
                r, entry, exit_ = copy_trade(g, s, prop, fx)
                rows.append({"scenario": scen, "wallet": w, "size_sol": s, "n": len(g),
                             "mean_return": r.mean(), "win_rate": (r > 0).mean(),
                             "exit_over_entry": float(np.median(exit_ / entry)),
                             "median_hold_s": g["hold_duration_ms"].median() / 1000})
    out = pd.DataFrame(rows)
    out.to_csv(args.out, index=False)

    m = out[out["scenario"] == "measured"]
    print("Return on capital per trade at fixed copy size -- MEASURED fees (2%/leg, 0.002 SOL/rt)")
    piv = m.pivot(index="wallet", columns="size_sol", values="mean_return") * 100
    print(piv.round(1).to_string())
    print("\nexit/entry price at 0.25 SOL  (<1 = we sell below where we bought: exit liquidity)")
    print(m[m["size_sol"] == 0.25].set_index("wallet")[["exit_over_entry", "median_hold_s", "n"]]
          .round(3).to_string())
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
