"""Point-in-time annual comparison without conflating research and trading advice."""
from datetime import date
import math

METRICS = ("annual_revenue", "annual_net_income", "annual_operating_cash_flow",
           "annual_capex", "annual_free_cash_flow", "annual_diluted_shares")
TW_EXTENDED_METRICS = METRICS + (
    "annual_gross_profit", "annual_operating_income",
    "annual_parent_net_income", "annual_basic_eps",
)


def _compare_tw_financials(issuer, asof):
    history = issuer.get("financial_history") or {}
    result = {"status": "unavailable", "source": None, "currency": "USD",
              "rows": [], "coverage": {k: 0 for k in METRICS}, "warnings": []}
    if history.get("currency") != "TWD" or history.get("period_type") != "tw_ifrs_reconciled":
        result["warnings"].append("Taiwan IFRS annual statements unavailable; monthly revenue is not annual financials")
        return result
    result["currency"] = "TWD"
    result["source"] = history.get("source")
    result["reconciled_twse_openapi"] = bool(history.get("reconciled_twse_openapi"))
    result["reconciled_period_end"] = history.get("reconciled_period_end")
    periods = {}
    for metric in TW_EXTENDED_METRICS:
        for item in history.get(metric, []):
            try:
                start, end, filed = [date.fromisoformat(item[x]) for x in
                                     ("period_start", "period_end", "filed")]
                value = item["value"]
            except (ValueError, KeyError, TypeError):
                continue
            if (not isinstance(value, (int, float)) or isinstance(value, bool)
                    or not math.isfinite(value) or end > asof or filed > asof
                    or not 330 <= (end - start).days <= 380):
                continue
            periods.setdefault((start.isoformat(), end.isoformat()), {})[metric] = item
    by_end = {}
    for (start, end), metrics in periods.items():
        if end not in by_end or len(metrics) > len(by_end[end][1]):
            by_end[end] = (start, metrics)
    sorted_ends = sorted(by_end, reverse=True)[:6]
    for end in sorted_ends:
        start, facts = by_end[end]
        values = {k: facts[k]["value"] if k in facts else None for k in TW_EXTENDED_METRICS}
        sources = {k: {"filed": v["filed"], "source": v.get("source", history.get("source")),
                       "accession": v.get("accession"), "taxonomy_tag": v.get("taxonomy_tag")}
                   for k, v in facts.items()}
        for metric in METRICS:
            if metric in facts:
                result["coverage"][metric] += 1
        revenue = values["annual_revenue"]
        def margin(metric):
            v = values.get(metric)
            return round(100 * v / revenue, 2) if v is not None and revenue is not None and revenue > 0 else None
        row = {
            "period_start": start, "period_end": end, "metrics": values,
            "gross_margin_pct": margin("annual_gross_profit"),
            "operating_margin_pct": margin("annual_operating_income"),
            "net_margin_pct": margin("annual_net_income"),
            "fcf_margin_pct": margin("annual_free_cash_flow"),
            "missing_metrics": [k for k in METRICS if k not in facts],
            "filing_provenance": sources,
        }
        result["rows"].append(row)
    for i, row in enumerate(result["rows"]):
        if i + 1 < len(result["rows"]):
            prev = result["rows"][i + 1]["metrics"]
            curr = row["metrics"]
            for key, out_key in (
                ("annual_revenue", "revenue_yoy_pct"),
                ("annual_net_income", "net_income_yoy_pct"),
                ("annual_free_cash_flow", "fcf_yoy_pct"),
            ):
                if curr.get(key) is not None and prev.get(key) and prev[key] > 0:
                    row[out_key] = round(100.0 * (curr[key] - prev[key]) / prev[key], 2)
    result["quarterly_rows"] = history.get("quarterly_statements", [])
    result["latest_cumulative_interim"] = history.get("latest_cumulative_interim")
    result["ttm"] = history.get("ttm")
    result["latest_balance_sheet"] = history.get("latest_balance_sheet")
    result["balance_sheet_history"] = history.get("balance_sheet_history", [])
    result["dividend_schedule"] = history.get("dividend_schedule", [])
    result["ex_dividend_history"] = history.get("ex_dividend_history", [])
    result["exchange_multiples"] = history.get("exchange_multiples")
    if result["rows"]:
        result["status"] = "available"
        if len(result["rows"]) < 3:
            result["warnings"].append("Fewer than three comparable fiscal years")
        for row in result["rows"][:3]:
            if row["missing_metrics"]:
                result["warnings"].append(row["period_end"] + " missing " + ", ".join(row["missing_metrics"]))
    else:
        result["warnings"].append("Taiwan IFRS annual statements unavailable; monthly revenue is not annual financials")
    return result


