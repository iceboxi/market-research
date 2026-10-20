"""Production entry rejects unauthorized context and implicit initialization."""
import pytest

from scripts.research_publication import execute
from scripts.state_store import StateError
from test_research_state import repo
from test_research_snapshot import report


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


def test_daily_schedule_cannot_initialize_production_authority(repo, tmp_path, monkeypatch):
    checkout, _, store = repo
    monkeypatch.chdir(checkout)
    context(monkeypatch)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", "owner/repo/.github/workflows/scan.yml@refs/heads/main")
    monkeypatch.setenv("SCAN_MARKET", "tw")
    monkeypatch.setenv("GITHUB_SHA", store.main_head())
    with pytest.raises(ValueError, match="Daily publication cannot initialize"):
        execute("production", True, tmp_path, report=report(), daily=True)
    assert store.read("research")["status"] == "uninitialized"


@pytest.mark.parametrize("key,value", [
    ("GITHUB_REF", "refs/heads/feature"), ("GITHUB_EVENT_NAME", "push"),
    ("GITHUB_WORKFLOW_REF", "owner/repo/.github/workflows/other.yml@refs/heads/main"),
    ("SCAN_MARKET", "us"),
])
def test_daily_publication_rejects_other_contexts_before_state_write(repo, tmp_path, monkeypatch, key, value):
    checkout, _, store = repo
    monkeypatch.chdir(checkout)
    context(monkeypatch)
    for name, actual in {"GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "schedule",
                         "GITHUB_WORKFLOW_REF": "owner/repo/.github/workflows/scan.yml@refs/heads/main",
                         "SCAN_MARKET": "tw", "GITHUB_SHA": store.main_head()}.items():
        monkeypatch.setenv(name, actual)
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match="explicit main TW scan runtime"):
        execute("production", False, tmp_path, report=report(), daily=True)
    assert store.read("research")["status"] == "uninitialized"


def test_precomputed_daily_report_uses_real_git_and_fresh_process_delivery(repo, tmp_path, monkeypatch):
    import json
    import os
    from pathlib import Path
    import sys
    import httpx
    from scripts.research_state import initialize, read, SUBJECT, snapshot_path
    checkout, _, store = repo
    initialize(store)
    code = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(checkout)
    context(monkeypatch)
    for key, value in {"GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "schedule",
                       "GITHUB_WORKFLOW_REF": "owner/repo/.github/workflows/scan.yml@refs/heads/main",
                       "SCAN_MARKET": "tw", "GITHUB_SHA": store.main_head(), "GITHUB_RUN_ATTEMPT": "1",
                       "PYTHONPATH": str(code) + os.pathsep + str(code / "src")}.items():
        monkeypatch.setenv(key, value)
    executable = tmp_path / "bin"
    executable.mkdir()
    # Independent gh process emulator; state survives fresh publisher processes.
    gh = executable / "gh"
    gh.write_text(f'''#!{sys.executable}
import json, sys
from pathlib import Path
file = Path({str(tmp_path / "external-issues.json")!r})
issues = json.loads(file.read_text()) if file.exists() else {{}}
args = sys.argv[1:]
method, endpoint = args[2], args[3]
if '--paginate' in args:
    result = [list(issues.values())]
elif method == 'POST':
    payload = json.load(sys.stdin)
    issues['900'] = dict(number=900, state='open', locked=False, **payload)
    result = issues['900']
elif method == 'PATCH':
    number = endpoint.rsplit('/', 1)[1]
    issues[number].update(json.load(sys.stdin))
    result = issues[number]
else:
    result = issues[endpoint.rsplit('/', 1)[1]]
file.write_text(json.dumps(issues))
print(json.dumps(result))
''')
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", str(executable) + os.pathsep + os.environ["PATH"])
    def forbidden(*args, **kwargs):
        raise AssertionError("Prepared report must not retrieve another source batch")
    monkeypatch.setattr(httpx.Client, "request", forbidden)
    out = tmp_path / "publication"
    receipt = execute("production", False, out, report=report(), daily=True)
    assert receipt["acceptance"] == "passed"
    assert receipt["entry"] == "daily_scan"
    assert receipt["publication"]["marker_matches"] == [900]
    records = read(store)["records"]
    owner = records[SUBJECT]
    assert owner["pending_publication_id"] is None
    assert records[snapshot_path(owner["latest_observation_id"])]["monthly_revenue"][0]["value"] == 1000
    assert (out / "comparison.md").read_text() in (out / "report.md").read_text()
    assert json.loads((tmp_path / "external-issues.json").read_text())["900"]["body"] == (out / "report.md").read_text()
