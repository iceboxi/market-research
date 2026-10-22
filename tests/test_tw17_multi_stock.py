"""TW17 Multi-stock research workflow, fault isolation, and model applicability tests."""
import json
from pathlib import Path
import pytest
import subprocess

from market_research.research_snapshot import prepare_snapshot, validate_snapshot
from market_research.research_site import write_research_site, _price_chart
from scripts.state_store import GitStateStore, StateError
from scripts.research_state import (
    archive, initialize, read, render_publication, validate_records,
    snapshot_path, publication_path, subject_path,
)
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
    initialize(store)
    return checkout, bare, store


def test_multi_stock_archive_coexistence_and_isolation(repo):
    checkout, bare, store = repo

    # 1. Prepare 2330.TW snapshot
    rep_2330 = report(stamp="2026-10-19T12:00:00+00:00")
    rep_2330["symbol"] = "2330.TW"
    rep_2330["issuer"]["company_name"] = "台灣積體電路製造"
    rep_2330["technical"]["recent_closes"] = [
        {"date": "2026-10-18", "close": 1050.0},
        {"date": "2026-10-19", "close": 1055.0},
    ]
    snap_2330_v1 = prepare_snapshot(rep_2330, identity(run_id="233001", stamp="2026-10-19T12:01:00+00:00"))
    archive(snap_2330_v1, store)

    # 2. Prepare 2303.TW snapshot (United Microelectronics Corporation)
    rep_2303 = report(stamp="2026-10-19T12:05:00+00:00")
    rep_2303["symbol"] = "2303.TW"
    rep_2303["issuer"]["company_name"] = "聯華電子"
    rep_2303["technical"]["recent_closes"] = [
        {"date": "2026-10-18", "close": 50.0},
        {"date": "2026-10-19", "close": 51.5},
    ]
    snap_2303_v1 = prepare_snapshot(rep_2303, identity(run_id="230301", stamp="2026-10-19T12:06:00+00:00"))
    archive(snap_2303_v1, store)

    state = read(store)
    records = state["records"]

    # Verify per-stock isolation in records
    assert snapshot_path(snap_2330_v1["id"], "2330.TW") in records
    assert snapshot_path(snap_2303_v1["id"], "2303.TW") in records
    assert subject_path("2330.TW") in records
    assert subject_path("2303.TW") in records

    subj_2330 = records[subject_path("2330.TW")]
    subj_2303 = records[subject_path("2303.TW")]

    assert subj_2330["symbol"] == "2330.TW"
    assert subj_2330["latest_observation_id"] == snap_2330_v1["id"]
    pub_2330_id = subj_2330["pending_publication_id"]
    assert pub_2330_id is not None
    pub_2330 = records[publication_path(pub_2330_id, "2330.TW")]
    assert pub_2330["symbol"] == "2330.TW"

    assert subj_2303["symbol"] == "2303.TW"
    assert subj_2303["latest_observation_id"] == snap_2303_v1["id"]
    pub_2303_id = subj_2303["pending_publication_id"]
    assert pub_2303_id is not None
    pub_2303 = records[publication_path(pub_2303_id, "2303.TW")]
    assert pub_2303["symbol"] == "2303.TW"

    # Verify publication rendered headers
    body_2330 = render_publication(records, pub_2330_id, store.branch)
    assert "# 2330 台積電研究" in body_2330
    assert "<!-- market-research:fixed-report:research-state:tw:2330.TW -->" in body_2330

    body_2303 = render_publication(records, pub_2303_id, store.branch)
    assert "# 2303.TW 聯華電子研究" in body_2303
    assert "<!-- market-research:fixed-report:research-state:tw:2303.TW -->" in body_2303

    # 3. Archive an updated snapshot for 2303.TW; ensure 2330.TW is untouched
    rep_2303_v2 = report(stamp="2026-10-20T12:00:00+00:00")
    rep_2303_v2["symbol"] = "2303.TW"
    rep_2303_v2["issuer"]["company_name"] = "聯華電子"
    rep_2303_v2["technical"]["recent_closes"] = [
        {"date": "2026-10-19", "close": 51.5},
        {"date": "2026-10-20", "close": 52.0},
    ]
    snap_2303_v2 = prepare_snapshot(rep_2303_v2, identity(run_id="230302", stamp="2026-10-20T12:01:00+00:00"))
    archive(snap_2303_v2, store)

    state_after = read(store)
    records_after = state_after["records"]

    # 2330 subject is identical
    assert records_after[subject_path("2330.TW")] == subj_2330
    # 2303 subject updated to new observation
    subj_2303_after = records_after[subject_path("2303.TW")]
    assert subj_2303_after["latest_observation_id"] == snap_2303_v2["id"]
    assert subj_2303_after["pending_publication_id"] != pub_2303_id
    # Old publication is superseded
    assert records_after[publication_path(pub_2303_id, "2303.TW")]["status"] == "superseded"


