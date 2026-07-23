"""
Experimental: does a binary "should we copy this trade" classifier add value
over simple wallet-selection heuristics, given what we've collected so far
from paper_trade?

Methodology notes (read before trusting any number this prints):

1. Walk-forward, not a random train/test split. Trades are sorted
   chronologically (by epoch_ms, i.e. position-close time) and evaluated in
   order: at each step, the model is trained ONLY on trades that closed
   before the one being predicted, then that trade's true outcome is folded
   into the training set before moving on ("little by little", as requested).
   A random split would let the model train on trades that happened *after*
   the one it's being tested on, which is not a decision we could actually
   have made in real time.

2. Known feature-leakage caveat: paper_trade.cpp logs one row per CLOSED
   position, with wallet_token_amount / wallet_lamports_spent / buy_count as
   the CUMULATIVE totals across every buy in that position -- not just the
   first buy. For a position built from a single buy (most of them), that's
   fine and known at decision time. For positions with buy_count > 1, those
   fields include amounts added *after* the position was already open, which
   a real "should we copy the FIRST buy" decision wouldn't have known yet.
   This is a real limitation of the current logging granularity, not
   something this script can fix after the fact -- flagged in the report,
   not hidden.

3. Feature set is intentionally thin: wallet_label, buy_count,
   wallet_token_amount, wallet_lamports_spent, avg_buy_price_lamports. There
   is NO bonding-curve state, no price-impact-of-the-buy, no priority fee, no
   token age, no rolling market context logged anywhere yet. If the model
   just rediscovers "wallet_label == theo -> profitable", that means it
   isn't finding anything beyond what we already know from simple
   aggregation -- which is itself the answer to "does ML add value *with
   the data we have right now*."
"""

import sys

import lightgbm as lgb
import numpy as np
import pandas as pd

CSV_PATH = sys.argv[1] if len(sys.argv) > 1 else "data/paper_trades_combined.csv"
BURN_IN = 40  # trades used for initial training only, never evaluated
COPY_THRESHOLD = 0.5


def load_data(path):
    df = pd.read_csv(path)
    df = df.sort_values("epoch_ms").reset_index(drop=True)
    df["label"] = (df["our_pnl_sol"] > 0).astype(int)
    df["avg_buy_price_lamports"] = df["wallet_lamports_spent"] / df["wallet_token_amount"].replace(0, np.nan)
    df["wallet_label"] = df["wallet_label"].astype("category")
    return df


FEATURES = ["wallet_label", "buy_count", "wallet_token_amount", "wallet_lamports_spent", "avg_buy_price_lamports"]


def walk_forward(df):
    """Returns a DataFrame of out-of-sample predictions, one row per trade
    evaluated (i.e. every trade after BURN_IN), with the model retrained from
    scratch on all prior trades before each prediction."""
    results = []
    for i in range(BURN_IN, len(df)):
        train = df.iloc[:i]
        test = df.iloc[[i]]

        if train["label"].nunique() < 2:
            # Can't train a binary classifier on a single class yet -- treat
            # as "no opinion" (predict the majority class trivially).
            pred_proba = float(train["label"].mean())
        else:
            model = lgb.LGBMClassifier(
                n_estimators=50,
                max_depth=3,
                num_leaves=7,
                min_child_samples=5,
                learning_rate=0.1,
                verbosity=-1,
            )
            model.fit(train[FEATURES], train["label"], categorical_feature=["wallet_label"])
            pred_proba = model.predict_proba(test[FEATURES])[0][1]

        row = test.iloc[0]
        results.append(
            {
                "epoch_ms": row["epoch_ms"],
                "wallet_label": row["wallet_label"],
                "actual_label": row["label"],
                "our_pnl_sol": row["our_pnl_sol"],
                "pred_proba": pred_proba,
            }
        )
    return pd.DataFrame(results)


