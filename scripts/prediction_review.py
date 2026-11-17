"""Prediction review Issue (#183): one Issue listing every ledger prediction and its status.

Each daily TW run reads the knowledge-base prediction ledger, takes each prediction's First seen
from main's git history, and rewrites the Issue body. Only the main TW schedule or dispatch may
write; nothing is written back to the repository.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
from zoneinfo import ZoneInfo

import yaml

from market_research.prediction_ledger import load_ledger, supported_symbols
from market_research.prediction_review import STATUS_LABELS, TRIGGER_LABELS, evaluate
from scripts.research_github import GitHubResearchSink

ROOT = Path(__file__).resolve().parents[1]
LEDGER = Path("knowledge") / "predictions.yaml"
REPO_URL = "https://github.com/iceboxi/market-research"
MARKER = "<!-- market-research:prediction-review -->"
TITLE = "預測回顧（非買賣建議）"
DISCLAIMER = "非買賣建議"
TAIPEI = ZoneInfo("Asia/Taipei")


class ReviewContextError(ValueError):
    pass


def require_review_context(env):
    """Branch, pull-request and validation runs must never write the review Issue."""
    if (env.get("GITHUB_REF") != "refs/heads/main" or
            env.get("GITHUB_EVENT_NAME") not in ("schedule", "workflow_dispatch") or
            env.get("SCAN_MARKET") not in ("tw", "both")):
        raise ReviewContextError("The prediction review writes only from the main TW schedule or dispatch")


# ---------------------------------------------------------------- git history

def ledger_history(repo=ROOT, path=LEDGER, ref="HEAD", run=subprocess.run):
    """First seen of every id: the first first-parent commit on `ref` whose ledger holds it.

    Returns ({id: {"first_seen": datetime, "entry": dict}}, warnings). A historical version
    that does not parse is skipped and named in the warnings.
    """
    def git(*args):
        result = run(["git", "-C", str(repo), *args], text=True, capture_output=True, timeout=60)
        if result.returncode:
            raise RuntimeError(f"git {args[0]} failed: {result.stderr.strip()}")
        return result.stdout

    history, warnings = {}, []
    log = git("log", "--first-parent", "--reverse", "--format=%H%x09%cI", ref, "--", str(path))
    for line in filter(None, log.splitlines()):
        sha, committed = line.split("\t")
        try:
            data = yaml.safe_load(git("show", f"{sha}:{path.as_posix()}")) or {}
            entries = data.get("predictions") or []
        except (RuntimeError, yaml.YAMLError, AttributeError) as error:
            warnings.append(f"{sha[:7]}：{type(error).__name__}")
            continue
        for entry in entries:
            if isinstance(entry, dict) and entry.get("id") and entry["id"] not in history:
                history[entry["id"]] = {"first_seen": datetime.fromisoformat(committed),
                                        "commit": sha, "entry": entry}
    return history, warnings


# ---------------------------------------------------------------- rendering

def _taipei(iso):
    return datetime.fromisoformat(iso).astimezone(TAIPEI).strftime("%Y-%m-%d %H:%M") if iso else "—"


def _method(record):
    return f"{record['method']} {record['method_version']}" if record.get("method_version") else record["method"]


def _status(record):
    label = STATUS_LABELS.get(record["status"], record["status"])
    return f"{label}：{record['reason']}" if record.get("reason") else label


def _cell(text):
    return str(text).replace("|", "／").replace("\n", " ")


def render_table(records):
    lines = ["| 預測 | 類型 | 方法 | 條件 | 機率 | First seen（台北） | 起算日 | 檢查日 | 狀態 |",
             "| :--- | :--- | :--- | :--- | ---: | :--- | :--- | :--- | :--- |"]
    for r in records:
        lines.append(
            f"| `{r['id']}` | {TRIGGER_LABELS.get(r['trigger'], r['trigger'])} | {_cell(_method(r))} | "
            f"{_cell(r['condition'])} | {r['probability']:.2f} | {_taipei(r['first_seen'])} | "
            f"{r['start_session'] or '—'} | {r['expected_check_session'] or '—'} | {_cell(_status(r))} |")
    if not records:
        lines.append("| — | — | — | 預測紀錄沒有預測 | — | — | — | — | — |")
    return lines


def render_body(records, as_of, run_url):
    ledger_url = f"{REPO_URL}/blob/main/{LEDGER.as_posix()}"
    rules_url = f"{REPO_URL}/blob/main/knowledge/README.md#預測紀錄"
    lines = [MARKER, "# 預測回顧", "",
             f"**{DISCLAIMER}。** 每日 TW 排程讀[預測紀錄]({ledger_url})，列出每筆預測的起算日、檢查日和狀態。"
             f"起算日是預測第一次合併到 main 時最近一個已完成的交易日。寫法見[知識庫 README]({rules_url})。", "",
             f"最後更新：{as_of}（[執行紀錄]({run_url})）", "", *render_table(records)]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- delivery

def sync(sink, entries, history, now, *, run_id, run_url):
    """Create or update the review Issue body from the ledger and its First seen times."""
    as_of = now.astimezone(TAIPEI).date().isoformat()
    records = evaluate(entries, history, now)
    issues = [issue for issue in sink.find(MARKER) if issue.get("state") == "open"]
    if len(issues) > 1:
        raise ValueError("More than one open prediction review Issue")
    number = issues[0]["number"] if issues else sink.create(TITLE, MARKER + "\n初始化中。\n")["number"]
    sink.update(number, render_body(records, as_of, run_url))
    return {"status": "synced", "issue_number": number, "as_of": as_of, "run_id": run_id,
            "records": records}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config-dir", type=Path, default=ROOT / "config")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    failed = False
    try:
        require_review_context(os.environ)
    except ReviewContextError as error:
        result = {"status": "skipped", "reason": str(error)}
    else:
        try:
            entries = load_ledger(ROOT / LEDGER, supported_symbols(args.config_dir))
            history, warnings = ledger_history()
            result = sync(GitHubResearchSink(args.repo), entries, history, datetime.now(timezone.utc),
                          run_id=args.run_id, run_url=args.run_url)
            result["history_warnings"] = warnings
        except Exception as error:  # reported in the receipt and the step summary, then the step fails
            result, failed = {"status": "failed", "error_type": type(error).__name__,
                              "reason": str(error)}, True
    (args.out / "prediction_review_receipt.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "records"}, ensure_ascii=False))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
