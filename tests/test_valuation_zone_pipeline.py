"""#114: the review zone travels from FinMind PER to report, daily summary and Pages."""
import json
from datetime import timedelta

import pytest

from market_research.fundamentals import FINMIND_URL, TW_PROFILE, TW_REVENUE, twse_fundamentals
from market_research.research_site import render_research_site_html
from market_research.valuation_zone import evaluate_valuation_zone
from scripts import company_report
from scripts.company_report import run
from scripts.daily_research import execute
from test_company_report_feedback import NOW, Prices, facts_get, source_clock  # noqa: F401
from test_daily_research import delivered
from test_research_site import _make_full_financial_research, _sample_report
from test_scan_company_research import artifacts
from test_valuation_zone import per_rows, uniform

PER_URL = f"{FINMIND_URL}?dataset=TaiwanStockPER&data_id=2330&start_date=2021-10-19"
CUTOFF = NOW.date()


def official(url):
    if url == TW_PROFILE:
        return [{"公司代號": "2330", "公司名稱": "台積電", "產業別": "24", "出表日期": "1151019"}]
    if url == TW_REVENUE:
        return []
    raise ValueError(f"fixture has no {url}")


def test_fundamentals_fetch_five_years_of_per_for_the_cutoff():
    rows = per_rows([15.0] * 3, end=CUTOFF)
    def fin_get(url):
        if url == PER_URL:
            return {"status": 200, "msg": "success", "data": rows}
        raise ValueError(f"fixture has no {url}")
    issuer = twse_fundamentals("2330.TW", official, financial_get=fin_get, asof=CUTOFF)
    assert issuer["per_history_raw"] == {"source": PER_URL, "rows": rows}


@pytest.mark.parametrize("answer", [ValueError("down"), {"status": 402, "msg": "quota", "data": []}])
def test_per_source_failure_is_a_warning_not_an_empty_history(answer):
    def fin_get(url):
        if url == PER_URL and isinstance(answer, dict):
            return answer
        raise ValueError(f"fixture has no {url}")
    issuer = twse_fundamentals("2330.TW", official, financial_get=fin_get, asof=CUTOFF)
    assert "per_history_raw" not in issuer
    assert any("FinMind TaiwanStockPER unavailable" in w for w in issuer["warnings"])


def zone_inputs(symbol):
    def fundamentals(requested, **kwargs):
        assert requested == symbol and kwargs["asof"] == CUTOFF
        return {
            "symbol": symbol, "market": "tw", "company_name": "Fixture", "industry_code": "24",
            "profile": {"source": TW_PROFILE, "reported_at": "1151019"}, "facts": [], "warnings": [],
            "financial_history": {"currency": "TWD", "period_type": "tw_ifrs_reconciled",
                                  "source": "fixture", "ttm": {
                                      "status": "available", "basic_eps": 5.0,
                                      "period_start": "2025-07-01", "period_end": "2026-06-30",
                                      "quarters": ["2025Q3", "2025Q4", "2026Q1", "2026Q2"],
                                      "eps_derivation": "sum_of_four_quarters_within_0.5pct_share_drift"}},
            "per_history_raw": {"source": PER_URL, "rows": per_rows(uniform(), code=symbol[:4], end=CUTOFF)},
        }
    return fundamentals


def test_satellite_report_carries_review_zone_without_raw_per_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(company_report, "twse_fundamentals", zone_inputs("2330.TW"))
    result = run("2330.TW", out=tmp_path, now=NOW, provider=Prices(), facts_get=facts_get,
                 clock=lambda: NOW)
    zone = result["valuation_zone"]
    # Close 100 against 12/15/18 x EPS 5 = 60/75/90.
    assert zone["status"] == "available" and zone["zone"] == "above_high"
    assert zone["review_prices_twd"] == {"low": 60.0, "mid": 75.0, "high": 90.0}
    assert zone["price"] == {"close": 100.0, "session": "2026-10-19", "source": "fixture_daily"}
    assert "per_history_raw" not in result["issuer"]
    stored = json.loads((tmp_path / "report.json").read_text())
    assert stored["valuation_zone"] == zone
    assert "per_history_raw" not in json.dumps(stored)
    report = (tmp_path / "report.md").read_text()
    assert "## 估值檢視區（歷史本益比）" in report
    assert "檢視區，非買賣建議" in report
    assert "| 60.00 | 75.00 | 90.00 | 高於偏高價 |" in report


def test_model_identity_includes_the_satellite_setting(tmp_path, monkeypatch):
    monkeypatch.setattr(company_report, "twse_fundamentals", zone_inputs("2330.TW"))
    first = run("2330.TW", out=tmp_path / "a", now=NOW, provider=Prices(), facts_get=facts_get,
                clock=lambda: NOW)
    config = tmp_path / "config"
    config.mkdir()
    for name in ("markets.yaml", "strategies.yaml"):
        (config / name).write_text((company_report.ROOT / "config" / name).read_text())
    (config / "watchlist.yaml").write_text(
        "satellites:\n  2330.TW:\n    valuation_zone:\n      percentiles: [10, 50, 90]\n")
    second = run("2330.TW", out=tmp_path / "b", now=NOW, provider=Prices(), facts_get=facts_get,
                 clock=lambda: NOW, config_dir=config)
    assert second["valuation_zone"]["pe_band"] == {"low": 11.0, "mid": 15.0, "high": 19.0}
    assert first["model_identity"] != second["model_identity"]


