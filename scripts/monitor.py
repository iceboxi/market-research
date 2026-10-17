"""GitHub-native scan health, metadata-only history, and issue alerts.

No external Python packages: this runs even after dependency/scan failures.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time

EXPECTED_WARNINGS = {"unfinalized_session_bars_excluded"}


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


def archive(record):
    """Rebase-free fast-forward-only retry; commit only sanitized metadata."""
    d = datetime.fromisoformat(record["observed_at_utc"])
    filename = d.strftime("%Y%m%d") + "-run-" + record["run_id"] + ".json"
    path = Path("history") / d.strftime("%Y/%m") / filename
    payload = json.dumps(record, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    for attempt in range(3):
        command("git", "fetch", "origin", "main")
        command("git", "switch", "-C", "health-archive", "origin/main")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_text(encoding="utf-8") == payload:
            return str(path)
        path.write_text(payload, encoding="utf-8")
        command("git", "add", "--", str(path))
        command("git", "-c", "user.name=github-actions[bot]",
                "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                "commit", "-m", "history: EOD run " + record["run_id"])
        pushed = command("git", "push", "origin", "HEAD:main", check=False)
        if pushed.returncode == 0:
            return str(path)
        if attempt == 2:
            raise RuntimeError("Archive push failed: " + pushed.stderr)
        time.sleep(attempt + 1)
    raise RuntimeError("Archive retry exhausted")


def alert(record, repo):
    """Deduplicate issues per market; successful subsequent scans close them."""
    title = "[market-health] EOD scan " + record["market"]
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
        print("Archived:", archive(read(a.report)))
    else:
        print("GitHub issue:", alert(read(a.report), a.repo))


if __name__ == "__main__":
    main()