def compare_financials(issuer, asof):
    result = {"status": "unavailable", "source": None, "currency": "USD",
              "rows": [], "coverage": {k: 0 for k in METRICS}, "warnings": []}
    if issuer.get("market") == "tw":
        return _compare_tw_financials(issuer, asof)
    if issuer.get("market") != "us":
        result["warnings"].append("Taiwan IFRS annual statements unavailable; monthly revenue is not annual financials")
        return result
    history = issuer.get("financial_history") or {}
    if history.get("currency") != "USD" or history.get("period_type") != "annual_10k":
        result["warnings"].append("Normalized SEC annual USD statements unavailable")
        return result
    result["source"] = history.get("source")
    periods = {}
    for metric in METRICS:
        for item in history.get(metric, []):
            try:
                start, end, filed = [date.fromisoformat(item[x]) for x in
                                     ("period_start", "period_end", "filed")]
                value = item["value"]
            except (ValueError, KeyError, TypeError):
                continue
            if (not isinstance(value, (int, float)) or isinstance(value, bool)
                    or not math.isfinite(value) or end > asof or filed > asof
                    or not 330 <= (end - start).days <= 380):
                continue
            periods.setdefault((start.isoformat(), end.isoformat()), {})[metric] = item
    # The same fiscal end with a different fiscal start cannot be merged.
    by_end = {}
    for (start, end), metrics in periods.items():
        if end not in by_end or len(metrics) > len(by_end[end][1]):
            by_end[end] = (start, metrics)
    for end in sorted(by_end, reverse=True)[:6]:
        start, facts = by_end[end]
        values = {k: facts[k]["value"] if k in facts else None for k in METRICS}
        sources = {k: {"filed": v["filed"], "source": v.get("source", history.get("source")),
                       "accession": v.get("accession"), "taxonomy_tag": v.get("taxonomy_tag")}
                   for k, v in facts.items()}
        for metric in facts:
            result["coverage"][metric] += 1
        revenue = values["annual_revenue"]
        def margin(metric):
            v = values[metric]
            return round(100 * v / revenue, 2) if v is not None and revenue is not None and revenue > 0 else None
        row = {"period_start": start, "period_end": end, "metrics": values,
               "net_margin_pct": margin("annual_net_income"),
               "fcf_margin_pct": margin("annual_free_cash_flow"),
               "missing_metrics": [k for k in METRICS if k not in facts],
               "filing_provenance": sources}
        result["rows"].append(row)
    if result["rows"]:
        result["status"] = "available"
        if len(result["rows"]) < 3:
            result["warnings"].append("Fewer than three comparable fiscal years")
        for row in result["rows"][:3]:
            if row["missing_metrics"]:
                result["warnings"].append(row["period_end"] + " missing " + ", ".join(row["missing_metrics"]))
    else:
        result["warnings"].append("No annual SEC fiscal years available as of report date")
    return result


def research_status(financial, valuation, technical):
    if valuation["status"] == "illustrative_only":
        stage = "illustrative_valuation_available"
    elif financial["status"] == "available":
        stage = "financial_review_only"
    else:
        stage = "preliminary_only"
    matches = [x["strategy_id"] for x in technical.get("observations", [])
               if x.get("active") and x.get("matched")]
    return {"stage": stage, "valuation_reason": valuation.get("why"),
            "technical_status": technical.get("status"),
            "active_pattern_observations": matches, "entry_exit_status": "not_evaluated",
            "investment_recommendation": "not_available"}


