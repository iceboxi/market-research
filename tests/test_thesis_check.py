"""#115: satellite thesis check from monthly revenue and same-day announcements."""
from datetime import date
import json
from pathlib import Path

import pytest
import yaml

from market_research.event_risk import TW_MATERIAL_URL
from market_research.fundamentals import FINMIND_URL, twse_fundamentals
from market_research.research_site import render_research_site_html
from market_research.thesis_check import (
    DEFAULT_RULE, evaluate_announcements, evaluate_revenue_trend, evaluate_thesis,
)
from market_research.valuation_zone import load_watchlist
from scripts import company_report
from scripts.company_report import run
from scripts.daily_research import execute
from test_company_report_feedback import NOW, Prices, facts_get, source_clock  # noqa: F401
from test_daily_research import delivered
from test_price_watch import watch_rows
from test_research_site import _sample_report
from test_scan_company_research import artifacts
from test_valuation_zone import write_config
from test_valuation_zone_pipeline import official, zone_inputs

ROOT = Path(__file__).resolve().parents[1]
CUTOFF = date(2026, 10, 29)
REVENUE_URL = f"{FINMIND_URL}?dataset=TaiwanStockMonthRevenue&data_id=2317&start_date=2023-10-01"


def revenue_rows(yoy_by_month, code="2317", first=(2024, 1), last=(2026, 9), created=True):
    """Monthly rows from `first` to `last`; 2024 = 100 each month, later years follow `yoy`.

    `yoy_by_month` maps "YYYY-MM" to that month's year-over-year growth (default +10%).
    """
    rows, level = [], {}
    year, month = first
    while (year, month) <= last:
        key = f"{year}-{month:02d}"
        base = level.get((year - 1, month))
        revenue = 100e8 if base is None else base * (1 + yoy_by_month.get(key, 0.10))
        level[(year, month)] = revenue
        published = f"{year + (month == 12)}-{month % 12 + 1:02d}-07"
        rows.append({"date": f"{year + (month == 12)}-{month % 12 + 1:02d}-01", "stock_id": code,
                     "country": "Taiwan", "revenue": round(revenue), "revenue_month": month,
                     "revenue_year": year, "create_time": published if created else ""})
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return rows


def history(rows):
    return {"source": REVENUE_URL, "rows": rows}


# ---------------------------------------------------------------- revenue rule

def test_growing_revenue_is_ok_with_the_three_latest_public_months():
    check = evaluate_revenue_trend("2317.TW", CUTOFF, DEFAULT_RULE, history(revenue_rows({})))
    assert check["status"] == "ok" and check["reason"] is None
    assert [m["period"] for m in check["months"]] == ["2026-07", "2026-08", "2026-09"]
    assert all(m["yoy_pct"] == 10.0 for m in check["months"])
    assert check["months"][-1]["published"] == "2026-10-07"
    assert check["source"] == REVENUE_URL


def test_three_negative_months_ask_for_review():
    rows = revenue_rows({"2026-07": -0.01, "2026-08": -0.05, "2026-09": -0.005})
    check = evaluate_revenue_trend("2317.TW", CUTOFF, DEFAULT_RULE, history(rows))
    assert check["status"] == "review"
    assert check["reason"] == "月營收年增率連續 3 個月低於 0%"
    assert [m["yoy_pct"] for m in check["months"]] == [-1.0, -5.0, -0.5]


@pytest.mark.parametrize("yoy", [
    {"2026-07": -0.01, "2026-08": 0.0, "2026-09": -0.02},   # exactly 0 is not below 0
    {"2026-07": -0.01, "2026-08": -0.02, "2026-09": 0.01},  # the latest month recovered
])
def test_any_month_at_or_above_threshold_is_ok(yoy):
    assert evaluate_revenue_trend("2317.TW", CUTOFF, DEFAULT_RULE,
                                  history(revenue_rows(yoy)))["status"] == "ok"


def test_rule_months_and_threshold_come_from_settings():
    rows = revenue_rows({"2026-08": 0.03, "2026-09": 0.04})
    rule = {"consecutive_months": 2, "yoy_below_pct": 5.0}
    check = evaluate_revenue_trend("2317.TW", CUTOFF, rule, history(rows))
    assert check["status"] == "review" and check["reason"] == "月營收年增率連續 2 個月低於 5%"
    assert [m["period"] for m in check["months"]] == ["2026-08", "2026-09"]


