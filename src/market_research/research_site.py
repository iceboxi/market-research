"""Static stock research workspace rendered from validated research state.

Read-only presentation layer. Inputs are the canonical `research-state` records
(compact snapshots, subject, checkpoint) or one `company_report` result. Output is
one dependency-free `index.html`:

- server-rendered latest research version (readable without JavaScript)
- persistent stock selector listing only symbols whose research state resolves
- separate research-version (historical snapshot) selector, reflected in the URL
- sections: overview, fundamentals, valuation, technical, risks & events,
  data & methodology

Nothing here computes new research conclusions. Values come from the snapshot;
the few derived ratios (e.g. same-quarter YoY, capex / revenue) are labelled as
derived and never replace missing inputs with zero.
"""

from __future__ import annotations

from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo

from market_research.research_comparison import available, compare_snapshots
from market_research.research_snapshot import SnapshotError, prepare_snapshot, utc
from market_research.fundamentals import finmind_per_url
from market_research.price_watch import (DISCLAIMER as PRICE_WATCH_DISCLAIMER, MA_SESSIONS,
                                         WINDOW_WEEKS, price_watch_notes)
from market_research.thesis_check import STATUS_LABELS as THESIS_LABELS
from market_research.valuation_zone import DISCLAIMER, ZONE_LABELS

TAIPEI = ZoneInfo("Asia/Taipei")
# The overview, risk and valuation narrative was hand-written for TSMC's foundry business;
# every other stock gets neutral wording built only from its own data (#125).
NARRATIVE_SYMBOL = "2330.TW"
# Each embedded version costs ~55 kB; older ones stay listed in 資料與方法 (#131).
MAX_EMBEDDED_VERSIONS = 30
SUBJECT_RE = re.compile(r"subjects/([a-z]+)/([A-Za-z0-9.\-]+)\.json")

MARKETS = {
    "tw": {"exchange": "臺灣證券交易所", "code": "TWSE", "currency": "TWD", "currency_label": "新台幣"},
}

# status code -> (human label, non-colour symbol, tone)
STATUS = {
    "available": ("完成", "✓", "ok"),
    "completed": ("完成", "✓", "ok"),
    "candidate_for_nonfinancial_research": ("適用（非金融業）", "✓", "ok"),
    "inapplicable": ("不適用（金融/特殊業）", "—", "neutral"),
    "reconciled_tw_dual_track": ("雙軌對帳完成", "✓", "ok"),
    "illustrative_only": ("僅示意情境", "◐", "warn"),
    "review_only": ("僅供人工複核", "◐", "warn"),
    "partial": ("部分完成", "◐", "warn"),
    "degraded": ("來源降級", "◐", "warn"),
    "no_recent_observed_events": ("近期未觀測到事件", "○", "neutral"),
    "not_evaluated": ("未評估", "—", "neutral"),
    "not_available": ("不提供", "—", "neutral"),
    "not_verified": ("未驗證", "—", "neutral"),
    "unavailable": ("無資料", "✕", "bad"),
    "unknown": ("未知", "?", "neutral"),
}

MODULES = [
    ("financial", "財務研究", {
        "available": "年度三表、單季拆解與 TTM 已與 TWSE 開放資料對帳。",
        "unavailable": "此版本沒有可用的財務研究資料。",
        "not_evaluated": "金融控股業未套用製造業財務報表。",
    }),
    ("valuation", "估值", {
        "illustrative_only": "僅有倍數情境試算，不是合理價或目標價。",
        "not_evaluated": "未進行估值（金融業不適用一般 FCF 模型，或財報未齊全）。",
    }),
    ("technical", "技術資料", {
        "available": "行情資料可用；依輕量契約保存近期收盤走勢與檢驗 metadata。",
        "unavailable": "此版本無法取得行情資料。",
    }),
    ("events", "事件觀測", {
        "no_recent_observed_events": "最近一次每日快照未觀測到重大訊息；觀測範圍有限，不代表沒有風險。",
    }),
    ("valuation_provenance", "估值資料溯源", {
        "reconciled_tw_dual_track": "估值輸入取自已對帳的財報資料。",
        "not_verified": "估值輸入未經驗證。",
    }),
    ("source_evidence", "來源證據", {
        "review_only": "來源證據可追溯，但仍需人工複核。",
    }),
    ("instrument", "標的適用性", {
        "candidate_for_nonfinancial_research": "適用一般產業（非金融業）研究模型。",
        "inapplicable": "金融或特殊產業；一般產業現金流與估值模型不適用。",
    }),
    ("trade_plan", "交易計畫", {
        "not_evaluated": "系統不產生進出場區間、停損或目標價。",
    }),
    ("recommendation", "投資建議", {
        "not_available": "系統不產生買進／賣出建議或評等。",
    }),
]

COMPARISON_LABELS = {
    "baseline": "首次基準（無前版可比）",
    "latest_only": "只保留最新一版（未存歷史）",
    "unchanged": "與前一版本相比無研究變化",
    "new_period": "新增資料期別",
    "revision": "同期間數值更正",
    "coverage_change": "來源或模組狀態變化",
    "model_change": "模型或設定變更",
    "incomparable": "部分內容無法比較",
}

COMPONENT_LABELS = {
    "issuer": "公司身分", "monthly_revenue": "月營收", "technical": "技術資料", "events": "事件",
    "financial_research": "財務研究", "calendar_schedule": "行事曆", "model": "模型", "schema": "資料格式",
    "time": "評估時間",
}

QUARTER_BASIS = {
    "standalone_q1": "Q1 單季（即當年累計）",
    "standalone_reconciled_t187ap45": "累計相減；已與 TWSE 單季淨利核對",
    "standalone_eps_identity": "累計相減；以 EPS 恆等式核對",
}

PRICE_BASIS = {"twse_official_unadjusted": "TWSE 官方未還原價格（除權息日有價格缺口）"}
PRICE_SOURCE = {"twse_stock_day_official_raw_ohlcv": "TWSE 個股日成交資訊（STOCK_DAY）"}

SOURCE_STATUS = {
    "available": "可用", "available_with_events": "可用，有符合事件",
    "available_no_matching_events": "可用，無符合事件", "unavailable": "無法取得", "failed": "取得失敗",
    "degraded": "降級",
}


# ---------------------------------------------------------------- formatting

def _e(value: Any) -> str:
    return "—" if value is None else html.escape(str(value))


NA = '<span class="na" title="資料未提供">—</span>'


def _yi(value: Any, decimals: int = 1) -> str:
    """Raw TWD -> 新台幣億元."""
    if value is None:
        return NA
    return f"{float(value) / 1e8:,.{decimals}f}"


def _pct(value: Any, decimals: int = 1) -> str:
    if value is None:
        return NA
    return f"{float(value):.{decimals}f}%"


def _num(value: Any, decimals: int = 2) -> str:
    if value is None:
        return NA
    return f"{float(value):,.{decimals}f}"


def _chg(value: Any, unit: str = "%", decimals: int = 1) -> str:
    """Signed change with a text arrow so meaning never depends on colour."""
    if value is None:
        return NA
    v = float(value)
    if v > 0:
        return f'<span class="chg up">▲ +{v:.{decimals}f}{unit}</span>'
    if v < 0:
        return f'<span class="chg down">▼ {v:.{decimals}f}{unit}</span>'
    return f'<span class="chg">0{unit}</span>'


def _ratio(numer: Any, denom: Any) -> float | None:
    if numer is None or denom in (None, 0):
        return None
    return float(numer) / float(denom) * 100


def _roc_date(value: Any) -> str | None:
    s = str(value or "")
    if re.fullmatch(r"\d{7}", s):
        return f"{int(s[:3]) + 1911}-{s[3:5]}-{s[5:7]}"
    return None


def _roc_month(value: Any) -> str | None:
    s = str(value or "")
    if re.fullmatch(r"\d{5}", s):
        return f"{int(s[:3]) + 1911}-{s[3:5]}"
    return None


def _tpe(value: Any) -> str:
    try:
        return utc(value).astimezone(TAIPEI).strftime("%Y-%m-%d %H:%M")
    except Exception:  # noqa: BLE001 - display only
        return _e(value)


def _status(code: Any) -> str:
    label, symbol, tone = STATUS.get(code, (code or "未知", "?", "neutral"))
    return f'<span class="st st-{tone}"><span aria-hidden="true">{symbol}</span> {_e(label)}</span>'


def _link(url: Any, text: str = "來源") -> str:
    if not isinstance(url, str) or not url.startswith("https://"):
        return NA
    return f'<a href="{_e(url)}" target="_blank" rel="noopener">{_e(text)}</a>'


def _empty(title: str, message: str) -> str:
    return f'<div class="empty" role="note"><strong>{_e(title)}</strong><p>{message}</p></div>'


# ---------------------------------------------------------------- payload

def _report_records(report: dict[str, Any]) -> dict[str, Any]:
    raw_run_id = os.getenv("GITHUB_RUN_ID", "1")
    run_id = raw_run_id if re.fullmatch(r"[0-9]{1,30}", raw_run_id) else "1"
    raw_sha = os.getenv("GITHUB_SHA") or report.get("model_identity") or ("0" * 40)
    code_sha = raw_sha[:40] if re.fullmatch(r"[a-f0-9]{40,64}", str(raw_sha)) else ("0" * 40)
    generated = report.get("generated_utc") or datetime.now(timezone.utc).isoformat()
    started = report.get("started_utc") or generated
    snap = prepare_snapshot(report, {
        "repository": os.getenv("GITHUB_REPOSITORY") or "iceboxi/market-research",
        "run_id": run_id,
        "run_attempt": int(os.getenv("GITHUB_RUN_ATTEMPT", "1") or "1"),
        "code_sha": code_sha,
        "observed_at_utc": max(utc(generated), utc(started)).isoformat(),
    })
    market, symbol = snap["market"], snap["symbol"]
    return {
        f"snapshots/{market}/{symbol}/{snap['id']}.json": snap,
        f"subjects/{market}/{symbol}.json": {
            "schema_version": 2, "symbol": symbol, "issue_number": None,
            "latest_observation_id": snap["id"], "last_success_id": snap["id"],
        },
    }


def _stock_payload(records: dict[str, Any], market: str, symbol: str) -> dict[str, Any] | None:
    prefix = f"snapshots/{market}/{symbol}/"
    by_id = {v["id"]: v for p, v in records.items()
             if p.startswith(prefix) and isinstance(v, dict) and v.get("id")}
    if not by_id:
        return None
    chronological = sorted(by_id.values(), key=lambda s: (s.get("observed_at_utc") or "", s["id"]))
    comparisons: dict[str, dict[str, Any]] = {}
    previous = None
    last_good: dict[str, str] = {}
    for snap in chronological:
        comp = compare_snapshots(previous, snap, {k: by_id[v] for k, v in last_good.items()})
        cats = comp.get("categories") or []
        comp["status"] = cats[0] if cats in (["baseline"], ["unchanged"]) else "changed"
        comparisons[snap["id"]] = comp
        if snap.get("execution", {}).get("status") == "completed":
            previous = snap
        for key in ("issuer", "monthly_revenue", "technical", "events"):
            if available(snap, key):
                last_good[key] = snap["id"]
    subject = records.get(f"subjects/{market}/{symbol}.json") or {}
    latest = subject.get("last_success_id") or subject.get("latest_observation_id")
    if latest not in by_id:
        latest = chronological[-1]["id"]
    meta = MARKETS.get(market, {"exchange": market.upper(), "code": market.upper(), "currency": None, "currency_label": None})
    name = next((s["issuer"].get("company_name") for s in reversed(chronological)
                 if (s.get("issuer") or {}).get("company_name")), None)
    newest = [s["id"] for s in reversed(chronological)]
    embedded = set(newest[:MAX_EMBEDDED_VERSIONS]) | {latest}
    return {
        "symbol": symbol, "market": market, "name": name, **meta,
        "embedded_ids": embedded,
        "subject": subject,
        "checkpoint": records.get(f"checkpoints/{market}/{symbol}.json"),
        "snapshots": list(reversed(chronological)),
        "comparisons": comparisons,
        "latest_snapshot_id": latest,
    }


def latest_only_records(reports: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, str]]:
    """Records for stocks shown from today's report only (#125), and why any cannot be shown."""
    records: dict[str, Any] = {}
    skipped: dict[str, str] = {}
    for report in reports:
        try:
            records.update(_report_records(report))
        except (SnapshotError, ValueError, KeyError, TypeError) as error:
            skipped[str(report.get("symbol"))] = f"{type(error).__name__}: {error}"
    return records, skipped


