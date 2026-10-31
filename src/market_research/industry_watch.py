"""Industry watch (#141): price position, a P/B review zone and revenue momentum.

Industry-watch groups sit beside the satellites and the core ETFs. Their stocks are
never scanned or researched. Each daily TW run gives every stock the core-ETF price
position (close, 52-week drawdown, 200-session moving average) and a review zone: the
stock's own five-year daily P/B percentiles times the book value per share implied by
the latest close and the P/B of the same day. Cyclical makers earn most when their P/E
is lowest, so the zone uses P/B, not P/E. A review zone asks a person to look again; it
is not a fair value, target, entry or exit price.

Revenue momentum (#143) watches whether the cycle's growth is peaking: the three-month
rolling revenue YoY, from months public at the cutoff under the thesis-check rule, is
`contracting` below zero, else `slowing` after N consecutive strict declines.
"""
from datetime import date, datetime, timezone
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import yaml

from .fundamentals import finmind_per_url, finmind_revenue_url, json_get
from .price_watch import load_price_watch, price_watch_notes
from .thesis_check import (
    DEFAULT_CONSECUTIVE_MONTHS, MAX_CONSECUTIVE_MONTHS, REVENUE_DATASET, REVENUE_DEADLINE_DAY,
    _label, _revenue_by_month, revenue_start,
)
from .valuation_zone import (
    DEFAULT_PERCENTILES, DISCLAIMER, MIN_PER_SAMPLES, PER_DATASET, WINDOW_YEARS, ZONE_LABELS,
    _increasing_triple, load_watchlist, per_window_start, ratio_series,
)

TAIPEI = ZoneInfo("Asia/Taipei")
PBR_FIELD = "PBR"
SUFFIXES = (".TW",)
GROUP_KEYS = {"name", "rationale", "symbols", "pb_zone", "revenue_momentum"}
SYMBOL_KEYS = {"name", "revenue_momentum"}
ROLLING_MONTHS = 3
MOMENTUM_LABELS = {"ok": "未放緩", "slowing": "放緩", "contracting": "衰退",
                   "not_evaluated": "未評估"}
POSITION_FIELDS = ("status", "source", "session", "first_date", "close", "drawdown_52w",
                   "ma_200", "adjustments", "error_type", "reason")
ASSUMPTIONS = (
    "Review prices = P/B band x book value per share; the band is the stock's own daily P/B "
    "percentiles (linear interpolation) over the five years up to the cutoff, positive P/B only. "
    "Book value per share = latest close / FinMind TaiwanStockPER PBR of the same day (derived; "
    "PBR is rounded to 0.01). No forward book value, earnings or cycle adjustment."
)


