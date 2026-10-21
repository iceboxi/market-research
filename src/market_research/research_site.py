"""Self-contained static HTML dashboard generator for 2330.TW research state.

Reads validated `research-state` records (or a standalone `company_report` dict)
and produces a single dependency-free `index.html` with:
- Server-rendered initial view of the latest snapshot (searchable/testable without JS)
- Embedded JSON bundle + interactive Snapshot Time Machine & tabbed explorer
- Strict non-trading / illustrative-only boundary disclosures
"""

from __future__ import annotations

from datetime import datetime, timezone
import html
import json
from pathlib import Path
from typing import Any

from market_research.research_comparison import available, compare_snapshots
from market_research.research_snapshot import prepare_snapshot, utc


def _esc(val: Any) -> str:
    if val is None:
        return "—"
    return html.escape(str(val))


def _fmt_twd_B(val: float | int | None) -> str:
    """Format raw TWD amount into 億元 (hundred millions) with 2 decimals."""
    if val is None:
        return "—"
    return f"{float(val) / 1e8:,.2f} 億"


def _fmt_pct(val: float | int | None, signed: bool = False) -> str:
    if val is None:
        return "—"
    v = float(val)
    if signed and v > 0:
        return f"+{v:.2f}%"
    return f"{v:.2f}%"


def _fmt_num(val: float | int | None, decimals: int = 2) -> str:
    if val is None:
        return "—"
    return f"{float(val):,.{decimals}f}"


def _badge_class(status: str | None) -> str:
    s = (status or "").lower()
    if s in ("available", "completed", "acked", "delivered", "confirmed", "current", "reconciled_tw_dual_track"):
        return "badge-ok"
    if s in ("illustrative_only", "changed", "partial", "degraded", "review_only", "candidate_for_nonfinancial_research"):
        return "badge-warn"
    if s in ("not_evaluated", "not_available", "unchanged", "baseline", "no_recent_observed_events", "unknown"):
        return "badge-neutral"
    return "badge-err"


