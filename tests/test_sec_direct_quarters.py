"""F04-A direct-only SEC quarter fixture checks; no live SEC or FY/Q4 inference."""
from datetime import date

import pytest

from market_research.financial_history import (
    direct_quarter_version_trace, normalize_sec_direct_quarters,
    normalize_sec_history,
)

SOURCE = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
Q1 = ("2024-01-01", "2024-03-31")
Q2 = ("2024-04-01", "2024-06-30")
Q3 = ("2024-07-01", "2024-09-30")
Q4 = ("2024-10-01", "2024-12-31")
FY = ("2024-01-01", "2024-12-31")


def record(value, period=Q1, accession="q1", filed="2024-05-02", form="10-Q"):
    return {"start": period[0], "end": period[1], "val": value,
            "accn": accession, "filed": filed, "form": form}


def facts(**tags):
    # Values are dicts whose keys are (taxonomy-tag, reported-unit).
    concepts = {}
    for tag, unit, rows in tags.get("series", []):
        concepts.setdefault(tag, {"units": {}})["units"][unit] = rows
    return {"facts": {"us-gaap": concepts}}


def base():
    return facts(series=[
        ("Revenues", "USD", [record(100), record(150, Q2, "q2", "2024-08-02"),
                             record(170, Q3, "q3", "2024-11-02")]),
        ("GrossProfit", "USD", [record(40), record(60, Q2, "q2", "2024-08-02")]),
        ("NetIncomeLoss", "USD", [record(18)]),
        ("EarningsPerShareDiluted", "USD/shares", [record(1.2)]),
        ("NetCashProvidedByUsedInOperatingActivities", "USD", [record(20)]),
        ("PaymentsToAcquirePropertyPlantAndEquipment", "USD", [record(7)]),
    ])


def test_direct_quarters_are_separate_and_same_accession_margin():
    result = normalize_sec_direct_quarters(base(), date(2025, 2, 1), SOURCE)
    assert result["period_type"] == "direct_quarter_only_no_ytd_derivation"
    assert [x["value"] for x in result["quarterly_revenue"]] == [170, 150, 100]
    assert len(result["quarterly_gross_profit"]) == 2
    assert [x["value"] for x in result["gross_margin_pct"]] == [40.0, 40.0]
    assert result["quarterly_diluted_eps"][0]["unit"] == "USD/shares"
    assert result["gross_margin_pct"][0]["gross_profit"]["accession"] == "q2"
    assert result["quarterly_version_trace"]["quarterly_revenue"][0][
        "availability_precision"] == "filing_date_only_not_intraday"
    assert result["publication_time_verified"] is False
    assert result["quarterly_version_trace"]["quarterly_revenue"][0]["first_seen_at"] is None
    assert "TTM" not in str(result) and "standalone_q4_estimated" not in str(result)


def test_full_year_ytd_and_monthly_are_never_direct_quarters():
    raw = facts(series=[("Revenues", "USD", [
        record(100, FY, "fy", "2025-02-02", "10-K"),
        record(75, ("2024-01-01", "2024-09-30"), "ytd", "2024-11-02"),
        record(55, ("2024-01-01", "2024-06-30"), "ytd2", "2024-08-02"),
        record(3, ("2024-02-01", "2024-02-29"), "m", "2024-03-01"),
    ])])
    result = normalize_sec_direct_quarters(raw, date(2025, 5, 1), SOURCE)
    assert result["quarterly_revenue"] == []
    assert result["quarterly_version_trace"]["quarterly_revenue"] == []


@pytest.mark.parametrize("period", [
    ("2023-12-31", "2024-04-06"),  # 97d, fiscal-period may cross year
    ("2024-08-04", "2024-11-09"),  # 97d, 14-week quarter
    ("2024-01-27", "2024-04-27"),  # 91d, non-calendar boundary
])
def test_direct_52_53_week_and_non_calendar_periods(period):
    raw = facts(series=[("Revenues", "USD", [record(42, period, "f", "2025-01-02")])])
    value = normalize_sec_direct_quarters(raw, date(2025, 2, 1), SOURCE)["quarterly_revenue"]
    assert len(value) == 1
    assert (value[0]["period_start"], value[0]["period_end"]) == period


def test_asof_excludes_future_and_not_yet_filed_amendments():
    initial = record(100, Q1, "original", "2024-05-02")
    future = record(200, Q1, "restated", "2025-09-01", "10-Q/A")
    raw = facts(series=[("Revenues", "USD", [initial, future])])
    old = normalize_sec_direct_quarters(raw, date(2024, 5, 1), SOURCE)
    assert old["quarterly_revenue"] == []
    asof_original = normalize_sec_direct_quarters(raw, date(2024, 7, 1), SOURCE)
    assert asof_original["quarterly_revenue"][0]["value"] == 100
    asof_amend = normalize_sec_direct_quarters(raw, date(2025, 10, 1), SOURCE)
    assert asof_amend["quarterly_revenue"][0]["value"] == 200
    trace = asof_amend["quarterly_version_trace"]["quarterly_revenue"][0]
    assert trace["version_count"] == 2
    assert [x["accession"] for x in trace["versions"]] == ["restated", "original"]


