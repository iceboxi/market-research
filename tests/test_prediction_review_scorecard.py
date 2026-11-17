"""#183 PL5: base rates from the 5 years before the start, and the Brier scorecard."""
from datetime import date, datetime

import exchange_calendars as xcals
import pandas as pd
import pytest

from market_research.prediction_review import base_rate, brier, scorecard
from scripts.prediction_review import sync
from tests.test_prediction_review import FakeSink
from tests.test_prediction_review_results import UP_WEEK, WEEKLY, bars

START = date(2026, 11, 17)
CUTOFF = date(2021, 11, 17)
CALENDAR = xcals.get_calendar("XTAI")


def history(closes_fn, first="2021-11-01", last="2026-11-17", lows_fn=None):
    """Daily bars on every XTAI session, closes from a function of the position."""
    sessions = CALENDAR.sessions_in_range(pd.Timestamp(first), pd.Timestamp(last))
    closes = [float(closes_fn(i)) for i in range(len(sessions))]
    lows = [float(lows_fn(i)) if lows_fn else c * 0.99 for i, c in enumerate(closes)]
    return pd.DataFrame({"open": closes, "high": [c * 1.01 for c in closes], "low": lows, "close": closes,
                         "volume": 1, "reference_price": [closes[0], *closes[:-1]]}, index=sessions)


def windows(horizon):
    """Independent count: sessions from the cutoff whose window ends by the start."""
    sessions = [s.date() for s in CALENDAR.sessions_in_range(pd.Timestamp(CUTOFF), pd.Timestamp(START))]
    return len(sessions) - horizon


UP = {"kind": "return", "symbol": "TAIEX", "op": ">", "threshold_pct": 0}


def test_rising_history_has_base_rate_one():
    rate = base_rate(UP, 5, START, history(lambda i: 100 + i))
    assert (rate["status"], rate["rate"], rate["windows"]) == ("available", 1.0, windows(5))
    assert type(rate["rate"]) is float and type(rate["windows"]) is int  # plain JSON values for the state
    assert (rate["from"], rate["to"]) == ("2021-11-17", "2026-11-17")


