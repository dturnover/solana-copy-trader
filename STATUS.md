# Status

Generated 2026-09-07 18:19 UTC. This file is written by a scheduled job -- nobody has to ask for it.

## Collection

- **1,545 closed round trips**, all collector v3, Aug 05 to Sep 07
- Newest trade **44 min old**
- **4 in the last 24h**, 33 in the last 7 days (4.7/day across 4 tracked wallets)
- **+1 since the last report** (2026-09-07 17:20 UTC)

## Detection lag

How stale a trade already was when the collector noticed it. This is what execution lag a row actually represents.

- Last 2 days: **median 11.4s**, p90 708.5s (8 rows)
- Before that: median 18.3s, p90 36.2s (1454 rows)
- ⚠️ Still above 10s. The 4s HTTP timeout should have brought this down; if it has not, the timeout was not the whole cause.

## Has anything been proven yet?

**Yes — 1:** theo

### Closest to a verdict

| wallet | trades | needs | P&L | win rate | days up | p_luck | last trade |
|---|---|---|---|---|---|---|---|
| Sheep | 27 | 3 more | +27.55 | 78% | 85% | 0.000 | 4.7 d ago |
| Cented | 2 | 28 more | +2.49 | 50% | 50% | 0.251 | 30.8 d ago |
| Sebastian | 1 | 29 more | +2.26 | 100% | 100% | nan | 32.6 d ago |

- Sheep needs 3 more trades; at its recent rate that is roughly 3 days away.
- Cented needs 28 more trades; at its recent rate that is roughly 24 days away.
- Sebastian needs 29 more trades; at its recent rate that is roughly 25 days away.

## Tracked wallets that have gone quiet

None — every tracked wallet has traded recently.

## Every wallet

| wallet | verdict | trades | P&L | win rate | days up | ex-top-3 | p_luck |
|---|---|---|---|---|---|---|---|
| theo | CONSISTENT | 30 | +45.62 | 83% | 92% | +31.26 | 0.000 |
| Dani | UNPROVEN | 79 | +27.93 | 51% | 58% | -4.55 | 0.128 |
| Sheep | INSUFFICIENT | 27 | +27.55 | 78% | 85% | +19.33 | 0.000 |
| Cented | INSUFFICIENT | 2 | +2.49 | 50% | 50% | — | 0.251 |
| Sebastian | INSUFFICIENT | 1 | +2.26 | 100% | 100% | — | — |
| Letterbomb | INSUFFICIENT | 1 | -0.50 | 0% | 0% | — | — |
| dov7 | INSUFFICIENT | 4 | -3.24 | 0% | 0% | -0.87 | 1.000 |
| Felix | INSUFFICIENT | 12 | -4.18 | 8% | 0% | -5.19 | 0.969 |
| Loopierr | INSUFFICIENT | 14 | -12.34 | 43% | 50% | -18.36 | 0.866 |
| Kadenox | LOSING | 41 | -2.51 | 51% | 43% | -9.55 | 0.624 |
| Monki | LOSING | 88 | -2.65 | 46% | 20% | -9.43 | 0.620 |
| Boomer | LOSING | 30 | -7.78 | 27% | 19% | -8.50 | 1.000 |
| Dedmeow5 | LOSING | 44 | -15.72 | 7% | 0% | -15.86 | 1.000 |
| Zuki | LOSING | 112 | -26.44 | 29% | 20% | -32.61 | 0.997 |
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

