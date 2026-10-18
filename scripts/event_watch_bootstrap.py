"""Explicit one-time events namespace import. Must not run on branch PRs."""
import argparse
import json
import os
from pathlib import Path

from scripts.event_watch_archive import initialize_events
from scripts.state_store import GitStateStore


def bootstrap(out):
    if os.getenv("GITHUB_REF") != "refs/heads/main" or os.getenv("GITHUB_EVENT_NAME") != "workflow_dispatch":
        raise ValueError("Production migration requires explicit dispatch on main")
    store = GitStateStore()
    if store.main_head() != os.getenv("GITHUB_SHA"):
        raise ValueError("Main moved; verify code revision before migration")
    result = initialize_events(store)
    return {"status": "initialized", **result}


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
