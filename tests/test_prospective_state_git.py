"""Real bare-Git acceptance of prospective namespace and main isolation."""
from contextlib import chdir
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

import pytest

from scripts.prospective_state import append, initialize, read
from scripts.state_store import GitStateStore, StateError


def git(*args, cwd=None):
    return subprocess.run(["git", *args], check=True, cwd=cwd,
                          capture_output=True, text=True).stdout.strip()


def fixture(run="123"):
    return {
        "schema_version": 1, "kind": "prospective_observation_only",
        "freeze_date": "2026-10-18", "freeze_hash": "a" * 64,
        "observed_at_utc": datetime(2026, 10, 19, 12, tzinfo=timezone.utc).isoformat(),
        "session_date": "2026-10-19", "market": "tw",
        "source_scan_run": "https://github.com/test/r/actions/runs/" + run,
        "run_id": run, "source_provenance": [], "strategy_versions": [],
        "scanned_symbols": 10, "observations": [], "abstained_count": 0,
        "has_matured_forward_outcomes": False,
        "is_strategy_performance_evidence": False,
    }


@pytest.fixture
def remote(tmp_path):
    bare = tmp_path / "origin.git"
    checkout = tmp_path / "checkout"
    git("init", "--bare", "--initial-branch=main", str(bare))
    git("clone", str(bare), str(checkout))
    git("config", "user.name", "Tester", cwd=checkout)
    git("config", "user.email", "test@example.invalid", cwd=checkout)
    old = checkout / ("prospective/" + "a" * 16 + "/tw/2026-10-19.json")
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps(fixture()), encoding="utf-8")
    (checkout / "code.txt").write_text("unchanged code")
    git("add", ".", cwd=checkout)
    git("commit", "-m", "Legacy prospective receipt", cwd=checkout)
    git("push", "origin", "main", cwd=checkout)
    main_sha = git("rev-parse", "main", cwd=bare)
    git("switch", "-c", "feature", cwd=checkout)
    with chdir(checkout):
        init = initialize(GitStateStore(checkout))
    assert init["status"] == "archived"
    return checkout, bare, main_sha


def test_canonical_import_read_repeat_conflict_and_main_invariance(remote):
    checkout, bare, main_sha = remote
    with chdir(checkout):
        store = GitStateStore(checkout)
        baseline = read(store)
        assert baseline["authority"]["legacy_import"]["source_sha"] == main_sha
        assert len(baseline["records"]) == 1
        assert append(fixture(), store)["status"] == "already_current"
        different = {**fixture(), "run_id": "999",
                     "source_scan_run": "https://github.com/test/r/actions/runs/999"}
        with pytest.raises(StateError, match="conflict"):
            append(different, store)
        assert git("rev-parse", "main", cwd=bare) == main_sha
        assert git("branch", "--show-current", cwd=checkout) == "feature"


def test_corrupt_or_deleted_authority_never_rebootstraps(remote):
    checkout, bare, _ = remote
    git("update-ref", "-d", "refs/heads/research-state", cwd=bare)
    with chdir(checkout):
        with pytest.raises(StateError):
            read(GitStateStore(checkout))
        with pytest.raises(StateError):
            append(fixture(), GitStateStore(checkout))


def test_other_namespace_unchanged_after_prospective_append(remote):
    checkout, bare, _ = remote
    with chdir(checkout):
        store = GitStateStore(checkout)
        store.commit("isolated", lambda _: {"metadata/check.json": {"ok": True}},
                     legacy_prefix="absent", initialize=True)
        same = append(fixture(), store)
        assert same["status"] == "already_current"
        assert store.read("isolated")["records"] == {"metadata/check.json": {"ok": True}}
