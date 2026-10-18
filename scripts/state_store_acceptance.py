"""Real GitHub persistence acceptance using explicitly synthetic metadata only."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

from scripts import monitor
from scripts.state_store import GitStateStore


def accept(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    receipt = {"schema_version": 1, "acceptance": "failed",
               "scope": "real Git persistence with synthetic metadata; no market-data acceptance"}
    try:
        store = GitStateStore(branch="research-state-validation")
        # Explicit test initialization, never an implicit production fallback.
        monitor.initialize_history(store)
        code_before = subprocess.run(["git", "rev-parse", "HEAD"], check=True,
                                     text=True, capture_output=True).stdout.strip()
        run_id = os.environ["GITHUB_RUN_ID"]
        run_url = "https://github.com/" + os.environ["GITHUB_REPOSITORY"] + "/actions/runs/" + run_id
        record = {"schema_version": 1, "kind": "state_store_acceptance", "run_id": run_id,
                  "run_url": run_url, "observed_at_utc": datetime.now(timezone.utc).isoformat(),
                  "market": "validation-" + run_id, "event": "ops_validation",
                  "health": "critical", "reasons": ["synthetic_validation_only"],
                  "requested": None, "scanned": None, "errors": None, "signals": None,
                  "mismatches": None, "expected_warnings": 0, "unexpected_warnings": 0,
                  "session_dates": {}, "input_hashes": [], "strategies": []}
        first = monitor.archive_history(record, store)
        reread = monitor.history(GitStateStore(branch="research-state-validation"))
        repeat = monitor.archive_history(record, GitStateStore(branch="research-state-validation"))
        code_after = subprocess.run(["git", "rev-parse", "HEAD"], check=True,
                                    text=True, capture_output=True).stdout.strip()
        receipt.update(code_sha=code_before, run_url=run_url, write=first, repeat=repeat,
                       reread_commit=reread["head"], checkout_unchanged=code_before == code_after,
                       main_unchanged=first["main_before"] == repeat["main_after"])
        if (reread["records"].get(first["path"]) != record or
                reread["head"] != first["state_commit"] or
                repeat["state_commit"] != first["state_commit"] or
                repeat["status"] != "already_current" or
                not receipt["checkout_unchanged"] or not receipt["main_unchanged"]):
            raise ValueError("State write/read/rerun or revision contract failed")
        (out / "state_snapshot.json").write_text(json.dumps(reread, indent=2) + "\n", encoding="utf-8")
        receipt["acceptance"] = "passed"
    except Exception as error:
        receipt["error"] = str(error)
        raise
    finally:
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        (out / "summary.md").write_text(
            "## State-store acceptance: " + receipt["acceptance"] + "\n\n" +
            receipt["scope"] + "\n\n" +
            "Target: research-state-validation; production namespace is untouched.\n" +
            "No source-data, notification or natural-schedule acceptance is claimed.\n",
            encoding="utf-8")
        print(json.dumps(receipt, indent=2))
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("state_acceptance"))
    parser.add_argument("--bootstrap-operations", action="store_true")
    args = parser.parse_args()
    if args.bootstrap_operations:
        bootstrap_operations(args.out)
    else:
        accept(args.out)


def bootstrap_operations(out):
    """One-time production migration, after verifying all legacy writers paused."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    receipt = {"schema_version": 1, "acceptance": "failed", "scope": "explicit operations cutover",
               "code_sha": os.getenv("GITHUB_SHA"), "writer_checks": []}
    try:
        if (os.getenv("GITHUB_REF") != "refs/heads/main" or
                os.getenv("GITHUB_EVENT_NAME") != "workflow_dispatch"):
            raise ValueError("Production bootstrap requires explicit dispatch on main")
        repo = os.environ["GITHUB_REPOSITORY"]
        for workflow in ("scan.yml", "ops-validation.yml"):
            path = "repos/" + repo + "/actions/workflows/" + workflow
            result = subprocess.run(["gh", "api", path], check=True, text=True,
                                    capture_output=True, timeout=30)
            state = json.loads(result.stdout)["state"]
            if state != "disabled_manually":
                raise ValueError("Pause legacy workflow before cutover: " + workflow)
            runs = subprocess.run(["gh", "api", "--paginate", path + "/runs?per_page=100",
                                   "--jq", '.workflow_runs[] | select(.status != "completed") | .id'],
                                  check=True, text=True, capture_output=True, timeout=30)
            if runs.stdout.strip():
                raise ValueError("Legacy workflow still has unfinished jobs: " + workflow)
            receipt["writer_checks"].append({"workflow": workflow, "state": state, "active_runs": 0})
        store = GitStateStore()
        receipt["main_before"] = store.main_head()
        if receipt["main_before"] != receipt["code_sha"]:
            raise ValueError("Deploy and bootstrap the latest main revision")
        receipt["migration"] = monitor.initialize_history(store)
        snapshot = monitor.history(GitStateStore())
        receipt["main_after"] = store.main_head()
        if receipt["main_after"] != receipt["main_before"]:
            raise ValueError("Main moved during cutover; inspect before resuming writers")
        (out / "state_snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        receipt["acceptance"] = "passed"
    except Exception as error:
        receipt["error"] = str(error)
        raise
    finally:
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
