"""Source/time provenance and instrument suitability for research reports.

Publication time is never synthesized from a date-only SEC filing or a
TWSE publication period. The analysis as-of and actual retrieval are distinct.
"""
from datetime import date, datetime, timezone
import math
import re

SCHEMA_VERSION = 1
TW_PROFILE = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TW_MONTHLY = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
TW_FINANCIAL_INDUSTRY = "17"
SEC_FUND_FORMS = {
    "N-1A", "N-2", "N-CEN", "N-PORT", "N-Q", "485BPOS", "497", "497K",
}
SEC_OPERATING_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F"}


def instrument_eligibility(issuer):
    """Candidate is not a finding that a model or instrument is investable."""
    market = issuer.get("market")
    identity = issuer.get("company_name")
    if not isinstance(identity, str) or not identity.strip():
        return _ineligible("unknown", "unknown", "Missing verified issuer identity", None)
    if market == "tw":
        raw_code = str(issuer.get("industry_code") or "").strip()
        code = raw_code.zfill(2) if raw_code else ""
        src = (issuer.get("profile") or {}).get("source")
        if src != TW_PROFILE or not re.fullmatch(r"[0-9]{2}", code):
            return _ineligible("unknown", "unknown", "TWSE industry or profile source unavailable", src)
        if code == TW_FINANCIAL_INDUSTRY:
            return _ineligible("financial_institution", "inapplicable",
                               "TWSE sector 17 requires a financial-sector model", src)
        # Profiles of listed companies are not proof of a security's tradability,
        # future financial availability or model-specific applicability.
        return {"instrument_type": "listed_company_profile",
                "status": "candidate_for_nonfinancial_research",
                "source": src, "basis": "TWSE listed issuer and non-financial industry",
                "model_status": "not_evaluated",
                "reason": "Annual IFRS statements and valuation-specific suitability not verified"}
    if market == "us":
        info = issuer.get("instrument_evidence") or {}
        sic = (issuer.get("industry") or {}).get("sic")
        forms = info.get("recent_form_types") or []
        src = info.get("source") or (issuer.get("industry") or {}).get("source")
        if any(x in SEC_FUND_FORMS for x in forms):
            return _ineligible("fund_or_etf", "inapplicable",
                               "SEC investment-company forms require fund-specific analysis", src)
        if isinstance(sic, int) and 6000 <= sic <= 6999:
            return _ineligible("financial_or_real_estate", "inapplicable",
                               "SEC financial/real-estate SIC requires a sector-specific model", src)
        if not isinstance(sic, int) or not 100 <= sic <= 9999 or not src:
            return _ineligible("unknown", "unknown", "SEC industry eligibility not verified", src)
        # SEC financial and operating company classification is indicative,
        # not evidence of current share count or a valid valuation model.
        return {"instrument_type": "operating_issuer_candidate",
                "status": "candidate_for_nonfinancial_research", "source": src,
                "basis": "SEC non-financial SIC; no investment-company form observed",
                "model_status": "illustrative_only",
                "reason": "Historical sensitivity remains uncalibrated and not executable"}
    return _ineligible("unknown", "unknown", "Unsupported instrument market", None)


def _ineligible(kind, status, reason, source):
    return {"instrument_type": kind, "status": status, "source": source,
            "basis": None, "model_status": "not_evaluated", "reason": reason}


def _availability(filed, cutoff):
    """Date-only SEC filings have no safe same-day intraday availability."""
    if not filed:
        return "missing_filing_date", "unknown"
    try:
        day = date.fromisoformat(filed)
    except (ValueError, TypeError):
        return "invalid_filing_date", "unknown"
    if day > cutoff.date():
        return "future_filing_not_available", "date_only"
    if day == cutoff.date():
        return "same_day_publication_unverified", "date_only"
    return "filed_before_cutoff_date_only", "date_only"


