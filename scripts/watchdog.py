"""Independent UTC watchdog for missing, failed or stuck scheduled EOD scans."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts import monitor

SLOTS = {"tw": (7, 40, frozenset(range(5))),
         "us": (0, 45, frozenset(range(1, 6)))}
# US cron removed in #117; its slot stays defined for manual probes.
MONITORED_MARKETS = ("tw",)
GRACE = timedelta(hours=2)
# Natural schedule runs were created 4-6.2h after their cron slot (#51);
# windows now overlap 07:25-08:45 UTC, where created_at cannot tell markets apart.
MAX_LATENESS = timedelta(hours=8)


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
    if selected.get("status") == "queued":
        return "critical", "scheduled_run_queued", due, selected
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


def next_scheduled_slot(market, now):
    hour, minute, weekdays = SLOTS[market]
    now = now.astimezone(timezone.utc)
    for age in range(9):
        day = (now + timedelta(days=age)).date()
        slot = datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc)
        if day.weekday() in weekdays and slot > now:
            return slot
    raise ValueError("no next scheduled slot within nine days")


def schedule_feedback(market, runs, now, first, due, state, selected):
    def metadata(run):
        return {key: run.get(key) for key in (
            "html_url", "created_at", "run_started_at", "updated_at",
            "status", "conclusion", "head_sha")}

    # Match the existing TW/US time windows. The API timestamps alone do not
    # prove the runtime market; that still needs the scan Artifact.
    hour, minute, weekdays = SLOTS[market]
    successes = []
    for run in runs:
        created = utc_time(run["created_at"])
        slot = created.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if (created.weekday() in weekdays and
                slot - timedelta(minutes=15) <= created <= slot + MAX_LATENESS and
                run.get("status") == "completed" and run.get("conclusion") == "success"):
            successes.append(run)
    latest = max(successes, key=lambda run: run["created_at"]) if successes else None
    phase = ("not_due" if state == "warming_up" else "not_created" if selected is None else
             "execution_failed" if selected.get("status") == "completed" and
             selected.get("conclusion") != "success" else selected.get("status"))
    nominal = latest_due_slot(market, now + GRACE)
    return {
        "observed_at_utc": now.astimezone(timezone.utc).isoformat(),
        "phase": phase,
        "freshness": "not_due" if state == "warming_up" else
                     "current" if state == "healthy" else "overdue",
        "grace_seconds": int(GRACE.total_seconds()),
        "grace_expires_utc": (due + GRACE).isoformat(),
        "latest_nominal_slot_utc": nominal.isoformat() if nominal >= first else None,
        "latest_nominal_grace_expires_utc": (nominal + GRACE).isoformat() if nominal >= first else None,
        "latest_nominal_within_grace": nominal >= first and nominal + GRACE > now,
        "next_scheduled_utc": max(first, next_scheduled_slot(market, now)).isoformat(),
        "matched_run": metadata(selected) if selected else None,
        "last_successful_scheduled_run": metadata(latest) if latest else None,
        "source_health": "not_evaluated",
        "root_cause": "unverified" if state == "critical" else None,
        "run_window_seconds": int(MAX_LATENESS.total_seconds()),
        "coverage": "returned_schedule_runs_only",
        "matching_basis": "created_at_window",
        "market_confirmation": "not_evaluated",
    }


def record_for(market, runs, repo, now):
    # A new installation cannot be responsible for scheduled slots before
    # its first active cron. Store this in versioned operations configuration.
    with open("config/operations.json", encoding="utf-8") as source:
        baseline = json.load(source)["first_due_slot_utc"]
    first = utc_time(baseline[market])
    due = latest_due_slot(market, now)
    runs = [run for run in runs if run.get("event") == "schedule" and
            utc_time(run["created_at"]) <= now]
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
            "schedule_feedback": schedule_feedback(
                market, runs, now, first, due, "warming_up", None),
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
        "schedule_feedback": schedule_feedback(market, runs, now, first, due, state, selected),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True)
    p.add_argument("--dry-run", action="store_true",
                   help="Do not query GitHub or change Issues")
    p.add_argument("--probe", action="store_true",
                   help="Read the real GitHub Actions API without creating issues or failing on missing slots")
    p.add_argument("--out", type=Path,
                   help="Also save schedule_feedback.json and schedule_feedback.md")
    args = p.parse_args()
    if args.dry_run and args.probe:
        p.error("--dry-run and --probe cannot be combined")
    now = datetime.now(timezone.utc)
    runs = [] if args.dry_run else get_scheduled_runs(args.repo)
    critical = False
    records = {}
    lines = ["# Scheduled Market Scan Watchdog", "",
             "觀測時間 (UTC)：" + now.isoformat(), ""]
    for market in MONITORED_MARKETS:
        rec = record_for(market, runs, args.repo, now)
        records[market] = rec
        critical |= rec["health"] == "critical"
        lines.append(
            f"- {market}: {rec['health']} / {rec['reasons'][0]} "
            f"(expected {rec['scheduled_utc']}; {rec['run_url']})"
        )
        feedback = rec["schedule_feedback"]
        next_slot = utc_time(feedback["next_scheduled_utc"])
        last = feedback["last_successful_scheduled_run"]
        matched = feedback["matched_run"]
        lines += [
            f"  - 執行階段：{feedback['phase']}；時效：{feedback['freshness']}",
            f"  - 本次判定 grace 到期 (UTC)：{feedback['grace_expires_utc']} "
            f"({feedback['grace_seconds']} 秒)",
            f"  - 下一次預期排程：{next_slot.isoformat()} (UTC) / "
            f"{next_slot.astimezone(ZoneInfo('Asia/Taipei')).isoformat()} (臺灣)",
            "  - 同 window 最後成功的自然 job（市場待 Artifact 確認）：" +
            (f"{last['html_url']}；created={last['created_at']}；started={last['run_started_at']}"
             if last else "本次 API 回傳範圍未觀測到"),
            "  - 本次 run 時間：" +
            (f"created={matched['created_at']}；started={matched['run_started_at']}"
             if matched else "尚無符合 window 的 run"),
            "  - 來源資料健康：not_evaluated；需另查 scan Artifact。",
        ]
        if feedback["latest_nominal_within_grace"]:
            lines.append(
                f"  - 最近名目 slot {feedback['latest_nominal_slot_utc']} 尚在 grace 內，"
                f"判定門檻為 {feedback['latest_nominal_grace_expires_utc']}；尚未代表檢查已執行。")
        if not (args.dry_run or args.probe) and rec['health'] != 'warming_up':
            monitor.alert(rec, args.repo)
    lines += ["", "grace 是判定門檻；實際檢查取決於 watchdog workflow 何時執行。",
              "下一個 slot 是預期時間，GitHub 排程可能延遲；本次僅涵蓋 API 回傳的 schedule runs。",
              "缺席或延遲的根因尚未確認；job 成功不等於行情健康或自然驗收已完成。"]
    report = "\n".join(lines) + "\n"
    print(report)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        receipt = {"schema_version": 1, "observed_at_utc": now.isoformat(),
                   "markets": records,
                   "mutations": "not_attempted" if args.dry_run or args.probe else "issue_sync_attempted"}
        (args.out / "schedule_feedback.json").write_text(
            json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (args.out / "schedule_feedback.md").write_text(report, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(report)
    if critical and not (args.dry_run or args.probe):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
