"""Research persistence against a real bare remote; no fake Git success."""
from contextlib import chdir
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from market_research.research_snapshot import prepare_snapshot
from scripts.state_store import GitStateStore, StateError
from scripts.research_state import archive, initialize, read, render_publication, validate_records, snapshot_path
from test_research_snapshot import report, identity


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, text=True,
                          capture_output=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    bare, checkout = tmp_path / "remote.git", tmp_path / "repo"
    git("init", "--bare", "--initial-branch=main", str(bare), cwd=tmp_path)
    git("clone", str(bare), str(checkout), cwd=tmp_path)
    git("config", "user.name", "Test", cwd=checkout)
    git("config", "user.email", "test@example.invalid", cwd=checkout)
    (checkout / "README.md").write_text("analysis checkout")
    git("add", ".", cwd=checkout)
    git("commit", "-m", "baseline", cwd=checkout)
    git("push", "origin", "main", cwd=checkout)
    git("switch", "-c", "feature", cwd=checkout)
    store = GitStateStore(checkout)
    store.commit("operations", lambda records: records, initialize=True, legacy_prefix="operations")
    return checkout, bare, store


def test_explicit_empty_init_archive_idempotence_and_fresh_process_restore(repo):
    checkout, bare, store = repo
    snapshot = prepare_snapshot(report(), identity())
    with pytest.raises(StateError, match="explicit"):
        archive(snapshot, store)
    before = store.read("operations")
    assert initialize(store)["status"] == "archived"
    assert read(store)["records"] == {}
    assert initialize(store)["status"] == "already_current"
    saved = archive(snapshot, store)
    assert saved["main_before"] == saved["main_after"]
    assert saved["checkout_before"] == saved["checkout_after"]
    assert archive(snapshot, store)["status"] == "already_current"
    state = read(store)
    subject = state["records"]["subjects/tw/2330.TW.json"]
    assert subject["latest_observation_id"] == subject["last_success_id"] == snapshot["id"]
    assert subject["pending_publication_id"]
    assert subject["issue_number"] is None
    assert store.read("operations")["authority"] == before["authority"]
    assert git("rev-parse", "main", cwd=bare) == saved["main_before"]
    assert git("branch", "--show-current", cwd=checkout) == "feature"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]) + ":" +
           str(Path(__file__).resolve().parents[1] / "src")}
    fresh = subprocess.run([sys.executable, "-c",
        "import json; from scripts.research_state import read; "
        "from scripts.state_store import GitStateStore; print(json.dumps(read(GitStateStore())))"],
        cwd=checkout, env=env, text=True, capture_output=True, check=True)
    assert json.loads(fresh.stdout) == state


def test_new_partial_keeps_last_success_and_out_of_order_does_not_hide_failure(repo):
    _, _, store = repo
    initialize(store)
    healthy = prepare_snapshot(report(), identity())
    archive(healthy, store)
    failed = prepare_snapshot(report("2026-10-20T12:00:00+00:00", False),
                              identity("101", "2026-10-20T12:01:00+00:00"))
    archive(failed, store)
    archive(healthy, store)
    records = read(store)["records"]
    subject = records["subjects/tw/2330.TW.json"]
    assert subject["latest_observation_id"] == failed["id"]
    assert subject["last_success_id"] == healthy["id"]
    body = render_publication(records, subject["pending_publication_id"], store.branch)
    assert "最近嘗試：2026-10-20T12:01:00+00:00 — partial" in body
    assert "最近資料流程完成：2026-10-19T12:01:00+00:00" in body
    assert "不代表財報、估值或買賣建議已完成" in body
    assert "完整 replay" in body


def test_real_ff_race_preserves_competing_namespace_and_retries_latest(repo):
    checkout, _, store = repo
    initialize(store)
    class RaceStore(GitStateStore):
        raced = False
        def _git(self, *args, **kwargs):
            if args and args[0] == "push" and not self.raced:
                self.raced = True
                GitStateStore(checkout).commit("operations", lambda records: {**records, "peer.json": {"run": "peer"}})
            return super()._git(*args, **kwargs)
    saved = archive(prepare_snapshot(report(), identity()), RaceStore(checkout))
    assert saved["attempts"] == 2
    assert store.read("operations")["records"] == {"peer.json": {"run": "peer"}}
    assert read(store)["records"]["subjects/tw/2330.TW.json"]["pending_publication_id"]


def test_failed_ff_retries_are_bounded_and_do_not_lose_pending(repo):
    checkout, _, store = repo
    initialize(store)
    class RejectStore(GitStateStore):
        pushes = 0
        def _git(self, *args, **kwargs):
            if args and args[0] == "push":
                self.pushes += 1
                return subprocess.CompletedProcess(args, 1, "", "rejected")
            return super()._git(*args, **kwargs)
    rejected = RejectStore(checkout)
    with pytest.raises(StateError, match="after 3 attempts"):
        archive(prepare_snapshot(report(), identity()), rejected)
    assert rejected.pushes == 3
    assert read(store)["records"] == {}


def test_corrupt_snapshot_and_unapproved_paths_fail_closed(repo):
    _, _, store = repo
    initialize(store)
    snapshot = prepare_snapshot(report(), identity())
    archive(snapshot, store)
    with pytest.raises(StateError):
        validate_records({"raw_response.json": {"payload": "private"}}, store.branch)
    with pytest.raises(StateError, match="budget"):
        validate_records({str(i): {} for i in range(2001)}, store.branch)
    def corrupt(records):
        records[snapshot_path(snapshot["id"])]["monthly_revenue"][0]["value"] += 1
        return records
    store.commit("research", corrupt)
    with pytest.raises(StateError):
        archive(snapshot, store)
