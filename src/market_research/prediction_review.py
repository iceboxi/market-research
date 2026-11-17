"""Prediction review (#183): when each ledger prediction starts, when it is due, and its status.

A prediction starts at the latest completed TWSE session when it first appeared on main (First
seen), so nothing written after the fact can count. Nothing here writes to the repository: every
status is derived again from the ledger, its git history and prices on each run.
"""
from __future__ import annotations

from datetime import datetime

import exchange_calendars as xcals
import pandas as pd

from .market_calendar import expected_complete_session

STATUS_LABELS = {"pending": "未到期", "withdrawn": "已撤回", "void": "作廢"}
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
    price = "收盤" if claim["basis"] == "close" else ("最低價" if op == ">" else "最高價")
    return f"{name} {horizon} 個交易日內每天{price} {op} {level}"


def evaluate(entries: list[dict], history: dict, now: datetime) -> list[dict]:
    """One record per ledger entry: First seen, start, expected check session and status.

    `history` maps an id to {"first_seen": aware datetime} from main's git history. An id
    missing from it has not reached main yet and stays pending without a start.
    """
    records = []
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
        if seen is None:
            record["reason"] = "尚未合併到 main"
            records.append(record)
            continue
        start = start_session(seen)
        check = expected_check_session(start, horizon)
        record.update(start_session=start.isoformat(),
                      expected_check_session=check.isoformat() if check else None)
        if check is None:
            record["reason"] = "檢查日超出交易所行事曆，之後再推算"
        if entry["trigger"] == "event" and seen > datetime.fromisoformat(str(entry["event_time"])):
            record.update(status="void", void_reason="late_entry", reason=VOID_REASONS["late_entry"])
        elif "withdrawn" in entry:
            withdrawn = entry["withdrawn"]
            record.update(status="withdrawn", reason=f"{withdrawn['date']} 撤回：{withdrawn['reason']}")
        records.append(record)
    return records
