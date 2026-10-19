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


def test_queued_run_is_distinct_from_missing_or_running_job():
    now = when("2026-10-20")
    queued = scheduled(when("2026-10-20", 0, 47), status="queued", conclusion=None)
    assert watchdog.evaluate("us", [queued], now)[:2] == (
        "critical", "scheduled_run_queued")


def test_missing_schedule_feedback_has_freshness_next_slot_and_last_success():
    now = when("2026-10-19", 16, 30)
    prior = scheduled(when("2026-10-16", 11, 35))
    prior["run_started_at"] = "2026-10-16T11:36:00Z"
    us = scheduled(when("2026-10-17", 1, 0))
    record = watchdog.record_for("tw", [prior, us], "owner/repo", now)

    assert record["reasons"] == ["scheduled_run_missing"]
    feedback = record["schedule_feedback"]
    assert feedback["observed_at_utc"] == "2026-10-19T16:30:00+00:00"
    assert feedback["phase"] == "not_created"
    assert feedback["freshness"] == "overdue"
    assert feedback["grace_seconds"] == 7200
    assert feedback["grace_expires_utc"] == "2026-10-19T13:30:00+00:00"
    assert feedback["next_scheduled_utc"] == "2026-10-20T11:30:00+00:00"
    assert feedback["last_successful_scheduled_run"]["created_at"] == prior["created_at"]
    assert feedback["last_successful_scheduled_run"]["run_started_at"] == prior["run_started_at"]
    assert feedback["matched_run"] is None
    assert feedback["source_health"] == "not_evaluated"
    assert feedback["root_cause"] == "unverified"


def test_first_slot_inside_grace_is_visible_before_watchdog_judges_it():
    record = watchdog.record_for("us", [], "owner/repo", when("2026-10-20", 1, 0))
    assert record["health"] == "warming_up"
    feedback = record["schedule_feedback"]
    assert feedback["latest_nominal_slot_utc"] == "2026-10-20T00:45:00+00:00"
    assert feedback["latest_nominal_grace_expires_utc"] == "2026-10-20T02:45:00+00:00"
    assert feedback["latest_nominal_within_grace"] is True
    assert feedback["next_scheduled_utc"] == "2026-10-21T00:45:00+00:00"


@pytest.mark.parametrize("status,conclusion,phase", [
    ("queued", None, "queued"),
    ("in_progress", None, "in_progress"),
    ("completed", "failure", "execution_failed"),
    ("completed", "success", "completed"),
])
def test_feedback_keeps_actual_execution_phase_and_times(status, conclusion, phase):
    run = scheduled(when("2026-10-20", 0, 47), status=status, conclusion=conclusion)
    run["run_started_at"] = None if status == "queued" else "2026-10-20T01:10:00Z"
    record = watchdog.record_for("us", [run], "owner/repo", when("2026-10-20"))
    feedback = record["schedule_feedback"]
    assert feedback["phase"] == phase
    assert feedback["matched_run"]["created_at"] == run["created_at"]
    assert feedback["matched_run"]["run_started_at"] == run["run_started_at"]
    assert feedback["source_health"] == "not_evaluated"
    assert feedback["freshness"] == ("current" if conclusion == "success" else "overdue")


def test_future_and_push_runs_do_not_satisfy_schedule_feedback():
    future = scheduled(when("2026-10-20", 11, 35))
    push = scheduled(when("2026-10-19", 11, 35))
    push["event"] = "push"
    record = watchdog.record_for("tw", [future, push], "owner/repo", when("2026-10-19", 16, 30))
    assert record["reasons"] == ["scheduled_run_missing"]
    assert record["schedule_feedback"]["last_successful_scheduled_run"] is None


@pytest.mark.parametrize("market,expected", [
    ("tw", "2026-10-19T11:30:00+00:00"),
    ("us", "2026-10-20T00:45:00+00:00"),
])
def test_next_slot_follows_market_cron_over_weekend(market, expected):
    record = watchdog.record_for(market, [], "owner/repo", when("2026-10-17", 17, 0))
    assert record["schedule_feedback"]["next_scheduled_utc"] == expected


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


def test_github_scheduled_run_schema_and_query(monkeypatch):
    from scripts import monitor
    calls = []
    def fake(*args, **kwargs):
        calls.append(args)
        class Result:
            stdout = '{"workflow_runs":[{"event":"schedule","created_at":"2026-10-20T00:47:00Z","status":"completed","conclusion":"success"}]}'
        return Result()
    monkeypatch.setattr(monitor, "command", fake)
    actual = watchdog.get_scheduled_runs("owner/repo")
    assert actual[0]["event"] == "schedule"
    assert "event=schedule" in calls[0][-1]
    assert watchdog.evaluate("us", actual, when("2026-10-20"))[0] == "healthy"


def test_probe_writes_readable_feedback_without_issue_mutations(monkeypatch, tmp_path):
    import json
    import sys
    from scripts import monitor

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return when("2026-10-19", 16, 30)

    calls = []
    def api(*args, **kwargs):
        calls.append(args)
        assert args[:2] == ("gh", "api")
        class Result:
            stdout = '{"workflow_runs":[]}'
        return Result()

    monkeypatch.setattr(watchdog, "datetime", Clock)
    monkeypatch.setattr(monitor, "command", api)
    monkeypatch.setattr(sys, "argv", ["watchdog", "--repo", "owner/repo", "--probe",
                                      "--out", str(tmp_path / "feedback")])
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    watchdog.main()

    receipt = json.loads((tmp_path / "feedback/schedule_feedback.json").read_text())
    report = (tmp_path / "feedback/schedule_feedback.md").read_text()
    assert receipt["schema_version"] == 1
    assert receipt["observed_at_utc"] == "2026-10-19T16:30:00+00:00"
    assert receipt["markets"]["tw"]["schedule_feedback"]["phase"] == "not_created"
    assert receipt["mutations"] == "not_attempted"
    assert "2026-10-20T11:30:00+00:00" in report
    assert "2026-10-20T19:30:00+08:00" in report
    assert "grace" in report
    assert "not_evaluated" in report
    assert summary.read_text() == report
    assert len(calls) == 1