def build_source_evidence(issuer, cutoff, retrieved_at=None):
    """Create a bounded evidence report without inventing publication times."""
    if cutoff.tzinfo is None:
        raise ValueError("Evaluation cutoff requires timezone")
    retrieved_at = retrieved_at or datetime.now(timezone.utc)
    if retrieved_at.tzinfo is None:
        raise ValueError("Actual retrieval time requires timezone")
    market = issuer.get("market")
    records = []
    for fact in issuer.get("facts", []):
        if not isinstance(fact, dict):
            continue
        is_sec = market == "us"
        state, precision = (_availability(fact.get("filed"), cutoff) if is_sec else
                            ("current_snapshot_only", "unknown"))
        if not is_sec and cutoff.astimezone(timezone.utc).date() < retrieved_at.astimezone(timezone.utc).date():
            # Current TWSE snapshots cannot be replayed at a past as-of.
            state = "historical_availability_unverified"
        records.append(_record(fact, issuer, cutoff, retrieved_at, state, precision,
                               derived=False))
    if market == "us":
        history = issuer.get("financial_history") or {}
        for metric in (
            "annual_revenue", "annual_net_income", "annual_operating_cash_flow",
            "annual_capex", "annual_diluted_shares", "annual_free_cash_flow",
        ):
            for item in (history.get(metric) or [])[:6]:
                if not isinstance(item, dict):
                    continue
                state, precision = _availability(item.get("filed"), cutoff)
                records.append(_record({"metric": metric, **item}, issuer,
                                       cutoff, retrieved_at, state, precision,
                                       derived=metric == "annual_free_cash_flow"))
    states = {x["availability_status"] for x in records}
    unsafe = {"same_day_publication_unverified", "future_filing_not_available",
              "missing_filing_date", "invalid_filing_date",
              "historical_availability_unverified"}
    missing_source = any(r["source_status"] == "missing_source" for r in records)
    source_status = "needs_availability_review" if states & unsafe or missing_source else (
        "review_only" if records else "no_fact_evidence")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": source_status, "cutoff_utc": cutoff.astimezone(timezone.utc).isoformat(),
        "retrieved_at_utc": retrieved_at.astimezone(timezone.utc).isoformat(),
        "source_coverage": "recent_source_snapshot_not_historical_replay",
        "observations": records,
        "limitations": [
            "SEC filing date is date-only, not acceptance time or public release time",
            "SEC current companyfacts may include later revisions; F03 must verify historic document versions",
            "TWSE latest profile/monthly revenue snapshots are not historical IFRS filings",
            "System retrieved_at is not publication evidence or an historic first_seen_at",
        ],
    }


def _record(fact, issuer, cutoff, retrieved_at, state, precision, derived):
    unit = fact.get("unit")
    currency = "USD" if unit == "USD" else "TWD" if unit == "TWD_thousands" else None
    scale = 1000 if unit == "TWD_thousands" else 1 if unit in ("USD", "shares") else None
    value = fact.get("value")
    if (not isinstance(value, (int, float)) or isinstance(value, bool) or
            not math.isfinite(value)):
        value = None
        state = "invalid_fact_value"
    return {
        "issuer_symbol": issuer.get("symbol"),
        "metric": fact.get("metric"), "kind": "derived" if derived else "reported",
        "value": value, "unit": unit, "currency": currency, "scale_to_base": scale,
        "statement_scope": fact.get("statement_scope"),
        "period_start": fact.get("period_start"),
        "period_end": fact.get("period_end"),
        "reported_period": fact.get("period"),
        "source_url": fact.get("source"),
        "document": {"accession": fact.get("accession"), "form": fact.get("form"),
                     "taxonomy_tag": fact.get("taxonomy_tag")},
        "date_evidence": {"filed": fact.get("filed"),
                          "reported_at": fact.get("reported_at"),
                          "published_at": None, "published_precision": "unknown",
                          "first_seen_at": None,
                          "availability_precision": precision},
        "retrieved_at_utc": retrieved_at.astimezone(timezone.utc).isoformat(),
        "availability_status": state,
        "source_status": "observed_source_record" if fact.get("source") else "missing_source",
        "derivation": fact.get("derivation") if derived else None,
    }


def validate_valuation_inputs(issuer, cutoff):
    """Forbid P/FCF scenarios without a verifiable date-only *earlier* filing."""
    history = issuer.get("financial_history") or {}
    cashflows = sorted(history.get("annual_free_cash_flow") or [],
                       key=lambda r: r.get("period_end", ""), reverse=True)[:3]
    if len(cashflows) < 3:
        return {"status": "not_verified", "why": "Fewer than three derived annual FCF observations"}
    for row in cashflows:
        legs = [row.get("operating_cash_flow"), row.get("capex")]
        if not all(isinstance(leg, dict) for leg in legs):
            return {"status": "not_verified", "why": "FCF underlying source legs unavailable"}
        for leg in legs:
            if (_availability(leg.get("filed"), cutoff)[0] != "filed_before_cutoff_date_only" or
                    not leg.get("source") or not leg.get("accession")):
                return {"status": "not_verified", "why": "FCF provenance or dated availability unverified"}
    return {"status": "date_only_prior_filing", "why": (
        "Source filings predate cutoff but exact publication and historical revision remain unverified")}


def render_evidence(eligibility, evidence, gate):
    lines = ["", "## Source evidence and instrument suitability", "",
             f"Instrument: **{eligibility['instrument_type']}** "
             f"({eligibility['status']})",
             eligibility["reason"], "",
             f"Evidence status: **{evidence['status']}**",
             f"Retrieved (UTC): {evidence['retrieved_at_utc']}",
             f"Evaluation cutoff (UTC): {evidence['cutoff_utc']}",
             f"Valuation provenance gate: {gate['status']} — {gate['why']}",
             "",
             "Publication time is **unknown** unless independently proven; "
             "filing date and retrieval time must not be used as a publication timestamp.",
             "Per-fact value, currency/scale, original dates, filing identity "
             "and source URL are in report.json."]
    return lines
