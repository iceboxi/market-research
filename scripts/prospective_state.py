"""Canonical immutable prospective metadata adapter; no production cutover here.

Legacy records remain schema v1 and are never silently upgraded.
The shared GitStateStore owns all Git operations and migration authority.
"""
from datetime import date, datetime
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess

from scripts.state_store import GitStateStore, StateError, canonical
from scripts.prospective_journal import fingerprint

NAMESPACE = "prospective"
ALLOWED = {
    "schema_version", "kind", "freeze_date", "freeze_hash",
    "observed_at_utc", "session_date", "market", "source_scan_run",
    "run_id", "source_provenance", "strategy_versions", "scanned_symbols",
    "observations", "abstained_count", "has_matured_forward_outcomes",
    "is_strategy_performance_evidence", "cohort_revision",
}


PROVIDER_FILES = (
    "src/market_research/market_data.py",
    "src/market_research/provider.py",
    "src/market_research/twse.py",
)
CALENDAR_FILES = (
    "src/market_research/market_calendar.py",
    "uv.lock",
)
METHOD_FILES = (
    "src/market_research/runner.py",
    "src/market_research/strategies.py",
    "src/market_research/strategy_contract.py",
    "scripts/strategy_research.py",
    "scripts/prospective_observe.py",
)
METHOD_REVISION_KEYS = (
    "config_sha256", "provider_sha256", "calendar_sha256", "method_sha256",
)


def _file_set_digest(repo, paths):
    raw = b""
    for relative in paths:
        path = repo / relative
        raw += relative.encode("utf-8") + b"\0" + path.read_bytes() + b"\0"
    return sha256(raw).hexdigest()


def runtime_revision(repo=Path("."), *, source_sha=None):
    """Pin code/config/provider/calendar inputs from this exact checkout."""
    repo = Path(repo)
    if source_sha is None:
        try:
            source_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                capture_output=True, text=True, timeout=20,
            ).stdout.strip()
        except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired) as exc:
            raise StateError("Cannot identify prospective source checkout") from exc
    if not re.fullmatch(r"[a-f0-9]{40,64}", str(source_sha)):
        raise StateError("Invalid prospective code SHA")
    return {
        "code_sha": source_sha,
        "config_sha256": fingerprint(repo),
        "provider_sha256": _file_set_digest(repo, PROVIDER_FILES),
        "calendar_sha256": _file_set_digest(repo, CALENDAR_FILES),
        "method_sha256": _file_set_digest(repo, METHOD_FILES),
    }


def verify_runtime(record, repo=Path(".")):
    """Refuse an archive copied from another code/config checkout."""
    if record.get("schema_version") != 2:
        raise StateError("Only revision-pinned schema v2 receipts may be newly archived")
    revision = runtime_revision(repo)
    if record.get("cohort_revision") != revision:
        raise StateError("Prospective run revision differs from active code/config/provider/calendar")
    if record.get("freeze_hash") != revision["config_sha256"]:
        raise StateError("Research freeze fingerprint does not match pinned config")
    return revision



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
        expected = {"code_sha", "provider_sha256", "calendar_sha256",
                    "config_sha256", "method_sha256"}
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
        # A new schema/revision cannot silently enter an existing frozen cohort.
        # The user must explicitly approve a fresh config freeze to start one.
        if record.get("schema_version") == 2:
            freeze = record["freeze_hash"]
            for prior in records.values():
                if prior["freeze_hash"] != freeze:
                    continue
                if (prior.get("schema_version") != 2 or
                        any(prior["cohort_revision"].get(field) !=
                            record["cohort_revision"].get(field)
                            for field in METHOD_REVISION_KEYS)):
                    raise StateError("New prospective cohort approval required for revision change")
        old = records.get(location)
        if old is not None and canonical(old) != canonical(record):
            raise StateError("Immutable prospective session conflict: " + location)
        return {**records, location: json.loads(canonical(record))}

    saved = (store or GitStateStore()).commit(NAMESPACE, merge)
    return {**saved, "path": location}