def build_site_payload(
    records: dict[str, Any] | None = None,
    *,
    branch: str = "research-state",
    latest_report: dict[str, Any] | None = None,
    latest_only: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the read-only site bundle. Only symbols with resolvable snapshots are listed.

    `latest_only` (from `latest_only_records`) adds stocks that research-state does not keep;
    a symbol the state already holds is never mixed with them.
    """
    records = dict(records or {})
    if not records and latest_report is not None and latest_report.get("market") == "tw":
        records = _report_records(latest_report)
    stored = {m.group(2) for m in map(SUBJECT_RE.fullmatch, records) if m}
    extra_symbols = set()
    for path, value in (latest_only or {}).items():
        symbol = (value or {}).get("symbol") if isinstance(value, dict) else None
        if symbol and symbol not in stored:
            records[path] = value
            extra_symbols.add(symbol)
    keys = set()
    for path in records:
        m = SUBJECT_RE.fullmatch(path)
        if m:
            keys.add((m.group(1), m.group(2)))
    for path in records:
        m = re.fullmatch(r"snapshots/([a-z]+)/([A-Za-z0-9.\-]+)/[a-f0-9]{64}\.json", path)
        if m:
            keys.add((m.group(1), m.group(2)))
    stocks = {}
    for market, symbol in sorted(keys):
        stock = _stock_payload(records, market, symbol)
        if stock and symbol in extra_symbols:
            stock["latest_only"] = True
            for comp in stock["comparisons"].values():
                comp["status"] = "latest_only"
        if stock:
            stocks[symbol] = stock
    default = "2330.TW" if "2330.TW" in stocks else (next(iter(stocks)) if stocks else None)
    extra = {}
    if isinstance(latest_report, dict):
        tech = latest_report.get("technical") or {}
        extra = {"symbol": latest_report.get("symbol"),
                 "analytical_close": tech.get("analytical_close"), "currency": tech.get("currency"),
                 "last_session": tech.get("last_session"), "observations": tech.get("observations") or [],
                 "price_context": tech.get("price_context")}
    return {"schema_version": 2, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "branch": branch, "default_symbol": default, "stocks": stocks, "extra_technical": extra}


# ---------------------------------------------------------------- charts

def _quarterly_chart(rows: list[dict[str, Any]]) -> str:
    rows = [r for r in sorted(rows, key=lambda r: str(r.get("period_end"))) if r.get("revenue") is not None]
    if len(rows) < 2:
        return ""
    w, h, left, right, top, bottom = 720, 260, 56, 56, 24, 44
    pw, ph = w - left - right, h - top - bottom
    rmax = max(float(r["revenue"]) for r in rows) * 1.1
    slot = pw / len(rows)
    bw = min(46.0, slot * 0.55)
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" aria-labelledby="qchart-title">'
           '<title id="qchart-title">單季營收（長條，新台幣億元）與毛利率、淨利率（折線，%）</title>']
    for frac in (0, 0.5, 1):
        y = top + ph - frac * ph
        out.append(f'<line x1="{left}" x2="{w - right}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                   f'<text x="{left - 6}" y="{y + 4:.1f}" class="axis" text-anchor="end">{rmax * frac / 1e8:,.0f}</text>'
                   f'<text x="{w - right + 6}" y="{y + 4:.1f}" class="axis">{frac * 100:.0f}%</text>')
    lines: dict[str, list[str]] = {"gross_margin_pct": [], "net_margin_pct": []}
    for i, r in enumerate(rows):
        cx = left + slot * i + slot / 2
        bh = float(r["revenue"]) / rmax * ph
        out.append(f'<rect x="{cx - bw / 2:.1f}" y="{top + ph - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" class="bar">'
                   f'<title>{_e(r.get("period_label"))} 營收 {float(r["revenue"]) / 1e8:,.1f} 億元</title></rect>'
                   f'<text x="{cx:.1f}" y="{h - 22}" class="axis" text-anchor="middle">{_e(r.get("period_label"))}</text>')
        for key in lines:
            if r.get(key) is not None:
                lines[key].append(f"{cx:.1f},{top + ph - float(r[key]) / 100 * ph:.1f}")
    for key, cls in (("gross_margin_pct", "line-a"), ("net_margin_pct", "line-b")):
        if len(lines[key]) >= 2:
            out.append(f'<polyline points="{" ".join(lines[key])}" class="{cls}"/>')
        for pt in lines[key]:
            x, y = pt.split(",")
            out.append(f'<circle cx="{x}" cy="{y}" r="3" class="{cls}-pt"/>')
    out.append(f'<g class="legend" transform="translate({left},{h - 6})">'
               '<rect x="0" y="-9" width="10" height="10" class="bar"/><text x="14" y="0">單季營收（億元，左軸）</text>'
               '<line x1="170" x2="186" y1="-4" y2="-4" class="line-a"/><text x="190" y="0">毛利率（右軸）</text>'
               '<line x1="290" x2="306" y1="-4" y2="-4" class="line-b"/><text x="310" y="0">淨利率（右軸）</text></g>')
    out.append("</svg>")
    return "".join(out)


def _valuation_chart(models: list[tuple[str, list[tuple[str, float]]]]) -> str:
    values = [v for _, pts in models for _, v in pts]
    if not values:
        return ""
    w, left, right, row = 720, 170, 30, 46
    h = 30 + row * len(models)
    vmax = max(values) * 1.12
    def x(v: float) -> float:
        return left + v / vmax * (w - left - right)
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" aria-labelledby="vchart-title">'
           '<title id="vchart-title">各估值方法在保守、基準、樂觀倍數下的每股試算值（新台幣元）</title>']
    step = 500 if vmax > 1500 else 250
    tick = 0
    while tick <= vmax:
        out.append(f'<line x1="{x(tick):.1f}" x2="{x(tick):.1f}" y1="10" y2="{h - 18}" class="grid"/>'
                   f'<text x="{x(tick):.1f}" y="{h - 4}" class="axis" text-anchor="middle">{tick:,}</text>')
        tick += step
    for i, (label, pts) in enumerate(models):
        y = 26 + i * row
        lo, hi = min(v for _, v in pts), max(v for _, v in pts)
        out.append(f'<text x="{left - 10}" y="{y + 4}" class="axis" text-anchor="end">{_e(label)}</text>'
                   f'<line x1="{x(lo):.1f}" x2="{x(hi):.1f}" y1="{y}" y2="{y}" class="range"/>')
        for name, v in pts:
            out.append(f'<circle cx="{x(v):.1f}" cy="{y}" r="5" class="pt-{name}"><title>{_e(label)} {name}: {v:,.2f} 元</title></circle>'
                       f'<text x="{x(v):.1f}" y="{y - 10}" class="axis" text-anchor="middle">{v:,.0f}</text>')
    out.append("</svg>")
    return "".join(out)


def _price_chart(closes: list[dict[str, Any]], currency: str = "TWD", levels: dict[str, Any] | None = None) -> str:
    if not closes:
        return ""
    closes = [c for c in closes if c.get("close") is not None and c.get("date")]
    if len(closes) < 2:
        return ""
    levels = levels or {}
    w, h, left, right, top, bottom = 720, 240, 64, 52, 24, 44
    pw, ph = w - left - right, h - top - bottom

    prices = [float(c["close"]) for c in closes]
    sup = float(levels["support_20d"]) if levels.get("support_20d") is not None else None
    res = float(levels["resistance_20d"]) if levels.get("resistance_20d") is not None else None

    all_vals = list(prices)
    if sup is not None:
        all_vals.append(sup)
    if res is not None:
        all_vals.append(res)

    pmin_raw, pmax_raw = min(all_vals), max(all_vals)
    span = max(pmax_raw - pmin_raw, 1.0)
    pmin = pmin_raw - span * 0.08
    pmax = pmax_raw + span * 0.08

    def x_coord(i: int) -> float:
        return left + i * (pw / (len(closes) - 1))

    def y_coord(val: float) -> float:
        return top + ph - (val - pmin) / (pmax - pmin) * ph

    out = [f'<svg viewBox="0 0 {w} {h}" class="chart price-chart" role="img" aria-labelledby="pchart-title">'
           f'<title id="pchart-title">官方未還原收盤價走勢（{len(closes)} 個交易日）</title>']

    # Horizontal grid lines (4 ticks)
    for frac in (0.0, 0.333, 0.667, 1.0):
        val = pmin + frac * (pmax - pmin)
        y = y_coord(val)
        out.append(f'<line x1="{left}" x2="{w - right}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                   f'<text x="{left - 8}" y="{y + 4:.1f}" class="axis" text-anchor="end">{val:,.0f}</text>')

    # Support / Resistance reference lines if present
    if res is not None:
        ry = y_coord(res)
        out.append(f'<line x1="{left}" x2="{w - right}" y1="{ry:.1f}" y2="{ry:.1f}" class="level-res"/>'
                   f'<text x="{w - right + 4}" y="{ry + 3:.1f}" class="axis-res">前20日高 {res:,.0f}</text>')
    if sup is not None:
        sy = y_coord(sup)
        out.append(f'<line x1="{left}" x2="{w - right}" y1="{sy:.1f}" y2="{sy:.1f}" class="level-sup"/>'
                   f'<text x="{w - right + 4}" y="{sy + 3:.1f}" class="axis-sup">前20日低 {sup:,.0f}</text>')

    # Path points
    pts = [f"{x_coord(i):.1f},{y_coord(p):.1f}" for i, p in enumerate(prices)]
    # Fill area polygon
    poly_pts = [f"{left:.1f},{top + ph:.1f}"] + pts + [f"{w - right:.1f},{top + ph:.1f}"]
    out.append(f'<polygon points="{" ".join(poly_pts)}" class="price-area"/>')
    out.append(f'<polyline points="{" ".join(pts)}" class="price-line"/>')

    # Points for all sessions (with title tooltips)
    for i, (c, p) in enumerate(zip(closes, prices)):
        cx, cy = x_coord(i), y_coord(p)
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3" class="price-dot">'
                   f'<title>{_e(c["date"])}: {p:,.2f} {currency}</title></circle>')

    # Highlight latest session
    lx, ly = x_coord(len(closes) - 1), y_coord(prices[-1])
    out.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="5" class="price-dot-latest"/>'
               f'<text x="{lx:.1f}" y="{ly - 10:.1f}" class="axis-latest" text-anchor="end">{prices[-1]:,.1f} {currency}</text>')

    # X axis date labels: Start, Mid, End
    mid_i = len(closes) // 2
    out.append(f'<text x="{left:.1f}" y="{h - 18}" class="axis" text-anchor="start">{_e(closes[0]["date"])}</text>')
    out.append(f'<text x="{x_coord(mid_i):.1f}" y="{h - 18}" class="axis" text-anchor="middle">{_e(closes[mid_i]["date"])}</text>')
    out.append(f'<text x="{w - right:.1f}" y="{h - 18}" class="axis" text-anchor="end">{_e(closes[-1]["date"])}</text>')

    out.append("</svg>")
    return "".join(out)



# ---------------------------------------------------------------- sections

def _annual(fr: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(fr.get("annual_summary") or [], key=lambda r: str(r.get("fiscal_year")), reverse=True)


def _quarters(fr: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(fr.get("quarterly_summary") or [], key=lambda r: str(r.get("period_end")), reverse=True)


def _same_quarter_yoy(quarters: list[dict[str, Any]]) -> tuple[dict, dict, float] | None:
    if not quarters:
        return None
    latest = quarters[0]
    m = re.fullmatch(r"(\d{4})Q([1-4])", str(latest.get("period_label")))
    if not m:
        return None
    prior_label = f"{int(m.group(1)) - 1}Q{m.group(2)}"
    prior = next((q for q in quarters if q.get("period_label") == prior_label), None)
    if not prior or prior.get("revenue") in (None, 0) or latest.get("revenue") is None:
        return None
    return latest, prior, (float(latest["revenue"]) / float(prior["revenue"]) - 1) * 100


def _findings(fr: dict[str, Any], symbol: Any = None) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Return (findings, interpretation gaps). Each finding: (topic, statement html, basis)."""
    foundry = symbol == NARRATIVE_SYMBOL
    annual, quarters = _annual(fr), _quarters(fr)
    ttm = fr.get("ttm") or {}
    ytd = fr.get("latest_cumulative_interim") or {}
    bs = fr.get("latest_balance_sheet") or {}
    val = fr.get("valuation_summary") or {}
    out: list[tuple[str, str, str]] = []
    gaps = [
        "製程節點與應用別拆分缺漏：公開財報資料未提供先進製程（3nm/5nm/7nm 等）或終端應用（HPC/智慧手機/車用/IoT）營收拆分，無法由數據直接歸因個別產品線成長率。",
        "量價動態（ASP 與晶圓出貨量）缺漏：未包含晶圓出貨片數與平均單價（ASP），無法區分營收成長係由晶圓出貨放量或定價權溢價所主導。",
        "產業競爭格局與集中度缺漏：未包含主要客戶營收佔比、代工市佔率變化及競爭對手（如 Intel IFS、Samsung）產能動態。",
    ] if foundry else [
        "產品與應用別拆分缺漏：公開財報資料未提供產品線或終端應用的營收拆分，無法由數據直接歸因個別產品線成長率。",
        "量價動態缺漏：未包含出貨量與平均單價，無法區分營收成長來自出貨量或價格。",
        "產業競爭格局與集中度缺漏：未包含主要客戶營收佔比、市佔率變化及競爭對手動態。",
    ]
    gaps += [
        "質性與總體經濟風險缺漏：地緣政治風險、外匯匯率（美元/台幣）敏感度、電力與水資源供應等質性風險不在自動化資料契約內。",
        "嚴守非交易建議邊界：系統不產生投資評等、買賣建議、目標價或交易計畫（trade_plan = not_evaluated，recommendation = not_available）。",
    ]
    if annual:
        a0 = annual[0]
        parts = [f"FY{_e(a0.get('fiscal_year'))} 營收 {_yi(a0.get('revenue'))} 億元，年增 {_chg(a0.get('revenue_yoy_pct'))}"]
        if ytd.get("revenue_yoy_pct") is not None:
            parts.append(f"{_e(ytd.get('period_label'))} 累計營收 {_yi(ytd.get('revenue'))} 億元，較去年同期 {_chg(ytd.get('revenue_yoy_pct'))}")
        sq = _same_quarter_yoy(quarters)
        if sq:
            parts.append(f"{_e(sq[0]['period_label'])} 單季營收較 {_e(sq[1]['period_label'])} {_chg(sq[2])}（推導值）")
        out.append((
            "營收擴張動能",
            "；".join(parts) + "。" + _revenue_trend(a0.get("revenue_yoy_pct"), ytd.get("revenue_yoy_pct"))
            + ("；惟終端產品應用、先進製程佔比與下游庫存去化進度等驅動細節，非公開財務報表所揭露，屬於外部假設。" if foundry
               else "；惟產品組合、終端需求與下游庫存等驅動細節，非公開財務報表所揭露，屬於外部假設。"),
            "年度三表、累計財報與單季拆解（法定申報數值直接推導；未納入未經證實之庫存週期假設）"
        ))
        if len(annual) > 1 and a0.get("net_income_yoy_pct") is not None:
            a1 = annual[1]
            gm_delta = (None if a0.get("gross_margin_pct") is None or a1.get("gross_margin_pct") is None
                        else float(a0["gross_margin_pct"]) - float(a1["gross_margin_pct"]))
            nm_delta = (None if a0.get("net_margin_pct") is None or a1.get("net_margin_pct") is None
                        else float(a0["net_margin_pct"]) - float(a1["net_margin_pct"]))
            out.append((
                "營業槓桿與獲利結構",
                (
                    f"FY{_e(a0.get('fiscal_year'))} 稅後淨利年增 {_chg(a0.get('net_income_yoy_pct'))}，增幅顯著高於營收年增 "
                    f"{_chg(a0.get('revenue_yoy_pct'))}，損益表呈現營業利益率與淨利率同步走揚之營業槓桿效益；"
                    f"毛利率由 {_pct(a1.get('gross_margin_pct'))} 攀升至 {_pct(a0.get('gross_margin_pct'))}（{_chg(gm_delta, ' 個百分點')}），"
                    f"淨利率由 {_pct(a1.get('net_margin_pct'))} 上升至 {_pct(a0.get('net_margin_pct'))}（{_chg(nm_delta, ' 個百分點')}）。"
                    "固定成本攤提稀釋與產品組合轉佳為合理假說，但產能利用率（稼動率）與產品平均單價（ASP / 定價權）未於申報報表揭露，不得視為已證因果。"
                ),
                "年度損益表推導（淨利增速大於營收增速；稼動率與定價權為未經申報驗證之假說）"
            ))
    if ttm.get("status") == "available":
        out.append((
            "獲利能力（TTM）",
            (
                f"近四季（{_e('、'.join(ttm.get('quarters') or []))}）四個單季加總推導：毛利率 {_pct(ttm.get('gross_margin_pct'))}、"
                f"營業利益率 {_pct(ttm.get('operating_margin_pct'))}、淨利率 {_pct(ttm.get('net_margin_pct'))}；"
                f"TTM 基本 EPS 達 {_num(ttm.get('basic_eps'))} 元。整體各項利潤率指標維持在五至六成之高水準區間。"
            ),
            "四季單季加總（TTM，各季加總股數漂移 ≤ 0.5%）"
        ))
        capex_int = _ratio(ttm.get("capex"), ttm.get("revenue"))
        fcf_conv = _ratio(ttm.get("free_cash_flow"), ttm.get("net_income"))
        ocf_ni = _ratio(ttm.get("operating_cash_flow"), ttm.get("net_income"))
        out.append((
            "現金流品質與再投資",
            (
                f"TTM 營業現金流 {_yi(ttm.get('operating_cash_flow'))} 億元，為同期淨利之 {_pct(ocf_ni, 0)}（營業現金流對淨利比 > 1.0）；"
                f"資本支出 {_yi(ttm.get('capex'))} 億元（佔營收 {_pct(capex_int)}），"
                f"扣除高額擴產投資後產出自由現金流 {_yi(ttm.get('free_cash_flow'))} 億元（約為淨利的 {_pct(fcf_conv, 0)}，FCF 利潤率 {_pct(ttm.get('fcf_margin_pct'))}）。"
                "營運現金流量充沛，但重資本再投資特性導致近半數淨利轉化為廠房設備投資；應收帳款與存貨週轉天數之細部營運資金品質未納入本次資料契約。"
            ),
            "TTM 現金流量表推導（FCF = 營業現金流 − 資本支出；未含營運資金細項週期驗證）"
        ))
    if bs.get("net_cash") is not None:
        out.append((
            "資產負債與流動性緩衝",
            (
                f"截至 {_e(bs.get('period_end'))}，現金及約當現金 {_yi(bs.get('cash'))} 億元，有息負債（公司債及長短期借款）合計 {_yi(bs.get('total_debt'))} 億元，"
                f"帳面淨現金頭寸達 {_yi(bs.get('net_cash'))} 億元（每股淨現金約 {_num(val.get('net_cash_twd_per_ordinary_share'))} 元）。"
                "帳面流動資金大於帳面有息負債，具備顯著現金緩衝；惟長短期借款到期排程、"
                + ("跨國建廠承諾款" if foundry else "資本支出承諾") +
                "與未入帳資本合約等表外義務仍須參閱完整財報附註，非保證零流動性風險。"
            ),
            "最新資產負債表時點值（現金與長短期有息負債對比；未含表外資本合約與到期排程分析）"
        ))
    if val:
        mult = val.get("exchange_multiples") or {}
        fcf_s, pe_s = val.get("fair_value_scenarios") or {}, val.get("ttm_pe_scenarios") or {}
        fcf_m = [s.get("fcf_multiple") for s in fcf_s.values() if s.get("fcf_multiple") is not None]
        pe_m = [s.get("pe_multiple") for s in pe_s.values() if s.get("pe_multiple") is not None]
        text = []
        if mult.get("pe_ratio") is not None:
            text.append(f"證交所公布本益比約 {_num(mult.get('pe_ratio'))} 倍、殖利率 {_pct(mult.get('dividend_yield_pct'), 2)}")
        fcf_v = [s.get(k) for s in fcf_s.values() for k in ("indicative_twd_per_share", "indicative_ttm_fcf_twd_per_share")
                 if isinstance(s.get(k), (int, float))]
        pe_v = [s.get("indicative_twd_per_share") for s in pe_s.values()
                if isinstance(s.get("indicative_twd_per_share"), (int, float))]
        if fcf_m and pe_m:
            text.append(f"敏感度模型假設 P/FCF {min(fcf_m):g}–{max(fcf_m):g} 倍（試算 {_span(fcf_v)} 元）、"
                        f"P/E {min(pe_m):g}–{max(pe_m):g} 倍（試算 {_span(pe_v)} 元）")
        conv = _ratio(ttm.get("free_cash_flow"), ttm.get("net_income"))
        gap = (sum(pe_v) / len(pe_v)) / (sum(fcf_v) / len(fcf_v)) if pe_v and fcf_v and sum(fcf_v) > 0 else None
        spread = (f"兩大方法試算值平均相差約 {gap:.1f} 倍，主要源於" if gap and gap >= 1.2 else "兩大方法試算值的差異來自")
        cash = f"，使當期 FCF 約為淨利之 {conv:.0f}%" if conv is not None else ""
        if text:
            out.append((
                "估值模型與結構性落差",
                (
                    "；".join(text) + "。"
                    + spread + f"資本支出與折舊的時間差：折舊認列時間落後於當期現金流出{cash}；"
                    "各項試算值受外生倍數假設高度主導，僅供敏感度觀察，絕非合理價、目標價或買賣建議。"
                ),
                "TWSE BWIBBU_ALL 與估值敏感度模型（情境試算非營運預測，不作交易依據）"
            ))
    return out, gaps


def _revenue_trend(annual_yoy: Any, ytd_yoy: Any) -> str:
    """Growth wording from the reported changes only, never assumed."""
    rates = [float(v) for v in (annual_yoy, ytd_yoy) if isinstance(v, (int, float))]
    if not rates:
        return "申報數據未提供可比較的年增率"
    if all(r >= 10 for r in rates):
        return "申報數據顯示年度與累計營收維持雙位數高速增長"
    if all(r >= 0 for r in rates):
        return "申報數據顯示年度與累計營收維持成長"
    if all(r < 0 for r in rates):
        return "申報數據顯示年度與累計營收較去年減少"
    return "申報數據顯示年度與累計營收的增減方向不一致"


def _uncertainties(snap: dict[str, Any], fr: dict[str, Any] | None) -> list[str]:
    foundry = snap.get("symbol") == NARRATIVE_SYMBOL
    items = []
    if fr:
        ttm = fr.get("ttm") or {}
        conv = _ratio(ttm.get("free_cash_flow"), ttm.get("net_income"))
        if conv is not None:
            plan = "未來先進製程（如 2nm / A16 / 跨國建廠）資本支出" if foundry else "未來資本支出"
            items.append(f"資本支出週期波動：自由現金流僅約淨利的 {conv:.0f}%（TTM 推導值）；{plan}若超預期增加，將直接壓抑自由現金流與 P/FCF 估值試算。")
        for ev in (fr.get("calendar_schedule") or {}).get("events") or []:
            if ev.get("scheduled_date") is None and ev.get("event_type") != "statutory_filing_deadline":
                items.append(f"關鍵公司行動未定：{_e(ev.get('title'))} 尚未正式公告確定日期。")
    if snap.get("readiness", {}).get("events") == "no_recent_observed_events":
        items.append("事件觀測範圍限制：重大訊息與事件觀測僅涵蓋最近一次每日快照，非全歷史事件庫；未觀測到事件不代表無潛在營運或法規風險。")
    if "prices_metadata_only" in (snap.get("comparison_limits") or []):
        items.append("行情序列未持久化：狀態儲存契約僅保留行情檢驗 metadata 與雜湊，未保存歷史 OHLCV 價格序列，無法重播技術指標或回測走勢。")
    items.append("外部與質性不確定性：先進製程良率爬坡速度、主要雲端/AI 客戶資本支出週期、地緣政治監管（晶片法案與出口管制）及水電資源供應等質性風險，本系統未納入量化評估。"
                 if foundry else
                 "外部與質性不確定性：產業景氣、主要客戶需求、地緣政治與法規變化等質性風險，本系統未納入量化評估。")
    return items


def _overview(snap: dict[str, Any], comp: dict[str, Any], stock: dict[str, Any], extra: dict[str, Any]) -> str:
    fr = snap.get("financial_research") if (snap.get("financial_research") or {}).get("status") == "available" else None
    tech = snap.get("technical") or {}
    readiness = snap.get("readiness") or {}
    mrev = (snap.get("monthly_revenue") or [None])[0] if snap.get("monthly_revenue") else None
    price = '<span class="na">未保存收盤價</span> <a href="#technical" class="hint">（依契約僅保存行情 metadata）</a>'
    closes = [c for c in tech.get("recent_closes") or [] if c.get("close") is not None and c.get("date")]
    if closes:
        price = (f"{_num(closes[-1]['close'])} {_e(stock.get('currency'))}"
                 f' <span class="hint">TWSE 收盤價，{_e(closes[-1]["date"])}</span>')
    if extra.get("analytical_close") is not None:
        price = (f"{_num(extra['analytical_close'])} {_e(extra.get('currency') or stock.get('currency'))}"
                 f' <span class="hint">分析用收盤價，{_e(extra.get("last_session"))}</span>')
    meta = [
        ("研究產生時間", f"{_tpe(snap.get('observed_at_utc'))} <span class=\"hint\">台北時間</span>"),
        ("財報基準期", _e(fr.get("reconciled_period_end")) if fr else NA),
        ("最新完整交易日", _e(tech.get("session"))),
        ("最新月營收", f"{_e(_roc_month(mrev.get('period')))}" if mrev else NA),
        ("收盤價", price),
        ("與前一版本", _e(COMPARISON_LABELS.get(comp.get("status"), "有研究變化"))
         if comp.get("status") in ("baseline", "unchanged", "latest_only")
         else "有研究變化 <a href=\"#m-compare\">查看明細</a>"),
    ]
    meta_html = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in meta)

    strip_items = []
    for key, name, _ in MODULES:
        code = readiness.get(key, "not_evaluated")
        strip_items.append(f'<span class="item"><span class="lbl">{name}</span> {_status(code)}</span>')
    readiness_ribbon = (f'<div class="readiness-strip"><span class="title">研究模組就緒度：</span>'
                        + " ".join(strip_items)
                        + ' <a href="#m-status" class="hint">完整檢驗代碼</a></div>')

    if fr:
        findings, gaps = _findings(fr, snap.get("symbol"))
        findings_html = "".join(
            f'<li><h4>{_e(t)}</h4><p>{s}</p><p class="basis">依據：{_e(b)}</p></li>' for t, s, b in findings)
        gaps_html = "".join(f"<li>{g}</li>" for g in gaps)
        body = (f'<ol class="findings">{findings_html}</ol>'
                f'<div class="callout warn"><strong>投資研究缺失證據與資料邊界（待擴充資料契約）</strong><ul>{gaps_html}</ul></div>'
                + _key_metrics(fr))
    else:
        body = _empty("此研究版本沒有完整財務研究",
                      f"當時財務研究狀態：{_status(readiness.get('financial', 'unavailable'))}。"
                      "研究重點與核心指標需要財務研究資料；請切換至較新的研究版本。")

    risks = "".join(f"<li>{x}</li>" for x in _uncertainties(snap, fr))
    return f"""
<section id="overview" aria-labelledby="h-overview">
  <h2 id="h-overview">研究總覽</h2>
  <dl class="meta">{meta_html}</dl>
  {readiness_ribbon}
  <h3>商業表現與財務動能分析</h3>
  <p class="lede">基於官方已對帳財務數據推導；標示「推導值」者為同口徑報表數字直接運算之比率，未添加外部主觀估計。</p>
  <div class="callout" role="note">
    <strong>分析宣稱認識論分級原則（Epistemological Standards）：</strong>
    <ul class="plain">
      <li><strong>直接觀測事實（Reported Facts）</strong>：法定申報之財報數額（如各期營收、淨利、現金頭寸、TWSE 公布倍數）。</li>
      <li><strong>報表推導指標（Derived Metrics）</strong>：同口徑數據依明確恆等式推導（如 OCF/淨利比、資本支出/營收、淨現金、YoY 變動）。</li>
      <li><strong>合理推論假說（Plausible Hypotheses）</strong>：對報表動能之合理解釋（如營業槓桿效應可能源於產能規模攤提），但未經申報驗證者一律標明為假說。</li>
      <li><strong>需外部補充證據之邊界（Evidence Gaps）</strong>：產能利用率、{"晶圓平均單價（ASP）" if snap.get("symbol") == NARRATIVE_SYMBOL else "平均單價"}、定價權、庫存調整週期、債務到期排程等非公開申報資料，不得冒充既證事實。</li>
    </ul>
  </div>
  {body}
  <h3>主要營運與市場不確定性</h3>
  <ul class="plain">{risks}</ul>
</section>"""


