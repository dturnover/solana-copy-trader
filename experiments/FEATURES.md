# Feature list for the copy/skip classifier

The model in `experiment/lgbm-trade-classifier` currently trains on five
features: `wallet_label`, `buy_count`, `wallet_token_amount`,
`wallet_lamports_spent`, `avg_buy_price_lamports`. That is all there is,
because that is all `paper_trade` logs.

**Features cannot be added to the model before they are added to the
collector.** Every indicator below is annotated with where it would come
from and what it costs to capture, because the gap between "we want this
feature" and "this feature exists in a CSV" is the entire job.

## The rule that governs everything here

A feature is only legitimate if its value is **fixed at the moment we would
have decided to copy the buy**. Anything sampled later — including anything
read at position close — leaks the outcome.

This matters most for exactly the indicators requested. "Liquidity" measured
*after* a rug trivially predicts that the trade lost money; the model learns
to read the future and reports superb accuracy that evaporates live. The
same trap already exists in the current feature set and is documented in the
classifier's docstring: `wallet_token_amount`, `wallet_lamports_spent` and
`buy_count` are cumulative across every buy in the position, so for
`buy_count > 1` they include amounts added after entry.

The `entry_*` columns added to `paper_trade` are snapshotted on the **first
buy only**, for this reason.

## A caveat about the "classic" rug checklist

Most of the standard Photon / DexScreener rug indicators were designed for
Raydium and ordinary SPL launches. For pump.fun **bonding-curve** tokens —
which is what this repo tracks pre-migration — a large share of them are
constant by construction and carry exactly zero information:

| Classic indicator | Status on a pump.fun bonding curve |
|---|---|
| Mint authority renounced | Always renounced by the program. Constant → no signal. |
| Freeze authority null | Always null. Constant → no signal. |
| LP burned / locked % | **No LP token exists** pre-migration. Liquidity *is* the curve; the dev cannot pull it. Only meaningful post-migration. |
| Liquidity can be removed | Impossible pre-migration. Structurally different risk. |
| Honeypot / sell tax | Not expressible on the pump.fun program. |

Including these as features would add columns that are either constant or
undefined, which costs training signal and invites the model to fit noise.
They become meaningful **only** for tokens that have migrated to Raydium —
`complete = true` on the curve. Worth capturing then, not before.

The real failure modes for a bonding-curve token are different, and that is
what the tiers below prioritise: **dev/sniper concentration, how far up the
curve you are entering, and how big your entry is relative to the pool.**

## Tier 0 — free, already captured

Derived from the bonding-curve read `paper_trade` already performs at the
decision instant. No extra RPC calls, no added latency. **Implemented** —
these columns are in the CSV now and accumulate from the next collector run.

Raw columns: `entry_virtual_sol_reserves`, `entry_virtual_token_reserves`,
`entry_real_sol_reserves`, `entry_real_token_reserves`,
`entry_token_total_supply`, `entry_our_cost_lamports`.

Raw reserves are logged rather than pre-computed ratios so the feature layer
owns the definitions and the collector does not hardcode pump.fun's
migration constants.

| Feature | Definition | Reads as |
|---|---|---|
| `liquidity_sol` | `entry_real_sol_reserves / 1e9` | Pool depth. The single most useful risk number available for free. |
| `curve_progress` | `1 - entry_real_token_reserves / entry_token_total_supply` | How far up the curve. Entering near the top means most of the upside is already gone. |
| `entry_price` | `virtual_sol / virtual_token` | Price paid, comparable across tokens. |
| `market_cap_sol` | `entry_price * entry_token_total_supply / 1e9` | Valuation at entry. |
| `liq_to_mcap` | `liquidity_sol / market_cap_sol` | The classic thin-liquidity ratio. Low = a small sell craters it. |
| `size_vs_liquidity` | `entry_our_cost_lamports / entry_real_sol_reserves` | **Our own price impact.** Directly explains the blow-up fills already in the data. |
| `wallet_size_vs_liquidity` | `wallet_lamports_spent / entry_real_sol_reserves` | How hard the tracked wallet moved the pool. |

## Tier 1 — one extra RPC call per detected buy

**This is not free on the current setup.** The collector already logs
near-continuous `RateLimitExceeded` on the free Shyft tier; polls are failing
across most wallets for hours at a time. Every added call per buy raises
detection lag and loses more trades outright. Measure the hit before
enabling — this is a direct trade against the ~17s detection lag that
already dominates results.

| Feature | Source | Notes |
|---|---|---|
| `holder_count` | `getTokenLargestAccounts` | Returns top 20 only; a true count needs `getProgramAccounts` (Tier 2). |
| `top10_concentration` | `getTokenLargestAccounts` | Share of supply in the top 10. The core rug proxy for pump.fun. |
| `dev_holding_pct` | Creator account balance | Dev still holding a large share = classic dump risk. |
| `token_age_seconds` | Curve account creation slot | Very young tokens are a different regime entirely. |
| `is_migrated` | `complete` flag | Gates every Raydium-only indicator in the table above. |

