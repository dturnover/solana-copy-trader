"""
Folds downloaded lag-experiment artifacts into reports/lag_samples_final.csv.

lag_experiment is the tool whose whole purpose is deciding whether paying for
the real-time gRPC engine is worth it -- it samples a buy, then re-prices the
bonding curve at each target lag and records how far the price moved. That
question is answerable from data already being collected on the free tier;
what was missing is that, exactly like paper-trade.yml, the results were only
ever uploaded as build artifacts. They expire after 90 days, so the evidence
for the single biggest spending decision here was quietly aging out unread.

One sample = one (signature, target_lag_ms) pair: the same observed buy is
re-priced at every lag in the sweep, which is what makes the lag-vs-cost
curve possible. So dedupe on that pair, not on signature alone -- keying on
signature would collapse each buy to a single lag and destroy the curve.
"""

import glob
import os
import sys

import pandas as pd

COLUMNS = [
    "epoch_ms",
    "label",
    "signature",
    "mint",
    "on_chain_age_ms",
    "target_lag_ms",
    "actual_elapsed_ms",
    "baseline_price",
    "later_price",
    "pct_change",
    "fee_lamports",
    "priority_fee_microlamports",
]

existing_path = sys.argv[1]
artifacts_dir = sys.argv[2]
out_path = sys.argv[3]

frames = []

if os.path.exists(existing_path) and os.path.getsize(existing_path) > 0:
    existing = pd.read_csv(existing_path)
    print(f"  existing dataset: {len(existing)} rows")
    frames.append(existing)

for path in sorted(glob.glob(os.path.join(artifacts_dir, "**", "*.csv"), recursive=True)):
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        print(f"  {path}: empty, skipped")
        continue
    missing = set(COLUMNS) - set(df.columns)
    if missing:
        sys.exit(f"ERROR: {path} is missing expected columns: {sorted(missing)}")
    print(f"  {path}: {len(df)} rows")
    frames.append(df)

if not frames:
    sys.exit("ERROR: nothing to merge -- no existing dataset and no artifact CSVs")

combined = pd.concat(frames, ignore_index=True)[COLUMNS]
n0 = len(combined)
combined = combined.drop_duplicates(subset=["signature", "target_lag_ms"])

print(f"Lag samples: {n0} -> {len(combined)} after dedupe on (signature, target_lag_ms)")
if len(combined):
    curve = combined.groupby("target_lag_ms")["pct_change"].agg(["count", "mean", "median"])
    print("Price drift by target lag (negative = costs us):")
    for lag, row in curve.iterrows():
        print(f"  {int(lag):>7} ms  n={int(row['count']):>6}  mean {row['mean']:+.3f}%  median {row['median']:+.3f}%")

combined.to_csv(out_path, index=False)
