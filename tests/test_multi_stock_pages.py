"""#125: Pages lists 2317 / 2454 from today's report next to stored 2330 history."""
import copy
import json
import re

import pytest

from market_research.research_site import (
    _revenue_trend, build_site_payload, latest_only_records, render_research_site_html,
    write_research_site,
)
from scripts.daily_research import execute
from test_company_report_feedback import NOW, source_clock  # noqa: F401
from test_price_watch import watch_rows
from test_research_site import _make_full_financial_research, _sample_report
from test_scan_company_research import artifacts

FOUNDRY_ONLY = ("晶圓", "先進製程", "2nm", "A16", "N2", "Intel IFS", "HPC", "稼動率跌破")


def report(symbol="2330.TW", name="台積電", close=1085.0):
    r = _sample_report()
    r["symbol"] = symbol
    r["issuer"]["company_name"] = name
    r["technical"]["analytical_close"] = close
    r["financial_research"] = _make_full_financial_research()
    r["research_readiness"]["components"]["financial"]["status"] = "available"
    r["research_readiness"]["components"]["valuation"]["status"] = "illustrative_only"
    r["valuation"] = {"status": "illustrative_only", "provenance": "reconciled_tw_dual_track"}
    return r


def stored_2330():
    records, skipped = latest_only_records([report()])
    assert skipped == {}
    return records


def site_data(html):
    raw = re.search(r'<script id="site-data" type="application/json">(.*?)</script>', html, re.S).group(1)
    return json.loads(raw.replace("<\\/", "</"))


def test_latest_only_stocks_join_the_stored_history():
    extra, skipped = latest_only_records([report("2317.TW", "鴻海"), report("2454.TW", "聯發科")])
    assert skipped == {}
    payload = build_site_payload(stored_2330(), latest_only=extra)
    assert list(payload["stocks"]) == ["2317.TW", "2330.TW", "2454.TW"]
    assert payload["default_symbol"] == "2330.TW"
    hon_hai = payload["stocks"]["2317.TW"]
    assert hon_hai["latest_only"] is True and hon_hai["name"] == "鴻海"
    assert {c["status"] for c in hon_hai["comparisons"].values()} == {"latest_only"}
    assert "latest_only" not in payload["stocks"]["2330.TW"]


def test_a_stored_symbol_is_never_mixed_with_a_latest_only_copy():
    extra, _ = latest_only_records([report("2330.TW", "台積電", close=9999.0)])
    payload = build_site_payload(stored_2330(), latest_only=extra)
    stock = payload["stocks"]["2330.TW"]
    assert len(stock["snapshots"]) == 1 and "latest_only" not in stock


def test_a_report_that_cannot_be_snapshotted_is_skipped_with_its_reason():
    oversized = report("2317.TW", "鴻海")
    oversized["financial_research"]["quarterly_summary"] = (
        oversized["financial_research"]["quarterly_summary"] * 200)
    extra, skipped = latest_only_records([oversized, report("2454.TW", "聯發科")])
    assert list(skipped) == ["2317.TW"] and skipped["2317.TW"].startswith("SnapshotError")
    assert {v["symbol"] for v in extra.values()} == {"2454.TW"}


def test_picker_lists_every_stock_with_its_versions_and_a_toggle():
    extra, _ = latest_only_records([report("2317.TW", "鴻海")])
    html = render_research_site_html(stored_2330(), latest_only=extra)
    data = site_data(html)
    assert [(s["symbol"], s["latest_only"], len(s["snapshots"])) for s in data["stocks"]] == [
        ("2317.TW", True, 1), ("2330.TW", False, 1)]
    assert 'id="stock-toggle"' in html and 'aria-label="展開全部股票"' in html
    assert "'最新一版'" in html and "' 個版本'" in html
    assert "Issue #65" not in html
    view = data["views"]["2317.TW"][data["stocks"][0]["latest_snapshot_id"]]
    assert "只保留最新一版（未存歷史）" in view
    assert "未寫入；每日排程當次報告，只保留最新一版" in view


def test_other_stocks_never_show_the_foundry_narrative():
    extra, _ = latest_only_records([report("2317.TW", "鴻海")])
    data = site_data(render_research_site_html(stored_2330(), latest_only=extra))
    views = {s["symbol"]: data["views"][s["symbol"]][s["latest_snapshot_id"]] for s in data["stocks"]}
    for word in FOUNDRY_ONLY:
        assert word not in views["2317.TW"], word
    assert "晶圓代工屬於重資本支出行業" in views["2330.TW"]
    assert "外部與質性不確定性：產業景氣、主要客戶需求" in views["2317.TW"]


