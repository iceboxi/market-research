"""#126: the 新手 section — health check, five questions and the P/E calculator."""
import json
import re

from market_research.beginner_view import (
    calc_diff, checklist, chg, facts, hbars, p_calc, render_beginner,
)
from market_research.research_site import latest_only_records, render_research_site_html
from test_multi_stock_pages import report, site_data, stored_2330
from test_valuation_zone_pipeline import full_zone


def snapshot_of(r):
    records, skipped = latest_only_records([r])
    assert skipped == {}
    return next(v for path, v in records.items() if path.startswith("snapshots/"))


STOCK = {"name": "台積電"}


def with_year_ago_quarter(r, revenue_factor, margin_delta):
    fr = r["financial_research"]
    latest = fr["quarterly_summary"][-1]
    year_ago = {**latest, "period_label": "2025Q2", "period_end": "2025-06-30",
                "revenue": latest["revenue"] * revenue_factor,
                "gross_margin_pct": latest["gross_margin_pct"] + margin_delta}
    fr["quarterly_summary"] = [year_ago, *fr["quarterly_summary"]]
    return r


def test_health_check_matches_the_reported_numbers():
    # Year-ago revenue 80% of today's (grew) and margin 2 points higher (fell).
    r = with_year_ago_quarter(report(), 0.8, 2.0)
    fr = r["financial_research"]
    items = {label: ok for label, ok, _ in checklist(facts(snapshot_of(r), STOCK))}
    assert items == {
        "近四季有賺錢": fr["ttm"]["basic_eps"] > 0,
        "營收比去年同季成長": True,
        "毛利率比去年同季高": False,
        "近四季自由現金流為正": fr["ttm"]["free_cash_flow"] > 0,
        "現金比借款多": fr["latest_balance_sheet"]["net_cash"] > 0,
    }
    single = {label: ok for label, ok, _ in checklist(facts(snapshot_of(report()), STOCK))}
    assert single["營收比去年同季成長"] is None and single["毛利率比去年同季高"] is None  # 資料不足, not ✗


def test_missing_financials_collapse_to_one_line_each():
    r = report()
    r["financial_research"] = None
    r["research_readiness"]["components"]["financial"]["status"] = "unavailable"
    html = render_beginner(snapshot_of(r), STOCK)
    assert "資料不足，這個版本無法檢查。" in html
    assert html.count("這個版本沒有財報資料。") == 2  # questions 1 and 2
    questions = html.split("問題 1", 1)[1]
    assert questions.count("<svg") == 0 and "<figure" not in questions  # no empty chart boxes
    assert "無法判斷" in html


def test_financial_or_special_industries_are_not_checked():
    r = report()
    r["research_readiness"]["components"]["instrument"] = {"status": "inapplicable"}
    F = facts(snapshot_of(r), STOCK)
    assert F["instrument"] == "inapplicable"
    assert checklist(F) is None
    assert "一般產業的體質條件不適用" in render_beginner(snapshot_of(r), STOCK)


def test_price_line_uses_the_review_zone_when_present():
    r = report()
    r["financial_research"]["valuation_zone"] = full_zone()
    html = render_beginner(snapshot_of(r), STOCK)
    prices = full_zone()["review_prices_twd"]
    assert "和自己過去 5 年的本益比相比" in html
    assert f'{prices["low"]:,.2f}'.rstrip("0").rstrip(".") in html
    assert "檢視區，非買賣建議" in html and "無法判斷" not in html


def test_calculator_multiplies_the_readers_multiple_by_ttm_eps():
    F = {"closes": [("2026-10-28", 2425.0)], "ttm": {"basic_eps": 86.28, "quarters": ["2025Q3", "2026Q2"]},
         "mult": {}}
    html = p_calc(F)
    current = round(2425.0 / 86.28, 1)
    assert current == 28.1
    assert f'value="{current}"' in html
    assert f"{round(current * 86.28):,}" in html  # 2,424 元 at the market's own multiple
    assert calc_diff(20 * 86.28, 2425.0) == "比現在股價低 28.8%：你給的倍數比市場現在低，所以換算出來的價格也比較低。"
    assert "不是合理價或目標價" in html
    loss = p_calc({**F, "ttm": {"basic_eps": -1.2}})
    assert "本益比無法換算" in loss and "<input" not in loss
    assert "無法換算" in p_calc({**F, "closes": []})


def test_taiwan_colours_rise_red_with_arrows():
    assert chg(3.2) == '<span class="pc-up">▲ 3.2%</span>'
    assert chg(-1.0) == '<span class="pc-down">▼ 1.0%</span>'
    assert chg(0.01) == "持平"


def test_negative_bar_value_sits_right_of_the_zero_line():
    svg = hbars([("收進", 1359.0, "gray"), ("剩下", -416.0, "blue")], fmt=lambda v: f"{v:,.0f} 億")
    zero = float(re.search(r'<line x1="([0-9.]+)"', svg).group(1))
    label_x = float(re.search(r'<text x="([0-9.]+)" y="[0-9.]+" class="vl" text-anchor="start">-416 億', svg).group(1))
    assert label_x > zero


def test_page_puts_the_section_first_and_only_on_the_latest_version():
    newer = report(close=1100.0)
    newer["generated_utc"] = "2026-10-20T12:00:00+00:00"
    newer["started_utc"] = "2026-10-20T11:59:00+00:00"
    records, skipped = latest_only_records([newer])
    assert skipped == {}
    records.update({k: v for k, v in stored_2330().items() if k.startswith("snapshots/")})
    html = render_research_site_html(records)
    nav = re.search(r'<nav class="secnav"[^>]*>(.*?)</nav>', html, re.S).group(1)
    assert nav.startswith('<a href="#beginner">新手</a><a href="#overview">總覽</a>')
    data = site_data(html)
    stock = data["stocks"][0]
    views = data["views"]["2330.TW"]
    latest = views[stock["latest_snapshot_id"]]
    others = [v for sid, v in views.items() if sid != stock["latest_snapshot_id"]]
    assert latest.index('id="beginner"') < latest.index('id="overview"')
    assert "先看結論：公司體質檢查" in latest
    assert others and all("新手章節只顯示最新研究版本" in v and "pc-check" not in v for v in others)
    assert "window.bindBeginner" in html and "window.bindBeginner(app)" in html