def load_industry_watch(config_dir):
    """Industry-watch groups from watchlist.yaml; their stocks are neither scanned nor satellites."""
    path = Path(config_dir) / "watchlist.yaml"
    if not path.exists():
        return []
    raw = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("industry_watch") or {}
    if not isinstance(raw, dict):
        raise ValueError("industry_watch: must map group ids to groups")
    markets = yaml.safe_load((Path(config_dir) / "markets.yaml").read_text())["markets"]
    scanned = set((markets.get("tw") or {}).get("symbols") or [])
    satellites = set(load_watchlist(config_dir))
    groups, seen = [], set()
    for group_id, entry in raw.items():
        where = f"industry_watch {group_id}"
        if not isinstance(entry, dict) or set(entry) - GROUP_KEYS:
            raise ValueError(f"{where}: unknown keys")
        for key in ("name", "rationale"):
            if not isinstance(entry.get(key), str) or not entry[key].strip():
                raise ValueError(f"{where}: {key} must be text")
        momentum = _momentum_rule(entry.get("revenue_momentum"), where,
                                  {"consecutive_months": DEFAULT_CONSECUTIVE_MONTHS})
        symbols = entry.get("symbols")
        if not isinstance(symbols, dict) or not symbols:
            raise ValueError(f"{where}: symbols must map codes to company names")
        names, overrides = {}, {}
        for symbol, value in symbols.items():
            code, dot, suffix = str(symbol).partition(".")
            if not dot or "." + suffix not in SUFFIXES or not code.isalnum():
                raise ValueError(f"{where} {symbol}: stock codes end in " + " or ".join(SUFFIXES))
            if code.startswith("00"):
                raise ValueError(f"{where} {symbol}: ETF/ETN codes are price-only, not industry watch")
            if symbol in scanned or symbol in satellites:
                raise ValueError(f"{where} {symbol}: already scanned in markets.yaml or a satellite")
            if symbol in seen:
                raise ValueError(f"{where} {symbol}: listed in more than one group")
            # A bare company name, or {name, revenue_momentum} to override the group rule.
            if isinstance(value, dict):
                if set(value) - SYMBOL_KEYS:
                    raise ValueError(f"{where} {symbol}: unknown keys")
                if "revenue_momentum" in value:
                    overrides[symbol] = {"revenue_momentum": _momentum_rule(
                        value["revenue_momentum"], f"{where} {symbol}", momentum)}
                value = value.get("name")
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{where} {symbol}: company name must be text")
            names[symbol] = value.strip()
            seen.add(symbol)
        zone = entry.get("pb_zone") or {}
        if not isinstance(zone, dict) or set(zone) - {"percentiles"}:
            raise ValueError(f"{where}: unknown pb_zone keys")
        percentiles = _increasing_triple(zone.get("percentiles", list(DEFAULT_PERCENTILES)),
                                         group_id, "percentiles")
        if not (0 < percentiles[0] and percentiles[2] < 100):
            raise ValueError(f"{where}: percentiles must be between 0 and 100")
        groups.append({"id": group_id, "name": entry["name"].strip(),
                       "rationale": entry["rationale"].strip(), "symbols": names,
                       "pb_zone": {"percentiles": tuple(percentiles)},
                       "revenue_momentum": momentum, "overrides": overrides})
    return groups


def _momentum_rule(raw, where, default):
    if raw is None:
        return dict(default)
    if not isinstance(raw, dict) or set(raw) - {"consecutive_months"}:
        raise ValueError(f"{where}: unknown revenue_momentum keys")
    months = raw.get("consecutive_months", default["consecutive_months"])
    if isinstance(months, bool) or not isinstance(months, int) or not 1 <= months <= MAX_CONSECUTIVE_MONTHS:
        raise ValueError(f"{where}: consecutive_months must be an integer "
                         f"from 1 to {MAX_CONSECUTIVE_MONTHS}")
    return {"consecutive_months": months}