def build_site_payload(
    records: dict[str, Any] | None = None,
    *,
    branch: str = "research-state",
    latest_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the complete read-only site data bundle from state records and/or a report."""
    records = dict(records or {})
    if not records and latest_report is not None and latest_report.get("symbol") == "2330.TW":
        import os
        import re
        raw_run_id = os.getenv("GITHUB_RUN_ID", "1")
        run_id = raw_run_id if re.fullmatch(r"[0-9]{1,30}", raw_run_id) else "1"
        raw_sha = os.getenv("GITHUB_SHA") or latest_report.get("model_identity") or ("0" * 40)
        code_sha = raw_sha[:40] if re.fullmatch(r"[a-f0-9]{40,64}", str(raw_sha)) else ("0" * 40)
        gen_str = latest_report.get("generated_utc") or datetime.now(timezone.utc).isoformat()
        start_str = latest_report.get("started_utc") or gen_str
        obs_str = max(utc(gen_str), utc(start_str)).isoformat()
        snap = prepare_snapshot(
            latest_report,
            {
                "repository": os.getenv("GITHUB_REPOSITORY") or "iceboxi/market-research",
                "run_id": run_id,
                "run_attempt": int(os.getenv("GITHUB_RUN_ATTEMPT", "1") or "1"),
                "code_sha": code_sha,
                "observed_at_utc": obs_str,
            },
        )
        records = {
            f"snapshots/tw/2330.TW/{snap['id']}.json": snap,
            "subjects/tw/2330.TW.json": {
                "schema_version": 2,
                "symbol": "2330.TW",
                "issue_number": 74,
                "creation_attempted": True,
                "latest_observation_id": snap["id"],
                "last_success_id": snap["id"],
                "pending_publication_id": None,
                "published_publication_id": None,
                "pending_notification_id": None,
                "published_notification_id": None,
            },
        }

    subject = records.get("subjects/tw/2330.TW.json") or {}
    checkpoint = records.get("checkpoints/tw/2330.TW.json")
    snapshots_by_id: dict[str, dict[str, Any]] = {}
    for path, val in records.items():
        if path.startswith("snapshots/tw/2330.TW/") and isinstance(val, dict) and val.get("id"):
            snapshots_by_id[val["id"]] = val

    # Sort chronologically (oldest -> newest) to compute pairwise comparisons, then reverse for UI
    chronological = sorted(
        snapshots_by_id.values(),
        key=lambda s: (s.get("observed_at_utc") or "", s.get("id") or ""),
    )

    comparisons: dict[str, dict[str, Any]] = {}
    prev_good: dict[str, Any] | None = None
    last_good_ids: dict[str, str | None] = {
        "issuer": None,
        "monthly_revenue": None,
        "technical": None,
        "events": None,
    }
    for snap in chronological:
        sid = snap["id"]
        comp = compare_snapshots(
            prev_good,
            snap,
            last_known_good={
                k: snapshots_by_id[v]
                for k, v in last_good_ids.items()
                if v and v in snapshots_by_id
            },
        )
        cats = comp.get("categories") or []
        comp["status"] = "baseline" if cats == ["baseline"] else ("unchanged" if cats == ["unchanged"] else "changed")
        comparisons[sid] = comp
        if snap.get("execution", {}).get("status") == "completed":
            prev_good = snap
        for k in last_good_ids:
            if available(snap, k):
                last_good_ids[k] = sid

    snapshots_desc = list(reversed(chronological))
    latest_id = subject.get("last_success_id") or subject.get("latest_observation_id")
    if not latest_id and snapshots_desc:
        latest_id = snapshots_desc[0]["id"]

    extra_technical = {}
    if isinstance(latest_report, dict):
        tech = latest_report.get("technical") or {}
        extra_technical = {
            "analytical_close": tech.get("analytical_close"),
            "currency": tech.get("currency", "TWD"),
            "last_session": tech.get("last_session"),
            "observations": tech.get("observations") or [],
            "price_context": tech.get("price_context"),
        }

    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "branch": branch,
        "symbol": "2330.TW",
        "latest_snapshot_id": latest_id,
        "subject": subject,
        "checkpoint": checkpoint,
        "snapshots": snapshots_desc,
        "comparisons": comparisons,
        "extra_technical": extra_technical,
    }


def _render_annual_svg_chart(annual_rows: list[dict[str, Any]]) -> str:
    """Render an inline SVG grouped bar chart for FY2023-FY2025 Revenue, Net Income, and FCF."""
    if not annual_rows:
        return ""
    rows = sorted(annual_rows, key=lambda r: str(r.get("fiscal_year") or ""))
    max_val = max(
        max(float(r.get("revenue") or 0), float(r.get("net_income") or 0), float(r.get("free_cash_flow") or 0))
        for r in rows
    )
    if max_val <= 0:
        return ""

    width, height = 680, 230
    pad_left, pad_right, pad_top, pad_bottom = 60, 24, 28, 42
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom
    group_w = plot_w / max(len(rows), 1)
    bar_w = min(38.0, group_w / 4.2)

    bars_svg = []
    for idx, r in enumerate(rows):
        gx = pad_left + idx * group_w + (group_w - bar_w * 3 - 12) / 2
        series = [
            ("營收", float(r.get("revenue") or 0), "#3b82f6"),
            ("稅後淨利", float(r.get("net_income") or 0), "#10b981"),
            ("自由現金流", float(r.get("free_cash_flow") or 0), "#f59e0b"),
        ]
        for s_idx, (label, val, color) in enumerate(series):
            bh = max(2.0, (val / max_val) * plot_h) if val > 0 else 0.0
            bx = gx + s_idx * (bar_w + 6)
            by = pad_top + plot_h - bh
            val_trillion = val / 1e12
            bars_svg.append(
                f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" rx="4" fill="{color}">'
                f"<title>FY{_esc(r.get('fiscal_year'))} {label}: {val / 1e8:,.1f} 億 TWD</title></rect>"
                f'<text x="{bx + bar_w / 2:.1f}" y="{by - 6:.1f}" text-anchor="middle" fill="#cbd5e1" font-size="10">'
                f"{val_trillion:.2f}兆</text>"
            )
        label_x = pad_left + idx * group_w + group_w / 2
        bars_svg.append(
            f'<text x="{label_x:.1f}" y="{height - 14}" text-anchor="middle" fill="#e2e8f0" font-size="12" font-weight="600">'
            f"FY{_esc(r.get('fiscal_year'))} (EPS {_fmt_num(r.get('basic_eps'))}元)</text>"
        )

    return (
        f'<svg viewBox="0 0 {width} {height}" class="chart-svg" role="img" aria-label="年度營收、淨利與自由現金流趨勢圖">'
        f'<line x1="{pad_left}" y1="{pad_top + plot_h}" x2="{width - pad_right}" y2="{pad_top + plot_h}" stroke="#334155" stroke-width="1"/>'
        + "".join(bars_svg)
        + '<g transform="translate(65, 14)" font-size="11" fill="#cbd5e1">'
        + '<rect x="0" y="-9" width="10" height="10" rx="2" fill="#3b82f6"/><text x="14" y="0">營業收入</text>'
        + '<rect x="85" y="-9" width="10" height="10" rx="2" fill="#10b981"/><text x="99" y="0">稅後淨利</text>'
        + '<rect x="170" y="-9" width="10" height="10" rx="2" fill="#f59e0b"/><text x="184" y="0">自由現金流 (FCF)</text>'
        + "</g></svg>"
    )


def _render_snapshot_static_html(
    snap: dict[str, Any],
    comp: dict[str, Any] | None,
    subject: dict[str, Any],
    checkpoint: dict[str, Any] | None,
    extra_technical: dict[str, Any] | None = None,
) -> str:
    """Render the full HTML content for a single snapshot (used as default DOM and mirrored in JS)."""
    readiness = snap.get("readiness") or {}
    issuer = snap.get("issuer") or {}
    tech = snap.get("technical") or {}
    run_info = snap.get("run") or {}
    fr = snap.get("financial_research") or {}
    comp = comp or {}
    extra_technical = extra_technical or {}

    company_name = issuer.get("company_name") or "台灣積體電路製造股份有限公司"
    symbol = snap.get("symbol") or "2330.TW"
    issue_num = subject.get("issue_number") or 74
    repo = run_info.get("repository") or "iceboxi/market-research"
    issue_url = f"https://github.com/{repo}/issues/{issue_num}"
    run_url = run_info.get("run_url") or f"https://github.com/{repo}/actions"

    # Comparison summary
    comp_status = comp.get("status") or "baseline"
    changed_Dims = sorted({
        f"{c.get('component')} ({c.get('kind')})"
        for c in (comp.get("changes") or [])
        if isinstance(c, dict) and c.get("component")
    })

    # Readiness cards
    readiness_items = [
        ("財務研究 (Financial)", readiness.get("financial", "unavailable")),
        ("技術型態 (Technical)", readiness.get("technical", "unavailable")),
        ("估值模型 (Valuation)", readiness.get("valuation", "not_evaluated")),
        ("資料對帳 (Provenance)", readiness.get("valuation_provenance", "not_verified")),
        ("事件觀測 (Events)", readiness.get("events", "unknown")),
        ("交易計畫 (Trade Plan)", readiness.get("trade_plan", "not_evaluated")),
        ("投資建議 (Recommendation)", readiness.get("recommendation", "not_available")),
    ]
    readiness_html = "".join(
        f'<div class="status-pill"><span class="pill-label">{_esc(label)}</span>'
        f'<span class="badge {_badge_class(val)}">{_esc(val)}</span></div>'
        for label, val in readiness_items
    )

    # Financial Research section
    if fr and fr.get("status") == "available":
        annual_rows = fr.get("annual_summary") or []
        q_rows = fr.get("quarterly_summary") or []
        ttm = fr.get("ttm") or {}
        interim = fr.get("latest_cumulative_interim") or {}
        bs = fr.get("latest_balance_sheet") or {}
        val = fr.get("valuation_summary") or {}
        cal = (fr.get("calendar_schedule") or {}).get("events") or []
        disc = fr.get("disclosure_and_news") or {}
        div_sched = fr.get("dividend_schedule") or []
        ex_divs = fr.get("ex_dividend_history") or []

        # Key KPI highlight cards
        ttm_rev_t = float(ttm.get("revenue") or 0) / 1e12
        ttm_fcf_t = float(ttm.get("free_cash_flow") or 0) / 1e12
        net_cash_t = float(bs.get("net_cash") or 0) / 1e12
        kpi_html = f"""
        <div class="kpi-grid">
          <div class="kpi-card">
            <div class="kpi-title">TTM 合併營收 ({_esc("–".join([ttm.get("quarters", [""])[0], ttm.get("quarters", [""])[-1]]) if ttm.get("quarters") else "近四季")})</div>
            <div class="kpi-value">{ttm_rev_t:,.3f} 兆 TWD</div>
            <div class="kpi-sub">毛利率 {_fmt_pct(ttm.get("gross_margin_pct"))} · 營益率 {_fmt_pct(ttm.get("operating_margin_pct"))} · 淨利率 {_fmt_pct(ttm.get("net_margin_pct"))}</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-title">TTM 累計基本 EPS</div>
            <div class="kpi-value">{_fmt_num(ttm.get("basic_eps"))} 元/股</div>
            <div class="kpi-sub">股數最大季度漂移 {_fmt_pct(ttm.get("share_count_max_drift_pct"), False)} (≤0.5% 合規)</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-title">TTM 自由現金流 (OCF − CapEx)</div>
            <div class="kpi-value">{ttm_fcf_t:,.3f} 兆 TWD</div>
            <div class="kpi-sub">FCF 利潤率 {_fmt_pct(ttm.get("fcf_margin_pct"))} · 每股 TTM FCF {_fmt_num(val.get("ttm_fcf_twd_per_ordinary_share"))} 元</div>
          </div>
          <div class="kpi-card">
            <div class="kpi-title">最新資產負債表淨現金 ({_esc(bs.get("period_end"))})</div>
            <div class="kpi-value">{net_cash_t:,.3f} 兆 TWD</div>
            <div class="kpi-sub">現金 {_fmt_twd_B(bs.get("cash"))} − 有息負債 {_fmt_twd_B(bs.get("total_debt"))} (每股淨現金 {_fmt_num(val.get("net_cash_twd_per_ordinary_share"))} 元)</div>
          </div>
        </div>
        """

        # Annual table
        annual_trs = "".join(
            f"<tr>"
            f"<td><strong>FY{_esc(r.get('fiscal_year'))}</strong><div class='cell-sub'>{_esc(r.get('period_end'))}</div></td>"
            f"<td class='num'>{_fmt_twd_B(r.get('revenue'))}<div class='cell-sub'>{_fmt_pct(r.get('revenue_yoy_pct'), True)} YoY</div></td>"
            f"<td class='num'>{_fmt_twd_B(r.get('gross_profit'))}<div class='cell-sub'>毛利率 {_fmt_pct(r.get('gross_margin_pct'))}</div></td>"
            f"<td class='num'>{_fmt_twd_B(r.get('operating_income'))}<div class='cell-sub'>營益率 {_fmt_pct(r.get('operating_margin_pct'))}</div></td>"
            f"<td class='num'>{_fmt_twd_B(r.get('net_income'))}<div class='cell-sub'>淨利率 {_fmt_pct(r.get('net_margin_pct'))} ({_fmt_pct(r.get('net_income_yoy_pct'), True)})</div></td>"
            f"<td class='num'><strong>{_fmt_num(r.get('basic_eps'))}</strong></td>"
            f"<td class='num'>{_fmt_twd_B(r.get('operating_cash_flow'))}</td>"
            f"<td class='num'>{_fmt_twd_B(r.get('capex'))}</td>"
            f"<td class='num'><strong>{_fmt_twd_B(r.get('free_cash_flow'))}</strong><div class='cell-sub'>FCF率 {_fmt_pct(r.get('fcf_margin_pct'))}</div></td>"
            f"</tr>"
            for r in annual_rows
        )

        # Quarterly table
        q_trs = "".join(
            f"<tr>"
            f"<td><strong>{_esc(r.get('period_label'))}</strong><div class='cell-sub'>{_esc(r.get('period_end'))}</div></td>"
            f"<td><span class='badge badge-neutral'>{_esc(r.get('basis'))}</span></td>"
            f"<td class='num'>{_fmt_twd_B(r.get('revenue'))}</td>"
            f"<td class='num'>{_fmt_pct(r.get('gross_margin_pct'))}</td>"
            f"<td class='num'>{_fmt_pct(r.get('operating_margin_pct'))}</td>"
            f"<td class='num'>{_fmt_twd_B(r.get('net_income'))}<div class='cell-sub'>淨利率 {_fmt_pct(r.get('net_margin_pct'))}</div></td>"
            f"<td class='num'><strong>{_fmt_num(r.get('basic_eps'))}</strong></td>"
            f"<td class='num'>{_fmt_twd_B(r.get('operating_cash_flow'))}</td>"
            f"<td class='num'>{_fmt_twd_B(r.get('capex'))}</td>"
            f"<td class='num'><strong>{_fmt_twd_B(r.get('free_cash_flow'))}</strong><div class='cell-sub'>{_fmt_pct(r.get('fcf_margin_pct'))}</div></td>"
            f"</tr>"
            for r in q_rows
        )

        # Valuation scenarios
        fcf_scen = val.get("fair_value_scenarios") or {}
        pe_scen = val.get("ttm_pe_scenarios") or {}
        ex_mult = val.get("exchange_multiples") or {}

        fcf_rows_html = "".join(
            f"<tr>"
            f"<td><strong>{_esc(name.capitalize())}</strong></td>"
            f"<td class='num'>{_fmt_num(s.get('fcf_multiple'), 1)}x</td>"
            f"<td class='num'>{_fmt_num(s.get('median_fcf_component_twd'))} 元</td>"
            f"<td class='num'>+{_fmt_num(s.get('net_cash_component_twd'))} 元</td>"
            f"<td class='num'><strong>{_fmt_num(s.get('indicative_twd_per_share'))} 元</strong></td>"
            f"<td class='num'><strong>{_fmt_num(s.get('indicative_ttm_fcf_twd_per_share'))} 元</strong></td>"
            f"</tr>"
            for name in ("conservative", "base", "optimistic")
            if (s := fcf_scen.get(name))
        )

        pe_rows_html = "".join(
            f"<tr>"
            f"<td><strong>{_esc(name.capitalize())}</strong></td>"
            f"<td class='num'>{_fmt_num(s.get('pe_multiple'), 1)}x</td>"
            f"<td class='num'>{_fmt_num(s.get('ttm_basic_eps_twd'))} 元</td>"
            f"<td class='num'><strong>{_fmt_num(s.get('indicative_twd_per_share'))} 元</strong></td>"
            f"</tr>"
            for name in ("conservative", "base", "optimistic")
            if (s := pe_scen.get(name))
        )

        # Calendar & disclosures
        cal_items_html = "".join(
            f"<div class='timeline-item'>"
            f"<div class='timeline-date'>{_esc(ev.get('scheduled_date') or '待公告')}</div>"
            f"<div class='timeline-body'>"
            f"<div class='timeline-title'>"
            f"<span class='badge {_badge_class(ev.get('confirmation_status'))}'>{_esc(ev.get('confirmation_status'))}</span> "
            f"<strong>[{_esc(ev.get('period_label'))}] {_esc(ev.get('title'))}</strong>"
            f"</div>"
            f"<div class='timeline-meta'>類型: {_esc(ev.get('event_type'))} · ID: <code>{_esc(ev.get('schedule_id'))}</code> · "
            f"<a href='{_esc(ev.get('source'))}' target='_blank' rel='noopener'>官方來源</a>"
            + (
                f" · <span class='badge badge-warn'>更正前日期: {_esc(', '.join(ev.get('superseded_dates') or []))}</span>"
                if ev.get("superseded_dates")
                else ""
            )
            + "</div></div></div>"
            for ev in cal
        )

        disc_items_html = "".join(
            f"<li><span class='badge badge-ok'>{_esc(d.get('event_date') or d.get('reported_at'))}</span> "
            f"<strong>{_esc(d.get('title'))}</strong> "
            f"<span class='cell-sub'>({_esc(d.get('category'))} · <a href='{_esc(d.get('source'))}' target='_blank' rel='noopener'>來源</a>)</span></li>"
            for d in (disc.get("official_disclosures") or [])
        ) or "<li>目前無近期重大公告項目</li>"

        news_items = disc.get("news_references") or []
        news_items_html = "".join(
            f"<li><span class='badge badge-neutral'>{_esc((n.get('published_at') or '')[:10])}</span> "
            f"<a href='{_esc(n.get('url'))}' target='_blank' rel='noopener'>{_esc(n.get('title'))}</a> "
            f"<span class='cell-sub'>({_esc(n.get('source'))})</span></li>"
            for n in news_items
        ) or f"<li>補充新聞已去重（去重移除重貼數：{_esc(disc.get('deduplicated_repost_count', 0))}），目前無額外列示項目。</li>"

        ex_div_trs = "".join(
            f"<tr><td>{_esc(x.get('ex_date'))}</td><td>{_esc(x.get('type'))}</td>"
            f"<td class='num'>{_fmt_num(x.get('dividend_per_share_twd'), 4)} 元</td>"
            f"<td class='num'>{_fmt_num(x.get('before_price'))}</td>"
            f"<td class='num'>{_fmt_num(x.get('reference_price'))}</td></tr>"
            for x in ex_divs
        )

        financial_section_html = f"""
        {kpi_html}

        <section class="panel" id="section-financials">
          <div class="panel-header">
            <h2>財務三表、單季拆解與連續四季 TTM 分析</h2>
            <div class="tab-bar" role="tablist">
              <button class="tab-btn active" data-tab="tab-annual" onclick="switchTab('tab-annual')">年度三表 (FY23–FY25)</button>
              <button class="tab-btn" data-tab="tab-quarterly" onclick="switchTab('tab-quarterly')">單季趨勢與 TTM (25Q1–26Q2)</button>
              <button class="tab-btn" data-tab="tab-bs" onclick="switchTab('tab-bs')">資產負債與最新半年報</button>
              <button class="tab-btn" data-tab="tab-shares" onclick="switchTab('tab-shares')">股本與除權息紀錄</button>
            </div>
          </div>

          <div id="tab-annual" class="tab-content active">
            <div class="chart-wrap">
              {_render_annual_svg_chart(annual_rows)}
            </div>
            <div class="table-scroll">
              <table class="data-table">
                <thead>
                  <tr>
                    <th>會計年度</th>
                    <th class="num">營業收入</th>
                    <th class="num">營業毛利 / 毛利率</th>
                    <th class="num">營業利益 / 營益率</th>
                    <th class="num">本期淨利 / 淨利率</th>
                    <th class="num">基本 EPS (元)</th>
                    <th class="num">營業現金流 (OCF)</th>
                    <th class="num">資本支出 (CapEx)</th>
                    <th class="num">自由現金流 (FCF)</th>
                  </tr>
                </thead>
                <tbody>{annual_trs}</tbody>
              </table>
            </div>
          </div>

          <div id="tab-quarterly" class="tab-content">
            <div class="callout callout-info">
              <strong>單季口徑保護：</strong>Q2 / Q3 / Q4 損益與現金流均已由累計財報拆解為獨立單季（並與 TWSE <code>t187ap45_L</code> 單季母公司淨利及每股盈餘交叉核對），絕不將 H1 或前三季累計值直接當作單季。
              <strong>TTM ({_esc(", ".join(ttm.get("quarters") or []))})：</strong>合併營收 <strong>{_fmt_twd_B(ttm.get("revenue"))}</strong>、稅後淨利 <strong>{_fmt_twd_B(ttm.get("net_income"))}</strong>、TTM 基本 EPS <strong>{_fmt_num(ttm.get("basic_eps"))} 元</strong>、TTM FCF <strong>{_fmt_twd_B(ttm.get("free_cash_flow"))}</strong>。
            </div>
            <div class="table-scroll">
              <table class="data-table">
                <thead>
                  <tr>
                    <th>季度</th>
                    <th>推導與核對口徑</th>
                    <th class="num">單季營收</th>
                    <th class="num">毛利率</th>
                    <th class="num">營益率</th>
                    <th class="num">單季淨利</th>
                    <th class="num">單季 EPS</th>
                    <th class="num">單季 OCF</th>
                    <th class="num">單季 CapEx</th>
                    <th class="num">單季 FCF</th>
                  </tr>
                </thead>
                <tbody>{q_trs}</tbody>
              </table>
            </div>
          </div>

          <div id="tab-bs" class="tab-content">
            <div class="two-col">
              <div>
                <h3>最新合併資產負債表重點 ({_esc(bs.get("period_end"))})</h3>
                <table class="data-table">
                  <tbody>
                    <tr><td>現金及約當現金</td><td class="num"><strong>{_fmt_twd_B(bs.get("cash"))}</strong></td></tr>
                    <tr><td>應付公司債</td><td class="num">{_fmt_twd_B(bs.get("bonds_payable"))}</td></tr>
                    <tr><td>長期銀行借款</td><td class="num">{_fmt_twd_B(bs.get("long_term_borrowings"))}</td></tr>
                    <tr><td>有息負債合計</td><td class="num">{_fmt_twd_B(bs.get("total_debt"))}</td></tr>
                    <tr><td><strong>帳上淨現金 (Net Cash)</strong></td><td class="num"><strong>{_fmt_twd_B(bs.get("net_cash"))}</strong></td></tr>
                    <tr><td>資產總計</td><td class="num">{_fmt_twd_B(bs.get("total_assets"))}</td></tr>
                    <tr><td>負債總計</td><td class="num">{_fmt_twd_B(bs.get("total_liabilities"))}</td></tr>
                    <tr><td>歸屬母公司業主權益</td><td class="num">{_fmt_twd_B(bs.get("parent_equity"))}</td></tr>
                  </tbody>
                </table>
              </div>
              <div>
                <h3>最新累計半年報 ({_esc(interim.get("period_label"))} · {_esc(interim.get("period_end"))})</h3>
                <table class="data-table">
                  <tbody>
                    <tr><td>累計營業收入</td><td class="num"><strong>{_fmt_twd_B(interim.get("revenue"))}</strong> ({_fmt_pct(interim.get("revenue_yoy_pct"), True)} YoY)</td></tr>
                    <tr><td>累計營業毛利</td><td class="num">{_fmt_twd_B(interim.get("gross_profit"))}</td></tr>
                    <tr><td>累計營業利益</td><td class="num">{_fmt_twd_B(interim.get("operating_income"))}</td></tr>
                    <tr><td>累計稅前淨利</td><td class="num">{_fmt_twd_B(interim.get("pre_tax_income"))}</td></tr>
                    <tr><td>累計本期淨利</td><td class="num"><strong>{_fmt_twd_B(interim.get("net_income"))}</strong> ({_fmt_pct(interim.get("net_income_yoy_pct"), True)} YoY)</td></tr>
                    <tr><td>累計基本 EPS</td><td class="num"><strong>{_fmt_num(interim.get("basic_eps"))} 元</strong></td></tr>
                    <tr><td>累計營業現金流 / 資本支出</td><td class="num">{_fmt_twd_B(interim.get("operating_cash_flow"))} / {_fmt_twd_B(interim.get("capex"))}</td></tr>
                    <tr><td>累計自由現金流 (H1 FCF)</td><td class="num"><strong>{_fmt_twd_B(interim.get("free_cash_flow"))}</strong></td></tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <div id="tab-shares" class="tab-content">
            <div class="callout callout-info">
              <strong>股本與普通股分母對帳：</strong>TWSE <code>t187ap03_L</code> 實收資本額 <strong>{_fmt_num(fr.get("paid_in_capital_twd"), 0)} 元</strong>（每股面額 10 元 → <strong>{_fmt_num(fr.get("issued_ordinary_shares"), 0)} 股</strong>），資產負債表普通股股本換算股數 <strong>{_fmt_num(bs.get("ordinary_shares"), 0)} 股</strong>。
            </div>
            <h3>近期除權息紀錄 (TWSE TWT49U)</h3>
            <div class="table-scroll">
              <table class="data-table">
                <thead>
                  <tr><th>除權息日</th><th>權/息</th><th class="num">每股現金股利</th><th class="num">除息前收盤價</th><th class="num">除息參考價</th></tr>
                </thead>
                <tbody>{ex_div_trs}</tbody>
              </table>
            </div>
          </div>
        </section>

        <section class="panel" id="section-valuation">
          <div class="panel-header">
            <h2>雙模型估值情境敏感度分析 <span class="badge badge-warn">illustrative_only（非目標價／非買賣建議）</span></h2>
          </div>
          <div class="callout callout-warn">
            <strong>研究邊界聲明：</strong>以下 P/FCF 與 TTM P/E 情境僅為歷史與 TTM 財務數據在不同假設倍數下的數學敏感度映射（<code>valuation = illustrative_only</code>）。
            系統<strong>不提供</strong>目標價、買進價、停損價或進出場區間（<code>trade_plan = not_evaluated</code>，<code>recommendation = not_available</code>）。
            TWSE 官方盤後參考倍數（<code>BWIBBU_ALL</code>，出表 {_esc(ex_mult.get("date_roc"))}）：P/E <strong>{_fmt_num(ex_mult.get("pe_ratio"))}x</strong> · P/B <strong>{_fmt_num(ex_mult.get("pb_ratio"))}x</strong> · 殖利率 <strong>{_fmt_pct(ex_mult.get("dividend_yield_pct"))}</strong>。
          </div>
          <div class="two-col">
            <div>
              <h3>模型一：EV 橋接 P/FCF 情境（含每股淨現金 +{_fmt_num(val.get("net_cash_twd_per_ordinary_share"))} 元）</h3>
              <table class="data-table">
                <thead>
                  <tr>
                    <th>情境</th>
                    <th class="num">假設 FCF 倍數</th>
                    <th class="num">3年中位數 FCF/股貢獻</th>
                    <th class="num">每股淨現金橋接</th>
                    <th class="num">3年中位數 P/FCF 參考值</th>
                    <th class="num">TTM P/FCF 參考值</th>
                  </tr>
                </thead>
                <tbody>{fcf_rows_html}</tbody>
              </table>
            </div>
            <div>
              <h3>模型二：TTM P/E 歷史倍數敏感度（TTM EPS {_fmt_num(ttm.get("basic_eps"))} 元）</h3>
              <table class="data-table">
                <thead>
                  <tr>
                    <th>情境</th>
                    <th class="num">假設 P/E 倍數</th>
                    <th class="num">TTM 基本 EPS</th>
                    <th class="num">對應每股情境參考值</th>
                  </tr>
                </thead>
                <tbody>{pe_rows_html}</tbody>
              </table>
            </div>
          </div>
        </section>

        <section class="panel" id="section-calendar-events">
          <div class="two-col">
            <div>
              <h2>財報、董事會與股東常會行事曆 (TW09)</h2>
              <div class="timeline">{cal_items_html}</div>
            </div>
            <div>
              <h2>官方重大訊息與去重補充新聞 (TW08)</h2>
              <h3>官方公告與董事會決議</h3>
              <ul class="clean-list">{disc_items_html}</ul>
              <h3>補充新聞參考（非官方財報依據）</h3>
              <ul class="clean-list">{news_items_html}</ul>
            </div>
          </div>
        </section>
        """
    else:
        financial_section_html = f"""
        <section class="panel">
          <h2>早期研究快照（尚未接入完整三表對帳前之歷史紀錄）</h2>
          <p>此快照（<code>{_esc(snap.get("id"))}</code>）產生於完整財務三表接入前，當時財務就緒狀態為 <span class="badge badge-neutral">{_esc(readiness.get("financial"))}</span>。請從頂部切換至最新快照查看完整三表、TTM 與雙模型估值。</p>
        </section>
        """

    # Technical & Monthly Revenue & Provenance footer panel
    mrev = (snap.get("monthly_revenue") or [{}])[0] if snap.get("monthly_revenue") else {}
    cp_html = ""
    if checkpoint:
        cp_html = (
            f"<div><strong>TW13 消費檢查點：</strong>財報版本 <code>{_esc(checkpoint.get('consumed_financial_version'))}</code> · "
            f"已消費官方事件數 <code>{len(checkpoint.get('consumed_event_ids') or [])}</code> · "
            f"待重跑請求 <code>{_esc(checkpoint.get('pending_rerun') or '無 (up_to_date)')}</code></div>"
        )

    return f"""
    <div class="snapshot-view" data-snapshot-id="{_esc(snap.get('id'))}">
      <section class="panel comparison-banner">
        <div class="banner-row">
          <div>
            <span class="badge {_badge_class(comp_status)}">比較結果: {_esc(comp_status.upper())}</span>
            <span class="banner-text">
              當前快照 <code>{_esc((snap.get("id") or "")[:12])}</code>
              {f" 對照前次成功快照 <code>{_esc((comp.get('previous_snapshot_id') or '')[:12])}</code>" if comp.get("previous_snapshot_id") else " (首筆基準快照)"}
              {f" · 變動面向: <strong>{_esc(', '.join(changed_Dims))}</strong>" if changed_Dims else " · 實質研究結論無變動"}
            </span>
          </div>
          <div class="banner-links">
            <a href="{_esc(issue_url)}" target="_blank" rel="noopener" class="btn-link">GitHub 固定報告 Issue #{_esc(issue_num)}</a>
            <a href="{_esc(run_url)}" target="_blank" rel="noopener" class="btn-link">驗證 Run #{_esc(run_info.get("run_id"))}</a>
          </div>
        </div>
        {cp_html}
      </section>

      <section class="panel">
        <h2>研究模組就緒狀態 (Readiness Gate)</h2>
        <div class="status-grid">{readiness_html}</div>
      </section>

      {financial_section_html}

      <section class="panel" id="section-technical-provenance">
        <div class="two-col">
          <div>
            <h2>技術研究與最新月營收快照</h2>
            <table class="data-table">
              <tbody>
                <tr><td>技術資料狀態 / 新鮮度</td><td><span class="badge {_badge_class(tech.get('status'))}">{_esc(tech.get("status"))}</span> ({_esc(tech.get("freshness"))})</td></tr>
                <tr><td>最新完整交易日 (Session)</td><td><strong>{_esc(tech.get("session"))}</strong></td></tr>
                <tr><td>價格基準與來源</td><td><code>{_esc(tech.get("price_basis"))}</code> ({_esc(tech.get("source"))})</td></tr>
                <tr><td>技術輸入指紋 (SHA-256)</td><td><code>{_esc((tech.get("input_sha256") or "")[:24])}...</code></td></tr>
                <tr><td>最新月營收 ({_esc(mrev.get("period"))})</td><td><strong>{_fmt_num(mrev.get("value"), 0)} {_esc(mrev.get("unit"))}</strong> (出表 {_esc(mrev.get("reported_at"))})</td></tr>
              </tbody>
            </table>
          </div>
          <div>
            <h2>資料來源追溯、授權與比較限制</h2>
            <p class="cell-sub">授權：{_esc((snap.get("attribution") or {}).get("provider"))}（<a href="{_esc((snap.get('attribution') or {}).get('license'))}" target="_blank" rel="noopener">政府資料開放授權條款 v{_esc((snap.get("attribution") or {}).get("license_version"))}</a>）</p>
            <ul class="clean-list">
              {"".join(f"<li><a href='{_esc(link)}' target='_blank' rel='noopener'>{_esc(link)}</a></li>" for link in (snap.get("source_links") or []))}
            </ul>
            <div class="cell-sub">
              <strong>快照保存限制 (Comparison Limits)：</strong><code>{_esc(", ".join(snap.get("comparison_limits") or []))}</code> ·
              可得時間屬性：<code>{_esc(snap.get("availability"))}</code> ·
              Commit SHA：<code>{_esc((run_info.get("code_sha") or "")[:12])}</code>
            </div>
          </div>
        </div>
      </section>
    </div>
    """


def render_research_site_html(
    records: dict[str, Any] | None = None,
    *,
    branch: str = "research-state",
    latest_report: dict[str, Any] | None = None,
) -> str:
    """Render a complete, self-contained HTML5 dashboard for 2330.TW research."""
    payload = build_site_payload(records, branch=branch, latest_report=latest_report)
    snapshots = payload["snapshots"]
    latest_id = payload["latest_snapshot_id"]
    latest_snap = next((s for s in snapshots if s["id"] == latest_id), snapshots[0] if snapshots else None)

    if latest_snap is None:
        raise ValueError("Cannot render research site without at least one snapshot or report")

    # Pre-render static HTML views for every snapshot so switching snapshots in the browser
    # is 100% faithful and instant without duplicating formatting logic!
    rendered_views: dict[str, str] = {}
    for snap in snapshots:
        sid = snap["id"]
        rendered_views[sid] = _render_snapshot_static_html(
            snap,
            payload["comparisons"].get(sid),
            payload["subject"],
            payload["checkpoint"],
            payload["extra_technical"] if sid == latest_id else None,
        )

    options_html = []
    for idx, snap in enumerate(snapshots):
        sid = snap["id"]
        obs = (snap.get("observed_at_utc") or "")[:19].replace("T", " ")
        comp_st = (payload["comparisons"].get(sid) or {}).get("status", "baseline")
        fin_st = (snap.get("readiness") or {}).get("financial", "unavailable")
        tag = "★ 最新正式快照" if sid == latest_id else f"歷史快照 #{len(snapshots) - idx}"
        sel = " selected" if sid == latest_id else ""
        options_html.append(
            f'<option value="{_esc(sid)}"{sel}>{_esc(tag)} — {_esc(obs)} UTC [{_esc(comp_st)} | 財務:{_esc(fin_st)}] ({_esc(sid[:8])})</option>'
        )

    embedded_json = json.dumps(
        {
            "latest_snapshot_id": latest_id,
            "generated_at_utc": payload["generated_at_utc"],
            "branch": branch,
            "snapshot_count": len(snapshots),
            "views": rendered_views,
        },
        ensure_ascii=False,
    ).replace("</", "<\\/")

    issuer_name = (latest_snap.get("issuer") or {}).get("company_name") or "台灣積體電路製造股份有限公司"

    return f"""<!DOCTYPE html>
<html lang="zh-Hant-TW">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>2330.TW {_esc(issuer_name)} — 個股研究儀表板 (Market Research)</title>
  <style>
    :root {{
      --bg: #0f172a;
      --panel: #1e293b;
      --panel-alt: #0b1120;
      --border: #334155;
      --text: #f8fafc;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --ok-bg: rgba(16, 185, 129, 0.16);
      --ok-fg: #34d399;
      --warn-bg: rgba(245, 158, 11, 0.18);
      --warn-fg: #fbbf24;
      --neutral-bg: rgba(148, 163, 184, 0.16);
      --neutral-fg: #cbd5e1;
      --err-bg: rgba(239, 68, 68, 0.18);
      --err-fg: #f87171;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang TC", "Noto Sans TC", sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.55;
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.86em;
      background: rgba(15, 23, 42, 0.65);
      padding: 2px 6px;
      border-radius: 4px;
      color: #e2e8f0;
    }}
    .top-header {{
      position: sticky;
      top: 0;
      z-index: 20;
      background: rgba(15, 23, 42, 0.92);
      backdrop-filter: blur(10px);
      border-bottom: 1px solid var(--border);
      padding: 14px 24px;
    }}
    .header-inner {{
      max-width: 1360px;
      margin: 0 auto;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
    }}
    .brand-title {{
      font-size: 1.25rem;
      font-weight: 700;
      margin: 0;
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .brand-sub {{
      font-size: 0.82rem;
      color: var(--muted);
      margin-top: 2px;
    }}
    .time-machine {{
      display: flex;
      align-items: center;
      gap: 10px;
      background: var(--panel);
      padding: 8px 12px;
      border-radius: 8px;
      border: 1px solid var(--border);
    }}
    .time-machine label {{
      font-size: 0.82rem;
      color: var(--muted);
      white-space: nowrap;
      font-weight: 600;
    }}
    .time-machine select {{
      background: var(--bg);
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 6px 10px;
      font-size: 0.85rem;
      max-width: 460px;
    }}
    .container {{
      max-width: 1360px;
      margin: 20px auto 48px;
      padding: 0 24px;
    }}
    .disclaimer-bar {{
      background: rgba(245, 158, 11, 0.12);
      border: 1px solid rgba(245, 158, 11, 0.4);
      color: #fde68a;
      padding: 10px 16px;
      border-radius: 8px;
      font-size: 0.86rem;
      margin-bottom: 18px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 20px;
      margin-bottom: 18px;
    }}
    .panel h2 {{
      margin: 0 0 14px 0;
      font-size: 1.1rem;
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .panel h3 {{
      margin: 12px 0 10px 0;
      font-size: 0.96rem;
      color: #e2e8f0;
    }}
    .panel-header {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 14px;
    }}
    .panel-header h2 {{ margin: 0; }}
    .comparison-banner {{
      background: linear-gradient(90deg, rgba(30, 41, 59, 0.95), rgba(15, 23, 42, 0.95));
      display: flex;
      flex-direction: column;
      gap: 8px;
      font-size: 0.88rem;
    }}
    .banner-row {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
    }}
    .banner-links {{ display: flex; gap: 10px; flex-wrap: wrap; }}
    .btn-link {{
      background: rgba(56, 189, 248, 0.14);
      border: 1px solid rgba(56, 189, 248, 0.35);
      color: var(--accent);
      padding: 5px 12px;
      border-radius: 6px;
      font-size: 0.82rem;
      font-weight: 600;
    }}
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 14px;
      margin-bottom: 18px;
    }}
    .kpi-card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px 18px;
    }}
    .kpi-title {{ font-size: 0.8rem; color: var(--muted); font-weight: 600; }}
    .kpi-value {{ font-size: 1.45rem; font-weight: 700; margin: 6px 0 4px; color: #f8fafc; }}
    .kpi-sub {{ font-size: 0.78rem; color: var(--muted); }}
    .status-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
    }}
    .status-pill {{
      background: var(--panel-alt);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 12px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}
    .pill-label {{ font-size: 0.78rem; color: var(--muted); }}
    .badge {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 0.75rem;
      font-weight: 600;
      width: fit-content;
    }}
    .badge-ok {{ background: var(--ok-bg); color: var(--ok-fg); }}
    .badge-warn {{ background: var(--warn-bg); color: var(--warn-fg); }}
    .badge-neutral {{ background: var(--neutral-bg); color: var(--neutral-fg); }}
    .badge-err {{ background: var(--err-bg); color: var(--err-fg); }}
    .tab-bar {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .tab-btn {{
      background: var(--panel-alt);
      color: var(--muted);
      border: 1px solid var(--border);
      padding: 7px 14px;
      border-radius: 8px;
      cursor: pointer;
      font-size: 0.84rem;
      font-weight: 600;
    }}
    .tab-btn.active {{
      background: rgba(56, 189, 248, 0.16);
      color: var(--accent);
      border-color: var(--accent);
    }}
    .tab-content {{ display: none; }}
    .tab-content.active {{ display: block; }}
    .chart-wrap {{
      background: var(--panel-alt);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px;
      margin-bottom: 14px;
      overflow-x: auto;
    }}
    .chart-svg {{ width: 100%; max-width: 720px; height: auto; display: block; margin: 0 auto; }}
    .table-scroll {{ overflow-x: auto; }}
    .data-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.85rem;
    }}
    .data-table th, .data-table td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--border);
      text-align: left;
      vertical-align: top;
    }}
    .data-table th {{
      color: var(--muted);
      font-weight: 600;
      background: rgba(15, 23, 42, 0.5);
      white-space: nowrap;
    }}
    .data-table th.num, .data-table td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .cell-sub {{ font-size: 0.75rem; color: var(--muted); margin-top: 2px; }}
    .two-col {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
      gap: 20px;
    }}
    .callout {{
      padding: 12px 14px;
      border-radius: 8px;
      font-size: 0.84rem;
      margin-bottom: 14px;
    }}
    .callout-info {{
      background: rgba(56, 189, 248, 0.1);
      border: 1px solid rgba(56, 189, 248, 0.3);
      color: #e0f2fe;
    }}
    .callout-warn {{
      background: rgba(245, 158, 11, 0.12);
      border: 1px solid rgba(245, 158, 11, 0.35);
      color: #fef3c7;
    }}
    .timeline {{ display: flex; flex-direction: column; gap: 10px; }}
    .timeline-item {{
      display: flex;
      gap: 12px;
      background: var(--panel-alt);
      border: 1px solid var(--border);
      padding: 10px 12px;
      border-radius: 8px;
    }}
    .timeline-date {{
      font-family: ui-monospace, monospace;
      font-size: 0.82rem;
      font-weight: 700;
      color: var(--accent);
      min-width: 92px;
    }}
    .timeline-title {{ font-size: 0.86rem; margin-bottom: 4px; }}
    .timeline-meta {{ font-size: 0.76rem; color: var(--muted); }}
    .clean-list {{ margin: 0 0 14px 0; padding-left: 18px; font-size: 0.85rem; }}
    .clean-list li {{ margin-bottom: 8px; }}
    .site-footer {{
      text-align: center;
      font-size: 0.78rem;
      color: var(--muted);
      padding: 20px 0;
      border-top: 1px solid var(--border);
      margin-top: 28px;
    }}
  </style>
