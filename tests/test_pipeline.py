"""
Tests that exercise the code the way production runs it.

Every defect that reached production in this repo shared one property: the
code path was never executed before it mattered. A --limit default that only
existed on manual runs failed 13 scheduled runs in a row. int() on a pandas
Series crashed on first real use. A 90% gate written for 250-row samples
refused to price 13 good trades out of 15. None needed a clever test -- only a
test that ran the thing.

So these run the real scripts on the real committed data, and pin the specific
failures above so they cannot come back quietly. They also guard the external
facts the analysis silently depends on: if pump.fun ever changes its curve
parameters, the constant-product test fails before any number is mispriced.
"""

import glob
import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
DATASET = REPORTS / "paper_trades_final.csv"
K = 30_000_000_000 * 1_073_000_000_000_000


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, REPORTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(script, *args, cwd=ROOT):
    return subprocess.run([sys.executable, str(script), *map(str, args)],
                          cwd=cwd, capture_output=True, text=True, timeout=300)


# --- regressions: each of these shipped broken once --------------------------

@pytest.mark.parametrize("priced,attempted,confirmed,expected", [
    (13, 15, 13, "price-small-sample"),      # 2026-09-23: refused 13 good rows of 15
    (95, 100, 95, "price"),
    (80, 100, 80, "price-offsets-confirmed"),  # every success reproduced both constants
    (80, 100, 60, "abort"),                  # the case the gate exists for
])
def test_layout_gate(priced, attempted, confirmed, expected):
    replay = load_module("replay_same_block")
    assert replay.layout_verdict(priced, attempted, confirmed) == expected


def test_scheduled_workflows_never_pass_raw_inputs_to_a_flag():
    """inputs.* are EMPTY on a schedule; declared defaults apply only to manual
    runs. Passing one straight to a CLI flag failed every scheduled replay from
    2026-09-11 to 09-23. Default it in the shell instead."""
    offenders = []
    for wf in sorted((ROOT / ".github/workflows").glob("*.yml")):
        text = wf.read_text()
        if not re.search(r"^\s*schedule:", text, re.M):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if re.search(r'--[\w-]+\s+"?\$\{\{\s*inputs\.', line):
                offenders.append(f"{wf.name}:{n}: {line.strip()}")
    assert not offenders, "scheduled workflow passes inputs.* directly:\n" + "\n".join(offenders)


# --- the external facts every price depends on --------------------------------

def test_pumpfun_constant_product_holds():
    df = pd.read_csv(DATASET)
    s = df[(df.entry_virtual_sol_reserves > 0) & (df.entry_virtual_token_reserves > 0)]
    k = s.entry_virtual_sol_reserves.astype(float) * s.entry_virtual_token_reserves.astype(float)
    share = ((k - K).abs() / K < 1e-6).mean()
    assert share > 0.95, f"only {share:.1%} of snapshots match k0 -- pump.fun curve changed?"


def test_size_sweep_reproduces_the_replay_exactly():
    """The fixed-size model must agree with the replay's own P&L when run at the
    replay's own settings, or every size it reports is suspect."""
    sweep = load_module("size_sweep")
    if not glob.glob(str(REPORTS / "same_block" / "*.csv")):
        pytest.skip("no same-block data committed yet")
    d, _ = sweep.load(str(REPORTS / "same_block" / "*.csv"), str(DATASET))
    T = d.wallet_token_amount.astype(float)
    f = d.our_cost_lamports / d.raw_cost_lamports - 1
    gross = d.sell_vs - K / (K / d.sell_vs + T)
    model = (gross * (1 - f) - d.raw_cost_lamports * (1 + f)) / 1e9
    assert np.allclose(model, d.same_block_pnl_sol, atol=1e-9)


# --- dataset invariants that were each silently violated once ------------------

def test_dataset_is_uncensored_collector_only():
    df = pd.read_csv(DATASET)
    assert (df.collector_version >= 3).all(), "pre-v3 (censored) rows leaked past the quarantine"


