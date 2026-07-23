import sys

import pandas as pd

path_in = sys.argv[1]
path_out = sys.argv[2]

df = pd.read_csv(path_in)
ratio = df["our_lamports_spent"] / df["wallet_lamports_spent"].replace(0, float("nan"))
clean = df[(ratio >= 0.33) & (ratio <= 3)]
print(f"Kept {len(clean)}/{len(df)} rows after dropping simulation-blowup outliers")
clean.to_csv(path_out, index=False)