</head>
<body>
  <header class="top-header">
    <div class="header-inner">
      <div>
        <h1 class="brand-title">
          <span>2330.TW {_esc(issuer_name)}</span>
          <span class="badge badge-ok">實證資料驅動研究報告</span>
        </h1>
        <div class="brand-sub">
          資料分支: <code>{_esc(branch)}</code> · 頁面生成 (UTC): <code>{_esc(payload["generated_at_utc"][:19])}</code> · 共收錄 <strong>{len(snapshots)}</strong> 期研究快照
        </div>
      </div>
      <div class="time-machine">
        <label for="snapshot-selector">歷史快照切換器 (Time Machine)：</label>
        <select id="snapshot-selector" onchange="switchSnapshot(this.value)">
          {"".join(options_html)}
        </select>
      </div>
    </div>
  </header>

  <main class="container">
    <div class="disclaimer-bar">
      <strong>投資研究合規與非交易建議聲明：</strong>
      本頁面所有數據皆來自公開官方來源（TWSE OpenAPI / 政府資料開放平臺 / MOPS / FinMind 雙軌核對），缺值不補零。
      估值情境（<code>illustrative_only</code>）與技術觀察僅供研究敏感度對照，<strong>不可冒充合理買賣價、進出場區間或停損目標價</strong>（<code>trade_plan = not_evaluated</code>，<code>recommendation = not_available</code>）。
    </div>

    <div id="app">
      {rendered_views[latest_id]}
    </div>

    <footer class="site-footer">
      Market Research Static Dashboard · Single State Owner: <code>GitStateStore ({_esc(branch)})</code> · Zero Backend Dependency
    </footer>
  </main>

  <script id="research-site-data" type="application/json">{embedded_json}</script>
  <script>
    const SITE_DATA = JSON.parse(document.getElementById("research-site-data").textContent);
    function switchSnapshot(snapshotId) {{
      const app = document.getElementById("app");
      if (SITE_DATA.views && SITE_DATA.views[snapshotId]) {{
        app.innerHTML = SITE_DATA.views[snapshotId];
      }}
    }}
    function switchTab(tabId) {{
      const root = document.getElementById("app");
      root.querySelectorAll(".tab-btn").forEach(btn => {{
        btn.classList.toggle("active", btn.getAttribute("data-tab") === tabId);
      }});
      root.querySelectorAll(".tab-content").forEach(panel => {{
        panel.classList.toggle("active", panel.id === tabId);
      }});
    }}
  </script>
</body>
</html>
"""


def write_research_site(
    out_dir: Path,
    records: dict[str, Any] | None = None,
    *,
    branch: str = "research-state",
    latest_report: dict[str, Any] | None = None,
) -> Path:
    """Write `index.html` into `out_dir` and return its path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    html_text = render_research_site_html(records, branch=branch, latest_report=latest_report)
    target = out_dir / "index.html"
    target.write_text(html_text, encoding="utf-8")
    return target
