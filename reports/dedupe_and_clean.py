import sys

import pandas as pd

# Fill-cost divergence bounds. our_lamports_spent / wallet_lamports_spent far
# above 1 means the price ran away between the wallet's buy and our simulated
# fill -- we bought the top. Far below 1 means it dipped and we got in cheaper.
BLOWUP_LO, BLOWUP_HI = 0.33, 3.0

path_in = sys.argv[1]
path_out = sys.argv[2]

df = pd.read_csv(path_in)
n0 = len(df)

# Old rows have no sell_signature column (added after this data was
# collected) -- approximate dedup key for those. Any row that DOES have a
# signature can dedupe on that directly (exact, no approximation needed).
if "sell_signature" in df.columns:
    has_sig = df["sell_signature"].notna() & (df["sell_signature"] != "")
    with_sig = df[has_sig].drop_duplicates(subset=["sell_signature"])
    without_sig = df[~has_sig].drop_duplicates(
        subset=["wallet_label", "mint", "wallet_lamports_spent", "wallet_lamports_received"]
    )
    df = pd.concat([with_sig, without_sig], ignore_index=True)
else:
    df = df.drop_duplicates(subset=["wallet_label", "mint", "wallet_lamports_spent", "wallet_lamports_received"])
n1 = len(df)

# These rows used to be DROPPED here. That silently deleted the worst tail of
# the distribution: P&L degrades monotonically as this ratio rises (measured
# 2026-08-02 over 916 surviving trades -- 0.5-0.8x averaged +0.33 SOL,
# 1.25-2x averaged -1.26, 2-3x averaged -4.76), so cutting everything past 3x
# removed exactly the fills a live system suffers most from, biasing every
# headline number upward by an unknown amount. Unknown because the evidence
# was discarded before it was ever committed -- nothing downstream could size
# the hole.
#
# Flag instead of drop. Consumers decide what to do:
# generate_performance_report.py still excludes these from its headline
# figures (keeping them comparable to earlier reports) but now also reports
# the excluded cohort's size and P&L alongside.
ratio = df["our_lamports_spent"] / df["wallet_lamports_spent"].replace(0, float("nan"))
df["fill_ratio"] = ratio
# NaN (wallet spent 0, so the ratio is unverifiable) sorts to True: these were
# dropped before as well, since NaN fails both comparisons. Keep excluding
# them from headline figures -- but visibly now, not silently.
df["blowup"] = ~ratio.between(BLOWUP_LO, BLOWUP_HI)

n_blow = int(df["blowup"].sum())
print(f"Rows: {n0} -> deduped {n1} -> flagged {n_blow} blow-up fill(s), kept all {len(df)}")
if n_blow:
    blow = df[df["blowup"]]
    clean = df[~df["blowup"]]
    print(f"  blow-up cohort: our P&L {blow['our_pnl_sol'].sum():+.2f} SOL "
          f"(mean {blow['our_pnl_sol'].mean():+.3f}), wallet P&L {blow['wallet_pnl_sol'].sum():+.2f} SOL")
    print(f"  clean cohort  : our P&L {clean['our_pnl_sol'].sum():+.2f} SOL over {len(clean)} trades")

# Collector v1 dropped any buy whose lag-delayed cost exceeded the wallet's
# max_sol_cost bound, so v1 rows are a favourable-fills-only sample and must
# not be pooled with v2 without saying so. Surface the split every merge.
if "collector_version" in df.columns:
    counts = df["collector_version"].value_counts().sort_index()
    print("Collector versions: " + ", ".join(f"v{int(k)}={int(v)}" for k, v in counts.items()))
    for ver, complete in ((2, False), (3, True)):
        sub = df[df["collector_version"] == ver]
        if sub.empty:
            continue
        buy_rev = sub[sub["would_have_reverted"] == 1]
        print(f"  v{ver} ({'complete' if complete else 'buy-side fixed, sell-side still censored'}): "
              f"{len(buy_rev)}/{len(sub)} ({100.0 * len(buy_rev) / len(sub):.1f}%) reverting BUYS, "
              f"our P&L {buy_rev['our_pnl_sol'].sum():+.2f} SOL")
        if complete:
            sell_rev = sub[sub["sell_would_have_reverted"] == 1]
            print(f"        {len(sell_rev)}/{len(sub)} ({100.0 * len(sell_rev) / len(sub):.1f}%) reverting SELLS, "
                  f"our P&L {sell_rev['our_pnl_sol'].sum():+.2f} SOL")

df.to_csv(path_out, index=False)