def test_missing_month_or_prior_year_is_not_evaluated():
    rows = [r for r in revenue_rows({}) if (r["revenue_year"], r["revenue_month"]) != (2026, 8)]
    check = evaluate_revenue_trend("2317.TW", CUTOFF, DEFAULT_RULE, history(rows))
    assert check["status"] == "not_evaluated" and check["reason"] == "缺月營收：2026-08"
    rows = [r for r in revenue_rows({}) if (r["revenue_year"], r["revenue_month"]) != (2025, 7)]
    check = evaluate_revenue_trend("2317.TW", CUTOFF, DEFAULT_RULE, history(rows))
    assert check["reason"] == "缺月營收：2025-07"


def test_lagging_source_cannot_pass_as_ok():
    # After 10/10 every company has published September; data ending in August is stale.
    rows = revenue_rows({}, last=(2026, 8))
    check = evaluate_revenue_trend("2317.TW", CUTOFF, DEFAULT_RULE, history(rows))
    assert check["status"] == "not_evaluated" and check["reason"] == "缺月營收：2026-09"


def test_months_published_after_the_cutoff_are_never_read():
    rows = revenue_rows({"2026-09": -0.5})  # September published 2026-10-07
    before = evaluate_revenue_trend("2317.TW", date(2026, 10, 6), DEFAULT_RULE, history(rows))
    assert [m["period"] for m in before["months"]] == ["2026-06", "2026-07", "2026-08"]
    assert before["status"] == "ok"
    after = evaluate_revenue_trend("2317.TW", date(2026, 10, 7), DEFAULT_RULE, history(rows))
    assert after["months"][-1]["period"] == "2026-09" and after["months"][-1]["yoy_pct"] == -50.0


def test_rows_without_publication_time_wait_for_the_statutory_deadline():
    rows = revenue_rows({}, created=False)
    on_ninth = evaluate_revenue_trend("2317.TW", date(2026, 10, 9), DEFAULT_RULE, history(rows))
    assert on_ninth["months"][-1]["period"] == "2026-08"
    on_tenth = evaluate_revenue_trend("2317.TW", date(2026, 10, 10), DEFAULT_RULE, history(rows))
    assert on_tenth["months"][-1]["period"] == "2026-09"
    assert on_tenth["months"][-1]["published"] is None


@pytest.mark.parametrize("source, reason", [
    (None, "FinMind TaiwanStockMonthRevenue 無法取得"),
    (history(revenue_rows({}, code="2330")), "foreign stock_id 2330 in TaiwanStockMonthRevenue"),
    (history(revenue_rows({}) + [dict(revenue_rows({})[-1], revenue=1)]),
     "conflicting duplicate TaiwanStockMonthRevenue rows for 2026-09"),
])
def test_source_failure_or_bad_rows_are_not_evaluated(source, reason):
    check = evaluate_revenue_trend("2317.TW", CUTOFF, DEFAULT_RULE, source)
    assert check["status"] == "not_evaluated" and check["reason"] == reason


# ---------------------------------------------------------------- announcements

def feed(events, status="available"):
    return {"source": TW_MATERIAL_URL, "status": status, "snapshot_date": "2026-10-29",
            "events": [{"event_id": f"tw-material-{i}", "title": title, "published_at": published}
                       for i, (title, published) in enumerate(events)]}


def test_same_day_announcement_asks_for_review_with_subject_and_link():
    check = evaluate_announcements(feed([
        ("董事會決議資本支出", "2026-10-29T17:30:00+08:00"),
        ("昨日公告", "2026-10-28T19:00:00+08:00")]), CUTOFF)
    assert check["status"] == "review" and check["reason"] == "當日重大公告 1 則"
    assert check["items"] == [{"title": "董事會決議資本支出", "published_at": "2026-10-29T17:30:00+08:00"}]
    assert check["link"] == "https://mops.twse.com.tw/mops/web/t05st01"
    assert check["source"] == TW_MATERIAL_URL


