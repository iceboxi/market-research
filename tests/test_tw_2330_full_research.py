"""End-to-end TW05/TW06/TW07/TW10/TW11/TW12 tests for 2330.TW full research workflow."""
from datetime import date, datetime, timezone
import json

import pandas as pd
import pytest

from market_research.fundamentals import (
    FINMIND_URL, TW_BALANCE_CI, TW_DIVIDEND_L, TW_INCOME_CI, TW_PROFILE,
    TW_PROFIT_L, TW_REVENUE, TW_VALUATION_L,
)
from market_research.event_risk import TW_MATERIAL_URL
from market_research.financial_history import normalize_tw_financial_history
from market_research.research_comparison import compare_snapshots
from market_research.research_snapshot import prepare_snapshot, validate_snapshot
from scripts.company_report import run
from scripts.research_state import archive, initialize, read, render_publication
from test_research_state import repo


NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


class Prices2330:
    source = "fixture_daily"
    def load(self, symbol, period):
        dates = pd.bdate_range("2026-07-01", "2026-10-19").date
        n = len(dates)
        return pd.DataFrame({
            "open": [1400.0 + i for i in range(n)],
            "high": [1415.0 + i for i in range(n)],
            "low": [1390.0 + i for i in range(n)],
            "close": [1405.0 + i for i in range(n)],
            "volume": [25_000_000] * n,
        }, index=pd.Index(dates, name="date"))


