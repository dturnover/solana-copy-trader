"""
Pulls the KOL wallets listed on kolscan.io's leaderboard, so the screener
samples traders people actually follow instead of random program traffic.

Run from GitHub Actions (the dev sandbox cannot reach kolscan.io). The page
structure is not documented, so this does not assume one: it collects every
Solana address in the page and in any embedded JSON, keeps the names it can
pair with them, and reports what it found. Nothing here trusts the page beyond
"these are addresses kolscan shows" -- every wallet still goes through the
same on-chain screen as any other.
"""

import json
import os
import re
import sys
import urllib.request

URLS = [
    "https://kolscan.io/leaderboard",
    "https://kolscan.io/",
]
B58 = r"[1-9A-HJ-NP-Za-km-z]{32,44}"
# Program and system addresses that show up in any Solana page.
IGNORE = {"11111111111111111111111111111111", "So11111111111111111111111111111111111111112",
          "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P", "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research; solana-copy-trader)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode("utf-8", "replace")


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "reports/screened/kolscan_wallets.json"
    found = {}
    for url in URLS:
        try:
            status, html = fetch(url)
        except Exception as e:
            print(f"{url}: {e}")
            continue
        print(f"{url}: HTTP {status}, {len(html)} bytes, "
              f"__NEXT_DATA__={'yes' if '__NEXT_DATA__' in html else 'no'}")
        # Name/address pairs inside embedded JSON, when the page carries any.
        for m in re.finditer(r'"(?:name|username|displayName|twitter)"\s*:\s*"([^"]{1,40})"[^{}]{0,400}?"(?:wallet|address|walletAddress|pubkey)"\s*:\s*"(' + B58 + r')"', html):
            found.setdefault(m.group(2), m.group(1))
        for m in re.finditer(r'"(?:wallet|address|walletAddress|pubkey)"\s*:\s*"(' + B58 + r')"[^{}]{0,400}?"(?:name|username|displayName|twitter)"\s*:\s*"([^"]{1,40})"', html):
            found.setdefault(m.group(1), m.group(2))
        # Profile links, e.g. /account/<address>
        for m in re.finditer(r'/account/(' + B58 + r')', html):
            found.setdefault(m.group(1), None)
        print(f"  sample: {html[:300]!r}")
    found = {a: n for a, n in found.items() if a not in IGNORE}
    print(f"\n{len(found)} wallet(s) found")
    for a, n in list(found.items())[:60]:
        print(f"  {n or '?':<24} {a}")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump([{"label": n, "pubkey": a} for a, n in found.items()], open(out, "w"), indent=1)
    if not found:
        sys.exit("No wallets found -- the page may render client-side; see the sample above")


if __name__ == "__main__":
    main()
