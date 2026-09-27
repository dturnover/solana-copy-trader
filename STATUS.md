# Status

Generated 2026-09-27 17:45 UTC. This file is written by a scheduled job -- nobody has to ask for it.

## Collection

- **1,731 closed round trips**, all collector v3, Aug 05 to Sep 27
- Newest trade **19 min old**
- **59 in the last 24h**, 116 in the last 7 days (16.6/day across 5 tracked wallets)
- **+14 since the last report** (2026-09-27 12:58 UTC)

## Detection lag

How stale a trade already was when the collector noticed it. This is what execution lag a row actually represents.

- Last 2 days: **median 2.7s**, p90 3.8s (74 rows)
- Before that: median 18.0s, p90 34.3s (1574 rows)

## Has anything been proven yet?

**Yes — 1:** theo

### Closest to a verdict

| wallet | trades | needs | P&L | win rate | days up | p_luck | last trade |
|---|---|---|---|---|---|---|---|
| Cented | 2 | 28 more | +2.49 | 50% | 50% | 0.251 | 50.8 d ago |
| Sebastian | 1 | 29 more | +2.26 | 100% | 100% | nan | 52.6 d ago |
| West | 2 | 28 more | +0.62 | 50% | 100% | 0.246 | 11.9 h ago |

- Cented needs 28 more trades; at its recent rate that is roughly 8 days away.
- Sebastian needs 29 more trades; at its recent rate that is roughly 9 days away.
- West needs 28 more trades; at its recent rate that is roughly 8 days away.

## Tracked wallets that have gone quiet

None — every tracked wallet has traded recently.

## Every wallet

| wallet | verdict | trades | P&L | win rate | days up | ex-top-3 | p_luck |
|---|---|---|---|---|---|---|---|
| theo | CONSISTENT | 40 | +70.11 | 88% | 95% | +54.49 | 0.000 |
| Sheep | UNSTABLE | 70 | +33.22 | 60% | 78% | +24.65 | 0.001 |
| Dani | UNPROVEN | 147 | +13.95 | 48% | 54% | -21.31 | 0.341 |
| Cented | INSUFFICIENT | 2 | +2.49 | 50% | 50% | — | 0.251 |
| Sebastian | INSUFFICIENT | 1 | +2.26 | 100% | 100% | — | — |
| West | INSUFFICIENT | 2 | +0.62 | 50% | 100% | — | 0.246 |
| Pavel | INSUFFICIENT | 31 | -0.24 | 23% | 0% | -0.36 | 0.974 |
| Letterbomb | INSUFFICIENT | 1 | -0.50 | 0% | 0% | — | — |
| dov7 | INSUFFICIENT | 4 | -3.24 | 0% | 0% | -0.87 | 1.000 |
| Felix | INSUFFICIENT | 12 | -4.18 | 8% | 0% | -5.19 | 0.969 |
| Pikalosi | INSUFFICIENT | 16 | -6.20 | 19% | 50% | -10.86 | 0.895 |
| Loopierr | INSUFFICIENT | 14 | -12.34 | 43% | 50% | -18.36 | 0.867 |
| Monki | LOSING | 88 | -2.65 | 46% | 20% | -9.43 | 0.617 |
| Kadenox | LOSING | 57 | -6.25 | 49% | 45% | -13.73 | 0.735 |
| Boomer | LOSING | 30 | -7.78 | 27% | 19% | -8.50 | 1.000 |
| Dedmeow5 | LOSING | 44 | -15.72 | 7% | 0% | -15.86 | 1.000 |
| Zuki | LOSING | 112 | -26.44 | 29% | 20% | -32.61 | 0.997 |
| Doji | LOSING | 59 | -41.68 | 20% | 20% | -44.39 | 1.000 |
| Insyder | LOSING | 193 | -42.79 | 19% | 0% | -48.74 | 1.000 |
| Cope | LOSING | 98 | -54.73 | 18% | 0% | -63.17 | 1.000 |
| KOREAN | LOSING | 445 | -147.63 | 24% | 0% | -155.55 | 1.000 |
| Tom | LOSING | 265 | -171.25 | 26% | 10% | -186.12 | 1.000 |

`ex-top-3` is P&L with the three best trades removed. A wallet whose edge vanishes there has shown you three good trades, not an edge -- which is how Zuki looked best-in-class on censored data while actually losing 26 SOL.

## Can we actually copy them?

Same-block execution, copying at a **fixed 0.25 SOL** instead of the wallet's own size, measured fees (2%/leg + 0.002 SOL/trip). `exit/entry` below 1 means we sell below where we bought -- the wallet is using us as exit liquidity.

| wallet | n | return/trade | win rate | exit/entry | median hold |
|---|---|---|---|---|---|
| Sheep | 28 | +13.4% | 57% | 1.19 | 4.2s |
| Pavel | 21 | +5.9% | 29% | 0.98 | 24.0s |
| Pikalosi | 8 | +4.6% | 38% | 0.99 | 21.3s |
| Dani | 9 | -0.1% | 56% | 1.05 | 3.8s |
| Kadenox | 5 | -6.4% | 20% | 1.02 | 14.0s |
| theo | 4 | -13.8% | 25% | 0.82 | 50.8s |
| West | 2 | -15.0% | 50% | 0.89 | 2.7s |

**This is a ceiling, not a forecast.** It assumes we land in the same block as the wallet. The collector's real detection lag is ~12s, and a wallet with a 3-second hold has already sold by then.

## Where does the edge die?

Return per trade copying at 0.25 SOL, by time from the wallet's trade to our fill (detection + 1.5s to submit and land). Cells are `return (trades)`; `·` means fewer than 3. Until 2026-09-24 nothing was ever seen under ~9s, so the fast columns fill in from then on. **The column where a row turns positive is the latency we would need.**

| wallet | same-block | 0-2s | 2-4s | 4-6s | 6-9s | 9-13s | 13-20s | 20s+ |
|---|---|---|---|---|---|---|---|---|
| Sheep | +13% (28) | · | -31% (7) | -47% (4) | · | -6% (9) | -6% (26) | · |
| Kadenox | -6% (5) | · | · | · | · | -36% (5) | -16% (30) | · |
| Pikalosi | +5% (8) | · | -10% (4) | · | · | · | · | · |
| Pavel | +6% (21) | · | -6% (12) | -16% (16) | · | · | · | -6% (3) |
| West | · | · | · | · | · | · | · | · |
| ALL | +5% (77) | · | -14% (24) | -22% (24) | · | -16% (24) | -22% (476) | -15% (388) |

## What we know

- **Copy size is the biggest cost lever, not speed.** Mirroring the wallet's size puts us straight after them on a curve they just pushed: position size vs fill penalty correlates at +0.84 (0.26 SOL fills at 1.007x, 5 SOL at 1.34x). Copy small.
- **Some good traders are uncopyable by construction.** theo is profitable but sells into strength; we exit after theo's own dump, 18% below entry. No speed fixes that.
- **At our old ~12s detection lag, every wallet loses money at every copy size** (924 clean round trips). Sheep goes from +15% at same-block to -5% at ~14s.
- **That 12s was never the free tier.** Polling asked for *finalized* transactions, which Solana only produces ~12.8s after they land. Switched to *confirmed* (~1s) on 2026-09-24. The table above will show whether that is fast enough before anything is spent on paid infrastructure.
- **Execution costs ~2% per leg all-in**, measured. The live collector applies none, so its simulated copy P&L is optimistic.
- **The RPC forgets transactions in ~2 days.** Same-block pricing now runs daily and saves the curve state, so each day's trades stay analysable.

