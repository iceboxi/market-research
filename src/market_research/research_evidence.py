"""Descriptive research provenance; filing dates never imply intraday publication."""
from datetime import datetime, timezone
from math import isfinite
import re


def instrument_gate(issuer):
    market = issuer.get("market")
    known = str(issuer.get("instrument_type") or "").strip().lower()
    if known in {"etf", "fund", "investment_fund", "registered_investment_company"}:
        return {"status": "ineligible", "kind": "fund_or_etf",
                "generic_fcf": "blocked", "reason": "Explicit investment fund/ETF"}
    if market == "tw":
        code = str(issuer.get("industry_code") or "").strip().zfill(2)
        if code == "17":
            return {"status": "ineligible", "kind": "financial_company",
                    "generic_fcf": "blocked", "reason": "Official TWSE financial sector"}
        if re.fullmatch(r"[0-9]{2}", code) and code != "00":
            return {"status": "candidate_only", "kind": "twse_nonfinancial_candidate",
                    "generic_fcf": "blocked",
                    "reason": "TWSE monthly revenue cannot establish annual IFRS cashflows"}
    if market == "us":
        sic = (issuer.get("industry") or {}).get("sic")
        if type(sic) is int and 6000 <= sic <= 6999:
            return {"status": "ineligible", "kind": "financial_real_estate",
                    "generic_fcf": "blocked", "reason": "Financial/insurance/real-estate SIC"}
        if type(sic) is int and 100 <= sic <= 9999:
            return {"status": "candidate_only", "kind": "us_nonfinancial_candidate",
                    "generic_fcf": "illustrative_only",
                    "reason": "Nonfinancial SIC; security type not independently established"}
    return {"status": "unknown", "kind": "unknown", "generic_fcf": "blocked",
            "reason": "Insufficient official issuer classification"}


def evidence_report(issuer, now):
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("An offset-aware observation time is required")
    stamp = now.astimezone(timezone.utc).isoformat()
    rows = []
    for fact in issuer.get("facts", []):
        if not isinstance(fact, dict):
            continue
        value = fact.get("value")
        if type(value) not in (float, int) or not isfinite(value):
            continue
        if not all(fact.get(k) for k in ("metric", "unit", "source")):
            continue
        us = issuer.get("market") == "us"
        rows.append({
            "metric": fact["metric"], "value": value, "unit": fact["unit"],
            "currency": ("USD" if fact["unit"] == "USD" else "TWD"
                         if fact["unit"] == "TWD_thousands" else None),
            "scale_to_base_unit": 1000 if fact["unit"] == "TWD_thousands" else 1,
            "source": fact["source"], "accession": fact.get("accession"),
            "taxonomy_tag": fact.get("taxonomy_tag"), "form": fact.get("form"),
            "period_start": fact.get("period_start"), "period_end": fact.get("period_end"),
            "period_label": fact.get("period"),
            "statement_scope": ("SEC_scope_unverified" if us else "TWSE_monthly_not_IFRS"),
            "filed_date": fact.get("filed") if us else None,
            "publication_time": None, "first_seen_at": None,
            "availability_precision": ("filed_date_only_intraday_unverified" if us
                                      else "current_snapshot_not_historical"),
            "retrieved_at_utc": stamp,
        })
    return {
        "schema_version": 1, "market": issuer.get("market"),
        "issuer": issuer.get("symbol"), "retrieved_at_utc": stamp,
        "historical_availability": "not_verified", "facts": rows,
        "source_status": "observed_not_historically_verified" if rows else "unavailable",
    }


def render_evidence(evidence, gate):
    return ["", "## Source evidence and instrument applicability", "",
            f"Instrument: **{gate['kind']}** ({gate['status']})",
            f"Generic FCF applicability: **{gate['generic_fcf']}**",
            gate["reason"],
            f"Source observations: {len(evidence['facts'])}; historical availability unverified.",
            "Filed date or data retrieval is NOT independently verified publication time.",
            "See report.json for original units, source, accession and date precision."]