def make_finmind_and_twse_fixtures():
    # Exact reconciled 2330.TW data (2023Q1-2026Q2)
    q_is = [
        # 2023 standalone quarters (sums to FY2023: Rev 2,161,735,841,000, NI 837,767,517,000, EPS 32.34)
        ("2023-03-31", 508632973000, 286500162000, 231238452000, 206948723000, 206986578000, 7.98),
        ("2023-06-30", 480841256000, 260200127000, 201959445000, 181721010000, 181799482000, 7.01),
        ("2023-09-30", 546732762000, 296959326000, 228064396000, 210802307000, 210999923000, 8.14),
        ("2023-12-31", 625528850000, 331451013000, 260203313000, 238295477000, 238711681000, 9.21),
        # 2024 standalone quarters (sums to FY2024: Rev 2,894,307,699,000, NI 1,172,431,759,000, EPS 45.26)
        ("2024-03-31", 592644201000, 314505200000, 249018162000, 225221307000, 225484862000, 8.70),
        ("2024-06-30", 673510177000, 358125166000, 286555863000, 247662297000, 247845466000, 9.56),
        ("2024-09-30", 759692440000, 439345258000, 360766227000, 325079438000, 325257828000, 12.54),
        ("2024-12-31", 868460881000, 512377940000, 425712798000, 374468717000, 374679547000, 14.46),
        # 2025 standalone quarters (sums to FY2025: Rev 3,809,054,272,000, NI 1,715,396,780,000, EPS 66.26)
        ("2025-03-31", 839253655000, 493395224000, 407081908000, 360732752000, 361564143000, 13.95),
        ("2025-06-30", 933791878000, 547129090000, 463422543000, 397493333000, 398273087000, 15.36),
        ("2025-09-30", 989918318000, 588542829000, 500684818000, 451755362000, 452301407000, 17.44),
        ("2025-12-31", 1046090421000, 651986836000, 564902413000, 505415333000, 505743990000, 19.51),
        # 2026Q1 standalone, 2026-06-30 reported as H1 YTD (except EPS which is standalone Q2 27.25)
        ("2026-03-31", 1134103440000, 751295421000, 658966142000, 572801304000, 572479752000, 22.08),
        ("2026-06-30", 2404483690000, 1611606116000, 1425568793000, 1279582227000, 1279041690000, 27.25),
    ]
    inc_rows = []
    for dt, rev, gp, op, ni, pni, eps in q_is:
        for typ, val in (
            ("Revenue", rev), ("GrossProfit", gp), ("OperatingIncome", op),
            ("IncomeAfterTaxes", ni), ("EquityAttributableToOwnersOfParent", pni), ("EPS", eps),
        ):
            inc_rows.append({"date": dt, "stock_id": "2330", "type": typ, "value": val, "origin_name": typ})

    # Balance Sheet per quarter end
    bs_rows = []
    all_q_dates = [r[0] for r in q_is]
    for dt in all_q_dates:
        cap = 259320710000 if dt.startswith("2023") else (
            259327332000 if dt.startswith("2024") else (
                259325245000 if dt.startswith("2025") else 259323701000
            )
        )
        cash = 1465427753000 if dt.startswith("2023") else (
            2127627043000 if dt.startswith("2024") else (
                2767856402000 if dt.startswith("2025") else 3134218213000
            )
        )
        assets = 9375654727000 if dt == "2026-06-30" else 7933023878000
        liab = 2901183746000 if dt == "2026-06-30" else 2472228595000
        eq = 6474470981000 if dt == "2026-06-30" else 5460795283000
        bonds = 815036716000 if dt == "2026-06-30" else 856227503000
        lt_borrow = 49226958000 if dt == "2026-06-30" else 39834496000
        for typ, val in (
            ("CashAndCashEquivalents", cash),
            ("TotalAssets", assets),
            ("Liabilities", liab),
            ("Equity", eq),
            ("CapitalStock", cap),
            ("OrdinaryShare", cap),
            ("BondsPayable", bonds),
            ("LongtermBorrowings", lt_borrow),
        ):
            bs_rows.append({"date": dt, "stock_id": "2330", "type": typ, "value": val, "origin_name": typ})

    # Cash Flow YTD per quarter end
    cf_ytd = [
        ("2023-03-31", 385244722000, -302509666000),
        ("2023-06-30", 552267289000, -553064720000),
        ("2023-09-30", 846912695000, -763106684000),
        ("2023-12-31", 1241967347000, -949816825000),
        ("2024-03-31", 436311033000, -181397732000),
        ("2024-06-30", 813979263000, -372198338000),
        ("2024-09-30", 1205926845000, -579067258000),
        ("2024-12-31", 1826177068000, -956006536000),
        ("2025-03-31", 625573672000, -330589588000),
        ("2025-06-30", 1122637757000, -628052531000),
        ("2025-09-30", 1549428917000, -915048506000),
        ("2025-12-31", 2274975625000, -1272410529000),
        ("2026-03-31", 698976265000, -350762799000),
        ("2026-06-30", 1482341242000, -846764746000),
    ]
    cf_rows = []
    for dt, cfo, capex in cf_ytd:
        cf_rows.append({"date": dt, "stock_id": "2330", "type": "CashFlowsFromOperatingActivities", "value": cfo, "origin_name": "CFO"})
        cf_rows.append({"date": dt, "stock_id": "2330", "type": "PropertyAndPlantAndEquipment", "value": capex, "origin_name": "CAPEX"})

    div_res = [
        {"date": "2026-09-10", "stock_id": "2330", "stock_and_cache_dividend": "息", "stock_or_cache_dividend": 6.0, "before_price": 1460.0, "reference_price": 1454.0},
    ]

    twse = {
        "income": {
            "出表日期": "1151019", "年度": "115", "季別": "2", "公司代號": "2330",
            "營業收入": "2404483690.00", "營業毛利（毛損）": "1611606116.00",
            "營業利益（損失）": "1425568793.00", "本期淨利（淨損）": "1279582227.00",
            "淨利（淨損）歸屬於母公司業主": "1279041690.00", "基本每股盈餘（元）": "49.33",
        },
        "balance": {
            "出表日期": "1151019", "年度": "115", "季別": "2", "公司代號": "2330",
            "資產總計": "9375654727.00", "負債總計": "2901183746.00",
            "權益總計": "6474470981.00", "股本": "259323701.00",
        },
        "profitability": {
            "出表日期": "1151019", "年度": "115", "季別": "2", "公司代號": "2330",
            "毛利率(%)(營業毛利)/(營業收入)": "67.03", "營業利益率(%)(營業利益)/(營業收入)": "59.29",
            "稅後純益率(%)(稅後純益)/(營業收入)": "53.22",
        },
        "dividends": [
            {"出表日期": "1151019", "公司代號": "2330", "年度": "114", "季別": "第4季", "董事會（擬議）股利分派日": "1150210", "本期淨利(淨損)(元)": "505743990228", "現金股利(元/股)": "6.00003573", "股票股利(元/股)": "0.00000000"},
            {"出表日期": "1151019", "公司代號": "2330", "年度": "115", "季別": "第1季", "董事會（擬議）股利分派日": "1150512", "本期淨利(淨損)(元)": "572479752038", "現金股利(元/股)": "7.00000137", "股票股利(元/股)": "0.00000000"},
            {"出表日期": "1151019", "公司代號": "2330", "年度": "115", "季別": "第2季", "董事會（擬議）股利分派日": "1150811", "本期淨利(淨損)(元)": "706561938461", "現金股利(元/股)": "7.00000000", "股票股利(元/股)": "0.00000000"},
        ],
        "valuation": {
            "Date": "1151019", "Code": "2330", "Name": "台積電",
            "PEratio": "28.05", "DividendYield": "0.91", "PBratio": "9.76",
        },
    }
    return {"income": inc_rows, "balance": bs_rows, "cashflow": cf_rows, "dividend_result": div_res}, twse


