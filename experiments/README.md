# Trade-copy classifier experiments

Question: given the paper-trading data collected so far, does a binary
"should we copy this trade" classifier add value over simple wallet-selection
heuristics -- and given how little data we have, is LightGBM even the right
model, or does something more data-efficient do as well or better while
staying interpretable?

## Methodology

- **Walk-forward, not random split.** Trades sorted chronologically by
  position-close time. At each step every model trains only on trades that
  closed *before* the one being evaluated, then that trade's true outcome is
  folded into training data before moving to the next ("little by little").
- **Data pipeline**: `dedupe_and_clean.py` removes (a) duplicate closed-trade
  rows -- found because each CI run starts with no persisted cursor and can
  re-detect/re-log the same historical close across separate runs (8 pairs
  found in the first pass; `paper_trade.cpp` now logs the closing sell's
  signature so future data dedupes exactly instead of by approximate key),
  and (b) rows where the constant-product simulation blew up (a bug found
  and fixed in `main_paper_trade.cpp` on `master` -- see that commit).
  `data/paper_trades_final.csv` (215 rows) is the clean result; use that one.
- **Features**: `buy_count`, `wallet_token_amount`, `wallet_lamports_spent`,
  `avg_buy_price_lamports`, plus one-hot wallet identity. Same leakage
  caveat as before applies to the cumulative-amount fields on multi-buy
  positions -- see `lgbm_trade_classifier.py`'s docstring for the full
  explanation, not re-litigated here.
- **Baselines**: copy-everything, and the trailing per-wallet win-rate filter
  (the "just copy good wallets" rule already found by hand).

## Results (`paper_trades_final.csv`, 175 trades evaluated after a 40-trade burn-in)

| Strategy | Trades copied | Win rate | Total P&L | AUC | Precision |
|---|---|---|---|---|---|
| Copy everything | 175 | 21.1% | -95.9 SOL | - | - |
| Wallet-filter (no ML) | 18 | 61.1% | +13.4 SOL | - | - |
| **Logistic Regression @ p>0.5** | 22 | **63.6%** | **+19.8 SOL** | **0.745** | **0.636** |
| Random Forest @ p>0.5 | 17 | 58.8% | +16.4 SOL | 0.724 | 0.588 |
| LightGBM @ p>0.5 | 31 | 54.8% | +19.9 SOL | 0.738 | 0.548 |

**Logistic Regression wins or ties on every metric that matters**, despite
being the simplest model here. It matches LightGBM's total P&L while copying
30% fewer trades (22 vs 31) at meaningfully higher precision (64% vs 55%) --
i.e. it's pickier and each pick is more trustworthy, not just riding more
volume to the same total. It also has the best AUC. With ~215 rows, that's
not surprising: gradient boosting has more capacity to overfit noise than a
regularized linear model does, and there isn't enough data yet for that
extra capacity to pay for itself.

### Logistic regression coefficients (full interpretability, no SHAP needed)

```
wallet_lamports_spent:   -1.464  (bigger spend -> lower odds of profit)
wallet_theo:             +0.870  (confirms the manual finding)
avg_buy_price_lamports:  +0.650  (higher entry price -> higher odds -- established/momentum tokens?)
wallet_token_amount:     -0.449  (bigger token amount -> lower odds, consistent with lamports_spent)
wallet_Doji/Sheep/Letterbomb: negative (confirms these are bad wallets)
buy_count:               +0.333  (adding to a position slightly correlates with it working out)
wallet_Pavel:            +0.309
wallet_Zuki:             +0.001  (~zero -- see below)
```

**The interesting convergent finding**: both this run and the earlier
LightGBM-only experiment independently landed on the same surprising result
-- wallet identity carries less signal than position size/entry price do.
`wallet_Zuki`'s own coefficient here is ~0, even though Zuki looked clearly
bad in the raw aggregate stats -- suggesting his badness is being explained
by *how* he sizes/prices trades (which the continuous features already
capture) rather than by "being Zuki" specifically. Two different model
families agreeing on this independently is a real reason to take it
seriously rather than dismiss it as one model's quirk -- but it's still
n=215, so "real, generalizable pattern" and "artifact of this particular
window of data" remain both plausible.

## Recommendation

**Switch the default to Logistic Regression at the current data volume.**
It's simultaneously the best performer and the most interpretable option --
there's no trade-off to make here, unlike the usual "simple vs. powerful"
tension. Revisit LightGBM (or gradient boosting generally) once there's
meaningfully more clean data (many hundreds to low thousands of closed
trades) where its extra capacity has room to find real non-linear patterns
instead of noise. Random Forest sits in between and isn't clearly better
than either at this size -- no strong reason to use it over the other two
right now.

Still true regardless of model choice: n=215 (and only ~18-31 trades ever
actually "copied" by any of these strategies) is a small sample to trust as
a durable edge. The consistent direction across three different model
families is encouraging, not conclusive.
