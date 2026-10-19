"""I01: shared compute-only seam and independent research evidence gates."""
from datetime import datetime, date, timezone
from types import MappingProxyType

import pytest

from market_research import research_engine
from market_research.research_engine import compute_research, component_readiness


NOW = datetime(2026, 10, 19, 3, 30, tzinfo=timezone.utc)


def tw_issuer(industry="24"):
    return {
        "symbol": "2330.TW", "market": "tw", "company_name": "Taiwan semiconductor",
        "industry_code": industry, "profile": {
            "source": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"},
        "facts": [{"metric": "monthly_reported_revenue", "value": 1000.0,
                   "unit": "TWD_thousands", "period": "11509",
                   "source": "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"}],
        "warnings": [],
    }


def events(status="available", new_event=False):
    return {
        "status": status,
        "source": "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
        "coverage": "recent_daily_snapshot_only_not_a_full_history" if status == "available" else "not_verified",
        "events": ([{"event_id": "tw-material-abc",
                    "published_at": "2026-10-18T09:00:00+08:00"}]
                   if new_event else []),
    }


def technical(status="available"):
    return {
        "status": status, "observations": [
            {"strategy_id": "sakata_three_soldiers",
             "active": True, "matched": True},
            {"strategy_id": "sakata_morning_star",
             "active": False, "matched": True},
        ], "errors": [],
    }


def test_tw_pipeline_components_do_not_infer_trade_recommendation():
    result = compute_research(
        tw_issuer(), technical(), events(), "2330.TW", "tw", NOW,
    )
    components = result["research_readiness"]["components"]
    assert result["valuation"]["status"] == "not_evaluated"
    assert result["financial_comparison"]["status"] == "unavailable"
    assert components["instrument"]["status"] == "candidate_for_nonfinancial_research"
    assert components["financial"]["status"] == "unavailable"
    assert components["technical"]["status"] == "available"
    assert components["valuation"]["status"] == "not_evaluated"
    assert components["trade_plan"]["status"] == "not_evaluated"
    assert components["recommendation"]["status"] == "not_available"
    assert result["research_readiness"]["active_pattern_observations"] == ["sakata_three_soldiers"]
    assert result["research_readiness"]["source_ready_for_recommendation"] is False


def test_financial_instrument_and_stale_technical_gates_are_independent():
    result = compute_research(
        tw_issuer(industry="17"), technical("partial"),
        events("unavailable"), "2330.TW", "tw", NOW,
    )
    c = result["research_readiness"]["components"]
    assert c["instrument"]["status"] != "candidate_for_nonfinancial_research"
    assert c["technical"]["status"] == "partial"
    assert c["events"]["status"] == "coverage_incomplete"
    assert c["trade_plan"]["status"] == "not_evaluated"


def test_recent_official_event_requires_manual_review_not_buy():
    result = compute_research(
        tw_issuer(), technical(), events(new_event=True), "2330.TW", "tw", NOW,
    )
    c = result["research_readiness"]["components"]
    assert c["events"]["status"] == "manual_review_required"
    assert c["recommendation"]["status"] == "not_available"
    assert result["event_risk"]["review_required"] is True


def test_us_date_only_guard_keeps_new_york_calendar(monkeypatch):
    seen = []
    def fake_valuation(issuer, asof):
        seen.append(("valuation", asof))
        return {"status": "illustrative_only",
                "fair_value_scenarios": {"base": {"indicative_usd_per_share": 100.0}},
                "why": None}
    def fake_financial(issuer, asof):
        seen.append(("financial", asof))
        return {"status": "available", "rows": [], "warnings": []}
    monkeypatch.setattr(research_engine, "evaluate_valuation", fake_valuation)
    monkeypatch.setattr(research_engine, "compare_financials", fake_financial)
    monkeypatch.setattr(research_engine, "instrument_eligibility",
                        lambda issuer: {"status": "candidate_for_nonfinancial_research", "reason": None})
    monkeypatch.setattr(research_engine, "validate_valuation_inputs",
                        lambda issuer, now: {"status": "date_only_prior_filing"})
    monkeypatch.setattr(research_engine, "build_source_evidence",
                        lambda issuer, now: {"status": "available"})
    monkeypatch.setattr(research_engine, "evaluate_events",
                        lambda feed, now: {"status": "no_recent_observed_events"})
    issuer = {"symbol": "AAPL", "market": "us", "company_name": "Apple", "facts": []}
    result = compute_research(
        issuer, technical(), events(), "AAPL", "us", NOW,
    )
    assert seen == [("valuation", date(2026, 10, 17)),
                    ("financial", date(2026, 10, 17))]
    assert result["valuation"]["status"] == "illustrative_only"
    assert result["research_readiness"]["components"]["financial"]["status"] == "available"


def test_bad_identity_and_naive_time_fail_before_calculation():
    with pytest.raises(ValueError, match="timezone"):
        compute_research(tw_issuer(), technical(), events(), "2330.TW", "tw",
                         datetime(2026, 10, 19))
    with pytest.raises(ValueError, match="symbol"):
        compute_research(tw_issuer(), technical(), events(), "2317.TW", "tw", NOW)
    with pytest.raises(ValueError, match="market"):
        compute_research(tw_issuer(), technical(), events(), "2330.TW", "us", NOW)


def test_component_readiness_uses_explicit_unavailable_states():
    result = component_readiness(
        eligibility={"status": "unknown", "reason": "Issuer unidentified"},
        evidence={"status": "needs_availability_review"},
        source_gate={"status": "not_verified", "reason": "Date only"},
        financial={"status": "unavailable", "warnings": ["No annual data"]},
        technical={"status": "unavailable"},
        valuation={"status": "not_evaluated", "why": "No comparable data"},
        event_risk={"status": "coverage_incomplete"},
    )
    assert result["source_evidence"]["status"] == "needs_availability_review"
    assert result["valuation_provenance"]["status"] == "not_verified"
    assert result["financial"]["reason"] == "No annual data"
    assert result["events"]["status"] == "coverage_incomplete"
    assert result["recommendation"]["status"] == "not_available"
