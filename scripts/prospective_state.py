"""Canonical immutable prospective metadata adapter; no production cutover here.

Legacy records remain schema v1 and are never silently upgraded.
The shared GitStateStore owns all Git operations and migration authority.
"""
from datetime import date, datetime
import json
import re

from scripts.state_store import GitStateStore, StateError, canonical

NAMESPACE = "prospective"
ALLOWED = {
    "schema_version", "kind", "freeze_date", "freeze_hash",
    "observed_at_utc", "session_date", "market", "source_scan_run",
    "run_id", "source_provenance", "strategy_versions", "scanned_symbols",
    "observations", "abstained_count", "has_matured_forward_outcomes",
    "is_strategy_performance_evidence", "cohort_revision",
}


def identity(record):
    """Validate provenance/temporal/cohort identity prior to Git writes."""
    if not isinstance(record, dict) or not set(record) <= ALLOWED:
        raise StateError("Unknown prospective metadata fields")
    try:
        session = date.fromisoformat(record["session_date"])
        frozen = date.fromisoformat(record["freeze_date"])
        observed = datetime.fromisoformat(record["observed_at_utc"])
    except (KeyError, ValueError, TypeError) as exc:
        raise StateError("Missing or malformed prospective observation dates") from exc
    if session <= frozen or observed.tzinfo is None:
        raise StateError("Prospective sample must be post-freeze and timezone-aware")
    if record.get("market") not in ("tw", "us"):
        raise StateError("Unknown prospective market")
    if (record.get("kind") != "prospective_observation_only" or
            record.get("has_matured_forward_outcomes") is not False or
            record.get("is_strategy_performance_evidence") is not False):
        raise StateError("Prospective metadata is not research-only")
    if not re.fullmatch("[a-f0-9]{64}", str(record.get("freeze_hash", ""))):
        raise StateError("Invalid frozen configuration hash")
    if not isinstance(record.get("run_id"), str) or not record["run_id"].isdigit():
        raise StateError("Missing numeric source run identity")
    if (not isinstance(record.get("source_scan_run"), str) or
            not record["source_scan_run"].endswith("/" + record["run_id"])):
        raise StateError("Mismatched source run")
    for name in ("source_provenance", "strategy_versions", "observations"):
        if not isinstance(record.get(name), list):
            raise StateError("Prospective observation payload must be a list")
    if (type(record.get("scanned_symbols")) is not int or record["scanned_symbols"] < 0 or
            type(record.get("abstained_count")) is not int or record["abstained_count"] < 0):
        raise StateError("Missing prospective coverage")
    if record.get("schema_version") == 1:
        if "cohort_revision" in record:
            raise StateError("Cannot retroactively relabel frozen legacy cohort")
    elif record.get("schema_version") == 2:
        rev = record.get("cohort_revision")
        expected = {"code_sha", "provider_sha256", "calendar_sha256", "config_sha256"}
        if (not isinstance(rev, dict) or set(rev) != expected or
                any(not re.fullmatch("[a-f0-9]{40,64}" if k == "code_sha" else "[a-f0-9]{64}",
                                     str(v)) for k, v in rev.items())):
            raise StateError("Incomplete prospective code/provider/calendar/config revision")
    else:
        raise StateError("Unknown prospective schema version")
    if len(canonical(record)) > 200000:
        raise StateError("Prospective metadata too large")
    return "prospective/" + record["freeze_hash"][:16] + "/" + record["market"] + "/" + session.isoformat() + ".json"


def validate(records):
    if not isinstance(records, dict):
        raise StateError("Prospective state must be a metadata map")
    for path, payload in records.items():
        if path != identity(payload):
            raise StateError("Prospective state path and receipt identity disagree")
    return records


def read(store=None):
    data = (store or GitStateStore()).read(NAMESPACE)
    if data["status"] != "available":
        raise StateError("Prospective state unavailable; explicit bootstrap required")
    validate(data["records"])
    return data


def initialize(store=None):
    return (store or GitStateStore()).commit(
        NAMESPACE, validate, legacy_prefix="prospective", initialize=True
    )


def append(record, store=None):
    """Immutable session key; FF retry owned by shared store."""
    location = identity(record)

    def merge(records):
        validate(records)
        old = records.get(location)
        if old is not None and canonical(old) != canonical(record):
            raise StateError("Immutable prospective session conflict: " + location)
        return {**records, location: json.loads(canonical(record))}

    saved = (store or GitStateStore()).commit(NAMESPACE, merge)
    return {**saved, "path": location}