def trailing_wallet_win_rate_baseline(df):
    """Simple heuristic baseline, computed walk-forward with the same
    no-lookahead discipline: copy a trade only if that specific wallet's
    trailing (prior-only) mean P&L is positive. This is exactly the
    "just copy good wallets" rule we already found by hand -- the bar the ML
    model needs to clear to be worth the added complexity."""
    results = []
    for i in range(BURN_IN, len(df)):
        train = df.iloc[:i]
        row = df.iloc[i]
        prior_same_wallet = train[train["wallet_label"] == row["wallet_label"]]
        if len(prior_same_wallet) == 0:
            copy_decision = True  # no history yet -- default to copying
        else:
            copy_decision = prior_same_wallet["our_pnl_sol"].mean() > 0
        results.append({"epoch_ms": row["epoch_ms"], "copy": copy_decision, "our_pnl_sol": row["our_pnl_sol"]})
    return pd.DataFrame(results)


def summarize(name, pnl_series, n_total):
    n = len(pnl_series)
    total = pnl_series.sum()
    win_rate = (pnl_series > 0).mean() * 100 if n else float("nan")
    print(f"  {name}: copied {n}/{n_total} trades, win_rate={win_rate:.1f}%, total_pnl={total:.3f} SOL")


def main():
    df = load_data(CSV_PATH)
    print(f"Loaded {len(df)} closed trades. Burn-in: {BURN_IN}. Evaluating {len(df) - BURN_IN} trades walk-forward.\n")
    print("Label balance (all data): profitable=%d unprofitable=%d" % (df["label"].sum(), (1 - df["label"]).sum()))
    print("Label balance (post-burn-in eval window): profitable=%d unprofitable=%d\n" % (
        df["label"].iloc[BURN_IN:].sum(), (1 - df["label"].iloc[BURN_IN:]).sum()))

    n_eval = len(df) - BURN_IN

    print("=== Baseline: copy everything ===")
    everything = df.iloc[BURN_IN:]
    summarize("copy-everything", everything["our_pnl_sol"], n_eval)

    print("\n=== Baseline: trailing per-wallet win-rate filter (no ML) ===")
    wallet_baseline = trailing_wallet_win_rate_baseline(df)
    copied = wallet_baseline[wallet_baseline["copy"]]
    summarize("wallet-filter", copied["our_pnl_sol"], n_eval)

    print("\n=== LightGBM walk-forward classifier ===")
    preds = walk_forward(df)
    for thresh in [0.5, 0.6, 0.7]:
        copied_ml = preds[preds["pred_proba"] > thresh]
        summarize(f"lgbm@p>{thresh}", copied_ml["our_pnl_sol"], n_eval)

    # Classifier quality metrics at the default threshold, for context --
    # separate from the P&L question above.
    from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score

    pred_label = (preds["pred_proba"] > COPY_THRESHOLD).astype(int)
    print(f"\n  classifier metrics @ p>{COPY_THRESHOLD}: "
          f"accuracy={accuracy_score(preds['actual_label'], pred_label):.3f} "
          f"precision={precision_score(preds['actual_label'], pred_label, zero_division=0):.3f} "
          f"recall={recall_score(preds['actual_label'], pred_label, zero_division=0):.3f}")
    try:
        auc = roc_auc_score(preds["actual_label"], preds["pred_proba"])
        print(f"  AUC={auc:.3f} (0.5 = no better than random)")
    except ValueError as e:
        print(f"  AUC undefined: {e}")

    print("\n=== Feature importance (from a model trained on ALL data, for context only -- not used above) ===")
    full_model = lgb.LGBMClassifier(n_estimators=50, max_depth=3, num_leaves=7, min_child_samples=5, verbosity=-1)
    full_model.fit(df[FEATURES], df["label"], categorical_feature=["wallet_label"])
    for feat, imp in sorted(zip(FEATURES, full_model.feature_importances_), key=lambda x: -x[1]):
        print(f"  {feat}: {imp}")


if __name__ == "__main__":
    main()
