"""
Watches paper-trade.yml and lag-experiment.yml from the outside and files
(or updates) a GitHub issue if either looks broken.

Why a separate watcher instead of a step inside those workflows: they are
long, unattended jobs (350min job-timeout budget) that can be hard-killed
by their own job-level timeout before a cleanup/"if: always()" step is
guaranteed to run. A watcher that only reads run history via `gh run list`
doesn't share that failure mode -- it can't be silently taken down by the
same problem it's supposed to detect. This exists because of a real
incident: a stale vcpkg binary cache caused 8 consecutive runs (~2 days) of
both workflows to fail or get job-timeout-cancelled with nobody aware,
until someone happened to run `gh run list` by hand.

Requires the `gh` CLI authenticated via GH_TOKEN (GitHub Actions provides
this automatically as secrets.GITHUB_TOKEN -- no extra secret needed) and
the `issues: write` permission granted to the workflow.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone

# merge-paper-trades.yml belongs here as much as the collectors do: it failed
# on every run for three days in 2026-08 while both collectors stayed green,
# so the data was being gathered and then silently never committed. A watcher
# that only looks at producers misses a broken consumer entirely.
WORKFLOWS = ["paper-trade.yml", "lag-experiment.yml", "merge-paper-trades.yml"]
LOOKBACK_RUNS = 5
MIN_SUCCESS_IN_LOOKBACK = 1
STALE_HOURS = 18  # 3x the 6h schedule cadence -- one missed run is normal jitter, three isn't
ISSUE_LABEL = "ci-broken"


def gh_json(args, repo):
    out = subprocess.run(["gh"] + args + ["--repo", repo], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def gh_run(args, repo):
    subprocess.run(["gh"] + args + ["--repo", repo], check=True)


def check_workflow(workflow, repo):
    runs = gh_json(
        ["run", "list", "--workflow", workflow, "--limit", str(LOOKBACK_RUNS),
         "--json", "status,conclusion,createdAt,url"],
        repo,
    )
    if not runs:
        return {"healthy": False, "reason": "no runs found at all", "runs": []}

    successes = [r for r in runs if r["conclusion"] == "success"]
    if len(successes) < MIN_SUCCESS_IN_LOOKBACK:
        return {"healthy": False, "reason": f"0 successes in the last {len(runs)} runs", "runs": runs}

    latest_success = max(successes, key=lambda r: r["createdAt"])
    ts = datetime.fromisoformat(latest_success["createdAt"].replace("Z", "+00:00"))
    age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
    if age_hours > STALE_HOURS:
        return {"healthy": False, "reason": f"last success was {age_hours:.1f}h ago (> {STALE_HOURS}h)", "runs": runs}

    return {"healthy": True, "reason": f"last success {age_hours:.1f}h ago", "runs": runs}


def find_open_issue(workflow, repo):
    issues = gh_json(
        ["issue", "list", "--label", ISSUE_LABEL, "--state", "open", "--json", "number,title"],
        repo,
    )
    for issue in issues:
        if workflow in issue["title"]:
            return issue["number"]
    return None


def format_runs(runs):
    return "\n".join(f"- {r['status']}/{r['conclusion']}: {r['url']}" for r in runs) or "(none)"


def main():
    if len(sys.argv) != 2:
        print("usage: ci_health_check.py <owner/repo>", file=sys.stderr)
        sys.exit(2)
    repo = sys.argv[1]

    any_unhealthy = False
    for workflow in WORKFLOWS:
        result = check_workflow(workflow, repo)
        existing_issue = find_open_issue(workflow, repo)

        if not result["healthy"]:
            any_unhealthy = True
            body = (
                f"Automated health check: `{workflow}` looks broken.\n\n"
                f"**Reason**: {result['reason']}\n\n"
                f"**Recent runs**:\n{format_runs(result['runs'])}\n\n"
                f"Filed/updated automatically by `.github/workflows/ci-health-check.yml`. "
                f"Closes itself once a run of `{workflow}` succeeds again."
            )
            if existing_issue:
                gh_run(["issue", "comment", str(existing_issue), "--body", body], repo)
                print(f"{workflow}: unhealthy ({result['reason']}) -- updated issue #{existing_issue}")
            else:
                gh_run(
                    ["issue", "create", "--title", f"CI data pipeline broken: {workflow}",
                     "--body", body, "--label", ISSUE_LABEL],
                    repo,
                )
                print(f"{workflow}: unhealthy ({result['reason']}) -- filed new issue")
        else:
            print(f"{workflow}: healthy ({result['reason']})")
            if existing_issue:
                gh_run(
                    ["issue", "comment", str(existing_issue), "--body",
                     f"`{workflow}` has a successful run again ({result['reason']}) -- closing."],
                    repo,
                )
                gh_run(["issue", "close", str(existing_issue)], repo)
                print(f"{workflow}: closed recovered issue #{existing_issue}")

    sys.exit(1 if any_unhealthy else 0)


if __name__ == "__main__":
    main()