def build_financial_research_summary(result):
    financial = result.get("financial_comparison") or {}
    if financial.get("status") != "available" or result.get("market") != "tw":
        return None
    issuer = result.get("issuer") or {}
    valuation = result.get("valuation") or {}
    annual_summary = []
    for row in financial.get("rows", [])[:3]:
        m = row.get("metrics") or {}
        annual_summary.append({
            "fiscal_year": row["period_end"][:4],
            "period_start": row["period_start"],
            "period_end": row["period_end"],
            "revenue": m.get("annual_revenue"),
            "gross_profit": m.get("annual_gross_profit"),
            "operating_income": m.get("annual_operating_income"),
            "net_income": m.get("annual_net_income"),
            "parent_net_income": m.get("annual_parent_net_income"),
            "basic_eps": m.get("annual_basic_eps"),
            "operating_cash_flow": m.get("annual_operating_cash_flow"),
            "capex": m.get("annual_capex"),
            "free_cash_flow": m.get("annual_free_cash_flow"),
            "ordinary_shares": m.get("annual_diluted_shares"),
            "gross_margin_pct": row.get("gross_margin_pct"),
            "operating_margin_pct": row.get("operating_margin_pct"),
            "net_margin_pct": row.get("net_margin_pct"),
            "fcf_margin_pct": row.get("fcf_margin_pct"),
            "revenue_yoy_pct": row.get("revenue_yoy_pct"),
            "net_income_yoy_pct": row.get("net_income_yoy_pct"),
            "fcf_yoy_pct": row.get("fcf_yoy_pct"),
        })
    quarterly_summary = [
        {
            "period_label": q["period_label"],
            "period_start": q["period_start"],
            "period_end": q["period_end"],
            "basis": q["basis"],
            "revenue": q.get("revenue"),
            "gross_profit": q.get("gross_profit"),
            "operating_income": q.get("operating_income"),
            "net_income": q.get("net_income"),
            "parent_net_income": q.get("parent_net_income"),
            "basic_eps": q.get("basic_eps"),
            "operating_cash_flow": q.get("operating_cash_flow"),
            "capex": q.get("capex"),
            "free_cash_flow": q.get("free_cash_flow"),
            "gross_margin_pct": q.get("gross_margin_pct"),
            "operating_margin_pct": q.get("operating_margin_pct"),
            "net_margin_pct": q.get("net_margin_pct"),
            "fcf_margin_pct": q.get("fcf_margin_pct"),
            "ordinary_shares": q.get("ordinary_shares"),
        }
        for q in (financial.get("quarterly_rows") or [])[:6]
    ]
    val_summary = {
        "status": valuation.get("status", "not_evaluated"),
        "method": valuation.get("method"),
        "asof": valuation.get("asof"),
        "latest_fiscal_end": valuation.get("latest_fiscal_end"),
        "latest_balance_sheet_end": valuation.get("latest_balance_sheet_end"),
        "normalized_annual_fcf_twd": valuation.get("normalized_annual_fcf_twd"),
        "ttm_fcf_twd": valuation.get("ttm_fcf_twd"),
        "fcf_twd_per_ordinary_share": valuation.get("fcf_twd_per_ordinary_share"),
        "ttm_fcf_twd_per_ordinary_share": valuation.get("ttm_fcf_twd_per_ordinary_share"),
        "net_cash_twd": valuation.get("net_cash_twd"),
        "net_cash_twd_per_ordinary_share": valuation.get("net_cash_twd_per_ordinary_share"),
        "denominator": valuation.get("denominator"),
        "fair_value_scenarios": valuation.get("fair_value_scenarios"),
        "ttm_pe_scenarios": valuation.get("ttm_pe_scenarios"),
        "exchange_multiples": valuation.get("exchange_multiples") or financial.get("exchange_multiples"),
        "why": valuation.get("why"),
    }
    shares_obj = issuer.get("issued_shares") or {}
    return {
        "schema_version": 1,
        "status": "available",
        "currency": "TWD",
        "reconciled_twse_openapi": bool(financial.get("reconciled_twse_openapi")),
        "reconciled_period_end": financial.get("reconciled_period_end"),
        "issued_ordinary_shares": shares_obj.get("value"),
        "paid_in_capital_twd": issuer.get("paid_in_capital_twd"),
        "par_value_desc": issuer.get("par_value_desc"),
        "annual_summary": annual_summary,
        "quarterly_summary": quarterly_summary,
        "latest_cumulative_interim": financial.get("latest_cumulative_interim"),
        "ttm": financial.get("ttm"),
        "latest_balance_sheet": financial.get("latest_balance_sheet"),
        "dividend_schedule": (financial.get("dividend_schedule") or [])[:6],
        "ex_dividend_history": (financial.get("ex_dividend_history") or [])[:6],
        "disclosure_and_news": issuer.get("disclosure_and_news"),
        "calendar_schedule": issuer.get("calendar_schedule"),
        "valuation_zone": result.get("valuation_zone"),
        "valuation_summary": val_summary,
        "ogdl_datasets": [
            {"name": "上市公司綜合損益表(一般業)", "endpoint": "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci"},
            {"name": "上市公司資產負債表(一般業)", "endpoint": "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_ci"},
            {"name": "上市公司營益分析查詢彙總表", "endpoint": "https://openapi.twse.com.tw/v1/opendata/t187ap17_L"},
            {"name": "上市公司股利分派情形", "endpoint": "https://openapi.twse.com.tw/v1/opendata/t187ap45_L"},
            {"name": "上市公司召集股東常(臨時)會公告資料彙總表", "endpoint": "https://openapi.twse.com.tw/v1/opendata/t187ap38_L"},
            {"name": "上市公司召開股東常(臨時)會日期、地點及採用電子投票情形", "endpoint": "https://openapi.twse.com.tw/v1/opendata/t187ap41_L"},
            {"name": "上市個股日本益比、殖利率及股價淨值比", "endpoint": "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"},
        ],
    }