def _key_metrics(fr: dict[str, Any]) -> str:
    ttm = fr.get("ttm") or {}
    annual = _annual(fr)[:3]
    cols = []
    if ttm.get("status") == "available":
        q = ttm.get("quarters") or []
        cols.append((f"TTM<span class=\"sub\">{_e(q[0] if q else '')}–{_e(q[-1] if q else '')}</span>", ttm))
    cols += [(f"FY{_e(a.get('fiscal_year'))}<span class=\"sub\">{_e(a.get('period_end'))}</span>", a) for a in annual]
    if not cols:
        return ""
    rows = [
        ("營業收入", "revenue", "yi", "億元"), ("營收年增率", "revenue_yoy_pct", "chg", "%"),
        ("毛利率", "gross_margin_pct", "pct", "%"), ("營業利益率", "operating_margin_pct", "pct", "%"),
        ("淨利率", "net_margin_pct", "pct", "%"), ("基本 EPS", "basic_eps", "num", "元"),
        ("營業現金流", "operating_cash_flow", "yi", "億元"), ("自由現金流", "free_cash_flow", "yi", "億元"),
        ("FCF 利潤率", "fcf_margin_pct", "pct", "%"),
    ]
    fmt = {"yi": _yi, "chg": _chg, "pct": _pct, "num": _num}
    head = "".join(f'<th scope="col" class="num">{c}</th>' for c, _ in cols)
    body = "".join(
        f'<tr><th scope="row">{label}<span class="unit">{unit}</span></th>'
        + "".join(f'<td class="num">{fmt[kind](src.get(key))}</td>' for _, src in cols) + "</tr>"
        for label, key, kind, unit in rows)
    bs = fr.get("latest_balance_sheet") or {}
    return f"""
  <h3>核心指標</h3>
  <div class="table-wrap"><table class="metrics"><thead><tr><th scope="col">指標（單位）</th>{head}</tr></thead><tbody>{body}</tbody></table></div>
  <p class="note">金額為新台幣億元。TTM 為最近四個單季加總；FY 為完整會計年度；兩者不可直接當作同期比較。
  TTM 營收年增率未由研究引擎計算，因此顯示「—」。淨現金為 {_e(bs.get('period_end'))} 時點值：{_yi(bs.get('net_cash'))} 億元。</p>"""