@pytest.mark.parametrize("snapshot, status, reason", [
    (feed([("昨日公告", "2026-10-28T19:00:00+08:00")]), "ok", None),
    (feed([], status="partial"), "not_evaluated", "部分重大訊息列無法解析，無法確認當日沒有公告"),
    ({"status": "unavailable", "reason": "TWSE events unavailable: ConnectError"}, "not_evaluated",
     "TWSE 重大訊息無法取得：TWSE events unavailable: ConnectError"),
    (None, "not_evaluated", "TWSE 重大訊息無法取得：unknown"),
])
def test_no_announcement_is_ok_only_with_a_complete_snapshot(snapshot, status, reason):
    check = evaluate_announcements(snapshot, CUTOFF)
    assert (check["status"], check["reason"]) == (status, reason)


def test_review_outranks_not_evaluated_which_outranks_ok():
    settings = {"thesis": "AI 伺服器組裝", "revenue_check": DEFAULT_RULE}
    falling = history(revenue_rows({"2026-07": -0.1, "2026-08": -0.1, "2026-09": -0.1}))
    review = evaluate_thesis("2317.TW", CUTOFF, settings, falling, None)
    assert review["status"] == "review" and review["reason"] == "月營收年增率連續 3 個月低於 0%"
    assert review["thesis"] == "AI 伺服器組裝"
    unknown = evaluate_thesis("2317.TW", CUTOFF, settings, history(revenue_rows({})), None)
    assert unknown["status"] == "not_evaluated"
    assert unknown["reason"] == "TWSE 重大訊息無法取得：unknown"
    ok = evaluate_thesis("2317.TW", CUTOFF, settings, history(revenue_rows({})), feed([]))
    assert ok["status"] == "ok" and ok["reason"] is None
    outside = evaluate_thesis("2317.TW", CUTOFF, None, history(revenue_rows({})), feed([]))
    assert outside["status"] == "not_evaluated" and outside["revenue"] is None


# ---------------------------------------------------------------- configuration

def test_revenue_rule_defaults_and_overrides(tmp_path):
    config = write_config(tmp_path, "satellites:\n  2317.TW:\n    revenue_check:\n"
                          "      consecutive_months: 6\n      yoy_below_pct: -5\n  2330.TW:\n")
    watchlist = load_watchlist(config)
    assert watchlist["2317.TW"]["revenue_check"] == {"consecutive_months": 6, "yoy_below_pct": -5.0}
    assert watchlist["2330.TW"]["revenue_check"] == DEFAULT_RULE


@pytest.mark.parametrize("body, message", [
    ("    revenue_check:\n      months: 3\n", "unknown revenue_check keys"),
    ("    revenue_check:\n      consecutive_months: 0\n", "from 1 to 12"),
    ("    revenue_check:\n      consecutive_months: 13\n", "from 1 to 12"),
    ("    revenue_check:\n      consecutive_months: true\n", "from 1 to 12"),
    ("    revenue_check:\n      yoy_below_pct: low\n", "yoy_below_pct must be a number"),
])
def test_invalid_revenue_rule_is_rejected(tmp_path, body, message):
    config = write_config(tmp_path, "satellites:\n  2317.TW:\n" + body)
    with pytest.raises(ValueError, match=message):
        load_watchlist(config)


def test_all_three_satellites_are_in_the_announcement_watch():
    events = yaml.safe_load((ROOT / "config/event_watchlist.yaml").read_text(encoding="utf-8"))
    watched = {(item["market"], item["symbol"]) for item in events["symbols"]}
    satellites = load_watchlist(ROOT / "config")
    assert {("tw", symbol) for symbol in satellites} <= watched
    assert set(satellites) == {"2330.TW", "2317.TW", "2454.TW", "2356.TW", "3017.TW"}


# ---------------------------------------------------------------- pipeline

