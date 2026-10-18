from datetime import date
from scripts.sec_live_acceptance import assess


def test_sec_acceptance_good_history_preserves_no_valuation_claim():
    issuer = {
        "symbol": "AAPL", "market": "us", "cik": "0000320193",
        "company_name": "Apple Inc.", "industry": {"sic": 3571},
        "financial_history": {
            "source": "https://data.sec.gov/test", "currency": "USD",
            "period_type": "annual_10k",
            **{m: [{"value": 10}] for m in (
                "annual_revenue", "annual_net_income", "annual_operating_cash_flow",
                "annual_capex", "annual_diluted_shares", "annual_free_cash_flow"
            )},
        },
    }
    outcome = assess(issuer, date(2026, 10, 18))
    assert outcome["acceptance"] == "passed"
    assert outcome["valuation_status"] == "not_evaluated"
    assert not outcome["failures"]


def test_sec_acceptance_rejects_missing_cashflow_coverage():
    issuer = {"symbol": "AAPL", "market": "us", "cik": "0000320193",
              "company_name": "Apple Inc.",
              "financial_history": {"currency": "USD", "period_type": "annual_10k"}}
    outcome = assess(issuer, date(2026, 10, 18))
    assert outcome["acceptance"] == "failed"
    assert "essential annual" in outcome["failures"][0]