def _fundamentals(fr: dict[str, Any] | None, snap: dict[str, Any]) -> str:
    if not fr:
        return f"""
<section id="fundamentals" aria-labelledby="h-fund"><h2 id="h-fund">基本面</h2>
{_empty("此研究版本沒有財務研究資料", f"財務研究狀態：{_status((snap.get('readiness') or {}).get('financial', 'unavailable'))}。")}</section>"""
    quarters, annual = _quarters(fr), _annual(fr)
    ttm, ytd, bs = fr.get("ttm") or {}, fr.get("latest_cumulative_interim") or {}, fr.get("latest_balance_sheet") or {}
    q_rows = "".join(
        f'<tr><th scope="row">{_e(q.get("period_label"))}<span class="sub">{_e(q.get("period_start"))}–{_e(q.get("period_end"))}</span></th>'
        f'<td class="num">{_yi(q.get("revenue"))}</td><td class="num">{_pct(q.get("gross_margin_pct"))}</td>'
        f'<td class="num">{_pct(q.get("operating_margin_pct"))}</td><td class="num">{_pct(q.get("net_margin_pct"))}</td>'
        f'<td class="num">{_num(q.get("basic_eps"))}</td><td class="num">{_yi(q.get("operating_cash_flow"))}</td>'
        f'<td class="num">{_yi(q.get("capex"))}</td><td class="num">{_yi(q.get("free_cash_flow"))}</td>'
        f'<td class="basis-cell">{_e(QUARTER_BASIS.get(q.get("basis"), q.get("basis")))}</td></tr>' for q in quarters)
    a_rows = "".join(
        f'<tr><th scope="row">FY{_e(a.get("fiscal_year"))}</th><td class="num">{_yi(a.get("revenue"))}</td>'
        f'<td class="num">{_yi(a.get("gross_profit"))}</td><td class="num">{_yi(a.get("operating_income"))}</td>'
        f'<td class="num">{_yi(a.get("net_income"))}</td><td class="num">{_yi(a.get("parent_net_income"))}</td>'
        f'<td class="num">{_num(a.get("basic_eps"))}</td><td class="num">{_yi(a.get("operating_cash_flow"))}</td>'
        f'<td class="num">{_yi(a.get("capex"))}</td><td class="num">{_yi(a.get("free_cash_flow"))}</td>'
        f'<td class="num">{_chg(a.get("fcf_yoy_pct"))}</td></tr>' for a in annual)
    eps_basis = {"sum_of_four_quarters_within_0.5pct_share_drift": "四季 EPS 加總（各季股數差異 ≤ 0.5%）"}
    ttm_note = ""
    if ttm.get("status") == "available":
        ttm_note = (f'<p class="note">TTM 由 {_e("、".join(ttm.get("quarters") or []))} 四個單季加總：營收 {_yi(ttm.get("revenue"))} 億元、'
                    f'淨利 {_yi(ttm.get("net_income"))} 億元、EPS {_num(ttm.get("basic_eps"))} 元'
                    f'（{_e(eps_basis.get(ttm.get("eps_derivation"), ttm.get("eps_derivation")))}；股數最大差異 {_num(ttm.get("share_count_max_drift_pct"), 4)}%）。</p>')
    bs_rows = [("現金及約當現金", bs.get("cash")), ("應付公司債", bs.get("bonds_payable")),
               ("長期借款", bs.get("long_term_borrowings")), ("有息負債合計", bs.get("total_debt")),
               ("淨現金（現金 − 有息負債）", bs.get("net_cash")), ("資產總計", bs.get("total_assets")),
               ("負債總計", bs.get("total_liabilities")), ("權益總計", bs.get("total_equity")),
               ("歸屬母公司權益", bs.get("parent_equity"))]
    ytd_rows = [("營業收入", _yi(ytd.get("revenue")), _chg(ytd.get("revenue_yoy_pct"))),
                ("營業毛利", _yi(ytd.get("gross_profit")), NA), ("營業利益", _yi(ytd.get("operating_income")), NA),
                ("稅前淨利", _yi(ytd.get("pre_tax_income")), NA),
                ("本期淨利", _yi(ytd.get("net_income")), _chg(ytd.get("net_income_yoy_pct"))),
                ("基本 EPS（元）", _num(ytd.get("basic_eps")), NA),
                ("營業現金流", _yi(ytd.get("operating_cash_flow")), NA), ("資本支出", _yi(ytd.get("capex")), NA),
                ("自由現金流", _yi(ytd.get("free_cash_flow")), NA)]
    div_rows = "".join(
        f'<tr><th scope="row">{_e(d.get("period"))}</th><td>{_e(_roc_date(d.get("board_Or_approval_date_roc")))}</td>'
        f'<td class="num">{_num(d.get("cash_dividend_per_share_twd"), 2)}</td><td class="num">{_num(d.get("stock_dividend_per_share_twd"), 2)}</td>'
        f'<td class="num">{_yi(d.get("parent_net_income_twd"))}</td><td>{_link(d.get("source"))}</td></tr>'
        for d in fr.get("dividend_schedule") or [])
    ex_rows = "".join(
        f'<tr><th scope="row">{_e(x.get("ex_date"))}</th><td>{_e(x.get("type"))}</td>'
        f'<td class="num">{_num(x.get("dividend_per_share_twd"), 2)}</td><td class="num">{_num(x.get("before_price"))}</td>'
        f'<td class="num">{_num(x.get("reference_price"))}</td></tr>' for x in fr.get("ex_dividend_history") or [])
    val = fr.get("valuation_summary") or {}
    denom = val.get("denominator") or {}
    return f"""
<section id="fundamentals" aria-labelledby="h-fund">
  <h2 id="h-fund">基本面</h2>
  <h3>單季趨勢</h3>
  <figure class="chart-box">{_quarterly_chart(quarters)}<figcaption>單季數字由累計財報拆解，各季核對方式見表格最後一欄。</figcaption></figure>
  <div class="table-wrap"><table><thead><tr><th scope="col">季度</th><th scope="col" class="num">營收<span class="unit">億元</span></th>
  <th scope="col" class="num">毛利率</th><th scope="col" class="num">營益率</th><th scope="col" class="num">淨利率</th>
  <th scope="col" class="num">EPS<span class="unit">元</span></th><th scope="col" class="num">營業現金流<span class="unit">億元</span></th>
  <th scope="col" class="num">資本支出<span class="unit">億元</span></th><th scope="col" class="num">自由現金流<span class="unit">億元</span></th>
  <th scope="col">單季口徑</th></tr></thead><tbody>{q_rows}</tbody></table></div>
  {ttm_note}

  <h3>年度損益與現金流</h3>
  <div class="table-wrap"><table><thead><tr><th scope="col">會計年度</th><th scope="col" class="num">營收</th><th scope="col" class="num">毛利</th>
  <th scope="col" class="num">營業利益</th><th scope="col" class="num">淨利</th><th scope="col" class="num">母公司淨利</th>
  <th scope="col" class="num">EPS<span class="unit">元</span></th><th scope="col" class="num">營業現金流</th><th scope="col" class="num">資本支出</th>
  <th scope="col" class="num">自由現金流</th><th scope="col" class="num">FCF 年增</th></tr></thead><tbody>{a_rows}</tbody></table></div>
  <p class="note">金額單位：新台幣億元。合併報表口徑。</p>

  <div class="two-col">
    <div>
      <h3>資產負債（{_e(bs.get('period_end'))} 時點）</h3>
      <div class="table-wrap"><table class="kv"><tbody>{''.join(f'<tr><th scope="row">{k}</th><td class="num">{_yi(v)}</td></tr>' for k, v in bs_rows)}</tbody></table></div>
      <p class="note">單位：新台幣億元。</p>
    </div>
    <div>
      <h3>年初至今累計（{_e(ytd.get('period_label'))}）</h3>
      <div class="table-wrap"><table class="kv"><thead><tr><th scope="col">{_e(ytd.get('period_start'))}–{_e(ytd.get('period_end'))}</th><th scope="col" class="num">金額</th><th scope="col" class="num">較去年同期</th></tr></thead>
      <tbody>{''.join(f'<tr><th scope="row">{k}</th><td class="num">{v}</td><td class="num">{c}</td></tr>' for k, v, c in ytd_rows)}</tbody></table></div>
      <p class="note">累計值不是單季值。金額單位：新台幣億元。</p>
    </div>
  </div>

  <h3>股利與股數</h3>
  <div class="table-wrap"><table><thead><tr><th scope="col">盈餘期別</th><th scope="col">董事會決議日</th><th scope="col" class="num">現金股利<span class="unit">元/股</span></th>
  <th scope="col" class="num">股票股利<span class="unit">元/股</span></th><th scope="col" class="num">該期母公司淨利<span class="unit">億元</span></th><th scope="col">來源</th></tr></thead>
  <tbody>{div_rows or f'<tr><td colspan="6">{NA} 無股利分派資料</td></tr>'}</tbody></table></div>
  <div class="table-wrap"><table><caption>除權息紀錄（TWSE）</caption><thead><tr><th scope="col">除權息日</th><th scope="col">類型</th>
  <th scope="col" class="num">每股配發<span class="unit">元</span></th><th scope="col" class="num">除權息前收盤</th><th scope="col" class="num">參考價</th></tr></thead>
  <tbody>{ex_rows or f'<tr><td colspan="5">{NA} 無除權息資料</td></tr>'}</tbody></table></div>
  <p class="note">股數核對：TWSE 公司基本資料實收資本額 {_num(fr.get('paid_in_capital_twd'), 0)} 元，對應已發行普通股 {_num(fr.get('issued_ordinary_shares'), 0)} 股；
  資產負債表股本換算 {_num(bs.get('ordinary_shares'), 0)} 股；估值分母採 {_num(denom.get('value'), 0)} 股（{_e(denom.get('period_end'))}）。</p>
</section>"""


def _valuation_zone(fr: dict[str, Any] | None, symbol: Any) -> str:
    """Historical P/E review zone (#114); a prompt to look again, not a price target."""
    zone = (fr or {}).get("valuation_zone")
    if not zone:
        return ""
    head = '<h3>估值檢視區（歷史本益比）</h3>'
    note = (f'<div class="callout warn" role="note"><strong>{_e(zone.get("disclaimer") or DISCLAIMER)}。</strong>'
            '價位 = 本益比區間 × 近四季 EPS；價格進出區間只代表值得重新檢視，不是合理價、目標價或進出場價格。</div>')
    if zone.get("status") != "available":
        return head + note + _empty("此次未計算檢視區", f"not_evaluated：{_e(zone.get('reason'))}")
    prices, band = zone["review_prices_twd"], zone["pe_band"]
    price, eps, hist = zone["price"], zone["eps"] or {}, zone.get("per_history") or {}
    quarters = eps.get("quarters") or []
    # Public snapshots drop the query URL; it is fixed by the ticker and window start.
    source = hist.get("source") or (finmind_per_url(str(symbol).split(".")[0], hist["window_start"])
                                    if hist.get("window_start") else None)
    if zone.get("method") == "configured_pe_multiples_x_ttm_eps":
        method = "設定的固定本益比倍數（config/watchlist.yaml）"
    else:
        method = "近 5 年每日本益比 " + "／".join(f"P{q}" for q in zone.get("percentiles") or [])
    cells = "".join(f'<td class="num">{_num(prices[k])}<br><span class="unit">{_num(band[k])}x</span></td>'
                    for k in ("low", "mid", "high"))
    sample = (f'{_e(hist.get("samples"))} 筆（{_e(hist.get("first_date"))}～{_e(hist.get("last_date"))}），'
              f'最新 {_num(hist.get("latest_per"))}x · {_link(source, "FinMind TaiwanStockPER")}'
              if hist else NA)
    return f"""{head}{note}
  <div class="table-wrap"><table><thead><tr><th scope="col">收盤（{_e(price.get('session'))}）</th>
  <th scope="col" class="num">偏低價<span class="unit">元/股</span></th><th scope="col" class="num">合理價<span class="unit">元/股</span></th>
  <th scope="col" class="num">偏高價<span class="unit">元/股</span></th><th scope="col">目前區間</th></tr></thead>
  <tbody><tr><td class="num">{_num(price.get('close'))}</td>{cells}<td>{_e(ZONE_LABELS.get(zone.get('zone')))}</td></tr></tbody></table></div>
  <dl class="meta">
    <div><dt>方法</dt><dd>{_e(method)} × 近四季基本 EPS</dd></div>
    <div><dt>近四季 EPS</dt><dd>{_num(eps.get('ttm_basic_eps'))} 元（{_e(quarters[0] if quarters else None)}–{_e(quarters[-1] if quarters else None)}，截至 {_e(eps.get('period_end'))}）</dd></div>
    <div><dt>本益比樣本</dt><dd>{sample}</dd></div>
  </dl>"""


def _signed(value: Any) -> str:
    return f"{value:+.2f}%" if isinstance(value, (int, float)) else NA


def _watch_measure(measure: dict[str, Any], detail: str) -> str:
    if measure.get("status") != "available":
        return '<td class="num">未評估</td>'
    return f'<td class="num">{_signed(measure["pct"])}<span class="unit">{detail}</span></td>'


def _price_watch_row(row: dict[str, Any]) -> str:
    label = f'{_e(row["symbol"])}<span class="unit">{_e(row.get("name") or "")}</span>'
    if row.get("status") == "failed":
        return (f'<tr><th scope="row">{label}</th><td class="num">{NA}</td><td class="num">{NA}</td>'
                f'<td class="num">{NA}</td><td>取得失敗：{_e(row.get("error_type"))}：{_e(row.get("reason"))}</td></tr>')
    high, ma = row["drawdown_52w"], row["ma_200"]
    high_detail = f'高點 {_num(high.get("high"))}（{_e(high.get("high_date"))}）'
    ma_detail = f'均線 {_num(ma.get("average"))}'
    return (f'<tr><th scope="row">{label}</th>'
            f'<td class="num">{_num(row["close"])}<span class="unit">{_e(row["session"])}</span></td>'
            f'{_watch_measure(high, high_detail)}{_watch_measure(ma, ma_detail)}'
            f'<td>{_e(price_watch_notes(row))}</td></tr>')


def _thesis_cell(check: dict[str, Any] | None) -> str:
    if not check or check.get("revenue") is None:
        return f"<td>{NA}</td>"
    reason = f'<span class="unit">{_e(check["reason"])}</span>' if check.get("reason") else ""
    return f'<td>{_e(THESIS_LABELS.get(check["status"], check["status"]))}{reason}</td>'


def _zone_row(symbol: str, zone: dict[str, Any] | None, name: Any, check: dict[str, Any] | None) -> str:
    label = f'{_e(symbol)}<span class="unit">{_e(name or "")}</span>'
    if zone is None:
        return (f'<tr><th scope="row">{label}</th><td class="num">{NA}</td>'
                f'<td colspan="4">{NA}</td>{_thesis_cell(check)}</tr>')
    price = zone.get("price") or {}
    close = (f'{_num(price.get("close"))}<span class="unit">{_e(price.get("session"))}</span>'
             if price else NA)
    if zone.get("status") != "available":
        return (f'<tr><th scope="row">{label}</th><td class="num">{close}</td>'
                f'<td colspan="4">未評估：{_e(zone.get("reason"))}</td>{_thesis_cell(check)}</tr>')
    prices = zone["review_prices_twd"]
    cells = "".join(f'<td class="num">{_num(prices[k])}</td>' for k in ("low", "mid", "high"))
    return (f'<tr><th scope="row">{label}</th><td class="num">{close}</td>{cells}'
            f'<td>{_e(ZONE_LABELS.get(zone.get("zone")))}</td>{_thesis_cell(check)}</tr>')


