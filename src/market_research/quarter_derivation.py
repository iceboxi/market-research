"""Strict offline-only cumulative SEC fiscal quarter arithmetic (F04-B1).

This does not fetch SEC facts or establish source/revision comparability.
Caller must preselect unambiguous records and assert a comparability key.
A mathematical result is always a candidate, never accepted live evidence.
"""
from datetime import date, timedelta
import math
import re


class QuarterDerivationError(ValueError):
    """Insufficient evidence to subtract cumulative financial facts safely."""


_ADDITIVE = frozenset({
    "revenue", "gross_profit", "net_income", "operating_cash_flow", "capex",
})
_IDENTITY_KEYS = (
    "issuer", "metric", "unit", "currency", "scale", "taxonomy_tag",
    "statement_scope", "accounting_basis", "source", "comparability_key",
)
_REQUIRED = (*_IDENTITY_KEYS, "period_start", "period_end", "filed",
             "accession", "value", "selection_status", "dimensions")
_QUARTER_SPANS = (
    ("Q2", (75, 106), (160, 200)),
    ("Q3", (160, 200), (245, 300)),
    ("Q4", (245, 300), (330, 380)),
)


def _read_day(value, field):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise QuarterDerivationError(f"{field}: exact ISO date required")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise QuarterDerivationError(f"{field}: invalid ISO calendar date") from error


def _validate_fact(record, asof, label):
    if not isinstance(record, dict) or any(k not in record for k in _REQUIRED):
        raise QuarterDerivationError(f"{label}: required provenance field missing")
    if record["metric"] not in _ADDITIVE:
        raise QuarterDerivationError("Only whitelisted additive monetary metrics may be subtracted")
    if record["unit"] != "USD" or record["currency"] != "USD":
        raise QuarterDerivationError("Only original unscaled USD monetary facts are accepted")
    if type(record["scale"]) is not int or record["scale"] != 0:
        raise QuarterDerivationError("Facts must retain original USD scale=0")
    if record["selection_status"] != "unambiguous_asof":
        raise QuarterDerivationError("Selected filing version must be unambiguous")
    if record["dimensions"] not in (None, [], {}):
        raise QuarterDerivationError("Dimensioned facts must not be subtracted")
    for key in ("issuer", "taxonomy_tag", "statement_scope", "accounting_basis",
                "source", "comparability_key", "accession"):
        if not isinstance(record[key], str) or not record[key].strip():
            raise QuarterDerivationError(f"{label}: missing {key}")
    if not record["source"].startswith("https://"):
        raise QuarterDerivationError("Source must identify a HTTPS evidence origin")
    if isinstance(record["value"], bool) or not isinstance(record["value"], (int, float)):
        raise QuarterDerivationError("Fact value must be numeric and not boolean")
    if not math.isfinite(record["value"]):
        raise QuarterDerivationError("Fact value must be finite")
    start = _read_day(record["period_start"], "period_start")
    end = _read_day(record["period_end"], "period_end")
    filed = _read_day(record["filed"], "filed")
    if start >= end or not end <= filed <= asof:
        raise QuarterDerivationError(f"{label}: invalid future/not-yet-filed period")
    return start, end, filed


def derive_cumulative_quarter(previous, current, *, asof):
    """Candidate Q2/Q3/Q4 flow: current fiscal YTD less prior fiscal YTD.

    A matching caller-supplied comparability key is NOT independent evidence of
    revision compatibility. Never auto-wire this result to a live report.
    """
    if type(asof) is not date:
        raise QuarterDerivationError("asof must be a date, not a timestamp")
    prev_start, prev_end, prev_filed = _validate_fact(previous, asof, "previous")
    current_start, current_end, current_filed = _validate_fact(current, asof, "current")
    if any(previous[k] != current[k] for k in _IDENTITY_KEYS):
        raise QuarterDerivationError("Incompatible issuer/metric/unit/scale/scope/tag/source/revision basis")
    if prev_start != current_start:
        raise QuarterDerivationError("Cumulative periods must share the same fiscal start")
    if current_end <= prev_end or prev_filed > current_filed:
        raise QuarterDerivationError("Cumulative or filing chronology is inconsistent")
    quarter_start = prev_end + timedelta(days=1)
    quarter_days = (current_end - quarter_start).days + 1
    prev_days = (prev_end - prev_start).days + 1
    current_days = (current_end - current_start).days + 1
    matches = [name for name, (pmin, pmax), (cmin, cmax) in _QUARTER_SPANS
               if pmin <= prev_days <= pmax and cmin <= current_days <= cmax]
    if len(matches) != 1 or not 75 <= quarter_days <= 106:
        raise QuarterDerivationError("Cumulative windows are not one recognized fiscal quarter apart")
    return {
        "status": "derived_candidate_only",
        "source_acceptance": "not_evaluated",
        "historical_publication_verified": False,
        "filing_revision_alignment_verified": False,
        "quarter": matches[0],
        "metric": current["metric"], "issuer": current["issuer"],
        "period_type": "derived_from_two_explicit_cumulative_facts",
        "period_start": quarter_start.isoformat(),
        "period_end": current_end.isoformat(),
        "value": current["value"] - previous["value"],
        "unit": current["unit"], "currency": current["currency"],
        "scale": current["scale"],
        "formula": "current_cumulative_minus_previous_cumulative",
        "asof": asof.isoformat(),
        "availability_precision": "filing_date_only_not_intraday",
        "comparability_key": current["comparability_key"],
        "inputs": [dict(previous), dict(current)],
        "limitations": [
            "Comparability key is caller asserted, not independent filing compatibility evidence",
            "Cross-accession revisions and exact availability require original filing reconciliation",
            "Not wired to report, TTM, valuation or automated trading",
        ],
    }
