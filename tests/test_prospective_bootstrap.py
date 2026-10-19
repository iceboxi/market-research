"""A bootstrap is a deliberate control-plane action, not a scan side effect."""
from contextlib import chdir
import json
from pathlib import Path
import subprocess
import pytest

from scripts.prospective_bootstrap import bootstrap
from scripts.state_store import StateError


def test_migration_not_executable_on_pr_or_without_paused_scan(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_REPOSITORY", "iceboxi/market-research")
    monkeypatch.setenv("GITHUB_SHA", "a"*40)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/feature")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    with pytest.raises(StateError, match="main workflow_dispatch"):
        bootstrap(tmp_path / "blocked")
    assert json.loads((tmp_path / "blocked/receipt.json").read_text())["status"] == "failed"

    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setattr("scripts.prospective_bootstrap._gh_api",
                        lambda path, jq=None: json.dumps({"state": "active"}) if not jq else "")
    with pytest.raises(StateError, match="manually disabled"):
        bootstrap(tmp_path / "still_active")


def test_pending_legacy_jobs_block_before_git_write(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_REPOSITORY", "iceboxi/market-research")
    monkeypatch.setenv("GITHUB_SHA", "a"*40)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    def control(path, jq=None):
        return "7788" if jq else json.dumps({"state":"disabled_manually"})
    monkeypatch.setattr("scripts.prospective_bootstrap._gh_api", control)
    with pytest.raises(StateError, match="unfinished runs"):
        bootstrap(tmp_path / "pending")
    data = json.loads((tmp_path / "pending/receipt.json").read_text())
    assert data["stage"] == "writer_quiescence"
    assert data["migration"] is None
