"""Prediction review Issue (#183): one Issue listing every ledger prediction and its status.

Each daily TW run reads the knowledge-base prediction ledger, takes each prediction's First seen
from main's git history, judges due price predictions from official daily bars, rewrites the
Issue body and comments once per run when a prediction turns hit, miss, void or awaiting review.
The body keeps the statuses already announced in a hidden marker. Only the main TW schedule or
dispatch may write; nothing is written back to the repository.
"""
import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo

import yaml

from market_research.market_data import load_daily_bars
from market_research.prediction_ledger import load_ledger, supported_symbols
from market_research.prediction_review import STATUS_LABELS, TRIGGER_LABELS, evaluate, result_text
from market_research.twse import LOOKBACK_MONTHS
from scripts.research_github import GitHubResearchSink

ROOT = Path(__file__).resolve().parents[1]
LEDGER = Path("knowledge") / "predictions.yaml"
REPO_URL = "https://github.com/iceboxi/market-research"
MARKER = "<!-- market-research:prediction-review -->"
STATE_RE = re.compile(r"<!-- prediction-review-state:(.*?) -->", re.S)
STATE_SCHEMA = 1
TITLE = "預測回顧（非買賣建議）"
DISCLAIMER = "非買賣建議"
TAIPEI = ZoneInfo("Asia/Taipei")
# Statuses worth a comment the first time a prediction reaches them.
ANNOUNCED = ("hit", "miss", "void", "awaiting_review")


class ReviewContextError(ValueError):
    pass


def require_review_context(env):
    """Branch, pull-request and validation runs must never write the review Issue."""
    if (env.get("GITHUB_REF") != "refs/heads/main" or
            env.get("GITHUB_EVENT_NAME") not in ("schedule", "workflow_dispatch") or
            env.get("SCAN_MARKET") not in ("tw", "both")):
        raise ReviewContextError("The prediction review writes only from the main TW schedule or dispatch")


# ---------------------------------------------------------------- sources

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


def period_since(since: date, today: date) -> str:
    """The shortest provider period whose months reach back to `since`."""
    months = (today.year * 12 + today.month) - (since.year * 12 + since.month) + 1
    for period, count in sorted(LOOKBACK_MONTHS.items(), key=lambda item: item[1]):
        if count >= months:
            return period
    raise ValueError(f"起算日 {since} 早於行情來源支援的範圍")


def bars_loader(provider, now, closed_sessions=()):
    """`bars_fn(symbol, since)` over the pipeline's routed provider (TWSE, TPEx via FinMind)."""
    today = now.astimezone(TAIPEI).date()

    def bars(symbol, since):
        daily = load_daily_bars(provider, "tw", symbol, period_since(since, today), now,
                                "Asia/Taipei", closed_sessions=closed_sessions)
        return daily.frame
    return bars


# ---------------------------------------------------------------- rendering

def _taipei(iso):
    return datetime.fromisoformat(iso).astimezone(TAIPEI).strftime("%Y-%m-%d %H:%M") if iso else "—"


def _method(record):
    return f"{record['method']} {record['method_version']}" if record.get("method_version") else record["method"]


def _status(record):
    label = STATUS_LABELS.get(record["status"], record["status"])
    detail = result_text(record)
    return f"{label}：{detail}" if detail else label


def _cell(text):
    return str(text).replace("|", "／").replace("\n", " ")


def _check(record):
    return record.get("check_session") or record["expected_check_session"] or "—"


def render_table(records):
    lines = ["| 預測 | 類型 | 方法 | 條件 | 機率 | First seen（台北） | 起算日 | 檢查日 | 狀態 |",
             "| :--- | :--- | :--- | :--- | ---: | :--- | :--- | :--- | :--- |"]
    for r in records:
        lines.append(
            f"| `{r['id']}` | {TRIGGER_LABELS.get(r['trigger'], r['trigger'])} | {_cell(_method(r))} | "
            f"{_cell(r['condition'])} | {r['probability']:.2f} | {_taipei(r['first_seen'])} | "
            f"{r['start_session'] or '—'} | {_check(r)} | {_cell(_status(r))} |")
    if not records:
        lines.append("| — | — | — | 預測紀錄沒有預測 | — | — | — | — | — |")
    return lines


