"""Beginner section of the research page (#126): five questions, a health check and a P/E calculator.

Ported from the reviewed prototype (variant A, `scripts/prototype_beginner_site.py` on the
prototype branch). Every sentence comes from snapshot fields, so the same format applies to
any stock; missing data collapses to one line. Nothing here is a fair value, target or
trade price: the calculator only multiplies the reader's own P/E by trailing EPS.
"""
from __future__ import annotations

import html
import math
import re
from typing import Any

from market_research.research_site import TAIPEI, _roc_date, _roc_month, _tpe
from market_research.research_snapshot import utc
from market_research.valuation_zone import DISCLAIMER as ZONE_DISCLAIMER, ZONE_LABELS

QRE = re.compile(r"(\d{4})Q([1-4])")
S1, S2, S3, GRAY = "var(--s1)", "var(--s2)", "var(--s3)", "var(--pc-gray)"


def _f(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def facts(snap: dict[str, Any], stock: dict[str, Any]) -> dict[str, Any]:
    fr = snap.get("financial_research") or {}
    fin = fr.get("status") == "available"
    tech = snap.get("technical") or {}
    val = (fr.get("valuation_summary") or {}) if fin else {}
    return {
        "symbol": snap.get("symbol"),
        "name": (snap.get("issuer") or {}).get("company_name") or stock.get("name") or snap.get("symbol"),
        "asof": utc(snap["observed_at_utc"]).astimezone(TAIPEI).date().isoformat(),
        "generated": _tpe(snap.get("observed_at_utc")),
        "session": tech.get("session"),
        "closes": [(c["date"], float(c["close"])) for c in tech.get("recent_closes") or []
                   if c.get("date") and c.get("close") is not None],
        "q": sorted(fr.get("quarterly_summary") or [], key=lambda r: str(r.get("period_end"))) if fin else [],
        "a": sorted(fr.get("annual_summary") or [], key=lambda r: str(r.get("fiscal_year"))) if fin else [],
        "ttm": fr.get("ttm") if fin and (fr.get("ttm") or {}).get("status") == "available" else None,
        "mult": val.get("exchange_multiples") or {},
        "bs": (fr.get("latest_balance_sheet") or {}) if fin else {},
        "divs": sorted((d for d in fr.get("ex_dividend_history") or [] if d.get("ex_date")),
                       key=lambda d: d["ex_date"]) if fin else [],
        "cal": ((fr.get("calendar_schedule") or {}).get("events") or []) if fin else [],
        "mrev": (snap.get("monthly_revenue") or [None])[0] or {},
        "instrument": (snap.get("readiness") or {}).get("instrument"),
        "zone": (fr.get("valuation_zone") or {}) if fin else {},
    }


def price(F: dict[str, Any]) -> dict[str, Any] | None:
    c = F["closes"]
    if len(c) < 2:
        return None
    vals = [p for _, p in c]
    return {"last": vals[-1], "date": c[-1][0], "chg": (vals[-1] / vals[0] - 1) * 100, "n": len(c),
            "hi": max(vals), "lo": min(vals)}


def same_quarter_yoy(q: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    if not q:
        return None
    cur = q[-1]
    m = QRE.fullmatch(str(cur.get("period_label") or ""))
    prev = next((r for r in q if m and r.get("period_label") == f"{int(m[1]) - 1}Q{m[2]}"), None)
    a, b = _f(cur.get(key)), _f((prev or {}).get(key))
    if a is None or b is None or b <= 0:
        return None
    return {"label": cur["period_label"], "prev": prev["period_label"], "pct": (a / b - 1) * 100}


def same_quarter(q: list[dict[str, Any]], key: str) -> tuple[str, str, float, float] | None:
    """Latest quarter and the same quarter one year earlier: (label, prev label, value, prev value)."""
    if not q:
        return None
    cur = q[-1]
    m = QRE.fullmatch(str(cur.get("period_label") or ""))
    prev = next((r for r in q if m and r.get("period_label") == f"{int(m[1]) - 1}Q{m[2]}"), None)
    a, b = _f(cur.get(key)), _f((prev or {}).get(key))
    return None if a is None or b is None else (cur["period_label"], prev["period_label"], a, b)


def checklist(F: dict[str, Any]) -> list[tuple[str, bool | None, str]] | None:
    """公司體質檢查（草案門檻，正式版寫進 spec）。

    只用公開財報，條件都是「大於 0」或「高於去年同季」，不需調參；缺資料為 None（資料不足），
    不當成未符合。金融或特殊產業（instrument = inapplicable）整份不適用。價格面不在此判斷。
    """
    if F["instrument"] == "inapplicable":
        return None
    ttm, bs = F["ttm"] or {}, F["bs"]
    eps, fcf, net = _f(ttm.get("basic_eps")), _f(ttm.get("free_cash_flow")), _f(bs.get("net_cash"))
    rev, gm = same_quarter(F["q"], "revenue"), same_quarter(F["q"], "gross_margin_pct")
    na = "資料不足"
    return [
        ("近四季有賺錢", None if eps is None else eps > 0, na if eps is None else f"近四季每股賺 {trim(eps)} 元"),
        ("營收比去年同季成長", None if rev is None else rev[2] > rev[3],
         na if rev is None else (f"{E(rev[0])} {chg((rev[2] / rev[3] - 1) * 100)}" if rev[3] > 0 else
                                 f"{E(rev[0])} {yi(rev[2])} 億元（去年同季 {yi(rev[3])} 億元）")),
        ("毛利率比去年同季高", None if gm is None else gm[2] > gm[3],
         na if gm is None else f"{E(gm[0])} {pct(gm[2])}（去年同季 {pct(gm[3])}）"),
        ("近四季自由現金流為正", None if fcf is None else fcf > 0, na if fcf is None else f"{yi(fcf)} 億元"),
        ("現金比借款多", None if net is None else net > 0,
         na if net is None else (f"淨現金 {yi(net)} 億元" if net > 0 else f"淨負債 {yi(abs(net))} 億元")),
    ]


def check_html(F: dict[str, Any]) -> str:
    head = ('<div class="pc-check"><div class="pc-check-h"><h3>先看結論：公司體質檢查</h3>'
            '<p class="pc-sub">用 5 個固定條件檢查公開財報。好公司不等於好價格，這不是買進建議。</p></div>')
    items = checklist(F)
    if items is None:
        return head + miss("金融或特殊產業：一般產業的體質條件不適用，這裡不評估。") + "</div>"
    judged = [ok for _, ok, _ in items if ok is not None]
    if not judged:
        summary = "資料不足，這個版本無法檢查。"
    else:
        summary = f"符合 {sum(judged)}／{len(judged)} 項" + (
            f"（另有 {len(items) - len(judged)} 項資料不足）" if len(judged) < len(items) else "")
    mark = {True: ("ok", "✓", ""), False: ("no", "✗", "未符合・"), None: ("na", "—", "")}
    li = "".join(f'<li class="{mark[ok][0]}"><span class="ic" aria-hidden="true">{mark[ok][1]}</span>'
                 f'<span class="t">{label}</span><span class="v">{mark[ok][2]}{value}</span></li>' for label, ok, value in items)
    eps = _f((F["ttm"] or {}).get("basic_eps"))
    tryit = "可以先用下方的本益比換算器，用你自己的倍數試算。" if F["closes"] and eps is not None and eps > 0 else ""
    return head + f'<p class="sum">{summary}</p><ul>{li}</ul>' + price_line(F, tryit) + "</div>"


def price_line(F: dict[str, Any], tryit: str) -> str:
    """Where the price sits in the stock's own five-year P/E band; never a fair value."""
    zone = F["zone"]
    prices = zone.get("review_prices_twd") or {}
    if zone.get("status") != "available" or zone.get("zone") not in ZONE_LABELS:
        return (f'<p class="price">— 現在的價格貴不貴：<strong>無法判斷</strong>。'
                f'這個版本沒有歷史本益比檢視區可以比較；{tryit}</p>')
    band = "／".join(f"{trim(_f(prices.get(k)))}" for k in ("low", "mid", "high"))
    session = (zone.get("price") or {}).get("session")
    return (f'<p class="price">— 和自己過去 5 年的本益比相比：<strong>{ZONE_LABELS[zone["zone"]]}</strong>'
            f'（偏低／合理／偏高 {band} 元{f"，{E(session)} 收盤" if session else ""}）。'
            f'{ZONE_DISCLAIMER}：價格跑出區間只代表值得重新看一次，不是合理價或目標價。{tryit}</p>')


def run_length(values: list[float | None]) -> int | None:
    """Consecutive moves in the latest direction: +n rising, -n falling, 0 flat, None unknown."""
    if len(values) < 2 or values[-1] is None or values[-2] is None:
        return None
    if values[-1] == values[-2]:
        return 0
    sign = 1 if values[-1] > values[-2] else -1
    n = 0
    for i in range(len(values) - 1, 0, -1):
        a, b = values[i - 1], values[i]
        if a is None or b is None or (b - a) * sign <= 0:
            break
        n += 1
    return n * sign


EVENT_LABEL = {"board_meeting": "{p} 財報公布與配息決議", "shareholder_meeting": "股東常會",
               "earnings_release": "下一次季報公布", "investor_conference": "下一次法說會"}


def timeline(F: dict[str, Any]) -> tuple[list[tuple[str | None, str]], list[tuple[str, str]]]:
    items: list[tuple[str | None, str]] = []
    for e in F["cal"]:
        fmt = EVENT_LABEL.get(e.get("event_type"))
        if fmt:
            items.append((e.get("scheduled_date"), fmt.format(p=e.get("period_label") or "")))
    for d in F["divs"]:
        items.append((d["ex_date"], f"除息：每股配 {trim(_f(d.get('dividend_per_share_twd')))} 元"))
    m = F["mrev"]
    if m.get("unit") == "TWD_thousands" and _f(m.get("value")) is not None and _roc_month(m.get("period")):
        items.append((_roc_date(m.get("reported_at")), f"公布 {_roc_month(m['period'])} 月營收 {yi(_f(m['value']) * 1000)} 億元"))
    upcoming = sorted([(d, t) for d, t in items if d is None or d > F["asof"]], key=lambda x: (x[0] is None, x[0] or ""))
    past = sorted([(d, t) for d, t in items if d is not None and d <= F["asof"]], reverse=True)
    return upcoming, past

# ------------------------------------------------------------------ text

def E(s: Any) -> str:
    return html.escape(str(s))


def yi(v: float | None, d: int = 1) -> str:
    return "—" if v is None else f"{v / 1e8:,.{d}f}"


def trim(v: float | None) -> str:
    return "—" if v is None else f"{v:,.2f}".rstrip("0").rstrip(".")


def pct(v: float | None, d: int = 1) -> str:
    return "—" if v is None else f"{v:.{d}f}%"


def chg(v: float | None, unit: str = "%", d: int = 1) -> str:
    """台股慣例：上漲紅、下跌綠，並附箭頭，不只靠顏色。"""
    if v is None:
        return '<span class="na">—</span>'
    if abs(v) < 0.5 * 10 ** -d:
        return "持平"
    cls, sym = ("pc-up", "▲") if v > 0 else ("pc-down", "▼")
    return f'<span class="{cls}">{sym} {abs(v):.{d}f}{unit}</span>'


GLOSS = {
    "EPS": "每股盈餘：公司替每一股賺了多少錢",
    "毛利率": "每賣 100 元，扣掉直接成本後剩下幾元",
    "營業利益率": "再扣掉研發、管銷等營運費用後剩下幾元",
    "淨利率": "扣完所有費用和稅之後，最後真正賺到幾元",
    "營業現金流": "本業實際收進來的現金",
    "資本支出": "買設備、蓋廠房等長期投資花掉的錢",
    "自由現金流": "營業現金流扣掉資本支出後，公司能自由運用的現金",
    "本益比": "股價 ÷ 每股一年獲利；越高代表市場願意為每 1 元獲利付越多錢",
    "殖利率": "一年配息占股價的比例",
    "淨現金": "現金減掉要付利息的借款；正數代表現金比借款多",
    "近四季": "最近四個季度加總（TTM），比單季更不受季節影響",
    "除息": "發放現金股利的基準日，當天股價會先扣掉配息金額",
}


def gloss(*terms: str) -> str:
    return '<dl class="pc-gloss">' + "".join(f"<dt>{t}</dt><dd>{GLOSS[t]}</dd>" for t in terms) + "</dl>"


def miss(text: str) -> str:
    return f'<p class="pc-missing">{text}</p>'


def table(head: list[str], rows: list[list[str]]) -> str:
    th = "".join(f'<th scope="col">{h}</th>' for h in head)
    body = "".join("<tr>" + "".join(f'<td class="num">{c}</td>' if i else f'<th scope="row">{c}</th>'
                                    for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<div class="table-wrap"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'

# ------------------------------------------------------------------ charts

def ticks(lo: float, hi: float, n: int = 4) -> tuple[float, float, list[float]]:
    if hi == lo:
        hi = lo + (abs(lo) or 1)
    raw = (hi - lo) / n
    exp = 10 ** math.floor(math.log10(raw))
    step = next(m * exp for m in (1, 2, 2.5, 5, 10) if m * exp >= raw * (1 - 1e-9))
    a, b = math.floor(lo / step + 1e-9) * step, math.ceil(hi / step - 1e-9) * step
    return a, b, [a + i * step for i in range(int(round((b - a) / step)) + 1)]


def axis_num(t: float) -> str:
    return format(round(t, 6), ",.10g")


def bar_v(x: float, base: float, end: float, w: float, color: str) -> str:
    top, bot = min(base, end), max(base, end)
    r = min(4.0, bot - top, w / 2)
    if end <= base:
        d = (f"M{x:.1f},{bot:.1f}V{top + r:.1f}Q{x:.1f},{top:.1f} {x + r:.1f},{top:.1f}"
             f"H{x + w - r:.1f}Q{x + w:.1f},{top:.1f} {x + w:.1f},{top + r:.1f}V{bot:.1f}Z")
    else:
        d = (f"M{x:.1f},{top:.1f}V{bot - r:.1f}Q{x:.1f},{bot:.1f} {x + r:.1f},{bot:.1f}"
             f"H{x + w - r:.1f}Q{x + w:.1f},{bot:.1f} {x + w:.1f},{bot - r:.1f}V{top:.1f}Z")
    return f'<path d="{d}" fill="{color}"/>'


def bar_h(base: float, end: float, y: float, h: float, color: str) -> str:
    left, right = min(base, end), max(base, end)
    r = min(4.0, right - left, h / 2)
    if end >= base:
        d = (f"M{left:.1f},{y:.1f}H{right - r:.1f}Q{right:.1f},{y:.1f} {right:.1f},{y + r:.1f}"
             f"V{y + h - r:.1f}Q{right:.1f},{y + h:.1f} {right - r:.1f},{y + h:.1f}H{left:.1f}Z")
    else:
        d = (f"M{right:.1f},{y:.1f}H{left + r:.1f}Q{left:.1f},{y:.1f} {left:.1f},{y + r:.1f}"
             f"V{y + h - r:.1f}Q{left:.1f},{y + h:.1f} {left + r:.1f},{y + h:.1f}H{right:.1f}Z")
    return f'<path d="{d}" fill="{color}"/>'


def legend(series: list[tuple[str, str, Any]]) -> str:
    if len(series) < 2:
        return ""
    return '<div class="pc-legend">' + "".join(f'<span><i style="background:{c}"></i>{E(n)}</span>' for n, c, _ in series) + "</div>"


def columns(cats: list[str], series: list[tuple[str, str, list[float | None]]], *, fmt, w: int = 520, h: int = 210,
            label: str | None = "last", colors: list[str | None] | None = None) -> str:
    """Vertical columns on one zero baseline; series = [(name, css colour, values)]."""
    vals = [v for _, _, vs in series for v in vs if v is not None]
    if not vals or not cats:
        return ""
    lo, hi, tk = ticks(min(0, min(vals)), max(0, max(vals)))
    L, R, T, B = 56, 10, 20, 26
    pw, ph = w - L - R, h - T - B

    def y(v: float) -> float:
        return T + (hi - v) / (hi - lo) * ph
    out = [f'<svg viewBox="0 0 {w} {h}" role="img">']
    for t in tk:
        out.append(f'<line x1="{L}" x2="{w - R}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="{"bl" if t == 0 else "gl"}"/>'
                   f'<text x="{L - 6}" y="{y(t) + 4:.1f}" class="ax" text-anchor="end">{axis_num(t)}</text>')
    slot, k = pw / len(cats), len(series)
    bw = max(4.0, min(24.0, (slot * 0.62 - 2 * (k - 1)) / k))
    gw = k * bw + 2 * (k - 1)
    labelled = {"last": {len(cats) - 1}, "ends": {0, len(cats) - 1}, "all": set(range(len(cats)))}.get(label or "", set())
    for i, c in enumerate(cats):
        x0 = L + slot * i + (slot - gw) / 2
        tips = []
        for j, (name, color, vs) in enumerate(series):
            v = vs[i]
            if v is None:
                tips.append(f"{name} —")
                continue
            out.append(bar_v(x0 + j * (bw + 2), y(0), y(v), bw, (colors[i] if colors and colors[i] else color)))
            tips.append(f"{name} {fmt(v)}" if k > 1 else fmt(v))
            if k == 1 and i in labelled:
                ly = y(v) - 6 if v >= 0 else y(v) + 14
                out.append(f'<text x="{x0 + bw / 2:.1f}" y="{ly:.1f}" class="vl" text-anchor="middle">{E(fmt(v))}</text>')
        out.append(f'<text x="{L + slot * i + slot / 2:.1f}" y="{h - 8}" class="ax" text-anchor="middle">{E(c)}</text>'
                   f'<rect x="{L + slot * i:.1f}" y="{T}" width="{slot:.1f}" height="{ph}" class="hit" '
                   f'data-tip="{E(c + "：" + "；".join(tips))}"/>')
    out.append("</svg>")
    return "".join(out) + legend(series)


def lines(cats: list[str], series: list[tuple[str, str, list[float | None]]], *, fmt, w: int = 520, h: int = 210,
          zero: bool = True, extremes: bool = False) -> str:
    vals = [v for _, _, vs in series for v in vs if v is not None]
    if len(vals) < 2:
        return ""
    lo0, hi0 = min(vals), max(vals)
    if zero:
        lo0, hi0 = min(0, lo0), max(0, hi0)
    else:
        pad = (hi0 - lo0) * 0.1 or abs(hi0) * 0.02 or 1
        lo0, hi0 = lo0 - pad, hi0 + pad
    lo, hi, tk = ticks(lo0, hi0)
    L, R, T, B = 56, 16, 20, 26
    pw, ph = w - L - R, h - T - B
    slot = pw / len(cats)

    def x(i: int) -> float:
        return L + (i + 0.5) * slot

    def y(v: float) -> float:
        return T + (hi - v) / (hi - lo) * ph
    out = [f'<svg viewBox="0 0 {w} {h}" role="img">']
    for t in tk:
        out.append(f'<line x1="{L}" x2="{w - R}" y1="{y(t):.1f}" y2="{y(t):.1f}" class="{"bl" if t == 0 and zero else "gl"}"/>'
                   f'<text x="{L - 6}" y="{y(t) + 4:.1f}" class="ax" text-anchor="end">{axis_num(t)}</text>')
    for name, color, vs in series:
        pts = [(x(i), y(v)) for i, v in enumerate(vs) if v is not None]
        out.append(f'<polyline points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in pts)}" class="ln" stroke="{color}"/>')
        out.append(f'<circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="4" fill="{color}" class="ring"/>')
    if len(series) == 1:
        vs = series[0][2]
        idx = [i for i, v in enumerate(vs) if v is not None]
        marks = {idx[-1]: "end"}
        if extremes:
            marks.setdefault(max(idx, key=lambda i: vs[i]), "hi")
            marks.setdefault(min(idx, key=lambda i: vs[i]), "lo")
        for i, kind in marks.items():
            anchor = "end" if i > len(cats) * 0.8 else "start" if i < len(cats) * 0.2 else "middle"
            dy = 16 if kind == "lo" else -9
            out.append(f'<text x="{x(i):.1f}" y="{y(vs[i]) + dy:.1f}" class="vl" text-anchor="{anchor}">{E(fmt(vs[i]))}</text>')
    shown = set(range(len(cats))) if len(cats) <= 8 else {0, len(cats) // 2, len(cats) - 1}
    for i, c in enumerate(cats):
        if i in shown:
            anchor = "start" if len(cats) > 8 and i == 0 else "end" if len(cats) > 8 and i == len(cats) - 1 else "middle"
            ax = L if anchor == "start" else w - R if anchor == "end" else x(i)
            out.append(f'<text x="{ax:.1f}" y="{h - 8}" class="ax" text-anchor="{anchor}">{E(c)}</text>')
        tip = "；".join(f"{n} {fmt(vs[i]) if vs[i] is not None else '—'}" if len(series) > 1 else
                       (fmt(vs[i]) if vs[i] is not None else "—") for n, _, vs in series)
        out.append(f'<rect x="{L + slot * i:.1f}" y="{T}" width="{slot:.1f}" height="{ph}" class="hit" data-tip="{E(c + "：" + tip)}"/>')
    out.append("</svg>")
    return "".join(out) + legend(series)


def hbars(rows: list[tuple[str, float | None, str]], *, fmt, w: int = 520) -> str:
    """One zero-based horizontal scale; value printed at the bar tip."""
    vals = [v for _, v, _ in rows if v is not None]
    if not vals:
        return ""
    lo, hi = min(0, min(vals)), max(0, max(vals))
    if hi == lo:
        hi = lo + 1
    L, R, row, bh = (120, 80, 34, 16) if w < 450 else (150, 96, 36, 18)
    h = row * len(rows) + 8
    pw = w - L - R

    def x(v: float) -> float:
        return L + (v - lo) / (hi - lo) * pw
    out = [f'<svg viewBox="0 0 {w} {h}" role="img"><line x1="{x(0):.1f}" x2="{x(0):.1f}" y1="0" y2="{h}" class="bl"/>']
    for i, (label, v, color) in enumerate(rows):
        top = 4 + i * row
        cy = top + row / 2
        out.append(f'<text x="{L - 10}" y="{cy + 4:.1f}" class="lb" text-anchor="end">{E(label)}</text>')
        if v is None:
            out.append(f'<text x="{x(0) + 6:.1f}" y="{cy + 4:.1f}" class="ax">—</text>')
            continue
        out.append(bar_h(x(0), x(v), cy - bh / 2, bh, color))
        # A negative bar grows toward the row labels; its value sits right of the zero line instead.
        tx, anchor = (x(v) + 6, "start") if v >= 0 else (x(0) + 6, "start")
        out.append(f'<text x="{tx:.1f}" y="{cy + 4:.1f}" class="vl" text-anchor="{anchor}">{E(fmt(v))}</text>'
                   f'<rect x="0" y="{top}" width="{w}" height="{row}" class="hit" data-tip="{E(label + "：" + fmt(v))}"/>')
    out.append("</svg>")
    return "".join(out)


def spark(values: list[float], w: int = 140, h: int = 36) -> str:
    if len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    hi = hi if hi > lo else lo + 1
    pts = [(3 + i * (w - 8) / (len(values) - 1), 4 + (hi - v) / (hi - lo) * (h - 8)) for i, v in enumerate(values)]
    return (f'<svg class="pc-spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" aria-hidden="true">'
            f'<polyline points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in pts)}" class="ln" stroke="{S1}"/>'
            f'<circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="3.5" fill="{S1}" class="ring"/></svg>')


def fig(title: str, svg: str, caption: str = "") -> str:
    if not svg:
        return ""
    cap = f'<p class="pc-cap">{caption}</p>' if caption else ""
    return f'<figure class="pc-fig"><figcaption class="pc-ft">{title}</figcaption>{svg}{cap}</figure>'

# ------------------------------------------------------------------ content pieces (shared by variants)

def yi_fmt(v: float) -> str:
    return f"{v:,.0f} 億"


def p_price(F: dict[str, Any], w: int = 520) -> dict[str, Any] | None:
    P = price(F)
    if not P:
        return None
    dates, vals = [d for d, _ in F["closes"]], [v for _, v in F["closes"]]
    return {
        **P,
        "head": f'{trim(P["last"])} <small>元</small>',
        "text": (f'收在 {trim(P["last"])} 元（{E(P["date"])}）；近 {P["n"]} 個交易日 {chg(P["chg"])}，'
                 f'期間最高 {trim(P["hi"])}、最低 {trim(P["lo"])} 元。'),
        "chart": lines(dates, [("收盤價", S1, vals)], fmt=lambda v: f"{trim(v)} 元", zero=False, extremes=True, w=w),
        "spark": spark(vals),
        "table": table(["日期", "收盤價（元）"], [[E(d), trim(v)] for d, v in reversed(F["closes"])]),
    }


def p_growth(F: dict[str, Any], w: int = 520) -> dict[str, Any] | None:
    q = [r for r in F["q"] if _f(r.get("revenue")) is not None]
    if not q:
        return None
    last, yoy = q[-1], same_quarter_yoy(F["q"], "revenue")
    text = f'最近一季（{E(last["period_label"])}）營收 {yi(_f(last["revenue"]))} 億元'
    text += f'，比去年同季（{E(yoy["prev"])}）{chg(yoy["pct"])}。' if yoy else "。"
    m = F["mrev"]
    if m.get("unit") == "TWD_thousands" and _f(m.get("value")) is not None and _roc_month(m.get("period")):
        text += f'最新公布的月營收（{_roc_month(m["period"])}）為 {yi(_f(m["value"]) * 1000)} 億元。'
    annual = [r for r in F["a"] if _f(r.get("revenue")) is not None]
    acats = [f'FY{r["fiscal_year"]}' for r in annual]
    avals: list[float | None] = [_f(r["revenue"]) / 1e8 for r in annual]
    colors: list[str | None] = [None] * len(annual)
    atext = ""
    if len(annual) >= 2:
        atext = (f'年營收由 FY{E(annual[0]["fiscal_year"])} 的 {yi(_f(annual[0]["revenue"]))} 億元，'
                 f'到 FY{E(annual[-1]["fiscal_year"])} 的 {yi(_f(annual[-1]["revenue"]))} 億元'
                 f'（最近一年 {chg(_f(annual[-1].get("revenue_yoy_pct")))}）。')
    if F["ttm"] and _f(F["ttm"].get("revenue")) is not None:
        acats.append("近四季")
        avals.append(_f(F["ttm"]["revenue"]) / 1e8)
        colors.append(GRAY)
    return {
        "head": f'比去年同季 {chg(yoy["pct"])}' if yoy else f'{yi(_f(last["revenue"]))} 億元',
        "text": text, "atext": atext,
        "chart": columns([r["period_label"] for r in q], [("單季營收", S1, [_f(r["revenue"]) / 1e8 for r in q])], fmt=yi_fmt, w=w),
        "annual": columns(acats, [("年營收", S1, avals)], fmt=yi_fmt, label="ends", colors=colors) if len(avals) >= 2 else "",
        "table": table(["期間", "營收（億元）", "年增率"],
                       [[f'FY{E(r["fiscal_year"])}', yi(_f(r["revenue"])), chg(_f(r.get("revenue_yoy_pct")))] for r in reversed(annual)]
                       + [[E(r["period_label"]), yi(_f(r["revenue"])), "—"] for r in reversed(q)]),
    }


def p_margin(F: dict[str, Any], w: int = 520) -> dict[str, Any] | None:
    q, ttm = F["q"], F["ttm"]
    keys = [("毛利率", "gross_margin_pct", S1), ("營業利益率", "operating_margin_pct", S2), ("淨利率", "net_margin_pct", S3)]
    series = [(n, c, [_f(r.get(k)) for r in q]) for n, k, c in keys]
    has_q = any(v is not None for _, _, vs in series for v in vs)
    if not has_q and not ttm:
        return None
    text, head = "", "—"
    gm = series[0][2]
    if gm and gm[-1] is not None:
        head = f"毛利率 {pct(gm[-1])}"
        n = run_length(gm)
        trend = ("" if n is None else "和上一季持平" if n == 0 else
                 f"已連續 {abs(n)} 季{'上升' if n > 0 else '下降'}" if abs(n) >= 2 else
                 f"比上一季{'上升' if n > 0 else '下降'} {abs(gm[-1] - gm[-2]):.1f} 個百分點")
        text += f'最近一季（{E(q[-1]["period_label"])}）毛利率 {pct(gm[-1])}' + (f"，{trend}。" if trend else "。")
    chain, ctext = "", ""
    if ttm:
        g, o, n_ = (_f(ttm.get(k)) for k in ("gross_margin_pct", "operating_margin_pct", "net_margin_pct"))
        if None not in (g, o, n_):
            last = f"最後淨賺 {n_:.1f} 元" if n_ >= 0 else f"最後虧損 {abs(n_):.1f} 元"
            ctext = f"近四季每賣 100 元：扣掉直接成本剩 {g:.1f} 元，再扣營運費用剩 {o:.1f} 元，{last}。"
        chain = hbars([("營收", 100.0, GRAY), ("毛利", g, GRAY), ("營業利益", o, GRAY), ("淨利", n_, S1)],
                      fmt=lambda v: f"{v:.1f} 元", w=w)
    return {
        "head": head, "text": text, "ctext": ctext, "chain": chain,
        "chart": lines([r["period_label"] for r in q], series, fmt=pct, w=w) if has_q else "",
        "table": table(["季度", "毛利率", "營業利益率", "淨利率"],
                       [[E(r["period_label"]), *(pct(_f(r.get(k))) for _, k, _ in keys)] for r in reversed(q)]),
    }


def p_eps(F: dict[str, Any], w: int = 520) -> dict[str, Any] | None:
    q = [r for r in F["q"] if _f(r.get("basic_eps")) is not None]
    ttm_eps = _f((F["ttm"] or {}).get("basic_eps"))
    if not q and ttm_eps is None:
        return None
    yoy = same_quarter_yoy(F["q"], "basic_eps")
    text = f"近四季每股賺 {trim(ttm_eps)} 元。" if ttm_eps is not None else ""
    if q:
        text += f'最近一季（{E(q[-1]["period_label"])}）每股賺 {trim(_f(q[-1]["basic_eps"]))} 元'
        text += f"，比去年同季 {chg(yoy['pct'])}。" if yoy else "。"
    return {"head": f"{trim(ttm_eps)} 元", "text": text,
            "chart": columns([r["period_label"] for r in q], [("單季 EPS", S1, [_f(r["basic_eps"]) for r in q])],
                             fmt=lambda v: f"{trim(v)} 元", w=w)}


def p_cash(F: dict[str, Any], w: int = 520) -> dict[str, Any] | None:
    ttm, q = F["ttm"], F["q"]
    if not ttm:
        return None
    ocf, capex, fcf = (_f(ttm.get(k)) for k in ("operating_cash_flow", "capex", "free_cash_flow"))
    if ocf is None:
        return None
    text = f"近四季本業收進現金 {yi(ocf)} 億元"
    if capex is not None and ocf > 0:
        text += f"，其中 {yi(capex)} 億元（約 {capex / ocf * 100:.0f}%）用在資本支出"
    text += f"，剩下自由現金流 {yi(fcf)} 億元。" if fcf is not None else "。"
    keys = [("營業現金流", "operating_cash_flow", S1), ("資本支出", "capex", S2), ("自由現金流", "free_cash_flow", S3)]
    return {
        "head": f"自由現金流 {yi(fcf)} 億", "text": text,
        "chart": hbars([("營業現金流（收進）", ocf / 1e8, GRAY), ("資本支出（花掉）", None if capex is None else capex / 1e8, GRAY),
                        ("自由現金流（剩下）", None if fcf is None else fcf / 1e8, S1)], fmt=yi_fmt, w=w),
        "quarterly": columns([r["period_label"] for r in q],
                             [(n, c, [None if _f(r.get(k)) is None else _f(r.get(k)) / 1e8 for r in q]) for n, k, c in keys],
                             fmt=yi_fmt, label=None, w=w) if q else "",
        "table": table(["期間", "營業現金流", "資本支出", "自由現金流"],
                       [["近四季", yi(ocf), yi(capex), yi(fcf)]]
                       + [[E(r["period_label"]), *(yi(_f(r.get(k))) for _, k, _ in keys)] for r in reversed(q)]),
    }


def p_balance(F: dict[str, Any], w: int = 520) -> dict[str, Any] | None:
    bs = F["bs"]
    cash, debt, net = (_f(bs.get(k)) for k in ("cash", "total_debt", "net_cash"))
    if cash is None and net is None:
        return None
    word = "淨現金" if (net or 0) >= 0 else "淨負債"
    return {
        "word": word, "amount": f"{yi(abs(net) if net is not None else None, 0)} 億",
        "head": f"{word} {yi(abs(net) if net is not None else None)} 億",
        "text": f'{E(bs.get("period_end"))} 帳上現金 {yi(cash)} 億元、要付利息的借款 {yi(debt)} 億元，{word} {yi(abs(net) if net is not None else None)} 億元。',
        "chart": hbars([("現金", None if cash is None else cash / 1e8, GRAY), ("有息負債", None if debt is None else debt / 1e8, GRAY),
                        (word, None if net is None else net / 1e8, S1)], fmt=yi_fmt, w=w),
    }


def p_value(F: dict[str, Any], w: int = 520) -> dict[str, Any] | None:
    m = F["mult"]
    pe, yld = _f(m.get("pe_ratio")), _f(m.get("dividend_yield_pct"))
    if pe is None and yld is None:
        return None
    when = _roc_date(m.get("date_roc")) or "日期未提供"
    earn = 100 / pe if pe and pe > 0 else None
    parts = []
    if pe is not None:
        parts.append(f"證交所公布本益比 {trim(pe)} 倍" + (f"：每 100 元股價，對應一年約 {earn:.1f} 元獲利" if earn else ""))
    if yld is not None:
        parts.append(f"殖利率 {pct(yld, 2)}：每 100 元股價，一年約配 {yld:.1f} 元")
    return {
        "head": f"本益比 {trim(pe)} 倍",
        "text": "；".join(parts) + f"（{E(when)}）。這是市場目前給的價格水準，不是合理價或目標價。",
        "chart": hbars([("股價", 100.0, GRAY), ("一年獲利", earn, S1), ("一年配息", yld, S1)], fmt=lambda v: f"{v:.1f} 元", w=w),
        "pe": pe, "yld": yld,
    }


def money(v: float) -> str:
    return f"{v:,.0f}" if v >= 100 else f"{v:,.1f}"


def calc_diff(v: float, last: float) -> str:
    """Same wording as CALC_JS; neutral ink, because the gap only restates the reader's own multiple."""
    d = (v / last - 1) * 100
    if abs(d) < 0.5:
        return "和現在股價差不多：你給的倍數和市場現在差不多。"
    word = "高" if d > 0 else "低"
    return f"比現在股價{word} {abs(d):.1f}%：你給的倍數比市場現在{word}，所以換算出來的價格也比較{word}。"


def p_calc(F: dict[str, Any]) -> str:
    """本益比換算器：倍數由讀者決定，頁面只做「倍數 × 近四季 EPS」的換算，不產生合理價或目標價。"""
    head = '<div class="pc-ft">本益比換算器：你願意給幾倍？</div>'
    ttm = F["ttm"] or {}
    eps = _f(ttm.get("basic_eps"))
    if not F["closes"] or eps is None:
        return f'<div class="pc-fig">{head}{miss("這個版本沒有股價或近四季 EPS，無法換算。")}</div>'
    if eps <= 0:
        return f'<div class="pc-fig">{head}{miss("近四季沒有賺錢（EPS 不是正數），本益比無法換算。")}</div>'
    day, last = F["closes"][-1]
    cur = round(last / eps, 1)
    lo, hi = min(5.0, math.floor(cur / 2)), max(50.0, math.ceil(cur * 2 / 10) * 10)
    span = hi - lo
    q = ttm.get("quarters") or []
    period = f"（{E(q[0])}–{E(q[-1])}）" if q else ""
    scale = "".join(f'<span style="--p:{(t - lo) / span:.4f}">{axis_num(t)} 倍<br>{money(t * eps)} 元</span>'
                    for t in ticks(lo, hi, 6)[2] if lo <= t <= hi)
    m = F["mult"]
    twse = (f'；證交所 {E(_roc_date(m.get("date_roc")) or "日期未提供")} 公布 {trim(_f(m["pe_ratio"]))} 倍（日期不同）'
            if _f(m.get("pe_ratio")) is not None else "")
    return (f'<div class="pc-fig pc-calc" data-eps="{eps}" data-price="{last}" data-cur="{cur}" style="--p:{(cur - lo) / span:.4f}">{head}'
            f'<p class="pc-cap">股價 = 本益比 × 每股一年獲利。拉動滑桿試試看。</p>'
            f'<p class="eq"><output class="m">{cur:.1f}</output> 倍 × 近四季 EPS {trim(eps)} 元 = '
            f'<output class="v">{money(cur * eps)}</output> 元</p>'
            f'<div class="track"><span class="now" style="--p:{(cur - lo) / span:.4f}" '
            f'data-tip="市場現在：{trim(last)} 元 ÷ {trim(eps)} 元 ≈ {cur:.1f} 倍">市場現在 {cur:.1f} 倍</span>'
            f'<input type="range" min="{lo:g}" max="{hi:g}" step="0.1" value="{cur}" aria-label="你願意給的本益比（倍）">'
            f'<div class="scale">{scale}</div></div>'
            f'<p class="diff">{calc_diff(cur * eps, last)}</p>'
            f'<button type="button" class="reset">回到市場現在的倍數</button>'
            f'<p class="pc-cap">市場現在：股價 {trim(last)} 元（{E(day)}）÷ 近四季 EPS {trim(eps)} 元{period}≈ {cur:.1f} 倍{twse}。'
            '倍數由你決定、沒有標準答案，算出來的不是合理價或目標價。</p></div>')


def p_divs(F: dict[str, Any], w: int = 520) -> dict[str, Any] | None:
    d = [x for x in F["divs"] if _f(x.get("dividend_per_share_twd")) is not None]
    if not d:
        return None
    amounts = [_f(x["dividend_per_share_twd"]) for x in d]
    text = f'最近一次除息在 {E(d[-1]["ex_date"])}，每股配 {trim(amounts[-1])} 元'
    text += f"；近 {len(d)} 次配息從每股 {trim(amounts[0])} 元到 {trim(amounts[-1])} 元。" if len(d) >= 2 else "。"
    longp = [(x["ex_date"], _f(x.get("before_price"))) for x in d if _f(x.get("before_price")) is not None]
    return {
        "head": f"每股 {trim(amounts[-1])} 元", "text": text,
        "chart": columns([x["ex_date"][:7] for x in d], [("每股配息", S1, amounts)], fmt=lambda v: f"{trim(v)} 元", label="ends", w=w),
        "long": lines([dt[:7] for dt, _ in longp], [("除息前一日收盤價", S1, [p for _, p in longp])],
                      fmt=lambda v: f"{trim(v)} 元", zero=False) if len(longp) >= 2 else "",
        "longtext": (f"從除息資料可以看到更長的股價：{E(longp[0][0])} 為 {trim(longp[0][1])} 元，"
                     f"{E(longp[-1][0])} 為 {trim(longp[-1][1])} 元。") if len(longp) >= 2 else "",
        "table": table(["除息日", "每股配息（元）", "除息前一日收盤價（元）"],
                       [[E(x["ex_date"]), trim(a), trim(_f(x.get("before_price")))] for x, a in zip(reversed(d), reversed(amounts))]),
    }


def events_html(F: dict[str, Any], limit: int = 6, cls: str = "pc-tl") -> str:
    upcoming, past = timeline(F)
    if not upcoming and not past:
        return miss("這個版本沒有事件資料。")
    li = ([f'<li class="next"><time>{E(d) if d else "日期未公告"}</time><span>{E(t)}</span></li>' for d, t in upcoming]
          + [f'<li><time>{E(d)}</time><span>{E(t)}</span></li>' for d, t in past[:limit]])
    return f'<ol class="{cls}">{"".join(li)}</ol>'

# ------------------------------------------------------------------ variant A：問答式

def render_beginner(snap: dict[str, Any], stock: dict[str, Any]) -> str:
    """The 新手 section for one research version."""
    F = facts(snap, stock)
    P, G, M, Q, C, BAL, V, D = (p_price(F), p_growth(F), p_margin(F), p_eps(F), p_cash(F), p_balance(F), p_value(F), p_divs(F))
    hero_price = (f'<div class="va-price"><div class="big">{P["head"]}</div>'
                  f'<div>{chg(P["chg"])} <span class="pc-sub">近 {P["n"]} 個交易日</span></div>{P["spark"]}</div>') if P else miss("這個版本沒有保存股價。")

    def q(n: int, title: str, head: str, body: str, charts: list[str], terms: tuple[str, ...]) -> str:
        charts = [c for c in charts if c]
        return (f'<article class="va-q"><div><p class="qn">問題 {n}</p><h3>{title}</h3>'
                f'{f"<p class=va-ans>{head}</p>" if head else ""}<p>{body}</p>{gloss(*terms) if terms else ""}</div>'
                f'<div class="va-charts">{"".join(charts)}</div></article>')

    def gap(n: int, title: str, what: str) -> str:
        """Missing data collapses to one line instead of an empty question-and-chart block."""
        return f'<article class="va-q va-gap"><p class="qn">問題 {n}</p><h3>{title}</h3>{miss(f"這個版本沒有{what}。")}</article>'
    upcoming, past = timeline(F)
    nxt = (f'{upcoming[0][1]}：{upcoming[0][0] or "日期未公告"}' if upcoming else
           f'{past[0][1]}（{past[0][0]}）' if past else "")
    blocks = [
        q(1, "生意有變大嗎？", G["head"], G["text"] + G["atext"],
          [fig("單季營收（億元）", G["chart"]), fig("年營收（億元）", G["annual"], "灰色是近四季加總，和會計年度的期間不同。")], ("近四季",))
        if G else gap(1, "生意有變大嗎？", "財報資料"),
        q(2, "賺錢能力有變好嗎？", M["head"], M["text"] + M["ctext"] + (Q["text"] if Q else ""),
          [fig("每賣 100 元，最後剩多少（近四季）", M["chain"]), fig("三種利潤率（單季，%）", M["chart"])],
          ("毛利率", "營業利益率", "淨利率", "EPS"))
        if M else gap(2, "賺錢能力有變好嗎？", "財報資料"),
        q(3, "賺到的錢，真的有進口袋嗎？", C["head"] if C else BAL["head"] if BAL else "",
          (C["text"] if C else "") + (BAL["text"] if BAL else ""),
          [fig("近四季現金流向（億元）", C["chart"] if C else ""), fig("現金和借款（億元）", BAL["chart"] if BAL else "")],
          ("營業現金流", "資本支出", "自由現金流", "淨現金"))
        if (C or BAL) else gap(3, "賺到的錢，真的有進口袋嗎？", "現金流資料"),
        q(4, "現在的股價在什麼水準？", V["head"] if V else (P["head"] if P else ""),
          (P["text"] if P else "") + (V["text"] if V else ""),
          [fig(f'近 {P["n"]} 個交易日收盤價（元）' if P else "", P["chart"] if P else ""),
           fig("花 100 元買股票，一年對應多少（元）", V["chart"] if V else ""), p_calc(F)], ("本益比", "殖利率") if V else ())
        if (P or V) else gap(4, "現在的股價在什麼水準？", "股價或本益比資料"),
        q(5, "最近和接下來有什麼事？", E(nxt), D["text"] if D else "",
          [f'<div class="pc-fig"><div class="pc-ft">事件時間軸</div>{events_html(F)}</div>',
           fig("每次配息（每股，元）", D["chart"] if D else "")], ("除息",) if D else ())
        if (upcoming or past) else gap(5, "最近和接下來有什麼事？", "事件資料"),
    ]
    return ('<section id="beginner" class="pc va" aria-labelledby="h-beginner">'
            f'<header class="va-hero"><div><h2 id="h-beginner">新手看這裡</h2>'
            f'<p class="pc-sub">股價資料日 {E(F["session"] or "—")}・研究產生 {E(F["generated"])}（台北）</p>'
            f'<p class="pc-disc">用 5 個問題看懂這家公司。只整理公開資料，不是投資建議；完整數字在後面的章節。</p></div>{hero_price}</header>'
            + check_html(F) + "".join(blocks) + "</section>")



# ---------------------------------------------------------------- page assets

BEGINNER_CSS = """
.pc{--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--pc-gray:#c3c2b7;--pc-grid:#e1e0d9;--pc-axis:#c3c2b7;--pc-muted:#898781;--pc-up:#c62828;--pc-down:#1a7f37}
@media (prefers-color-scheme:dark){.pc{--s1:#3987e5;--s2:#d95926;--s3:#199e70;--pc-gray:#55544f;--pc-grid:#2c2c2a;--pc-axis:#383835;--pc-up:#ff6b6b;--pc-down:#4cc38a}}
.pc-sub{color:var(--muted);font-size:13px;margin:4px 0 0}.pc-disc{font-size:14px;margin:8px 0 0}
.pc-missing{color:var(--muted);font-size:13px;padding:10px 12px;border:1px dashed var(--line);border-radius:6px;margin:6px 0}
.pc-fig{margin:0;padding:12px 14px;background:var(--surface);border:1px solid var(--line);border-radius:8px}
.pc-ft{font-size:13px;font-weight:600;margin-bottom:6px}.pc-cap{font-size:12px;color:var(--muted);margin:6px 0 0}
.pc svg{display:block;width:100%;height:auto;overflow:visible}.pc svg.pc-spark{width:140px;margin-top:6px}
.pc .ax{font-size:11px;fill:var(--pc-muted)}.pc .vl{font-size:12px;font-weight:600;fill:var(--text)}.pc .lb{font-size:13px;fill:var(--text)}
.pc .gl{stroke:var(--pc-grid);stroke-width:1}.pc .bl{stroke:var(--pc-axis);stroke-width:1}
.pc .ln{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}.pc .ring{stroke:var(--surface);stroke-width:2}
.pc .hit{fill:transparent}.pc .hit:hover{fill:var(--text);fill-opacity:.05}
.pc-legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:var(--muted);margin-top:6px}
.pc-legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.pc-gloss{display:grid;grid-template-columns:auto 1fr;gap:3px 10px;font-size:12px;color:var(--muted);margin:12px 0 0;padding:10px 12px;background:var(--surface);border-radius:6px}
.pc-gloss dt{font-weight:600;color:var(--text)}.pc-gloss dd{margin:0}
.pc-check{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:6px 0 20px}.pc-check-h{display:flex;justify-content:space-between;align-items:baseline;gap:6px 16px;flex-wrap:wrap}.pc-check h3{font-size:18px;margin:0}.pc-check .sum{font-size:24px;font-weight:700;margin:8px 0 12px}.pc-check ul{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:8px}.pc-check li{display:grid;grid-template-columns:22px minmax(0,1fr);gap:2px 8px;padding:10px 12px;border:1px solid var(--line);border-radius:8px}.pc-check .ic{font-weight:700;font-size:16px;grid-row:span 2}.pc-check li.ok .ic{color:var(--ok)}.pc-check li.no .ic{color:var(--warn)}.pc-check li.na .ic{color:var(--muted)}.pc-check .t{font-weight:600;font-size:14px}.pc-check .v{font-size:13px;color:var(--muted)}.pc-check .price{margin:12px 0 0;font-size:14px;color:var(--muted)}.pc-check .price strong{color:var(--text)}.pc-up{color:var(--pc-up);font-weight:600}.pc-down{color:var(--pc-down);font-weight:600}
.pc-tl{list-style:none;margin:0;padding:0}.pc-tl li{display:flex;gap:12px;padding:7px 0;border-bottom:1px solid var(--line);font-size:14px}
.pc-tl li:last-child{border-bottom:0}.pc-tl time{color:var(--muted);min-width:96px;font-variant-numeric:tabular-nums}
.pc-tl li.next time{color:var(--accent);font-weight:600}
.va-hero{display:flex;justify-content:space-between;align-items:flex-end;gap:24px;padding:0 0 18px}.va-hero h2{margin:0}
.va-price{text-align:right}.va-price .big{font-size:52px;font-weight:700;line-height:1.05}.va-price small{font-size:18px;color:var(--muted)}
.va-price .pc-spark{margin-left:auto}
.va-q{display:grid;grid-template-columns:minmax(0,4fr) minmax(0,7fr);gap:32px;padding:30px 0;border-top:1px solid var(--line)}
.va-q .qn{font-size:12px;color:var(--accent);font-weight:700;margin:0}.va-q h3{margin:2px 0 6px;font-size:22px}
.va-ans{font-size:28px;font-weight:700;margin:4px 0 10px;line-height:1.3}.va-gap{display:block;padding:18px 0}.va-gap h3{font-size:18px}.va-q .va-ans{font-size:26px}.va-charts{display:grid;gap:14px;align-content:start}
.pc-calc .eq{font-size:20px;margin:10px 0 4px}.pc-calc output{font-weight:700;font-variant-numeric:tabular-nums}.pc-calc .v{font-size:30px;color:var(--s1)}
.pc-calc .track{position:relative;padding:30px 0 34px;margin:0 2px}
.pc-calc input[type=range]{width:100%;margin:0;accent-color:var(--s1);cursor:pointer;height:22px}
.pc-calc .now{position:absolute;top:0;left:calc(8px + (100% - 16px) * var(--p));transform:translateX(-50%);font-size:12px;color:var(--muted);white-space:nowrap;padding-bottom:12px}
.pc-calc .now::after{content:"";position:absolute;left:50%;bottom:0;height:16px;border-left:2px dashed var(--pc-axis)}
.pc-calc .scale span{position:absolute;bottom:0;left:calc(8px + (100% - 16px) * var(--p));transform:translateX(-50%);font-size:11px;color:var(--pc-muted);text-align:center;line-height:1.3;white-space:nowrap}
.pc-calc .diff{font-size:15px;margin:6px 0}.pc-calc .reset{font:inherit;font-size:13px;background:none;border:1px solid var(--line);border-radius:6px;padding:4px 10px;color:var(--text);cursor:pointer}
.pc-tip{position:fixed;z-index:100;pointer-events:none;background:var(--text);color:var(--bg);font-size:12px;padding:6px 8px;border-radius:6px;max-width:300px}
@media (max-width:760px){.va-q{grid-template-columns:1fr;gap:14px}.va-hero{flex-wrap:wrap}.va-price{text-align:left}.va-price .pc-spark{margin-left:0}}
"""

# Tooltips are delegated once; calculators are bound each time a view is injected.
BEGINNER_JS = """(function(){var tip=document.createElement("div");tip.className="pc-tip";tip.hidden=true;document.body.appendChild(tip);
addEventListener("pointerover",function(e){var t=e.target.closest&&e.target.closest("[data-tip]");if(!t){tip.hidden=true;return}tip.textContent=t.dataset.tip;tip.hidden=false});
addEventListener("pointermove",function(e){if(!tip.hidden){tip.style.left=Math.min(e.clientX+14,innerWidth-310)+"px";tip.style.top=(e.clientY+16)+"px"}});
window.bindBeginner=function(root){(root||document).querySelectorAll(".pc-calc").forEach(function(box){if(box.dataset.bound)return;box.dataset.bound="1";
var eps=+box.dataset.eps,px=+box.dataset.price,r=box.querySelector("input");
function money(v){return v.toLocaleString("en-US",{maximumFractionDigits:v>=100?0:1,minimumFractionDigits:v>=100?0:1})}
function upd(){var m=+r.value,v=m*eps,d=(v/px-1)*100,w=d>0?"高":"低";box.style.setProperty("--p",(m-r.min)/(r.max-r.min));
box.querySelector(".m").textContent=m.toFixed(1);box.querySelector(".v").textContent=money(v);
box.querySelector(".diff").textContent=Math.abs(d)<0.5?"和現在股價差不多：你給的倍數和市場現在差不多。":
"比現在股價"+w+" "+Math.abs(d).toFixed(1)+"%：你給的倍數比市場現在"+w+"，所以換算出來的價格也比較"+w+"。"}
r.addEventListener("input",upd);box.querySelector(".reset").onclick=function(){r.value=box.dataset.cur;upd()}})};
window.bindBeginner(document)})();"""
