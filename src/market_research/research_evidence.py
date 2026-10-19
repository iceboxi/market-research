"""Source availability and issuer eligibility in company research.

SEC filingDate cannot prove intraday publication. TWSE current snapshots
cannot be used as historical filings without independent evidence.
"""
from datetime import datetime, timezone
import re

VERSION = 1
TW_FINANCIAL_INDUSTRY = {"17"}
ANNUAL_FIELDS = (
    "annual_revenue", "annual_net_income", "annual_operating_cash_flow",
    "annual_capex", "annual_diluted_shares", "annual_free_cash_flow",
)


def instrument_eligibility(issuer):
    """Require positive issuer/sector evidence; never infer equity class from ticker."""
    market = issuer.get("market")
    if market == "tw":
        profile = issuer.get("profile") or {}
        industry = str(issuer.get("industry_code") or "").strip()
        source = profile.get("source")
        if not issuer.get("company_name") or not source or not industry:
            status, kind, reason = ("unknown", "unverified",
                                    "TWSE listed-company identity/industry not verified")
        elif industry in TW_FINANCIAL_INDUSTRY:
            status, kind, reason = ("ineligible", "financial_issuer",
                                    "Financial/insurance industry requires a different valuation model")
        elif re.fullmatch(r"[0-9]{1,3}", industry):
            status, kind, reason = ("eligible", "listed_nonfinancial_issuer",
                                    "TWSE nonfinancial issuer verified; annual IFRS evidence still required")
        else:
            status, kind, reason = ("unknown", "unverified", "TWSE industry classification unknown")
    elif market == "us":
        industry = issuer.get("industry") or {}
        instrument = issuer.get("instrument") or {}
        sic, entity = industry.get("sic"), instrument.get("sec_entity_type")
        source = instrument.get("source") or industry.get("source")
        if entity != "operating" or type(sic) is not int:
            status, kind, reason = ("unknown", "unverified",
                                    "SEC operating filer and SIC not both verified; possibly fund/ETF/trust")
        elif 6000 <= sic <= 6999:
            status, kind, reason = ("ineligible", "financial_issuer",
                                    "SEC financial/insurance/real-estate SIC requires a different model")
        elif 100 <= sic <= 9999:
            status, kind, reason = ("eligible", "operating_nonfinancial_issuer",
                                    "SEC nonfinancial operating filer; quoted share class not verified")
        else:
            status, kind, reason = ("unknown", "unverified", "Invalid SEC SIC")
    else:
        status, kind, reason, source = "unknown", "unverified", "Unknown issuer market", None
    return {
        "schema_version": VERSION, "status": status, "instrument_kind": kind,
        "valuation_model": "generic_nonfinancial_illustrative_only" if status == "eligible"
                           else "not_evaluated",
        "security_class_verified": False, "reason": reason, "source": source,
    }


def _retrieved(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo:
            return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:
        pass
    return None


def _sec_observation(metric, item, retrieved):
    derived = metric == "annual_free_cash_flow"
    parent = item.get("operating_cash_flow") or {}
    capex = item.get("capex") or {}
    documents = ([f.get("accession") for f in (parent, capex) if f.get("accession")]
                 if derived else [item.get("accession")] if item.get("accession") else [])
    unit = item.get("unit")
    return {
        "metric": metric, "value": item.get("value"), "unit": unit, "scale": 1,
        "currency": "USD" if unit == "USD" else None,
        "statement_scope": "SEC_US_GAAP_companyfacts_consolidation_unverified",
        "period_start": item.get("period_start"), "period_end": item.get("period_end"),
        "source": item.get("source") or parent.get("source"),
        "source_documents": documents, "source_tag": item.get("taxonomy_tag"),
        "formula": item.get("derivation") if derived else None,
        "source_filed_date": item.get("filed"), "source_publication_at": None,
        "source_availability_precision": "filing_date_only_not_intraday",
        "retrieved_at_utc": retrieved, "parser_contract": "sec_annual_v1",
        "asof_evidence": "filed_before_evaluation_utc_date",
    }


def build_source_evidence(issuer, evaluation_time):
    """Label fact provenance. No historical replay guarantee is implied."""
    if evaluation_time.tzinfo is None:
        raise ValueError("Evaluation time must be timezone aware")
    retrieved = _retrieved(issuer.get("retrieved_at_utc"))
    out = {
        "schema_version": VERSION,
        "evaluation_cutoff_utc": evaluation_time.astimezone(timezone.utc).isoformat(),
        "retrieved_at_utc": retrieved,
        "source_availability": "date_only_or_current_snapshot_no_verified_intraday_publication",
        "historical_replay_verified": False,
        "facts": [], "warnings": [],
    }
    if issuer.get("market") == "us":
        history = issuer.get("financial_history") or {}
        cutoff_date = evaluation_time.astimezone(timezone.utc).date().isoformat()
        for metric in ANNUAL_FIELDS:
            for record in history.get(metric, []):
                if not isinstance(record, dict):
                    continue
                filed = record.get("filed")
                if not isinstance(filed, str) or filed >= cutoff_date:
                    out["warnings"].append("SEC fact date availability unverified: " + metric)
                    continue
                out["facts"].append(_sec_observation(metric, record, retrieved))
        if not out["facts"]:
            out["warnings"].append("No verified prior-day SEC companyfacts in current input")
        out["warnings"].append("SEC filed date is not a verified exact publication timestamp")
    elif issuer.get("market") == "tw":
        for record in issuer.get("facts", []):
            if not isinstance(record, dict) or record.get("metric") != "monthly_reported_revenue":
                continue
            unit = record.get("unit")
            out["facts"].append({
                "metric": record["metric"], "value": record.get("value"),
                "unit": unit, "scale": 1000 if unit == "TWD_thousands" else None,
                "currency": "TWD" if unit == "TWD_thousands" else None,
                "statement_scope": "monthly_non_audited_revenue",
                "period_raw": record.get("period"), "source": record.get("source"),
                "source_documents": [],
                "source_filed_date": record.get("reported_at"),
                "source_publication_at": None,
                "source_availability_precision": "current_snapshot_not_historical",
                "retrieved_at_utc": _retrieved(record.get("retrieved_at_utc")) or retrieved,
                "parser_contract": "twse_monthly_revenue_v1",
                "asof_evidence": "not_verified_for_historical_cutoff",
            })
        out["warnings"].append(
            "TWSE latest profile/monthly revenue cannot reconstruct historical publication time")
    else:
        out["warnings"].append("Unknown issuer market and source")
    return out