def evaluate_pb_zone(symbol, cutoff, setting, per_history, price):
    """P/B review zone at the evaluation cutoff (a Taipei date).

    setting: {"percentiles": (low, mid, high)}.
    per_history: {"source": url, "rows": FinMind TaiwanStockPER rows} or None.
    price: {"close", "session", "source"} from the price position, or None.
    """
    result = {
        "status": "not_evaluated", "zone": "not_evaluated", "reason": None,
        "method": "historical_pbr_percentile_x_book_value_per_share",
        "cutoff": cutoff.isoformat(), "percentiles": list(setting["percentiles"]),
        "pb_band": None, "review_prices_twd": None, "book_value_per_share": None,
        "pbr_history": None, "price": None, "assumptions": ASSUMPTIONS, "disclaimer": DISCLAIMER,
    }

    def blocked(reason):
        result["reason"] = reason
        return result

    price = price or {}
    close, session = price.get("close"), price.get("session")
    if close is None or isinstance(close, bool) or not math.isfinite(close) or close <= 0 or not session:
        return blocked("Verified close unavailable")
    session = date.fromisoformat(str(session)[:10])
    if session > cutoff:
        return blocked("Close session is after evaluation cutoff")
    result["price"] = {"close": float(close), "session": session.isoformat(),
                       "source": price.get("source")}
    if per_history is None:
        return blocked(f"FinMind {PER_DATASET} unavailable")
    try:
        series = ratio_series(per_history.get("rows") or [], symbol.split(".")[0], cutoff, PBR_FIELD)
    except ValueError as error:
        return blocked(str(error))
    if series:
        result["pbr_history"] = {
            "dataset": PER_DATASET, "field": PBR_FIELD, "source": per_history.get("source"),
            "window_start": per_window_start(cutoff).isoformat(),
            "first_date": series[0][0].isoformat(), "last_date": series[-1][0].isoformat(),
            "samples": len(series), "latest_pbr": series[-1][1],
        }
    if len(series) < MIN_PER_SAMPLES:
        return blocked(f"Only {len(series)} PBR samples in the {WINDOW_YEARS}-year window; "
                       f"need {MIN_PER_SAMPLES}")
    last_day, latest = series[-1]
    if last_day != session:
        return blocked(f"Latest PBR is dated {last_day}, the close {session}; "
                       "book value per share needs both on one day")

    values = np.array([v for _, v in series])
    book_value = float(close) / latest
    band = tuple(round(float(np.percentile(values, q)), 4) for q in setting["percentiles"])
    keys = ("low", "mid", "high")
    prices = {k: round(m * book_value, 2) for k, m in zip(keys, band)}
    result["pbr_history"]["latest_percentile_rank"] = round(float((values <= latest).mean()) * 100, 1)
    result.update(
        status="available",
        pb_band={k: float(m) for k, m in zip(keys, band)},
        book_value_per_share=round(book_value, 2),
        review_prices_twd=prices,
        zone=("below_low" if close < prices["low"] else
              "above_high" if close > prices["high"] else "fair"),
    )
    return result


def evaluate_revenue_momentum(symbol, cutoff, setting, history):
    """Three-month rolling revenue YoY momentum at the evaluation cutoff (a Taipei date).

    setting: {"consecutive_months": N}. The latest N + 1 rolling values are compared;
    every month they need, and the same months a year earlier, must be public.
    history: {"source": url, "rows": FinMind TaiwanStockMonthRevenue rows} or None.
    """
    n = setting["consecutive_months"]
    result = {"status": "not_evaluated", "reason": None, "consecutive_months": n,
              "declining_months": None, "latest_period": None, "latest_published": None,
              "months": [], "dataset": REVENUE_DATASET, "source": (history or {}).get("source"),
              "disclaimer": DISCLAIMER}
    if not history:
        result["reason"] = f"FinMind {REVENUE_DATASET} unavailable"
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
    result["latest_period"] = _label(latest)
    shown = range(latest - n, latest + 1)
    needed = range(shown[0] - ROLLING_MONTHS + 1, latest + 1)
    missing = [_label(k) for k in sorted({*needed, *(k - 12 for k in needed)}) if k not in by_month]
    if missing:
        result["reason"] = "缺月營收：" + "、".join(missing)
        return result
    revenue = {k: by_month[k]["revenue"] for k in by_month}
    rolling = []
    for key in shown:
        this, prior = (sum(revenue[k - i] for i in range(ROLLING_MONTHS)) for k in (key, key - 12))
        if prior <= 0:
            result["reason"] = f"去年同期營收合計小於等於 0：{_label(key - 12)}"
            return result
        rolling.append(this / prior - 1)

    def ratio(a, b):
        return round((a / b - 1) * 100, 2) if b > 0 else None

    result["months"] = [{
        "period": _label(key), "revenue_twd": revenue[key], "prior_year_twd": revenue[key - 12],
        "yoy_pct": ratio(revenue[key], revenue[key - 12]),
        "mom_pct": ratio(revenue[key], revenue[key - 1]),
        "rolling_3m_yoy_pct": round(value * 100, 2), "published": by_month[key]["published"],
    } for key, value in zip(shown, rolling)]
    result["latest_published"] = by_month[latest]["published"]
    declining = 0
    while declining < n and rolling[-1 - declining] < rolling[-2 - declining]:
        declining += 1
    result["declining_months"] = declining
    if rolling[-1] < 0:
        result.update(status="contracting",
                      reason=f"3 個月滾動年增率 {rolling[-1] * 100:+.2f}%，低於 0")
    else:
        result.update(status="slowing" if declining == n else "ok",
                      reason=f"3 個月滾動年增率連續下降 {declining} 個月（門檻 {n}）")
    return result


