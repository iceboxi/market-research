"""Guarded, illustrative P/FCF valuation for non-financial US issuers.

This is a sensitivity study of historical owner cash-generation, not a DCF,
intrinsic-value assertion, entry price, target or buy recommendation.
"""
from datetime import date
from statistics import median
import math

MULTIPLES = (("conservative", 10.0), ("base", 15.0), ("optimistic", 20.0))


def evaluate_valuation(issuer, asof):
    result = {
        "status": "not_evaluated", "method": None, "fair_value_scenarios": None,
        "entry_zone": None, "stop_loss": None, "target_price": None,
        "why": "Insufficient verified annual statements for a defensible valuation",
    }
    gate = issuer.get("instrument_eligibility")
    if gate is not None and gate.get("status") != "eligible":
        result["why"] = "Instrument/model eligibility blocked: " + str(gate.get("reason"))
        return result
    if issuer.get("market") != "us":
        result["why"] = "TWSE profile/monthly revenue are not three audited annual financial statements"
        return result
    industry = issuer.get("industry") or {}
    sic = industry.get("sic")
    if not isinstance(sic, int):
        result["why"] = "SEC SIC classification unavailable; sector-aware model gate blocked"
        return result
    if 6000 <= sic <= 6999:
        result["why"] = "Financial, insurance and real-estate SIC require a different valuation contract"
        return result
    h = issuer.get("financial_history") or {}
    if h.get("currency") != "USD" or h.get("period_type") != "annual_10k":
        result["why"] = "No normalized SEC annual USD financial history"
        return result
    cashflows = h.get("annual_free_cash_flow") or []
    if len(cashflows) < 3:
        result["why"] = "Require at least three complete annual operating cash flow and capex pairs"
        return result
    recent = sorted(cashflows, key=lambda r: r["period_end"], reverse=True)[:3]
    ends = [date.fromisoformat(r["period_end"]) for r in recent]
    if (asof - ends[0]).days > 550 or any(
        not 300 <= (ends[i] - ends[i + 1]).days <= 430 for i in range(2)
    ):
        result["why"] = "Latest three fiscal years are stale or not consecutive"
        return result
    if any(r["value"] <= 0 or not math.isfinite(r["value"]) for r in recent):
        result["why"] = "All three historical annual FCF observations must be positive and finite"
        return result
    # Profit and revenue must be available for each *matching fiscal duration*.
    keys = {(r["period_start"], r["period_end"]) for r in recent}
    for metric in ("annual_revenue", "annual_net_income"):
        observed = {(r["period_start"], r["period_end"]): r["value"]
                    for r in h.get(metric, [])}
        if any(k not in observed or observed[k] <= 0 or
               not math.isfinite(observed[k]) for k in keys):
            result["why"] = f"Missing positive aligned {metric} for all three fiscal years"
            return result
    latest = recent[0]
    shares = next((r for r in h.get("annual_diluted_shares", [])
                   if (r["period_start"], r["period_end"]) ==
                   (latest["period_start"], latest["period_end"])), None)
    if not shares or shares["value"] <= 0 or not math.isfinite(shares["value"]):
        result["why"] = "Latest full-year diluted average share count unavailable"
        return result
    for record in recent + [shares]:
        if date.fromisoformat(record["filed"]) > asof:
            result["why"] = "Financial observation filed after evaluation date"
            return result

    normalized = float(median(r["value"] for r in recent))
    per_share = normalized / shares["value"]
    if not math.isfinite(per_share) or per_share <= 0:
        result["why"] = "Invalid normalized per-share free cash flow"
        return result
    scenarios = {
        name: {
            "indicative_usd_per_share": round(per_share * multiple, 2),
            "fcf_multiple": multiple,
        }
        for name, multiple in MULTIPLES
    }
    result.update({
        "status": "illustrative_only",
        "method": "three_year_median_historical_fcf_times_assumed_equity_multiple",
        "currency": "USD",
        "fair_value_scenarios": scenarios,
        "asof": asof.isoformat(),
        "latest_fiscal_end": latest["period_end"],
        "normalized_annual_fcf_usd": normalized,
        "fcf_usd_per_diluted_average_share": round(per_share, 6),
        "annual_fcf_observations": recent,
        "denominator": shares,
        "assumptions": {
            "historical_years": 3,
            "annual_fcf": "operating cash flow minus reported positive PP&E payments",
            "normalization": "median of latest three complete consecutive fiscal years",
            "multiple_basis": "illustrative, hard-coded sensitivities; not empirically calibrated",
        },
        "why": "Scenario sensitivities only; no defensible executable entry/exit, forward cash-flow forecast, net debt adjustment, current shares or risk-adjusted fair value",
    })
    return result
