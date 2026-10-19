"""Offline F04-B2 four-quarter TTM candidate validation; never source acceptance.

The caller must supply four provenance-rich, previously selected quarterly
observations. Cross-filing comparability remains *unverified* even if a
caller-provided comparability key matches. No data fetch, storage or valuation.
"""
from datetime import date, timedelta
import math

from .quarter_derivation import (
    QuarterDerivationError, _IDENTITY_KEYS, _validate_fact,
    _read_day, derive_cumulative_quarter,
)


def _candidate(record, asof):
    if not isinstance(record, dict):
        raise QuarterDerivationError("Quarter candidate must be an object")
    status = record.get("status")
    if record.get("source_acceptance") != "not_evaluated":
        raise QuarterDerivationError("Quarter input must retain unverified source acceptance")
    if status == "direct_quarter_unverified":
        start, end, _ = _validate_fact(record, asof, "direct")
        if record.get("form") not in ("10-Q", "10-Q/A", "10-K", "10-K/A"):
            raise QuarterDerivationError("Direct quarter needs a supported filing form")
        if record.get("publication_time_verified") is not False:
            raise QuarterDerivationError("Exact publication is not verified")
        originals = [dict(record)]
        identity = record
        value = record["value"]
        period_start, period_end = start, end
        accessions = [record["accession"]]
    elif status == "derived_candidate_only":
        originals = record.get("inputs")
        if not isinstance(originals, list) or len(originals) != 2:
            raise QuarterDerivationError("Derived quarter requires its two original cumulative facts")
        if not isinstance(record.get("asof"), str) or record["asof"] != asof.isoformat():
            raise QuarterDerivationError("Derived quarter must be re-evaluated at requested cutoff")
        if (record.get("filing_revision_alignment_verified") is not False
                or record.get("historical_publication_verified") is not False):
            raise QuarterDerivationError("Derived quarter cannot assert independent source proof")
        expected = derive_cumulative_quarter(originals[0], originals[1], asof=asof)
        for key in ("quarter", "period_start", "period_end", "metric", "issuer",
                    "value", "unit", "currency", "scale", "formula",
                    "comparability_key", "source_acceptance", "status"):
            if type(record.get(key)) is not type(expected[key]) or record.get(key) != expected[key]:
                raise QuarterDerivationError(f"Derived candidate tampered with: {key}")
        if record.get("inputs") != expected["inputs"]:
            raise QuarterDerivationError("Derived source observations changed")
        identity = originals[1]
        start = _read_day(record["period_start"], "period_start")
        end = _read_day(record["period_end"], "period_end")
        value = expected["value"]
        period_start, period_end = start, end
        accessions = [originals[0]["accession"], originals[1]["accession"]]
    else:
        raise QuarterDerivationError("Quarter must be explicitly direct or cumulative-derived")

    calendar_id = identity.get("fiscal_calendar_id")
    if not isinstance(calendar_id, str) or not calendar_id.strip():
        raise QuarterDerivationError("Reviewed fiscal calendar identity required")
    for source_fact in originals:
        if source_fact.get("fiscal_calendar_id") != calendar_id:
            raise QuarterDerivationError("Derived sources must have identical fiscal calendars")
    quarter_days = (period_end - period_start).days + 1
    if not 75 <= quarter_days <= 106:
        raise QuarterDerivationError("Candidate is not one plausible fiscal quarter")
    if not math.isfinite(value):
        raise QuarterDerivationError("Quarter candidate value must be finite")

    return {
        "identity": tuple(identity[k] for k in _IDENTITY_KEYS) + (calendar_id,),
        "start": period_start, "end": period_end,
        "value": value, "status": status,
        "origins": originals, "accessions": accessions,
    }


def build_ttm_candidate(quarters, *, asof):
    """Sum exactly four eligible adjacent quarterly monetary candidates.

    Produces an audit-only result, never an approved normalized report fact.
    """
    if type(asof) is not date:
        raise QuarterDerivationError("asof must be an exact date")
    if not isinstance(quarters, (list, tuple)) or len(quarters) != 4:
        raise QuarterDerivationError("Exactly four quarters are required")
    observations = [_candidate(q, asof) for q in quarters]
    if len({o["identity"] for o in observations}) != 1:
        raise QuarterDerivationError("TTM issuer/metric/unit/scope/source/calendar/version mismatch")
    observations.sort(key=lambda q: (q["start"], q["end"]))
    for previous, current in zip(observations, observations[1:]):
        if previous["end"] + timedelta(days=1) != current["start"]:
            raise QuarterDerivationError("TTM quarters overlap or have a date gap")
    start, end = observations[0]["start"], observations[-1]["end"]
    days = (end - start).days + 1
    if not 350 <= days <= 380:
        raise QuarterDerivationError("Four-quarter TTM period is not a plausible fiscal year")
    total = math.fsum(q["value"] for q in observations)
    if not math.isfinite(total):
        raise QuarterDerivationError("Quarter arithmetic overflow")
    identity = observations[0]["identity"]
    output = {
        "status": "ttm_candidate_only",
        "source_acceptance": "not_evaluated",
        "filing_revision_alignment_verified": False,
        "historical_publication_verified": False,
        "asof": asof.isoformat(),
        "period_type": "four_direct_or_rederived_quarter_candidates",
        "period_start": start.isoformat(), "period_end": end.isoformat(),
        "value": total, "quarter_count": 4,
        "metric": identity[_IDENTITY_KEYS.index("metric")],
        "issuer": identity[_IDENTITY_KEYS.index("issuer")],
        "unit": identity[_IDENTITY_KEYS.index("unit")],
        "currency": identity[_IDENTITY_KEYS.index("currency")],
        "fiscal_calendar_id": identity[-1],
        "availability_precision": "filing_date_only_not_intraday",
        "quarters": [
            {"period_start": o["start"].isoformat(), "period_end": o["end"].isoformat(),
             "value": o["value"], "status": o["status"],
             "accessions": list(o["accessions"]), "source_inputs": o["origins"]}
            for o in observations
        ],
        "limitations": [
            "Source comparability key and calendar ID are caller asserted",
            "Quarter version/filing amendments and exact availability are not independently verified",
            "Not eligible for production report, valuation, trade plan or investment recommendation",
        ],
    }
    return output