def _watchlist_overview(watchlist: dict[str, Any] | None) -> str:
    """Daily watchlist overview (#113, #115): core ETF / TAIEX positions, satellite zones and thesis checks.

    Supplied only by the daily TW run; a manual publication renders without it.
    """
    if not watchlist:
        return ""
    rows = watchlist.get("price_watch") or []
    zones = watchlist.get("valuation_zones") or {}
    names = watchlist.get("names") or {}
    checks = watchlist.get("thesis_checks") or {}
    satellites = list(zones) + [s for s in checks if s not in zones]
    if not rows and not satellites:
        return ""
    parts = ['<section id="watchlist" class="watchlist" aria-labelledby="watchlist-title">'
             '<h2 id="watchlist-title">觀察名單總覽</h2>']
    if rows:
        parts.append(
            f'<h3>核心 ETF 與加權指數</h3><p class="disclaimer">{_e(PRICE_WATCH_DISCLAIMER)}。'
            f'距高點 = 收盤 ÷ 近 {WINDOW_WEEKS} 週最高價 − 1；距均線 = 收盤 ÷ 近 {MA_SESSIONS} 個交易日收盤平均 − 1。'
            'TWSE 官方日 K；分割等依 TWSE 參考價還原，除息未還原。</p>'
            '<div class="table-wrap"><table><thead><tr><th scope="col">標的</th>'
            '<th scope="col" class="num">收盤<span class="unit">日期</span></th>'
            f'<th scope="col" class="num">距 {WINDOW_WEEKS} 週高點</th>'
            f'<th scope="col" class="num">距 {MA_SESSIONS} 日均線</th><th scope="col">備註</th></tr></thead>'
            f'<tbody>{"".join(_price_watch_row(r) for r in rows)}</tbody></table></div>')
    if satellites:
        parts.append(
            f'<h3>衛星個股估值檢視區與論點檢查</h3><p class="disclaimer">{_e(DISCLAIMER)}。'
            '價位 = 本益比區間 × 近四季 EPS；論點檢查看月營收年增率與當日重大公告。'
            '方法與樣本見各股估值章節或每日 Artifact。</p>'
            '<div class="table-wrap"><table><thead><tr><th scope="col">標的</th>'
            '<th scope="col" class="num">收盤<span class="unit">日期</span></th>'
            '<th scope="col" class="num">偏低價<span class="unit">元/股</span></th>'
            '<th scope="col" class="num">合理價<span class="unit">元/股</span></th>'
            '<th scope="col" class="num">偏高價<span class="unit">元/股</span></th>'
            '<th scope="col">目前區間</th><th scope="col">論點檢查</th></tr></thead>'
            f'<tbody>{"".join(_zone_row(s, zones.get(s), names.get(s), checks.get(s)) for s in satellites)}'
            '</tbody></table></div>')
    parts.append("</section>")
    return "".join(parts)


FOUNDRY_SCENARIOS = {
    "conservative": ("終端消費電子需求復甦停滯、全球景氣走緩；先進製程稼動率跌破 75%；高額資本支出後折舊壓力大增侵蝕獲利。",
                     "AI 與高效能運算需求外溢擴大、產能持續供不應求。"),
    "base": ("半導體維持中長期複合成長常態（CAGR 15–20%）；先進製程維持 85–90% 健康稼動率；毛利率維持在長期目標 53% 以上。",
             "總經急遽惡化或出現非預期之良率/客戶轉單瓶頸。"),
    "optimistic": ("AI / HPC 算力需求呈現結構性跳躍；N2/A16 技術大幅領先且享有顯著溢價定價權；毛利率長期穩居 60% 以上。",
                   "雲端大廠 Capex 縮減、競爭對手製程重大突破或定價競爭。"),
}
GENERIC_SCENARIOS = {
    "conservative": ("景氣走緩或終端需求下滑，獲利與自由現金流低於近期水準。", "需求回升、獲利優於預期。"),
    "base": ("營運大致延續近期的成長與獲利水準。", "總經急遽惡化或出現公司特有的營運事件。"),
    "optimistic": ("需求強勁且具定價能力，獲利與自由現金流高於近期水準。", "需求轉弱、競爭加劇或價格壓力。"),
}


def _span(values: list[float]) -> str:
    return f"{_num(min(values), 0)}–{_num(max(values), 0)}" if values else "—"


def _valuation(fr: dict[str, Any] | None, snap: dict[str, Any]) -> str:
    val = (fr or {}).get("valuation_summary") or {}
    readiness = snap.get("readiness") or {}
    if not val:
        return f"""
<section id="valuation" aria-labelledby="h-val"><h2 id="h-val">估值</h2>{_valuation_zone(fr, snap.get('symbol'))}
{_empty("此研究版本沒有估值情境", f"估值狀態：{_status(readiness.get('valuation', 'not_evaluated'))}。")}</section>"""
    mult = val.get("exchange_multiples") or {}
    fcf_s, pe_s = val.get("fair_value_scenarios") or {}, val.get("ttm_pe_scenarios") or {}
    ttm = (fr or {}).get("ttm") or {}
    names = [("conservative", "保守"), ("base", "基準"), ("optimistic", "樂觀")]
    nc = val.get("net_cash_twd_per_ordinary_share")
    rows = "".join(
        f'<tr><th scope="row">{zh}</th>'
        f'<td class="num">{_num((fcf_s.get(k) or {}).get("fcf_multiple"), 0)}x</td>'
        f'<td class="num">{_num((fcf_s.get(k) or {}).get("indicative_twd_per_share"))}</td>'
        f'<td class="num">{_num((fcf_s.get(k) or {}).get("indicative_ttm_fcf_twd_per_share"))}</td>'
        f'<td class="num">{_num((pe_s.get(k) or {}).get("pe_multiple"), 0)}x</td>'
        f'<td class="num">{_num((pe_s.get(k) or {}).get("indicative_twd_per_share"))}</td></tr>'
        for k, zh in names if k in fcf_s or k in pe_s)
    models = []
    for label, src, key in (("P/FCF（三年中位數）", fcf_s, "indicative_twd_per_share"),
                            ("P/FCF（TTM）", fcf_s, "indicative_ttm_fcf_twd_per_share"),
                            ("P/E（TTM）", pe_s, "indicative_twd_per_share")):
        pts = [(k, float(src[k][key])) for k, _ in names if k in src and src[k].get(key) is not None]
        if pts:
            models.append((label, pts))
    sens = []
    for label, per_share in (("P/FCF（三年中位數 FCF）", val.get("fcf_twd_per_ordinary_share")),
                             ("P/FCF（TTM FCF）", val.get("ttm_fcf_twd_per_ordinary_share")),
                             ("P/E（TTM EPS）", ttm.get("basic_eps"))):
        if per_share is not None:
            sens.append(f'<tr><th scope="row">{label}</th><td class="num">{_num(per_share)}</td><td class="num">±{_num(per_share)}</td></tr>')
    capex_int = _ratio(ttm.get("capex"), ttm.get("revenue"))
    conv = _ratio(ttm.get("free_cash_flow"), ttm.get("net_income"))
    denom = val.get("denominator") or {}
    foundry = snap.get("symbol") == NARRATIVE_SYMBOL
    fcf_values = [v for label, pts in models if label.startswith("P/FCF") for _, v in pts]
    pe_values = [v for label, pts in models if label.startswith("P/E") for _, v in pts]
    fcf_range = _span(fcf_values)
    pe_range = _span(pe_values)
    base_fcf = (fcf_s.get("base") or {}).get("indicative_twd_per_share")
    base_pe = (pe_s.get("base") or {}).get("indicative_twd_per_share")
    gap = base_pe / base_fcf if isinstance(base_pe, (int, float)) and isinstance(base_fcf, (int, float)) and base_fcf > 0 else None
    method_title = (f"方法比較：為什麼 P/FCF 與 P/E 試算值差距約 {gap:.1f} 倍？" if gap and gap >= 1.2
                    else "方法比較：P/FCF 與 P/E 試算值的差異")
    method_intro = (
        "晶圓代工屬於重資本支出行業。購買先進機台與興建廠房之資本支出（Capex）在發生時為<strong>立即現金流出</strong>，"
        "但在損益表上是依照會計準則分 3–5 年透過折舊逐期攤提。在先進製程擴產高峰期（如 N2 / A16 / 跨國建廠），"
        "當期自由現金流（FCF）會顯著低於會計淨利" if foundry else
        "資本支出（Capex）在發生時為<strong>立即現金流出</strong>，但在損益表上是依照會計準則分年透過折舊逐期攤提；"
        "擴產或大額投資期間，當期自由現金流（FCF）會低於會計淨利") + f"（本期 TTM FCF 約為淨利的 {_pct(conv, 0)}）。"
    exchange_pe = mult.get("pe_ratio")
    pe_basis = (("，反映高產能利用率下的獲利能力" if foundry else "")
                + (f"，可與證交所公告本益比 {_num(exchange_pe, 1)} 倍對照" if exchange_pe is not None else ""))
    scenario_text = FOUNDRY_SCENARIOS if foundry else GENERIC_SCENARIOS
    scenario_rows = "".join(
        f'<tr><th scope="row">{zh}情境</th><td>P/FCF {_num((fcf_s.get(k) or {}).get("fcf_multiple"), 0)}x<br>'
        f'P/E {_num((pe_s.get(k) or {}).get("pe_multiple"), 0)}x</td><td>{scenario_text[k][0]}</td><td>{scenario_text[k][1]}</td></tr>'
        for k, zh in names if k in fcf_s or k in pe_s)
    return f"""
<section id="valuation" aria-labelledby="h-val">
  <h2 id="h-val">估值</h2>{_valuation_zone(fr, snap.get('symbol'))}
  <div class="callout warn" role="note"><strong>示意試算，不是目標價。</strong>
  以下情境以假設倍數乘上已對帳的財務數字，用來觀察假設的敏感度；不是合理價、目標價或買賣價格。
  交易計畫狀態：{_status(readiness.get('trade_plan', 'not_evaluated'))}；投資建議：{_status(readiness.get('recommendation', 'not_available'))}。</div>

  <h3>市場觀察倍數</h3>
  <dl class="meta">
    <div><dt>本益比（P/E）</dt><dd>{_num(mult.get('pe_ratio'))} 倍</dd></div>
    <div><dt>股價淨值比（P/B）</dt><dd>{_num(mult.get('pb_ratio'))} 倍</dd></div>
    <div><dt>殖利率</dt><dd>{_pct(mult.get('dividend_yield_pct'), 2)}</dd></div>
    <div><dt>資料日期</dt><dd>{_e(_roc_date(mult.get('date_roc')) or mult.get('date_roc'))} · {_link(mult.get('source'), 'TWSE BWIBBU_ALL')}</dd></div>
  </dl>
  <p class="note">交易所公布值，計算基礎由 TWSE 定義，與下方以 TTM EPS 為基礎的模型不必然一致。</p>

  <h3>模型輸入</h3>
  <div class="table-wrap"><table class="kv"><tbody>
    <tr><th scope="row">三年中位數年度自由現金流</th><td class="num">{_yi(val.get('normalized_annual_fcf_twd'))} 億元</td><td class="num">{_num(val.get('fcf_twd_per_ordinary_share'))} 元/股</td></tr>
    <tr><th scope="row">TTM 自由現金流</th><td class="num">{_yi(val.get('ttm_fcf_twd'))} 億元</td><td class="num">{_num(val.get('ttm_fcf_twd_per_ordinary_share'))} 元/股</td></tr>
    <tr><th scope="row">淨現金（{_e(val.get('latest_balance_sheet_end'))}）</th><td class="num">{_yi(val.get('net_cash_twd'))} 億元</td><td class="num">{_num(nc)} 元/股</td></tr>
    <tr><th scope="row">TTM 基本 EPS</th><td class="num">{NA}</td><td class="num">{_num(ttm.get('basic_eps'))} 元/股</td></tr>
    <tr><th scope="row">股數分母（{_e(denom.get('period_end'))}）</th><td class="num" colspan="2">{_num(denom.get('value'), 0)} 股</td></tr>
  </tbody></table></div>

  <h3>情境試算</h3>
  <ul class="formula">
    <li>P/FCF 法：每股 FCF × 假設倍數 + 每股淨現金 {_num(nc)} 元</li>
    <li>P/E 法：TTM 基本 EPS × 假設倍數（不加計淨現金）</li>
  </ul>
  <div class="table-wrap"><table><thead><tr><th scope="col">情境</th><th scope="col" class="num">P/FCF 倍數</th>
  <th scope="col" class="num">三年中位數 FCF 法<span class="unit">元/股</span></th><th scope="col" class="num">TTM FCF 法<span class="unit">元/股</span></th>
  <th scope="col" class="num">P/E 倍數</th><th scope="col" class="num">TTM P/E 法<span class="unit">元/股</span></th></tr></thead><tbody>{rows}</tbody></table></div>
  <figure class="chart-box">{_valuation_chart(models)}<figcaption>點位由左至右為保守、基準、樂觀。圖中未標示市價，因研究狀態未保存經驗證的收盤價。</figcaption></figure>

  <h3>敏感度：哪個輸入影響最大</h3>
  <div class="table-wrap"><table><thead><tr><th scope="col">方法</th><th scope="col" class="num">每股基礎值<span class="unit">元</span></th>
  <th scope="col" class="num">倍數每變動 1x 的影響<span class="unit">元/股</span></th></tr></thead><tbody>{''.join(sens)}</tbody></table></div>
  <p>倍數假設是最大變因：同一方法內，倍數每差 1x，試算值就差一個「每股基礎值」。兩種方法的差距主要來自 FCF 只約為淨利的
  {_pct(conv, 0)}（TTM，推導值），反映資本支出約占營收 {_pct(capex_int)}（TTM，推導值）。資本支出計畫改變時，P/FCF 法結果會明顯移動。</p>

  <h3>{_e(method_title)}</h3>
  <div class="callout">
    <p><strong>產業資本特性與折舊時間差：</strong></p>
    <p>{method_intro}</p>
    <ul>
      <li><strong>P/FCF 法（EV-bridged）</strong>：假設市場投資人僅依照當期或三年中位數之「扣除資本支出後的真實現金」給予倍數，再加上每股淨現金 {_num(nc)} 元。此方法在重資本支出擴張期會壓抑每股試算值（{fcf_range} 元）。</li>
      <li><strong>TTM P/E 法</strong>：以當期帳面 EPS（{_num(ttm.get('basic_eps'))} 元）為基礎{pe_basis}（試算值 {pe_range} 元），但未直接扣除未來維持競爭優勢所需之再投資支出。</li>
    </ul>
  </div>

  <h3>情境倍數適用條件分析（敏感度壓力測試假設，非營運預測）</h3>
  <p class="note">以下情境條件旨在說明不同倍數假設背後所隱含之營運與產業環境，僅用於壓力測試與敏感度觀察；非本系統之預測，亦未經獨立財務預測驗證。</p>
  <div class="table-wrap"><table><thead><tr><th scope="col">情境</th><th scope="col">倍數假設</th><th scope="col">隱含之產業與營運情境（非預測）</th><th scope="col">失效或風險條件</th></tr></thead><tbody>
    {scenario_rows}
  </tbody></table></div>
</section>"""


