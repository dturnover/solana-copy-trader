"""
Extends the original LightGBM-only experiment: with this little data (~215
clean closed trades), is a heavier gradient-boosted model even the right
choice, or would something simpler and more data-efficient do as well or
better while staying interpretable?

Models compared, all walk-forward (never trained on future trades relative
to what they're predicting), all using the same one-hot-encoded feature set:

  - Logistic Regression (L2): the classic small-data, maximally-interpretable
    baseline -- coefficients are directly "this feature raises/lowers the
    odds of profit by X", no tuning needed, very hard to overfit with ~215
    rows and ~25 features.
  - Random Forest: bagging instead of boosting. Generally more robust to
    small-sample overfitting than gradient boosting, since each tree is
    grown independently on a bootstrap sample rather than sequentially
    fitting the previous trees' residuals (which can chase noise faster in
    tiny datasets). Similar interpretability profile to LightGBM (feature
    importances, partial dependence, SHAP all apply the same way).
  - LightGBM: kept for direct comparison against the original experiment.

Same methodology as lgbm_trade_classifier.py otherwise (walk-forward,
40-trade burn-in, same leakage caveat on buy_count/amount fields for
multi-buy positions -- see that file's docstring for the full explanation).
"""

import sys

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score
from sklearn.preprocessing import StandardScaler

CSV_PATH = sys.argv[1] if len(sys.argv) > 1 else "data/paper_trades_final.csv"
BURN_IN = 40
COPY_THRESHOLD = 0.5


def load_data(path):
    df = pd.read_csv(path)
    df = df.sort_values("epoch_ms").reset_index(drop=True)
    df["label"] = (df["our_pnl_sol"] > 0).astype(int)
    df["avg_buy_price_lamports"] = df["wallet_lamports_spent"] / df["wallet_token_amount"].replace(0, np.nan)

    # One-hot upfront: which wallets we track is known in advance, not
    # revealed over time, so this isn't a lookahead leak -- unlike the
    # trade outcomes themselves, which walk_forward() still only reveals
    # incrementally.
    wallet_dummies = pd.get_dummies(df["wallet_label"], prefix="wallet")
    df = pd.concat([df, wallet_dummies], axis=1)
    feature_cols = ["buy_count", "wallet_token_amount", "wallet_lamports_spent",
                     "avg_buy_price_lamports"] + list(wallet_dummies.columns)
    return df, feature_cols


def make_models():
    return {
        "logreg": lambda: (StandardScaler(), LogisticRegression(max_iter=1000, C=1.0)),
        "random_forest": lambda: (None, RandomForestClassifier(n_estimators=100, max_depth=4, min_samples_leaf=5,
                                                                  random_state=0)),
        "lightgbm": lambda: (None, lgb.LGBMClassifier(n_estimators=50, max_depth=3, num_leaves=7,
                                                        min_child_samples=5, learning_rate=0.1, verbosity=-1)),
    }


def walk_forward(df, feature_cols, model_name, model_builder):
    results = []
    x_all = df[feature_cols].fillna(0).to_numpy(dtype=float)
    y_all = df["label"].to_numpy()

    for i in range(BURN_IN, len(df)):
        x_train, y_train = x_all[:i], y_all[:i]
        x_test = x_all[i:i + 1]

        if len(set(y_train)) < 2:
            pred_proba = float(y_train.mean())
        else:
            scaler, model = model_builder()
            if scaler is not None:
                x_train_fit = scaler.fit_transform(x_train)
                x_test_fit = scaler.transform(x_test)
            else:
                x_train_fit, x_test_fit = x_train, x_test
            model.fit(x_train_fit, y_train)
            pred_proba = model.predict_proba(x_test_fit)[0][1]

        row = df.iloc[i]
        results.append({
            "epoch_ms": row["epoch_ms"],
            "wallet_label": row["wallet_label"],
            "actual_label": row["label"],
            "our_pnl_sol": row["our_pnl_sol"],
            "pred_proba": pred_proba,
        })
    return pd.DataFrame(results)


def trailing_wallet_win_rate_baseline(df):
    results = []
    for i in range(BURN_IN, len(df)):
        train = df.iloc[:i]
        row = df.iloc[i]
        prior_same_wallet = train[train["wallet_label"] == row["wallet_label"]]
        copy_decision = True if len(prior_same_wallet) == 0 else prior_same_wallet["our_pnl_sol"].mean() > 0
        results.append({"copy": copy_decision, "our_pnl_sol": row["our_pnl_sol"]})
    return pd.DataFrame(results)


def summarize(name, pnl_series, n_total):
    n = len(pnl_series)
    total = pnl_series.sum()
    win_rate = (pnl_series > 0).mean() * 100 if n else float("nan")
    print(f"  {name}: copied {n}/{n_total} trades, win_rate={win_rate:.1f}%, total_pnl={total:.3f} SOL")


def main():
    df, feature_cols = load_data(CSV_PATH)
    n_eval = len(df) - BURN_IN
    print(f"Loaded {len(df)} closed trades. Burn-in: {BURN_IN}. Evaluating {n_eval} trades walk-forward.")
    print(f"Features ({len(feature_cols)}): {feature_cols}\n")

    print("=== Baseline: copy everything ===")
    summarize("copy-everything", df.iloc[BURN_IN:]["our_pnl_sol"], n_eval)

    print("\n=== Baseline: trailing per-wallet win-rate filter (no ML) ===")
    wallet_baseline = trailing_wallet_win_rate_baseline(df)
    summarize("wallet-filter", wallet_baseline[wallet_baseline["copy"]]["our_pnl_sol"], n_eval)

    models = make_models()
    for name, builder in models.items():
        print(f"\n=== {name} (walk-forward) ===")
        preds = walk_forward(df, feature_cols, name, builder)
        for thresh in [0.5, 0.6]:
            copied = preds[preds["pred_proba"] > thresh]
            summarize(f"{name}@p>{thresh}", copied["our_pnl_sol"], n_eval)

        pred_label = (preds["pred_proba"] > COPY_THRESHOLD).astype(int)
        acc = accuracy_score(preds["actual_label"], pred_label)
        prec = precision_score(preds["actual_label"], pred_label, zero_division=0)
        rec = recall_score(preds["actual_label"], pred_label, zero_division=0)
        print(f"  metrics @ p>{COPY_THRESHOLD}: accuracy={acc:.3f} precision={prec:.3f} recall={rec:.3f}", end=" ")
        try:
            print(f"AUC={roc_auc_score(preds['actual_label'], preds['pred_proba']):.3f}")
        except ValueError:
            print("AUC=undefined")

    print("\n=== Logistic Regression coefficients (trained on ALL data, for interpretability) ===")
    scaler = StandardScaler()
    x_all = scaler.fit_transform(df[feature_cols].fillna(0))
    lr = LogisticRegression(max_iter=1000).fit(x_all, df["label"])
    for feat, coef in sorted(zip(feature_cols, lr.coef_[0]), key=lambda x: -abs(x[1])):
        direction = "higher odds of profit" if coef > 0 else "lower odds of profit"
        print(f"  {feat}: {coef:+.3f} ({direction})")


if __name__ == "__main__":
    main()