def test_fundamentals_fetch_three_years_of_monthly_revenue():
    url = f"{FINMIND_URL}?dataset=TaiwanStockMonthRevenue&data_id=2330&start_date=2023-10-01"
    rows = revenue_rows({}, code="2330")
    def fin_get(requested):
        if requested == url:
            return {"status": 200, "msg": "success", "data": rows}
        raise ValueError(f"fixture has no {requested}")
    issuer = twse_fundamentals("2330.TW", official, financial_get=fin_get, asof=NOW.date())
    assert issuer["revenue_history_raw"] == {"source": url, "rows": rows}
    def down(requested):
        raise ValueError("down")
    issuer = twse_fundamentals("2330.TW", official, financial_get=down, asof=NOW.date())
    assert "revenue_history_raw" not in issuer
    assert any("FinMind TaiwanStockMonthRevenue unavailable" in w for w in issuer["warnings"])


def test_report_shows_thesis_status_and_basis_without_raw_rows(tmp_path, monkeypatch):
    def fundamentals(requested, **kwargs):
        issuer = zone_inputs("2330.TW")(requested, **kwargs)
        issuer["revenue_history_raw"] = {"source": "https://example.test/revenue", "rows": revenue_rows(
            {"2026-07": -0.2, "2026-08": -0.2, "2026-09": -0.2}, code="2330")}
        return issuer
    monkeypatch.setattr(company_report, "twse_fundamentals", fundamentals)
    result = run("2330.TW", out=tmp_path, now=NOW, provider=Prices(), facts_get=facts_get,
                 clock=lambda: NOW)
    check = result["thesis_check"]
    assert [m["period"] for m in check["revenue"]["months"]] == ["2026-07", "2026-08", "2026-09"]
    assert check["announcements"]["items"] == [{"title": "Known fixture disclosure",
                                                "published_at": "2026-10-19T10:00:00+08:00"}]
    assert check["status"] == "review"
    assert check["reason"] == "月營收年增率連續 3 個月低於 0%；當日重大公告 1 則"
    assert "revenue_history_raw" not in json.dumps(json.loads((tmp_path / "report.json").read_text()))
    report = (tmp_path / "report.md").read_text()
    assert "## 論點檢查" in report and "請檢視，非買賣建議" in report
    assert "- 狀態：請檢視（review）：月營收年增率連續 3 個月低於 0%；當日重大公告 1 則" in report
    assert "| 2026-09 | 88.00 | 110.00 | -20.00% | 2026-10-07 |" in report
    assert "- 2026-10-19T10:00:00+08:00：Known fixture disclosure" in report


def test_daily_summary_and_pages_show_the_thesis_column(tmp_path):
    check = evaluate_thesis("2317.TW", CUTOFF, {"thesis": None, "revenue_check": DEFAULT_RULE},
                            history(revenue_rows({"2026-07": -0.1, "2026-08": -0.1, "2026-09": -0.1})),
                            feed([]))

    def research(symbol, out, now, **kwargs):
        return {"complete": True, "technical": {"last_session": "2026-10-19"},
                "issuer": {"company_name": symbol}, "research_readiness": {"components": {}},
                "thesis_check": check if symbol == "2317.TW" else evaluate_thesis(
                    symbol, CUTOFF, None, None, None)}

    result = execute(artifacts(tmp_path), tmp_path / "out", research_fn=research,
                     publication_fn=delivered, now=NOW, price_watch_fn=watch_rows(),
                     symbols=["2330.TW", "2317.TW"])
    assert result["pilot_coverage"]["symbols"]["2317.TW"]["thesis_check"]["status"] == "review"
    summary = (tmp_path / "out" / "daily_summary.md").read_text()
    assert "### 衛星個股論點檢查（請檢視，非買賣建議）" in summary
    assert ("| 2317.TW | 請檢視 | 2026-07 -10.00% / 2026-08 -10.00% / 2026-09 -10.00% | 0 則 "
            "| 月營收年增率連續 3 個月低於 0% |") in summary
    assert "| 2330.TW | 未評估" not in summary  # not a satellite in this fixture: no row

    html = render_research_site_html(latest_report=_sample_report(), watchlist={
        "price_watch": [], "valuation_zones": {}, "thesis_checks": {"2317.TW": check},
        "names": {"2317.TW": "鴻海"}})
    overview = html[html.index('<section id="watchlist"'):html.index("</section>")]
    assert "<th scope=\"col\">論點檢查</th>" in overview
    assert "請檢視<span class=\"unit\">月營收年增率連續 3 個月低於 0%</span>" in overview