def test_valuation_ranges_come_from_each_stocks_own_scenarios():
    cheap = report("2317.TW", "鴻海")
    val = cheap["financial_research"]["valuation_summary"]
    for name, factor in (("fair_value_scenarios", 0.1), ("ttm_pe_scenarios", 0.1)):
        for scenario in val[name].values():
            for key in ("indicative_twd_per_share", "indicative_ttm_fcf_twd_per_share"):
                if key in scenario:
                    scenario[key] = round(scenario[key] * factor, 2)
    val["exchange_multiples"]["pe_ratio"] = 12.3
    extra, _ = latest_only_records([cheap])
    data = site_data(render_research_site_html(stored_2330(), latest_only=extra))
    views = {s["symbol"]: data["views"][s["symbol"]][s["latest_snapshot_id"]] for s in data["stocks"]}
    assert "（591–1,190 元）" in views["2330.TW"] and "（試算值 1,726–2,588 元）" in views["2330.TW"]
    assert "（59–119 元）" in views["2317.TW"] and "（試算值 173–259 元）" in views["2317.TW"]
    assert "證交所公告本益比 12.3 倍" in views["2317.TW"]
    assert "591–1,190" not in views["2317.TW"] and "27.9x" not in views["2317.TW"]
    assert "差距約 2.8 倍" in views["2317.TW"]  # 2,157 / 758.64 for both, scaled alike


def test_scenario_multiples_come_from_the_data():
    r = report("2317.TW", "鴻海")
    r["financial_research"]["valuation_summary"]["ttm_pe_scenarios"]["base"]["pe_multiple"] = 18.0
    extra, _ = latest_only_records([r])
    data = site_data(render_research_site_html(stored_2330(), latest_only=extra))
    view = data["views"]["2317.TW"][data["stocks"][0]["latest_snapshot_id"]]
    assert "P/FCF 20x<br>P/E 18x" in view


@pytest.mark.parametrize("annual, ytd, words", [
    (31.6, 35.6, "維持雙位數高速增長"), (8.0, 12.0, "維持成長"), (-3.0, -1.0, "較去年減少"),
    (5.0, -2.0, "增減方向不一致"), (None, None, "未提供可比較的年增率"), (12.0, None, "維持雙位數高速增長"),
])
def test_revenue_wording_follows_the_reported_changes(annual, ytd, words):
    assert words in _revenue_trend(annual, ytd)


def test_one_stocks_extra_close_never_lands_on_another():
    extra, _ = latest_only_records([report("2317.TW", "鴻海", close=251.5)])
    data = site_data(render_research_site_html(None, latest_report=report(close=2425.0), latest_only=extra))
    views = {s["symbol"]: data["views"][s["symbol"]][s["latest_snapshot_id"]] for s in data["stocks"]}
    assert "2,425.00 TWD" in views["2330.TW"]
    assert "2,425.00" not in views["2317.TW"]


def test_daily_run_adds_the_other_satellites_from_todays_reports(tmp_path):
    def research(symbol, out, now, **kwargs):
        if symbol == "2454.TW":
            raise TimeoutError("FinMind down")
        names = {"2330.TW": "台積電", "2317.TW": "鴻海"}
        return {**report(symbol, names[symbol]), "complete": True}

    def publish(mode, bootstrap, out, *, report, daily):
        out.mkdir(parents=True, exist_ok=True)
        records, _ = latest_only_records([report])
        (out / "research_state.json").write_text(json.dumps({"records": records}), encoding="utf-8")
        return {"publication": {"status": "published"}, "snapshot_id": "a" * 64,
                "state_branch": "research-state-validation"}

    result = execute(artifacts(tmp_path), tmp_path / "out", research_fn=research, publication_fn=publish,
                     now=NOW, price_watch_fn=watch_rows(), symbols=["2330.TW", "2317.TW", "2454.TW", "0050.TW"])
    assert result["watchlist_site"] == {"status": "rendered", "latest_only": ["2317.TW"], "skipped": {}}
    data = site_data((tmp_path / "out" / "fixed_research" / "index.html").read_text())
    assert [s["symbol"] for s in data["stocks"]] == ["2317.TW", "2330.TW"]
    assert data["default_symbol"] == "2330.TW"


def test_overview_close_comes_from_the_stored_twse_closes():
    r = report("2317.TW", "鴻海")
    r["technical"]["recent_closes"] = [{"date": "2026-10-16", "close": 250.0},
                                       {"date": "2026-10-19", "close": 251.5}]
    extra, _ = latest_only_records([r])
    data = site_data(render_research_site_html(stored_2330(), latest_only=extra))
    view = data["views"]["2317.TW"][data["stocks"][0]["latest_snapshot_id"]]
    assert "251.50 TWD <span class=\"hint\">TWSE 收盤價，2026-10-19</span>" in view
    assert "未保存收盤價" not in view.split('id="h-overview"')[1].split("</dl>")[0]
