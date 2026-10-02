# Status

Generated 2026-10-02 22:57 UTC. This file is written by a scheduled job -- nobody has to ask for it.

## Collection

- **2,151 closed round trips**, all collector v3, Aug 05 to Oct 02
- Newest trade **5.8 h old**
- **45 in the last 24h**, 491 in the last 7 days (70.1/day across 2 tracked wallets)
- **+0 since the last report** (2026-10-02 18:31 UTC)

## Detection lag

How stale a trade already was when the collector noticed it. This is what execution lag a row actually represents.

- Last 2 days: **median 2.6s**, p90 3.7s (269 rows)
- Before that: median 17.2s, p90 30.9s (1799 rows)

## Has anything been proven yet?

**Yes — 1:** theo

### Closest to a verdict

| wallet | trades | needs | P&L | win rate | days up | p_luck | last trade |
|---|---|---|---|---|---|---|---|
| Cented | 2 | 28 more | +2.49 | 50% | 50% | 0.250 | 56.0 d ago |
| Sebastian | 1 | 29 more | +2.26 | 100% | 100% | nan | 57.8 d ago |
| West | 3 | 27 more | +0.08 | 33% | 50% | 0.402 | 3.5 d ago |

- Cented needs 28 more trades; at its recent rate that is roughly 1 days away.
- Sebastian needs 29 more trades; at its recent rate that is roughly 1 days away.
- West needs 27 more trades; at its recent rate that is roughly 1 days away.

## Tracked wallets that have gone quiet

None — every tracked wallet has traded recently.

## Every wallet

| wallet | verdict | trades | P&L | win rate | days up | ex-top-3 | p_luck |
|---|---|---|---|---|---|---|---|
| theo | CONSISTENT | 40 | +70.11 | 88% | 95% | +54.49 | 0.000 |
| Dani | UNPROVEN | 147 | +13.95 | 48% | 54% | -21.31 | 0.349 |
| Kadenox | UNPROVEN | 67 | +0.49 | 52% | 49% | -8.34 | 0.484 |
| Cented | INSUFFICIENT | 2 | +2.49 | 50% | 50% | — | 0.250 |
| Sebastian | INSUFFICIENT | 1 | +2.26 | 100% | 100% | — | — |
| West | INSUFFICIENT | 3 | +0.08 | 33% | 50% | — | 0.402 |
| Letterbomb | INSUFFICIENT | 1 | -0.50 | 0% | 0% | — | — |
| dov7 | INSUFFICIENT | 4 | -3.24 | 0% | 0% | -0.87 | 1.000 |
| Felix | INSUFFICIENT | 12 | -4.18 | 8% | 0% | -5.19 | 0.968 |
| Pikalosi | INSUFFICIENT | 21 | -8.15 | 19% | 33% | -12.81 | 0.948 |
| Loopierr | INSUFFICIENT | 14 | -12.34 | 43% | 50% | -18.36 | 0.872 |
| 6SB1n4 | INSUFFICIENT | 247 | -19.26 | 29% | 50% | -22.20 | 1.000 |
| Pavel | LOSING | 38 | -0.38 | 18% | 0% | -0.51 | 0.998 |
| Monki | LOSING | 88 | -2.65 | 46% | 20% | -9.43 | 0.623 |
| Sheep | LOSING | 220 | -3.86 | 42% | 64% | -13.41 | 0.589 |
| Boomer | LOSING | 30 | -7.78 | 27% | 19% | -8.50 | 1.000 |
| Dedmeow5 | LOSING | 44 | -15.72 | 7% | 0% | -15.86 | 1.000 |
| Zuki | LOSING | 112 | -26.44 | 29% | 20% | -32.61 | 0.998 |
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
| Sheep | 145 | +23.7% | 63% | 1.19 | 4.3s |
| Kadenox | 10 | +8.2% | 20% | 1.01 | 16.4s |
| Pikalosi | 11 | +1.4% | 36% | 0.94 | 22.3s |
| Dani | 9 | -0.1% | 56% | 1.05 | 3.8s |
| Pavel | 38 | -3.2% | 21% | 0.91 | 25.0s |
| 6SB1n4 | 158 | -4.0% | 34% | 0.96 | 11.5s |
| theo | 4 | -13.8% | 25% | 0.82 | 50.8s |
| West | 2 | -15.0% | 50% | 0.89 | 2.7s |

