"""Core ETF and benchmark price watch (#113): display only.

For the TWSE ETFs and the TAIEX benchmark: latest close, drawdown from the
52-week high and distance from the 200-session simple moving average. Nothing
here produces a signal, alert or allocation.

TWSE prices are unadjusted. Where TWSE publishes a reference price that differs
from the previous close (a split or reverse split), earlier bars are scaled by
reference / previous close so one series stays comparable. 'X' (不比價) days,
e.g. ex-dividend days, publish no reference: they stay unadjusted and are
listed, and a gap on such a day too large for a distribution makes the
measures whose window contains it not_evaluated. A source with no reference
on any day (TPEx via FinMind, #144) has every day treated that way and is
labelled once instead of listing each day.
"""
from datetime import datetime, timedelta, timezone
import math

import exchange_calendars as xcals
import pandas as pd

from .market_data import load_daily_bars
from .twse import TAIEX

WINDOW_WEEKS = 52
MA_SESSIONS = 200
# 13 TWSE months: always reaches back past 52 weeks and 200 sessions.
PERIOD = "1y"
TIMEZONE = "Asia/Taipei"
# One day's move on an unadjusted 'X' day beyond this ratio is a split, not a payout.
MAX_UNADJUSTED_DAY_RATIO = 1.5
# Reference and previous close are both published to the cent.
REFERENCE_TOLERANCE = 0.005
DISCLAIMER = "僅顯示價格位置，非訊號或買賣建議"
NAMES = {TAIEX: "發行量加權股價指數", "0050.TW": "元大台灣50", "00631L.TW": "元大台灣50正2"}
NOTES = {"00631L.TW": "每日 2 倍槓桿，盤整時有波動侵蝕"}
SOURCE_LABELS = {
    "twse_stock_day_official_raw_ohlcv": "TWSE STOCK_DAY",
    "twse_mi_5mins_hist_index_with_fmtqik_volume": "TWSE MI_5MINS_HIST＋FMTQIK",
    "finmind_taiwan_stock_price_raw_ohlcv": "FinMind TaiwanStockPrice",
}


def _not_evaluated(reason):
    return {"status": "not_evaluated", "reason": reason}


def _row(symbol, **fields):
    return {"symbol": symbol, "name": NAMES.get(symbol),
            "kind": "index" if symbol == TAIEX else "etf",
            "note": NOTES.get(symbol), **fields}


def _reference_scale(frame):
    """Per-row price scale from published reference breaks, plus the evidence."""
    if "reference_price" not in frame:
        raise ValueError("無 TWSE 參考價，無法確認分割等價格斷層")
    dates = [pd.Timestamp(d).date() for d in frame.index]
    close = frame["close"].astype(float).to_numpy()
    reference = frame["reference_price"].astype(float).to_numpy()
    factors = [1.0] * len(dates)
    breaks, unadjusted, gaps = [], [], []
    for i in range(1, len(dates)):
        previous = close[i - 1]
        if math.isnan(reference[i]):
            unadjusted.append(dates[i])
            ratio = close[i] / previous
            if max(ratio, 1 / ratio) > MAX_UNADJUSTED_DAY_RATIO:
                gaps.append(dates[i])
        elif abs(reference[i] - previous) > REFERENCE_TOLERANCE:
            factors[i] = reference[i] / previous
            breaks.append({"date": dates[i].isoformat(), "previous_close": round(previous, 4),
                           "reference_price": round(reference[i], 4),
                           "factor": round(factors[i], 6)})
    # A break on day i rescales every earlier day.
    scale, running = [1.0] * len(dates), 1.0
    for i in range(len(dates) - 1, -1, -1):
        scale[i] = running
        running *= factors[i]
    return pd.Series(scale, index=frame.index), breaks, unadjusted, gaps


def _covers(first, window_start):
    """True when no XTAI session falls between the window start and the first bar."""
    if first <= window_start:
        return True
    calendar = xcals.get_calendar("XTAI")
    return len(calendar.sessions_in_range(pd.Timestamp(window_start),
                                          pd.Timestamp(first - timedelta(days=1)))) == 0


def _gap_in(gaps, start, label="不比價日"):
    inside = [d.isoformat() for d in gaps if d > start]
    return _not_evaluated(f"{label}價格斷層無法還原：{', '.join(inside)}") if inside else None


