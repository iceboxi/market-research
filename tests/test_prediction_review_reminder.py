"""#183 PL4: on the week's last session, remind to write next week's prediction when none is open."""
from datetime import datetime

import pytest

from scripts.prediction_review import sync
from tests.test_prediction_review import FakeSink
from tests.test_prediction_review_results import UP_WEEK, WEEKLY, bars

INFERENCE = {"id": "P-20261117-37837", "trigger": "inference", "method": "judgment", "reasoning": "r",
             "claim": {"kind": "held", "symbol": "TAIEX", "op": ">", "level": 37837.05, "basis": "intraday"},
             "horizon_sessions": 10, "probability": 0.55}
OLD = {"first_seen": datetime.fromisoformat("2026-11-18T00:03:59+08:00")}  # start 11/17


def at(day):
    return datetime.fromisoformat(f"{day}T16:00:00+08:00")


def run(entries, now, history=None, sink=None, run_id="1", frames=None):
    sink = sink or FakeSink()
    history = history if history is not None else {e["id"]: OLD for e in entries}
    result = sync(sink, entries, history, now, run_id=run_id, run_url=f"https://example.invalid/run/{run_id}",
                  bars_fn=lambda symbol, since: frames[symbol])
    return sink, result


def test_friday_without_an_open_weekly_prediction_reminds():
    sink, result = run([INFERENCE], at("2026-11-20"))
    assert result["reminder"] == "2026-W47" and result["comment"] == "posted"
    [comment] = sink.comments[901]
    assert "## 週預測提醒：2026-11-20" in comment and "本週（2026-W47）結束後沒有未到期的週預測" in comment
    assert '"reminded_week":"2026-W47"' in sink.issues[901]["body"]


def test_an_open_weekly_prediction_needs_no_reminder():
    _, result = run([WEEKLY], at("2026-11-20"))  # started 11/17, due 11/24
    assert result["reminder"] is None and result["comment"] == "not_needed"


def test_only_the_last_session_of_the_week_reminds():
    _, result = run([INFERENCE], at("2026-11-19"))
    assert result["reminder"] is None and result["comment"] == "not_needed"


def test_a_friday_holiday_moves_the_reminder_to_thursday():
    # 2027-01-01 (Friday) is closed, so Thursday 2026-12-31 ends the week.
    _, result = run([INFERENCE], at("2026-12-31"))
    assert result["reminder"] == "2026-W53"


def test_a_confirmed_closure_counts_as_closed():
    sink = FakeSink()
    result = sync(sink, [INFERENCE], {INFERENCE["id"]: OLD}, at("2026-11-19"), run_id="1",
                  run_url="https://example.invalid/run/1", bars_fn=None,
                  closed_sessions=("2026-11-20",))  # typhoon on Friday
    assert result["reminder"] == "2026-W47"


def test_a_weekly_prediction_started_within_five_sessions_needs_no_reminder():
    # Withdrawn, so not open, but it started on 11/17, within the last 5 sessions of Friday 11/20.
    withdrawn = {**WEEKLY, "withdrawn": {"date": "2026-11-18", "reason": "重寫"}}
    _, result = run([withdrawn], at("2026-11-20"))
    assert result["reminder"] is None


def test_the_same_week_is_reminded_once():
    sink, first = run([INFERENCE], at("2026-11-20"), run_id="1")
    _, second = run([INFERENCE], datetime.fromisoformat("2026-11-21T10:00:00+08:00"), sink=sink, run_id="2")
    assert first["reminder"] == "2026-W47" and second["reminder"] is None
    assert len(sink.comments[901]) == 1


def test_results_and_reminder_share_one_comment():
    # Started 11/13 (first seen Saturday 11/14), due Friday 11/20: judged hit, nothing else open.
    weekly = {**WEEKLY, "id": "W-20261113-taiex"}
    history = {"W-20261113-taiex": {"first_seen": datetime.fromisoformat("2026-11-14T10:00:00+08:00")}}
    dates = ["2026-11-12", "2026-11-13", "2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20"]
    frame = bars([43091.87, 43675.12, 41040.08, 40092.11, 40500.0, 40800.0, 44000.0], dates=dates)
    sink, result = run([weekly], at("2026-11-20"), history=history, frames={"TAIEX": frame})
    assert result["changes"] == ["W-20261113-taiex"] and result["reminder"] == "2026-W47"
    [comment] = sink.comments[901]
    assert "## 預測結果：2026-11-20" in comment and "命中" in comment and "**週預測提醒**" in comment


@pytest.mark.parametrize("day", ["2026-11-23", "2026-11-24"])
def test_no_reminder_early_in_the_week(day):
    _, result = run([INFERENCE], at(day), frames={"TAIEX": bars(UP_WEEK)})
    assert result["reminder"] is None
