"""Satellite thesis check (#115): monthly revenue trend and same-day announcements.

`review` asks a person to re-read the thesis; it is not a sell signal. A missing
month, an unavailable source or an incomplete announcement snapshot gives
`not_evaluated`, never an assumed `ok`.

Monthly revenue is FinMind TaiwanStockMonthRevenue. A month counts only once it
was public at the cutoff: FinMind's `create_time` when present, otherwise the
statutory deadline (the 10th of the following month).
"""
from datetime import date, datetime
import math
from zoneinfo import ZoneInfo

from .event_risk import TW_MATERIAL_URL

REVENUE_DATASET = "TaiwanStockMonthRevenue"
DEFAULT_CONSECUTIVE_MONTHS = 3
DEFAULT_YOY_BELOW_PCT = 0.0
MAX_CONSECUTIVE_MONTHS = 12
DEFAULT_RULE = {"consecutive_months": DEFAULT_CONSECUTIVE_MONTHS,
                "yoy_below_pct": DEFAULT_YOY_BELOW_PCT}
REVENUE_DEADLINE_DAY = 10
MOPS_ANNOUNCEMENTS_URL = "https://mops.twse.com.tw/mops/web/t05st01"
DISCLAIMER = "請檢視，非買賣建議"
STATUS_LABELS = {"ok": "未觸發", "review": "請檢視", "not_evaluated": "未評估"}
TAIPEI = ZoneInfo("Asia/Taipei")


def revenue_start(cutoff):
    """First month fetched: enough for a 12-month rule plus the prior year and lag."""
    return date(cutoff.year - 3, cutoff.month, 1)


def _label(month_id):
    return f"{month_id // 12}-{month_id % 12 + 1:02d}"


def _public_by(row, year, month, cutoff):
    created = str(row.get("create_time") or "").strip()
    if created:
        return date.fromisoformat(created[:10]) <= cutoff
    deadline = date(year + (month == 12), month % 12 + 1, REVENUE_DEADLINE_DAY)
    return deadline <= cutoff


def _revenue_by_month(rows, code, cutoff):
    by_month = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("stock_id", "")).strip() != code:
            raise ValueError(f"foreign stock_id {row.get('stock_id')} in {REVENUE_DATASET}")
        try:
            year, month = int(row["revenue_year"]), int(row["revenue_month"])
            public = 1 <= month <= 12 and _public_by(row, year, month, cutoff)
        except (KeyError, TypeError, ValueError):
            continue
        revenue = row.get("revenue")
        if (not public or isinstance(revenue, bool) or not isinstance(revenue, (int, float))
                or not math.isfinite(revenue) or revenue < 0):
            continue
        key = year * 12 + month - 1
        if key in by_month and by_month[key]["revenue"] != float(revenue):
            raise ValueError(f"conflicting duplicate {REVENUE_DATASET} rows for {_label(key)}")
        by_month[key] = {"revenue": float(revenue),
                         "published": str(row.get("create_time") or "")[:10] or None}
    return by_month


def evaluate_revenue_trend(symbol, cutoff, rule, history):
    """`review` when year-over-year revenue stays below the threshold for N months."""
    result = {"status": "not_evaluated", "reason": None, "rule": dict(rule), "months": [],
              "dataset": REVENUE_DATASET, "source": (history or {}).get("source")}
    if not history:
        result["reason"] = f"FinMind {REVENUE_DATASET} 無法取得"
        return result
    try:
        by_month = _revenue_by_month(history.get("rows") or [], symbol.split(".")[0], cutoff)
    except ValueError as error:
        result["reason"] = str(error)
        return result
    current = cutoff.year * 12 + cutoff.month - 1
    # Every company has published the previous month after the 10th.
    due = current - 1 if cutoff.day > REVENUE_DEADLINE_DAY else current - 2
    latest = max([due, *by_month])
    n = rule["consecutive_months"]
    missing = []
    for key in range(latest - n + 1, latest + 1):
        this, prior = by_month.get(key), by_month.get(key - 12)
        if this is None or prior is None or prior["revenue"] <= 0:
            missing.append(_label(key if this is None else key - 12))
            continue
        result["months"].append({
            "period": _label(key), "revenue_twd": this["revenue"],
            "prior_year_twd": prior["revenue"], "published": this["published"],
            "yoy_pct": round((this["revenue"] / prior["revenue"] - 1) * 100, 2),
            "_yoy": this["revenue"] / prior["revenue"] - 1})
    if missing:
        result["reason"] = "缺月營收：" + "、".join(missing)
    elif all(m["_yoy"] * 100 < rule["yoy_below_pct"] for m in result["months"]):
        result["status"] = "review"
        result["reason"] = f"月營收年增率連續 {n} 個月低於 {rule['yoy_below_pct']:g}%"
    else:
        result["status"] = "ok"
    for month in result["months"]:
        del month["_yoy"]
    return result


