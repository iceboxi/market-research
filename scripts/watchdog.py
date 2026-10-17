"""Independent UTC watchdog for missing, failed or stuck scheduled EOD scans."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os

from scripts import monitor

SLOTS = {"tw": (11, 30, frozenset(range(5))),
         "us": (0, 45, frozenset(range(1, 6)))}
GRACE = timedelta(hours=2)
MAX_LATENESS = timedelta(hours=5)


def utc_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def latest_due_slot(market, now):
    """Latest UTC cron slot due >= two hours ago, respecting each market weekday."""
    if now.tzinfo is None:
        raise ValueError("watchdog clock must be timezone-aware")
    hour, minute, weekdays = SLOTS[market]
    now = now.astimezone(timezone.utc)
    for age in range(9):
        day = (now - timedelta(days=age)).date()
        if day.weekday() not in weekdays:
            continue
        due = datetime(day.year, day.month, day.day, hour, minute,
                       tzinfo=timezone.utc)
        if due + GRACE <= now:
            return due
    raise ValueError("no eligible scheduled slot within nine days")


def evaluate(market, runs, now):
    due = latest_due_slot(market, now)
    matches = [
        item for item in runs
        if item.get("event") == "schedule"
        and due - timedelta(minutes=15) <= utc_time(item["created_at"]) <= due + MAX_LATENESS
    ]
    selected = max(matches, key=lambda item: item["created_at"]) if matches else None
    if selected is None:
        return "critical", "scheduled_run_missing", due, None
    if selected.get("status") != "completed":
        return "critical", "scheduled_run_stalled", due, selected
    if selected.get("conclusion") != "success":
        return "critical", "scheduled_run_" + str(selected.get("conclusion")), due, selected
    return "healthy", "scheduled_run_success", due, selected


def get_scheduled_runs(repo):
    result = monitor.command(
        "gh", "api", f"repos/{repo}/actions/workflows/scan.yml/runs?event=schedule&per_page=100"
    )
    body = json.loads(result.stdout)
    if not isinstance(body.get("workflow_runs"), list):
        raise ValueError("malformed GitHub Actions response")
    return body["workflow_runs"]


def record_for(market, runs, repo, now):
    # A new installation cannot be responsible for scheduled slots before
    # its first active cron. Store this in versioned operations configuration.
    with open("config/operations.json", encoding="utf-8") as source:
        baseline = json.load(source)["first_due_slot_utc"]
    first = utc_time(baseline[market])
    due = latest_due_slot(market, now)
    if due < first:
        return {
            "kind": "watchdog", "market": market, "health": "warming_up",
            "reasons": ["first_scheduled_slot_not_due"],
            "scheduled_utc": due.isoformat(), "activation_utc": first.isoformat(),
            "run_url": f"https://github.com/{repo}/actions/workflows/scan.yml",
            "scanned": None, "requested": None, "errors": None,
            "signals": None, "expected_warnings": 0,
            "unexpected_warnings": 0, "mismatches": None,
            "session_dates": {},
        }

    state, reason, due, selected = evaluate(market, runs, now)
    url = selected.get("html_url") if selected else (
        f"https://github.com/{repo}/actions/workflows/scan.yml")
    return {
        "kind": "watchdog", "market": market, "health": state,
        "reasons": [reason], "scheduled_utc": due.isoformat(),
        "run_url": url, "scanned": None, "requested": None,
        "errors": None, "signals": None, "expected_warnings": 0,
        "unexpected_warnings": 0, "mismatches": None,
        "session_dates": {},
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True)
    p.add_argument("--dry-run", action="store_true",
                   help="Do not query GitHub or change Issues")
    args = p.parse_args()
    now = datetime.now(timezone.utc)
    runs = [] if args.dry_run else get_scheduled_runs(args.repo)
    critical = False
    lines = ["# Scheduled Market Scan Watchdog", ""]
    for market in ("tw", "us"):
        rec = record_for(market, runs, args.repo, now)
        critical |= rec["health"] == "critical"
        lines.append(
            f"- {market}: {rec['health']} / {rec['reasons'][0]} "
            f"(expected {rec['scheduled_utc']}; {rec['run_url']})"
        )
        if not args.dry_run and rec['health'] != 'warming_up':
            monitor.alert(rec, args.repo)
    report = "\n".join(lines) + "\n"
    print(report)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(report)
    if critical and not args.dry_run:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
