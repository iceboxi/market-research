"""F03 SEC annual accession version trace and derived cash-flow integrity."""
from datetime import date

from market_research.financial_history import (
    annual_history, annual_version_trace, normalize_sec_history,
)

START, END = "2024-01-01", "2024-12-31"
SOURCE = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"


def row(value, filed, accession, tag="Revenues", form="10-K"):
    return {
        "start": START, "end": END, "val": value, "filed": filed,
        "accn": accession, "form": form, "fy": 2024, "fp": "FY",
    }


def raw_revenue(records):
    return {"facts": {"us-gaap": {"Revenues": {"units": {"USD": records}}}}}


def test_revision_asof_cutoff_is_deterministic_and_keeps_both_versions():
    facts = raw_revenue([
        row(100, "2025-02-01", "first"),
        row(120, "2025-06-01", "amended", form="10-K/A"),
    ])
    old = annual_version_trace(facts, ("Revenues",), "USD", date(2025, 5, 1), SOURCE)
    new = annual_version_trace(facts, ("Revenues",), "USD", date(2025, 9, 1), SOURCE)
    assert old[0]["selected"]["value"] == 100
    assert old[0]["version_count"] == 1
    assert new[0]["selected"]["value"] == 120
    assert new[0]["version_count"] == 2
    assert [x["accession"] for x in new[0]["versions"]] == ["amended", "first"]
    assert new[0]["publication_time_verified"] is False
    assert annual_history(facts, ("Revenues",), "USD", date(2025, 5, 1), SOURCE)[0]["value"] == 100


def test_same_date_conflicting_accessions_fail_closed_regardless_of_input_order():
    records = [row(100, "2025-02-01", "filing-a"),
               row(125, "2025-02-01", "filing-b")]
    for order in (records, list(reversed(records))):
        facts = raw_revenue(order)
        trace = annual_version_trace(facts, ("Revenues",), "USD", date(2026, 1, 1), SOURCE)
        assert trace[0]["status"] == "ambiguous_filing_versions"
        assert trace[0]["selected"] is None
        assert annual_history(facts, ("Revenues",), "USD", date(2026, 1, 1), SOURCE) == []


def test_same_accession_conflicting_values_reject_span_and_duplicates_do_not_multiply():
    duplicate = row(100, "2025-02-01", "filing-a")
    trace = annual_version_trace(raw_revenue([duplicate, dict(duplicate)]),
                                 ("Revenues",), "USD", date(2026, 1, 1), SOURCE)
    assert trace[0]["version_count"] == 1
    conflict = row(200, "2025-02-01", "filing-a")
    trace = annual_version_trace(raw_revenue([duplicate, conflict]),
                                 ("Revenues",), "USD", date(2026, 1, 1), SOURCE)
    assert trace[0]["status"] == "ambiguous_filing_versions"
    assert trace[0]["selected"] is None


def test_no_accession_no_accepted_filing_and_future_amendment_is_excluded():
    facts = raw_revenue([
        row(100, "2025-02-01", None),
        row(120, "2027-05-01", "amended", form="10-K/A"),
    ])
    assert annual_history(facts, ("Revenues",), "USD", date(2026, 1, 1), SOURCE) == []
    assert annual_version_trace(facts, ("Revenues",), "USD", date(2026, 1, 1), SOURCE) == []


def test_fcf_blocks_mixed_partial_amendments_and_accepts_matched_accession():
    facts = {"facts": {"us-gaap": {
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
            row(50, "2025-02-01", "filing-a"),
            row(60, "2025-06-01", "filing-b", form="10-K/A"),
        ]}},
        "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [
            row(10, "2025-02-01", "filing-a"),
        ]}},
    }}}
    old = normalize_sec_history(facts, date(2025, 5, 1), SOURCE)
    assert len(old["annual_free_cash_flow"]) == 1
    assert old["annual_free_cash_flow"][0]["value"] == 40
    assert old["annual_free_cash_flow"][0]["accession"] == "filing-a"
    new = normalize_sec_history(facts, date(2025, 9, 1), SOURCE)
    assert new["annual_free_cash_flow"] == []
    assert new["annual_operating_cash_flow"][0]["accession"] == "filing-b"
    assert new["annual_capex"][0]["accession"] == "filing-a"
    facts["facts"]["us-gaap"]["PaymentsToAcquirePropertyPlantAndEquipment"]["units"]["USD"].append(
        row(12, "2025-06-01", "filing-b", form="10-K/A"))
    latest = normalize_sec_history(facts, date(2025, 9, 1), SOURCE)
    assert latest["annual_free_cash_flow"][0]["value"] == 48
    assert latest["annual_free_cash_flow"][0]["accession"] == "filing-b"


def test_trace_does_not_expose_unbounded_companyfacts():
    rows = [row(i, f"{2025 + i // 25:04d}-{1 + i % 12:02d}-01", f"f-{i:03d}")
            for i in range(100)]
    trace = annual_version_trace(raw_revenue(rows), ("Revenues",), "USD",
                                 date(2030, 1, 1), SOURCE)
    assert len(trace[0]["versions"]) <= 12
    assert trace[0]["publication_time_verified"] is False