def evaluate_announcements(feed, cutoff):
    """`review` when TWSE's daily material-information snapshot lists one dated today."""
    feed = feed or {}
    result = {"status": "not_evaluated", "reason": None, "items": [],
              "source": TW_MATERIAL_URL, "link": MOPS_ANNOUNCEMENTS_URL,
              "snapshot_date": feed.get("snapshot_date")}
    if feed.get("status") not in ("available", "partial"):
        result["reason"] = "TWSE 重大訊息無法取得：" + str(feed.get("reason") or "unknown")
        return result
    for event in feed.get("events") or []:
        try:
            published = datetime.fromisoformat(event["published_at"]).astimezone(TAIPEI)
        except (KeyError, TypeError, ValueError):
            continue
        if published.date() == cutoff:
            result["items"].append({"title": event.get("title"),
                                    "published_at": event["published_at"]})
    if result["items"]:
        result["status"] = "review"
        result["reason"] = f"當日重大公告 {len(result['items'])} 則"
    elif feed["status"] == "partial":
        result["reason"] = "部分重大訊息列無法解析，無法確認當日沒有公告"
    else:
        result["status"] = "ok"
    return result


def evaluate_thesis(symbol, cutoff, settings, revenue_history, event_feed):
    """Thesis status for one satellite at the evaluation cutoff (a Taipei date)."""
    result = {"status": "not_evaluated", "reason": None, "cutoff": cutoff.isoformat(),
              "thesis": None, "revenue": None, "announcements": None, "disclaimer": DISCLAIMER}
    if settings is None:
        result["reason"] = "Not a watchlist satellite (config/watchlist.yaml)"
        return result
    revenue = evaluate_revenue_trend(symbol, cutoff, settings.get("revenue_check") or DEFAULT_RULE,
                                     revenue_history)
    announcements = evaluate_announcements(event_feed, cutoff)
    statuses = (revenue["status"], announcements["status"])
    status = "review" if "review" in statuses else "not_evaluated" if "not_evaluated" in statuses else "ok"
    reasons = [part["reason"] for part in (revenue, announcements)
               if part["status"] == status and part["reason"]]
    result.update(status=status, reason="；".join(reasons) or None, thesis=settings.get("thesis"),
                  revenue=revenue, announcements=announcements)
    return result


# ---------------------------------------------------------------- presentation

def _yoy_cell(check):
    months = (check.get("revenue") or {}).get("months") or []
    return " / ".join(f"{m['period']} {m['yoy_pct']:+.2f}%" for m in months) or "—"


def _announcement_cell(check):
    announcements = check.get("announcements") or {}
    if announcements.get("status") == "not_evaluated":
        return "未評估"
    return f"{len(announcements.get('items') or [])} 則"


def thesis_summary_row(symbol, check):
    """One daily-summary table row."""
    status = STATUS_LABELS.get(check["status"], check["status"])
    return (f"| {symbol} | {status} | {_yoy_cell(check)} | {_announcement_cell(check)} | "
            f"{check.get('reason') or '—'} |")


def render_thesis_check(check):
    """Markdown section for the company report."""
    lines = ["", "## 論點檢查", "",
             f"**{DISCLAIMER}。** 月營收年增率連續低於門檻或當日有重大公告時標為「請檢視」；"
             "資料不足或來源失敗時為「未評估」，不推定為正常。", ""]
    if check.get("revenue") is None:
        return lines + [f"**not_evaluated**：{check.get('reason')}"]
    status = STATUS_LABELS.get(check["status"], check["status"])
    lines += [f"- 狀態：{status}（{check['status']}）" + (f"：{check['reason']}" if check.get("reason") else ""),
              f"- 論點：{check.get('thesis') or '尚未填寫（config/watchlist.yaml）'}"]
    revenue = check["revenue"]
    rule = revenue["rule"]
    lines += ["", f"### 月營收年增率（FinMind {REVENUE_DATASET}）", "",
              f"規則：連續 {rule['consecutive_months']} 個月年增率 < {rule['yoy_below_pct']:g}% → 請檢視。"
              f"來源：{revenue.get('source') or '—'}"]
    if revenue["months"]:
        lines += ["", "| 月份 | 營收（億元） | 去年同月（億元） | 年增率 | 公開日 |",
                  "| --- | ---: | ---: | ---: | --- |"]
        lines += [f"| {m['period']} | {m['revenue_twd'] / 1e8:,.2f} | {m['prior_year_twd'] / 1e8:,.2f} | "
                  f"{m['yoy_pct']:+.2f}% | {m['published'] or '依法定期限'} |" for m in revenue["months"]]
    if revenue["status"] == "not_evaluated":
        lines += ["", f"未評估：{revenue['reason']}"]
    announcements = check["announcements"]
    lines += ["", "### 當日重大公告（TWSE 每日重大訊息）", "",
              f"來源：{announcements['source']}（快照 {announcements.get('snapshot_date') or '—'}）；"
              f"公告全文：{announcements['link']}"]
    if announcements["status"] == "not_evaluated":
        lines.append(f"未評估：{announcements['reason']}")
    elif announcements["items"]:
        lines += [f"- {item['published_at']}：{item['title']}" for item in announcements["items"]]
    else:
        lines.append("當日沒有重大公告。")
    return lines