**This is a ceiling, not a forecast.** It assumes we land in the same block as the wallet. The collector's real detection lag is ~12s, and a wallet with a 3-second hold has already sold by then.

## Where does the edge die?

Return per trade copying at 0.25 SOL, by time from the wallet's trade to our fill (detection + 1.5s to submit and land). Cells are `return (trades)`; `·` means fewer than 3. Until 2026-09-24 nothing was ever seen under ~9s, so the fast columns fill in from then on. **The column where a row turns positive is the latency we would need.**

| wallet | same-block | 0-2s | 2-4s | 4-6s | 6-9s | 9-13s | 13-20s | 20s+ |
|---|---|---|---|---|---|---|---|---|
| Sheep | +24% (145) | · | -28% (42) | -28% (45) | · | -6% (9) | -6% (26) | -0% (3) |
| Kadenox | +8% (10) | · | -5% (3) | -34% (3) | · | -36% (5) | -16% (30) | · |
| ALL | +7% (377) | · | -13% (137) | -16% (156) | · | -16% (24) | -22% (476) | -15% (390) |

## At simulated gRPC speed

Return per copy at 0.25 SOL (measured fees), filled N blocks (~0.4s each) after the wallet, on both buy and sell. **"First in next block" is the best any copier can do** -- nothing lands inside the wallet's own block. Cells are `return (copies)`; `·` means fewer than 3.

| wallet | same block | first in next block | +1 block | +3 blocks | +10 blocks |
|---|---|---|---|---|---|
| 6SB1n4 | -4% (114) | -4% (114) | -4% (114) | -5% (114) | -4% (110) |
| Kadenox | +9% (8) | -7% (8) | -8% (8) | -10% (8) | -10% (8) |
| Pavel | -12% (29) | -12% (29) | -14% (29) | -13% (29) | -15% (29) |
| Pikalosi | +5% (12) | -11% (12) | -11% (12) | -12% (11) | -20% (11) |
| Sheep | +12% (150) | -21% (150) | -23% (143) | -22% (135) | -27% (124) |
| West | · | · | · | · | · |

## What we know

- **Copy size is the biggest cost lever, not speed.** Mirroring the wallet's size puts us straight after them on a curve they just pushed: position size vs fill penalty correlates at +0.84 (0.26 SOL fills at 1.007x, 5 SOL at 1.34x). Copy small.
- **Some good traders are uncopyable by construction.** theo is profitable but sells into strength; we exit after theo's own dump, 18% below entry. No speed fixes that.
- **At our old ~12s detection lag, every wallet loses money at every copy size** (924 clean round trips). Sheep goes from +15% at same-block to -5% at ~14s.
- **That 12s was never the free tier.** Polling asked for *finalized* transactions, which Solana only produces ~12.8s after they land. Switched to *confirmed* (~1s) on 2026-09-24. The table above will show whether that is fast enough before anything is spent on paid infrastructure.
- **Speed will not rescue these wallets (2026-09-29).** Simulated block by block, their edge exists only inside their own block: Sheep +25% same-block, -20% if first in the next one, and every tracked wallet is negative from there on. Bots swarm the same coins in the same block. Paying for gRPC buys ~1s; the edge is gone in 0.4s. The roster search must find wallets whose trades are still profitable at "first in next block".
- **Execution costs ~2% per leg all-in**, measured. The live collector applies none, so its simulated copy P&L is optimistic.
- **The RPC forgets transactions in ~2 days.** Same-block pricing now runs daily and saves the curve state, so each day's trades stay analysable.