def evaluate_price_watch(symbol, frame, *, source):
    """Close, 52-week-high drawdown and 200-session MA distance from completed bars."""
    dates = [pd.Timestamp(d).date() for d in frame.index]
    last, first = dates[-1], dates[0]
    close = float(frame["close"].iloc[-1])
    row = _row(symbol, status="available", source=source, session=last.isoformat(),
               first_date=first.isoformat(), close=round(close, 4))
    try:
        scale, breaks, unadjusted, gaps = _reference_scale(frame)
    except ValueError as error:
        row.update(status="partial", drawdown_52w=_not_evaluated(str(error)),
                   ma_200=_not_evaluated(str(error)))
        return row
    # Every day lacks a reference: each is an 'X' day, and the gap names why.
    no_reference = bool(frame["reference_price"].isna().iloc[1:].all()) and len(dates) > 1
    label = "無參考價，" if no_reference else "不比價日"
    window_start = last - timedelta(weeks=WINDOW_WEEKS)
    if not _covers(first, window_start):
        drawdown = _not_evaluated(f"資料不足 52 週（最早 {first}，需要 {window_start}）")
    else:
        drawdown = _gap_in(gaps, window_start, label)
    if drawdown is None:
        in_window = [d >= window_start for d in dates]
        highs = (frame["high"].astype(float) * scale)[in_window]
        high = float(highs.max())
        drawdown = {"status": "available", "pct": round((close / high - 1) * 100, 2),
                    "high": round(high, 4),
                    "high_date": pd.Timestamp(highs.idxmax()).date().isoformat(),
                    "window_start": window_start.isoformat()}
    relevant = window_start
    if len(dates) < MA_SESSIONS:
        ma = _not_evaluated(f"只有 {len(dates)} 個交易日，需要 {MA_SESSIONS}")
    else:
        ma_first = dates[-MA_SESSIONS]
        relevant = min(relevant, ma_first)
        ma = _gap_in(gaps, ma_first, label)
        if ma is None:
            average = float((frame["close"].astype(float) * scale).iloc[-MA_SESSIONS:].mean())
            ma = {"status": "available", "pct": round((close / average - 1) * 100, 2),
                  "average": round(average, 4), "first_date": ma_first.isoformat(),
                  "sessions": MA_SESSIONS}
    adjustments = {
        "reference_breaks": [b for b in breaks if b["date"] > relevant.isoformat()],
        "unadjusted_dates": [d.isoformat() for d in unadjusted if d > relevant]}
    if no_reference:
        adjustments.update(unadjusted_dates=[], no_reference_price=True)
    row.update(drawdown_52w=drawdown, ma_200=ma, adjustments=adjustments)
    if "not_evaluated" in (drawdown["status"], ma["status"]):
        row["status"] = "partial"
    return row


def load_price_watch(symbols, now=None, *, provider=None):
    """Price-watch rows from the latest completed TWSE session (strict freshness)."""
    from .provider import RoutedDailyProvider
    provider = provider or RoutedDailyProvider()
    now = now or datetime.now(timezone.utc)
    check = getattr(provider, "unscheduled_closures", None)
    closed = tuple(check("tw", now)) if check else ()
    rows = []
    for symbol in symbols:
        try:
            daily = load_daily_bars(provider, "tw", symbol, PERIOD, now, TIMEZONE,
                                    strict_freshness=True, closed_sessions=closed)
            rows.append(evaluate_price_watch(symbol, daily.frame, source=daily.metadata["source"]))
        except Exception as error:
            rows.append(_row(symbol, status="failed", error_type=type(error).__name__,
                             reason=str(error)))
    return rows


# ---------------------------------------------------------------- presentation

def _pct(measure):
    return f"{measure['pct']:+.2f}%" if measure.get("status") == "available" else "not_evaluated"


def _value(value):
    return f"{value:,.2f}" if isinstance(value, (int, float)) else "—"


def price_watch_notes(row):
    notes = [row["note"]] if row.get("note") else []
    adjustments = row.get("adjustments") or {}
    for brk in adjustments.get("reference_breaks") or []:
        notes.append(f"{brk['date']} 依 TWSE 參考價還原（×{brk['factor']:g}）")
    if adjustments.get("no_reference_price"):
        notes.append("無參考價，未還原（每日比照不比價日）")
    if adjustments.get("unadjusted_dates"):
        notes.append("不比價日未還原（如除息）：" + "、".join(adjustments["unadjusted_dates"]))
    for key in ("drawdown_52w", "ma_200"):
        if (row.get(key) or {}).get("status") == "not_evaluated":
            notes.append(row[key]["reason"])
    return "；".join(notes) or "—"


def price_watch_summary_row(row):
    """One daily-summary table row."""
    label = f"{row['symbol']} {row['name']}" if row.get("name") else row["symbol"]
    if row["status"] == "failed":
        return f"| {label} | — | 取得失敗 | — | — | — | {row['error_type']}：{row['reason']} |"
    high, ma = row["drawdown_52w"], row["ma_200"]
    high_cell = (f"{_value(high['high'])}（{high['high_date']}）"
                 if high["status"] == "available" else "—")
    ma_cell = _value(ma["average"]) if ma["status"] == "available" else "—"
    return (f"| {label} | {_value(row['close'])}（{row['session']}） | {_pct(high)} | {high_cell} | "
            f"{_pct(ma)} | {ma_cell} | {price_watch_notes(row)} |")


def render_price_watch_summary(rows):
    """Daily-summary section; empty when no row was requested."""
    if not rows:
        return []
    return [
        "", f"### 核心 ETF 與加權指數（{DISCLAIMER}）", "",
        f"距高點 = 收盤 ÷ 近 {WINDOW_WEEKS} 週最高價 − 1；距均線 = 收盤 ÷ 近 {MA_SESSIONS} "
        "個交易日收盤平均 − 1。來源為 TWSE 官方日 K；分割等依 TWSE 參考價還原，除息未還原。", "",
        "| 標的 | 收盤（日期） | 距 52 週高點 | 52 週高點（日期） | 距 200 日均線 | 200 日均線 | 備註 |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | :--- |",
        *(price_watch_summary_row(row) for row in rows),
    ]
