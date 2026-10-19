"""F03: SEC day-only filing date is not a same-day published-at timestamp."""
from datetime import date, datetime, timezone

import pytest
from market_research.source_evidence import _availability, build_source_evidence
from scripts import company_report


@pytest.mark.parametrize("cutoff, filing, expected", [
    (datetime(2026, 10, 19, 3, 30, tzinfo=timezone.utc), "2026-10-18",
     "same_day_publication_unverified"),  # 10/18 evening in New York
    (datetime(2026, 10, 19, 3, 30, tzinfo=timezone.utc), "2026-10-17",
     "filed_before_cutoff_date_only"),
    (datetime(2026, 10, 19, 18, 0, tzinfo=timezone.utc), "2026-10-19",
     "same_day_publication_unverified"),
    (datetime(2026, 10, 19, 18, 0, tzinfo=timezone.utc), "2026-10-20",
     "future_filing_not_available"),
])
def test_sec_filing_date_uses_ny_calendar(cutoff, filing, expected):
    assert _availability(filing, cutoff)[0] == expected


@pytest.mark.parametrize("cutoff, expected_asof", [
    (datetime(2026, 10, 19, 3, 30, tzinfo=timezone.utc), date(2026, 10, 17)),
    (datetime(2026, 10, 19, 18, 0, tzinfo=timezone.utc), date(2026, 10, 18)),
])
def test_company_research_filters_raw_sec_facts_before_valuation(
        cutoff, expected_asof, tmp_path, monkeypatch):
    seen = []

    def fake_sec(symbol, asof, **kwargs):
        seen.append(asof)
        return {
            "market": "us", "symbol": symbol, "company_name": "US Operating",
            "profile": {"source": "https://www.sec.gov/files/company_tickers.json"},
            "industry": {"sic": 3571, "source": "https://data.sec.gov/submissions/CIK0000320193.json"},
            "instrument_evidence": {
                "source": "https://data.sec.gov/submissions/CIK0000320193.json",
                "recent_form_types": ["10-K"],
            },
            "facts": [{"metric": "annual_revenue", "value": 100.0, "unit": "USD",
                       "filed": expected_asof.isoformat(), "period_end": "2025-12-31",
                       "source": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"}],
            "financial_history": {"currency": "USD", "period_type": "annual_10k",
                                  "annual_revenue": []},
            "event_feed": {"source": "SEC", "status": "unavailable",
                           "coverage": "not_verified", "events": [],
                           "reason": "fixture", "upcoming_earnings": "not_verified"},
            "warnings": [],
        }

    monkeypatch.setattr(company_report, "sec_fundamentals", fake_sec)
    monkeypatch.setattr(company_report, "load_daily_bars",
                        lambda *args, **kw: (_ for _ in ()).throw(ValueError("fixture market unavailable")))
    result = company_report.run("AAPL", out=tmp_path, now=cutoff)
    assert seen == [expected_asof]
    assert result["schema_version"] == 4
    assert result["financial_comparison"]["status"] == "unavailable"
    assert result["valuation"]["status"] == "not_evaluated"
    assert result["complete"] is False  # pipeline-only legacy behavior
    assert result["source_evidence"]["observations"][0]["availability_status"] == "filed_before_cutoff_date_only"


def test_sec_same_ny_day_not_recognized_as_available_after_utc_rollover():
    now = datetime(2026, 10, 19, 3, 30, tzinfo=timezone.utc)
    issuer = {
        "market": "us", "symbol": "AAPL",
        "facts": [{"metric": "annual_revenue", "value": 100, "unit": "USD",
                   "filed": "2026-10-18", "source": "SEC", "period_end": "2025-12-31"}],
        "financial_history": {},
    }
    evidence = build_source_evidence(issuer, now, now)
    assert evidence["observations"][0]["availability_status"] == "same_day_publication_unverified"
    assert evidence["status"] == "needs_availability_review"
