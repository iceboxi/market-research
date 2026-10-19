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
        result = archive(proposal(tmp_path, snapshot(["tw-material-new"], day=18)),
                         GitStateStore(checkout))
        assert result["status"] == "partial"
        assert "event_state/tw/2330.TW.json" in result["skipped"]
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


def test_reject_unapproved_fields_bad_source_and_oversized_ids(repo, tmp_path):
    from scripts.event_watch_archive import validate_records
    checkout, bare, _ = repo
    original = snapshot(["tw-material-a"])
    key = "event_state/tw/2330.TW.json"
    for altered in (
        {**original, "headline": "Do not store disclosure text"},
        {**original, "source": "https://untrusted.example/news"},
        {**original, "seen_ids": ["tw-material-" + str(i) for i in range(2001)]},
        {**original, "observed_at_utc": "2026-10-19T12:00:00"},
        {**original, "seen_ids": ["tw-material-duplicate"] * 2},
    ):
        with pytest.raises(StateError):
            validate_records({key: altered})
    assert git("rev-parse", "main", cwd=bare) == repo[2]


def test_valid_us_source_contract_and_bad_sec_url():
    from scripts.event_watch_archive import validate_records
    good = build_snapshot("AAPL", "us", {
        "status": "available", "coverage": "recent_SEC_submissions_metadata_only",
        "source": "https://data.sec.gov/submissions/CIK0000320193.json",
        "events": [{"event_id": "sec-0000320193-26-000111"}],
    }, datetime(2026, 10, 19, 12, tzinfo=timezone.utc))
    validate_records({"event_state/us/AAPL.json": good})
    with pytest.raises(StateError):
        validate_records({"event_state/us/AAPL.json":
                          {**good, "source": "https://dataXsec.gov/submissions/CIK0000320193.json"}})


def test_conflicting_single_symbol_does_not_block_healthy_peer(repo, tmp_path):
    checkout, bare, _ = repo
    proposals = tmp_path / "split"
    (proposals / "tw").mkdir(parents=True)
    (proposals / "tw/2330.TW.json").write_text(json.dumps(snapshot(["tw-material-old"], day=18)))
    another = build_snapshot("2317.TW", "tw", {
        "status": "available", "coverage": "recent_daily_snapshot_only_not_a_full_history",
        "source": "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
        "events": [{"event_id": "tw-material-new"}],
    }, datetime(2026, 10, 19, 12, tzinfo=timezone.utc))
    (proposals / "tw/2317.TW.json").write_text(json.dumps(another))
    with chdir(checkout):
        result = archive(proposals, GitStateStore(checkout))
        assert result["status"] == "partial"
        assert result["skipped"].keys() == {"event_state/tw/2330.TW.json"}
        actual = event_state(GitStateStore(checkout))["records"]
        assert actual["event_state/tw/2330.TW.json"]["seen_ids"] == ["tw-material-a"]
        assert actual["event_state/tw/2317.TW.json"]["seen_ids"] == ["tw-material-new"]


def test_real_git_race_remerges_healthy_other_symbol(repo, tmp_path):
    checkout, bare, main_sha = repo
    first = proposal(tmp_path, snapshot(["tw-material-b"]))
    competing = tmp_path / "competing"
    (competing / "tw").mkdir(parents=True)
    independent = build_snapshot("2317.TW", "tw", {
        "status": "available", "coverage": "recent_daily_snapshot_only_not_a_full_history",
        "source": "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
        "events": [{"event_id": "tw-material-competitor"}],
    }, datetime(2026, 10, 19, 12, tzinfo=timezone.utc))
    (competing / "tw/2317.TW.json").write_text(json.dumps(independent))
    class RaceStore(GitStateStore):
        raced = False
        def _git(self, *args, **kwargs):
            if args and args[0] == "push" and not self.raced:
                self.raced = True
                success = archive(competing, GitStateStore(checkout))
                assert success["status"] == "archived"
            return super()._git(*args, **kwargs)
    with chdir(checkout):
        response = archive(first, RaceStore(checkout))
        assert response["attempts"] == 2
        state = event_state(GitStateStore(checkout))
        assert set(state["records"]) == {
            "event_state/tw/2330.TW.json",
            "event_state/tw/2317.TW.json",
        }
        assert state["records"]["event_state/tw/2330.TW.json"]["seen_ids"] == [
            "tw-material-a", "tw-material-b"]
        assert git("rev-parse", "main", cwd=bare) == main_sha


