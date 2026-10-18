"""Normalized, point-in-time SEC annual 10-K financial observations.

Amounts are kept in original USD, never scaled into millions. The original
start/end dates, filing dates, taxonomy tags and accessions remain attached.
"""
from datetime import date
import math


METRICS = {
    "annual_revenue": ("USD", ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet")),
    "annual_net_income": ("USD", ("NetIncomeLoss",)),
    "annual_operating_cash_flow": ("USD", ("NetCashProvidedByUsedInOperatingActivities",)),
    "annual_capex": ("USD", ("PaymentsToAcquirePropertyPlantAndEquipment",)),
    "annual_diluted_shares": ("shares", ("WeightedAverageNumberOfDilutedSharesOutstanding",)),
}


def annual_history(raw, tags, unit, asof, source, limit=6):
    """Choose newest as-of-known annual filing per actual fiscal period.

    SEC FY/fp can refer to the *filing*, rather than the comparison-year
    observation. Do not filter history by fy alone or use future restatements.
    """
    concepts = raw.get("facts", {}).get("us-gaap", {})
    selected = {}
    for priority, tag in enumerate(tags):
        rows = concepts.get(tag, {}).get("units", {}).get(unit, [])
        for row in rows:
            if row.get("form") not in ("10-K", "10-K/A"):
                continue
            try:
                start = date.fromisoformat(row["start"])
                end = date.fromisoformat(row["end"])
                filed = date.fromisoformat(row["filed"])
                value = float(row["val"])
            except (KeyError, ValueError, TypeError, OverflowError):
                continue
            if not (330 <= (end - start).days <= 380):
                continue
            if end > asof or filed > asof or not math.isfinite(value):
                continue
            key = (start.isoformat(), end.isoformat())
            candidate = {
                "value": value, "unit": unit, "period_start": key[0],
                "period_end": key[1], "filed": filed.isoformat(),
                "taxonomy_tag": tag, "accession": row.get("accn"),
                "form": row["form"], "source": source,
            }
            previous = selected.get(key)
            # Recent filings win; for equal dates prefer the first taxonomy tag.
            if previous is None or (filed, -priority) > previous[0]:
                selected[key] = ((filed, -priority), candidate)
    # Two observation spans occasionally end on the same date. Never double
    # count one fiscal year in an annual time series.
    by_end = {}
    for (_, end), (rank, record) in selected.items():
        if end not in by_end or rank > by_end[end][0]:
            by_end[end] = (rank, record)
    return [by_end[end][1] for end in sorted(by_end, reverse=True)[:limit]]


def normalize_sec_history(raw, asof, source):
    result = {"source": source, "asof": asof.isoformat(),
              "currency": "USD", "period_type": "annual_10k"}
    for metric, (unit, tags) in METRICS.items():
        result[metric] = annual_history(raw, tags, unit, asof, source)

    # Only pair the exact same *annual duration*. Never subtract one
    # year's capex from another year's operating cash flow.
    capex = {(r["period_start"], r["period_end"]): r
             for r in result["annual_capex"]}
    fcf = []
    for cash in result["annual_operating_cash_flow"]:
        key = (cash["period_start"], cash["period_end"])
        spend = capex.get(key)
        if spend is None or spend["value"] < 0:
            continue
        fcf.append({
            "value": cash["value"] - spend["value"], "unit": "USD",
            "period_start": key[0], "period_end": key[1],
            "filed": max(cash["filed"], spend["filed"]),
            "derivation": "operating_cash_flow_minus_positive_capex",
            "operating_cash_flow": cash,
            "capex": spend,
        })
    result["annual_free_cash_flow"] = fcf
    return result
