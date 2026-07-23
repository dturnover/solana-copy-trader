# LightGBM trade-copy classifier — experiment

Question: given the paper-trading data collected so far, does a binary
"should we copy this trade" classifier add value over simple wallet-selection
heuristics?

## Methodology

- **Walk-forward, not random split.** Trades sorted chronologically by
  position-close time. At each step the model trains only on trades that
  closed *before* the one being evaluated, then that trade's true outcome is
  folded into training data before moving to the next ("little by little," as
  requested) — never trains on future information relative to what it's
  predicting.
- **Data**: `data/paper_trades_combined.csv` is every closed round trip
  collected across CI runs during this session (239 rows, 8 wallets).
  `data/paper_trades_clean.csv` drops rows where the constant-product
  simulation blew up (a bug found and fixed in `main_paper_trade.cpp` on
  `master` after this branch was cut — see that commit). **Use the `_clean`
  file** — the raw one is kept only for comparison.
- **Features** (all knowable before the outcome, in principle):
  `wallet_label`, `buy_count`, `wallet_token_amount`, `wallet_lamports_spent`,
  `avg_buy_price_lamports`.
- **Known leakage caveat**: `paper_trade.cpp` logs one row per *closed*
  position with cumulative totals across every buy in it. For positions
  built from more than one buy, the amount/price fields include tokens
  bought *after* the position was already open — information a real
  "copy the first buy" decision wouldn't have had yet. Not fixable
  retroactively; would need paper_trade to log features at position-open
  time instead of close time.
- **Baselines compared**: (1) copy every trade, (2) copy only when that
  specific wallet's trailing (prior-only) mean P&L is positive — the "just
  copy good wallets" rule already found by hand — and (3) the LightGBM
  classifier's walk-forward predictions.

## Results (`paper_trades_clean.csv`, 181 trades evaluated after a 40-trade burn-in)

| Strategy | Trades copied | Win rate | Total P&L |
|---|---|---|---|
| Copy everything | 181/181 | 21.0% | -96.8 SOL |
| Trailing wallet-win-rate filter (no ML) | 18/181 | 61.1% | +13.4 SOL |
| LightGBM @ p>0.5 | 34/181 | 44.1% | **+15.1 SOL** |
| LightGBM @ p>0.6 | 29/181 | 44.8% | +13.7 SOL |
| LightGBM @ p>0.7 | 21/181 | 38.1% | +9.7 SOL |

Classifier quality @ p>0.5: accuracy 0.77, precision 0.44, recall 0.40,
**AUC 0.70** (0.5 = random).

Feature importance: `wallet_lamports_spent` and `wallet_token_amount` and
`avg_buy_price_lamports` dominate; **`wallet_label` importance is ~0**.

## Honest read

- Both the simple heuristic and the ML model demolish "copy everything" —
  confirms again that indiscriminate copying is a loser regardless of method.
- LightGBM modestly beats the simple wallet-filter in total P&L (+15.1 vs
  +13.4 SOL) while copying ~2x as many trades (34 vs 18) at a lower win rate
  (44% vs 61%) — it's finding more opportunities at similar total profit,
  not a dramatically bigger edge.
- The interesting/surprising part: `wallet_label` is barely used. The model
  is keying almost entirely on **position size and entry price**, not who's
  trading. That's either (a) a real, generalizable pattern independent of
  wallet identity, or (b) the model reconstructing wallet identity
  indirectly through each wallet's characteristic size range. Can't tell
  which from this data.
- AUC 0.70 and precision 0.44 are "meaningfully better than a coin flip,"
  not "reliable enough to trust blindly" — more than half of the model's
  "copy" calls still lose money.
- n=34 copied trades in the evaluation window is a small sample to draw a
  durable conclusion from. The ~+1.7 SOL edge over the simple baseline could
  easily be noise rather than a robust, generalizable effect.

## Bottom line

**Modest, above-random signal that ML adds a little value beyond pure
wallet-selection, but not enough evidence yet to trust it as a real filter.**
Worth revisiting once (a) CI has collected meaningfully more *clean*
(post-fix) data, and (b) paper_trade logs richer pre-trade features (bonding
curve reserves/price-impact at buy time, priority fee, token age, per-wallet
rolling win rate as an explicit feature) rather than relying on this thin,
partially-leaky feature set.
