"""Prediction review (#183): when each ledger prediction starts, when it is due, and its status.

A prediction starts at the latest completed TWSE session when it first appeared on main (First
seen), so nothing written after the fact can count. A due price prediction is judged from
official daily bars: the check session is the horizon-th bar after the start, so a closed day
never counts. Missing bars or a failed source leave it not_evaluated, never a miss. Nothing here
writes to the repository: every status is derived again from the ledger, its git history and
prices on each run.
"""
from __future__ import annotations

from datetime import date, datetime

import exchange_calendars as xcals
import pandas as pd

from .market_calendar import expected_complete_session
# Same split handling as the core-ETF price watch; shared within the package.
from .price_watch import MAX_UNADJUSTED_DAY_RATIO, _reference_scale as reference_scale

STATUS_LABELS = {"pending": "未到期", "withdrawn": "已撤回", "void": "作廢", "hit": "命中",
                 "miss": "未命中", "not_evaluated": "未評估", "awaiting_review": "待人工判定"}
VOID_REASONS = {"late_entry": "事件發生後才合併"}
SYMBOL_NAMES = {"TAIEX": "加權指數"}
TRIGGER_LABELS = {"weekly": "週預測", "event": "事件預測", "inference": "推論轉預測"}


def start_session(first_seen: datetime, closed_sessions=()):
    """Latest completed TW session at First seen (close + 60 minutes, as the pipeline uses)."""
    return expected_complete_session("tw", first_seen, closed_sessions)


def expected_check_session(start, horizon: int):
    """The horizon-th XTAI session after start; None when beyond the published calendar."""
    calendar = xcals.get_calendar("XTAI")
    try:
        window = calendar.sessions_window(pd.Timestamp(start), horizon + 1)
    except ValueError:  # RequestedSessionOutOfBounds: the calendar is published about a year ahead
        return None
    return window[-1].date()


def _number(value):
    return f"{value:,.2f}" if isinstance(value, float) and not value.is_integer() else f"{value:,}"


def _held_price(claim):
    return "收盤" if claim["basis"] == "close" else ("最低價" if claim["op"] == ">" else "最高價")


def claim_text(claim: dict, horizon: int) -> str:
    """One readable line for the condition, in the knowledge base's wording."""
    if claim["kind"] == "manual":
        return claim["text"]
    name = SYMBOL_NAMES.get(claim["symbol"], claim["symbol"])
    op = claim["op"]
    if claim["kind"] == "return":
        return f"{name} {horizon} 個交易日報酬 {op} {claim['threshold_pct']:g}%"
    level = _number(claim["level"])
    if claim["kind"] == "close_at_check":
        return f"{name} 第 {horizon} 個交易日收盤 {op} {level}"
    return f"{name} {horizon} 個交易日內每天{_held_price(claim)} {op} {level}"


# ---------------------------------------------------------------- judging

def _start_basis(frame, start_bar, check):
    """Prices on the start session's basis, or a reason they cannot be compared.

    TWSE reference breaks (splits) are undone as the price watch does; a large unexplained gap
    inside the window, or any such gap where the source has no reference price, is not judged.
    """
    dates = [pd.Timestamp(d).date() for d in frame.index]
    try:
        scale, _, _, gaps = reference_scale(frame)
    except ValueError:  # no reference price (TPEx via FinMind): compare raw, refuse split-sized gaps
        close = frame["close"].astype(float).to_numpy()
        gaps = [dates[i] for i in range(1, len(dates))
                if max(close[i] / close[i - 1], close[i - 1] / close[i]) > MAX_UNADJUSTED_DAY_RATIO]
        scale = pd.Series(1.0, index=frame.index)
    inside = [d.isoformat() for d in gaps if start_bar < d <= check]
    if inside:
        return None, f"價格斷層無法還原：{', '.join(inside)}"
    factor = scale / float(scale.iloc[dates.index(start_bar)])
    prices = frame[["open", "high", "low", "close"]].astype(float).mul(factor, axis=0)
    prices.index = dates
    return prices, None


