"""
Fails a collector run that was blind, so it cannot report success again.

From 2026-09-23 ~14:00 UTC every getTransaction the collector made was
rejected (Solana began producing version-1 transactions; we asked for at most
version 0). It recorded nothing, and because the workflow ends the process
with `|| true`, every run went green for over a day. Nobody could tell a
broken collector from quiet wallets.

The difference is visible in the log. A quiet wallet produces few
getTransaction calls and so few failures. A blind collector produces a steady
stream of them. So: many fetch failures and nothing recorded is a failure,
whatever the exit code said.

Usage: collector_health.py <collector log> <paper_trades.csv>
"""

import os
import re
import sys
from collections import Counter

# A handful of fetch failures in a 5h run is normal rate-limiting noise; a
# systematic fault produces hundreds (the version-1 outage: 131 in the last
# three minutes of one run alone).
MAX_FAILURES_WITH_NO_TRADES = 30


def rows_recorded(csv_path):
    if not os.path.exists(csv_path):
        return 0
    with open(csv_path) as f:
        return max(sum(1 for line in f if line.strip()) - 1, 0)


def verdict(log_text, rows):
    """(ok, message). Pure, so the rule itself is tested."""
    failures = re.findall(r"getTransaction failed for \S+: (.*)", log_text)
    if len(failures) >= MAX_FAILURES_WITH_NO_TRADES and rows == 0:
        # The error text carries the signature-free cause; group by it so the
        # failure message names the fault instead of listing 500 lines.
        causes = Counter(re.sub(r"\d{3,}", "N", f)[:160] for f in failures)
        top = "\n".join(f"  {n:>5}x  {c}" for c, n in causes.most_common(3))
        return False, (f"BLIND: {len(failures)} getTransaction failures and 0 trades recorded.\n"
                       f"This is a broken collector, not quiet wallets. Most common causes:\n{top}")
    return True, f"ok: {rows} trade(s) recorded, {len(failures)} getTransaction failure(s)"


def main():
    log_path, csv_path = sys.argv[1], sys.argv[2]
    log_text = open(log_path, errors="replace").read() if os.path.exists(log_path) else ""
    ok, msg = verdict(log_text, rows_recorded(csv_path))
    print(msg)
    if not ok:
        print(f"::error title=Collector was blind::{msg.splitlines()[0]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