def test_same_filed_date_multi_accession_conflict_is_order_independent():
    a = record(100, Q1, "first", "2024-05-02")
    b = record(200, Q1, "second", "2024-05-02", "10-Q/A")
    for rows in ([a, b], [b, a]):
        raw = facts(series=[("Revenues", "USD", rows)])
        result = normalize_sec_direct_quarters(raw, date(2025, 1, 1), SOURCE)
        assert result["quarterly_revenue"] == []
        trace = result["quarterly_version_trace"]["quarterly_revenue"][0]
        assert trace["status"] == "ambiguous_filing_versions"
        assert trace["selected"] is None


def test_same_accession_conflicting_rows_and_competing_tags_rejected():
    a = record(100)
    bad = record(200)
    raw = facts(series=[("Revenues", "USD", [a, bad])])
    assert not normalize_sec_direct_quarters(raw, date(2025, 1, 1), SOURCE)[
        "quarterly_revenue"]
    raw = facts(series=[("Revenues", "USD", [a]),
                        ("SalesRevenueNet", "USD", [bad])])
    assert not normalize_sec_direct_quarters(raw, date(2025, 1, 1), SOURCE)[
        "quarterly_revenue"]


def test_gross_margin_refuses_cross_accession_even_in_same_quarter():
    raw = facts(series=[("Revenues", "USD", [record(100, Q1, "filing-a", "2024-05-02"),
                                           record(120, Q1, "filing-b", "2024-08-02", "10-Q/A")]),
                        ("GrossProfit", "USD", [record(40, Q1, "filing-a", "2024-05-02")])])
    result = normalize_sec_direct_quarters(raw, date(2025, 1, 1), SOURCE)
    assert result["quarterly_revenue"][0]["accession"] == "filing-b"
    assert result["gross_margin_pct"] == []


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "not_numeric"])
def test_invalid_financial_numbers_skipped(value):
    raw = facts(series=[("Revenues", "USD", [record(value)])])
    assert normalize_sec_direct_quarters(raw, date(2025, 1, 1), SOURCE)[
        "quarterly_revenue"] == []


def test_missing_accession_wrong_unit_wrong_form_and_future_period_skipped():
    raw = facts(series=[
        ("Revenues", "EUR", [record(100)]),
        ("Revenues", "USD", [
            record(100, accession=None),
            record(100, form="8-K"),
            record(100, period=("2026-01-01", "2026-03-31"),
                   filed="2026-05-02"),
            record(100, filed="2024-02-01"),  # before fiscal end
        ]),
    ])
    assert normalize_sec_direct_quarters(raw, date(2025, 1, 1), SOURCE)[
        "quarterly_revenue"] == []


def test_eps_units_and_gross_margin_zero_revenue_fails_closed():
    raw = facts(series=[("EarningsPerShareBasic", "USD", [record(2)]),
                        ("EarningsPerShareDiluted", "USD/shares", [record(1.5)]),
                        ("Revenues", "USD", [record(0)]),
                        ("GrossProfit", "USD", [record(10)])])
    result = normalize_sec_direct_quarters(raw, date(2025, 1, 1), SOURCE)
    assert result["quarterly_basic_eps"] == []
    assert result["quarterly_diluted_eps"][0]["value"] == 1.5
    assert result["gross_margin_pct"] == []


def test_annual_owner_output_is_not_redefined_by_direct_quarters():
    raw = facts(series=[("Revenues", "USD", [record(100),
        record(1000, FY, "fy", "2025-02-02", "10-K")])])
    original = normalize_sec_history(raw, date(2025, 6, 1), SOURCE)
    direct = normalize_sec_direct_quarters(raw, date(2025, 6, 1), SOURCE)
    assert original["annual_revenue"][0]["value"] == 1000
    assert direct["quarterly_revenue"][0]["value"] == 100
    assert "quarterly_revenue" not in original


def test_invalid_trace_arguments_fail_instead_of_guessing():
    with pytest.raises((TypeError, ValueError)):
        direct_quarter_version_trace({}, ("Revenues",), "USD", "2025-01-01", SOURCE)
    with pytest.raises(ValueError):
        direct_quarter_version_trace({}, (), "USD", date(2025, 1, 1), SOURCE)
