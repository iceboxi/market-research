from datetime import datetime, timezone
from market_research.research_evidence import evidence_report, instrument_gate

NOW = datetime(2026, 10, 19, 4, tzinfo=timezone.utc)


def test_tw_source_time_is_not_a_fake_release_time():
    issuer = {"market": "tw", "symbol": "2330.TW", "industry_code": "24",
              "facts": [{"metric": "monthly_reported_revenue", "value": 123,
                         "unit": "TWD_thousands", "period": "11509",
                         "reported_at": "1151019", "source": "https://openapi.twse.com.tw/revenue"}]}
    assert instrument_gate(issuer)["generic_fcf"] == "blocked"
    fact = evidence_report(issuer, NOW)["facts"][0]
    assert fact["scale_to_base_unit"] == 1000
    assert fact["currency"] == "TWD"
    assert fact["publication_time"] is None
    assert fact["first_seen_at"] is None
    assert fact["availability_precision"] == "current_snapshot_not_historical"


def test_nonfinancial_us_is_only_a_candidate_not_verified_investment():
    issuer = {"market": "us", "symbol": "AAPL", "industry": {"sic": 3571},
              "facts": [{"metric": "annual_net_income", "value": 99, "unit": "USD",
                         "filed": "2026-10-19", "period_end": "2025-12-31",
                         "accession": "0000320193-26-000001",
                         "source": "https://data.sec.gov/test"}]}
    assert instrument_gate(issuer)["status"] == "candidate_only"
    fact = evidence_report(issuer, NOW)["facts"][0]
    assert fact["filed_date"] == "2026-10-19"
    assert fact["publication_time"] is None
    assert fact["availability_precision"] == "filed_date_only_intraday_unverified"


def test_financial_etf_unknown_are_blocked():
    for issuer in ({"market": "tw", "industry_code": "17"},
                   {"market": "us", "industry": {"sic": 6021}},
                   {"market": "us", "industry": {"sic": 3571}, "instrument_type": "ETF"},
                   {"market": "us", "industry": {"sic": None}}):
        assert instrument_gate(issuer)["generic_fcf"] == "blocked"


def test_invalid_values_not_source_evidence():
    issuer = {"market": "us", "facts": [
        {"metric": "test", "value": float("nan"), "source": "sec", "unit": "USD"},
        {"metric": "test", "value": None, "source": "sec", "unit": "USD"},
        {"metric": "test", "value": 0, "source": "sec", "unit": "USD"}]}
    assert len(evidence_report(issuer, NOW)["facts"]) == 1
