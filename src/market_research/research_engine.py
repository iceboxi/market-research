"""Pure company research computation shared by scan, on-demand and future watchlist.

No HTTP, market-data fetches, Git state, wall-clock calls or artifact writes.
All inputs are already acquired snapshots; evidence gates can block outputs.
"""
from datetime import timedelta
from zoneinfo import ZoneInfo

from .company_analysis import compare_financials, research_status
from .event_risk import evaluate_events
from .source_evidence import (
    instrument_eligibility, build_source_evidence, validate_valuation_inputs,
)
from .valuation import evaluate_valuation

# Bump when this module's research/model contract changes; strategy models have
# their own existing versions. Formatting-only commits are not model changes.
RESEARCH_CONTRACT_VERSION = 1


def _component(status, reason=None):
    return {"status": status, "reason": reason}


def component_readiness(eligibility, evidence, source_gate, financial,
                        technical, valuation, event_risk):
    """Independent evidence states; never a buy or sell recommendation."""
    financial_status = financial.get("status", "unavailable")
    technical_status = technical.get("status", "unavailable")
    valuation_status = valuation.get("status", "not_evaluated")
    event_status = event_risk.get("status", "coverage_incomplete")
    if event_status == "manual_review_required":
        event_reason = "Recent official disclosures require content and impact review"
    elif event_status == "coverage_incomplete":
        event_reason = "Official event source coverage is not verified"
    else:
        event_reason = "No recent event observed within the limited verified source window"

    return {
        "instrument": _component(eligibility.get("status", "unknown"),
                                 eligibility.get("reason")),
        "source_evidence": _component(evidence.get("status", "unavailable"),
                                      "Source timestamps and historical availability require verification"
                                      if evidence.get("status") != "available" else None),
        "valuation_provenance": _component(source_gate.get("status", "not_verified"),
                                            source_gate.get("reason")),
        "financial": _component(financial_status,
                                 "; ".join(financial.get("warnings", [])) or None),
        "technical": _component(technical_status,
                                 "Check source freshness and failed strategy observations"
                                 if technical_status != "available" else None),
        "valuation": _component(valuation_status, valuation.get("why")),
        "events": _component(event_status, event_reason),
        "trade_plan": _component("not_evaluated",
                                 "Execution price basis, costs and trade risk are not validated"),
        "recommendation": _component("not_available",
                                     "Research evidence does not authorize buy/sell advice"),
    }


def compute_research(issuer, technical, event_feed, symbol, market, now):
    """Return computed sections of company report v4 without external I/O.

    The caller ensures official snapshots were acquired consistently with the
    evaluation cutoff. This function does not make live-data claims.
    """
    if now.tzinfo is None:
        raise ValueError("Evaluation timestamp must have a timezone")
    if market not in ("tw", "us") or issuer.get("market") != market:
        raise ValueError("Issuer market does not match report market")
    if not isinstance(symbol, str) or issuer.get("symbol") != symbol:
        raise ValueError("Issuer symbol does not match report identity")
    if not isinstance(technical, dict) or not isinstance(event_feed, dict):
        raise TypeError("Technical and official event snapshots must be mappings")

    event_risk = evaluate_events(event_feed, now)
    eligibility = instrument_eligibility(issuer)
    evidence = build_source_evidence(issuer, now)
    source_gate = validate_valuation_inputs(issuer, now)
    # The original source ingestion uses prior New York filing date for SEC.
    annual_cutoff = (
        now.astimezone(ZoneInfo("America/New_York")).date() - timedelta(days=1)
        if market == "us" else now.date()
    )
    valuation = evaluate_valuation(issuer, annual_cutoff)
    if valuation["status"] == "illustrative_only" and (
        eligibility["status"] != "candidate_for_nonfinancial_research" or
        source_gate["status"] not in ("date_only_prior_filing", "reconciled_tw_dual_track")
    ):
        valuation = {
            "status": "not_evaluated", "method": None,
            "fair_value_scenarios": None,
            "entry_zone": None, "stop_loss": None, "target_price": None,
            "why": "Research eligibility or source provenance gate incomplete",
        }
    financial = compare_financials(issuer, annual_cutoff)
    readiness = research_status(financial, valuation, technical)
    readiness["instrument_status"] = eligibility["status"]
    readiness["source_evidence_status"] = evidence["status"]
    readiness["valuation_source_gate"] = source_gate["status"]
    readiness["trade_plan_status"] = "not_evaluated"
    readiness["source_ready_for_recommendation"] = False
    readiness["components"] = component_readiness(
        eligibility, evidence, source_gate, financial, technical, valuation, event_risk,
    )
    return {
        "instrument_eligibility": eligibility,
        "source_evidence": evidence,
        "valuation_source_gate": source_gate,
        "valuation": valuation,
        "financial_comparison": financial,
        "research_readiness": readiness,
        "event_risk": event_risk,
    }
