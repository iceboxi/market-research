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


def _versions(raw, tags, unit, asof, source):
    """Return eligible unique filing versions for each exact fiscal duration.

    A missing accession or contradictory records within one filing identity
    cannot establish trustworthy filing-level facts; reject that metric-span.
    """
    concepts = raw.get("facts", {}).get("us-gaap", {})
    grouped = {}
    conflicted = set()
    for priority, tag in enumerate(tags):
        for row in concepts.get(tag, {}).get("units", {}).get(unit, []):
            if row.get("form") not in ("10-K", "10-K/A"):
                continue
            try:
                start = date.fromisoformat(row["start"])
                end = date.fromisoformat(row["end"])
                filed = date.fromisoformat(row["filed"])
                value = float(row["val"])
            except (KeyError, ValueError, TypeError, OverflowError):
                continue
            if (not 330 <= (end - start).days <= 380 or end > asof
                    or filed > asof or not math.isfinite(value)):
                continue
            accession = row.get("accn")
            if not isinstance(accession, str) or not accession.strip():
                continue  # Cannot prove filing identity; never combine ambiguous legs.
            span = (start.isoformat(), end.isoformat())
            key = (span, filed.isoformat(), tag, accession)
            record = {
                "value": value, "unit": unit, "period_start": span[0],
                "period_end": span[1], "filed": filed.isoformat(),
                "taxonomy_tag": tag, "accession": accession,
                "form": row["form"], "source": source,
            }
            previous = grouped.get(key)
            if previous is not None and (previous["value"] != value or previous["form"] != record["form"]):
                conflicted.add(span)
            else:
                grouped[key] = record
    return grouped, conflicted


def annual_version_trace(raw, tags, unit, asof, source, limit=6):
    """Bounded filing version trace, not an exact-time historical SEC snapshot.

    If one filed date/tag has contradictory filings, the entire fiscal span
    is excluded. 'first_seen_at' and actual public timestamp remain unknown.
    """
    records, conflicts = _versions(raw, tags, unit, asof, source)
    spans = {}
    for (span, filed, tag, accn), record in records.items():
        spans.setdefault(span, []).append(record)

    traces = []
    for span in sorted(set(spans) | conflicts, key=lambda x: x[1], reverse=True)[:limit]:
        versions = spans.get(span, [])
        # Two filings with identical filing day and taxonomy tag cannot be
        # time ordered; do not accept whichever the SEC API happens to list last.
        day_tags = {}
        for r in versions:
            day_tags.setdefault((r["filed"], r["taxonomy_tag"]), set()).add(
                (r["accession"], r["value"], r["form"]))
        ambiguous = span in conflicts or any(len(group) > 1 for group in day_tags.values())
        ranked = sorted(versions, key=lambda x: (
            x["filed"], -tags.index(x["taxonomy_tag"]), x["accession"]), reverse=True)
        traces.append({
            "period_start": span[0], "period_end": span[1],
            "status": "ambiguous_filing_versions" if ambiguous else "available",
            "versions": ranked[:12],
            "version_count": len(versions),
            "selected": ranked[0] if ranked and not ambiguous else None,
            "availability_precision": "filing_date_only_not_intraday",
            "publication_time_verified": False,
        })
    return traces


def annual_history(raw, tags, unit, asof, source, limit=6):
    """Most recent unambiguous filing version for an exact fiscal period."""
    trace = annual_version_trace(raw, tags, unit, asof, source, limit=max(limit * 2, 12))
    selected = [row["selected"] for row in trace if row["status"] == "available"]
    by_end = {}
    for record in selected:
        end = record["period_end"]
        prev = by_end.get(end)
        if prev is None or (record["filed"], -tags.index(record["taxonomy_tag"])) > (
                prev["filed"], -tags.index(prev["taxonomy_tag"])):
            by_end[end] = record
    return [by_end[end] for end in sorted(by_end, reverse=True)[:limit]]


def normalize_sec_history(raw, asof, source):
    result = {"source": source, "asof": asof.isoformat(),
              "currency": "USD", "period_type": "annual_10k"}
    result["annual_version_trace"] = {}
    for metric, (unit, tags) in METRICS.items():
        result[metric] = annual_history(raw, tags, unit, asof, source)
        result["annual_version_trace"][metric] = annual_version_trace(
            raw, tags, unit, asof, source)

    # Only pair the exact same *annual duration*. Never subtract one
    # year's capex from another year's operating cash flow.
    capex = {(r["period_start"], r["period_end"]): r
             for r in result["annual_capex"]}
    fcf = []
    for cash in result["annual_operating_cash_flow"]:
        key = (cash["period_start"], cash["period_end"])
        spend = capex.get(key)
        if (spend is None or spend["value"] < 0 or
                not cash.get("accession") or
                cash["accession"] != spend.get("accession")):
            continue
        fcf.append({
            "value": cash["value"] - spend["value"], "unit": "USD",
            "period_start": key[0], "period_end": key[1],
            "filed": max(cash["filed"], spend["filed"]),
            "derivation": "operating_cash_flow_minus_positive_capex",
            "operating_cash_flow": cash,
            "capex": spend,
            "accession": cash["accession"],
            "source": source,
        })
    result["annual_free_cash_flow"] = fcf
    return result
