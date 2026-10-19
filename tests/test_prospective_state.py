"""Prospective state domain contract without modifying any production writer."""
from datetime import datetime, timezone
import json
import pytest

from scripts.prospective_state import identity, validate, append, read
from scripts.state_store import StateError


def record():
    return {
        "schema_version": 1, "kind": "prospective_observation_only",
        "freeze_date": "2026-10-18", "freeze_hash": "a" * 64,
        "observed_at_utc": datetime(2026, 10, 19, 12, tzinfo=timezone.utc).isoformat(),
        "session_date": "2026-10-19", "market": "tw",
        "source_scan_run": "https://github.com/test/repo/actions/runs/123",
        "run_id": "123", "source_provenance": [], "strategy_versions": [],
        "scanned_symbols": 10, "observations": [], "abstained_count": 0,
        "has_matured_forward_outcomes": False,
        "is_strategy_performance_evidence": False,
    }


class InMemoryState:
    def __init__(self, initialized=True):
        self.initialized = initialized
        self.records = {}
        self.calls = 0

    def read(self, namespace):
        return {"status": "available" if self.initialized else "uninitialized",
                "records": self.records, "head": "a" * 40}

    def commit(self, namespace, merge):
        if not self.initialized:
            raise StateError("Missing authority")
        self.calls += 1
        updated = merge(self.records)
        changed = updated != self.records
        self.records = updated
        return {"status": "archived" if changed else "already_current",
                "state_commit": "b" * 40}


def test_legacy_identity_and_replay_are_immutable():
    s = InMemoryState()
    r = record()
    assert identity(r) == "prospective/" + "a" * 16 + "/tw/2026-10-19.json"
    assert append(r, s)["status"] == "archived"
    assert append(r, s)["status"] == "already_current"
    assert len(read(s)["records"]) == 1
    with pytest.raises(StateError, match="conflict"):
        append({**r, "run_id": "124", "source_scan_run": r["source_scan_run"][:-3] + "124"}, s)


def test_legacy_cohorts_not_retroactively_upgraded():
    r = record()
    rev = {"code_sha": "a" * 40, "provider_sha256": "b" * 64,
           "calendar_sha256": "c" * 64, "config_sha256": "d" * 64}
    with pytest.raises(StateError, match="retroactively"):
        identity({**r, "cohort_revision": rev})
    assert identity({**r, "schema_version": 2, "cohort_revision": rev})
    with pytest.raises(StateError, match="revision"):
        identity({**r, "schema_version": 2, "cohort_revision": {}})


def test_lack_of_provenance_or_authority_is_not_a_fresh_baseline():
    r = record()
    bad = {**r, "kind": "executed_buy_order"}
    with pytest.raises(StateError):
        identity(bad)
    with pytest.raises(StateError):
        append(r, InMemoryState(initialized=False))
    with pytest.raises(StateError):
        read(InMemoryState(initialized=False))


def test_raw_unapproved_fields_and_path_mismatch_fail_closed():
    r = record()
    with pytest.raises(StateError):
        identity({**r, "close": [100, 101]})
    with pytest.raises(StateError):
        validate({"prospective/wrong/tw/2026-10-19.json": r})


def test_runtime_revision_pins_file_versions(tmp_path, monkeypatch):
    from scripts.prospective_state import runtime_revision, verify_runtime, PROVIDER_FILES, CALENDAR_FILES
    from scripts.state_store import StateError
    from scripts.prospective_journal import fingerprint
    import pytest
    repo = tmp_path
    for relative in (*PROVIDER_FILES, *CALENDAR_FILES,
                     "config/strategies.yaml", "config/markets.yaml",
                     "docs/strategies/catalog.yaml"):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture " + relative)
    sha = "a" * 40
    rev = runtime_revision(repo, source_sha=sha)
    receipt = {**record(), "schema_version": 2,
               "freeze_hash": fingerprint(repo), "cohort_revision": rev}
    assert rev["code_sha"] == sha
    assert rev["config_sha256"] == receipt["freeze_hash"]
    monkey = receipt["cohort_revision"].copy()
    monkey["provider_sha256"] = "b" * 64
    monkeypatch.setattr("scripts.prospective_state.runtime_revision", lambda repo: rev)
    with pytest.raises(StateError, match="revision"):
        verify_runtime({**receipt, "cohort_revision": monkey}, repo)


def test_same_freeze_revision_change_requires_cohort_review():
    from scripts.prospective_state import append
    from scripts.state_store import StateError
    s = InMemoryState()
    r = {**record(), "schema_version": 2, "cohort_revision": {
        "code_sha": "a" * 40, "provider_sha256": "b" * 64,
        "calendar_sha256": "c" * 64, "config_sha256": "a" * 64}}
    assert append(r, s)["status"] == "archived"
    new = {**r, "session_date": "2026-10-20",
           "observed_at_utc": datetime(2026, 10, 20, 12, tzinfo=timezone.utc).isoformat(),
           "cohort_revision": {**r["cohort_revision"], "code_sha": "d" * 40}}
    with pytest.raises(StateError, match="approval"):
        append(new, s)