def _finmind_history(get, url, dataset):
    """({"source", "rows"}, None) or (None, reason); the reason names the failed dataset."""
    try:
        body = get(url)
        if not (isinstance(body, dict) and body.get("status") == 200 and
                isinstance(body.get("data"), list)):
            raise ValueError("invalid_shape")
        return {"source": url, "rows": body["data"]}, None
    except Exception as error:
        return None, f"FinMind {dataset} unavailable: {type(error).__name__}"


def load_industry_watch_rows(groups, now=None, *, provider=None, get=json_get):
    """Price position, P/B zone and revenue momentum per stock; a failure stays in its cell."""
    now = now or datetime.now(timezone.utc)
    cutoff = now.astimezone(TAIPEI).date()
    symbols = [symbol for group in groups for symbol in group["symbols"]]
    positions = {row["symbol"]: row for row in load_price_watch(symbols, now, provider=provider)}
    rows = []
    for group in groups:
        for symbol, name in group["symbols"].items():
            code = symbol.split(".")[0]
            position = {k: v for k, v in positions[symbol].items() if k in POSITION_FIELDS}
            per_history, per_error = _finmind_history(
                get, finmind_per_url(code, per_window_start(cutoff).isoformat()), PER_DATASET)
            failed = position["status"] == "failed"
            zone = evaluate_pb_zone(symbol, cutoff, group["pb_zone"], per_history,
                                    None if failed else position)
            # Name the failed input instead of the generic gap.
            if failed:
                zone["reason"] = f"Verified close unavailable: {position['error_type']}"
            elif per_error:
                zone["reason"] = per_error
            revenue_history, revenue_error = _finmind_history(
                get, finmind_revenue_url(code, revenue_start(cutoff).isoformat()), REVENUE_DATASET)
            rule = (group["overrides"].get(symbol) or {}).get("revenue_momentum") or group["revenue_momentum"]
            momentum = evaluate_revenue_momentum(symbol, cutoff, rule, revenue_history)
            if revenue_error:
                momentum["reason"] = revenue_error
            evaluated = (position["status"] == zone["status"] == "available"
                         and momentum["status"] != "not_evaluated")
            rows.append({"symbol": symbol, "name": name, "group": group["id"],
                         "status": "available" if evaluated else "partial",
                         "price_position": position, "pb_zone": zone,
                         "revenue_momentum": momentum})
    return {"status": "complete" if all(r["status"] == "available" for r in rows) else "partial",
            "cutoff": cutoff.isoformat(),
            "groups": [{"id": g["id"], "name": g["name"], "rationale": g["rationale"],
                        "symbols": list(g["symbols"])} for g in groups],
            "rows": rows}


# ---------------------------------------------------------------- presentation

def _money(value):
    return f"{value:,.2f}" if isinstance(value, (int, float)) else "—"


def _pct(measure):
    return f"{measure['pct']:+.2f}%" if (measure or {}).get("status") == "available" else "not_evaluated"