## Tier 2 — expensive, defer

| Feature | Why it costs |
|---|---|
| `bundled_buy_count` / sniper count | Requires pulling and parsing the token's first N transactions. |
| `dev_has_sold` | Requires the creator's full transaction history. |
| `holder_distribution` (gini) | `getProgramAccounts` on the mint — heavy, frequently rate-limited or disabled. |
| Prior rugs by same creator | Needs a creator→token index built and maintained over time. |

## SOL 24h price movement

Requested as market-regime context, and justified: when SOL sells off,
memecoins sell off harder, so the same trade is not the same bet in both
regimes. The Aug 4–5 collapse in this dataset — every wallet negative, win
rates falling from ~40% to ~19% — is exactly the kind of regime a model
cannot see with the current feature set.

Implementation options, cheapest first:

1. **Self-sourced series (recommended).** Sample SOL/USD once per poll cycle
   and append to a small CSV; derive 24h change offline. No external
   dependency, no per-buy cost, and one sample per cycle is negligible
   against the existing poll volume.
2. **Pyth on-chain price account.** One `getAccountInfo` on the SOL/USD
   feed, same RPC, no new provider. Gives spot only — 24h change still needs
   a stored series, so it collapses into option 1.
3. **External price API.** Adds a network dependency to a CI job that is
   already fighting rate limits, for data option 1 provides for free.

Derived features once a series exists: `sol_return_24h`, `sol_return_1h`,
`sol_volatility_24h`, and a regime flag. All are decision-time safe: they
describe the world *before* the buy.

## Sequencing

Worth being blunt about where this sits. The current dataset says copying
these wallets loses money before execution quality is even considered, and
the only uncensored data is a two-day window in which no wallet clears the
scorecard's evidence bar. **A classifier cannot rescue a negative-edge
strategy** — it can only select a subset of it, and it needs far more clean
rows than exist today to do even that without overfitting.

The reason to land the capture work now is that features must accumulate
before they can be modelled. Every day the collector runs without them is a
day of training data that cannot be reconstructed. Build the pipe now, train
when there is something worth training on — and train only on
`collector_version >= 3`, since earlier rows are a censored sample whose
drop rate varies by wallet.

## Hold duration — measured, and it is a wallet feature, not a trade feature

Requested on the hunch that longer holds are more solid. The data supports
it at trade level, strongly:

| wallet's hold time | n | their P&L | mean | win rate |
|---|---|---|---|---|
| < 10s | 844 | −205.45 | −0.243 | 25.0% |
| 10–30s | 758 | −37.15 | −0.049 | 30.6% |
| 30–60s | 295 | **+39.52** | +0.134 | 42.7% |
| 1–5m | 382 | **+106.62** | +0.279 | 48.2% |
| 5–30m | 112 | +1.94 | +0.017 | 42.9% |
| > 30m | 31 | +2.66 | +0.086 | 32.3% |

Split at 30 seconds: trades held under it lose 242.59 SOL, trades held over
it make 150.73. Every loss in this dataset lives in the fast flips.

**But hold time cannot be a feature of the copy/skip model.** It is not
known until the position closes — using it is precisely the leakage this
document warns about. It is only usable in two legitimate forms:

1. **The wallet's historical median hold**, known before any given buy.
2. As an explanation of *why* certain wallets are uncopyable, below.

### The mechanism: we arrive after they have already left

Effective execution lag on the free tier is ~18.5s (≈17s detection + 1.5s
configured). A wallet whose median hold is *shorter than that* has already
exited before our buy would land. We are not copying them; we are their exit
liquidity.

Splitting wallets on that threshold separates the book almost perfectly:

| wallets | median hold | trades | their P&L |
|---|---|---|---|
| Felix, Insyder, KOREAN, Kadenox, Monki, Sheep, Tom | < 20s | 1420 | **−403.09** |
| Cope, Dedmeow5, Doji, Zuki, theo | ≥ 20s | 920 | **+301.15** |

`wallet_median_hold_seconds` is therefore a first-class decision-time
feature, computed from the wallet's own prior closed trades. Its natural
companion is `wallet_median_hold / execution_lag` — a ratio below ~1 means
the trade is mechanically uncopyable at current latency.

Note this is a *trade-level* effect, not a claim that slow wallets are good
traders: across wallets the rank correlation between median hold and mean
P&L is only 0.14, and Dedmeow5 holds longest of all while losing money.

### A caveat this dataset cannot answer

`position_timeout_minutes: 180` abandons any position open longer than three
hours, and abandoned positions are never written. So the dataset is censored
on exactly the dimension being asked about, and cannot show whether holds
beyond three hours are better still. No position currently comes near the
cutoff (longest observed: 2.7h, and only 31 trades exceed 30 minutes), so it
is not biting yet — but raise the timeout before concluding anything about
long holds.
