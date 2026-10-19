"""F04-B2 TTM fixtures: candidate arithmetic, not real SEC filing acceptance."""
from datetime import date, timedelta

import pytest

from market_research.quarter_derivation import QuarterDerivationError, derive_cumulative_quarter
from market_research.ttm_candidates import build_ttm_candidate

CUTOFF = date(2025, 4, 15)
SOURCE = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"


def original(start, end, value, accession, filed, **overrides):
    item = {
        "issuer": "CIK0000320193", "metric": "revenue", "unit": "USD",
        "currency": "USD", "scale": 0, "taxonomy_tag": "Revenues",
        "statement_scope": "consolidated", "accounting_basis": "US_GAAP",
        "source": SOURCE, "comparability_key": "reviewed-synthetic-filing-family",
        "fiscal_calendar_id": "synthetic-fiscal-calendar-52-week",
        "period_start": start, "period_end": end,
        "filed": filed, "accession": accession,
        "value": value, "selection_status": "unambiguous_asof",
        "dimensions": [],
    }
    item.update(overrides)
    return item


def direct(start, end, value, accession, filed, **overrides):
    return {**original(start, end, value, accession, filed, **overrides),
            "status": "direct_quarter_unverified", "source_acceptance": "not_evaluated",
            "form": overrides.get("form", "10-Q"), "publication_time_verified": False}


Q1 = original("2024-01-01", "2024-03-31", 100, "q1", "2024-05-01")
H1 = original("2024-01-01", "2024-06-30", 240, "q2", "2024-08-01")
M9 = original("2024-01-01", "2024-09-30", 390, "q3", "2024-11-01")
FY = original("2024-01-01", "2024-12-31", 550, "fy", "2025-02-15")


def quarter_chain():
    return [
        direct("2024-01-01", "2024-03-31", 100, "q1", "2024-05-01"),
        derive_cumulative_quarter(Q1, H1, asof=CUTOFF),
        derive_cumulative_quarter(H1, M9, asof=CUTOFF),
        derive_cumulative_quarter(M9, FY, asof=CUTOFF),
    ]


def test_ttm_four_quarters_preserves_origins_and_candidate_status():
    result = build_ttm_candidate(quarter_chain(), asof=CUTOFF)
    assert result["value"] == 550
    assert result["quarter_count"] == 4
    assert result["period_start"] == "2024-01-01"
    assert result["period_end"] == "2024-12-31"
    assert [q["value"] for q in result["quarters"]] == [100, 140, 150, 160]
    assert result["source_acceptance"] == "not_evaluated"
    assert result["filing_revision_alignment_verified"] is False
    assert result["historical_publication_verified"] is False
    assert result["quarters"][3]["accessions"] == ["q3", "fy"]
    assert result["quarters"][3]["source_inputs"] == [M9, FY]


def test_input_order_does_not_change_ttm_semantics():
    a = quarter_chain()
    assert build_ttm_candidate([a[3], a[1], a[0], a[2]], asof=CUTOFF) == (
        build_ttm_candidate(a, asof=CUTOFF))


def test_four_explicit_direct_reported_quarters():
    all_direct = [
        direct("2024-01-01", "2024-03-31", 10, "q1", "2024-05-01"),
        direct("2024-04-01", "2024-06-30", 11, "q2", "2024-08-01"),
        direct("2024-07-01", "2024-09-30", 12, "q3", "2024-11-01"),
        direct("2024-10-01", "2024-12-31", 13, "q4", "2025-02-15", form="10-K"),
    ]
    assert build_ttm_candidate(all_direct, asof=CUTOFF)["value"] == 46


def test_noncalendar_53_week_fiscal_year():
    start = date(2023, 10, 1)
    lengths = [91, 91, 91, 98]
    values = [5, 6, 7, 8]
    pieces = []
    for i, (days, value) in enumerate(zip(lengths, values), 1):
        end = start + timedelta(days=days - 1)
        pieces.append(direct(start.isoformat(), end.isoformat(), value,
                             f"f{i}", "2025-02-15"))
        start = end + timedelta(days=1)
    result = build_ttm_candidate(pieces, asof=CUTOFF)
    assert result["value"] == 26
    assert (date.fromisoformat(result["period_end"]) -
            date.fromisoformat(result["period_start"])).days + 1 == 371


@pytest.mark.parametrize("count", [0, 1, 3, 5])
def test_requires_exactly_four_quarters(count):
    with pytest.raises(QuarterDerivationError):
        build_ttm_candidate(quarter_chain()[:count] + (
            [quarter_chain()[0]] if count == 5 else []), asof=CUTOFF)


