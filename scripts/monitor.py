"""GitHub-native scan health, metadata-only history, and issue alerts.

No external Python packages: this runs even after dependency/scan failures.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess

if __package__:
    from .state_store import GitStateStore, StateError, canonical
else:
    from state_store import GitStateStore, StateError, canonical

EXPECTED_WARNINGS = {"unfinalized_session_bars_excluded"}
HISTORY_FIELDS = {"schema_version", "run_id", "run_url", "observed_at_utc", "event",
                  "market", "scan_outcome", "health", "reasons", "requested", "scanned",
                  "errors", "signals", "mismatches", "expected_warnings",
                  "unexpected_warnings", "session_dates", "input_hashes", "strategies",
                  "source_sha", "kind"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def classify(manifest, quality, outcome):
    if not isinstance(manifest, dict) or not isinstance(quality, dict):
        return "critical", ["missing_run_artifacts"]
    errors = quality.get("errors", [])
    reasons = []
    if outcome != "success" or errors:
        reasons.append("scan_failed_or_partial")
    if manifest.get("error_count") != len(errors):
        reasons.append("error_count_mismatch")
    if manifest.get("scanned_symbols", -1) + len(errors) != manifest.get("requested_symbols", -2):
        reasons.append("incomplete_coverage")
    if not manifest.get("strict_freshness"):
        reasons.append("freshness_gate_inactive")
    if manifest.get("official_mismatch_count", 0) > 0:
        reasons.append("official_data_mismatch")
    if reasons:
        return "critical", reasons
    unexpected = sorted({w.get("reason", "unknown")
                         for w in quality.get("warnings", [])
                         if w.get("reason") not in EXPECTED_WARNINGS})
    return ("degraded", unexpected) if unexpected else ("healthy", [])


def summarize(folder, repo, run_id, event, market, outcome, now=None):
    now = now or datetime.now(timezone.utc)
    m, q, signals = [read(folder / file) for file in (
        "manifest.json", "data_quality.json", "signals.json")]
    health, reasons = classify(m, q, outcome)
    record = {
        "schema_version": 1, "run_id": str(run_id),
        "run_url": "https://github.com/" + repo + "/actions/runs/" + str(run_id),
        "observed_at_utc": now.astimezone(timezone.utc).isoformat(),
        "event": event, "market": market, "scan_outcome": outcome,
        "health": health, "reasons": reasons,
        "requested": None, "scanned": None, "errors": None, "signals": None,
        "mismatches": None, "expected_warnings": 0, "unexpected_warnings": 0,
        "session_dates": {}, "input_hashes": [], "strategies": [],
    }
    if m:
        record.update({
            "requested": m.get("requested_symbols"),
            "scanned": m.get("scanned_symbols"), "errors": m.get("error_count"),
            "signals": m.get("matching_signals"),
            "mismatches": m.get("official_mismatch_count"),
            "strategies": m.get("strategies", []), "source_sha": m.get("git_sha"),
        })
    if q:
        sessions = {}
        for row in q.get("symbols", []):
            sessions.setdefault(row["market"], set()).add(row["last_date"])
            record["input_hashes"].append({
                "market": row["market"], "symbol": row["symbol"],
                "date": row["last_date"], "sha256": row["input_sha256"],
            })
        record["session_dates"] = {k: sorted(v) for k, v in sessions.items()}
        warnings = q.get("warnings", [])
        record["expected_warnings"] = sum(
            w.get("reason") in EXPECTED_WARNINGS for w in warnings)
        record["unexpected_warnings"] = len(warnings) - record["expected_warnings"]
    if signals is not None and len(signals) != record["signals"]:
        record["health"] = "critical"
        record["reasons"].append("signal_count_mismatch")
    return record


def markdown(r):
    return "\n".join([
        "### Scan health: " + r["health"].upper(), "",
        "- Run: " + r["run_url"],
        "- Market: " + r["market"],
        "- Coverage: " + str(r["scanned"]) + "/" + str(r["requested"]),
        "- Errors: " + str(r["errors"]) + "; signals: " + str(r["signals"]),
        "- Expected warnings: " + str(r["expected_warnings"]),
        "- Unexpected warnings: " + str(r["unexpected_warnings"]),
        "- Official mismatches: " + str(r["mismatches"]),
        "- Sessions: " + str(r["session_dates"]),
        "- Reasons: " + (", ".join(r["reasons"]) or "none"),
        "", "Contains metadata and hashes, not OHLCV prices.", "",
    ])


def command(*args, check=True):
    return subprocess.run(args, capture_output=True, text=True, check=check)


def history_key(record):
    if (not isinstance(record, dict) or record.get("schema_version") != 1 or
            not record.keys() <= HISTORY_FIELDS or
            record.get("health") not in ("healthy", "degraded", "critical")):
        raise StateError("Only versioned health metadata may be archived")
    if not isinstance(record.get("run_id"), str) or not re.fullmatch(r"[0-9]+", record["run_id"]):
        raise StateError("History needs a numeric run ID")
    d = datetime.fromisoformat(record["observed_at_utc"])
    if d.tzinfo is None:
        raise StateError("History needs a timezone and numeric run ID")
    for item in record.get("input_hashes", []):
        if not isinstance(item, dict) or set(item) != {"market", "symbol", "date", "sha256"}:
            raise StateError("Only input identities/hashes may be archived")
    for strategy in record.get("strategies", []):
        if (not isinstance(strategy, dict) or not strategy.keys() <= {"id", "version", "params"}
                or not isinstance(strategy.get("params", {}), dict) or
                any(isinstance(v, (dict, list)) for v in strategy.get("params", {}).values())):
            raise StateError("Only strategy metadata may be archived")
    canonical(record)
    d = d.astimezone(timezone.utc)
    filename = d.strftime("%Y%m%d") + "-run-" + record["run_id"] + ".json"
    return "history/" + d.strftime("%Y/%m/") + filename


def archive_history(record, store=None):
    """Persist metadata immutably; preserve source health independently of IO."""
    path = history_key(record)
    store = store or GitStateStore()

    def merge(records):
        for key, previous in records.items():
            if key != history_key(previous):
                raise StateError("History path/identity mismatch")
        if path in records and canonical(records[path]) != canonical(record):
            raise StateError("Immutable history key already has different content")
        return {**records, path: record}

    before = store.main_head()
    result = store.commit("operations", merge, legacy_prefix="history")
    return {**result, "path": path, "main_before": before, "main_after": store.main_head(),
            "run_url": record["run_url"], "source_health": record["health"]}


def archive(record):
    """Compatibility entry point; returns the logical history key."""
    return archive_history(record)["path"]


def history(store=None):
    result = (store or GitStateStore()).read("operations")
    if result["status"] != "available":
        raise StateError("Operations state is not initialized; no legacy fallback")
    for key, record in result["records"].items():
        if key != history_key(record):
            raise StateError("History path/identity mismatch")
    return result


def alert(record, repo):
    """Deduplicate issues per market; successful subsequent scans close them."""
    title = ("[market-watchdog] Scheduled scan " if record.get("kind") == "watchdog" else "[market-health] EOD scan ") + record["market"]
    issues = json.loads(command(
        "gh", "issue", "list", "--repo", repo,
        "--state", "open", "--limit", "100",
        "--json", "number,title").stdout)
    matches = [issue for issue in issues if issue["title"] == title]
    details = markdown(record)
    if record["health"] == "healthy":
        for issue in matches:
            number = str(issue["number"])
            command("gh", "issue", "comment", number, "--repo", repo,
                    "--body", "Recovered:\n\n" + details)
            command("gh", "issue", "close", number, "--repo", repo)
        return "recovered" if matches else "healthy"
    if matches:
        command("gh", "issue", "comment", str(matches[0]["number"]),
                "--repo", repo, "--body", details)
        return "updated"
    command("gh", "issue", "create", "--repo", repo,
            "--title", title, "--body", details)
    return "created"


def main():
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="action", required=True)
    p = subs.add_parser("report")
    for key in ("repo", "run-id", "event", "market", "outcome"):
        p.add_argument("--" + key, required=True)
    p.add_argument("--out", type=Path, default=Path("output"))
    p = subs.add_parser("archive")
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--receipt", type=Path, default=Path("output/state_receipt.json"))
    p = subs.add_parser("alert")
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--repo", required=True)
    a = parser.parse_args()
    if a.action == "report":
        a.out.mkdir(parents=True, exist_ok=True)
        record = summarize(a.out, a.repo, a.run_id, a.event, a.market, a.outcome)
        (a.out / "health_report.json").write_text(
            json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8")
        (a.out / "health_report.md").write_text(markdown(record), encoding="utf-8")
        print(markdown(record))
    elif a.action == "archive":
        receipt = {"schema_version": 1, "status": "failed", "code_sha": os.getenv("GITHUB_SHA")}
        try:
            record = read(a.report)
            if isinstance(record, dict):
                receipt["run_url"] = record.get("run_url")
            receipt = archive_history(record)
        except (StateError, ValueError, KeyError, TypeError) as error:
            receipt["error"] = str(error)
            raise
        finally:
            a.receipt.parent.mkdir(parents=True, exist_ok=True)
            a.receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(receipt, indent=2))
    else:
        print("GitHub issue:", alert(read(a.report), a.repo))


if __name__ == "__main__":
    main()
