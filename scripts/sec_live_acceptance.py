"""Live SEC-only acceptance of annual financial research without Yahoo dependencies."""
import argparse
from datetime import date
import json
from pathlib import Path

from market_research.fundamentals import sec_fundamentals
from market_research.valuation import evaluate_valuation

METRICS = ("annual_revenue", "annual_net_income", "annual_operating_cash_flow",
           "annual_capex", "annual_diluted_shares", "annual_free_cash_flow")


def assess(issuer, asof):
    history = issuer.get("financial_history") or {}
    coverage = {name: len(history.get(name) or []) for name in METRICS}
    valuation = evaluate_valuation(issuer, asof)
    failures = []
    if issuer.get("market") != "us" or not issuer.get("cik"):
        failures.append("Missing verified SEC issuer identity")
    if not issuer.get("company_name"):
        failures.append("Missing SEC issuer name")
    if min(coverage.values()) < 1:
        failures.append("At least one essential annual financial category is absent")
    if history.get("currency") != "USD" or history.get("period_type") != "annual_10k":
        failures.append("Unsupported annual financial data contract")
    return {
        "schema_version": 1, "symbol": issuer.get("symbol"), "asof": asof.isoformat(),
        "company_name": issuer.get("company_name"), "cik": issuer.get("cik"),
        "source": history.get("source"),
        "industry": issuer.get("industry"),
        "annual_coverage": coverage,
        "valuation_status": valuation["status"],
        "valuation_gate_reason": valuation["why"],
        "warnings": issuer.get("warnings", []),
        "acceptance": "failed" if failures else "passed",
        "failures": failures,
        "scope": "live SEC issuer financial integration; not a validation of intrinsic value or investment recommendation",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--out", type=Path, default=Path("sec_acceptance"))
    parser.add_argument("--asof", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    # Deliberately fail with explicit error if SEC_USER_AGENT is not set:
    # a green "skipped" acceptance would hide the integration gap.
    issuer = sec_fundamentals(args.symbol.upper(), args.asof)
    result = assess(issuer, args.asof)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "acceptance.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    summary = [
        f"# SEC live acceptance — {result['symbol']}",
        "",
        f"Result: **{result['acceptance']}**",
        f"Company: {result['company_name']}",
        f"SEC CIK: {result['cik']}",
        f"As of: {result['asof']}",
        f"SEC source: {result['source']}",
        "",
        "| Annual metric | Available fiscal years |",
        "| --- | ---: |",
    ]
    summary.extend(f"| {key} | {count} |" for key, count in result["annual_coverage"].items())
    summary.extend([
        "", f"Valuation gate: **{result['valuation_status']}**",
        result["valuation_gate_reason"], "",
        "Passing confirms SEC ingestion and required annual fact coverage only.",
        "It does not validate model multiples, fair value or trade execution.", "",
    ])
    if result["failures"]:
        summary += ["## Failures", *("- " + f for f in result["failures"])]
    (args.out / "acceptance.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print((args.out / "acceptance.md").read_text(encoding="utf-8"))
    if result["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