def render_body(records, as_of, run_url, announced):
    ledger_url = f"{REPO_URL}/blob/main/{LEDGER.as_posix()}"
    rules_url = f"{REPO_URL}/blob/main/knowledge/README.md#預測紀錄"
    state = {"schema": STATE_SCHEMA, "as_of": as_of, "announced": announced}
    lines = [MARKER, "# 預測回顧", "",
             f"**{DISCLAIMER}。** 每日 TW 排程讀[預測紀錄]({ledger_url})，判定到期的價格類預測，"
             "在結果第一次出現時於本 Issue 留言。起算日是預測第一次合併到 main 時最近一個已完成的交易日；"
             f"缺行情或來源失敗標為未評估，下次再判定。寫法見[知識庫 README]({rules_url})。", "",
             f"最後更新：{as_of}（[執行紀錄]({run_url})）", "", *render_table(records), "",
             "<!-- prediction-review-state:" + json.dumps(state, sort_keys=True, separators=(",", ":")) + " -->"]
    return "\n".join(lines) + "\n"


def parse_state(body):
    """Statuses already announced, by id; None when the body never had a state."""
    match = STATE_RE.search(body or "")
    if not match:
        return None
    try:
        state = json.loads(match.group(1))
    except json.JSONDecodeError as error:
        raise ValueError(f"狀態不是 JSON：{error.msg}") from None
    announced = state.get("announced") if isinstance(state, dict) else None
    if state.get("schema") != STATE_SCHEMA or not isinstance(announced, dict) or any(
            value not in ANNOUNCED for value in announced.values()):
        raise ValueError("狀態格式不符")
    return announced


def render_comment(changes, as_of, run_id, run_url, note=None):
    lines = [f"<!-- prediction-review-run:{run_id} -->", f"## 預測結果：{as_of}（{DISCLAIMER}）", ""]
    if note:
        lines += [f"前次狀態無法使用（{note}），以下可能包含已經通知過的結果。", ""]
    lines += ["| 預測 | 條件 | 機率 | 起算日 | 檢查日 | 結果 |", "| :--- | :--- | ---: | :--- | :--- | :--- |"]
    for r in changes:
        lines.append(f"| `{r['id']}` | {_cell(r['condition'])} | {r['probability']:.2f} | "
                     f"{r['start_session'] or '—'} | {_check(r)} | {_cell(_status(r))} |")
    lines += ["", f"到期的預測請在對話中說「週回顧」寫回顧。執行紀錄：{run_url}"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- delivery

def sync(sink, entries, history, now, *, run_id, run_url, bars_fn=None, closed_sessions=()):
    """Create or update the review Issue; comment once per run when a result first appears."""
    as_of = now.astimezone(TAIPEI).date().isoformat()
    records = evaluate(entries, history, now, bars_fn, closed_sessions)
    issues = [issue for issue in sink.find(MARKER) if issue.get("state") == "open"]
    if len(issues) > 1:
        raise ValueError("More than one open prediction review Issue")
    number, previous, note = None, {}, None
    if issues:
        number = issues[0]["number"]
        try:
            previous = parse_state(issues[0].get("body")) or {}
        except ValueError as error:
            note = str(error)
    current = {r["id"]: r["status"] for r in records if r["status"] in ANNOUNCED}
    changes = [r for r in records if r["id"] in current and previous.get(r["id"]) != r["status"]]
    announced = {**previous, **current}
    if number is None:
        # The state lands only after the comment, so a failed comment is retried next run.
        number = sink.create(TITLE, MARKER + "\n初始化中。\n")["number"]
    comment = "not_needed"
    if changes:
        run_marker = f"<!-- prediction-review-run:{run_id} -->"
        if sink.find_comments(number, run_marker):
            comment = "already_posted"
        else:
            sink.create_comment(number, render_comment(changes, as_of, run_id, run_url, note))
            comment = "posted"
    sink.update(number, render_body(records, as_of, run_url, announced))
    return {"status": "synced", "issue_number": number, "as_of": as_of, "run_id": run_id,
            "comment": comment, "changes": [r["id"] for r in changes], "note": note,
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
            from market_research.provider import RoutedDailyProvider
            now = datetime.now(timezone.utc)
            entries = load_ledger(ROOT / LEDGER, supported_symbols(args.config_dir))
            history, warnings = ledger_history()
            provider = RoutedDailyProvider()
            closed = provider.unscheduled_closures("tw", now)
            result = sync(GitHubResearchSink(args.repo), entries, history, now,
                          run_id=args.run_id, run_url=args.run_url,
                          bars_fn=bars_loader(provider, now, closed), closed_sessions=closed)
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