@pytest.mark.parametrize("alter", [
    {"issuer": "CIK0000000001"}, {"metric": "net_income"},
    {"unit": "EUR"}, {"currency": "EUR"}, {"scale": 1},
    {"taxonomy_tag": "Other"}, {"statement_scope": "individual"},
    {"accounting_basis": "IFRS"}, {"source": "https://data.sec.gov/other"},
    {"comparability_key": "incomparable"}, {"fiscal_calendar_id": "other-calendar"},
    {"value": float("inf")}, {"value": True}, {"selection_status": "ambiguous"},
    {"dimensions": ["segment"]}, {"accession": ""}, {"form": "8-K"},
    {"source_acceptance": "accepted"}, {"publication_time_verified": True},
])
def test_rejects_bad_or_incompatible_direct_source(alter):
    chain = quarter_chain()
    # Modify Q1 raw fact: same fiscal time, but changed source semantics.
    chain[0] = {**chain[0], **alter}
    with pytest.raises(QuarterDerivationError):
        build_ttm_candidate(chain, asof=CUTOFF)


@pytest.mark.parametrize("alter", [
    {"period_start": "2024-04-02"},
    {"period_end": "2024-07-01"},
    {"value": 999},
    {"quarter": "Q4"},
    {"unit": "EUR"},
    {"status": "direct_quarter_unverified"},
    {"source_acceptance": "accepted"},
    {"filing_revision_alignment_verified": True},
    {"historical_publication_verified": True},
    {"asof": "2024-01-01"},
])
def test_derived_candidate_tampering_is_rejected(alter):
    chain = quarter_chain()
    chain[1] = {**chain[1], **alter}
    with pytest.raises(QuarterDerivationError):
        build_ttm_candidate(chain, asof=CUTOFF)


def test_derived_original_facts_are_revalidated():
    chain = quarter_chain()
    f = dict(chain[2])
    original_inputs = [dict(p) for p in f["inputs"]]
    original_inputs[1]["value"] = 999
    f["inputs"] = original_inputs
    chain[2] = f
    with pytest.raises(QuarterDerivationError):
        build_ttm_candidate(chain, asof=CUTOFF)


def test_derived_cross_fiscal_calendar_fails():
    chain = quarter_chain()
    f = dict(chain[3])
    f["inputs"] = [dict(f["inputs"][0]),
                   {**f["inputs"][1], "fiscal_calendar_id": "other"}]
    chain[3] = f
    with pytest.raises(QuarterDerivationError):
        build_ttm_candidate(chain, asof=CUTOFF)


def test_direct_date_gap_and_overlap_and_duplicate_fails():
    for start, end in [("2024-01-01", "2024-03-30"),
                       ("2024-01-01", "2024-04-01")]:
        chain = quarter_chain()
        chain[0] = {**chain[0], "period_start": start, "period_end": end}
        with pytest.raises(QuarterDerivationError):
            build_ttm_candidate(chain, asof=CUTOFF)
    chain = quarter_chain()
    chain[1] = dict(chain[0])
    with pytest.raises(QuarterDerivationError):
        build_ttm_candidate(chain, asof=CUTOFF)


def test_cutoff_and_future_amendment_fail_closed():
    with pytest.raises(QuarterDerivationError):
        build_ttm_candidate(quarter_chain(), asof=date(2024, 10, 1))
    with pytest.raises(QuarterDerivationError):
        build_ttm_candidate(quarter_chain(), asof="2025-04-15")
    chain = quarter_chain()
    chain[0] = {**chain[0], "filed": "2025-05-01", "accession": "later-amendment"}
    with pytest.raises(QuarterDerivationError):
        build_ttm_candidate(chain, asof=CUTOFF)


@pytest.mark.parametrize("metric", [
    "basic_eps", "diluted_eps", "shares_outstanding", "gross_margin_pct", "fcf",
])
def test_nonadditive_metrics_not_eligible(metric):
    chain = quarter_chain()
    chain[0] = {**chain[0], "metric": metric}
    with pytest.raises(QuarterDerivationError):
        build_ttm_candidate(chain, asof=CUTOFF)


def test_missing_original_lineage_fails():
    chain = quarter_chain()
    chain[2] = {**chain[2], "inputs": []}
    with pytest.raises(QuarterDerivationError):
        build_ttm_candidate(chain, asof=CUTOFF)


def test_different_asof_must_rederive_candidates():
    with pytest.raises(QuarterDerivationError):
        build_ttm_candidate(quarter_chain(), asof=date(2025, 4, 16))