def test_dataset_has_no_duplicate_round_trips():
    df = pd.read_csv(DATASET)
    sigs = df.sell_signature.dropna()
    sigs = sigs[sigs != ""]
    assert not sigs.duplicated().any()


# --- every scheduled script actually runs on real data -------------------------

def test_scorecard_runs(tmp_path):
    r = run(REPORTS / "wallet_scorecard.py", DATASET, tmp_path / "sc.csv")
    assert r.returncode == 0, r.stderr
    assert "verdict" in pd.read_csv(tmp_path / "sc.csv").columns


def test_size_sweep_runs(tmp_path):
    if not glob.glob(str(REPORTS / "same_block" / "*.csv")):
        pytest.skip("no same-block data committed yet")
    r = run(REPORTS / "size_sweep.py", "--out", tmp_path / "sweep.csv")
    assert r.returncode == 0, r.stderr
    assert len(pd.read_csv(tmp_path / "sweep.csv")) > 0


def test_status_report_runs(tmp_path):
    """status.py writes into the repo, so run it against a copy."""
    for rel in ("reports/paper_trades_final.csv", "reports/wallet_scorecard.py",
                "reports/status.py", "config/config.paper_trade.ci.json"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp_path / rel)
    for f in (ROOT / "reports" / "same_block").glob("*.csv"):
        (tmp_path / "reports" / "same_block").mkdir(parents=True, exist_ok=True)
        shutil.copy(f, tmp_path / "reports" / "same_block" / f.name)
    shutil.copy(ROOT / "reports" / "size_sweep.py", tmp_path / "reports" / "size_sweep.py")
    r = run(tmp_path / "reports" / "status.py", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "STATUS.md").read_text().startswith("# Status")


def test_live_signature_polling_reads_at_confirmed_commitment():
    """The RPC default is 'finalized' (~12.8s after landing). That hidden floor
    set every detection lag in the dataset for over a month and was mistaken for
    a property of the free tier. Pin it: live polling must ask for 'confirmed'."""
    src = (ROOT / "src/rpc/rpc_client.cpp").read_text()
    body = src[src.index("RpcClient::get_signatures_for_address"):]
    body = body[:body.index("\n}\n")]
    assert '"commitment", "confirmed"' in body, "live signature polling fell back to finalized"


def test_every_transaction_fetch_accepts_version_1():
    """Solana began producing version-1 transactions on 2026-09-23. Asking for
    at most version 0 made every getTransaction fail, and the collector
    recorded nothing for over a day while reporting success. Every fetch, C++
    and Python, must accept them."""
    offenders = []
    for path in [ROOT / "src/rpc/rpc_client.cpp", *sorted(REPORTS.glob("*.py"))]:
        for n, line in enumerate(path.read_text().splitlines(), 1):
            m = re.search(r'"maxSupportedTransactionVersion"\s*[,:]\s*(\d+)', line)
            if m and int(m.group(1)) < 1:
                offenders.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()}")
    assert not offenders, "transaction fetch rejects v1:\n" + "\n".join(offenders)


V1_REJECTION = ('RPC error: {"code":-32015,"message":"Transaction version (1) is not supported '
                'by the requesting client."}')


@pytest.mark.parametrize("failures,rows,ok", [
    (131, 0, False),   # the 2026-09-23 outage: blind, and green
    (131, 4, True),    # failures, but it is still seeing trades
    (3, 0, True),      # a quiet day: few trades means few fetches to fail
    (0, 0, True),
])
def test_collector_health_tells_blind_from_quiet(failures, rows, ok):
    health = load_module("collector_health")
    log = "".join(f"[WARN] getTransaction failed for sig{i}: {V1_REJECTION}\n" for i in range(failures))
    got, msg = health.verdict(log, rows)
    assert got == ok, msg
    if not ok:
        assert "Transaction version (1)" in msg, "failure must name its cause"


def test_paper_trade_workflow_runs_the_health_check():
    wf = (ROOT / ".github/workflows/paper-trade.yml").read_text()
    assert "tee collector.log" in wf and "collector_health.py collector.log" in wf