def _technical(snap: dict[str, Any], extra: dict[str, Any], stock: dict[str, Any] | None = None) -> str:
    tech = snap.get("technical") or {}
    run = snap.get("run") or {}
    stock = stock or {}
    rc = tech.get("recent_closes") or []
    obs = sorted(extra.get("observations") or [], key=lambda o: (not o.get("matched"), str(o.get("strategy_id"))))
    if obs:
        matched = [o for o in obs if o.get("matched")]
        rows = "".join(
            f'<tr><th scope="row">{_e(o.get("strategy_id"))}</th><td>{"✓ 本次出現" if o.get("matched") else "— 未出現"}</td>'
            f'<td>{"已啟用（通過驗證）" if o.get("active") else "研究中（未驗證）"}</td></tr>' for o in obs)
        observations = (f'<p>{len(matched)} 個型態在 {_e(extra.get("last_session"))} 出現，共檢查 {len(obs)} 個。</p>'
                        f'<div class="table-wrap"><table><thead><tr><th scope="col">型態</th><th scope="col">本次</th><th scope="col">策略狀態</th></tr></thead><tbody>{rows}</tbody></table></div>'
                        '<p class="note">型態出現只代表歷史價格符合規則，不代表後續走勢；研究中策略未通過前瞻驗證。</p>')
    else:
        observations = _empty("研究狀態未保存型態觀測結果",
                              f'每次執行的型態掃描結果保存在該次 GitHub Actions Artifact 的 report.json。{_link(run.get("run_url"), "前往此版本的執行紀錄")}')
    ctx = extra.get("price_context") or {}
    ctx_html = ""
    if ctx.get("status") == "observation_only":
        lv, atr = ctx.get("levels") or {}, ctx.get("atr") or {}
        ctx_html = f"""
  <h3>價格區間觀察</h3>
  <div class="table-wrap"><table class="kv"><tbody>
  <tr><th scope="row">前 20 交易日低／高</th><td class="num">{_num(lv.get('support_20d'))} / {_num(lv.get('resistance_20d'))}</td></tr>
  <tr><th scope="row">前 60 交易日低／高</th><td class="num">{_num(lv.get('support_60d'))} / {_num(lv.get('resistance_60d'))}</td></tr>
  <tr><th scope="row">ATR(14)</th><td class="num">{_num(atr.get('absolute'))}（收盤價的 {_pct(atr.get('percentage_of_close'), 2)}）</td></tr>
  </tbody></table></div>
  <p class="note">歷史區間觀察，不是買進價、停損價或目標價。</p>"""

    chart_html = ""
    if len(rc) >= 2:
        chart_html = f"""
  <h3>近 30 個交易日收盤價走勢</h3>
  <figure class="chart-box">
    {_price_chart(rc, stock.get('currency') or 'TWD', ctx.get('levels') or {})}
    <figcaption>TWSE 官方未還原收盤價走勢（近 {len(rc)} 個交易日）。除權息日可能包含價格缺口；虛線標示前 20 交易日區間高低點。</figcaption>
  </figure>"""

    callout_html = (
        f"""<div class="callout" role="note">
    <strong>行情與價格走勢持久化契約說明：</strong>
    <p>狀態存儲分支採<strong>輕量化契約（方案 A）</strong>：快照內嵌近期 30 個交易日之未還原收盤價序列（約 750 Bytes），兼顧離線視覺化與 Git 存儲預算（<code>MAX_SNAPSHOT_BYTES = 20,000</code>），嚴格遵循不假造數據原則。長週期 OHLCV 與均線分析可依<strong>方案 B（Sidecar 產物契約）</strong>進行漸進擴充。</p>
  </div>"""
        if len(rc) >= 2 else
        f"""<div class="callout" role="note">
    <strong>行情與價格走勢持久化契約限制說明：</strong>
    <p>依本系統之資料契約（<code>comparison_limits = ["prices_metadata_only"]</code>），此歷史版本之快照僅保存行情驗證 metadata，未保存近期收盤價序列。本系統遵循嚴謹研究原則，絕不假造虛擬價格走勢圖。較新之研究版本已採輕量化契約（方案 A）內嵌近期收盤價走勢。</p>
  </div>"""
    )

    return f"""
<section id="technical" aria-labelledby="h-tech">
  <h2 id="h-tech">技術分析</h2>
  {callout_html}
  {chart_html}
  <dl class="meta">
    <div><dt>資料狀態</dt><dd>{_status(tech.get('status'))}</dd></div>
    <div><dt>最新完整交易日</dt><dd>{_e(tech.get('session'))}</dd></div>
    <div><dt>資料新鮮度</dt><dd>{ {'current': '最新', 'stale': '過時（沿用舊資料）'}.get(tech.get('freshness'), _e(tech.get('freshness'))) }</dd></div>
    <div><dt>價格基準</dt><dd>{_e(PRICE_BASIS.get(tech.get('price_basis'), tech.get('price_basis')))}</dd></div>
    <div><dt>資料來源</dt><dd>{_e(PRICE_SOURCE.get(tech.get('source'), tech.get('source')))}</dd></div>
  </dl>
  <h3>歷史型態清單</h3>
  {observations}
  {ctx_html}
</section>"""


def _events(fr: dict[str, Any] | None, snap: dict[str, Any]) -> str:
    cutoff_date = _tpe(snap.get("evaluation_cutoff_utc"))[:10]
    cal = ((fr or {}).get("calendar_schedule") or {}).get("events") or []
    groups: dict[str, list[str]] = {"upcoming": [], "unknown": [], "past": [], "rule": []}
    for ev in cal:
        date, status = ev.get("scheduled_date"), ev.get("confirmation_status")
        if ev.get("event_type") == "statutory_filing_deadline":
            key, label = "rule", "法規期限（非公司公告日）"
        elif status == "cancelled":
            key, label = "past", "已取消"
        elif not date or status == "unknown":
            key, label = "unknown", "日期未定"
        elif status == "confirmed":
            key, label = ("upcoming", "已確認・即將到來") if date >= cutoff_date else ("past", "已確認・已發生")
        else:
            key, label = ("upcoming" if date >= cutoff_date else "past"), f"預估（{_e(status)}）"
        sup = ev.get("superseded_dates") or []
        sup_html = f'<span class="hint">原訂 {_e("、".join(sup))}，已更正</span>' if sup else ""
        groups[key].append(
            f'<tr><th scope="row">{_e(date) if date else NA}</th><td>{_e(ev.get("title"))} {sup_html}</td>'
            f'<td>{label}</td><td>{_e(ev.get("period_label"))}</td><td>{_link(ev.get("source"))}</td></tr>')
    cal_rows = "".join(groups["upcoming"] + groups["unknown"] + groups["past"] + groups["rule"])
    disc = (fr or {}).get("disclosure_and_news") or {}
    discl = "".join(
        f'<li><time>{_e(d.get("event_date") or d.get("reported_at"))}</time> {_e(d.get("title"))} {_link(d.get("source"))}</li>'
        for d in disc.get("official_disclosures") or [])
    news = "".join(
        f'<li><time>{_e((n.get("published_at") or "")[:10] or None)}</time> {_link(n.get("url"), n.get("title") or "新聞")} '
        f'<span class="hint">{_e(n.get("source"))}</span></li>' for n in disc.get("news_references") or [])
    statuses = "、".join(f"{_e(k)}：{_e(SOURCE_STATUS.get(v, v))}" for k, v in (disc.get("source_statuses") or {}).items())
    ev = snap.get("events") or {}
    return f"""
<section id="events" aria-labelledby="h-events">
  <h2 id="h-events">風險與事件</h2>
  <p class="callout">事件觀測狀態：{_status((snap.get('readiness') or {}).get('events'))}。觀測範圍：{_e({'recent_daily_snapshot_only_not_a_full_history': '僅最近一次每日快照，非完整歷史'}.get(ev.get('coverage'), ev.get('coverage')))}（{_e(ev.get('snapshot_date'))}）。
  未觀測到事件不代表沒有風險。主要不確定性列於<a href="#overview">研究總覽</a>。</p>
  <h3>財報、董事會與股東會行事曆</h3>
  {f'<div class="table-wrap"><table><thead><tr><th scope="col">日期</th><th scope="col">事件</th><th scope="col">日期性質</th><th scope="col">期別</th><th scope="col">來源</th></tr></thead><tbody>{cal_rows}</tbody></table></div>' if cal_rows else _empty("此版本沒有行事曆資料", "行事曆需要財務研究資料（TW09）。")}
  <p class="note">「即將到來／已發生」以本版本評估日 {_e(cutoff_date)}（台北）判斷。</p>
  <div class="two-col">
    <div><h3>官方公告與董事會決議</h3>{f'<ul class="plain dated">{discl}</ul>' if discl else _empty("無官方公告項目", "觀測範圍內沒有符合條件的公告。")}</div>
    <div><h3>補充新聞</h3>{f'<ul class="plain dated">{news}</ul>' if news else _empty("無列示新聞", f"去重後未保留新聞項目（移除重複轉載 {_e(disc.get('deduplicated_repost_count', 0))} 則）。新聞不作為財報依據。")}</div>
  </div>
  {f'<p class="note">來源狀態：{statuses}</p>' if statuses else ''}
</section>"""


def _methodology(snap: dict[str, Any], comp: dict[str, Any], stock: dict[str, Any], branch: str) -> str:
    fr = snap.get("financial_research") or {}
    run = snap.get("run") or {}
    tech = snap.get("technical") or {}
    attr = snap.get("attribution") or {}
    readiness = snap.get("readiness") or {}
    checkpoint = stock.get("checkpoint")
    subject = stock.get("subject") or {}
    history = []
    for s in stock["snapshots"]:
        c = stock["comparisons"].get(s["id"]) or {}
        current = ' aria-current="true"' if s["id"] == snap["id"] else ""
        action = ("目前檢視" if current else
                  '<button type="button" class="link-btn" data-snapshot="' + _e(s["id"]) + '">檢視此版本</button>'
                  if s["id"] in stock.get("embedded_ids", {s["id"]}) else
                  f'<span class="hint">未內嵌（頁面只保留最近 {MAX_EMBEDDED_VERSIONS} 版）</span>')
        run_s = s.get("run") or {}
        history.append(
            f'<tr{current}><th scope="row">{_tpe(s.get("observed_at_utc"))}</th>'
            f'<td>{_status((s.get("execution") or {}).get("status"))}</td>'
            f'<td>{_status((s.get("readiness") or {}).get("financial"))}</td>'
            f'<td>{_e(COMPARISON_LABELS.get(c.get("status"), "有研究變化"))}</td>'
            f'<td>{_link(run_s.get("run_url"), "#" + str(run_s.get("run_id")))}</td>'
            f'<td>{action}</td></tr>')
    changes = "".join(
        f'<tr><td>{_e(COMPARISON_LABELS.get(c.get("kind"), c.get("kind")))}</td>'
        f'<td>{_e(COMPONENT_LABELS.get(c.get("component"), c.get("component")))}</td><td><code>{_e(c.get("reason"))}</code></td>'
        f'<td>{_e(c.get("period"))}</td></tr>' for c in comp.get("changes") or [])
    sources = "".join(f"<li>{_link(u, u)}</li>" for u in snap.get("source_links") or [])
    datasets = "".join(f'<li>{_e(d.get("name"))}：{_link(d.get("endpoint"), d.get("endpoint"))}</li>' for d in fr.get("ogdl_datasets") or [])
    attr_ds = "".join(f'<li>{_link(d.get("catalog"), d.get("name"))}（上架 {_e(d.get("released_year"))}）</li>' for d in attr.get("datasets") or [])
    status_table_rows = []
    for key, name, notes in MODULES:
        code = readiness.get(key, "not_evaluated")
        status_table_rows.append(
            f'<tr><th scope="row">{name}</th><td>{_status(code)}</td><td><code>{_e(code)}</code></td><td>{_e(notes.get(code, ""))}</td></tr>')
    raw_status = "".join(status_table_rows)
    cp_html = "<p>此標的尚未建立重新研究檢查點。</p>"
    if checkpoint:
        cp_html = (f'<dl class="meta"><div><dt>已消費財報版本</dt><dd><code>{_e(checkpoint.get("consumed_financial_version"))}</code></dd></div>'
                   f'<div><dt>已消費官方事件數</dt><dd>{len(checkpoint.get("consumed_event_ids") or [])}</dd></div>'
                   f'<div><dt>待重新研究</dt><dd>{_e(checkpoint.get("pending_rerun")) if checkpoint.get("pending_rerun") else "無"}</dd></div>'
                   f'<div><dt>最後完成版本</dt><dd><code>{_e((checkpoint.get("last_completed_snapshot_id") or "")[:12])}</code></dd></div></dl>')
    limits = {"prices_metadata_only": "行情只保存 metadata", "events_metadata_only": "事件只保存 metadata",
              "artifact_inputs_not_retained": "完整輸入只在有期限的 Artifact 中", "model_identity_not_retained": "未保存模型識別"}
    limit_items = "".join(f"<li>{_e(limits.get(x, x))}（<code>{_e(x)}</code>）</li>" for x in snap.get("comparison_limits") or [])
    issue = subject.get("issue_number")
    repo = run.get("repository") or "iceboxi/market-research"
    return f"""
<section id="methodology" aria-labelledby="h-method">
  <h2 id="h-method">資料與方法</h2>
  <p class="lede">來源、對帳、識別碼與歷史版本。這些資訊用於稽核，不代表投資論點的品質。</p>
  <details open id="m-history"><summary>研究版本（歷史快照，共 {len(stock['snapshots'])} 個）</summary>
    <div class="table-wrap"><table><thead><tr><th scope="col">產生時間（台北）</th><th scope="col">執行</th><th scope="col">財務研究</th>
    <th scope="col">與前版比較</th><th scope="col">執行紀錄</th><th scope="col">動作</th></tr></thead><tbody>{''.join(history)}</tbody></table></div>
  </details>
  <details id="m-compare"><summary>與前一版本的比較明細</summary>
    <p>結果：{_e(COMPARISON_LABELS.get(comp.get('status'), '有研究變化'))}；前一版本 <code>{_e((comp.get('previous_snapshot_id') or '無')[:12])}</code>。</p>
    {f'<div class="table-wrap"><table><thead><tr><th scope="col">類型</th><th scope="col">內容</th><th scope="col">原因代碼</th><th scope="col">期別</th></tr></thead><tbody>{changes}</tbody></table></div>' if changes else '<p>沒有逐項變化。</p>'}
    <p class="note">比較限制：{_e('、'.join(comp.get('limitations') or []))}</p>
  </details>
  <details><summary>資料來源與授權</summary>
    <h4>本版本引用的來源</h4><ul class="plain">{sources}</ul>
    {f'<h4>財務資料集（TWSE OpenAPI）</h4><ul class="plain">{datasets}</ul>' if datasets else ''}
    <h4>開放資料授權</h4><p>{_e(attr.get('provider'))}；依 {_link(attr.get('license'), '政府資料開放授權條款第 ' + str(attr.get('license_version')) + ' 版')} 使用。</p>
    <ul class="plain">{attr_ds}</ul>
  </details>
  <details><summary>計算方法與對帳</summary>
    <ul class="plain">
      <li>財務資料：TWSE OpenAPI 與 FinMind 雙軌取得，以 TWSE 為準對帳（對帳完成：{'是' if fr.get('reconciled_twse_openapi') else '否'}；基準期 {_e(fr.get('reconciled_period_end'))}）。</li>
      <li>單季值：Q1 直接採用；Q2–Q4 以累計值相減，並以 TWSE 單季淨利或 EPS 恆等式核對。累計值與單季值分開呈現。</li>
      <li>TTM：最近四個單季加總；EPS 為四季加總，前提是各季股數差異 ≤ 0.5%。</li>
      <li>自由現金流 = 營業現金流 − 資本支出。淨現金 = 現金及約當現金 − 有息負債（公司債＋長期借款）。</li>
      <li>估值：{_e((fr.get('valuation_summary') or {}).get('why'))}</li>
      <li>本頁推導值（同季年增、資本支出/營收、FCF/淨利）由同口徑數字直接相除，缺任一輸入即不顯示。</li>
      <li>缺值顯示為「—」，不補零。</li>
    </ul>
  </details>
  <details id="m-status"><summary>研究模組就緒度與原始狀態代碼（完整檢驗清單）</summary>
    <div class="table-wrap"><table><thead><tr><th scope="col">模組</th><th scope="col">狀態</th><th scope="col">原始代碼</th><th scope="col">定義與約束</th></tr></thead><tbody>{raw_status}</tbody></table></div>
  </details>
  <details><summary>執行與完整性識別碼</summary>
    <dl class="meta ids">
      <div><dt>研究版本 ID</dt><dd><code>{_e(snap.get('id'))}</code></dd></div>
      <div><dt>評估截止（UTC）</dt><dd>{_e(snap.get('evaluation_cutoff_utc'))}</dd></div>
      <div><dt>開始／觀測（UTC）</dt><dd>{_e(snap.get('started_at_utc'))} / {_e(snap.get('observed_at_utc'))}</dd></div>
      <div><dt>執行</dt><dd>{_link(run.get('run_url'), f"Run #{run.get('run_id')}（attempt {run.get('run_attempt')}）")}</dd></div>
      <div><dt>程式版本</dt><dd><code>{_e(run.get('code_sha'))}</code></dd></div>
      <div><dt>模型設定識別</dt><dd><code>{_e(snap.get('model_identity'))}</code></dd></div>
      <div><dt>行情輸入雜湊</dt><dd><code>{_e(tech.get('input_sha256'))}</code></dd></div>
      <div><dt>可得時間屬性</dt><dd><code>{_e(snap.get('availability'))}</code></dd></div>
      <div><dt>狀態分支</dt><dd>{"未寫入；每日排程當次報告，只保留最新一版" if stock.get("latest_only") else f"<code>{_e(branch)}</code>"}</dd></div>
      {f'<div><dt>固定研究報告</dt><dd>{_link(f"https://github.com/{repo}/issues/{issue}", f"Issue #{issue}")}</dd></div>' if issue else ''}
    </dl>
  </details>
  <details><summary>重新研究檢查點</summary>{cp_html}</details>
  <details><summary>保存限制與合規聲明</summary>
    <ul class="plain">{limit_items}</ul>
    <p>所有數據來自公開來源，缺值不補零。估值情境為示意性質，技術觀察僅供研究，皆不構成合理價、進出場區間、停損價、目標價或投資建議。
    資料完整、對帳完成或模組可用，不代表投資論點正確。</p>
  </details>
</section>"""


