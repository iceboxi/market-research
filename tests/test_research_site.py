"""Tests for the self-contained 2330.TW static HTML research dashboard (Issue #87)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from market_research.research_site import (
    _findings,
    build_site_payload,
    render_research_site_html,
    write_research_site,
)


def _sample_report(stamp: str = "2026-10-19T12:00:00+00:00", complete: bool = True) -> dict:
    return {
        "schema_version": 4,
        "symbol": "2330.TW",
        "market": "tw",
        "started_utc": "2026-10-19T11:59:00+00:00",
        "generated_utc": stamp,
        "complete": complete,
        "issuer": {
            "company_name": "台灣積體電路製造股份有限公司" if complete else None,
            "profile": {
                "source": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
                "reported_at": "1151019",
            },
            "facts": [
                {
                    "metric": "monthly_reported_revenue",
                    "value": 511857399.0,
                    "unit": "TWD_thousands",
                    "period": "11509",
                    "reported_at": "1151010",
                    "source": "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
                }
            ],
        },
        "technical": {
            "status": "available" if complete else "unavailable",
            "source": "fixture_daily",
            "last_session": "2026-10-19" if complete else None,
            "input_sha256": "b" * 64,
            "price_basis": "unadjusted",
            "analytical_close": 1085.0,
            "ohlcv": ["DO_NOT_STORE_PRICE_SERIES"],
        },
        "official_events": {
            "status": "available",
            "source": "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
            "snapshot_date": "2026-10-19",
            "coverage": "recent_daily_snapshot_only_not_a_full_history",
            "events": [{"title": "DO_NOT_STORE_DISCLOSURE_BODY"}],
        },
        "research_readiness": {
            "components": {
                "financial": {"status": "unavailable"},
                "valuation": {"status": "not_evaluated"},
                "trade_plan": {"status": "not_evaluated"},
                "recommendation": {"status": "not_available"},
            }
        },
    }


def _make_full_financial_research() -> dict:
    return {
        "schema_version": 1,
        "status": "available",
        "currency": "TWD",
        "reconciled_period_end": "2026-06-30",
        "reconciled_twse_openapi": True,
        "paid_in_capital_twd": 259323700670.0,
        "issued_ordinary_shares": 25932370067,
        "par_value_desc": "新台幣 10.0000元",
        "annual_summary": [
            {
                "fiscal_year": "2025",
                "period_start": "2025-01-01",
                "period_end": "2025-12-31",
                "revenue": 3809054272000.0,
                "revenue_yoy_pct": 31.61,
                "gross_profit": 2281293979000.0,
                "gross_margin_pct": 59.89,
                "operating_income": 1936091677000.0,
                "operating_margin_pct": 50.83,
                "net_income": 1715396780000.0,
                "net_income_yoy_pct": 46.31,
                "net_margin_pct": 45.03,
                "parent_net_income": 1717882627000.0,
                "basic_eps": 66.26,
                "operating_cash_flow": 2274975625000.0,
                "capex": 1272410529000.0,
                "free_cash_flow": 1002565096000.0,
                "fcf_margin_pct": 26.32,
                "fcf_yoy_pct": 15.21,
                "ordinary_shares": 25932524500.0,
            },
            {
                "fiscal_year": "2024",
                "period_start": "2024-01-01",
                "period_end": "2024-12-31",
                "revenue": 2894307699000.0,
                "revenue_yoy_pct": 33.89,
                "gross_profit": 1624353564000.0,
                "gross_margin_pct": 56.12,
                "operating_income": 1322053050000.0,
                "operating_margin_pct": 45.68,
                "net_income": 1172431759000.0,
                "net_income_yoy_pct": 39.95,
                "net_margin_pct": 40.51,
                "parent_net_income": 1173267703000.0,
                "basic_eps": 45.26,
                "operating_cash_flow": 1826177068000.0,
                "capex": 956006536000.0,
                "free_cash_flow": 870170532000.0,
                "fcf_margin_pct": 30.06,
                "fcf_yoy_pct": 197.85,
                "ordinary_shares": 25932733200.0,
            },
        ],
        "quarterly_summary": [
            {
                "period_label": "2026Q2",
                "period_start": "2026-04-01",
                "period_end": "2026-06-30",
                "basis": "standalone_reconciled_t187ap45",
                "revenue": 1270380250000.0,
                "gross_profit": 860310695000.0,
                "gross_margin_pct": 67.72,
                "operating_income": 766602651000.0,
                "operating_margin_pct": 60.34,
                "net_income": 706780923000.0,
                "net_margin_pct": 55.64,
                "parent_net_income": 706561938000.0,
                "basic_eps": 27.25,
                "operating_cash_flow": 783364977000.0,
                "capex": 496001947000.0,
                "free_cash_flow": 287363030000.0,
                "fcf_margin_pct": 22.62,
                "ordinary_shares": 25932370100,
            }
        ],
        "ttm": {
            "status": "available",
            "quarters": ["2025Q3", "2025Q4", "2026Q1", "2026Q2"],
            "quarter_ends": ["2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"],
            "revenue": 4440492429000.0,
            "gross_profit": 2852135781000.0,
            "gross_margin_pct": 64.23,
            "operating_income": 2491156024000.0,
            "operating_margin_pct": 56.10,
            "net_income": 2236752922000.0,
            "net_margin_pct": 50.37,
            "basic_eps": 86.28,
            "eps_derivation": "sum_of_four_quarters_within_0.5pct_share_drift",
            "share_count_max_drift_pct": 0.000595,
            "operating_cash_flow": 2634679110000.0,
            "capex": 1491122744000.0,
            "free_cash_flow": 1143556366000.0,
            "fcf_margin_pct": 25.75,
        },
        "latest_cumulative_interim": {
            "period_label": "2026-H1",
            "period_start": "2026-01-01",
            "period_end": "2026-06-30",
            "revenue": 2404483690000.0,
            "revenue_yoy_pct": 35.61,
            "gross_profit": 1611606116000.0,
            "operating_income": 1425568793000.0,
            "pre_tax_income": 1550229773000.0,
            "net_income": 1279582227000.0,
            "net_income_yoy_pct": 68.76,
            "parent_net_income": 1279041690000.0,
            "basic_eps": 49.33,
            "operating_cash_flow": 1482341242000.0,
            "capex": 846764746000.0,
            "free_cash_flow": 635576496000.0,
            "reconciled_twse_openapi": True,
        },
        "latest_balance_sheet": {
            "period_end": "2026-06-30",
            "cash": 3134218213000.0,
            "bonds_payable": 815036716000.0,
            "long_term_borrowings": 49226958000.0,
            "total_debt": 864263674000.0,
            "net_cash": 2269954539000.0,
            "total_assets": 9375654727000.0,
            "total_liabilities": 2901183746000.0,
            "total_equity": 6474470981000.0,
            "parent_equity": 6432518334000.0,
            "capital_stock": 259323701000.0,
            "ordinary_shares": 25932370100,
        },
        "valuation_summary": {
            "status": "illustrative_only",
            "method": "ev_bridged_three_year_median_fcf_and_ttm_pe_scenarios",
            "asof": "2026-10-21",
            "latest_fiscal_end": "2025-12-31",
            "latest_balance_sheet_end": "2026-06-30",
            "normalized_annual_fcf_twd": 870170532000.0,
            "ttm_fcf_twd": 1143556366000.0,
            "net_cash_twd": 2269954539000.0,
            "fcf_twd_per_ordinary_share": 33.5554,
            "ttm_fcf_twd_per_ordinary_share": 44.0976,
            "net_cash_twd_per_ordinary_share": 87.5336,
            "denominator": {
                "value": 25932370100.0,
                "unit": "shares",
                "period_end": "2026-06-30",
                "basis": "ordinary_share_capital_divided_by_10_twd_par_reconciled_with_twse_t187ap03",
            },
            "exchange_multiples": {
                "pe_ratio": 27.88,
                "pb_ratio": 9.7,
                "dividend_yield_pct": 0.91,
                "date_roc": "1151020",
                "source": "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL",
            },
            "fair_value_scenarios": {
                "conservative": {
                    "fcf_multiple": 15.0,
                    "median_fcf_component_twd": 503.33,
                    "net_cash_component_twd": 87.53,
                    "indicative_twd_per_share": 590.86,
                    "indicative_ttm_fcf_twd_per_share": 749.0,
                },
                "base": {
                    "fcf_multiple": 20.0,
                    "median_fcf_component_twd": 671.11,
                    "net_cash_component_twd": 87.53,
                    "indicative_twd_per_share": 758.64,
                    "indicative_ttm_fcf_twd_per_share": 969.49,
                },
                "optimistic": {
                    "fcf_multiple": 25.0,
                    "median_fcf_component_twd": 838.88,
                    "net_cash_component_twd": 87.53,
                    "indicative_twd_per_share": 926.42,
                    "indicative_ttm_fcf_twd_per_share": 1189.97,
                },
            },
            "ttm_pe_scenarios": {
                "conservative": {
                    "pe_multiple": 20.0,
                    "ttm_basic_eps_twd": 86.28,
                    "indicative_twd_per_share": 1725.6,
                },
                "base": {
                    "pe_multiple": 25.0,
                    "ttm_basic_eps_twd": 86.28,
                    "indicative_twd_per_share": 2157.0,
                },
                "optimistic": {
                    "pe_multiple": 30.0,
                    "ttm_basic_eps_twd": 86.28,
                    "indicative_twd_per_share": 2588.4,
                },
            },
            "why": "Illustrative EV-bridged P/FCF and TTM P/E scenario sensitivities only",
        },
        "calendar_schedule": {
            "schema_version": 1,
            "status": "available",
            "timezone": "Asia/Taipei",
            "events": [
                {
                    "schedule_id": "2330-shareholder_meeting-2026",
                    "event_type": "shareholder_meeting",
                    "period_label": "FY2026",
                    "scheduled_date": "2026-06-04",
                    "confirmation_status": "confirmed",
                    "superseded_dates": ["2026-06-02"],
                    "title": "2026 年股東常會",
                    "source": "https://openapi.twse.com.tw/v1/opendata/t187ap38_L",
                }
            ],
        },
        "disclosure_and_news": {
            "schema_version": 1,
            "status": "available",
            "deduplicated_repost_count": 4,
            "official_disclosures": [
                {
                    "disclosure_id": "tw-board-1",
                    "category": "board_dividend_and_earnings_resolution",
                    "event_date": "2026-08-11",
                    "title": "董事會決議通過 2026第2季 盈餘分派（每股現金股利 7.00 元） <script>alert(1)</script>",
                    "source": "https://openapi.twse.com.tw/v1/opendata/t187ap45_L",
                }
            ],
            "news_references": [],
        },
        "ex_dividend_history": [
            {
                "ex_date": "2026-09-16",
                "type": "息",
                "dividend_per_share_twd": 7.0,
                "before_price": 2385.0,
                "reference_price": 2378.0,
            }
        ],
    }


def test_render_research_site_multi_snapshot_time_machine_and_xss_safety(tmp_path: Path):
    from market_research.research_snapshot import prepare_snapshot

    r1 = _sample_report()
    s1 = prepare_snapshot(
        r1,
        {
            "repository": "iceboxi/market-research",
            "run_id": "1001",
            "run_attempt": 1,
            "code_sha": "a" * 40,
            "observed_at_utc": "2026-10-20T12:00:00+00:00",
        },
    )

    r2 = _sample_report()
    r2["financial_research"] = _make_full_financial_research()
    r2["research_readiness"]["components"]["financial"]["status"] = "available"
    r2["research_readiness"]["components"]["valuation"]["status"] = "illustrative_only"
    r2["valuation"] = {"status": "illustrative_only", "provenance": "reconciled_tw_dual_track"}
    s2 = prepare_snapshot(
        r2,
        {
            "repository": "iceboxi/market-research",
            "run_id": "1002",
            "run_attempt": 1,
            "code_sha": "b" * 40,
            "observed_at_utc": "2026-10-21T12:00:00+00:00",
        },
    )

    records = {
        f"snapshots/tw/2330.TW/{s1['id']}.json": s1,
        f"snapshots/tw/2330.TW/{s2['id']}.json": s2,
        "subjects/tw/2330.TW.json": {
            "schema_version": 2,
            "symbol": "2330.TW",
            "issue_number": 74,
            "creation_attempted": True,
            "latest_observation_id": s2["id"],
            "last_success_id": s2["id"],
            "pending_publication_id": None,
            "published_publication_id": None,
        },
        "checkpoints/tw/2330.TW.json": {
            "schema_version": 1,
            "symbol": "2330.TW",
            "consumed_event_ids": ["mops:2330:20260811:1"],
            "consumed_financial_version": "ifrs-2026-06-30",
            "pending_rerun": None,
            "last_completed_snapshot_id": s2["id"],
        },
    }

    out_path = write_research_site(tmp_path, records, branch="research-state")
    assert out_path.exists()
    html_text = out_path.read_text(encoding="utf-8")

    # 1. Valid HTML5 & Time Machine options for both snapshots
    assert html_text.startswith("<!DOCTYPE html>")
    assert f'<option value="{s2["id"]}" selected>' in html_text
    assert f'<option value="{s1["id"]}">' in html_text

    # 2. Key financial numbers, TTM, dual-model valuation, calendar, and boundary badges
    assert "44,404.9" in html_text
    assert "86.28" in html_text
    assert "illustrative_only" in html_text
    assert "not_evaluated" in html_text
    assert "not_available" in html_text
    assert "原訂 2026-06-02，已更正" in html_text
    assert "ifrs-2026-06-30" in html_text

    # 3. Workspace IA: Search combobox, section nav, charts, and non-color semantic indicators
    assert 'id="stock-input"' in html_text
    assert 'id="stock-list"' in html_text
    assert 'href="#overview"' in html_text
    assert 'href="#fundamentals"' in html_text
    assert 'href="#valuation"' in html_text
    assert 'href="#technical"' in html_text
    assert 'href="#events"' in html_text
    assert 'href="#methodology"' in html_text
    assert '<svg viewBox="0 0 720' in html_text
    assert "▲" in html_text

    # 4. Investment research depth: Financial dynamics, boundary disclosure, valuation conditions, technical contract
    assert "商業表現與財務動能分析" in html_text
    assert "營業槓桿與獲利結構" in html_text
    assert "投資研究缺失證據與資料邊界" in html_text
    assert "行情與價格走勢持久化契約限制說明" in html_text
    assert "情境倍數適用條件分析" in html_text
    assert "研究模組就緒度" in html_text
    assert 'id="m-status"' in html_text

    # 5. XSS payload in disclosure title must be escaped both in DOM and embedded JSON
    assert "<script>alert(1)</script>" not in html_text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_text

    # 6. Embedded JSON bundle parses cleanly and contains multi-stock registry and views
    match = re.search(
        r'<script id="site-data" type="application/json">(.*?)</script>',
        html_text,
        re.DOTALL,
    )
    assert match is not None
    embedded = json.loads(match.group(1))
    assert embedded["schema_version"] == 2
    assert embedded["default_symbol"] == "2330.TW"
    assert len(embedded["stocks"]) == 1
    assert len(embedded["stocks"][0]["snapshots"]) == 2
    assert embedded["stocks"][0]["latest_snapshot_id"] == s2["id"]
    assert "2330.TW" in embedded["views"]
    assert s1["id"] in embedded["views"]["2330.TW"]
    assert s2["id"] in embedded["views"]["2330.TW"]
    assert "此研究版本沒有完整財務研究" in embedded["views"]["2330.TW"][s1["id"]]


def test_render_research_site_standalone_report_mode():
    r = _sample_report(stamp="2026-10-19T12:00:00+00:00")
    r["started_utc"] = "2026-10-21T12:00:00+00:00"
    r["financial_research"] = _make_full_financial_research()
    r["technical"]["recent_closes"] = [
        {"date": f"2026-09-{i:02d}", "close": 900.0 + i * 5}
        for i in range(1, 31)
    ]
    payload = build_site_payload(latest_report=r)
    assert len(payload["stocks"]["2330.TW"]["snapshots"]) == 1
    html_text = render_research_site_html(latest_report=r)
    assert "2330.TW" in html_text
    assert "台灣積體電路製造股份有限公司" in html_text
    assert 'id="stock-input"' in html_text
    assert 'href="#overview"' in html_text
    assert "近 30 個交易日收盤價走勢" in html_text
    assert "price-chart" in html_text
    assert "price-line" in html_text


def test_render_research_site_financial_stock_graceful_presentation():
    """Verify financial holding stock (2881.TW) renders with inapplicable instrument & not_evaluated valuation."""
    r_fin = {
        "schema_version": 4,
        "symbol": "2881.TW",
        "market": "tw",
        "started_utc": "2026-10-21T12:00:00+00:00",
        "generated_utc": "2026-10-21T12:01:00+00:00",
        "complete": True,
        "issuer": {
            "company_name": "富邦金融控股股份有限公司",
            "profile": {
                "source": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
                "reported_at": "1151021",
            },
            "facts": [],
        },
        "technical": {
            "status": "available",
            "source": "twse_stock_day",
            "last_session": "2026-10-21",
            "input_sha256": "c" * 64,
            "price_basis": "unadjusted",
            "analytical_close": 91.5,
            "recent_closes": [
                {"date": "2026-10-20", "close": 90.8},
                {"date": "2026-10-21", "close": 91.5},
            ],
        },
        "official_events": {
            "status": "available",
            "source": "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
            "snapshot_date": "2026-10-21",
            "coverage": "recent_daily_snapshot_only_not_a_full_history",
            "events": [],
        },
        "research_readiness": {
            "components": {
                "instrument": {"status": "inapplicable"},
                "financial": {"status": "unavailable"},
                "valuation": {"status": "not_evaluated"},
                "trade_plan": {"status": "not_evaluated"},
                "recommendation": {"status": "not_available"},
            }
        },
    }
    html_text = render_research_site_html(latest_report=r_fin)
    assert "2881.TW" in html_text
    assert "富邦金融控股股份有限公司" in html_text
    assert "不適用（金融/特殊業）" in html_text
    assert "未進行估值" in html_text
    assert "此研究版本沒有估值情境" in html_text
    assert "近 30 個交易日收盤價走勢" in html_text



def test_narrative_generation_epistemological_precision():
    """Verify narrative generator strictly distinguishes facts, derivations, hypotheses, and gaps."""
    fr = _make_full_financial_research()
    findings, gaps = _findings(fr)

    topics = {t: (stmt, basis) for t, stmt, basis in findings}

    # 1. Revenue growth: Must NOT claim unverified cyclical recovery
    assert "營收擴張動能" in topics
    rev_stmt, rev_basis = topics["營收擴張動能"]
    assert "走出半導體庫存調整週期" not in rev_stmt
    assert "雙位數" in rev_stmt
    assert "未納入未經證實之庫存週期假設" in rev_basis

    # 2. Operating leverage: Must NOT claim capacity utilization / pricing power as proven fact
    assert "營業槓桿與獲利結構" in topics
    op_stmt, op_basis = topics["營業槓桿與獲利結構"]
    assert "反映高稼動率與定價權帶動之利潤率擴張" not in op_basis
    assert "稼動率與定價權為未經申報驗證之假說" in op_basis
    assert "合理假說" in op_stmt
    assert "不得視為已證因果" in op_stmt

    # 3. Cash flow: Must note capex intensity and working capital verification limits
    assert "現金流品質與再投資" in topics
    cf_stmt, cf_basis = topics["現金流品質與再投資"]
    assert "未含營運資金細項週期驗證" in cf_basis
    assert "重資本再投資特性導致近半數淨利轉化為廠房設備投資" in cf_stmt

    # 4. Liquidity & balance sheet: Absolutely NO claims of 'zero risk' or 'no liquidity risk'
    assert "資產負債與流動性緩衝" in topics
    bs_stmt, bs_basis = topics["資產負債與流動性緩衝"]
    assert "無短期償債或流動性財務風險" not in bs_stmt
    assert "非保證零流動性風險" in bs_stmt
    assert "未含表外資本合約與到期排程分析" in bs_basis

    # 5. Valuation: Must frame scenarios as sensitivities rather than forecasts
    assert "估值模型與結構性落差" in topics
    val_stmt, val_basis = topics["估值模型與結構性落差"]
    assert "情境試算非營運預測，不作交易依據" in val_basis
    assert "敏感度觀察，絕非合理價" in val_stmt

    # 6. Full rendered page checks: 4 epistemological tiers in HTML
    r = _sample_report()
    r["financial_research"] = fr
    r["research_readiness"]["components"]["financial"]["status"] = "available"
    r["research_readiness"]["components"]["valuation"]["status"] = "illustrative_only"
    html_text = render_research_site_html(latest_report=r)

    assert "分析宣稱認識論分級原則（Epistemological Standards）" in html_text
    assert "直接觀測事實（Reported Facts）" in html_text
    assert "報表推導指標（Derived Metrics）" in html_text
    assert "合理推論假說（Plausible Hypotheses）" in html_text
    assert "需外部補充證據之邊界（Evidence Gaps）" in html_text
    assert "情境倍數適用條件分析（敏感度壓力測試假設，非營運預測）" in html_text

    # Forbidden overclaims must never appear in final rendered page
    assert "走出半導體庫存調整週期" not in html_text
    assert "無短期償債或流動性財務風險" not in html_text

