"""
Writes STATUS.md: what the experiment has found, not whether CI is green.

There is already a health check running every six hours, 158 times so far,
and it has never once said anything about the experiment. It watches for
failed jobs. That is worth having and it is not a status report -- the
question "is the machine on" has been answered continuously while "has any
of this found anything" required someone to go and ask.

So this reports findings, on a schedule, into a file readable on a phone:
what came in, which wallets have a verdict, which are close to earning one,
and which have gone quiet. It compares against the previous run so a report
that says nothing changed is saying that deliberately.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import pandas as pd

CSV = "reports/paper_trades_final.csv"
OUT = "STATUS.md"
STATE = "reports/.status_prev.json"

# A tracked wallet silent this long is either inactive, trading somewhere we
# do not parse, or no longer being detected. All three change what its numbers
# mean, and none announce themselves.
QUIET_DAYS = 5

# Matches wallet_scorecard.py. Repeated here only to say how far a wallet has
# left to go, which the scorecard itself does not report.
MIN_TRADES = 30


def humanise_age(hours):
    if hours < 1:
        return f"{hours * 60:.0f} min"
    if hours < 48:
        return f"{hours:.1f} h"
    return f"{hours / 24:.1f} d"


def main():
    now = datetime.now(timezone.utc)
    df = pd.read_csv(CSV)
    df["dt"] = pd.to_datetime(df["epoch_ms"], unit="ms", utc=True)

    newest = df["dt"].max()
    stale_h = (now - newest).total_seconds() / 3600
    d1 = int((df["dt"] > now - pd.Timedelta(days=1)).sum())
    d7 = int((df["dt"] > now - pd.Timedelta(days=7)).sum())

    prev = {}
    if os.path.exists(STATE):
        try:
            prev = json.load(open(STATE))
        except Exception:
            prev = {}
    added = len(df) - prev.get("rows", len(df))

    # Reuse the scorecard rather than reimplementing its statistics; a second
    # implementation of the skill-vs-luck test would drift from the first.
    sc_path = "/tmp/status_scorecard.csv"
    subprocess.run([sys.executable, "reports/wallet_scorecard.py", CSV, sc_path],
                   check=True, capture_output=True)
    sc = pd.read_csv(sc_path)

    last_seen = df.groupby("wallet_label")["dt"].max()
    tracked = [w["label"] for w in
               json.load(open("config/config.paper_trade.ci.json"))["tracked_wallets"]]

    L = []
    L.append("# Status")
    L.append("")
    L.append(f"Generated {now:%Y-%m-%d %H:%M} UTC. "
             f"This file is written by a scheduled job -- nobody has to ask for it.")
    L.append("")

    L.append("## Collection")
    L.append("")
    L.append(f"- **{len(df):,} closed round trips**, all collector v3, "
             f"{df['dt'].min():%b %d} to {newest:%b %d}")
    L.append(f"- Newest trade **{humanise_age(stale_h)} old**"
             + ("  ⚠️ collector may be stuck" if stale_h > 12 else ""))
    L.append(f"- **{d1} in the last 24h**, {d7} in the last 7 days "
             f"({d7 / 7:.1f}/day across {len(tracked)} tracked wallets)")
    if prev:
        L.append(f"- **{added:+d} since the last report** ({prev.get('generated', 'unknown')})")
    L.append("")

    # The headline the whole project is trying to answer.
    proven = sc[sc["verdict"].isin(["CONSISTENT"])]
    L.append("## Has anything been proven yet?")
    L.append("")
    if proven.empty:
        L.append("**No.** No wallet has cleared the bar: enough trades, profitable, "
                 "survives removing its best three trades, and holds up across both "
                 "halves of its own history.")
    else:
        L.append(f"**Yes — {len(proven)}:** " + ", ".join(proven["wallet"]))
    L.append("")

    close = sc[(sc["verdict"] == "INSUFFICIENT") & (sc["total_sol"] > 0)
               ].sort_values("total_sol", ascending=False)
    if not close.empty:
        L.append("### Closest to a verdict")
        L.append("")
        L.append("| wallet | trades | needs | P&L | win rate | days up | p_luck | last trade |")
        L.append("|---|---|---|---|---|---|---|---|")
        for _, r in close.iterrows():
            need = max(0, MIN_TRADES - int(r["trades"]))
            seen = last_seen.get(r["wallet"])
            age = humanise_age((now - seen).total_seconds() / 3600) if pd.notna(seen) else "—"
            L.append(f"| {r['wallet']} | {int(r['trades'])} | {need} more | "
                     f"{r['total_sol']:+.2f} | {r['win_rate']:.0%} | "
                     f"{r['days_positive']:.0%} | {r['p_luck']:.3f} | {age} ago |")
        L.append("")
        rate = d7 / 7 / max(len(tracked), 1)
        for _, r in close.iterrows():
            need = max(0, MIN_TRADES - int(r["trades"]))
            if need and rate > 0:
                L.append(f"- {r['wallet']} needs {need} more trades; at its recent rate "
                         f"that is roughly {need / max(rate, 0.01):.0f} days away.")
        L.append("")

    quiet = [w for w in tracked
             if w not in last_seen.index
             or (now - last_seen[w]).days >= QUIET_DAYS]
    L.append("## Tracked wallets that have gone quiet")
    L.append("")
    if quiet:
        for w in quiet:
            seen = last_seen.get(w)
            when = f"{humanise_age((now - seen).total_seconds() / 3600)} ago" if pd.notna(seen) else "never seen"
            L.append(f"- **{w}** — last trade {when}. Costs ~43,200 RPC calls/day regardless.")
        L.append("")
        L.append("A silent wallet is not necessarily a dead one: it may be trading "
                 "somewhere the collector does not parse. Either way it is spending "
                 "poll budget for nothing.")
    else:
        L.append("None — every tracked wallet has traded recently.")
    L.append("")

    L.append("## Every wallet")
    L.append("")
    L.append("| wallet | verdict | trades | P&L | win rate | days up | ex-top-3 | p_luck |")
    L.append("|---|---|---|---|---|---|---|---|")
    order = {v: i for i, v in enumerate(
        ["CONSISTENT", "TAIL-DEPENDENT", "UNSTABLE", "UNPROVEN", "INSUFFICIENT", "LOSING"])}
    sc = sc.assign(_o=sc["verdict"].map(order)).sort_values(["_o", "total_sol"],
                                                           ascending=[True, False])
    for _, r in sc.iterrows():
        ex3 = "—" if pd.isna(r["total_ex_top3"]) else f"{r['total_ex_top3']:+.2f}"
        pl = "—" if pd.isna(r["p_luck"]) else f"{r['p_luck']:.3f}"
        L.append(f"| {r['wallet']} | {r['verdict']} | {int(r['trades'])} | "
                 f"{r['total_sol']:+.2f} | {r['win_rate']:.0%} | "
                 f"{r['days_positive']:.0%} | {ex3} | {pl} |")
    L.append("")
    L.append("`ex-top-3` is P&L with the three best trades removed. A wallet whose "
             "edge vanishes there has shown you three good trades, not an edge -- "
             "which is how Zuki looked best-in-class on censored data while actually "
             "losing 26 SOL.")
    L.append("")

    L.append("## Settled")
    L.append("")
    L.append("- **gRPC: no.** Filling in the same block as the wallet -- the floor no "
             "speed purchase can beat -- still loses money (-39.14 SOL over 57 round "
             "trips). Latency is worth ~32 SOL of that; the rest is the wallets.")
    L.append("- **Execution costs 243 bps per leg** (~4.9% round trip), measured. The "
             "collector applies none of it, so simulated copy P&L is optimistic by "
             "that much. Wallet-side figures are unaffected.")
    L.append("- **The RPC forgets transactions after ~3.5 days.** Anything not "
             "replayed or screened within that window can never be re-priced.")
    L.append("")

    open(OUT, "w").write("\n".join(L) + "\n")
    json.dump({"rows": len(df), "generated": f"{now:%Y-%m-%d %H:%M} UTC"},
              open(STATE, "w"), indent=2)
    print(f"Wrote {OUT}: {len(df)} rows, {d1} in 24h, {len(quiet)} quiet wallet(s)")
    print("\n".join(L))


if __name__ == "__main__":
    main()
