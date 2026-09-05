# Status

Generated 2026-09-05 01:55 UTC. This file is written by a scheduled job -- nobody has to ask for it.

## Collection

- **1,534 closed round trips**, all collector v3, Aug 05 to Sep 04
- Newest trade **5.9 h old**
- **5 in the last 24h**, 26 in the last 7 days (3.7/day across 4 tracked wallets)
- **+0 since the last report** (2026-09-04 22:19 UTC)

## Has anything been proven yet?

**No.** No wallet has cleared the bar: enough trades, profitable, survives removing its best three trades, and holds up across both halves of its own history.

### Closest to a verdict

| wallet | trades | needs | P&L | win rate | days up | p_luck | last trade |
|---|---|---|---|---|---|---|---|
| theo | 24 | 6 more | +35.45 | 79% | 91% | 0.002 | 9.7 h ago |
| Sheep | 27 | 3 more | +27.55 | 78% | 85% | 0.000 | 2.1 d ago |
| Cented | 2 | 28 more | +2.49 | 50% | 50% | 0.251 | 28.1 d ago |
| Sebastian | 1 | 29 more | +2.26 | 100% | 100% | nan | 29.9 d ago |

- theo needs 6 more trades; at its recent rate that is roughly 6 days away.
- Sheep needs 3 more trades; at its recent rate that is roughly 3 days away.
- Cented needs 28 more trades; at its recent rate that is roughly 30 days away.
- Sebastian needs 29 more trades; at its recent rate that is roughly 31 days away.

## Tracked wallets that have gone quiet

None — every tracked wallet has traded recently.

## Every wallet

| wallet | verdict | trades | P&L | win rate | days up | ex-top-3 | p_luck |
|---|---|---|---|---|---|---|---|
| Dani | UNPROVEN | 77 | +26.86 | 49% | 56% | -5.61 | 0.141 |
| theo | INSUFFICIENT | 24 | +35.45 | 79% | 91% | +21.09 | 0.002 |
| Sheep | INSUFFICIENT | 27 | +27.55 | 78% | 85% | +19.33 | 0.000 |
| Cented | INSUFFICIENT | 2 | +2.49 | 50% | 50% | — | 0.251 |
| Sebastian | INSUFFICIENT | 1 | +2.26 | 100% | 100% | — | — |
| Letterbomb | INSUFFICIENT | 1 | -0.50 | 0% | 0% | — | — |
| dov7 | INSUFFICIENT | 4 | -3.24 | 0% | 0% | -0.87 | 1.000 |
| Felix | INSUFFICIENT | 12 | -4.18 | 8% | 0% | -5.19 | 0.969 |
| Loopierr | INSUFFICIENT | 14 | -12.34 | 43% | 50% | -18.36 | 0.866 |
| Kadenox | LOSING | 38 | -2.13 | 53% | 47% | -9.17 | 0.604 |
| Monki | LOSING | 88 | -2.65 | 46% | 20% | -9.43 | 0.618 |
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

