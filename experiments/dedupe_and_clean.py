import sys

import pandas as pd

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

ratio = df["our_lamports_spent"] / df["wallet_lamports_spent"].replace(0, float("nan"))
df = df[(ratio >= 0.33) & (ratio <= 3)]
n2 = len(df)

print(f"Rows: {n0} -> deduped {n1} -> blowup-filtered {n2}")
df.to_csv(path_out, index=False)
