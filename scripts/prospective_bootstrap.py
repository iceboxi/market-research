"""Explicit prospective state migration while EOD legacy writer is disabled.

This is not invoked by ordinary scans. No source labels or realized outcomes
are manufactured. It preserves any unrelated research-state namespaces.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from scripts.prospective_state import initialize, read
from scripts.state_store import GitStateStore, StateError


def _gh_api(path, jq=None):
    args = ["gh", "api"]
    if jq:
        args += ["--paginate", "--jq", jq]
    args.append(path)
    result = subprocess.run(args, check=True, capture_output=True,
                            text=True, timeout=45)
    return result.stdout.strip()


def bootstrap(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 1, "status": "failed",
        "scope": "explicit prospective state bootstrap; no market or schedule acceptance",
        "code_sha": os.getenv("GITHUB_SHA"), "stage": "start",
        "writer_checks": [], "migration": None,
        "main_before": None, "main_after": None, "state_head": None,
    }
    try:
        if (os.getenv("GITHUB_REF") != "refs/heads/main"
                or os.getenv("GITHUB_EVENT_NAME") != "workflow_dispatch"):
            raise StateError("Explicit main workflow_dispatch required")
        name = os.environ["GITHUB_REPOSITORY"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name):
            raise StateError("Invalid GitHub repository identity")
        report["stage"] = "writer_quiescence"
        endpoint = f"repos/{name}/actions/workflows/scan.yml"
        metadata = json.loads(_gh_api(endpoint))
        if metadata.get("state") != "disabled_manually":
            raise StateError("EOD market scan must be manually disabled for prospective migration")
        outstanding = _gh_api(
            endpoint + "/runs?per_page=100",
            '.workflow_runs[] | select(.status != "completed") | .id',
        )
        if outstanding:
            raise StateError("EOD legacy prospective writer has unfinished runs")
        report["writer_checks"].append({
            "workflow": "scan.yml", "state": "disabled_manually",
            "active_runs": 0,
        })
        store = GitStateStore()
        report["stage"] = "verify_main"
        report["main_before"] = store.main_head()
        if report["main_before"] != report["code_sha"]:
            raise StateError("The migration runner does not match latest main")
        report["stage"] = "initialize_namespace"
        report["migration"] = initialize(store)
        report["stage"] = "fresh_read"
        restored = read(GitStateStore())
        report["state_head"] = restored["head"]
        report["state_record_count"] = len(restored["records"])
        report["authority"] = restored["authority"]
        if report["migration"]["state_commit"] != restored["head"]:
            raise StateError("Prospective migration state commit mismatch")
        report["main_after"] = store.main_head()
        if report["main_before"] != report["main_after"]:
            raise StateError("Main advanced during prospective migration")
        report["status"] = "passed"
        report["stage"] = "complete"
    except Exception as exc:
        report["error"] = str(exc)
        raise
    finally:
        (out / "receipt.json").write_text(json.dumps(report, ensure_ascii=False,
            indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("prospective_bootstrap_output"))
    args = parser.parse_args()
    bootstrap(args.out)


if __name__ == "__main__":
    main()
