"""Persist verified official event baselines to shared GitStateStore.

Independent healthy sources survive partial watch failures. No direct main
writes, and no implicit initialization or legacy fallback after migration.
"""
import argparse
import json
import os
from pathlib import Path
import re
from datetime import datetime

from market_research.event_risk import TW_MATERIAL_URL
from market_research.event_monitor import MAX_IDS, build_snapshot

from market_research.event_monitor import compare_snapshots
from scripts.state_store import GitStateStore, StateError


class EventArchiveError(StateError):
    def __init__(self, receipt):
        self.receipt = receipt
        super().__init__(receipt["error"])


def validate_records(records):
    """Only strict, compact, source-identified metadata may enter the events store."""
    expected_keys = {
        "schema_version", "market", "symbol", "observed_at_utc",
        "source", "coverage", "seen_ids",
    }
    if not isinstance(records, dict):
        raise StateError("Invalid event state tree")
    for path, value in records.items():
        parts = path.split("/")
        if len(parts) != 3 or parts[0] != "event_state" or not parts[2].endswith(".json"):
            raise StateError("Invalid event state path")
        market, symbol = parts[1], parts[2][:-5]
        if not isinstance(value, dict) or set(value) != expected_keys:
            raise StateError("Event state must contain metadata fields only")
        if (type(value["schema_version"]) is not int or value["schema_version"] != 1 or
                value["market"] != market or value["symbol"] != symbol):
            raise StateError("Event state identity or schema mismatch")
        try:
            build_snapshot(symbol, market, {"status": "unavailable"},
                           datetime.fromisoformat(value["observed_at_utc"]))
            observed = datetime.fromisoformat(value["observed_at_utc"])
        except (KeyError, ValueError, TypeError) as exc:
            raise StateError("Malformed event state observation timestamp") from exc
        if observed.tzinfo is None:
            raise StateError("Event snapshot timestamp must have a timezone")
        if market == "tw":
            if (value["source"] != TW_MATERIAL_URL or
                    value["coverage"] != "recent_daily_snapshot_only_not_a_full_history"):
                raise StateError("Unrecognized TWSE event source/coverage")
        elif market == "us":
            if (not isinstance(value["source"], str) or
                    not re.fullmatch(r"https://data\.sec\.gov/submissions/CIK[0-9]{10}\.json",
                                     value["source"]) or
                    value["coverage"] != "recent_SEC_submissions_metadata_only"):
                raise StateError("Unrecognized SEC event source/coverage")
        else:
            raise StateError("Unsupported event market")
        ids = value["seen_ids"]
        if (not isinstance(ids, list) or len(ids) > MAX_IDS or
                len(ids) != len(set(x for x in ids if isinstance(x, str))) or
                any(not isinstance(x, str) or not re.fullmatch(r"[A-Za-z0-9-]{3,100}", x)
                    for x in ids)):
            raise StateError("Malformed or oversized observed event ID cache")
    return records


def event_state(store=None):
    data = (store or GitStateStore()).read("events")
    if data["status"] != "available":
        raise StateError("Events state namespace missing; explicit migration required")
    validate_records(data["records"])
    return data


def initialize_events(store=None):
    """Deliberate one-time migration from tracked main/event_state only."""
    store = store or GitStateStore()
    return store.commit("events", validate_records,
                        legacy_prefix="event_state", initialize=True)


def archive(proposed_root, store=None, run_url=None):
    store = store or GitStateStore()
    receipt = {"schema_version": 1, "status": "failed", "namespace": "events",
               "run_url": run_url, "code_sha": os.getenv("GITHUB_SHA"),
               "state_commit": None, "stage": "read_main_before",
               "persistence_status": "not_attempted", "main_before": None,
               "main_after": None, "eligible": 0}
    try:
        receipt["main_before"] = store.main_head()
        source = Path(proposed_root)
        proposed = {}
        for path in sorted(source.glob("*/*.json")):
            market, symbol = path.parent.name, path.stem
            value = json.loads(path.read_text(encoding="utf-8"))
            key = "event_state/" + market + "/" + symbol + ".json"
            proposed[key] = value
        validate_records(proposed)
        receipt["eligible"] = len(proposed)
        if not proposed:
            current = event_state(store)
            receipt.update(status="no_eligible_state", state_commit=current["head"],
                           authority=current["authority"], stage="complete",
                           persistence_status="unchanged", main_after=store.main_head())
            return receipt

        skipped = {}

        def merge(records):
            # This callback runs again after a concurrent fast-forward race.
            # Decide eligibility against the latest state, never the stale
            # state originally restored by the watcher.
            validate_records(records)
            result = dict(records)
            skipped.clear()
            for key, candidate in proposed.items():
                prior = records.get(key)
                change, merged = compare_snapshots(prior, candidate)
                if merged is None:
                    skipped[key] = change["reason"]
                    continue
                result[key] = merged
            return validate_records(result)

        receipt.update(stage="commit_state", persistence_status="outcome_unknown")
        saved = store.commit("events", merge)
        receipt.update(saved)
        receipt.update(stage="verify_main_after", main_after=store.main_head(),
                       persistence_status=saved["status"])
        if receipt["main_before"] != receipt["main_after"]:
            raise StateError("Main changed during persistence; manual review required")
        receipt["skipped"] = dict(skipped)
        receipt["status"] = "partial" if skipped else saved["status"]
        receipt["stage"] = "complete"
        return receipt
    except (StateError, OSError, ValueError, TypeError, KeyError) as error:
        receipt.update(getattr(error, "context", {}))
        receipt.update(status="failed", error=str(error))
        raise EventArchiveError(receipt) from error


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--proposed", type=Path, required=True)
    p.add_argument("--receipt", type=Path, default=Path("event_watch_output/state_receipt.json"))
    args = p.parse_args()
    receipt = {"status": "failed", "stage": "not_started"}
    try:
        url = ("https://github.com/" + os.getenv("GITHUB_REPOSITORY", "") +
               "/actions/runs/" + os.getenv("GITHUB_RUN_ID", ""))
        receipt = archive(args.proposed, run_url=url)
        if receipt["status"] == "partial":
            raise EventArchiveError({**receipt,
                                     "error": "Some event keys could not be safely persisted"})
    except EventArchiveError as error:
        receipt = error.receipt
        raise
    finally:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
