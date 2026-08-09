# Removed wallets

Every wallet costs 43,200 RPC calls/day to poll whether it trades or not, and
that budget is the binding constraint: the collector logs near-continuous
RateLimitExceeded, which is what drives the ~17s detection lag that dominates
every result. Polling a wallet we have no use for directly degrades the data
for the ones we do.

Removal is a much cheaper decision than addition. Rejecting a wallet needs
only evidence it is not worth a slot; accepting one needs evidence it has an
edge, which at these fat tails takes far more data. Nothing here is promoted
on the strength of looking good.

## Produced <=2 closed trades in 5 days of v3 collection

Pure cost, no signal. Either inactive, trading venues we do not parse, or
dead.

- `Earl` (F2SuErm4MviWJ2HzKXk2nuzBC6xe883CFWUDCPz6cyWm)
- `Trey` (831yhv67QpKqLBJjbmw2xoDUeeFHGUx8RnuRj9imeoEs)
- `Letterbomb` (BtMBMPkoNbnLF9Xn552guQq528KKXcsNBNNBre3oaQtr)
- `Felix` (3uz65G8e463MA5FxcSu1rTUyWRtrRLRZYskKtEHHj7qn)
- `Bi8gjp` (Bi8gjp6g7hYmLJ2gsHbtdMwHyin4js1efTzDdJSQ6m4T)
- `Pavel` (3jckt69SiN3aCMbBWJoDS1s4xxGpqNxFFKnwhpRAQmuL)
- `Pikalosi` (9cdZg6xR4c9kZiqKSzqjn4QHCXNQuC9HEWBzzMJ3mzqw)
- `dov7` (8nqtxpFpuXwfXG4pBLsDkkuMMPK9FjSkBMCn542HiM3v)
- `Nyhrox` (6S8GezkxYUfZy9JPtYnanbcZTMB87Wjt1qx3c6ELajKC)
- `Flames` (6aXFYXbFob1ZKAEDCcqZnX2vooA3TgEqDoy5dAQbeWoV)
- `Cented` (CyaE1VxvBrahnPWkqm5VsdCvyS2QmNht2UFrKJHga54o)
- `decu` (4vw54BmAogeRV3vPKWyFet5yf8DTLcREzdSzx4rw9Ud9)
- `West` (JDd3hy3gQn2V982mi1zqhNqUw1GfV2UL6g76STojCJPN)
- `Megga` (H31vEBxSJk1nQdUN11qZgZyhScyShhscKhvhZZU3dQoU)
- `Sebastian` (3BLjRcxWGtR7WRshJ3hL25U3RjWr5Ud98wMcczQqk4Ei)

## Losing with conclusive evidence

Scored on collector v3 data only (uncensored). `p_luck` is the share of
bootstrap resamples of the wallet's own trades that net <= 0.

| wallet | v3 trades | their P&L | win rate | days positive | p_luck |
|---|---|---|---|---|---|
| KOREAN | 286 | -97.75 | 22.4% | 0% | 1.000 |
| Cope | 91 | -53.61 | 17.6% | 0% | 1.000 |
| Insyder | 161 | -40.67 | 17.4% | 0% | 1.000 |
| Doji | 47 | -33.49 | 23.4% | 25% | 1.000 |
| Zuki | 111 | -26.44 | 27.9% | 20% | 0.996 |
| Monki | 85 | -2.07 | 45.9% | 25% | 0.604 |

- `Doji` (5ZuV8eqkvzYFVEKbLvGBdexL2tFv7E5BCd2HZpjqbdg)
- `Zuki` (922VvmmYDHV9KMTJJ71Y5Yd3Vn7cfJuFasLNSsZPygrG)
- `Cope` (23wQ7bodYreW3qhnh2YrW8dMkTYSkHHJqGcsiYEJS3Pr)
- `Monki` (53BnNc49Ajgstciq3CRoyxuBpkkW1r8pgPyvr7JGYnsh)
- `KOREAN` (6KR7SorsUQtNH6CB6JpAnWCAKeTysa95iyXeWihdNeGT)
- `Insyder` (G3g1CKqKWSVEVURZDNMazDBv7YAhMNTjhJBVRTiKZygk)

Monki is the weakest case (p_luck 0.604 -- consistent with no edge rather
than proven negative) and is removed for volume, not verdict: 85 trades that
are not earning their slot while candidates go unscreened.

## Note on Zuki

Zuki scored CONSISTENT on pooled v1+v2 data with p_luck 0.000 and appeared to
be the best wallet tracked. On uncensored v3 data it is -26.44 over 111
trades. The earlier verdict was an artifact of censored rows, and 89 of the
188 partial-position rows in the old dataset were Zuki's. Worth remembering
before re-adding anything on the strength of pre-v3 numbers.
