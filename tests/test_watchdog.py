from datetime import datetime, timezone
import pytest
from scripts import watchdog


def when(day, hour=4, minute=15):
    return datetime.fromisoformat(day).replace(
        hour=hour, minute=minute, tzinfo=timezone.utc)


def scheduled(date, status="completed", conclusion="success"):
    return {"event": "schedule", "created_at": date.isoformat(),
            "status": status, "conclusion": conclusion,
            "html_url": "https://github.com/owner/repo/actions/runs/123"}


def test_taiwan_and_us_cron_are_independent_over_weekends():
    t = when("2026-10-20")
    assert watchdog.latest_due_slot("tw", t) == when("2026-10-19", 11, 30)
    assert watchdog.latest_due_slot("us", t) == when("2026-10-20", 0, 45)
    sat = when("2026-10-17")
    assert watchdog.latest_due_slot("tw", sat) == when("2026-10-16", 11, 30)
    assert watchdog.latest_due_slot("us", sat) == when("2026-10-17", 0, 45)


def test_successful_push_is_not_evidence_of_scheduled_run():
    now = when("2026-10-20")
    push = scheduled(when("2026-10-20", 0, 47))
    push["event"] = "push"
    assert watchdog.evaluate("us", [push], now)[:2] == (
        "critical", "scheduled_run_missing")


def test_success_failed_and_stalled_jobs():
    now = when("2026-10-20")
    d = when("2026-10-20", 0, 47)
    assert watchdog.evaluate("us", [scheduled(d)], now)[:2] == (
        "healthy", "scheduled_run_success")
    assert watchdog.evaluate("us", [scheduled(d, conclusion="failure")], now)[:2] == (
        "critical", "scheduled_run_failure")
    assert watchdog.evaluate("us", [scheduled(d, status="in_progress",
                                            conclusion=None)], now)[:2] == (
        "critical", "scheduled_run_stalled")


def test_prior_slot_not_accepted_for_new_day():
    now = when("2026-10-20")
    assert watchdog.evaluate("us", [scheduled(when("2026-10-19", 0, 47))], now)[1] == (
        "scheduled_run_missing")


def test_invalid_naive_clock():
    with pytest.raises(ValueError, match="timezone-aware"):
        watchdog.latest_due_slot("us", datetime(2026, 10, 20, 4, 15))


def test_issue_namespace_is_separate(monkeypatch):
    from scripts import monitor
    calls = []
    def fake(*args, **kwargs):
        calls.append(args)
        class Completed:
            stdout = "[]"
        return Completed()
    monkeypatch.setattr(monitor, "command", fake)
    record = watchdog.record_for("tw", [], "owner/repo", when("2026-10-20"))
    monitor.alert(record, "owner/repo")
    creation = next(c for c in calls if c[:3] == ("gh", "issue", "create"))
    assert "[market-watchdog]" in creation[creation.index("--title") + 1]

def test_before_installation_does_not_create_false_incident(monkeypatch):
    from scripts import watchdog
    # Saturday pre-deployment slots must not be called failures.
    t = when("2026-10-17")
    for market in ("tw", "us"):
        record = watchdog.record_for(market, [], "owner/repo", t)
        assert record["health"] == "warming_up"
        assert record["reasons"] == ["first_scheduled_slot_not_due"]

def test_first_live_due_slot_is_monitored():
    at = when("2026-10-20")
    for market in ("tw", "us"):
        record = watchdog.record_for(market, [], "owner/repo", at)
        assert record["health"] == "critical"
        assert "scheduled_run_missing" in record["reasons"]