def industry_summary_row(row):
    """One daily-summary table row: price position, P/B, review prices and zone."""
    position, zone = row["price_position"], row["pb_zone"]
    if position["status"] == "failed":
        close, high, ma = "—", "—", "—"
        notes = f"行情取得失敗：{position['error_type']}：{position['reason']}"
    else:
        close = f"{_money(position['close'])}（{position['session']}）"
        high, ma = _pct(position["drawdown_52w"]), _pct(position["ma_200"])
        notes = price_watch_notes(position)
    history = zone.get("pbr_history") or {}
    pbr = "—"
    if history:
        rank = history.get("latest_percentile_rank")
        pbr = f"{history['latest_pbr']:.2f}" + (f"（P{rank:.0f}）" if rank is not None else "")
    prices = zone.get("review_prices_twd") or {}
    zone_cell = (ZONE_LABELS[zone["zone"]] if zone["status"] == "available"
                 else f"not_evaluated：{zone['reason']}")
    sample = (f"{history['samples']} 筆（{history['first_date']}～{history['last_date']}）"
              if history else "—")
    cells = [f"{row['symbol']} {row['name']}", close, high, ma, pbr,
             *(_money(prices.get(k)) for k in ("low", "mid", "high")), zone_cell, sample, notes]
    return "| " + " | ".join(cells) + " |"


def momentum_summary_row(row):
    """One daily-summary table row: momentum status and the months behind it, oldest first."""
    momentum = row["revenue_momentum"]
    months = momentum["months"]

    def series(field, sep="／"):
        return sep.join("—" if m[field] is None else f"{m[field]:+.1f}%" for m in months) or "—"

    status = MOMENTUM_LABELS[momentum["status"]]
    cells = [f"{row['symbol']} {row['name']}",
             (f"{status}：{momentum['reason']}" if momentum["status"] != "not_evaluated"
              else f"not_evaluated：{momentum['reason']}"),
             f"{months[0]['period']}～{months[-1]['period']}" if months else "—",
             series("yoy_pct"), series("mom_pct"), series("rolling_3m_yoy_pct", " → "),
             (f"{momentum['latest_period']}（{momentum['latest_published'] or '依法定期限'}）"
              if months else "—")]
    return "| " + " | ".join(cells) + " |"


def render_industry_watch_summary(industry):
    """Daily-summary section; empty when no industry-watch group ran."""
    if not industry:
        return []
    lines = [
        "", f"### 產業觀察（{DISCLAIMER}）", "",
        "景氣循環股以股價淨值比（PBR）觀察，不用本益比：獲利高峰時本益比反而最低。"
        f"價位 = 近 {WINDOW_YEARS} 年每日 PBR（FinMind {PER_DATASET}）百分位（預設第 20／50／80）"
        "× 每股淨值（收盤 ÷ 同日 PBR，推導值）；價格位置算法同核心 ETF（TWSE 官方日 K）。"
        f"營收動能 = 3 個月滾動年增率（FinMind {REVENUE_DATASET}，只用截止時已公開的月份）："
        "低於 0 為衰退，連續 N 個月嚴格下降為放緩（預設 N = 3）。"
        "不跑公司研究與論點檢查，設定見 config/watchlist.yaml。",
    ]
    if industry.get("status") == "failed":
        return lines + ["", f"取得失敗：{industry['error_type']}：{industry['reason']}"]
    for group in industry["groups"]:
        rows = [r for r in industry["rows"] if r["group"] == group["id"]]
        lines += ["", f"#### {group['name']}", "", group["rationale"], "",
                  "| 標的 | 收盤（日期） | 距 52 週高點 | 距 200 日均線 | PBR（5 年百分位） "
                  "| 偏低價 | 合理價 | 偏高價 | 目前區間 | PBR 樣本 | 備註 |",
                  "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- | :--- | :--- |"]
        lines += [industry_summary_row(r) for r in rows]
        lines += ["", "| 標的 | 營收動能 | 月份 | 單月年增率 | 月增率 | 3 個月滾動年增率 "
                  "| 最新月份（公開日） |",
                  "| :--- | :--- | :--- | ---: | ---: | ---: | :--- |"]
        lines += [momentum_summary_row(r) for r in rows]
    return lines
