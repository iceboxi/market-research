"""Point-in-time financial normalization and valuation safety tests."""
from datetime import date

from market_research.financial_history import normalize_sec_history, annual_history
from market_research.valuation import evaluate_valuation


def rec(start, end, value, filed, form="10-K", accn="filing-1"):
    return {"start": start, "end": end, "val": value, "filed": filed,
            "form": form, "accn": accn, "fy": int(end[:4]), "fp": "FY"}


YEARS = [
    ("2022-01-01", "2022-12-31", "2023-02-10"),
    ("2023-01-01", "2023-12-31", "2024-02-10"),
    ("2024-01-01", "2024-12-31", "2025-02-10"),
]


def issuer_data(missing=None, override=None, sic=3571):
    missing = missing or set()
    override = override or {}
    series = {}
    metrics = [
        ("Revenues", "USD", 200),
        ("NetIncomeLoss", "USD", 25),
        ("NetCashProvidedByUsedInOperatingActivities", "USD", 50),
        ("PaymentsToAcquirePropertyPlantAndEquipment", "USD", 10),
        ("WeightedAverageNumberOfDilutedSharesOutstanding", "shares", 10),
    ]
    for tag, unit, value in metrics:
        rows = []
        for i, (start, end, filed) in enumerate(YEARS):
            if (tag, i) in missing:
                continue
            rows.append(rec(start, end, override.get((tag, i), value + i), filed))
        series[tag] = {"units": {unit: rows}}
    raw = {"facts": {"us-gaap": series}}
    hist = normalize_sec_history(raw, date(2026, 10, 18), "https://data.sec.gov/test")
    issuer = {"market": "us", "industry": {"sic": sic}, "financial_history": hist}
    return issuer, raw


def test_matching_three_year_fcf_and_sources():
    issuer, _ = issuer_data()
    h = issuer["financial_history"]
    assert len(h["annual_free_cash_flow"]) == 3
    assert [round(r["value"]) for r in h["annual_free_cash_flow"]] == [40, 40, 40]
    f = h["annual_free_cash_flow"][0]
    assert f["operating_cash_flow"]["taxonomy_tag"] == "NetCashProvidedByUsedInOperatingActivities"
    assert f["capex"]["period_start"] == f["period_start"]
    assert f["operating_cash_flow"]["source"].startswith("https://data.sec.gov")


def test_valuation_produces_labelled_research_only_scenarios():
    issuer, _ = issuer_data()
    result = evaluate_valuation(issuer, date(2026, 10, 18))
    assert result["status"] == "illustrative_only"
    assert result["fair_value_scenarios"]["base"]["fcf_multiple"] == 15
    assert result["entry_zone"] is None
    assert result["stop_loss"] is None
    assert result["target_price"] is None


def test_incomplete_financials_and_unaligned_years_are_blocked():
    issuer, _ = issuer_data(missing={("PaymentsToAcquirePropertyPlantAndEquipment", 1)})
    assert evaluate_valuation(issuer, date(2026, 10, 18))["status"] == "not_evaluated"
    issuer, _ = issuer_data(missing={("NetIncomeLoss", 1)})
    assert evaluate_valuation(issuer, date(2026, 10, 18))["status"] == "not_evaluated"
    issuer, _ = issuer_data(missing={("WeightedAverageNumberOfDilutedSharesOutstanding", 2)})
    assert evaluate_valuation(issuer, date(2026, 10, 18))["status"] == "not_evaluated"


def test_nonpositive_or_financial_sector_blocks():
    issuer, _ = issuer_data(override={("NetCashProvidedByUsedInOperatingActivities", 0): 1})
    assert evaluate_valuation(issuer, date(2026, 10, 18))["status"] == "not_evaluated"
    issuer, _ = issuer_data(sic=6021)
    assert "different valuation" in evaluate_valuation(issuer, date(2026, 10, 18))["why"]
    issuer, _ = issuer_data(sic=None)
    assert evaluate_valuation(issuer, date(2026, 10, 18))["status"] == "not_evaluated"
    assert evaluate_valuation({"market": "tw"}, date(2026, 10, 18))["status"] == "not_evaluated"


def test_no_lookahead_or_annual_quarter_mixing():
    issuer, raw = issuer_data()
    arr = raw["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
    arr.append(rec("2024-01-01", "2024-12-31", 9999, "2027-02-10", "10-K/A"))
    arr.append(rec("2025-01-01", "2025-03-31", 9999, "2025-05-01", "10-Q"))
    out = annual_history(raw, ("Revenues",), "USD", date(2026, 10, 18), "SEC")
    assert out[0]["value"] == 202
    assert len(out) == 3
    past = annual_history(raw, ("Revenues",), "USD", date(2024, 12, 1), "SEC")
    assert [r["period_end"] for r in past] == ["2023-12-31", "2022-12-31"]


def test_normalizer_does_not_cross_pair_mismatched_capex():
    issuer, raw = issuer_data()
    raw["facts"]["us-gaap"]["PaymentsToAcquirePropertyPlantAndEquipment"]["units"]["USD"][2]["start"] = "2024-04-01"
    hist = normalize_sec_history(raw, date(2026, 10, 18), "SEC")
    assert len(hist["annual_free_cash_flow"]) == 2


def test_valuation_blocks_stale_history():
    issuer, _ = issuer_data()
    assert evaluate_valuation(issuer, date(2028, 1, 1))["status"] == "not_evaluated"