def test_daily_summary_lists_satellite_zones_and_skips_etfs(tmp_path):
    zone = evaluate_valuation_zone(
        "2330.TW", CUTOFF, {"thesis": None, "valuation_zone": {"percentiles": (20, 50, 80)}},
        {"source": PER_URL, "rows": per_rows(uniform(), end=CUTOFF)},
        {"status": "available", "basic_eps": 5.0, "period_start": "2025-07-01",
         "period_end": "2026-06-30", "quarters": ["2025Q3", "2025Q4", "2026Q1", "2026Q2"]},
        {"close": 70.0, "session": "2026-10-19", "source": "fixture"})
    blocked = dict(zone, status="not_evaluated", zone="not_evaluated", review_prices_twd=None,
                   reason="TTM EPS is not positive; a P/E band is undefined")

    def research(symbol, out, now, **kwargs):
        return {"complete": True, "technical": {"last_session": "2026-10-19"},
                "issuer": {"company_name": symbol}, "research_readiness": {"components": {}},
                "valuation_zone": zone if symbol == "2330.TW" else blocked}

    result = execute(artifacts(tmp_path), tmp_path / "out", research_fn=research,
                     publication_fn=delivered, now=NOW,
                     symbols=["2330.TW", "2317.TW", "0050.TW"])
    symbols = result["pilot_coverage"]["symbols"]
    assert symbols["2330.TW"]["valuation_zone"]["zone"] == "fair"
    assert "valuation_zone" not in symbols["0050.TW"]
    summary = (tmp_path / "out" / "daily_summary.md").read_text()
    assert "### 衛星個股估值檢視區（檢視區，非買賣建議）" in summary
    first = CUTOFF - timedelta(days=1000)
    assert ("| 2330.TW | 70.00（2026-10-19） | 60.00 | 75.00 | 90.00 | 合理區間 "
            f"| 2025Q3–2026Q2 EPS 5.00 | 1001 筆（{first}～2026-10-19） |") in summary
    assert ("| 2317.TW | 70.00（2026-10-19） | — | — | — "
            "| not_evaluated：TTM EPS is not positive; a P/E band is undefined |") in summary
    assert "| 0050.TW |" not in summary.split("### 衛星個股估值檢視區")[1]


def test_pages_valuation_section_shows_the_review_zone():
    report = _sample_report()
    fr = _make_full_financial_research()
    fr["valuation_zone"] = evaluate_valuation_zone(
        "2330.TW", CUTOFF, {"thesis": None, "valuation_zone": {"percentiles": (20, 50, 80)}},
        {"source": PER_URL, "rows": per_rows(uniform(), end=CUTOFF)},
        {"status": "available", "basic_eps": 100.0, "period_start": "2025-07-01",
         "period_end": "2026-06-30", "quarters": ["2025Q3", "2025Q4", "2026Q1", "2026Q2"]},
        {"close": 1085.0, "session": "2026-10-19", "source": "fixture"})
    report["financial_research"] = fr
    html = render_research_site_html(latest_report=report)
    assert "估值檢視區（歷史本益比）" in html
    assert "檢視區，非買賣建議" in html
    assert "1,200.00" in html and "1,500.00" in html and "1,800.00" in html
    assert "低於偏低價" in html
    assert "TaiwanStockPER" in html


def full_zone():
    return evaluate_valuation_zone(
        "2330.TW", CUTOFF, {"thesis": None, "valuation_zone": {"percentiles": (20, 50, 80)}},
        {"source": PER_URL, "rows": per_rows(uniform(), end=CUTOFF)},
        {"status": "available", "basic_eps": 86.28, "period_start": "2025-07-01",
         "period_end": "2026-06-30", "quarters": ["2025Q3", "2025Q4", "2026Q1", "2026Q2"],
         "eps_derivation": "sum_of_four_quarters_within_0.5pct_share_drift"},
        {"close": 2425.0, "session": "2026-10-19", "source": "twse_stock_day_official_raw_ohlcv"})


def test_public_snapshot_keeps_a_compact_zone_within_the_size_budget():
    # research-state 2330 snapshots were ~18,820 of 20,000 canonical bytes before #114;
    # the full zone (~1.2 kB) overflowed the budget in PR CI.
    from market_research.research_snapshot import _compact_financial_research, encoded
    fr = _make_full_financial_research()
    fr["valuation_zone"] = full_zone()
    compact = _compact_financial_research(fr)["valuation_zone"]
    assert len(encoded(compact)) <= 600
    for verbose in ("assumptions", "disclaimer", "cutoff"):
        assert verbose not in compact
    assert "source" not in compact["per_history"] and "source" not in compact["price"]
    assert compact["review_prices_twd"] == full_zone()["review_prices_twd"]
    assert compact["per_history"]["window_start"] == "2021-10-19"


def test_pages_renders_the_compact_snapshot_zone_with_rebuilt_source():
    report = _sample_report()
    report["financial_research"] = _make_full_financial_research()
    report["financial_research"]["valuation_zone"] = full_zone()
    html = render_research_site_html(latest_report=report)
    assert "檢視區，非買賣建議" in html
    assert PER_URL.replace("&", "&amp;") in html
    assert "1,294.20" in html
