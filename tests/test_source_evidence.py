"""F01 source evidence and eligibility gates: independent fixture oracles."""
from datetime import datetime, timezone
from pathlib import Path
import json

from market_research.fundamentals import TW_PROFILE
from market_research.source_evidence import (
    instrument_eligibility, build_source_evidence, validate_valuation_inputs,
)
from scripts import company_report

CUTOFF = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
UTC = timezone.utc


def tw(code="24", profile=True):
    return {"symbol": "2330.TW", "market": "tw", "company_name": "台灣積體電路",
            "industry_code": code,
            "profile": {"source": TW_PROFILE if profile else "unknown"},
            "facts": [{"metric": "monthly_reported_revenue", "value": 1000,
                       "unit": "TWD_thousands", "period": "11509",
                       "reported_at": "1151010",
                       "source": "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"}],
            "warnings": []}


def us(sic=3571, forms=None, available="2026-02-01", accession="0000320193-26-000111"):
    leg = {"period_start": "2025-01-01", "period_end": "2025-12-31",
           "filed": available, "unit": "USD", "value": 100.0,
           "form": "10-K", "taxonomy_tag": "Revenues",
           "accession": accession,
           "source": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"}
    fcf = {"period_start": leg["period_start"], "period_end": leg["period_end"],
           "value": 50.0, "unit": "USD", "filed": available,
           "derivation": "operating_cash_flow_minus_positive_capex",
           "operating_cash_flow": leg, "capex": leg}
    return {"symbol": "AAPL", "market": "us", "company_name": "Apple Inc.",
            "profile": {"source": "https://www.sec.gov/files/company_tickers.json"},
            "industry": {"sic": sic, "source": "https://data.sec.gov/submissions/CIK0000320193.json"},
            "instrument_evidence": {
                "source": "https://data.sec.gov/submissions/CIK0000320193.json",
                "recent_form_types": forms if forms is not None else ["10-K"]},
            "facts": [{"metric": "annual_revenue", **leg}],
            "financial_history": {"currency": "USD", "period_type": "annual_10k",
                                   "annual_free_cash_flow": [fcf, fcf, fcf]},
            "warnings": []}


def test_twse_profile_monthly_revenue_remains_current_snapshot_not_ifrs():
    issuer = tw()
    evidence = build_source_evidence(issuer, CUTOFF, retrieved_at=CUTOFF)
    record = evidence["observations"][0]
    assert record["currency"] == "TWD"
    assert record["scale_to_base"] == 1000
    assert record["statement_scope"] is None
    assert record["date_evidence"]["published_at"] is None
    assert record["date_evidence"]["reported_at"] == "1151010"
    assert record["availability_status"] == "current_snapshot_only"
    assert instrument_eligibility(issuer)["status"] == "candidate_for_nonfinancial_research"


def test_tw_bank_and_unknown_issuer_block_generic_model_not_price_observation():
    assert instrument_eligibility(tw(code="17"))["instrument_type"] == "financial_institution"
    assert instrument_eligibility(tw(code=None))["status"] == "unknown"
    assert instrument_eligibility(tw(profile=False))["status"] == "unknown"


def test_us_nonfinancial_financial_fund_and_unknown_identity():
    assert instrument_eligibility(us())["instrument_type"] == "operating_issuer_candidate"
    assert instrument_eligibility(us(sic=6021))["model_status"] == "not_evaluated"
    assert instrument_eligibility(us(sic=3571, forms=["N-PORT"]))["instrument_type"] == "fund_or_etf"
    assert instrument_eligibility(us(sic=None))["status"] == "unknown"
    issuer = us()
    issuer["company_name"] = None
    assert instrument_eligibility(issuer)["status"] == "unknown"


def test_sec_date_only_and_retrieval_are_not_publication_timestamp():
    issuer = us(available="2026-10-19")
    record = build_source_evidence(issuer, CUTOFF, CUTOFF)["observations"][0]
    assert record["availability_status"] == "same_day_publication_unverified"
    assert record["date_evidence"]["published_at"] is None
    assert record["date_evidence"]["first_seen_at"] is None
    assert record["date_evidence"]["availability_precision"] == "date_only"
    assert build_source_evidence(us(available="2027-01-01"), CUTOFF, CUTOFF)["status"] == "needs_availability_review"
    assert build_source_evidence(us(available="invalid"), CUTOFF, CUTOFF)["status"] == "needs_availability_review"


def test_fcfs_only_earlier_known_dates_and_source_identity():
    data = us()
    assert validate_valuation_inputs(data, CUTOFF)["status"] == "date_only_prior_filing"
    data = us(available="2026-10-19")
    assert validate_valuation_inputs(data, CUTOFF)["status"] == "not_verified"
    data = us(accession=None)
    assert validate_valuation_inputs(data, CUTOFF)["status"] == "not_verified"


def test_company_report_v4_preserves_pipeline_complete_semantics(tmp_path, monkeypatch):
    issuer = tw(code="17")
    monkeypatch.setattr(company_report, "twse_fundamentals", lambda symbol, **kw: issuer)
    monkeypatch.setattr(company_report, "tw_material_events", lambda *args: {
        "status": "unavailable", "source": "fixture", "coverage": "not_verified",
        "events": [], "reason": "offline"})
    def fake_loader(*args, **kwargs):
        raise ValueError("No candle feed in fixture")
    monkeypatch.setattr(company_report, "load_daily_bars", fake_loader)
    output = company_report.run("2330.TW", out=tmp_path, now=CUTOFF)
    assert output["schema_version"] == 4
    assert output["complete"] is False  # unchanged legacy technical-pipeline contract
    assert output["instrument_eligibility"]["instrument_type"] == "financial_institution"
    assert output["valuation"]["status"] == "not_evaluated"
    assert output["technical"]["status"] == "unavailable"
    assert "Source evidence and instrument suitability" in (tmp_path / "report.md").read_text()
    assert json.loads((tmp_path / "report.json").read_text())["source_evidence"]["schema_version"] == 1
