"""
Why do some recent trades price against a curve that breaks pump.fun's
constant product?

Since the sell_v2 fix, 4 of the first 10 recorded trades carry entry reserves
whose product is 0.016x-56x the pump.fun constant (virtual SOL of 0.9, 21,
2757 and 1.06 SOL against normal virtual token reserves). For every such row
this prints what the chain itself says: the wallet's TradeEvent (the reserves
pump.fun reported at the trade), the wallet's SOL change, which token mints
moved, the program's own instruction log lines, and the curve account the
collector read (size, owner, discriminator, decoded reserves).
"""

import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
import pandas as pd  # noqa: E402
from replay_same_block import TX_OPTS, decode_trade_events, rpc  # noqa: E402

K = 30_000_000_000 * 1_073_000_000_000_000
DATASET = "reports/paper_trades_final.csv"


def main():
    endpoint = os.environ["RPC_ENDPOINT"]
    d = pd.read_csv(DATASET)
    d = d[d["entry_block_time_ms"] >= pd.Timestamp("2026-09-24 14:51", tz="UTC").value // 10**6]
    k = d["entry_virtual_sol_reserves"].astype(float) * d["entry_virtual_token_reserves"].astype(float) / K
    d = d.assign(k_ratio=k)
    print(d[["wallet_label", "mint", "k_ratio"]].to_string(), "\n")
    wallets = {w["label"]: w["pubkey"] for w in json.load(open("config/config.paper_trade.ci.json"))["tracked_wallets"]}

    for _, r in d.iterrows():
        tag = "ANOMALY" if abs(r["k_ratio"] - 1) > 1e-3 else "normal"
        print(f"=== {tag} {r['wallet_label']} mint={r['mint']} k_ratio={r['k_ratio']:.4f}")
        tx = rpc(endpoint, "getTransaction", [r["entry_signature"], TX_OPTS])
        if not tx:
            print("  entry tx not retained")
            continue
        w = wallets.get(r["wallet_label"])
        for e in decode_trade_events(tx):
            if e["user"] == w:
                print(f"  event: buy={e['is_buy']} sol={e['sol_amount']} tok={e['token_amount']} "
                      f"vsol={e['virtual_sol']} vtok={e['virtual_token']} real_sol={e['real_sol']} "
                      f"k_ratio={e['virtual_sol'] * e['virtual_token'] / K:.4f} mint_match={e['mint'] == r['mint']}")
        keys = [k["pubkey"] for k in tx["transaction"]["message"]["accountKeys"]]
        m = tx["meta"]
        if w in keys:
            i = keys.index(w)
            print(f"  wallet lamport delta: {m['postBalances'][i] - m['preBalances'][i]}")
        mints = {b["mint"] for b in (m.get("postTokenBalances") or [])}
        print(f"  token mints moved: {sorted(mints)}")
        print("  ix logs:", [l for l in m.get("logMessages") or [] if "Instruction:" in l][:8])
        acc = rpc(endpoint, "getAccountInfo", [r["bonding_curve"], {"encoding": "base64"}])
        v = (acc or {}).get("value")
        if not v:
            print(f"  curve {r['bonding_curve']}: gone")
            continue
        import base64
        raw = base64.b64decode(v["data"][0])
        vt, vs, rt, rs, sup = struct.unpack_from("<QQQQQ", raw, 8)
        print(f"  curve {r['bonding_curve']}: owner={v['owner']} len={len(raw)} disc={raw[:8].hex()} "
              f"now vtok={vt} vsol={vs} rtok={rt} rsol={rs} supply={sup} complete={raw[48]}")
        print(f"  curve tail bytes 49..: {raw[49:120].hex()}")


if __name__ == "__main__":
    main()