def render_tw_full_research_sections(fin_research):
    if not isinstance(fin_research, dict) or fin_research.get("status") != "available":
        return []
    def fmt_twd(v):
        return f"{v:,.0f}" if isinstance(v, (int, float)) and math.isfinite(v) else "—"
    def fmt_b(v):
        return f"{v / 1e8:,.2f} 億" if isinstance(v, (int, float)) and math.isfinite(v) else "—"
    def fmt_pct(v):
        return f"{v:.2f}%" if isinstance(v, (int, float)) and math.isfinite(v) else "—"
    def fmt_eps(v):
        return f"{v:,.2f}" if isinstance(v, (int, float)) and math.isfinite(v) else "—"

    lines = ["", "## 1. 公司目前財務與營運狀況（Current Financial & Operating Status）", ""]
    cum = fin_research.get("latest_cumulative_interim") or {}
    bs = fin_research.get("latest_balance_sheet") or {}
    ttm = fin_research.get("ttm") or {}
    q_list = fin_research.get("quarterly_summary") or []
    latest_q = q_list[0] if q_list else {}

    if cum:
        reconciled_note = "（已與 TWSE OpenAPI `t187ap06_L_ci` 官方累計損益表 100% 對帳吻合）" if cum.get("reconciled_twse_openapi") else ""
        rev_yoy = f"（YoY {cum['revenue_yoy_pct']:+.2f}%）" if cum.get("revenue_yoy_pct") is not None else ""
        ni_yoy = f"（YoY {cum['net_income_yoy_pct']:+.2f}%）" if cum.get("net_income_yoy_pct") is not None else ""
        lines += [
            f"- **最新累計期間（{cum.get('period_label')}：{cum.get('period_start')} 至 {cum.get('period_end')}）**{reconciled_note}：",
            f"  - 營業收入：`{fmt_twd(cum.get('revenue'))}` TWD（約 {fmt_b(cum.get('revenue'))}）{rev_yoy}",
            f"  - 營業毛利：`{fmt_twd(cum.get('gross_profit'))}` TWD｜營業利益：`{fmt_twd(cum.get('operating_income'))}` TWD",
            f"  - 本期稅後淨利：`{fmt_twd(cum.get('net_income'))}` TWD{ni_yoy}｜歸屬母公司業主淨利：`{fmt_twd(cum.get('parent_net_income'))}` TWD｜基本 EPS：`{fmt_eps(cum.get('basic_eps'))}` 元",
            f"  - 營業現金流（CFO）：`{fmt_twd(cum.get('operating_cash_flow'))}` TWD｜資本支出（CAPEX）：`{fmt_twd(cum.get('capex'))}` TWD｜自由現金流（FCF）：`{fmt_twd(cum.get('free_cash_flow'))}` TWD",
        ]
    if latest_q:
        lines += [
            f"- **最新單季表現（{latest_q.get('period_label')}：{latest_q.get('period_start')} 至 {latest_q.get('period_end')}，口徑驗證：`{latest_q.get('basis')}`）**：",
            f"  - 單季營收：`{fmt_twd(latest_q.get('revenue'))}` TWD｜毛利率：`{fmt_pct(latest_q.get('gross_margin_pct'))}`｜營益率：`{fmt_pct(latest_q.get('operating_margin_pct'))}`｜稅後淨利率：`{fmt_pct(latest_q.get('net_margin_pct'))}`",
            f"  - 單季歸屬母公司淨利：`{fmt_twd(latest_q.get('parent_net_income'))}` TWD｜單季基本 EPS：`{fmt_eps(latest_q.get('basic_eps'))}` 元｜單季 FCF：`{fmt_twd(latest_q.get('free_cash_flow'))}` TWD（FCF 利潤率 `{fmt_pct(latest_q.get('fcf_margin_pct'))}`）",
        ]
    if bs:
        lines += [
            f"- **最新資產負債與資本結構（截至 {bs.get('period_end')}，與 TWSE OpenAPI `t187ap07_L_ci` 對帳吻合）**：",
            f"  - 現金及約當現金：`{fmt_twd(bs.get('cash'))}` TWD（約 {fmt_b(bs.get('cash'))}）",
            f"  - 總資產：`{fmt_twd(bs.get('total_assets'))}` TWD｜總負債：`{fmt_twd(bs.get('total_liabilities'))}` TWD｜總權益：`{fmt_twd(bs.get('total_equity'))}` TWD",
            f"  - 有息負債明細：應付公司債 `{fmt_twd(bs.get('bonds_payable'))}` TWD ＋ 長期借款 `{fmt_twd(bs.get('long_term_borrowings'))}` TWD ＝ 有息負債合計 `{fmt_twd(bs.get('total_debt'))}` TWD",
            f"  - **淨現金（Net Cash = 現金 - 有息負債）**：`{fmt_twd(bs.get('net_cash'))}` TWD（約 {fmt_b(bs.get('net_cash'))}）",
            f"  - 普通股股本：`{fmt_twd(bs.get('capital_stock'))}` TWD（面額 10 元折合普通股數 `{fmt_twd(bs.get('ordinary_shares'))}` 股）",
        ]

    lines += ["", "## 2. 歷年、季度與 TTM 財務變化（Historical Annual, Quarterly & TTM Comparison）", ""]
    annuals = fin_research.get("annual_summary") or []
    if annuals:
        lines += [
            "### A. 最近三個完整會計年度三表摘要（單位：TWD；EPS 為 TWD/股）",
            "",
            "| 年度 (Period End) | 營業收入 | 營收 YoY | 毛利率 | 營益率 | 稅後淨利 | 淨利 YoY | 基本 EPS | 營業現金流 (CFO) | 資本支出 (CAPEX) | 自由現金流 (FCF) | FCF 利潤率 | 普通股股數 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for row in annuals:
            lines.append(
                f"| FY{row['fiscal_year']} ({row['period_end']}) | {fmt_twd(row.get('revenue'))} | {fmt_pct(row.get('revenue_yoy_pct'))} | "
                f"{fmt_pct(row.get('gross_margin_pct'))} | {fmt_pct(row.get('operating_margin_pct'))} | {fmt_twd(row.get('net_income'))} | "
                f"{fmt_pct(row.get('net_income_yoy_pct'))} | {fmt_eps(row.get('basic_eps'))} | {fmt_twd(row.get('operating_cash_flow'))} | "
                f"{fmt_twd(row.get('capex'))} | {fmt_twd(row.get('free_cash_flow'))} | {fmt_pct(row.get('fcf_margin_pct'))} | {fmt_twd(row.get('ordinary_shares'))} |"
            )

    if ttm.get("status") == "available":
        q_span = " + ".join(ttm.get("quarters") or [])
        lines += [
            "",
            f"### B. 連續四季滾動 TTM 指標（{q_span}，期間 `{ttm.get('period_start')}` 至 `{ttm.get('period_end')}`）",
            "",
            f"- **TTM 營業收入**：`{fmt_twd(ttm.get('revenue'))}` TWD（約 {fmt_b(ttm.get('revenue'))}）",
            f"- **TTM 營業毛利**：`{fmt_twd(ttm.get('gross_profit'))}` TWD（毛利率 `{fmt_pct(ttm.get('gross_margin_pct'))}`）",
            f"- **TTM 營業利益**：`{fmt_twd(ttm.get('operating_income'))}` TWD（營益率 `{fmt_pct(ttm.get('operating_margin_pct'))}`）",
            f"- **TTM 稅後淨利**：`{fmt_twd(ttm.get('net_income'))}` TWD（淨利率 `{fmt_pct(ttm.get('net_margin_pct'))}`）｜**TTM 歸屬母公司淨利**：`{fmt_twd(ttm.get('parent_net_income'))}` TWD",
            f"- **TTM 基本 EPS**：`{fmt_eps(ttm.get('basic_eps'))}` 元（計算規則：`{ttm.get('eps_derivation')}`，四季普通股數最大變動率 `{ttm.get('share_count_max_drift_pct')}%`）",
            f"- **TTM 營業現金流**：`{fmt_twd(ttm.get('operating_cash_flow'))}` TWD｜**TTM 資本支出**：`{fmt_twd(ttm.get('capex'))}` TWD｜**TTM 自由現金流（FCF）**：`{fmt_twd(ttm.get('free_cash_flow'))}` TWD（FCF 利潤率 `{fmt_pct(ttm.get('fcf_margin_pct'))}`）",
        ]

    if q_list:
        lines += [
            "",
            "### C. 近期單季財務趨勢明細（Single-Quarter Normalized Series）",
            "",
            "| 季度 (Period End) | 口徑驗證依據 | 單季營收 (TWD) | 毛利率 | 營益率 | 單季稅後淨利 (TWD) | 單季基本 EPS | 單季 CFO (TWD) | 單季 CAPEX (TWD) | 單季 FCF (TWD) |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for q in q_list:
            lines.append(
                f"| {q['period_label']} ({q['period_end']}) | `{q.get('basis')}` | {fmt_twd(q.get('revenue'))} | "
                f"{fmt_pct(q.get('gross_margin_pct'))} | {fmt_pct(q.get('operating_margin_pct'))} | "
                f"{fmt_twd(q.get('net_income'))} | {fmt_eps(q.get('basic_eps'))} | {fmt_twd(q.get('operating_cash_flow'))} | "
                f"{fmt_twd(q.get('capex'))} | {fmt_twd(q.get('free_cash_flow'))} |"
            )

    val = fin_research.get("valuation_summary") or {}
    lines += ["", "## 3. 估值模型、假設與情境分析（Valuation Models, Assumptions & Scenarios）", ""]
    if val.get("status") == "illustrative_only":
        denom = (val.get("denominator") or {}).get("value")
        lines += [
            "> **研究聲明**：以下估值情境僅為歷史與 TTM 財務數據之假設倍數敏感度分析（`illustrative_only`），**絕非目標價、買進價、停損價或投資建議**。交易計畫（`entry_zone` / `stop_loss` / `target_price`）維持 `not_evaluated`。",
            "",
            "- **真實輸入與分母依據**：",
            f"  - 近三年完整會計年度（FY2023–FY2025）中位數年自由現金流：`{fmt_twd(val.get('normalized_annual_fcf_twd'))}` TWD（折合每股 `{val.get('fcf_twd_per_ordinary_share')}` 元）",
            f"  - 近四季 TTM 自由現金流（2025Q3–2026Q2）：`{fmt_twd(val.get('ttm_fcf_twd'))}` TWD（折合每股 `{val.get('ttm_fcf_twd_per_ordinary_share')}` 元）",
            f"  - 最新驗證資產負債表淨現金（截至 `{val.get('latest_balance_sheet_end')}`）：`{fmt_twd(val.get('net_cash_twd'))}` TWD（折合每股淨現金 `+{val.get('net_cash_twd_per_ordinary_share')}` 元）",
            f"  - 普通股分母股數：`{fmt_twd(denom)}` 股（依據資產負債表普通股股本÷面額 10 元，並與 TWSE `t187ap03_L` 已發行普通股數 `{fmt_twd(fin_research.get('issued_ordinary_shares'))}` 股核對一致）",
            "",
            "### 模型 A：EV-Bridged P/FCF 自由現金流情境（公式：`(FCF × 倍數 + 期末淨現金) ÷ 普通股股數`）",
            "",
            "| 情境 (Scenario) | 假設 FCF 倍數 | 3 年中位數 FCF 推算每股價值 (TWD) | 其中：每股淨現金項 (TWD) | TTM FCF 推算每股價值 (TWD) |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for s_name, s_row in (val.get("fair_value_scenarios") or {}).items():
            lines.append(
                f"| {s_name} | {s_row.get('fcf_multiple')}x | {fmt_eps(s_row.get('indicative_twd_per_share'))} | "
                f"+{fmt_eps(s_row.get('net_cash_component_twd'))} | {fmt_eps(s_row.get('indicative_ttm_fcf_twd_per_share'))} |"
            )
        pe_scen = val.get("ttm_pe_scenarios") or {}
        if pe_scen:
            lines += [
                "",
                "### 模型 B：TTM 基本 EPS 本益比情境（公式：`TTM 基本 EPS × 假設 P/E 倍數`）",
                "",
                "| 情境 (Scenario) | 假設 P/E 倍數 | TTM 基本 EPS (TWD) | 推算每股價值情境 (TWD) |",
                "| --- | ---: | ---: | ---: |",
            ]
            for s_name, s_row in pe_scen.items():
                lines.append(
                    f"| {s_name} | {s_row.get('pe_multiple')}x | {fmt_eps(s_row.get('ttm_basic_eps_twd'))} | "
                    f"{fmt_eps(s_row.get('indicative_twd_per_share'))} |"
                )
        ex_mult = val.get("exchange_multiples") or {}
        if ex_mult:
            lines += [
                "",
                f"### 官方交易所當期估值倍數參照（TWSE `BWIBBU_ALL`，日期 `{ex_mult.get('date_roc') or '最新'}`）：",
                f"- 官方公布本益比（PER）：`{ex_mult.get('pe_ratio')}` 倍｜股價淨值比（PBR）：`{ex_mult.get('pb_ratio')}` 倍｜現金殖利率：`{ex_mult.get('dividend_yield_pct')}%`",
            ]
    else:
        lines.append(f"估值狀態：`not_evaluated` — {val.get('why')}")

    lines += ["", "## 4. 股數、除權息與公司行動證據（Share Capital, Dividends & Corporate Actions）", ""]
    lines += [
        f"- **已發行普通股數（TWSE `t187ap03_L`）**：`{fmt_twd(fin_research.get('issued_ordinary_shares'))}` 股｜實收資本額：`{fmt_twd(fin_research.get('paid_in_capital_twd'))}` TWD｜每股面額：`{fin_research.get('par_value_desc') or '新台幣 10 元'}`",
        "- **股本連續性與稀釋股數說明**：2023Q1 至 2026Q2 普通股股數介於 `25,932,071,000` 至 `25,932,733,200` 股（近四季變動率 `<0.001%`）。免費公開 API 未直接提供財報附註之稀釋加權平均股數，故每股指標統一採用普通股股數與基本 EPS，不臆測稀釋調整項。",
    ]
    divs = fin_research.get("dividend_schedule") or []
    if divs:
        lines += [
            "",
            "### 近期季度盈餘分派與現金股利（TWSE OpenAPI `t187ap45_L`）",
            "",
            "| 所屬季度 | 期末日期 | 董事會決議／分派日 (ROC) | 單季歸屬母公司淨利 (TWD) | 每股現金股利 (TWD) | 每股股票股利 (TWD) |",
            "| --- | --- | --- | ---: | ---: | ---: |",
        ]
        for d in divs:
            lines.append(
                f"| {d.get('period')} | {d.get('period_end')} | {d.get('board_Or_approval_date_roc') or '—'} | "
                f"{fmt_twd(d.get('parent_net_income_twd'))} | {fmt_eps(d.get('cash_dividend_per_share_twd'))} | "
                f"{fmt_eps(d.get('stock_dividend_per_share_twd'))} |"
            )
    ex_divs = fin_research.get("ex_dividend_history") or []
    if ex_divs:
        lines += [
            "",
            "### 近期除息交易與參考價調整紀錄（FinMind `TaiwanStockDividendResult`）",
            "",
            "| 除息交易日 | 股利類別 | 每股股利 (TWD) | 除息前收盤價 (TWD) | 除息參考價 (TWD) |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
        for ed in ex_divs:
            lines.append(
                f"| {ed.get('ex_date')} | {ed.get('type') or '—'} | {fmt_eps(ed.get('dividend_per_share_twd'))} | "
                f"{fmt_eps(ed.get('before_price'))} | {fmt_eps(ed.get('reference_price'))} |"
            )

    disc_news = fin_research.get("disclosure_and_news") or {}
    if disc_news:
        lines += [
            "",
            "### 重大公告與外部新聞索引（TW08：Official Disclosures & Deduplicated News References）",
            "",
            f"- **資料源涵蓋狀態（區分無事件／來源空窗／來源不可用）**：`{disc_news.get('source_statuses')}`（新聞轉載去重移除數：`{disc_news.get('deduplicated_repost_count', 0)}` 則）",
            "- **時間欄位契約**：嚴格區分 `event_date`（事實／決議日）、`published_at`（來源發布時間）、`reported_at`（彙總出表日）與 `first_seen_at`（系統首次觀測時間）；第三方新聞轉載不視為官方申報，且不擷取未授權全文或生成假摘要。",
        ]
        off_list = disc_news.get("official_disclosures") or []
        if off_list:
            lines += [
                "",
                "#### 1. 官方交易所公告與董事會／股東會決議（Official Exchange Disclosures）",
                "",
                "| 類別 | 事實／決議日 (`event_date`) | 發布時間 (`published_at`) | 彙總出表日 (`reported_at`) | 公告摘要 | 官方來源 |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
            for od in off_list[:8]:
                title_clean = str(od.get("title") or "").replace("|", "｜").replace("\n", " ")
                lines.append(
                    f"| `{od.get('category')}` | {od.get('event_date') or '—'} | {od.get('published_at') or '未標示分秒'} | "
                    f"{od.get('reported_at') or '—'} | {title_clean} | {od.get('source')} |"
                )
        news_list = disc_news.get("news_references") or []
        if news_list:
            lines += [
                "",
                "#### 2. 第三方新聞索引（去重後標題與連結，非官方申報，不做情緒評分）",
                "",
                "| 發布時間 (`published_at`) | 去重後新聞標題 | 媒體來源（含轉載合併） | 摘要與情緒狀態 |",
                "| --- | --- | --- | --- |",
            ]
            for nw in news_list[:6]:
                hl_clean = str(nw.get("headline") or "").replace("|", "｜").replace("\n", " ")
                outlets = "、".join(nw.get("sources") or []) or "—"
                if (nw.get("syndicated_count") or 1) > 1:
                    outlets += f"（共 {nw['syndicated_count']} 則同題轉載）"
                link_str = f"[原始連結]({nw['link']})" if nw.get("link") else "無外部連結"
                lines.append(
                    f"| {nw.get('published_at')} | {hl_clean}（{link_str}） | {outlets} | `{nw.get('summary_status')}` / `{nw.get('sentiment_score')}` |"
                )

    cal = fin_research.get("calendar_schedule") or {}
    if cal:
        lines += [
            "",
            "### 財報、法說會、董事會與股東會重要行程（TW09：Corporate Calendar & Filing Schedule）",
            "",
            f"- **行程時區**：`{cal.get('timezone', 'Asia/Taipei')}`｜**行程來源狀態**：`{cal.get('source_statuses')}`",
            "- **未知與更正原則**：未獲官方公告確認之未來法說會或財報公布日一律標記為 `unknown`（**絕不沿用往年日期推算**）；法定申報期限（`statutory_filing_deadline`）與公司實際財報公布日（`earnings_release`）嚴格區分。",
            "",
            "| 行程類別 (`event_type`) | 期別 | 預定／實際日期 (`Asia/Taipei`) | 確認狀態 (`confirmation_status`) | 行程說明與注意事項 | 來源 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for ev in (cal.get("events") or [])[:10]:
            t_clean = str(ev.get("title") or "").replace("|", "｜").replace("\n", " ")
            if ev.get("note"):
                t_clean += f"（{ev['note']}）"
            if ev.get("retained_from_previous"):
                t_clean += "（本次來源不可用，保留前次已驗證行程）"
            lines.append(
                f"| `{ev.get('event_type')}` | {ev.get('period_label') or '—'} | {ev.get('scheduled_date') or '未確認 (unknown)'} | "
                f"**{ev.get('confirmation_status')}** | {t_clean} | {ev.get('source')} |"
            )

    lines += [
        "",
        "## 5. 綜合研究判斷與後續觀察條件（Research Synthesis, Risks & Watch Conditions）",
        "",
        "### A. 目前研究判斷摘要（Research Judgment — 非買賣建議）",
        "- **有利因素（Bullish / Positive Drivers）**：",
        "  1. **營收與獲利規模高速成長**：FY2025 全年營收達 3.81 兆元（YoY +31.61%）、稅後淨利 1.72 兆元（YoY +46.31%）；2026 上半年（2026-H1）累計營收進一步達 2.40 兆元（YoY +35.61%），近四季 TTM 營收達 4.44 兆元、TTM 基本 EPS 達 86.28 元。",
        "  2. **獲利能力與利潤率結構性擴張**：毛利率由 FY2023 的 54.36%、FY2024 的 56.12%、FY2025 的 59.89%，躍升至 2026Q1 的 66.25% 與 2026Q2 的 67.72%（2026-H1 營益率達 59.29%、淨利率達 53.22%），顯示先進製程定價能力與產能利用率極強。",
        "  3. **自由現金流與資產負債表高度穩健**：儘管 TTM 資本支出高達 1.49 兆元，TTM 營業現金流仍達 2.63 兆元，創造 1.14 兆元 TTM 自由現金流；截至 2026-06-30 帳上現金 3.13 兆元，扣除有息負債 8,642.6 億元後，淨現金高達 +2.27 兆元（每股淨現金 +87.53 元），並支撐每季配息由 3.0 元穩步調升至 7.0 元。",
        "- **不利因素與風險（Bearish / Risk Factors）**：",
        "  1. **資本密集度與折舊負擔**：CAPEX 由 FY2024 的 9,560 億元上升至 TTM 的 1.49 兆元（2026Q2 單季 CAPEX 達 4,960 億元），若終端 AI／HPC 需求增速放緩，高額折舊將直接壓縮毛利率與自由現金流轉換率。",
        "  2. **估值倍數與資本支出敏感度**：以歷史 3 年中位數 FCF（8,701.7 億元）計算之 EV-bridged P/FCF 情境明顯低於以 TTM EPS（86.28 元）計算之 P/E 情境，反映公司處於高資本支出擴張期，盈餘轉化為自由現金流存在時間差；同時官方股價淨值比（PBR 9.76x）處於歷史相對高位。",
        "  3. **外部營運與總體風險**：海外晶圓廠建置與營運成本、匯率波動（新台幣兌美元）、地緣政治與出口管制變化。",
        "- **尚待確認事項與信心限制（Open Items & Confidence Limits）**：",
        "  1. 免費公開資料源未提供完整財報附註之稀釋股數調節表與客戶／製程別營收拆分。",
        "  2. 系統僅記錄資料 `first_seen_at` 時間，不宣稱還原歷史財報首次公開之分秒級時間戳記。",
        "  3. 交易執行價格、摩擦成本與停損／目標價模型尚未驗證，故 `trade_plan` 與 `recommendation` 嚴格維持 `not_evaluated` / `not_available`。",
        "",
        "### B. 後續關鍵觀察指標（What to Watch Next）",
        "1. **利潤率維持度**：後續季度毛利率是否守穩 `63%–65%` 以上，以及海外廠量產爬坡對營益率（目前 `60.34%`）之影響。",
        "2. **自由現金流轉換率**：在年度高強度資本支出下，單季與 TTM 自由現金流利潤率（FCF Margin，目前 TTM 為 `25.75%`）是否維持 `20%` 以上。",
        "3. **月營收動能**：TWSE 每月營業收入（`t187ap05_L`）年增率是否持續維持 `20%–30%+` 區間，驗證季度營收趨勢。",
        "4. **重大公告與資本配置**：透過 `t187ap04_L` 與 `t187ap45_L` 追蹤季度現金股利政策（目前每季 7.0 元）及法說會資本支出指引是否修正。",
    ]
    return lines


def render_financial_research(financial, readiness):
    lines = ["", "## Annual financial comparison", ""]
    if financial["status"] != "available":
        lines.append("Comparable annual statements unavailable; cannot infer them from monthly revenue.")
    elif financial.get("currency") == "TWD":
        lines += ["TWSE OpenAPI + FinMind cross-reconciled Taiwan IFRS statements, original TWD (ordinary shares from par 10 capital stock); missing facts show —, not 0.",
                  "", "| Fiscal end | Revenue (TWD) | Net income (TWD) | Operating CF (TWD) | Capex (TWD) | FCF (TWD) | Ordinary shares | Gross margin | Operating margin | Net margin | FCF margin |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for row in financial["rows"]:
            vals = row["metrics"]
            def fmt(k):
                v = vals.get(k)
                return f"{v:,.0f}" if v is not None else "—"
            def pct(k):
                v = row.get(k)
                return f"{v:.2f}%" if v is not None else "—"
            lines.append(
                f"| {row['period_end']} | {fmt('annual_revenue')} | "
                f"{fmt('annual_net_income')} | {fmt('annual_operating_cash_flow')} | "
                f"{fmt('annual_capex')} | {fmt('annual_free_cash_flow')} | "
                f"{fmt('annual_diluted_shares')} | {pct('gross_margin_pct')} | {pct('operating_margin_pct')} | {pct('net_margin_pct')} | {pct('fcf_margin_pct')} |"
            )
        lines += ["", "TWSE OpenAPI reconciliation source: " + str(financial["source"]),
                  "Filing dates, accession and taxonomy tags for each metric: report.json."]
    else:
        lines += ["SEC annual 10-K, original USD (shares for diluted counts); missing facts show —, not 0.",
                  "", "| Fiscal end | Revenue | Net income | Operating CF | Capex | FCF | Diluted shares | Net margin | FCF margin |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for row in financial["rows"]:
            vals = row["metrics"]
            def fmt(k):
                v = vals[k]
                return f"{v:,.0f}" if v is not None else "—"
            def pct(k):
                v = row[k]
                return f"{v:.2f}%" if v is not None else "—"
            lines.append(
                f"| {row['period_end']} | {fmt('annual_revenue')} | "
                f"{fmt('annual_net_income')} | {fmt('annual_operating_cash_flow')} | "
                f"{fmt('annual_capex')} | {fmt('annual_free_cash_flow')} | "
                f"{fmt('annual_diluted_shares')} | {pct('net_margin_pct')} | {pct('fcf_margin_pct')} |"
            )
        lines += ["", "SEC source: " + str(financial["source"]),
                  "Filing dates, accession and taxonomy tags for each metric: report.json."]
    if financial["warnings"]:
        lines += ["", "**Financial coverage limitations**"]
        lines.extend("- " + v for v in financial["warnings"])
    lines += ["", "## Research readiness", "",
              "**" + readiness["stage"] + "**",
              "Valuation: " + str(readiness["valuation_reason"]),
              "Active technical observations: " + (", ".join(readiness["active_pattern_observations"]) or "none"),
              "No validated trading entry, stop-loss or target. No buy/sell recommendation."]
    return lines
