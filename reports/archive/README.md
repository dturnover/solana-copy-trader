# Quarantined data

`paper_trades_pre_quarantine_2026-08-09.csv` — 3,364 rows, 2026-07-20 to
2026-08-09, collector versions 1, 2 and 3.

**Do not use it for P&L or wallet ranking.** It is kept because it is the only
record of those wallets' activity in that window: RPC signature retention does
not reach back far enough to recreate it, and the run artifacts it came from
expire 90 days after collection.

## Why it is quarantined

Four defects, found in sequence, all bending results in the same direction —
optimistic:

| defect | effect |
|---|---|
| Reverting **buys** dropped (v1) | ~50% of attempted buys deleted; only favourable fills recorded. 86% of fills came in cheaper than the wallet's, which is impossible for a lagged copy. |
| Reverting **sells** dropped (v1, v2) | Whole round trips never written when the exit breached the wallet's bound — i.e. the losing exits. |
| Partial positions recorded as whole | Missed buys meant full sale proceeds divided by a fraction of the position. 188 rows carried +394 SOL against a dataset total of −92. Every positive headline was this. |
| Hold time capped at CI run length | Positions died with the process every ~5h, so nothing longer than a run could ever be observed. Longest hold in 3,364 trades: 2.67h. |

The drop rates vary by wallet — they track how fast price moves after a buy,
which differs by the tokens each wallet trades. So these rows do not merely add
noise, **they reorder any ranking built on them.** Zuki scored CONSISTENT at
`p_luck` 0.000 on this data and is −26.44 over 111 uncensored trades; 89 of the
188 partial-position rows were Zuki's.

The `our_*` columns carry a further problem independent of the above: fills were
priced against the live bonding curve at whatever moment the poller reached it,
so they describe copying at ~18.5s latency rather than at any configured value.

## What replaced it

`reports/paper_trades_final.csv` now accepts only `collector_version >= 3`, and
the collector that writes v3+ has all four defects fixed. The filter lives in
`reports/merge_artifacts.py` — archiving this file alone would not have
quarantined anything, because the merge re-reads every unexpired artifact each
run and would have rebuilt these rows.
