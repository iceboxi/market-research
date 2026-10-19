"""Production entry rejects unauthorized context and implicit initialization."""
import pytest

from scripts.research_publication import execute
from scripts.state_store import StateError
from test_research_state import repo


def context(monkeypatch):
    for key, value in {"GITHUB_REPOSITORY": "owner/repo", "GITHUB_RUN_ID": "100",
                       "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/feature"}.items():
        monkeypatch.setenv(key, value)


def test_production_requires_main_dispatch(repo, tmp_path, monkeypatch):
    checkout, _, _ = repo
    monkeypatch.chdir(checkout)
    context(monkeypatch)
    with pytest.raises(ValueError, match="explicit main dispatch"):
        execute("production", True, tmp_path)


def test_normal_production_write_does_not_implicitly_initialize(repo, tmp_path, monkeypatch):
    checkout, _, store = repo
    monkeypatch.chdir(checkout)
    context(monkeypatch)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_SHA", store.main_head())
    with pytest.raises(StateError, match="explicit initialization"):
        execute("production", False, tmp_path)
    assert store.read("research")["status"] == "uninitialized"
