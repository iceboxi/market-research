"""Canonical prospective writer must fail closed on schema and state failures."""
from datetime import datetime, timezone
import pytest
from scripts.prospective_state_archive import archive, ArchiveFailure
from scripts.state_store import StateError
from scripts.prospective_state import append


def record(sha="a"*40):
    return {
        "schema_version": 2, "kind": "prospective_observation_only",
        "freeze_date": "2026-10-18", "freeze_hash": "b"*64,
        "observed_at_utc": datetime(2026,10,19,12,tzinfo=timezone.utc).isoformat(),
        "session_date": "2026-10-19", "market": "tw",
        "source_scan_run":"https://github.com/example/repo/actions/runs/123",
        "run_id":"123", "source_provenance":[], "strategy_versions":[],
        "scanned_symbols":10, "observations":[], "abstained_count":0,
        "has_matured_forward_outcomes":False, "is_strategy_performance_evidence":False,
        "cohort_revision": {
            "code_sha":sha, "config_sha256":"b"*64, "provider_sha256":"c"*64,
            "calendar_sha256":"d"*64, "method_sha256":"e"*64
        },
    }


class Store:
    def __init__(self, fail=False):
        self.records={}
        self.fail=fail
    def main_head(self):
        return "f"*40
    def commit(self, name, merge):
        if self.fail:
            raise StateError("remote write denied")
        before=dict(self.records)
        self.records=merge(self.records)
        return {"status":"archived" if before!=self.records else "already_current",
                "state_commit":"a"*40,"authority":{"source":"fixture"}}
    def read(self, name):
        return {"status":"available","records":self.records,"head":"a"*40}


def test_writer_success_exact_revision_and_fresh_read(monkeypatch):
    r=record()
    monkeypatch.setattr("scripts.prospective_state_archive.verify_runtime",
                        lambda candidate,repo:r["cohort_revision"])
    store=Store()
    first=archive(r,store)
    assert first["status"]=="passed"
    assert first["main_before"]==first["main_after"]
    assert archive(r,store)["persistence_status"]=="already_current"


def test_writer_denied_or_mismatched_revision_fails(monkeypatch):
    r=record()
    def invalid(candidate,repo):
        raise StateError("wrong revision")
    monkeypatch.setattr("scripts.prospective_state_archive.verify_runtime",invalid)
    with pytest.raises(ArchiveFailure,match="wrong revision"):
        archive(r,Store())
    monkeypatch.setattr("scripts.prospective_state_archive.verify_runtime",
                        lambda candidate,repo:r["cohort_revision"])
    with pytest.raises(ArchiveFailure,match="remote write denied") as exc:
        archive(r,Store(fail=True))
    assert exc.value.receipt["persistence_status"]=="outcome_unknown"