def make_http_router():
    finmind, twse = make_finmind_and_twse_fixtures()
    def router(url):
        if url == TW_PROFILE:
            return [{
                "公司代號": "2330", "公司名稱": "台灣積體電路製造股份有限公司",
                "產業別": "24", "出表日期": "1151019",
                "實收資本額": "259323700670", "普通股每股面額": "新台幣 10.0000元",
                "已發行普通股數或TDR原股發行股數": "25932370067",
            }]
        if url == TW_REVENUE:
            return [{
                "公司代號": "2330", "當月營收": "314240282",
                "資料年月": "11509", "出表日期": "1151010",
                "營業收入-去年同月增減(%)": "24.77", "營業收入-上月比較增減(%)": "-1.45",
            }]
        if url == TW_MATERIAL_URL:
            return [{
                "公司代號": "2330", "出表日期": "1151019",
                "發言日期": "1151018", "發言時間": "143000",
                "主旨": "台積公司董事會核准資本預算與股利分派說明",
            }]
        if url == TW_INCOME_CI:
            return [twse["income"]]
        if url == TW_BALANCE_CI:
            return [twse["balance"]]
        if url == TW_PROFIT_L:
            return [twse["profitability"]]
        if url == TW_DIVIDEND_L:
            return twse["dividends"]
        if url == TW_VALUATION_L:
            return [twse["valuation"]]
        if url.startswith(FINMIND_URL):
            if "TaiwanStockFinancialStatements" in url:
                return {"status": 200, "data": finmind["income"]}
            if "TaiwanStockBalanceSheet" in url:
                return {"status": 200, "data": finmind["balance"]}
            if "TaiwanStockCashFlowsStatement" in url:
                return {"status": 200, "data": finmind["cashflow"]}
            if "TaiwanStockDividendResult" in url:
                return {"status": 200, "data": finmind["dividend_result"]}
        raise AssertionError(f"Unexpected URL: {url}")
    return router


def test_normalize_tw_financial_history_reconciles_annual_quarterly_and_ttm():
    finmind, twse = make_finmind_and_twse_fixtures()
    hist = normalize_tw_financial_history("2330", date(2026, 10, 19), finmind=finmind, twse=twse)
    assert hist["reconciled_twse_openapi"] is True
    assert hist["reconciled_period_end"] == "2026-06-30"
    assert [r["value"] for r in hist["annual_revenue"]] == [3809054272000.0, 2894307699000.0, 2161735841000.0]
    assert [r["value"] for r in hist["annual_free_cash_flow"]] == [1002565096000.0, 870170532000.0, 292150522000.0]
    ttm = hist["ttm"]
    assert ttm["status"] == "available"
    assert ttm["quarters"] == ["2025Q3", "2025Q4", "2026Q1", "2026Q2"]
    assert ttm["revenue"] == 4440492429000.0
    assert ttm["basic_eps"] == 86.28
    assert ttm["free_cash_flow"] == 1143556366000.0
    q2_2026 = hist["quarterly_statements"][0]
    assert q2_2026["period_label"] == "2026Q2"
    assert q2_2026["basis"] == "ytd_reconciled_t187ap06"
    assert q2_2026["revenue"] == 1270380250000.0
    assert q2_2026["basic_eps"] == 27.25
    assert q2_2026["free_cash_flow"] == 287363030000.0

    # Also verify when 2026-06-30 in FinMind is reported as standalone Q2 (live FinMind format)
    finmind_sa, twse_sa = make_finmind_and_twse_fixtures()
    for row in finmind_sa["income"]:
        if row["date"] == "2026-06-30":
            row["value"] = {
                "Revenue": 1270380250000,
                "GrossProfit": 860310695000,
                "OperatingIncome": 766602651000,
                "IncomeAfterTaxes": 706780923000,
                "EquityAttributableToOwnersOfParent": 706561938000,
                "EPS": 27.25,
            }[row["type"]]
    hist_sa = normalize_tw_financial_history("2330", date(2026, 10, 19), finmind=finmind_sa, twse=twse_sa)
    assert hist_sa["reconciled_twse_openapi"] is True
    assert hist_sa["quarterly_statements"][0]["basis"] == "standalone_reconciled_t187ap45"
    assert hist_sa["quarterly_statements"][0]["revenue"] == 1270380250000.0
    assert hist_sa["latest_cumulative_interim"]["revenue"] == 2404483690000.0
    assert hist_sa["ttm"]["revenue"] == 4440492429000.0


