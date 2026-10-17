"""Conservative multi-market research-readiness gate.

This assesses the sufficiency and reproducibility of descriptive historical
holdouts. It NEVER approves investment deployment. "blocked" is a valid,
successful CI result; malformed or missing market inputs are not.
"""
import argparse
from collections import defaultdict
from datetime import date
import json
from pathlib import Path

import yaml


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_report(report, expected_market):
    if report.get("market") != expected_market or report.get("complete") is not True:
        raise ValueError(f"{expected_market}: missing or incomplete holdout report")
    if report.get("error_count") != 0:
        raise ValueError(f"{expected_market}: holdout data errors")
    if report.get("study") != "retrospective_fixed_chronological_holdout":
        raise ValueError("wrong research schema/study")
    strategies = report["strategy_ids"]
    if not strategies or len(strategies) != len(set(strategies)):
        raise ValueError("invalid strategy ID list")
    rows = report["rows"]
    if len(rows) != report["requested_symbols"] * len(strategies):
        raise ValueError("missing strategy/symbol coverage")
    pairs = [(r["strategy_id"], r["symbol"]) for r in rows]
    if len(pairs) != len(set(pairs)):
        raise ValueError("duplicate strategy/symbol reports")
    for r in rows:
        if r["strategy_id"] not in strategies or r["market"] != expected_market:
            raise ValueError("cross-strategy/market contamination")
        if r["nonoverlapping_labeled_events"] != len(r["events"]):
            raise ValueError("event count doesn't match retained event rows")
        if r["raw_holdout_signals"] < len(r["events"]):
            raise ValueError("retained events outnumber raw signals")
        for event in r["events"]:
            if (event["signal_date"] < r["first_test_date"] or
                    event["label_end_date"] > r["test_end_date"] or
                    event["label_end_date"] <= event["signal_date"]):
                raise ValueError("holdout event outside complete label interval")
    return strategies


def gate(tw, us, policy):
    ids = validate_report(tw, "tw")
    if validate_report(us, "us") != ids:
        raise ValueError("markets evaluated different strategy IDs")
    if tw["training_fraction"] != us["training_fraction"] or (
        tw["forward_horizon_sessions"] != us["forward_horizon_sessions"] or
        tw["embargo_sessions"] != us["embargo_sessions"]
    ):
        raise ValueError("temporal methodology differs across markets")
    thresholds = policy["minimums"]
    if thresholds["per_market_events"] < 1 or thresholds["per_market_symbols"] < 1 or thresholds["each_test_half_events"] < 1:
        raise ValueError("invalid evidence thresholds")
    summaries = []
    for name in ids:
        markets = {}
        for report in (tw, us):
            market = report["market"]
            rows = [r for r in report["rows"] if r["strategy_id"] == name]
            count = sum(r["nonoverlapping_labeled_events"] for r in rows)
            symbols = sum(bool(r["events"]) for r in rows)
            first_half, second_half = 0, 0
            for r in rows:
                cutoff = date.fromisoformat(r["first_test_date"]).toordinal()
                finish = date.fromisoformat(r["test_end_date"]).toordinal()
                midpoint = (cutoff + finish) // 2
                for event in r["events"]:
                    if date.fromisoformat(event["signal_date"]).toordinal() <= midpoint:
                        first_half += 1
                    else:
                        second_half += 1
            markets[market] = {
                "events": count, "symbols": symbols,
                "first_half_events": first_half, "second_half_events": second_half,
                "corporate_action_abstentions": sum(
                    r["corporate_action_abstentions"] for r in rows
                ),
                "baseline_is_descriptive": True,
                "adequate": (count >= thresholds["per_market_events"] and
                    symbols >= thresholds["per_market_symbols"] and
                    min(first_half, second_half) >= thresholds["each_test_half_events"]),
            }
        passed_sample = all(v["adequate"] for v in markets.values())
        # Do not convert adjusted analytical-close deltas into simulated P&L.
        # A validated independent execution-cost/corporate-action ledger and
        # genuinely post-freeze outcomes are required for readiness.
        gates = {
            "complete_sources": True,
            "both_markets_sufficient_events_and_breadth": passed_sample,
            "independent_execution_cost_and_dividend_model": False,
            "verified_taiwan_corporate_actions": False,
            "prospective_post_freeze_outcomes": False,
            "multiple_testing_and_selection_bias_review": False,
        }
        summaries.append({
            "strategy_id": name, "markets": markets, "checks": gates,
            "readiness": "blocked", "can_auto_enable": False,
            "why": [k for k, ok in gates.items() if not ok],
        })
    return {
        "schema_version": 1,
        "policy_version": policy["policy_version"],
        "evidence_policy": thresholds,
        "strategies": summaries,
        "all_strategies_readiness": "blocked",
        "production_activation_allowed": False,
        "limitations": [
            "This is a retrospective research-readiness gate, not a performance test.",
            "No independent multiple-testing correction or genuinely new post-freeze sample yet.",
            "The directional analytical-close labels are not executable trade returns.",
            "Costs and verified corporate-action/cashflow coverage are not available.",
            "A successful workflow MUST NOT auto-enable strategies or trade.",
        ],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tw", type=Path, required=True)
    p.add_argument("--us", type=Path, required=True)
    p.add_argument("--policy", type=Path, default=Path("config/research_policy.yaml"))
    p.add_argument("--out", type=Path, default=Path("quality_gate"))
    args = p.parse_args()
    policy = yaml.safe_load(args.policy.read_text(encoding="utf-8"))
    result = gate(read(args.tw), read(args.us), policy)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "gate.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Multi-market research-readiness gate",
        "",
        "This gate does not authorize trading, even if sample counts pass.",
        "",
        "| Strategy | TW events / symbols | US events / symbols | Evidence |",
        "| --- | ---: | ---: | --- |",
    ]
    for row in result["strategies"]:
        tw, us = row["markets"]["tw"], row["markets"]["us"]
        lines.append(
            f"| {row['strategy_id']} | {tw['events']} / {tw['symbols']} | "
            f"{us['events']} / {us['symbols']} | **BLOCKED** |"
        )
    lines += ["", "See gate.json for all unmet gates and temporal breadth.",
              "No investment effectiveness or statistical significance is claimed."]
    (args.out / "gate.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print((args.out / "gate.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
