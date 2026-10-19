"""F04-B1 synthetic cumulative SEC facts. Not evidence of a live filing."""
from datetime import date
import copy

import pytest

from market_research.quarter_derivation import QuarterDerivationError, derive_cumulative_quarter

ASOF = date(2025, 3, 1)


def record(start, end, value, accession, filed, **kwargs):
    row = {
        "issuer": "CIK0000320193", "metric": "revenue", "unit": "USD",
        "currency": "USD", "scale": 0, "taxonomy_tag": "Revenues",
        "statement_scope": "consolidated", "accounting_basis": "US_GAAP",
        "source": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
        "comparability_key": "reviewed-synthetic-fy2024-revision-a",
        "period_start": start, "period_end": end, "filed": filed,
        "accession": accession, "value": value,
        "selection_status": "unambiguous_asof", "dimensions": [],
    }
    row.update(kwargs)
    return row


Q1 = record("2024-01-01", "2024-03-31", 100, "10q1", "2024-05-01")
H1 = record("2024-01-01", "2024-06-30", 240, "10q2", "2024-08-01")
M9 = record("2024-01-01", "2024-09-30", 390, "10q3", "2024-11-01")
FY = record("2024-01-01", "2024-12-31", 550, "10k", "2025-02-15")


@pytest.mark.parametrize("left,right,quarter,span,value", [
    (Q1, H1, "Q2", ("2024-04-01", "2024-06-30"), 140),
    (H1, M9, "Q3", ("2024-07-01", "2024-09-30"), 150),
    (M9, FY, "Q4", ("2024-10-01", "2024-12-31"), 160),
])
def test_expected_candidate_and_complete_input_lineage(left, right, quarter, span, value):
    result = derive_cumulative_quarter(left, right, asof=ASOF)
    assert result["quarter"] == quarter
    assert result["value"] == value
    assert (result["period_start"], result["period_end"]) == span
    assert result["status"] == "derived_candidate_only"
    assert result["source_acceptance"] == "not_evaluated"
    assert result["filing_revision_alignment_verified"] is False
    assert [r["accession"] for r in result["inputs"]] == [left["accession"], right["accession"]]


def test_53_week_noncalendar_fiscal_boundaries():
    q1 = record("2023-10-01", "2023-12-30", 100, "a", "2024-02-01")
    h1 = record("2023-10-01", "2024-04-06", 210, "b", "2024-05-01")
    result = derive_cumulative_quarter(q1, h1, asof=ASOF)
    assert result["quarter"] == "Q2"
    assert result["period_start"] == "2023-12-31"
    assert result["period_end"] == "2024-04-06"


@pytest.mark.parametrize("alter", [
    {"issuer": "CIK0000000001"}, {"metric": "net_income"}, {"unit": "EUR"},
    {"currency": "EUR"}, {"scale": 3}, {"taxonomy_tag": "OtherSales"},
    {"statement_scope": "separate"}, {"accounting_basis": "IFRS"},
    {"source": "https://data.sec.gov/other"}, {"comparability_key": "different"},
    {"period_start": "2024-04-01"}, {"dimensions": ["segment-a"]},
    {"selection_status": "ambiguous_filing_versions"}, {"accession": ""},
    {"value": float("nan")}, {"value": True},
])
def test_incompatible_facts_fail_closed(alter):
    with pytest.raises(QuarterDerivationError):
        derive_cumulative_quarter(Q1, {**H1, **alter}, asof=ASOF)


@pytest.mark.parametrize("metric", ["basic_eps", "diluted_eps", "gross_margin_pct",
                                    "diluted_shares", "fcf", "shares_outstanding"])
def test_nonsummable_metric_rejected(metric):
    with pytest.raises(QuarterDerivationError):
        derive_cumulative_quarter({**Q1, "metric": metric},
                                  {**H1, "metric": metric}, asof=ASOF)


def test_filing_date_only_cutoff_and_future_amendment():
    with pytest.raises(QuarterDerivationError):
        derive_cumulative_quarter(Q1, H1, asof=date(2024, 7, 1))
    with pytest.raises(QuarterDerivationError):
        derive_cumulative_quarter(Q1, H1, asof="2025-03-01")
    with pytest.raises(QuarterDerivationError):
        derive_cumulative_quarter(Q1, {**H1, "filed": "2025-04-01"}, asof=ASOF)
    with pytest.raises(QuarterDerivationError):
        derive_cumulative_quarter({**Q1, "filed": "2024-09-01"}, H1, asof=ASOF)


def test_missing_provenance_invalid_calendar_and_timestamp_fail_closed():
    bad = copy.deepcopy(H1)
    del bad["comparability_key"]
    with pytest.raises(QuarterDerivationError):
        derive_cumulative_quarter(Q1, bad, asof=ASOF)
    for candidate in ["2024-13-01", "2024-01-01T00:00:00Z", "2024-6-01"]:
        with pytest.raises(QuarterDerivationError):
            derive_cumulative_quarter(Q1, {**H1, "period_end": candidate}, asof=ASOF)


def test_q4_cannot_be_fabricated_without_nine_month_basis():
    with pytest.raises(QuarterDerivationError):
        derive_cumulative_quarter(Q1, FY, asof=ASOF)


def test_nonadjacent_and_short_periods_fail_closed():
    with pytest.raises(QuarterDerivationError):
        derive_cumulative_quarter(Q1, {**H1, "period_end": "2024-10-15"}, asof=ASOF)
    with pytest.raises(QuarterDerivationError):
        derive_cumulative_quarter(Q1, {**H1, "period_end": "2024-05-01"}, asof=ASOF)


def test_revision_alignment_not_inferred_from_matching_comparability_key():
    first = derive_cumulative_quarter(Q1, H1, asof=ASOF)
    later = derive_cumulative_quarter(
        {**Q1, "accession": "amended-q1", "filed": "2024-07-01"}, H1, asof=ASOF
    )
    assert first["source_acceptance"] == later["source_acceptance"] == "not_evaluated"
    assert first["inputs"] != later["inputs"]