def test_full_2330_report_snapshot_archive_publication_and_idempotent_rerun(repo, tmp_path):
    _, _, store = repo
    initialize(store)
    router = make_http_router()
    result = run(
        "2330.TW", out=tmp_path / "run1", now=NOW,
        provider=Prices2330(), facts_get=router, financial_get=router,
    )
    assert result["complete"] is True
    assert result["financial_comparison"]["status"] == "available"
    assert result["valuation"]["status"] == "illustrative_only"
    assert result["valuation"]["entry_zone"] is None
    assert result["valuation"]["stop_loss"] is None
    assert result["valuation"]["target_price"] is None
    assert result["research_readiness"]["components"]["financial"]["status"] == "available"
    assert result["research_readiness"]["components"]["valuation"]["status"] == "illustrative_only"
    assert result["research_readiness"]["components"]["trade_plan"]["status"] == "not_evaluated"
    assert result["research_readiness"]["components"]["recommendation"]["status"] == "not_available"

    md = (tmp_path / "run1" / "report.md").read_text()
    assert "## 1. 公司目前財務與營運狀況" in md
    assert "## 2. 歷年、季度與 TTM 財務變化" in md
    assert "## 3. 估值模型、假設與情境分析" in md
    assert "## 4. 股數、除權息與公司行動證據" in md
    assert "## 5. 綜合研究判斷與後續觀察條件" in md
    assert "4,440,492,429,000" in md
    assert "86.28" in md

    snap1 = prepare_snapshot(result, {
        "repository": "owner/repo", "run_id": "201", "run_attempt": 1,
        "code_sha": "a" * 40, "observed_at_utc": "2026-10-19T12:01:00+00:00",
    })
    validate_snapshot(snap1)
    assert "financial_research" in snap1
    archive(snap1, store)
    assert archive(snap1, store)["status"] == "already_current"

    # Rerun on identical data at a later timestamp -> comparison must be "unchanged"
    result2 = run(
        "2330.TW", out=tmp_path / "run2",
        now=datetime(2026, 10, 19, 12, 5, tzinfo=timezone.utc),
        provider=Prices2330(), facts_get=router, financial_get=router,
    )
    snap2 = prepare_snapshot(result2, {
        "repository": "owner/repo", "run_id": "202", "run_attempt": 1,
        "code_sha": "a" * 40, "observed_at_utc": "2026-10-19T12:06:00+00:00",
    })
    delta_same = compare_snapshots(snap1, snap2)
    assert delta_same["categories"] == ["unchanged"]
    assert delta_same["changes"] == []

    archive(snap2, store)
    records = read(store)["records"]
    pub_id = records["subjects/tw/2330.TW.json"]["pending_publication_id"]
    pub_body = render_publication(records, pub_id, store.branch)
    assert "## 1. 公司目前財務與營運狀況" in pub_body
    assert "## 3. 估值模型、假設與情境分析" in pub_body
    assert "## 前後變化" in pub_body
    assert "無研究變化" in pub_body
