import sys

import pandas as pd

path = sys.argv[1]
df = pd.read_csv(path)
print("Total rows:", len(df))
dupe_key = ["wallet_label", "mint", "wallet_lamports_spent", "wallet_lamports_received"]
dupes = df.duplicated(subset=dupe_key, keep=False)
print("Rows that look like duplicates (same wallet+mint+exact spend/receive amounts):", dupes.sum())
if dupes.sum() > 0:
    print(df[dupes].sort_values(dupe_key)[["epoch_ms"] + dupe_key].to_string())