def test_every_fourth_session_down_gives_three_quarters_for_one_day():
    # Up, up, up, down, repeating: three of every four one-day returns are positive.
    frame = history(lambda i: 1000 + i // 4 + (1, 2, 3, 0.5)[i % 4])
    returns = frame["close"].pct_change()
    # Oracle: positive next-day returns over windows that start on or after the cutoff.
    starts = [i for i, d in enumerate(frame.index) if d.date() >= CUTOFF and i + 1 <= len(frame) - 1]
    expected = sum(1 for i in starts if returns.iloc[i + 1] > 0) / len(starts)
    rate = base_rate(UP, 1, START, frame)
    assert rate["rate"] == pytest.approx(round(expected, 4))
    assert 0.7 < rate["rate"] < 0.8


def test_bars_after_the_start_never_change_the_base_rate():
    frame = history(lambda i: 100 + i)
    future = history(lambda i: 5000 - 50 * i, first="2026-11-18", last="2026-12-31")
    with_future = pd.concat([frame, future])
    assert base_rate(UP, 5, START, with_future) == base_rate(UP, 5, START, frame)


def test_level_claims_use_the_return_relative_to_the_start_close():
    frame = history(lambda i: 100 + i)  # start close = 100 + last index
    start_close = float(frame["close"].iloc[-1])
    below = {"kind": "close_at_check", "symbol": "TAIEX", "op": "<", "level": start_close * 1.0001}
    # Relative threshold +0.01%: every 11-session rise is far larger, so none is below.
    assert base_rate(below, 11, START, frame)["rate"] == 0.0


def test_held_uses_the_window_extreme():
    # Lows dip 3% below the close on every tenth session.
    frame = history(lambda i: 1000.0, lows_fn=lambda i: 970.0 if i % 10 == 0 else 999.0)
    held = {"kind": "held", "symbol": "TAIEX", "op": ">", "level": 980.0, "basis": "intraday"}  # −2% of start
    rate = base_rate(held, 10, START, frame)
    assert rate["rate"] == 0.0  # every 10-session window contains a 970 low
    rate = base_rate({**held, "level": 960.0}, 10, START, frame)
    assert rate["rate"] == 1.0


def test_short_history_is_not_evaluated():
    rate = base_rate(UP, 5, START, history(lambda i: 100 + i, first="2023-01-02"))
    assert rate["status"] == "not_evaluated" and rate["retry"] is False
    assert rate["reason"] == "歷史不足 5 年（最早 2023-01-03，需要 2021-11-17）"


def test_brier_values():
    assert brier(0.55, True) == pytest.approx(0.2025)
    assert brier(0.75, False) == pytest.approx(0.5625)


def record(pid, status, probability, method="judgment", version=None, base=None):
    return {"id": pid, "status": status, "probability": probability, "method": method,
            "method_version": version,
            "base_rate": {"status": "available", "rate": base} if base is not None else None}


def test_scorecard_rows():
    rows = scorecard([
        record("a", "hit", 0.55, base=0.5), record("b", "miss", 0.75, base=0.8),
        record("c", "hit", 0.6, method="forced-selling", version="2026-11-12"),  # manual, no base
        record("d", "pending", 0.9), record("e", "void", 0.9), record("f", "not_evaluated", 0.9),
    ])
    overall, judgment, forced = rows
    assert overall["label"] == "全部" and overall["judged"] == 3 and overall["with_base"] == 2
    assert overall["hit_rate"] == pytest.approx(2 / 3)
    assert overall["mean_probability"] == pytest.approx((0.55 + 0.75 + 0.6) / 3)
    assert overall["brier"] == pytest.approx((0.2025 + 0.5625 + 0.16) / 3)
    assert overall["brier_with_base"] == pytest.approx((0.2025 + 0.5625) / 2)
    assert overall["base_brier"] == pytest.approx((0.25 + 0.64) / 2)
    assert (judgment["label"], judgment["judged"]) == ("judgment", 2)
    assert (forced["label"], forced["judged"], forced["base_brier"]) == ("forced-selling 2026-11-12", 1, None)


SEEN = {"first_seen": datetime.fromisoformat("2026-11-18T00:03:59+08:00")}


def run(sink, now, run_id, history_fn):
    return sync(sink, [WEEKLY], {WEEKLY["id"]: SEEN}, now, run_id=run_id,
                run_url=f"https://example.invalid/run/{run_id}",
                bars_fn=lambda symbol, since: bars(UP_WEEK), history_fn=history_fn)


def test_base_rate_is_shown_cached_and_fetched_once():
    calls = []

    def history_fn(symbol, since):
        calls.append((symbol, since))
        return pd.concat([history(lambda i: 100 + i, last="2026-11-16"), bars(UP_WEEK).iloc[1:]])
    sink = FakeSink()
    first = run(sink, datetime.fromisoformat("2026-11-24T16:00:00+08:00"), "1", history_fn)
    assert calls == [("TAIEX", date(2021, 11, 17))]
    record_ = first["records"][0]
    assert record_["base_rate"]["status"] == "available"
    comment = sink.comments[901][0]
    assert f"基準率 {record_['base_rate']['rate']:.2f}（{record_['base_rate']['windows']:,} 個窗口）" in comment
    body = sink.issues[901]["body"]
    assert "## 成績表" in body and "| 全部 | 1 | 1.00 | 0.55 | 0.2025 | 1 |" in body
    run(sink, datetime.fromisoformat("2026-11-25T16:00:00+08:00"), "2", history_fn)
    assert len(calls) == 1  # cached in the Issue state


def test_a_failed_history_fetch_is_retried_and_never_blocks_the_judgment():
    attempts = []

    def failing(symbol, since):
        attempts.append(symbol)
        raise ConnectionError("TWSE 連線中斷")
    sink = FakeSink()
    first = run(sink, datetime.fromisoformat("2026-11-24T16:00:00+08:00"), "1", failing)
    assert first["records"][0]["status"] == "hit"
    assert first["records"][0]["base_rate"]["retry"] is True
    run(sink, datetime.fromisoformat("2026-11-25T16:00:00+08:00"), "2", failing)
    assert attempts == ["TAIEX", "TAIEX"]
