"""Smoke tests using a real local Git remote, not mocked Git success."""
from contextlib import chdir
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

import pytest
from market_research.event_monitor import build_snapshot
from scripts.event_watch_archive import event_state, initialize_events, archive, EventArchiveError
from scripts.event_watch_restore import restore
from scripts.state_store import GitStateStore, StateError


def git(*args, cwd=None, check=True):
    p = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=check)
    return p.stdout.strip() if check else p


def snapshot(ids, day=19):
    return build_snapshot("2330.TW", "tw", {
        "status": "available", "coverage": "recent_daily_snapshot_only_not_a_full_history",
        "source": "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
        "events": [{"event_id": x} for x in ids],
    }, datetime(2026, 10, day, 12, tzinfo=timezone.utc))


@pytest.fixture
def repo(tmp_path):
    bare, checkout = tmp_path / "remote.git", tmp_path / "repo"
    git("init", "--bare", "--initial-branch=main", str(bare))
    git("clone", str(bare), str(checkout))
    git("config", "user.name", "Test", cwd=checkout)
    git("config", "user.email", "test@example.invalid", cwd=checkout)
    src = checkout / "event_state/tw/2330.TW.json"
    src.parent.mkdir(parents=True)
    src.write_text(json.dumps(snapshot(["tw-material-a"])))
    git("add", ".", cwd=checkout)
    git("commit", "-m", "legacy", cwd=checkout)
    git("push", "origin", "main", cwd=checkout)
    main_sha = git("rev-parse", "main", cwd=bare)
    git("switch", "-c", "feature", cwd=checkout)
    with chdir(checkout):
        initialize_events(GitStateStore(checkout))
    return checkout, bare, main_sha


def proposal(tmp_path, record):
    path = tmp_path / "proposal/tw/2330.TW.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record))
    return path.parent.parent


def test_import_restore_update_and_repeat(repo, tmp_path):
    checkout, bare, main_sha = repo
    with chdir(checkout):
        restored = restore(tmp_path / "restored")
        assert restored["count"] == 1
        assert json.loads((tmp_path / "restored/tw/2330.TW.json").read_text())["seen_ids"] == ["tw-material-a"]
        directory = proposal(tmp_path, snapshot(["tw-material-b"]))
        first = archive(directory, GitStateStore(checkout))
        assert first["status"] == "archived"
        assert first["main_before"] == first["main_after"] == main_sha
        assert event_state(GitStateStore(checkout))["records"]["event_state/tw/2330.TW.json"]["seen_ids"] == ["tw-material-a", "tw-material-b"]
        assert archive(directory, GitStateStore(checkout))["status"] == "already_current"
        assert git("rev-parse", "main", cwd=bare) == main_sha
        assert git("branch", "--show-current", cwd=checkout) == "feature"


def test_out_of_order_and_invalid_identity_do_not_overwrite(repo, tmp_path):
    checkout, bare, _ = repo
    with chdir(checkout):
        head = git("rev-parse", "research-state", cwd=bare)
        with pytest.raises(EventArchiveError):
            archive(proposal(tmp_path, snapshot(["tw-material-new"], day=18)), GitStateStore(checkout))
        assert git("rev-parse", "research-state", cwd=bare) == head


def test_missing_authority_is_not_a_new_baseline(repo):
    checkout, bare, _ = repo
    git("update-ref", "-d", "refs/heads/research-state", cwd=bare)
    with chdir(checkout), pytest.raises(StateError):
        event_state(GitStateStore(checkout))


def test_rejected_push_fails_explicitly(repo, tmp_path):
    checkout, bare, _ = repo
    hook = bare / "hooks/pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    with chdir(checkout), pytest.raises(EventArchiveError) as caught:
        archive(proposal(tmp_path, snapshot(["tw-material-b"])), GitStateStore(checkout))
    assert caught.value.receipt["status"] == "failed"
