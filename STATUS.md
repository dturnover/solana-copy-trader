# Status

Generated 2026-09-11 09:09 UTC. This file is written by a scheduled job -- nobody has to ask for it.

## Collection

- **1,561 closed round trips**, all collector v3, Aug 05 to Sep 10
- Newest trade **12.0 h old**
- **4 in the last 24h**, 32 in the last 7 days (4.6/day across 4 tracked wallets)
- **+0 since the last report** (2026-09-11 02:31 UTC)

## Detection lag

How stale a trade already was when the collector noticed it. This is what execution lag a row actually represents.

- Last 2 days: **median 12.6s**, p90 12.9s (9 rows)
- Before that: median 18.3s, p90 36.0s (1469 rows)
- ⚠️ Still above 10s. The 4s HTTP timeout should have brought this down; if it has not, the timeout was not the whole cause.

## Has anything been proven yet?

**Yes — 2:** theo, Sheep

### Closest to a verdict

| wallet | trades | needs | P&L | win rate | days up | p_luck | last trade |
|---|---|---|---|---|---|---|---|
| Cented | 2 | 28 more | +2.49 | 50% | 50% | 0.251 | 34.4 d ago |
| Sebastian | 1 | 29 more | +2.26 | 100% | 100% | nan | 36.2 d ago |

- Cented needs 28 more trades; at its recent rate that is roughly 24 days away.
- Sebastian needs 29 more trades; at its recent rate that is roughly 25 days away.

## Tracked wallets that have gone quiet

None — every tracked wallet has traded recently.

## Every wallet

| wallet | verdict | trades | P&L | win rate | days up | ex-top-3 | p_luck |
|---|---|---|---|---|---|---|---|
| theo | CONSISTENT | 31 | +49.39 | 84% | 93% | +35.03 | 0.000 |
| Sheep | CONSISTENT | 30 | +32.29 | 80% | 87% | +24.08 | 0.000 |
| Dani | UNPROVEN | 84 | +29.69 | 51% | 59% | -2.78 | 0.115 |
| Cented | INSUFFICIENT | 2 | +2.49 | 50% | 50% | — | 0.251 |
| Sebastian | INSUFFICIENT | 1 | +2.26 | 100% | 100% | — | — |
| Letterbomb | INSUFFICIENT | 1 | -0.50 | 0% | 0% | — | — |
| dov7 | INSUFFICIENT | 4 | -3.24 | 0% | 0% | -0.87 | 1.000 |
| Felix | INSUFFICIENT | 12 | -4.18 | 8% | 0% | -5.19 | 0.969 |
| Loopierr | INSUFFICIENT | 14 | -12.34 | 43% | 50% | -18.36 | 0.868 |
| Monki | LOSING | 88 | -2.65 | 46% | 20% | -9.43 | 0.619 |
| Kadenox | LOSING | 48 | -7.42 | 50% | 42% | -14.90 | 0.778 |
| Boomer | LOSING | 30 | -7.78 | 27% | 19% | -8.50 | 1.000 |
| Dedmeow5 | LOSING | 44 | -15.72 | 7% | 0% | -15.86 | 1.000 |
| Zuki | LOSING | 112 | -26.44 | 29% | 20% | -32.61 | 0.998 |
| Doji | LOSING | 59 | -41.68 | 20% | 20% | -44.39 | 1.000 |
| Insyder | LOSING | 193 | -42.79 | 19% | 0% | -48.74 | 1.000 |
| Cope | LOSING | 98 | -54.73 | 18% | 0% | -63.17 | 1.000 |
| KOREAN | LOSING | 445 | -147.63 | 24% | 0% | -155.55 | 1.000 |
| Tom | LOSING | 265 | -171.25 | 26% | 10% | -186.12 | 1.000 |

`ex-top-3` is P&L with the three best trades removed. A wallet whose edge vanishes there has shown you three good trades, not an edge -- which is how Zuki looked best-in-class on censored data while actually losing 26 SOL.

## Settled

- **gRPC: no.** Filling in the same block as the wallet -- the floor no speed purchase can beat -- still loses money (-39.14 SOL over 57 round trips). Latency is worth ~32 SOL of that; the rest is the wallets.
- **Execution costs 243 bps per leg** (~4.9% round trip), measured. The collector applies none of it, so simulated copy P&L is optimistic by that much. Wallet-side figures are unaffected.
- **The RPC forgets transactions after ~3.5 days.** Anything not replayed or screened within that window can never be re-priced.

