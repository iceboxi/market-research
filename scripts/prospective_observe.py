"""Prospective research *observations* on future scheduled scan sessions.

No future labels, orders, backfilled observations, or raw OHLCV export.
A separate temporary research strategy config never changes production.
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import shutil
import tempfile

import yaml

from market_research.runner import run_scan
from market_research.market_calendar import expected_complete_session
from scripts.prospective_journal import FREEZE_DATE, fingerprint
from scripts.prospective_state import runtime_revision
from scripts.strategy_research import select_variant


def collect(health, market, output, config_dir=Path("config"), now=None,
            provider=None, revision_pinned=False):
    now = now or datetime.now(timezone.utc)
    if health.get("event") != "schedule" or health.get("health") != "healthy":
        raise ValueError("Only verified healthy scheduled scans can enter prospective study")
    if market not in ("tw", "us") or health.get("market") != market:
        raise ValueError("Invalid single-market scheduled observation")
    session = expected_complete_session(market, now)
    if session <= FREEZE_DATE:
        raise ValueError("Observation session predates research freeze")
    if health.get("requested") != health.get("scanned") or health.get("errors") != 0:
        raise ValueError("Incomplete source coverage")
    sessions = health.get("session_dates", {}).get(market, [])
    if sessions != [session.isoformat()]:
        raise ValueError("Production scan and calendar disagree on completed session")
    config_dir = Path(config_dir)
    original = yaml.safe_load((config_dir / "strategies.yaml").read_text())["strategies"]
    if [r["id"] for r in original if r["enabled"]] != ["sakata_three_soldiers"]:
        raise ValueError("Production strategy activation has changed; new freeze required")
    research = []
    for row in original:
        if row["enabled"] or not row["id"].startswith("sakata_"):
            continue
        variant = select_variant(row["id"])
        research.append({"id": row["id"], "enabled": True, "params": row.get("params", {})})
    if len(research) != 9:
        raise ValueError("Expected nine frozen research-only candidates")
    with tempfile.TemporaryDirectory(prefix="prospective-research-") as tmp:
        cfg = Path(tmp) / "config"
        cfg.mkdir()
        shutil.copyfile(config_dir / "markets.yaml", cfg / "markets.yaml")
        (cfg / "strategies.yaml").write_text(
            yaml.safe_dump({"strategies": research}, sort_keys=False), encoding="utf-8")
        research_out = Path(tmp) / "output"
        result = run_scan(market, "6mo", research_out, cfg, provider=provider,
                          now=now, strict_freshness=True)
        quality = json.loads((research_out / "data_quality.json").read_text())
        observations = json.loads((research_out / "screening_results.json").read_text())
        if result["error_count"] or result["scanned_symbols"] != health["scanned"]:
            raise ValueError("Incomplete prospective research inputs")
        if len(observations) != len(research) * result["scanned_symbols"]:
            raise ValueError("Missing per-strategy research observations")
        if any(row["trade_date"] != session.isoformat() for row in observations):
            raise ValueError("Research signal date differs from completed session")
        # Source hashes must match the production scan's already-verified data.
        expected_hashes = {(r["market"], r["symbol"]): r["sha256"]
                           for r in health["input_hashes"]}
        actual_hashes = {(r["market"], r["symbol"]): r["input_sha256"]
                         for r in quality["symbols"]}
        if expected_hashes != actual_hashes:
            raise ValueError("Production and research source hashes differ")
        revision = runtime_revision() if revision_pinned else None
        if revision_pinned and health.get("source_sha") != revision["code_sha"]:
            raise ValueError("Production scan revision differs from prospective checkout SHA")
        receipt = {
            "schema_version": 2 if revision_pinned else 1,
            "kind": "prospective_observation_only",
            "freeze_date": FREEZE_DATE.isoformat(),
            "freeze_hash": fingerprint(),
            "observed_at_utc": now.isoformat(),
            "session_date": session.isoformat(),
            "market": market, "source_scan_run": health["run_url"],
            "run_id": health["run_id"],
            "source_provenance": health["input_hashes"],
            "strategy_versions": result["strategies"],
            "scanned_symbols": result["scanned_symbols"],
            "observations": [
                {"symbol": row["symbol"], "strategy_id": row["strategy_id"],
                 "strategy_version": row["strategy_version"],
                 "confirmed_date": row["trade_date"]}
                for row in observations if row["matched"]
            ],
            "abstained_count": sum(
                row.get("metrics", {}).get("observation") == "corporate_actions_unverified"
                for row in observations
            ),
            "has_matured_forward_outcomes": False,
            "is_strategy_performance_evidence": False,
        }
        if revision_pinned:
            if receipt["freeze_hash"] != revision["config_sha256"]:
                raise ValueError("Prospective config freeze differs from pinned revision")
            receipt["cohort_revision"] = revision
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(receipt, indent=2, ensure_ascii=False,
                                      allow_nan=False) + "\n", encoding="utf-8")
        return receipt


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--market", required=True, choices=["tw", "us"])
    p.add_argument("--health", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--revision-pinned", action="store_true")
    args = p.parse_args()
    health = json.loads(args.health.read_text(encoding="utf-8"))
    result = collect(health, args.market, args.out,
                     revision_pinned=args.revision_pinned)
    print("Prospective observations:", len(result["observations"]),
          "abstentions:", result["abstained_count"], "no future labels")


if __name__ == "__main__":
    main()
