"""
Folds every downloaded paper-trade artifact CSV into the committed dataset,
emitting a raw combined CSV for dedupe_and_clean.py to dedupe and filter.

Exists because paper-trade.yml only ever uploads its CSV as a build artifact:
artifacts expire (90d) and aren't queryable as data, so until 2026-08 the
dataset was refreshed by hand -- download artifacts locally, merge, commit --
which meant the committed CSV silently drifted days behind the pipeline
whenever nobody did it. merge-paper-trades.yml runs this instead.

The two schemas differ in column *order* only: the C++ writer
(append_csv_row in src/main_paper_trade.cpp) puts sell_signature 4th, while
the committed dataset carries it last, because sell_signature was added
after the first batches were collected and got appended to the existing
header rather than inserted. Both carry the same 13 fields, so aligning on
column names -- not position -- is what makes the merge safe; never switch
this to a positional concat.
"""

import glob
import os
import sys

import pandas as pd

# Column order of the committed dataset. The artifact order differs (see
# module docstring); output is normalized to this so the tracked file's
# schema stays stable across merges.
FINAL_COLUMNS = [
    "epoch_ms",
    "wallet_label",
    "mint",
    "buy_count",
    "hold_duration_ms",
    "wallet_token_amount",
    "wallet_lamports_spent",
    "wallet_lamports_received",
    "wallet_pnl_sol",
    "our_lamports_spent",
    "our_lamports_received",
    "our_pnl_sol",
    "sell_signature",
    "would_have_reverted",
    "sell_would_have_reverted",
    "entry_virtual_sol_reserves",
    "entry_virtual_token_reserves",
    "entry_real_sol_reserves",
    "entry_real_token_reserves",
    "entry_token_total_supply",
    "entry_our_cost_lamports",
    "collector_version",
]

# Columns added to the writer after collection had already started, with the
# value to assume for rows written before they existed. Backfilling here (on
# name, never position) is what lets one dataset span every schema vintage.
#   sell_signature      -- absent means "no signature captured"; dedupe has a
#                          separate branch keyed on wallet/mint/lamports.
#   would_have_reverted -- v1 dropped reverting buys outright, so every row it
#                          did write executed within the wallet's bound: 0.
#   sell_would_have_reverted -- v1 and v2 never closed a position whose sell
#                          breached the bound, so every row they wrote had a
#                          clean exit: 0. (The dropped ones aren't recoverable
#                          -- they were never written at all.)
#   collector_version   -- absent IS the v1 marker (v1 never wrote the column).
OPTIONAL_COLUMNS = {
    "sell_signature": "",
    "would_have_reverted": 0,
    "sell_would_have_reverted": 0,
    # Decision-time curve snapshot for the classifier (see
    # experiments/FEATURES.md). NaN, not 0, for rows collected before these
    # existed: 0 would read as "a pool with no liquidity", which is a
    # meaningful and wrong value. NaN is the honest "not recorded", and
    # LightGBM handles it natively.
    "entry_virtual_sol_reserves": float("nan"),
    "entry_virtual_token_reserves": float("nan"),
    "entry_real_sol_reserves": float("nan"),
    "entry_real_token_reserves": float("nan"),
    "entry_token_total_supply": float("nan"),
    "entry_our_cost_lamports": float("nan"),
    "collector_version": 1,
}

existing_path = sys.argv[1]
artifacts_dir = sys.argv[2]
out_path = sys.argv[3]

frames = []

def backfill_optional(df, label):
    """Add any post-hoc columns this file predates, at their v1 defaults."""
    filled = [c for c in OPTIONAL_COLUMNS if c not in df.columns]
    for c in filled:
        df[c] = OPTIONAL_COLUMNS[c]
    suffix = f" (backfilled: {', '.join(filled)})" if filled else ""
    print(f"  {label}: {len(df)} rows{suffix}")
    return df


if os.path.exists(existing_path) and os.path.getsize(existing_path) > 0:
    existing = pd.read_csv(existing_path)
    frames.append(backfill_optional(existing, "existing dataset"))
else:
    print("No existing dataset -- starting from artifacts alone")

# Artifacts unzip to <dir>/<artifact-id>/paper_trades.csv.
artifact_csvs = sorted(glob.glob(os.path.join(artifacts_dir, "**", "*.csv"), recursive=True))
for path in artifact_csvs:
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        # A run that closed no trades uploads a zero-byte/header-only CSV --
        # normal for a quiet window, not a failure.
        print(f"  {path}: empty, skipped")
        continue

    df = backfill_optional(df, path)

    # Any *other* missing column is a real schema break -- fail loudly rather
    # than merge partial rows that dedupe_and_clean.py would later drop on a
    # NaN key.
    missing = set(FINAL_COLUMNS) - set(df.columns)
    if missing:
        sys.exit(f"ERROR: {path} is missing expected columns: {sorted(missing)}")
    frames.append(df)

if not frames:
    sys.exit("ERROR: nothing to merge -- no existing dataset and no artifact CSVs")

# Aligns on column names, so the artifact/dataset order mismatch is handled.
combined = pd.concat(frames, ignore_index=True)[FINAL_COLUMNS]

print(f"Combined (pre-dedupe): {len(combined)} rows from {len(frames)} source(s)")
combined.to_csv(out_path, index=False)
