"""Controlled fixed-input acceptance on a local bare remote; no live GitHub writes."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from market_research.fundamentals import TW_PROFILE, TW_REVENUE
from market_research.research_snapshot import MAX_SNAPSHOT_BYTES, prepare_snapshot
from market_research.research_comparison import render_comparison
from scripts.research_state import SUBJECT, archive, initialize, read, render_publication, publication_comparison
from scripts.state_store import GitStateStore


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def replay(source, repo, out):
    store = GitStateStore(repo)
    remote = store._git("remote", "get-url", "origin").stdout.strip()
    if not Path(remote).is_absolute() or not Path(remote).is_dir():
        raise ValueError("Controlled replay requires an absolute local Git remote")
    raw = source.read_bytes()
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Replay snapshot is oversized")
    initialize(store)  # Explicit isolated fixture namespace; never production.
    receipt = archive(json.loads(raw), store)
    records = read(store)["records"]
    identifier = records[SUBJECT]["pending_publication_id"]
    comparison = publication_comparison(records, identifier)
    snapshots = {v["id"]: v for p, v in records.items() if p.startswith("snapshots/")}
    rendered = render_comparison(comparison, snapshots)
    body = render_publication(records, identifier, store.branch)
    out.mkdir(parents=True, exist_ok=True)
    save(out / "comparison.json", comparison)
    save(out / "receipt.json", {"scope": "controlled_fixture_not_live_data", "archive": receipt})
    (out / "comparison.md").write_text(rendered, encoding="utf-8")
    (out / "fixed_report.md").write_text(body, encoding="utf-8")
    if rendered not in body:
        raise ValueError("Comparison differs between report and artifact")


def accept(out):
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="comparison-replay-") as temp:
        temp = Path(temp)
        remote, checkout = temp / "remote.git", temp / "checkout"
        def git(*args, cwd=temp):
            subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
        git("init", "--bare", "--initial-branch=main", str(remote))
        git("clone", str(remote), str(checkout))
        (checkout / "README.md").write_text("Controlled fixture only\n")
        git("add", ".", cwd=checkout)
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture baseline", cwd=checkout)
        git("push", "origin", "main", cwd=checkout)
        git("switch", "-c", "fixture-analysis", cwd=checkout)
        for index, value in enumerate((1000, 1100)):
            stamp = f"2026-10-19T12:0{index}:00+00:00"
            report = {"schema_version": 4, "symbol": "2330.TW", "market": "tw", "generated_utc": stamp,
                      "started_utc": stamp, "model_identity": "a" * 64, "complete": False,
                      "issuer": {"company_name": "CONTROLLED FIXTURE, NOT LIVE DATA",
                                 "profile": {"source": TW_PROFILE, "reported_at": "1151019"},
                                 "facts": [{"metric": "monthly_reported_revenue", "value": value,
                                            "unit": "TWD_thousands", "period": "11509", "reported_at": "1151010", "source": TW_REVENUE}]},
                      "technical": {"status": "unavailable"},
                      "official_events": {"status": "unavailable", "coverage": "unknown"},
                      "research_readiness": {"components": {}}}
            snapshot = prepare_snapshot(report, {"repository": "controlled/fixture", "run_id": str(100 + index),
                "run_attempt": 1, "code_sha": "a" * 40, "observed_at_utc": stamp})
            source = temp / f"input-{index}.json"
            save(source, snapshot)
            target = out / f"run-{index + 1}"
            subprocess.run([sys.executable, "-m", "scripts.research_diff_replay", "--snapshot", str(source),
                            "--repo", str(checkout), "--out", str(target.resolve())], check=True, timeout=60)
            comparison = json.loads((target / "comparison.json").read_text())
            if comparison["categories"] != [["baseline"], ["revision"]][index]:
                raise ValueError("Fixed-input comparison oracle failed")
        if "1,000 → 1,100 TWD_thousands" not in (target / "comparison.md").read_text():
            raise ValueError("Revision values are absent")
    save(out / "acceptance.json", {"acceptance": "passed", "scope": "controlled_fixture_not_live_data",
                                    "cases": ["baseline", "revision"], "independent_runner_processes": 2})


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--snapshot", type=Path)
    mode.add_argument("--self-test", action="store_true")
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.self_test:
        accept(args.out)
    elif args.repo:
        replay(args.snapshot, args.repo, args.out)
    else:
        parser.error("--snapshot requires --repo")


if __name__ == "__main__":
    main()
