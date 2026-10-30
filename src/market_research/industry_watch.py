"""Industry watch (#141, #142): price position and a P/B review zone, no company research.

Industry-watch groups sit beside the satellites and the core ETFs. Their stocks are
never scanned or researched. Each daily TW run gives every stock the core-ETF price
position (close, 52-week drawdown, 200-session moving average) and a review zone: the
stock's own five-year daily P/B percentiles times the book value per share implied by
the latest close and the P/B of the same day. Cyclical makers earn most when their P/E
is lowest, so the zone uses P/B, not P/E. A review zone asks a person to look again; it
is not a fair value, target, entry or exit price.
"""
from datetime import date, datetime, timezone
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import yaml

from .fundamentals import finmind_per_url, json_get
from .price_watch import load_price_watch, price_watch_notes
from .valuation_zone import (
    DEFAULT_PERCENTILES, DISCLAIMER, MIN_PER_SAMPLES, PER_DATASET, WINDOW_YEARS, ZONE_LABELS,
    _increasing_triple, load_watchlist, per_window_start, ratio_series,
)

TAIPEI = ZoneInfo("Asia/Taipei")
PBR_FIELD = "PBR"
SUFFIXES = (".TW",)
GROUP_KEYS = {"name", "rationale", "symbols", "pb_zone"}
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
        symbols = entry.get("symbols")
        if not isinstance(symbols, dict) or not symbols:
            raise ValueError(f"{where}: symbols must map codes to company names")
        for symbol, name in symbols.items():
            code, dot, suffix = str(symbol).partition(".")
            if not dot or "." + suffix not in SUFFIXES or not code.isalnum():
                raise ValueError(f"{where} {symbol}: stock codes end in " + " or ".join(SUFFIXES))
            if code.startswith("00"):
                raise ValueError(f"{where} {symbol}: ETF/ETN codes are price-only, not industry watch")
            if symbol in scanned or symbol in satellites:
                raise ValueError(f"{where} {symbol}: already scanned in markets.yaml or a satellite")
            if symbol in seen:
                raise ValueError(f"{where} {symbol}: listed in more than one group")
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"{where} {symbol}: company name must be text")
            seen.add(symbol)
        zone = entry.get("pb_zone") or {}
        if not isinstance(zone, dict) or set(zone) - {"percentiles"}:
            raise ValueError(f"{where}: unknown pb_zone keys")
        percentiles = _increasing_triple(zone.get("percentiles", list(DEFAULT_PERCENTILES)),
                                         group_id, "percentiles")
        if not (0 < percentiles[0] and percentiles[2] < 100):
            raise ValueError(f"{where}: percentiles must be between 0 and 100")
        groups.append({"id": group_id, "name": entry["name"].strip(),
                       "rationale": entry["rationale"].strip(),
                       "symbols": {s: n.strip() for s, n in symbols.items()},
                       "pb_zone": {"percentiles": tuple(percentiles)}})
    return groups


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


def load_industry_watch_rows(groups, now=None, *, provider=None, per_get=json_get):
    """Price position and P/B zone for every industry-watch stock; a failure stays in its row."""
    now = now or datetime.now(timezone.utc)
    cutoff = now.astimezone(TAIPEI).date()
    symbols = [symbol for group in groups for symbol in group["symbols"]]
    positions = {row["symbol"]: row for row in load_price_watch(symbols, now, provider=provider)}
    rows = []
    for group in groups:
        for symbol, name in group["symbols"].items():
            position = {k: v for k, v in positions[symbol].items() if k in POSITION_FIELDS}
            url = finmind_per_url(symbol.split(".")[0], per_window_start(cutoff).isoformat())
            per_history, per_error = None, None
            try:
                body = per_get(url)
                if not (isinstance(body, dict) and body.get("status") == 200 and
                        isinstance(body.get("data"), list)):
                    raise ValueError("invalid_shape")
                per_history = {"source": url, "rows": body["data"]}
            except Exception as error:
                per_error = f"FinMind {PER_DATASET} unavailable: {type(error).__name__}"
            failed = position["status"] == "failed"
            zone = evaluate_pb_zone(symbol, cutoff, group["pb_zone"], per_history,
                                    None if failed else position)
            # Name the failed input instead of the generic gap.
            if failed:
                zone["reason"] = f"Verified close unavailable: {position['error_type']}"
            elif per_error:
                zone["reason"] = per_error
            rows.append({"symbol": symbol, "name": name, "group": group["id"],
                         "status": ("available" if position["status"] == zone["status"] == "available"
                                    else "partial"),
                         "price_position": position, "pb_zone": zone})
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


def render_industry_watch_summary(industry):
    """Daily-summary section; empty when no industry-watch group ran."""
    if not industry:
        return []
    lines = [
        "", f"### 產業觀察（{DISCLAIMER}）", "",
        "景氣循環股以股價淨值比（PBR）觀察，不用本益比：獲利高峰時本益比反而最低。"
        f"價位 = 近 {WINDOW_YEARS} 年每日 PBR（FinMind {PER_DATASET}）百分位（預設第 20／50／80）"
        "× 每股淨值（收盤 ÷ 同日 PBR，推導值）；價格位置算法同核心 ETF（TWSE 官方日 K）。"
        "不跑公司研究與論點檢查，設定見 config/watchlist.yaml。",
    ]
    if industry.get("status") == "failed":
        return lines + ["", f"取得失敗：{industry['error_type']}：{industry['reason']}"]
    for group in industry["groups"]:
        lines += ["", f"#### {group['name']}", "", group["rationale"], "",
                  "| 標的 | 收盤（日期） | 距 52 週高點 | 距 200 日均線 | PBR（5 年百分位） "
                  "| 偏低價 | 合理價 | 偏高價 | 目前區間 | PBR 樣本 | 備註 |",
                  "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- | :--- | :--- |"]
        lines += [industry_summary_row(r) for r in industry["rows"] if r["group"] == group["id"]]
    return lines