def test_partial_watch_source_still_proposes_healthy_symbol(tmp_path, monkeypatch):
    from scripts.event_watch import watch
    import yaml
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({"symbols": [
        {"market": "tw", "symbol": "2330.TW"},
        {"market": "tw", "symbol": "2317.TW"},
    ]}))
    def fake(symbol, now, get):
        if symbol == "2330.TW":
            return {"source": "TWSE", "status": "unavailable",
                    "coverage": "not_verified", "events": []}
        return {"source": "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
                "status": "available",
                "coverage": "recent_daily_snapshot_only_not_a_full_history",
                "events": [{"event_id": "tw-material-good"}]}
    monkeypatch.setattr("scripts.event_watch.tw_material_events", fake)
    output = tmp_path / "output"
    result = watch(cfg, tmp_path / "state", output,
                   now=datetime(2026, 10, 19, 12, tzinfo=timezone.utc))
    assert result["status"] == "partial"
    assert not (output / "proposed_state/tw/2330.TW.json").exists()
    assert (output / "proposed_state/tw/2317.TW.json").exists()


def test_bootstrap_blocked_outside_main_dispatch(tmp_path, monkeypatch):
    from scripts.event_watch_bootstrap import bootstrap
    monkeypatch.setenv("GITHUB_REF", "refs/heads/feature")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    with pytest.raises(ValueError):
        bootstrap(tmp_path)


def test_restore_refuses_nonempty_destination(repo, tmp_path):
    checkout, _, _ = repo
    out = tmp_path / "restore"
    out.mkdir()
    (out / "tw").mkdir()
    (out / "tw/2330.TW.json").write_text('{"stale": true}')
    with chdir(checkout), pytest.raises(ValueError, match="must be empty"):
        restore(out)
    assert (out / "tw/2330.TW.json").read_text() == '{"stale": true}'


def test_corrupt_authority_blocks_event_restore(repo, tmp_path):
    checkout, bare, _ = repo
    peer = tmp_path / "peer"
    git("clone", "--branch", "research-state", str(bare), str(peer))
    git("config", "user.name", "Breaker", cwd=peer)
    git("config", "user.email", "breaker@example.invalid", cwd=peer)
    record = peer / "events/event_state/tw/2330.TW.json"
    record.write_text('{"schema_version": 999}')
    git("add", ".", cwd=peer)
    git("commit", "-m", "corrupt canonical event snapshot", cwd=peer)
    git("push", "origin", "research-state", cwd=peer)
    with chdir(checkout), pytest.raises(StateError):
        restore(tmp_path / "out")
    assert git("branch", "--show-current", cwd=checkout) == "feature"


def test_bootstrap_requires_paused_writer_and_no_active_jobs(repo, tmp_path, monkeypatch):
    """One-time migration cannot overlap the old main-writing watcher."""
    import subprocess as process
    from scripts.event_watch_bootstrap import bootstrap

    checkout, _, main_sha = repo
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_REPOSITORY", "iceboxi/market-research")
    monkeypatch.setenv("GITHUB_SHA", main_sha)
    original = process.run
    state = {"enabled": True, "pending": ""}

    def fake_run(args, *rest, **kwargs):
        if args and args[0] == "gh":
            if "runs?" in args[-1]:
                return process.CompletedProcess(args, 0, stdout=state["pending"])
            return process.CompletedProcess(
                args, 0, stdout=json.dumps({
                    "state": "active" if state["enabled"] else "disabled_manually"
                }))
        return original(args, *rest, **kwargs)

    monkeypatch.setattr("scripts.event_watch_bootstrap.subprocess.run", fake_run)
    with chdir(checkout):
        with pytest.raises(ValueError, match="Disable Official"):
            bootstrap(tmp_path)
        state.update(enabled=False, pending="391888888")
        with pytest.raises(ValueError, match="still pending"):
            bootstrap(tmp_path)
        state["pending"] = ""
        result = bootstrap(tmp_path)
        assert result["authority"]["legacy_import"]["source_sha"] == main_sha
        assert result["main_after"] == main_sha


