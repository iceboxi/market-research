"""#127: reviewed removal of early and unchanged duplicate research versions."""
import copy
import subprocess

import pytest

from market_research.research_snapshot import prepare_snapshot
from scripts.research_state import archive, initialize, read, snapshot_path, subject_path
from scripts.research_state_prune import apply, plan
from scripts.state_store import GitStateStore, StateError
from test_research_site import _make_full_financial_research, _sample_report


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, text=True, capture_output=True).stdout.strip()


@pytest.fixture
def store(tmp_path):
    bare, checkout = tmp_path / "remote.git", tmp_path / "repo"
    git("init", "--bare", "--initial-branch=main", str(bare), cwd=tmp_path)
    git("clone", str(bare), str(checkout), cwd=tmp_path)
    git("config", "user.name", "Test", cwd=checkout)
    git("config", "user.email", "test@example.invalid", cwd=checkout)
    (checkout / "README.md").write_text("analysis checkout")
    git("add", ".", cwd=checkout)
    git("commit", "-m", "baseline", cwd=checkout)
    git("push", "origin", "main", cwd=checkout)
    store = GitStateStore(checkout)
    store.commit("operations", lambda records: records, initialize=True, legacy_prefix="operations")
    initialize(store)
    return store


def version(day, minute, *, financial=True, revenue=1000.0):
    stamp = f"2026-10-{day}T12:{minute:02d}:00+00:00"
    r = _sample_report(stamp=stamp)
    r["started_utc"] = stamp
    r["issuer"]["facts"][0]["value"] = revenue
    if financial:
        r["financial_research"] = _make_full_financial_research()
        r["research_readiness"]["components"]["financial"]["status"] = "available"
    return prepare_snapshot(r, {"repository": "owner/repo", "run_id": f"{day}{minute}", "run_attempt": 1,
                                "code_sha": "a" * 40, "observed_at_utc": stamp})


def build(store):
    snaps = {
        "early": version(19, 10, financial=False),
        "early_again": version(19, 20, financial=False, revenue=1100.0),
        "first_full": version(20, 10),
        "duplicate": version(20, 30),            # same research content as first_full
        "changed": version(21, 10, revenue=1200.0),
        "latest": version(22, 10, revenue=1300.0),  # the live publication compares against "changed"
    }
    for snap in snaps.values():
        archive(snap, store)
    return snaps


def test_plan_removes_early_and_unchanged_versions_with_their_records(store):
    snaps = build(store)
    records = read(store)["records"]
    result = plan(records, store.branch)
    pruned = {v["id"]: v["reason"] for v in result["versions"]}
    assert pruned == {snaps["early"]["id"]: "early_pipeline_before_first_full_research",
                      snaps["early_again"]["id"]: "early_pipeline_before_first_full_research",
                      snaps["duplicate"]["id"]: "unchanged_vs_previous_kept"}
    kept_snapshots = {p for p in records if p.startswith("snapshots/") and p not in result["remove"]}
    assert kept_snapshots == {snapshot_path(snaps[k]["id"], "2330.TW") for k in ("first_full", "changed", "latest")}
    assert subject_path("2330.TW") not in result["remove"]
    assert result["records_after"] == len(records) - len(result["remove"])


def test_versions_the_live_publication_uses_are_never_pruned(store):
    snaps = build(store)
    repeat = version(22, 40, revenue=1300.0)  # same content as "latest", now the live version
    archive(repeat, store)
    pruned = {v["id"] for v in plan(read(store)["records"], store.branch)["versions"]}
    assert repeat["id"] not in pruned           # subject latest
    assert snaps["latest"]["id"] not in pruned  # the live publication's previous version


def test_apply_removes_exactly_the_approved_plan(store):
    build(store)
    approved = plan(read(store)["records"], store.branch)
    result = apply(store, approved["digest"])
    assert result["write"]["status"] == "archived"
    after = read(store)["records"]  # read() validates the remaining state
    assert not set(approved["remove"]) & after.keys()
    assert len(after) == approved["records_after"]
    files = git("ls-tree", "-r", "--name-only", f"origin/{store.branch}", cwd=store.repo).splitlines()
    assert not {f"research/{p}" for p in approved["remove"]} & set(files)
    # A later daily version still archives on top of the pruned state.
    archive(version(23, 10, revenue=1400.0), store)
    assert len([p for p in read(store)["records"] if p.startswith("snapshots/")]) == 4


def test_apply_refuses_a_digest_that_no_longer_matches(store):
    build(store)
    head = read(store)["head"]
    with pytest.raises(StateError, match="differs from the approved digest"):
        apply(store, "0" * 64)
    assert read(store)["head"] == head


def test_store_rejects_unlisted_or_unowned_removals(store):
    build(store)
    records = read(store)["records"]
    victim = next(p for p in records if p.startswith("snapshots/"))
    with pytest.raises(StateError, match="preserve all previously owned records"):
        store.commit("research", lambda r: {p: v for p, v in r.items() if p != victim})
    with pytest.raises(StateError, match="Removals must name owned records"):
        store.commit("research", lambda r: r, remove={"snapshots/tw/2330.TW/" + "f" * 64 + ".json"})
    with pytest.raises(StateError, match="Removals must name owned records"):
        store.commit("research", lambda r: copy.deepcopy(r), remove={victim})