def test_financial_holding_model_applicability_and_site_rendering(repo, tmp_path):
    checkout, bare, store = repo

    # Financial holding company: 2881.TW (Fubon Financial Holding)
    rep_2881 = report(stamp="2026-10-19T12:00:00+00:00")
    rep_2881["symbol"] = "2881.TW"
    rep_2881["issuer"]["company_name"] = "富邦金控"
    rep_2881["research_readiness"]["components"]["valuation"] = {"status": "not_evaluated"}
    rep_2881["technical"]["recent_closes"] = [
        {"date": "2026-10-18", "close": 90.0},
        {"date": "2026-10-19", "close": 91.2},
    ]
    snap_2881 = prepare_snapshot(rep_2881, identity(run_id="288101", stamp="2026-10-19T12:01:00+00:00"))
    archive(snap_2881, store)

    state = read(store)
    validate_records(state["records"], store.branch)

    # Render site
    site_dir = tmp_path / "site"
    write_research_site(site_dir, state["records"], branch=store.branch)
    index_html = (site_dir / "index.html").read_text(encoding="utf-8")

    # Verify site has 2881.TW metadata and valuation inapplicability is clean
    assert "2881.TW" in index_html
    assert "富邦金控" in index_html
    assert "not_evaluated" in index_html


def test_batch_fault_isolation(repo):
    checkout, bare, store = repo

    candidates = ["2330.TW", "2454.TW", "2303.TW"]
    execution_results = {}

    for sym in candidates:
        try:
            if sym == "2454.TW":
                raise RuntimeError("Simulated API 500 error for failed candidate")
            rep = report(stamp="2026-10-19T12:00:00+00:00")
            rep["symbol"] = sym
            rep["issuer"]["company_name"] = f"Company {sym}"
            snap = prepare_snapshot(rep, identity(run_id="99901"))
            archive(snap, store)
            execution_results[sym] = "success"
        except Exception as exc:
            execution_results[sym] = f"failed: {type(exc).__name__}"

    assert execution_results["2330.TW"] == "success"
    assert execution_results["2454.TW"] == "failed: RuntimeError"
    assert execution_results["2303.TW"] == "success"

    # Store state is intact, containing both 2330.TW and 2303.TW, completely free of 2454.TW
    state = read(store)
    assert subject_path("2330.TW") in state["records"]
    assert subject_path("2303.TW") in state["records"]
    assert "subjects/tw/2454.TW.json" not in state["records"]


def test_recent_closes_price_chart_rendering():
    # 1. With closes
    closes = [
        {"date": f"2026-10-{i:02d}", "close": 100.0 + i} for i in range(1, 21)
    ]
    svg = _price_chart(closes, levels={"support_20d": 98.0, "resistance_20d": 125.0})
    assert svg is not None
    assert "<svg" in svg
    assert "<polyline" in svg
    assert "120.0" in svg  # Last close
    assert "前20日低 98" in svg
    assert "前20日高 125" in svg

    # 2. Empty closes returns empty string
    assert _price_chart([]) == ""
    assert _price_chart(None) == ""


