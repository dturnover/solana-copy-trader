# Status

Generated 2026-09-24 09:19 UTC. This file is written by a scheduled job -- nobody has to ask for it.

## Collection

- **1,651 closed round trips**, all collector v3, Aug 05 to Sep 23
- Newest trade **19.4 h old**  ⚠️ collector may be stuck
- **2 in the last 24h**, 52 in the last 7 days (7.4/day across 4 tracked wallets)
- **+0 since the last report** (2026-09-24 03:08 UTC)

## Detection lag

How stale a trade already was when the collector noticed it. This is what execution lag a row actually represents.

- Last 2 days: **median 10.3s**, p90 11.3s (22 rows)
- Before that: median 18.0s, p90 34.7s (1546 rows)
- ⚠️ Still above 10s. The 4s HTTP timeout should have brought this down; if it has not, the timeout was not the whole cause.

## Has anything been proven yet?

**Yes — 2:** theo, Sheep

### Closest to a verdict

| wallet | trades | needs | P&L | win rate | days up | p_luck | last trade |
|---|---|---|---|---|---|---|---|
| Cented | 2 | 28 more | +2.49 | 50% | 50% | 0.251 | 47.4 d ago |
| Sebastian | 1 | 29 more | +2.26 | 100% | 100% | nan | 49.2 d ago |

- Cented needs 28 more trades; at its recent rate that is roughly 15 days away.
- Sebastian needs 29 more trades; at its recent rate that is roughly 16 days away.

## Tracked wallets that have gone quiet

- **Kadenox** — last trade 6.2 d ago. Costs ~43,200 RPC calls/day regardless.

A silent wallet is not necessarily a dead one: it may be trading somewhere the collector does not parse. Either way it is spending poll budget for nothing.

## Every wallet

| wallet | verdict | trades | P&L | win rate | days up | ex-top-3 | p_luck |
|---|---|---|---|---|---|---|---|
| theo | CONSISTENT | 40 | +70.11 | 88% | 95% | +54.49 | 0.000 |
| Sheep | CONSISTENT | 41 | +44.99 | 83% | 90% | +36.42 | 0.000 |
| Dani | UNPROVEN | 147 | +13.95 | 48% | 54% | -21.31 | 0.341 |
| Cented | INSUFFICIENT | 2 | +2.49 | 50% | 50% | — | 0.251 |
| Sebastian | INSUFFICIENT | 1 | +2.26 | 100% | 100% | — | — |
| Letterbomb | INSUFFICIENT | 1 | -0.50 | 0% | 0% | — | — |
| dov7 | INSUFFICIENT | 4 | -3.24 | 0% | 0% | -0.87 | 1.000 |
| Felix | INSUFFICIENT | 12 | -4.18 | 8% | 0% | -5.19 | 0.969 |
| Loopierr | INSUFFICIENT | 14 | -12.34 | 43% | 50% | -18.36 | 0.868 |
| Monki | LOSING | 88 | -2.65 | 46% | 20% | -9.43 | 0.618 |
| Boomer | LOSING | 30 | -7.78 | 27% | 19% | -8.50 | 1.000 |
| Kadenox | LOSING | 55 | -8.05 | 49% | 43% | -15.53 | 0.792 |
| Dedmeow5 | LOSING | 44 | -15.72 | 7% | 0% | -15.86 | 1.000 |
| Zuki | LOSING | 112 | -26.44 | 29% | 20% | -32.61 | 0.996 |
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
| Sheep | 10 | +14.7% | 80% | 1.23 | 2.8s |
| Dani | 9 | -0.1% | 56% | 1.05 | 3.8s |
| Kadenox | 4 | -5.3% | 25% | 1.03 | 35.5s |
| theo | 4 | -13.8% | 25% | 0.82 | 50.8s |

**This is a ceiling, not a forecast.** It assumes we land in the same block as the wallet. The collector's real detection lag is ~12s, and a wallet with a 3-second hold has already sold by then.

## Where does the edge die?

Return per trade copying at 0.25 SOL, by time from the wallet's trade to our fill (detection + 1.5s to submit and land). Cells are `return (trades)`; `·` means fewer than 3. Until 2026-09-24 nothing was ever seen under ~9s, so the fast columns fill in from then on. **The column where a row turns positive is the latency we would need.**

| wallet | same-block | 0-2s | 2-4s | 4-6s | 6-9s | 9-13s | 13-20s | 20s+ |
|---|---|---|---|---|---|---|---|---|
| theo | -14% (4) | · | · | · | · | · | -35% (3) | · |
| Sheep | +15% (10) | · | · | · | · | -6% (9) | -6% (26) | · |
| Dani | -0% (9) | · | · | · | · | -13% (10) | -23% (57) | -7% (14) |
| Kadenox | -5% (4) | · | · | · | · | -36% (5) | -16% (30) | · |
| ALL | +3% (27) | · | · | · | · | -16% (24) | -22% (476) | -15% (385) |

## What we know

- **Copy size is the biggest cost lever, not speed.** Mirroring the wallet's size puts us straight after them on a curve they just pushed: position size vs fill penalty correlates at +0.84 (0.26 SOL fills at 1.007x, 5 SOL at 1.34x). Copy small.
- **Some good traders are uncopyable by construction.** theo is profitable but sells into strength; we exit after theo's own dump, 18% below entry. No speed fixes that.
- **At our old ~12s detection lag, every wallet loses money at every copy size** (924 clean round trips). Sheep goes from +15% at same-block to -5% at ~14s.
- **That 12s was never the free tier.** Polling asked for *finalized* transactions, which Solana only produces ~12.8s after they land. Switched to *confirmed* (~1s) on 2026-09-24. The table above will show whether that is fast enough before anything is spent on paid infrastructure.
- **Execution costs ~2% per leg all-in**, measured. The live collector applies none, so its simulated copy P&L is optimistic.
- **The RPC forgets transactions in ~2 days.** Same-block pricing now runs daily and saves the curve state, so each day's trades stay analysable.

