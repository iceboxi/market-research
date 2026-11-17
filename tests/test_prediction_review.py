"""#183 PL1: the prediction review Issue lists each prediction's start, check session and status."""
from datetime import datetime
from types import SimpleNamespace

import pytest

from scripts.prediction_review import (
    MARKER, ReviewContextError, ledger_history, require_review_context, sync,
)

RUN_URL = "https://github.com/iceboxi/market-research/actions/runs/1"
NOW = datetime.fromisoformat("2026-11-18T16:00:00+08:00")


class FakeSink:
    """GitHub Issues stand-in recording every write."""

    def __init__(self, issues=()):
        self.issues = {issue["number"]: dict(issue) for issue in issues}
        self.comments, self.calls = {}, []

    def find(self, marker):
        return [dict(i) for i in self.issues.values() if marker in (i.get("body") or "")]

    def create(self, title, body):
        number = max([900, *self.issues]) + 1
        self.issues[number] = {"number": number, "title": title, "body": body, "state": "open"}
        self.calls.append("create")
        return {"number": number}

    def update(self, number, body):
        self.issues[number]["body"] = body
        self.calls.append("update")

    def find_comments(self, number, marker):
        return [c for c in self.comments.get(number, []) if marker in c]

    def create_comment(self, number, body):
        self.comments.setdefault(number, []).append(body)
        self.calls.append("comment")


def entry(pid="W-20261117-taiex", **changes):
    base = {"id": pid, "trigger": "weekly", "method": "judgment", "reasoning": "r",
            "claim": {"kind": "return", "symbol": "TAIEX", "op": ">", "threshold_pct": 0},
            "horizon_sessions": 5, "probability": 0.55}
    base.update(changes)
    return base


def seen(iso):
    return {"first_seen": datetime.fromisoformat(iso)}


def run(entries, history, sink=None, now=NOW):
    sink = sink or FakeSink()
    result = sync(sink, entries, history, now, run_id="1", run_url=RUN_URL)
    return sink, result, {r["id"]: r for r in result["records"]}


@pytest.mark.parametrize("first_seen, start, check", [
    ("2026-11-18T00:03:59+08:00", "2026-11-17", "2026-11-24"),  # #184 merge, after the 11/17 close
    ("2026-11-17T14:31:00+08:00", "2026-11-17", "2026-11-24"),  # just past close + 60 minutes
    ("2026-11-17T14:29:00+08:00", "2026-11-16", "2026-11-23"),  # within 60 minutes of the close
    ("2026-11-17T10:00:00+08:00", "2026-11-16", "2026-11-23"),  # during the session
    ("2026-11-21T10:00:00+08:00", "2026-11-20", "2026-11-27"),  # Saturday
])
def test_start_is_the_latest_completed_session_at_first_seen(first_seen, start, check):
    _, _, records = run([entry()], {"W-20261117-taiex": seen(first_seen)})
    record = records["W-20261117-taiex"]
    assert (record["start_session"], record["expected_check_session"]) == (start, check)
    assert record["status"] == "pending"


def test_check_session_counts_trading_sessions():
    _, _, records = run([entry("P-20261117-43307", trigger="inference", horizon_sessions=11)],
                        {"P-20261117-43307": seen("2026-11-18T00:03:59+08:00")})
    assert records["P-20261117-43307"]["expected_check_session"] == "2026-12-02"


def test_event_merged_after_the_event_is_void():
    event = entry("E-20261117-nvda", trigger="event", event="財報",
                  event_time="2026-11-17T16:00:00-05:00", horizon_sessions=1)
    _, _, early = run([event], {"E-20261117-nvda": seen("2026-11-18T00:03:59+08:00")})
    _, _, late = run([event], {"E-20261117-nvda": seen("2026-11-18T05:00:01+08:00")})
    assert early["E-20261117-nvda"]["status"] == "pending"
    assert (late["E-20261117-nvda"]["status"], late["E-20261117-nvda"]["void_reason"]) == ("void", "late_entry")


