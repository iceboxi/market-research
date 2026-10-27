"""Exchange-aware, fail-closed daily-session freshness validation."""
from datetime import datetime

import exchange_calendars as xcals
import pandas as pd

CALENDARS = {"tw": "XTAI", "us": "XNYS"}
POST_CLOSE_LAG_MINUTES = 60


class StaleMarketData(ValueError):
    pass


def expected_complete_session(market: str, now: datetime, closed_sessions=()):
    if market not in CALENDARS:
        raise ValueError(f"Unsupported market: {market}")
    if now.tzinfo is None:
        raise ValueError("The current timestamp must have a timezone")
    calendar = xcals.get_calendar(CALENDARS[market])
    utc_now = pd.Timestamp(now).tz_convert("UTC")
    local_date = utc_now.tz_convert(calendar.tz).date()
    session = calendar.date_to_session(pd.Timestamp(local_date), direction="previous")
    close = calendar.session_close(session)
    if utc_now < close + pd.Timedelta(minutes=POST_CLOSE_LAG_MINUTES):
        session = calendar.previous_session(session)
    # Exchange-confirmed ad-hoc closures (e.g. typhoon days) that the published
    # calendar still lists as sessions; the caller supplies the evidence.
    closed = {pd.Timestamp(day) for day in closed_sessions}
    while session in closed:
        session = calendar.previous_session(session)
    return session.date()


def require_complete_session(market: str, latest_date, now: datetime,
                             closed_sessions=()) -> dict:
    expected = expected_complete_session(market, now, closed_sessions)
    latest = pd.Timestamp(latest_date).date()
    if latest != expected:
        raise StaleMarketData(
            f"{market}: latest={latest} but latest completed session={expected}. "
            "Refusing to screen stale or unfinished daily data."
        )
    session = {
        "calendar": CALENDARS[market],
        "expected_completed_session": expected.isoformat(),
        "status": "complete",
        "post_close_lag_minutes": POST_CLOSE_LAG_MINUTES,
    }
    if closed_sessions:
        session["unscheduled_closures"] = sorted(
            pd.Timestamp(day).date().isoformat() for day in closed_sessions)
    return session
