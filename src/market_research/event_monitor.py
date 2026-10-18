"""Compact, reproducible event-monitor snapshots and source-safe change detection.

Stores only official event identifiers, not headlines or unverified sentiment.
Missing/partial feeds never become 'no news' and never erase previous history.
"""
from datetime import datetime, timezone
import re

SCHEMA_VERSION = 1
MAX_IDS = 2000
MARKETS = {"tw", "us"}


def _timestamp(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("Timestamp requires timezone")
    return dt.astimezone(timezone.utc)


def _ids(items):
    ids = []
    for row in items:
        if not isinstance(row, dict):
            raise ValueError("Malformed official event")
        value = row.get("event_id")
        if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9-]{3,100}", value):
            raise ValueError("Unsafe official event identifier")
        ids.append(value)
    return sorted(set(ids))


def build_snapshot(symbol, market, feed, now):
    if now.tzinfo is None:
        raise ValueError("Now must contain timezone")
    if market not in MARKETS:
        raise ValueError("Unknown market")
    if market == "tw" and not re.fullmatch(r"[0-9]{4,6}\.TW", symbol):
        raise ValueError("Invalid TW symbol")
    if market == "us" and not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", symbol):
        raise ValueError("Invalid US symbol")
    if feed.get("status") != "available":
        return None
    if feed.get("coverage") in (None, "not_verified"):
        return None
    ids = _ids(feed.get("events", []))
    return {
        "schema_version": SCHEMA_VERSION,
        "market": market, "symbol": symbol,
        "observed_at_utc": now.astimezone(timezone.utc).isoformat(),
        "source": feed["source"], "coverage": feed["coverage"],
        "seen_ids": ids,
    }


def compare_snapshots(previous, current):
    """Return a safe receipt and proposed merged state (or no update)."""
    if current is None:
        return {
            "status": "coverage_unknown", "new_event_ids": [],
            "notify": False, "reason": "Source coverage incomplete; retained prior state",
        }, None
    if previous is None:
        return {
            "status": "baseline_initialized", "new_event_ids": [],
            "notify": False, "reason": "Initial state cannot distinguish historic and newly observed events",
        }, current
    if not isinstance(previous, dict) or any(
        previous.get(k) != current.get(k) for k in
        ("schema_version", "market", "symbol", "source", "coverage")
    ):
        return {
            "status": "state_incompatible", "new_event_ids": [],
            "notify": False, "reason": "Source/state contract changed; manual migration required",
        }, None
    try:
        if _timestamp(current["observed_at_utc"]) < _timestamp(previous["observed_at_utc"]):
            raise ValueError("Out-of-order snapshot")
        old = previous["seen_ids"]
        if (not isinstance(old, list) or
                any(not isinstance(k, str) for k in old) or
                len(old) != len(set(old)) or len(old) > MAX_IDS):
            raise ValueError("Invalid previous event ID collection")
        new = [k for k in current["seen_ids"] if k not in set(old)]
    except (KeyError, TypeError, ValueError):
        return {
            "status": "state_incompatible", "new_event_ids": [],
            "notify": False, "reason": "Invalid or out-of-order previous snapshot",
        }, None
    combined = list(dict.fromkeys(old + current["seen_ids"]))[-MAX_IDS:]
    merged = {**current, "seen_ids": combined}
    return {
        "status": "changed" if new else "unchanged",
        "new_event_ids": new, "notify": bool(new),
        "reason": "New official event IDs require review" if new else "No new observed IDs within limited coverage",
    }, merged