def test_withdrawn_shows_date_and_reason():
    sink, _, records = run([entry(withdrawn={"date": "2026-11-19", "reason": "條件寫錯"})],
                           {"W-20261117-taiex": seen("2026-11-18T00:03:59+08:00")})
    assert records["W-20261117-taiex"]["status"] == "withdrawn"
    body = sink.issues[901]["body"]
    assert "已撤回：2026-11-19 撤回：條件寫錯" in body


def test_prediction_not_on_main_has_no_start():
    _, _, records = run([entry()], {})
    record = records["W-20261117-taiex"]
    assert (record["status"], record["start_session"], record["reason"]) == ("pending", None, "尚未合併到 main")


def test_creates_then_updates_one_issue_with_the_table():
    entries = [entry(), entry("P-20261117-37837", trigger="inference", method="forced-selling",
                              method_version="2026-11-12", horizon_sessions=10,
                              claim={"kind": "held", "symbol": "TAIEX", "op": ">",
                                     "level": 37837.05, "basis": "intraday"})]
    history = {pid: seen("2026-11-18T00:03:59+08:00") for pid in ("W-20261117-taiex", "P-20261117-37837")}
    sink, result, _ = run(entries, history)
    assert sink.calls == ["create", "update"] and result["issue_number"] == 901
    body = sink.issues[901]["body"]
    assert body.startswith(MARKER) and "非買賣建議" in body
    assert ("| `W-20261117-taiex` | 週預測 | judgment | 加權指數 5 個交易日報酬 > 0% | 0.55 | "
            "2026-11-18 00:03 | 2026-11-17 | 2026-11-24 | 未到期 |") in body
    assert ("| `P-20261117-37837` | 推論轉預測 | forced-selling 2026-11-12 | "
            "加權指數 10 個交易日內每天最低價 > 37,837.05 | 0.55 | 2026-11-18 00:03 | 2026-11-17 | 2026-12-01 | 未到期 |") in body
    run(entries, history, sink)
    assert sink.calls == ["create", "update", "update"]


def test_two_open_issues_fail():
    sink = FakeSink([{"number": 1, "body": MARKER, "state": "open"},
                     {"number": 2, "body": MARKER, "state": "open"}])
    with pytest.raises(ValueError, match="More than one"):
        run([entry()], {}, sink)


def test_closed_issue_is_not_reused():
    sink = FakeSink([{"number": 5, "body": MARKER, "state": "closed"}])
    _, result, _ = run([entry()], {}, sink)
    assert result["issue_number"] == 901


@pytest.mark.parametrize("env", [
    {"GITHUB_REF": "refs/heads/feat", "GITHUB_EVENT_NAME": "workflow_dispatch", "SCAN_MARKET": "tw"},
    {"GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "push", "SCAN_MARKET": "tw"},
    {"GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "schedule", "SCAN_MARKET": "us"},
])
def test_only_main_tw_schedule_or_dispatch_may_write(env):
    with pytest.raises(ReviewContextError):
        require_review_context(env)


def test_main_tw_schedule_may_write():
    require_review_context({"GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "schedule", "SCAN_MARKET": "tw"})


def test_history_takes_the_first_commit_holding_each_id():
    versions = {
        "a1": "predictions:\n  - {id: W-1, horizon_sessions: 5}\n",
        "b2": "predictions: [unclosed\n",
        "c3": "predictions:\n  - {id: W-1, horizon_sessions: 4}\n  - {id: E-2}\n",
    }
    log = "a1\t2026-11-18T00:03:59+08:00\nb2\t2026-11-19T09:00:00+08:00\nc3\t2026-11-20T21:00:00+08:00\n"

    def fake_run(args, **_):
        if args[3] == "log":
            return SimpleNamespace(returncode=0, stdout=log, stderr="")
        sha = args[4].split(":")[0]
        return SimpleNamespace(returncode=0, stdout=versions[sha], stderr="")

    history, warnings = ledger_history(run=fake_run)
    assert history["W-1"]["first_seen"] == datetime.fromisoformat("2026-11-18T00:03:59+08:00")
    assert history["W-1"]["entry"]["horizon_sessions"] == 5  # the version at First seen
    assert history["E-2"]["first_seen"] == datetime.fromisoformat("2026-11-20T21:00:00+08:00")
    assert warnings == ["b2：ParserError"]
    assert history["E-2"]["commit"] == "c3"
