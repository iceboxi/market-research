"""F04-C: manually transcribed Apple FY2024 SEC filing net-sales reconciliation.

Source documents and filed dates are cited in docs/F04_APPLE_FY2024_RECONCILIATION.md.
Numbers are USD *millions* in disclosures, converted to original USD in tests.
This is source-observed arithmetic, NOT automatically fetched or rights-cleared
CompanyFacts. Revision comparability and exact published_at remain unverified.
"""
from datetime import date

import pytest

from market_research.quarter_derivation import (
    QuarterDerivationError, derive_cumulative_quarter,
)
from market_research.ttm_candidates import build_ttm_candidate

SOURCE = "https://www.sec.gov/Archives/edgar/data/320193"
ASOF = date(2024, 11, 1)
MILLION = 1_000_000


def cumulative(end, value_millions, accession, filed):
    return {
        "issuer": "CIK0000320193",
        "metric": "revenue", "unit": "USD", "currency": "USD",
        "scale": 0, "taxonomy_tag": "RevenueFromContractWithCustomerExcludingAssessedTax",
        "statement_scope": "consolidated", "accounting_basis": "US_GAAP",
        "source": SOURCE,
        "comparability_key": "aapl-fy2024-manual-provisional",
        "fiscal_calendar_id": "aapl-fy2024-52week",
        "period_start": "2023-10-01", "period_end": end,
        "filed": filed, "accession": accession,
        "value": value_millions * MILLION,
        "selection_status": "unambiguous_asof", "dimensions": [],
    }


Q1 = cumulative("2023-12-30", 119575, "0000320193-24-000006", "2024-02-02")
H1 = cumulative("2024-03-30", 210328, "0000320193-24-000069", "2024-05-03")
M9 = cumulative("2024-06-29", 296105, "0000320193-24-000081", "2024-08-02")
FY = cumulative("2024-09-28", 391035, "0000320193-24-000123", "2024-11-01")

# Independently published, source-observed quarterly net-sales comparisons.
REPORTED_Q2 = 90753 * MILLION
REPORTED_Q3 = 85777 * MILLION
REPORTED_Q4_8K = 94930 * MILLION  # 8-K accession 0000320193-24-000120, filed 2024-10-31


def direct_q1():
    return {
        **Q1, "status": "direct_quarter_unverified",
        "source_acceptance": "not_evaluated", "form": "10-Q",
        "publication_time_verified": False,
    }


def derived_quarters():
    return [
        derive_cumulative_quarter(Q1, H1, asof=ASOF),
        derive_cumulative_quarter(H1, M9, asof=ASOF),
        derive_cumulative_quarter(M9, FY, asof=ASOF),
    ]


def test_original_filing_cumulative_quarter_arithmetic_against_disclosures():
    q2, q3, q4 = derived_quarters()
    assert [x["quarter"] for x in (q2, q3, q4)] == ["Q2", "Q3", "Q4"]
    assert [x["value"] for x in (q2, q3, q4)] == [
        REPORTED_Q2, REPORTED_Q3, REPORTED_Q4_8K,
    ]
    assert q4["inputs"][1]["accession"] == "0000320193-24-000123"
    assert all(x["source_acceptance"] == "not_evaluated" for x in (q2, q3, q4))
    assert all(x["filing_revision_alignment_verified"] is False
               for x in (q2, q3, q4))


def test_four_quarter_ttm_reconciles_fy2024_10k():
    ttm = build_ttm_candidate([derived_quarters()[2], direct_q1(),
                               derived_quarters()[0], derived_quarters()[1]], asof=ASOF)
    assert ttm["value"] == FY["value"] == 391035 * MILLION
    assert [q["value"] // MILLION for q in ttm["quarters"]] == [
        119575, 90753, 85777, 94930,
    ]
    assert ttm["source_acceptance"] == "not_evaluated"


def test_october_31_8k_does_not_backfill_november_1_10k():
    with pytest.raises(QuarterDerivationError):
        derive_cumulative_quarter(M9, FY, asof=date(2024, 10, 31))
    with pytest.raises(QuarterDerivationError):
        build_ttm_candidate(
            [direct_q1(), *derived_quarters()], asof=date(2024, 10, 31))


def test_cross_accession_amendment_provenance_remains_unverified():
    q4 = derived_quarters()[2]
    assert q4["inputs"][0]["accession"] != q4["inputs"][1]["accession"]
    assert q4["historical_publication_verified"] is False
    assert q4["availability_precision"] == "filing_date_only_not_intraday"
