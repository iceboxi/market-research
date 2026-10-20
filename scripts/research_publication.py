"""2330 manual publication and isolated live recovery acceptance.

Full provider inputs/report files live only in an ephemeral directory. Exported
artifacts contain the validated compact research namespace and receipts only.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from market_research.research_snapshot import prepare_snapshot
from scripts.company_report import run
from scripts.research_github import GitHubResearchSink
from scripts.research_state import (
    SUBJECT, archive, initialize, marker, publication_comparison, publication_path,
    publish, read, render_publication,
)
from market_research.research_comparison import render_comparison
from scripts.state_store import GitStateStore


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def recover(branch, out):
    store = GitStateStore(branch=branch)
    sink = GitHubResearchSink(os.environ["GITHUB_REPOSITORY"])
    for attempt in range(1, 5):
        result = publish(sink, store)
        result["reconciliation_attempts"] = attempt
        if result.get("reason") != "marker_not_visible_after_attempt" or attempt == 4:
            break
        # Read/reconcile only: the durable creation fence forbids another POST.
        time.sleep(2 * attempt)
    if result["status"] in ("published", "already_current"):
        owner = read(store)["records"].get(SUBJECT)
        expected = owner["issue_number"] if owner else None
        for attempt in range(1, 5):
            matches = sink.find(marker(branch))
            if matches or attempt == 4:
                break
            time.sleep(2 * attempt)
        result["marker_matches"] = sorted(issue["number"] for issue in matches)
        if expected is None or result["marker_matches"] != [expected]:
            result.update(status="blocked", reason="published_identity_not_unique")
    save(out / "publication_receipt.json", result)
    state = read(store)
    save(out / "research_state.json", state)
    subject = state["records"].get(SUBJECT)
    if subject and subject["published_publication_id"]:
        identifier = subject["published_publication_id"]
        body = render_publication(state["records"], identifier, branch)
        (out / "report.md").write_text(body, encoding="utf-8")
        if state["records"][publication_path(identifier)]["renderer_version"] == 2:
            comparison = publication_comparison(state["records"], identifier)
            save(out / "comparison.json", comparison)
            snapshots = {value["id"]: value for path, value in state["records"].items() if path.startswith("snapshots/")}
            rendered = render_comparison(comparison, snapshots)
            (out / "comparison.md").write_text(rendered, encoding="utf-8")
            if rendered not in body:
                raise ValueError("Artifact and fixed report comparison differ")
    if result["status"] not in ("published", "already_current"):
        raise ValueError("Publication is still pending; inspect receipt before retry")
    return result


def require_production_context(daily=False):
    main = os.getenv("GITHUB_REF") == "refs/heads/main"
    event = os.getenv("GITHUB_EVENT_NAME")
    if daily:
        expected = f"{os.environ['GITHUB_REPOSITORY']}/.github/workflows/scan.yml@refs/heads/main"
        if (not main or event not in ("schedule", "workflow_dispatch") or
                os.getenv("GITHUB_WORKFLOW_REF") != expected or
                os.getenv("SCAN_MARKET") not in ("tw", "both")):
            raise ValueError("Daily production requires explicit main TW scan runtime")
    elif not main or event != "workflow_dispatch":
        raise ValueError("Production publication requires explicit main dispatch")


def execute(mode, bootstrap, out, *, report=None, daily=False):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    branch = "research-state-validation" if mode == "validation" else "research-state"
    store = GitStateStore(branch=branch)
    receipt = {"schema_version": 1, "acceptance": "failed", "mode": mode,
               "scope": "2330 snapshot / fixed publication / comparison consistency; natural schedule and historical replay separately accepted",
               "entry": "daily_scan" if daily else "manual",
               "state_branch": branch, "run_url": f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"}
    try:
        if daily and bootstrap:
            raise ValueError("Daily publication cannot initialize production authority")
        if daily and report is None:
            raise ValueError("Daily publication requires the computed report")
        if mode == "production":
            require_production_context(daily)
            if store.main_head() != os.environ["GITHUB_SHA"]:
                raise ValueError("Production publication requires the latest main revision")
        receipt["main_before"] = store.main_head()
        receipt["checkout_before"] = store._git("rev-parse", "HEAD").stdout.strip()
        if mode == "validation" or bootstrap:
            receipt["initialization"] = initialize(store)
        read(store)  # Never silently initialize ordinary production writes.
        with tempfile.TemporaryDirectory(prefix="research-inputs-") as temp:
            if report is None:
                report = run("2330.TW", out=Path(temp))
            snapshot = prepare_snapshot(report, {
                "repository": os.environ["GITHUB_REPOSITORY"], "run_id": os.environ["GITHUB_RUN_ID"],
                "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]), "code_sha": os.environ["GITHUB_SHA"],
                "observed_at_utc": datetime.now(timezone.utc).isoformat(),
            })
        save(out / "snapshot.json", snapshot)
        receipt["archive"] = archive(snapshot, store)
        receipt["repeat"] = archive(snapshot, store)
        if receipt["repeat"]["status"] != "already_current":
            raise ValueError("Snapshot rerun was not idempotent")
        before_publish = read(store)
        receipt["snapshot_id"] = snapshot["id"]
        receipt["pipeline_outcome"] = snapshot["execution"]["status"]
        receipt["pending_saved_with_snapshot"] = bool(before_publish["records"][SUBJECT]["pending_publication_id"])
        if mode == "validation":
            class UncertainReply(GitHubResearchSink):
                """Intentionally lose one successful external write reply."""
                def create(self, title, body):
                    super().create(title, body)
                    raise TimeoutError("controlled reply loss after actual creation")
                def update(self, number, body):
                    super().update(number, body)
                    raise TimeoutError("controlled reply loss after actual update")
            receipt["uncertain_delivery"] = publish(UncertainReply(os.environ["GITHUB_REPOSITORY"]), store)
            if (receipt["uncertain_delivery"]["status"] != "outcome_unknown" or
                    not read(store)["records"][SUBJECT]["pending_publication_id"]):
                raise ValueError("Expected a durable pending item after uncertain delivery")
        # Fresh process uses the real adapter and independently fetches Git.
        command = [sys.executable, "-m", "scripts.research_publication", "--recover-only",
                   "--state-branch", branch, "--out", str(out.resolve())]
        if daily:
            command.append("--daily")
        subprocess.run(command, check=True, timeout=180)
        receipt["publication"] = json.loads((out / "publication_receipt.json").read_text())
        final = json.loads((out / "research_state.json").read_text())
        receipt["fresh_read_commit"] = final["head"]
        if final["records"][SUBJECT]["pending_publication_id"]:
            raise ValueError("Fresh process still sees pending publication")
        receipt["main_after"] = store.main_head()
        receipt["checkout_after"] = store._git("rev-parse", "HEAD").stdout.strip()
        receipt["main_unchanged"] = receipt["main_before"] == receipt["main_after"]
        receipt["checkout_unchanged"] = receipt["checkout_before"] == receipt["checkout_after"]
        if not receipt["main_unchanged"] or not receipt["checkout_unchanged"]:
            raise ValueError("Revision moved during acceptance; inspect before claiming passed")
        receipt["acceptance"] = "passed"
    except Exception as error:
        receipt["error_type"] = type(error).__name__
        raise
    finally:
        save(out / "receipt.json", receipt)
        publication = receipt.get("publication", {})
        (out / "summary.md").write_text(
            f"## 2330 固定研究發布：{receipt['acceptance']}\n\n"
            f"Mode：{mode}；pipeline：{receipt.get('pipeline_outcome', 'unknown')}\n\n"
            f"固定報告：{publication.get('issue_url', '尚未確認；請看 publication_receipt.json')}\n\n"
            "此執行驗收精簡證據保存、固定頁面、發布恢復與比較輸出一致；分類判定另由受控 fixture 驗證。每日 schedule、財報與估值另有工作範圍。\n",
            encoding="utf-8")
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("validation", "production"), default="validation")
    parser.add_argument("--initialize", action="store_true")
    parser.add_argument("--daily", action="store_true", help="Recovery of an explicit TW scan publication")
    parser.add_argument("--recover-only", action="store_true")
    parser.add_argument("--state-branch", choices=("research-state", "research-state-validation"))
    parser.add_argument("--out", type=Path, default=Path("research_publication"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.recover_only:
        if args.state_branch == "research-state":
            require_production_context(args.daily)
        recover(args.state_branch or "research-state-validation", args.out)
    else:
        execute(args.mode, args.initialize, args.out, daily=args.daily)


if __name__ == "__main__":
    main()
