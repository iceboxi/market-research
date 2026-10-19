"""Opt-in canonical prospective writer; never touches main history.

Activation is gated in scan.yml by an explicit repository variable after
operator-verified namespace bootstrap, never inferred from a successful PR.
"""
import argparse
import json
import os
from pathlib import Path

from scripts.prospective_state import append, verify_runtime
from scripts.state_store import GitStateStore, StateError


def archive(record, store=None, repo=Path(".")):
    result = {
        "schema_version": 1, "status": "failed", "stage": "validate",
        "namespace": "prospective", "persistence_status": "not_attempted",
        "code_sha": os.getenv("GITHUB_SHA"), "main_before": None,
        "main_after": None, "state_commit": None,
        "run_id": os.getenv("GITHUB_RUN_ID"), "mode": "canonical",
    }
    try:
        revision = verify_runtime(record, repo)
        result["cohort_revision"] = revision
        store = store or GitStateStore(repo)
        result["main_before"] = store.main_head()
        result["stage"] = "commit_state"
        result["persistence_status"] = "outcome_unknown"
        committed = append(record, store)
        result.update(committed)
        result["persistence_status"] = committed["status"]
        result["stage"] = "fresh_read"
        current = store.read("prospective")
        if (current["status"] != "available" or
                committed["path"] not in current["records"] or
                current["records"][committed["path"]] != record):
            raise StateError("Fresh read did not reproduce the prospective observation")
        result["fresh_read_head"] = current["head"]
        result["main_after"] = store.main_head()
        if result["main_after"] != result["main_before"]:
            raise StateError("Main moved during prospective state archive")
        result["status"] = "passed"
        result["stage"] = "complete"
    except (StateError, ValueError, KeyError, TypeError, OSError) as exc:
        result["status"] = "failed"
        result["error"] = str(exc)
        result.update(getattr(exc, "context", {}))
        raise ArchiveFailure(result) from exc
    return result


class ArchiveFailure(StateError):
    def __init__(self, receipt):
        self.receipt = receipt
        super().__init__(receipt["error"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = {"status": "failed", "stage": "not_started"}
    try:
        if (os.getenv("GITHUB_EVENT_NAME") != "schedule" or
                os.getenv("GITHUB_REF") != "refs/heads/main" or
                os.getenv("PROSPECTIVE_STATE_MODE") != "canonical"):
            raise StateError("Canonical writer requires scheduled main and explicit cutover mode")
        result = archive(json.loads(args.receipt.read_text(encoding="utf-8")))
    except ArchiveFailure as exc:
        result = exc.receipt
        raise
    except Exception as exc:
        result = {"status": "failed", "stage": "activation", "error": str(exc)}
        raise
    finally:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
