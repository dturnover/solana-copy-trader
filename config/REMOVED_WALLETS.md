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
| Tom | 265 | -171.25 | 26.0% | 10.5% | 1.000 |

- `Doji` (5ZuV8eqkvzYFVEKbLvGBdexL2tFv7E5BCd2HZpjqbdg)
- `Zuki` (922VvmmYDHV9KMTJJ71Y5Yd3Vn7cfJuFasLNSsZPygrG)
- `Cope` (23wQ7bodYreW3qhnh2YrW8dMkTYSkHHJqGcsiYEJS3Pr)
- `Monki` (53BnNc49Ajgstciq3CRoyxuBpkkW1r8pgPyvr7JGYnsh)
- `KOREAN` (6KR7SorsUQtNH6CB6JpAnWCAKeTysa95iyXeWihdNeGT)
- `Insyder` (G3g1CKqKWSVEVURZDNMazDBv7YAhMNTjhJBVRTiKZygk)
- `Tom` (CEUA7zVoDRqRYoeHTP58UHU6TR8yvtVbeLrX1dppqoXJ)

Tom is the most conclusive entry in this table and the last one removed,
because he was the only tracked wallet with a full 19 days of v3 history --
the others were cut after five. That length is what makes it conclusive
rather than merely bad: 265 trades, profitable on 2 of 19 days, and every
one of 10,000 bootstrap resamples of his own trades nets negative. He also
dominated the collector, producing 98 of the 163 round trips in the last
seven days -- more than the other seven wallets combined -- so he was
setting the pace of data collection while being the thing the data most
clearly rejects. Over that week Tom lost 85.69 SOL while the rest of the
tracked set together made 20.59.

Monki is the weakest case (p_luck 0.604 -- consistent with no edge rather
than proven negative) and is removed for volume, not verdict: 85 trades that
are not earning their slot while candidates go unscreened.

## Note on Zuki

Zuki scored CONSISTENT on pooled v1+v2 data with p_luck 0.000 and appeared to
be the best wallet tracked. On uncensored v3 data it is -26.44 over 111
trades. The earlier verdict was an artifact of censored rows, and 89 of the
188 partial-position rows in the old dataset were Zuki's. Worth remembering
before re-adding anything on the strength of pre-v3 numbers.

## Note on execution cost (2026-08-23)

The same-block replay measured what a round trip actually costs above the
curve price: 243 basis points per leg, tightly distributed (p25 238, p75 253)
across 57 trades. That is the wallet's whole SOL outlay against the trade
amount the chain reports, so it covers protocol fee, creator fee, priority fee
and network fee together -- everything real execution pays and a curve
simulation does not.

The collector applies none of it. simulate_buy_sol_cost and
simulate_sell_sol_proceeds price straight off the constant product, so every
our_pnl_sol figure in the dataset omits roughly 4.9% per round trip. Wallet-side
figures are unaffected -- those come from real balance deltas -- so the
scorecard and every wallet verdict here still stand. It is the simulated
copy P&L that is optimistic, and by a margin that exceeds most of the edges
being looked for.

The tight spread is itself evidence: a fixed per-trade cost would vary widely
with trade size, and this does not, so the cost is proportional rather than
dominated by one-off rent.

## Silent, and paying for it (2026-09-04)

Removed after the first scheduled status report surfaced something nobody had
been watching for: three of seven tracked wallets had stopped trading and
were still consuming their full poll cost.

| wallet | last trade | v3 trades | their P&L | p_luck |
|---|---|---|---|---|
| Dedmeow5 | 18 days | 44 | -15.72 | 1.000 |
| Loopierr | 12 days | 14 | -12.34 | 0.866 |
| Boomer | 5 days | 30 | -7.78 | 1.000 |

- `Dedmeow5` (9THzoX5yGNSgPBAjCF4Lgqc1wLXoFkMQit4XWbhhRnqE)
- `Loopierr` (9yYya3F5EJoLnBNKW6z4bZvyQytMXzDcpU5D6yYr4jqL)
- `Boomer` (4JyenL2p8eQZAQuRS8QAASy7TzEcqAeKGha6bhiJXudh)

Dedmeow5 and Boomer are conclusive losers on their own record. Loopierr is
not conclusive -- 14 trades is short -- but it is silent, negative, and its
slot is not free.

Between them they were spending roughly 129,600 RPC calls a day to record
nothing, against a poll budget that is the binding constraint on detection
lag for the wallets that ARE trading. Collection had fallen to 3.7 round trips
a day across seven wallets; four of them were producing all of it.

## Note on screening (2026-09-04)

Screening was supposed to be the way out of waiting: read a candidate's
existing on-chain history instead of collecting it live. It cannot do that on
this endpoint. A 30-day screen of 8 wallets returned 14 round trips spanning
2 days, from 2 wallets; theo and Sheep produced nothing at all.

The cause is the same retention wall measured on 2026-08-23: getTransaction
returns null past roughly 3.5 days, and the screener must fetch every
historical transaction to reconstruct a round trip. It cannot see further back
than the endpoint remembers, so it cannot build a track record faster than
the collector does.

This makes the RPC the single constraint on the whole project. It caps live
collection through the poll budget, caps screening at about three days of
reach, and caps replay at the same. An endpoint with real historical retention
would remove all three at once, and is a different and much cheaper purchase
than the gRPC one the same-block replay ruled out.