def _beginner_note(stock: dict[str, Any]) -> str:
    """Older versions skip the 新手 charts (~20 kB each); the latest version carries them."""
    return ('<section id="beginner" aria-labelledby="h-beginner"><h2 id="h-beginner">新手看這裡</h2>'
            + _empty("新手章節只顯示最新研究版本",
                     f'<button type="button" class="link-btn" data-snapshot="{_e(stock["latest_snapshot_id"])}">回到最新版本</button>')
            + "</section>")


def _render_view(snap: dict[str, Any], comp: dict[str, Any], stock: dict[str, Any], branch: str, extra: dict[str, Any]) -> str:
    from market_research.beginner_view import render_beginner  # imports this module's helpers
    fr = snap.get("financial_research") if (snap.get("financial_research") or {}).get("status") == "available" else None
    beginner = render_beginner(snap, stock) if snap["id"] == stock.get("latest_snapshot_id") else _beginner_note(stock)
    return (f'<div class="view" data-snapshot-id="{_e(snap["id"])}">'
            + beginner + _overview(snap, comp, stock, extra) + _fundamentals(fr, snap) + _valuation(fr, snap)
            + _technical(snap, extra, stock) + _events(fr, snap) + _methodology(snap, comp, stock, branch) + "</div>")


# ---------------------------------------------------------------- page

NAV = [("beginner", "新手"), ("overview", "總覽"), ("fundamentals", "基本面"), ("valuation", "估值"),
       ("technical", "技術分析"), ("events", "風險與事件"), ("methodology", "資料與方法")]

CSS = """
:root{--bg:#f5f6f8;--surface:#fff;--text:#1a1d21;--muted:#5d6672;--line:#e1e4e8;--accent:#1f5fbf;
--ok:#1a7f37;--warn:#9a6700;--bad:#b42318;--neutral:#5d6672;--bar:#7fa3d6;--lineA:#3d4650;--lineB:#c0561b;--warn-bg:#fff8e6;
--up:#c62828;--down:#1a7f37}
@media (prefers-color-scheme:dark){:root{--bg:#0f1216;--surface:#161a20;--text:#e6e8eb;--muted:#9aa3ad;--line:#2a3039;
--accent:#79a8ff;--ok:#4cc38a;--warn:#e3b341;--bad:#f47067;--neutral:#9aa3ad;--bar:#3f6aa8;--lineA:#c9d1d9;--lineB:#f0883e;--warn-bg:#2b2410;
--up:#ff6b6b;--down:#4cc38a}}
*{box-sizing:border-box}html{scroll-padding-top:120px}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang TC","Noto Sans TC",sans-serif}
a{color:var(--accent)}code{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;word-break:break-all}
.skip{position:absolute;left:-999px}.skip:focus{left:8px;top:8px;z-index:50;background:var(--surface);padding:6px 10px}
.topbar{position:sticky;top:0;z-index:20;background:var(--surface);border-bottom:1px solid var(--line)}
.topbar-inner,.wrap{max-width:1180px;margin:0 auto;padding:0 20px}
.topbar-inner{display:flex;align-items:center;gap:16px;min-height:56px;flex-wrap:wrap}
.brand{font-weight:700;font-size:15px;white-space:nowrap}.brand span{font-weight:400;color:var(--muted);margin-left:6px}
.picker{position:relative;flex:1 1 320px;max-width:460px}
.picker label{position:absolute;left:-999px}
.picker input{width:100%;font:inherit;padding:7px 40px 7px 12px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--text)}
.picker input:focus{outline:2px solid var(--accent);outline-offset:1px}
.picker .toggle{position:absolute;right:4px;top:50%;transform:translateY(-50%);border:0;background:none;color:var(--muted);font-size:16px;line-height:1;padding:6px 8px;cursor:pointer;border-radius:4px}
.picker .toggle:hover,.picker .toggle:focus-visible{color:var(--text);background:var(--bg)}
.picker ul{position:absolute;left:0;right:0;top:calc(100% + 4px);margin:0;padding:4px 0;list-style:none;background:var(--surface);
border:1px solid var(--line);border-radius:6px;box-shadow:0 6px 20px rgba(0,0,0,.12);max-height:320px;overflow:auto}
.picker li{padding:8px 12px;cursor:pointer;display:flex;gap:10px;align-items:baseline}
.picker li[aria-selected=true]{background:var(--bg)}.picker li .t{font-weight:600;min-width:72px}
.picker li .m{margin-left:auto;color:var(--muted);font-size:12px}.picker li.msg{cursor:default;color:var(--muted);display:block}
.secnav{display:flex;gap:4px;overflow-x:auto;max-width:1180px;margin:0 auto;padding:0 12px}
.secnav a{padding:8px 10px;color:var(--muted);text-decoration:none;white-space:nowrap;border-bottom:2px solid transparent;font-size:14px}
.secnav a[aria-current=true]{color:var(--text);border-bottom-color:var(--accent)}
.identity{padding:22px 0 12px;display:flex;flex-wrap:wrap;gap:12px 28px;align-items:flex-end;justify-content:space-between}
.identity h1{margin:0;font-size:24px;line-height:1.3}.identity .ticker{font-weight:600;color:var(--muted);margin-left:8px;font-size:18px}
.identity .sub{color:var(--muted);font-size:14px;margin-top:2px}
.version{display:flex;flex-direction:column;gap:4px;padding:8px 12px;border:1px dashed var(--line);border-radius:6px;background:var(--surface)}
.version label{font-size:12px;color:var(--muted)}.version select{font:inherit;font-size:14px;padding:4px 6px;max-width:420px;background:var(--bg);color:var(--text);border:1px solid var(--line);border-radius:4px}
.watchlist{padding:12px 0 8px}.watchlist h3{margin-top:14px}
.disclaimer{font-size:13px;color:var(--muted);border-left:3px solid var(--warn);padding:6px 12px;margin:4px 0 8px;background:var(--surface)}
.banner{margin:10px 0;padding:10px 14px;border:1px solid var(--bad);border-radius:6px;background:var(--surface)}
main section{padding:28px 0 8px;border-top:1px solid var(--line)}main section:first-child{border-top:0}
h2{font-size:20px;margin:0 0 14px}h3{font-size:16px;margin:26px 0 10px}h4{font-size:14px;margin:0 0 4px}
.lede,.note,.hint,.basis{color:var(--muted)}.lede{margin-top:-6px}.note{font-size:13px}.hint{font-size:12px;margin-left:4px}
.meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px 24px;margin:0 0 8px;padding:14px 16px;background:var(--surface);border:1px solid var(--line);border-radius:6px}
.meta dt{font-size:12px;color:var(--muted)}.meta dd{margin:2px 0 0;font-weight:600}.meta.ids{grid-template-columns:1fr}.meta.ids dd{font-weight:400}
.findings{list-style:none;padding:0;margin:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:2px 28px}
.findings li{padding:12px 0;border-bottom:1px solid var(--line)}.findings p{margin:0}.basis{font-size:12px;margin-top:4px!important}
.callout{padding:12px 16px;border:1px solid var(--line);border-radius:6px;background:var(--surface);margin:16px 0}
.callout.warn{border-color:var(--warn);background:var(--warn-bg)}.callout ul{margin:6px 0 0;padding-left:18px}
.plain{padding-left:18px;margin:6px 0}.plain li{margin:4px 0}.dated time{color:var(--muted);font-variant-numeric:tabular-nums;margin-right:6px}
.formula{margin:0 0 10px;padding-left:18px;color:var(--muted)}
.table-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:6px;background:var(--surface);margin:8px 0}
table{border-collapse:collapse;width:100%;font-size:14px}caption{text-align:left;padding:8px 12px;font-weight:600}
th,td{padding:8px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}tbody tr:last-child>*{border-bottom:0}
thead th{font-size:12px;font-weight:600;color:var(--muted);white-space:nowrap;background:var(--bg)}
tbody th{font-weight:500}.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.unit,.sub{display:block;font-size:11px;font-weight:400;color:var(--muted)}.basis-cell{font-size:12px;color:var(--muted);min-width:180px}
table.metrics tbody th{white-space:nowrap}tr[aria-current=true]{background:var(--bg)}
.na{color:var(--muted)}.chg.up{color:var(--up)}.chg.down{color:var(--down)}
.st{white-space:nowrap}.st-ok{color:var(--ok)}.st-warn{color:var(--warn)}.st-bad{color:var(--bad)}.st-neutral{color:var(--neutral)}
.readiness-strip{display:flex;flex-wrap:wrap;gap:8px 14px;padding:10px 14px;background:var(--surface);border:1px solid var(--line);border-radius:6px;margin:10px 0 16px;align-items:center}
.readiness-strip .title{font-size:12px;font-weight:600;color:var(--muted)}
.readiness-strip .item{display:inline-flex;align-items:center;gap:6px;font-size:13px}
.readiness-strip .lbl{color:var(--text)}
.two-col{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:0 28px}
.chart-box{margin:8px 0;padding:12px;background:var(--surface);border:1px solid var(--line);border-radius:6px}
.chart-box figcaption{font-size:12px;color:var(--muted);margin-top:6px}
.chart{width:100%;height:auto;display:block}.chart .grid{stroke:var(--line)}.chart .axis,.chart .legend text{fill:var(--muted);font-size:11px}
.chart .bar{fill:var(--bar)}.chart .line-a{fill:none;stroke:var(--lineA);stroke-width:2;stroke-dasharray:5 3}.chart .line-b{fill:none;stroke:var(--lineB);stroke-width:2}
.chart .line-a-pt{fill:var(--lineA)}.chart .line-b-pt{fill:var(--lineB)}.chart .range{stroke:var(--line);stroke-width:6;stroke-linecap:round}
.chart .pt-conservative{fill:var(--surface);stroke:var(--lineA);stroke-width:2}.chart .pt-base{fill:var(--lineA)}.chart .pt-optimistic{fill:var(--lineB)}
.price-chart{height:auto;display:block}.price-line{fill:none;stroke:var(--accent);stroke-width:2.5}
.price-area{fill:var(--accent);fill-opacity:0.08}.price-dot{fill:var(--accent);opacity:0.7}
.price-dot-latest{fill:var(--surface);stroke:var(--accent);stroke-width:3}
.level-res{stroke:var(--bad);stroke-dasharray:4 3;stroke-width:1.5}.level-sup{stroke:var(--ok);stroke-dasharray:4 3;stroke-width:1.5}
.axis-res{fill:var(--bad);font-size:10px}.axis-sup{fill:var(--ok);font-size:10px}.axis-latest{fill:var(--accent);font-weight:700;font-size:12px}
.empty{padding:14px 16px;border:1px dashed var(--line);border-radius:6px;color:var(--muted);background:var(--surface);margin:8px 0}
.empty strong{color:var(--text)}.empty p{margin:4px 0 0}
details{border:1px solid var(--line);border-radius:6px;background:var(--surface);margin:8px 0;padding:0 16px}
details[open]{padding-bottom:12px}summary{cursor:pointer;padding:12px 0;font-weight:600}
.link-btn{font:inherit;font-size:13px;color:var(--accent);background:none;border:0;padding:0;cursor:pointer;text-decoration:underline}
footer{color:var(--muted);font-size:12px;padding:24px 0 40px;border-top:1px solid var(--line);margin-top:24px}
@media (max-width:640px){body{font-size:14px}.identity h1{font-size:20px}.brand span{display:none}.picker{flex-basis:100%;max-width:none;order:3;margin-bottom:8px}
html{scroll-padding-top:150px}.findings{grid-template-columns:1fr}.two-col{grid-template-columns:1fr}.version{width:100%}.version select{max-width:none}}
"""

