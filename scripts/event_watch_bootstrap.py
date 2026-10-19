"""Explicit one-time events namespace import. Must not run on branch PRs."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from scripts.event_watch_archive import initialize_events
from scripts.state_store import GitStateStore


def bootstrap(out):
    if os.getenv("GITHUB_REF") != "refs/heads/main" or os.getenv("GITHUB_EVENT_NAME") != "workflow_dispatch":
        raise ValueError("Production migration requires explicit dispatch on main")
    repo = os.getenv("GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("GitHub repository identity missing")
    def gh_api(endpoint, *args):
        result = subprocess.run(["gh", "api", *args, endpoint], check=True,
                                text=True, capture_output=True, timeout=30)
        return result.stdout.strip()

    state = json.loads(gh_api(f"repos/{repo}/actions/workflows/event-watch.yml"))
    if state.get("state") != "disabled_manually":
        raise ValueError("Disable Official disclosure watch before migrating its baseline")
    pending = gh_api(f"repos/{repo}/actions/workflows/event-watch.yml/runs?per_page=100",
                     "--paginate", "--jq",
                     '.workflow_runs[] | select(.status != "completed") | .id')
    if pending:
        raise ValueError("Old event-watch jobs are still pending/in progress; do not migrate")

    store = GitStateStore()
    if store.main_head() != os.getenv("GITHUB_SHA"):
        raise ValueError("Main moved; verify code revision before migration")
    result = initialize_events(store)
    imported = result["authority"]["legacy_import"]["source_sha"]
    if imported != os.environ["GITHUB_SHA"]:
        raise ValueError("Migration source moved during bootstrap; inspect state authority")
    current_main = store.main_head()
    if current_main != os.environ["GITHUB_SHA"]:
        raise ValueError("Main advanced during migration; manually verify authority")
    run = os.getenv("GITHUB_RUN_ID")
    return {"status": "initialized", "main_after": current_main,
            "run_url": "https://github.com/" + repo + "/actions/runs/" + run if repo and run else None,
            **result}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    receipt = {"status": "failed"}
    try:
        receipt = bootstrap(args.out)
    except Exception as error:
        receipt["error"] = str(error)
        raise
    finally:
        (args.out / "bootstrap_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
