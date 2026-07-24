"""
Extends the original LightGBM-only experiment: with this little data (~215
clean closed trades), is a heavier gradient-boosted model even the right
choice, or would something simpler and more data-efficient do as well or
better while staying interpretable? Also tracks a simple ensemble of all
three, since no single model has an obvious edge yet at this sample size.

Models compared, all walk-forward (never trained on future trades relative
to what they're predicting), all using the same one-hot-encoded feature set,
all computed in a single pass per row so every model (and the ensemble) sees
identical train/test splits at each step:

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
  - Ensemble: simple mean of the three models' predicted probabilities
    (soft voting). Not stacking/a meta-learner -- with only ~215 rows there
    isn't enough data to hold out a further slice to train a meta-learner
    on top of the three base models without starving all of them, so plain
    averaging is the appropriately-scoped choice here.

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
MODEL_NAMES = ["logreg", "random_forest", "lightgbm"]


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


def build_models():
    """(scaler_or_None, fresh_model) per model name -- called fresh at every
    walk-forward step so no model carries state across steps."""
    return {
        "logreg": (StandardScaler(), LogisticRegression(max_iter=1000, C=1.0)),
        "random_forest": (None, RandomForestClassifier(n_estimators=100, max_depth=4, min_samples_leaf=5,
                                                          random_state=0)),
        "lightgbm": (None, lgb.LGBMClassifier(n_estimators=50, max_depth=3, num_leaves=7,
                                                min_child_samples=5, learning_rate=0.1, verbosity=-1)),
    }


def walk_forward_all(df, feature_cols):
    """One pass over the evaluation window; for each row, fits all three
    models fresh on the same prior-only training slice and records each
    model's predicted probability plus the simple-average ensemble."""
    results = []
    x_all = df[feature_cols].fillna(0).to_numpy(dtype=float)
    y_all = df["label"].to_numpy()

    for i in range(BURN_IN, len(df)):
        x_train, y_train = x_all[:i], y_all[:i]
        x_test = x_all[i:i + 1]
        row = df.iloc[i]
        entry = {
            "epoch_ms": row["epoch_ms"],
            "wallet_label": row["wallet_label"],
            "actual_label": row["label"],
            "our_pnl_sol": row["our_pnl_sol"],
        }

        if len(set(y_train)) < 2:
            fallback = float(y_train.mean())
            for name in MODEL_NAMES:
                entry[name] = fallback
        else:
            models = build_models()
            for name, (scaler, model) in models.items():
                if scaler is not None:
                    x_train_fit = scaler.fit_transform(x_train)
                    x_test_fit = scaler.transform(x_test)
                else:
                    x_train_fit, x_test_fit = x_train, x_test
                model.fit(x_train_fit, y_train)
                entry[name] = model.predict_proba(x_test_fit)[0][1]

        entry["ensemble"] = np.mean([entry[name] for name in MODEL_NAMES])
        results.append(entry)
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


def risk_stats(pnl_chronological):
    """pnl_chronological must already be in the order trades actually
    happened -- preds is built by walk_forward_all() in increasing i order,
    and boolean-mask filtering preserves row order, so callers just pass the
    filtered column straight through."""
    pnl = pnl_chronological.to_numpy()
    n = len(pnl)
    if n == 0:
        return None
    mean = pnl.mean()
    std = pnl.std(ddof=1) if n > 1 else 0.0
    sharpe_like = mean / std if std > 0 else float("nan")

    cumulative = np.cumsum(pnl)
    running_max = np.maximum.accumulate(cumulative)
    max_drawdown = (running_max - cumulative).max()

    losses = pnl[pnl < 0]
    return {
        "n": n,
        "std_pnl": std,
        "sharpe_like": sharpe_like,
        "max_drawdown": max_drawdown,
        "worst_single_loss": losses.min() if len(losses) else 0.0,
        "avg_loss": losses.mean() if len(losses) else 0.0,
    }


def print_risk(name, stats):
    if stats is None:
        return
    print(f"    risk: std_per_trade={stats['std_pnl']:.3f} SOL, sharpe-like={stats['sharpe_like']:.3f}, "
          f"max_drawdown={stats['max_drawdown']:.3f} SOL, worst_single_loss={stats['worst_single_loss']:.3f} SOL, "
          f"avg_loss={stats['avg_loss']:.3f} SOL")


def report_model(preds, col, n_eval):
    print(f"\n=== {col} ===")
    for thresh in [0.5, 0.6]:
        copied = preds[preds[col] > thresh]
        summarize(f"{col}@p>{thresh}", copied["our_pnl_sol"], n_eval)
        print_risk(f"{col}@p>{thresh}", risk_stats(copied["our_pnl_sol"]))

    pred_label = (preds[col] > COPY_THRESHOLD).astype(int)
    acc = accuracy_score(preds["actual_label"], pred_label)
    prec = precision_score(preds["actual_label"], pred_label, zero_division=0)
    rec = recall_score(preds["actual_label"], pred_label, zero_division=0)
    print(f"  metrics @ p>{COPY_THRESHOLD}: accuracy={acc:.3f} precision={prec:.3f} recall={rec:.3f}", end=" ")
    try:
        print(f"AUC={roc_auc_score(preds['actual_label'], preds[col]):.3f}")
    except ValueError:
        print("AUC=undefined")


def main():
    df, feature_cols = load_data(CSV_PATH)
    n_eval = len(df) - BURN_IN
    print(f"Loaded {len(df)} closed trades. Burn-in: {BURN_IN}. Evaluating {n_eval} trades walk-forward.")
    print(f"Features ({len(feature_cols)}): {feature_cols}\n")

    print("=== Baseline: copy everything ===")
    everything = df.iloc[BURN_IN:]["our_pnl_sol"]
    summarize("copy-everything", everything, n_eval)
    print_risk("copy-everything", risk_stats(everything))

    print("\n=== Baseline: trailing per-wallet win-rate filter (no ML) ===")
    wallet_baseline = trailing_wallet_win_rate_baseline(df)
    filtered = wallet_baseline[wallet_baseline["copy"]]["our_pnl_sol"]
    summarize("wallet-filter", filtered, n_eval)
    print_risk("wallet-filter", risk_stats(filtered))

    preds = walk_forward_all(df, feature_cols)
    for col in MODEL_NAMES + ["ensemble"]:
        report_model(preds, col, n_eval)

    print("\n=== Logistic Regression coefficients (trained on ALL data, for interpretability) ===")
    scaler = StandardScaler()
    x_all = scaler.fit_transform(df[feature_cols].fillna(0))
    lr = LogisticRegression(max_iter=1000).fit(x_all, df["label"])
    for feat, coef in sorted(zip(feature_cols, lr.coef_[0]), key=lambda x: -abs(x[1])):
        direction = "higher odds of profit" if coef > 0 else "lower odds of profit"
        print(f"  {feat}: {coef:+.3f} ({direction})")


if __name__ == "__main__":
    main()