JS = r"""
(function(){
  var app=document.getElementById('app');
  var DATA;
  try{DATA=JSON.parse(document.getElementById('site-data').textContent);}
  catch(e){var b=document.getElementById('error-banner');b.hidden=false;
    b.textContent='互動資料載入失敗：股票搜尋與版本切換無法使用，以下為頁面產生時的最新版本靜態內容。';return;}
  var current=DATA.default_symbol, currentSnap=null;
  var input=document.getElementById('stock-input'), list=document.getElementById('stock-list'),
      toggle=document.getElementById('stock-toggle'),
      live=document.getElementById('stock-live'), sel=document.getElementById('version-select');
  var active=-1, shown=[];
  function stock(sym){for(var i=0;i<DATA.stocks.length;i++){if(DATA.stocks[i].symbol===sym)return DATA.stocks[i];}return null;}
  function label(s){return s.symbol+'  '+(s.name||'')+'  ·  '+s.exchange_code;}
  function setUrl(){var p=new URLSearchParams(location.search);p.set('symbol',current);
    var s=stock(current);if(currentSnap&&s&&currentSnap!==s.latest_snapshot_id)p.set('snapshot',currentSnap.slice(0,12));else p.delete('snapshot');
    history.replaceState(null,'','?'+p.toString()+location.hash);}
  function render(id){var s=stock(current);if(!s)return;var views=DATA.views[current]||{};
    if(!views[id])id=s.latest_snapshot_id;
    app.innerHTML=views[id];currentSnap=id;sel.value=id;bindView();spy();}
  function fillVersions(s){sel.innerHTML='';s.snapshots.forEach(function(v){var o=document.createElement('option');o.value=v.id;o.textContent=v.label;sel.appendChild(o);});}
  function selectStock(sym,snap){var s=stock(sym);if(!s){unsupported(sym);return;}
    current=sym;sel.disabled=false;input.value=label(s);document.getElementById('id-name').textContent=s.name||s.symbol;
    document.getElementById('id-ticker').textContent=s.symbol;
    document.getElementById('id-sub').textContent=s.exchange+'（'+s.exchange_code+'）'+(s.currency?' · '+s.currency_label+'（'+s.currency+'）':'');
    document.title=s.symbol+' '+(s.name||'')+' — 個股研究';fillVersions(s);render(snap||s.latest_snapshot_id);setUrl();}
  function unsupported(q){var names=DATA.stocks.map(function(s){return s.symbol;}).join('、');
    current=q;currentSnap=null;input.value=q;
    document.getElementById('id-name').textContent=q;
    document.getElementById('id-ticker').textContent='（未納入研究管線）';
    document.getElementById('id-sub').textContent='尚無可解析的研究快照 · 需等待研究管線納入支援';
    sel.disabled=true;sel.innerHTML='<option value="">無可用研究版本</option>';
    var p=new URLSearchParams(location.search);p.set('symbol',q);p.delete('snapshot');
    history.replaceState(null,'','?'+p.toString()+location.hash);
    document.title=q+'（未納入研究管線）— 個股研究';
    app.innerHTML='<section><h2>沒有「'+esc(q)+'」的研究資料</h2><div class="empty"><strong>此標的尚未納入自動化研究管線</strong>' +
    '<p>目前有研究資料的標的：<strong>'+esc(names)+'</strong>。觀察名單由 config/markets.yaml 決定，加入後的下一次每日排程會產生研究頁。</p>' +
    '<p><button type="button" class="link-btn" id="back-default">返回 '+esc(DATA.default_symbol)+'</button></p></div></section>';
    document.getElementById('back-default').onclick=function(){sel.disabled=false;selectStock(DATA.default_symbol);};}
  function esc(t){return String(t).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function match(q){q=q.trim().toLowerCase();if(!q)return DATA.stocks.slice();
    return DATA.stocks.filter(function(s){return [s.symbol,s.symbol.split('.')[0],s.name||'',s.exchange,s.exchange_code,s.market].join(' ').toLowerCase().indexOf(q)>=0;});}
  function open(q){shown=match(q);active=shown.length?0:-1;list.innerHTML='';
    if(!shown.length){var li=document.createElement('li');li.className='msg';li.setAttribute('role','option');li.setAttribute('aria-disabled','true');
      li.textContent='找不到「'+q.trim()+'」。目前有研究資料的是 '+DATA.stocks.map(function(s){return s.symbol+' '+(s.name||'');}).join('、')+'。';list.appendChild(li);
      live.textContent='沒有符合的股票';}
    else{shown.forEach(function(s,i){var li=document.createElement('li');li.id='opt-'+i;li.setAttribute('role','option');
      var n=s.latest_only?'最新一版':s.snapshots.length+' 個版本';
      li.innerHTML='<span class="t">'+esc(s.symbol)+'</span><span>'+esc(s.name||'')+'</span><span class="m">'+esc(n)+(s.symbol===current?' · 目前':'')+'</span>';
      li.onmousedown=function(e){e.preventDefault();choose(i);};list.appendChild(li);});live.textContent=shown.length+' 個符合的股票';}
    list.hidden=false;input.setAttribute('aria-expanded','true');toggle.setAttribute('aria-expanded','true');mark();}
  function close(restore){list.hidden=true;input.setAttribute('aria-expanded','false');toggle.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');
    if(restore){var s=stock(current);if(s)input.value=label(s);}}
  function mark(){Array.prototype.forEach.call(list.children,function(li,i){li.setAttribute('aria-selected',i===active?'true':'false');});
    if(active>=0){input.setAttribute('aria-activedescendant','opt-'+active);var el=document.getElementById('opt-'+active);if(el)el.scrollIntoView({block:'nearest'});}}
  function choose(i){var s=shown[i];if(!s)return;close(false);if(s.symbol!==current)selectStock(s.symbol);else input.value=label(s);input.blur();}
  input.addEventListener('focus',function(){input.select();open('');});
  toggle.addEventListener('mousedown',function(e){e.preventDefault();});
  toggle.addEventListener('click',function(){if(list.hidden){input.focus();open('');}else{close(true);input.blur();}});
  input.addEventListener('input',function(){open(input.value);});
  input.addEventListener('blur',function(){close(true);});
  input.addEventListener('keydown',function(e){
    if(e.key==='ArrowDown'){e.preventDefault();if(list.hidden)open(input.value);else if(shown.length){active=(active+1)%shown.length;mark();}}
    else if(e.key==='ArrowUp'){e.preventDefault();if(shown.length){active=(active-1+shown.length)%shown.length;mark();}}
    else if(e.key==='Enter'){e.preventDefault();if(active>=0)choose(active);else if(input.value.trim()){close(false);unsupported(input.value.trim());}}
    else if(e.key==='Escape'){close(true);}});
  sel.addEventListener('change',function(){render(sel.value);setUrl();document.getElementById('overview').scrollIntoView();});
  function bindView(){Array.prototype.forEach.call(app.querySelectorAll('[data-snapshot]'),function(b){
    b.onclick=function(){render(b.getAttribute('data-snapshot'));setUrl();document.getElementById('overview').scrollIntoView();};});
    if(window.bindBeginner)window.bindBeginner(app);}
  var observer=null;
  function spy(){if(!('IntersectionObserver' in window))return;if(observer)observer.disconnect();
    var links=document.querySelectorAll('.secnav a');
    observer=new IntersectionObserver(function(entries){entries.forEach(function(en){if(en.isIntersecting){
      links.forEach(function(a){a.setAttribute('aria-current',a.getAttribute('href')==='#'+en.target.id?'true':'false');});}});},{rootMargin:'-120px 0px -70% 0px'});
    app.querySelectorAll('section[id]').forEach(function(s){observer.observe(s);});}
  var p=new URLSearchParams(location.search), q=(p.get('symbol')||'').trim();
  var sym=current;
  if(q){var found=DATA.stocks.filter(function(s){return s.symbol.toLowerCase()===q.toLowerCase()||s.symbol.split('.')[0]===q;})[0];
    if(!found){unsupported(q);return;}sym=found.symbol;}
  var snapQ=p.get('snapshot'), snapId=null;
  if(snapQ){stock(sym).snapshots.forEach(function(v){if(v.id.indexOf(snapQ)===0)snapId=v.id;});}
  selectStock(sym,snapId);
})();
"""


def _empty_page(branch: str) -> str:
    return (f'<!DOCTYPE html><html lang="zh-Hant-TW"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>個股研究工作區</title><style>{CSS}</style></head><body><main class="wrap"><section><h2>尚無研究資料</h2>'
            + _empty("研究狀態中沒有任何研究版本", f"狀態分支 <code>{_e(branch)}</code> 尚未保存可解析的研究快照。研究管線完成第一次執行後，此頁會顯示研究內容。")
            + "</section></main></body></html>")


def render_research_site_html(
    records: dict[str, Any] | None = None,
    *,
    branch: str = "research-state",
    latest_report: dict[str, Any] | None = None,
    watchlist: dict[str, Any] | None = None,
    latest_only: dict[str, Any] | None = None,
) -> str:
    """Render the complete, self-contained research workspace."""
    from market_research.beginner_view import BEGINNER_CSS, BEGINNER_JS
    payload = build_site_payload(records, branch=branch, latest_report=latest_report, latest_only=latest_only)
    if not payload["stocks"]:
        return _empty_page(branch)
    extra = payload["extra_technical"]
    registry, views = [], {}
    for symbol, stock in payload["stocks"].items():
        views[symbol] = {}
        options = []
        for idx, snap in enumerate(stock["snapshots"]):
            sid = snap["id"]
            if sid not in stock["embedded_ids"]:
                continue
            comp = stock["comparisons"].get(sid) or {}
            own = extra if extra.get("symbol") == symbol and sid == stock["latest_snapshot_id"] else {}
            views[symbol][sid] = _render_view(snap, comp, stock, branch, own)
            tag = "最新" if sid == stock["latest_snapshot_id"] else f"#{len(stock['snapshots']) - idx}"
            fin = "含財務研究" if (snap.get("readiness") or {}).get("financial") == "available" else "無財務研究"
            options.append({"id": sid, "label": f"{_tpe(snap.get('observed_at_utc'))}（{tag}）· {fin} · {COMPARISON_LABELS.get(comp.get('status'), '有研究變化')}"})
        registry.append({"symbol": symbol, "name": stock["name"], "market": stock["market"],
                         "exchange": stock["exchange"], "exchange_code": stock["code"],
                         "currency": stock["currency"], "currency_label": stock["currency_label"],
                         "latest_snapshot_id": stock["latest_snapshot_id"], "snapshots": options,
                         "latest_only": bool(stock.get("latest_only"))})
    default = payload["default_symbol"]
    stock = payload["stocks"][default]
    latest_id = stock["latest_snapshot_id"]
    reg_default = next(r for r in registry if r["symbol"] == default)
    option_html = "".join(f'<option value="{_e(o["id"])}"{" selected" if o["id"] == latest_id else ""}>{_e(o["label"])}</option>'
                          for o in reg_default["snapshots"])
    data = json.dumps({"schema_version": 2, "default_symbol": default, "branch": branch,
                       "generated_at_utc": payload["generated_at_utc"], "stocks": registry, "views": views},
                      ensure_ascii=False).replace("</", "<\\/")
    overview = _watchlist_overview(watchlist)
    sections = ([("watchlist", "觀察名單")] if overview else []) + NAV
    nav = "".join(f'<a href="#{k}">{v}</a>' for k, v in sections)
    picker_value = f"{default}  {stock['name'] or ''}  ·  {stock['code']}"
    cur = f" · {stock['currency_label']}（{stock['currency']}）" if stock.get("currency") else ""
    return f"""<!DOCTYPE html>
<html lang="zh-Hant-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(default)} {_e(stock['name'])} — 個股研究</title>
<style>{CSS}{BEGINNER_CSS}</style>
</head>
<body>
<a class="skip" href="#app">跳到研究內容</a>
<header class="topbar">
  <div class="topbar-inner">
    <div class="brand">Market Research<span>個股研究工作區</span></div>
    <div class="picker" role="search">
      <label for="stock-input">搜尋股票（代號、公司名稱或市場）</label>
      <input id="stock-input" type="text" role="combobox" aria-autocomplete="list" aria-expanded="false"
        aria-controls="stock-list" autocomplete="off" spellcheck="false" value="{_e(picker_value)}" placeholder="搜尋代號或公司名稱">
      <button type="button" class="toggle" id="stock-toggle" aria-label="展開全部股票" aria-controls="stock-list" aria-expanded="false" tabindex="-1">▾</button>
      <ul id="stock-list" role="listbox" aria-label="可研究的股票" hidden></ul>
      <span id="stock-live" class="skip" aria-live="polite"></span>
    </div>
  </div>
  <nav class="secnav" aria-label="研究章節">{nav}</nav>
</header>
<div class="wrap">
  <div class="identity">
    <div>
      <h1><span id="id-name">{_e(stock['name'] or default)}</span><span class="ticker" id="id-ticker">{_e(default)}</span></h1>
      <div class="sub" id="id-sub">{_e(stock['exchange'])}（{_e(stock['code'])}）{_e(cur)}</div>
    </div>
    <div class="version">
      <label for="version-select">研究版本（歷史快照）</label>
      <select id="version-select">{option_html}</select>
    </div>
  </div>
  <p class="disclaimer">研究資料整理，不是投資建議。估值為示意情境、技術觀察僅供研究，皆不構成目標價、進出場或停損價格。缺值以「—」表示，不補零。</p>
  {overview}
  <div id="error-banner" class="banner" role="alert" hidden></div>
  <noscript><p class="banner">未啟用 JavaScript：顯示最新研究版本；股票搜尋與版本切換需要 JavaScript。</p></noscript>
  <main id="app" tabindex="-1">{views[default][latest_id]}</main>
  <footer>資料來源：TWSE OpenAPI、政府資料開放平臺、FinMind。狀態分支 <code>{_e(branch)}</code>；頁面產生於 {_tpe(payload['generated_at_utc'])}（台北）。</footer>
</div>
<script id="site-data" type="application/json">{data}</script>
<script>{BEGINNER_JS}</script>
<script>{JS}</script>
</body>
</html>
"""


def write_research_site(
    out_dir: Path,
    records: dict[str, Any] | None = None,
    *,
    branch: str = "research-state",
    latest_report: dict[str, Any] | None = None,
    watchlist: dict[str, Any] | None = None,
    latest_only: dict[str, Any] | None = None,
) -> Path:
    """Write `index.html` into `out_dir` and return its path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "index.html"
    target.write_text(render_research_site_html(records, branch=branch, latest_report=latest_report,
                                                watchlist=watchlist, latest_only=latest_only), encoding="utf-8")
    return target