def test_daily_research_pilot_batch_execution_and_shared_caching(tmp_path):
    from scripts.daily_research import execute
    from test_scan_company_research import artifacts
    from test_company_report_feedback import NOW

    folder = artifacts(tmp_path)
    out = tmp_path / "reports"

    requested_prices = []

    def mock_research(symbol, out, now, sec_user_agent):
        requested_prices.append(symbol)
        out.mkdir(parents=True, exist_ok=True)
        rep = report(stamp="2026-10-19T12:00:00+00:00")
        rep["symbol"] = symbol
        if symbol == "2881.TW":
            rep["issuer"]["company_name"] = "富邦金控"
            rep["research_readiness"]["components"]["valuation"] = {
                "status": "not_evaluated",
                "reason": "金融控股業不適用一般產業自由現金流估值",
            }
        elif symbol == "2303.TW":
            rep["issuer"]["company_name"] = "聯華電子"
        return rep

    result = execute(
        folder, out, research_fn=mock_research,
        publication_fn=lambda *a, **k: {
            "publication": {"status": "published", "issue_url": "https://example/74"},
            "snapshot_id": "s" * 64,
        },
        now=NOW, symbols=["2330.TW", "2303.TW", "2881.TW"],
    )

    assert result["status"] == "complete"
    assert requested_prices == ["2330.TW", "2303.TW", "2881.TW"]
    assert result["pilot_coverage"]["attempted_count"] == 3
    assert result["pilot_coverage"]["completed_count"] == 3
    assert result["pilot_coverage"]["failed_count"] == 0

    stocks = result["pilot_coverage"]["symbols"]
    assert stocks["2330.TW"]["status"] == "complete"
    assert stocks["2303.TW"]["status"] == "complete"
    assert stocks["2881.TW"]["status"] == "complete"
    assert stocks["2881.TW"]["readiness"]["valuation"]["status"] == "not_evaluated"

    # Check daily_summary.md table
    summary_md = (out / "daily_summary.md").read_text(encoding="utf-8")
    assert "2330.TW" in summary_md
    assert "2303.TW" in summary_md
    assert "2881.TW" in summary_md
    assert "not_evaluated (金融不適用)" in summary_md


def test_daily_research_pilot_fault_isolation(tmp_path):
    from scripts.daily_research import execute
    from test_scan_company_research import artifacts
    from test_company_report_feedback import NOW

    folder = artifacts(tmp_path)
    out = tmp_path / "reports"

    def mock_research(symbol, out, now, sec_user_agent):
        if symbol == "2454.TW":
            raise TimeoutError("TWSE network timeout for 2454.TW")
        rep = report(stamp="2026-10-19T12:00:00+00:00")
        rep["symbol"] = symbol
        return rep

    result = execute(
        folder, out, research_fn=mock_research,
        publication_fn=lambda *a, **k: {
            "publication": {"status": "published", "issue_url": "https://example/74"},
            "snapshot_id": "s" * 64,
        },
        now=NOW, symbols=["2330.TW", "2454.TW", "2303.TW"],
    )

    assert result["pilot_coverage"]["attempted_count"] == 3
    assert result["pilot_coverage"]["completed_count"] == 2
    assert result["pilot_coverage"]["failed_count"] == 1

    stocks = result["pilot_coverage"]["symbols"]
    assert stocks["2330.TW"]["status"] == "complete"
    assert stocks["2454.TW"]["status"] == "failed"
    assert stocks["2454.TW"]["error_type"] == "TimeoutError"
    assert stocks["2303.TW"]["status"] == "complete"

    summary_md = (out / "daily_summary.md").read_text(encoding="utf-8")
    assert "失敗 1" in summary_md
    assert "2454.TW" in summary_md