def test_restore_refuses_already_populated_directory(repo, tmp_path):
    checkout, _, _ = repo
    path = tmp_path / "output/tw/2330.TW.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"state": "stale"}')
    with chdir(checkout), pytest.raises(ValueError, match="must be empty"):
        restore(path.parents[1])
    assert json.loads(path.read_text()) == {"state": "stale"}



def test_zero_legacy_events_bootstraps_alongside_existing_operations_namespace(tmp_path):
    """Regression for failed real Bootstrap run #39196950385.

    A real bare Git remote has operations state but main has no event_state/
    files. The explicit empty import must persist an authority manifest and
    allow subsequent normal first-event archiving without touching main.
    """
    bare, checkout = tmp_path / "remote.git", tmp_path / "checkout"
    git("init", "--bare", "--initial-branch=main", str(bare))
    git("clone", str(bare), str(checkout))
    git("config", "user.name", "Test", cwd=checkout)
    git("config", "user.email", "test@example.invalid", cwd=checkout)
    legacy = checkout / "legacy_ops/history.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"kind":"operations","run":"prior"}')
    git("add", ".", cwd=checkout)
    git("commit", "-m", "main without event data", cwd=checkout)
    git("push", "origin", "main", cwd=checkout)
    main_before = git("rev-parse", "main", cwd=bare)
    git("switch", "-c", "feature", cwd=checkout)

    with chdir(checkout):
        store = GitStateStore(checkout)
        existing = store.commit("operations", lambda records: records,
                                legacy_prefix="legacy_ops", initialize=True)
        assert existing["status"] == "archived"
        imported = initialize_events(store)
        assert imported["status"] == "archived"
        assert imported["authority"]["record_count"] == 0
        assert imported["authority"]["legacy_import"]["record_count"] == 0
        assert imported["authority"]["legacy_import"]["source_sha"] == main_before
        assert imported["authority"]["legacy_import"]["prefix"] == "event_state"
        assert event_state(store)["records"] == {}
        assert initialize_events(store)["status"] == "already_current"

        saved_manifest = json.loads(
            git("show", "research-state:.state-store.json", cwd=bare))
        assert set(saved_manifest["namespaces"]) == {"operations", "events"}
        assert saved_manifest["namespaces"]["events"]["record_count"] == 0

        restored = restore(tmp_path / "restored")
        assert restored["count"] == 0
        assert git("rev-parse", "main", cwd=bare) == main_before
        assert git("branch", "--show-current", cwd=checkout) == "feature"

        first = archive(proposal(tmp_path, snapshot(["tw-material-first"])), store)
        assert first["status"] == "archived"
        assert event_state(store)["records"]["event_state/tw/2330.TW.json"][
            "seen_ids"] == ["tw-material-first"]
        assert git("rev-parse", "main", cwd=bare) == main_before


def test_empty_state_cannot_be_initialized_implicitly(tmp_path):
    bare, checkout = tmp_path / "remote.git", tmp_path / "checkout"
    git("init", "--bare", "--initial-branch=main", str(bare))
    git("clone", str(bare), str(checkout))
    git("config", "user.name", "Test", cwd=checkout)
    git("config", "user.email", "test@example.invalid", cwd=checkout)
    (checkout / "README.md").write_text("zero event legacy files")
    git("add", ".", cwd=checkout)
    git("commit", "-m", "baseline", cwd=checkout)
    git("push", "origin", "main", cwd=checkout)

    with chdir(checkout):
        store = GitStateStore(checkout)
        with pytest.raises(StateError, match="explicit migration required"):
            store.commit("events", lambda records: records)
        assert git("show-ref", "--verify", "refs/heads/research-state",
                   cwd=bare, check=False).returncode != 0