def judge(claim: dict, horizon: int, start, frame: pd.DataFrame, latest) -> dict:
    """Status and evidence for one due price claim from official daily bars."""
    dates = [pd.Timestamp(d).date() for d in frame.index]
    before = [d for d in dates if d <= start]
    if not before:
        return {"status": "not_evaluated", "reason": f"缺起算日 {start} 以前的行情"}
    start_bar = before[-1]  # a closed start day falls back to the session before it
    after = [d for d in dates if start_bar < d <= latest]
    if len(after) < horizon:
        if dates[-1] >= latest:
            return {"status": "pending", "reason": f"休市使檢查日延後（已有 {len(after)}／{horizon} 個交易日）"}
        return {"status": "not_evaluated", "reason": f"缺 {latest} 以前的行情（最新 {dates[-1]}）"}
    window = after[:horizon]
    check = window[-1]
    prices, reason = _start_basis(frame, start_bar, check)
    if reason:
        return {"status": "not_evaluated", "reason": reason}
    start_close, check_close = float(prices.loc[start_bar, "close"]), float(prices.loc[check, "close"])
    detail = {"start_bar": start_bar.isoformat(), "start_close": round(start_close, 4),
              "check_session": check.isoformat(), "check_close": round(check_close, 4)}
    above = claim["op"] == ">"
    if claim["kind"] == "return":
        pct = (check_close / start_close - 1) * 100
        detail["return_pct"] = round(pct, 4)
        hit = pct > claim["threshold_pct"] if above else pct < claim["threshold_pct"]
    elif claim["kind"] == "close_at_check":
        hit = check_close > claim["level"] if above else check_close < claim["level"]
    else:
        column = "close" if claim["basis"] == "close" else ("low" if above else "high")
        series = prices.loc[window, column]
        session = series.idxmin() if above else series.idxmax()
        extreme = float(series.loc[session])
        detail.update(extreme=round(extreme, 4), extreme_session=session.isoformat())
        hit = extreme > claim["level"] if above else extreme < claim["level"]
    return {"status": "hit" if hit else "miss", **detail}


def result_text(record: dict) -> str:
    """The evidence behind a status, for the Issue body and comments."""
    if record["status"] not in ("hit", "miss") or "check_close" not in record:
        return record.get("reason") or ""
    claim = record["claim"]
    if claim["kind"] == "return":
        text = f"報酬 {record['return_pct']:+.2f}%"
    elif claim["kind"] == "held":
        price = "收盤" if claim["basis"] == "close" else "價"
        text = f"期間{'最低' if claim['op'] == '>' else '最高'}{price} {record['extreme']:,.2f}（{record['extreme_session']}）"
    else:
        text = f"檢查日收盤 {record['check_close']:,.2f}"
    return (f"{text}；{record['start_bar']} 收 {record['start_close']:,.2f} → "
            f"{record['check_session']} 收 {record['check_close']:,.2f}")


# ---------------------------------------------------------------- evaluation

def evaluate(entries: list[dict], history: dict, now: datetime, bars_fn=None,
             closed_sessions=()) -> list[dict]:
    """One record per ledger entry: First seen, start, check session and status.

    `history` maps an id to {"first_seen": aware datetime} from main's git history; an id missing
    from it has not reached main yet and stays pending without a start. `bars_fn(symbol, since)`
    returns official daily bars from `since`; it is called only for due price predictions, once
    per symbol, and a raised error leaves those predictions not_evaluated.
    """
    latest = expected_complete_session("tw", now, closed_sessions)
    records, due = [], []
    for entry in entries:
        pid, horizon = entry["id"], entry["horizon_sessions"]
        seen = (history.get(pid) or {}).get("first_seen")
        record = {
            "id": pid, "trigger": entry["trigger"], "method": entry["method"],
            "method_version": entry.get("method_version"), "claim": entry["claim"],
            "condition": claim_text(entry["claim"], horizon), "probability": entry["probability"],
            "horizon_sessions": horizon, "first_seen": seen.isoformat() if seen else None,
            "start_session": None, "expected_check_session": None, "status": "pending",
            "reason": None,
        }
        records.append(record)
        if seen is None:
            record["reason"] = "尚未合併到 main"
            continue
        start = start_session(seen)
        check = expected_check_session(start, horizon)
        record.update(start_session=start.isoformat(),
                      expected_check_session=check.isoformat() if check else None)
        if entry["trigger"] == "event" and seen > datetime.fromisoformat(str(entry["event_time"])):
            record.update(status="void", void_reason="late_entry", reason=VOID_REASONS["late_entry"])
        elif "withdrawn" in entry:
            withdrawn = entry["withdrawn"]
            record.update(status="withdrawn", reason=f"{withdrawn['date']} 撤回：{withdrawn['reason']}")
        elif entry["claim"]["kind"] == "manual":
            outcome = (entry.get("review") or {}).get("outcome")
            if outcome:
                record.update(status=outcome, reason=f"人工判定（{entry['review']['date']}）")
            elif check is not None and latest >= check:
                record.update(status="awaiting_review", reason="已到期，請在回顧寫 review.outcome")
        elif check is None:
            record["reason"] = "檢查日超出交易所行事曆，之後再推算"
        elif latest >= check:
            due.append((record, start))
    frames = {}
    for record, start in due:
        symbol = record["claim"]["symbol"]
        if symbol not in frames:
            since = min(s for r, s in due if r["claim"]["symbol"] == symbol)
            try:
                if bars_fn is None:
                    raise RuntimeError("沒有行情來源")
                frames[symbol] = bars_fn(symbol, since)
            except Exception as error:  # one symbol's source failure never blocks the others
                frames[symbol] = error
        frame = frames[symbol]
        if isinstance(frame, Exception):
            record.update(status="not_evaluated", reason=f"行情取得失敗：{type(frame).__name__}：{frame}")
            continue
        record.update(judge(record["claim"], record["horizon_sessions"], start, frame, latest))
    return records
