"""Guarded, illustrative P/FCF valuation for non-financial US issuers.

This is a sensitivity study of historical owner cash-generation, not a DCF,
intrinsic-value assertion, entry price, target or buy recommendation.
"""
from datetime import date
from statistics import median
import math

MULTIPLES = (("conservative", 10.0), ("base", 15.0), ("optimistic", 20.0))
TW_FCF_MULTIPLES = (("conservative", 15.0), ("base", 20.0), ("optimistic", 25.0))
TW_PE_MULTIPLES = (("conservative", 20.0), ("base", 25.0), ("optimistic", 30.0))


def _evaluate_tw_valuation(issuer, asof, result):
    code = str(issuer.get("industry_code") or "").strip().zfill(2)
    if code == "17":
        result["why"] = "TWSE financial sector 17 requires a different valuation contract"
        return result
    h = issuer.get("financial_history") or {}
    if h.get("currency") != "TWD" or h.get("period_type") != "tw_ifrs_reconciled":
        result["why"] = "TWSE profile/monthly revenue are not three audited annual financial statements"
        return result
    if not h.get("reconciled_twse_openapi"):
        result["why"] = "TW financial statements are not cross-reconciled with TWSE OpenAPI"
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
    keys = {(r["period_start"], r["period_end"]) for r in recent}
    for metric in ("annual_revenue", "annual_net_income"):
        observed = {(r["period_start"], r["period_end"]): r["value"]
                    for r in h.get(metric, [])}
        if any(k not in observed or observed[k] <= 0 or
               not math.isfinite(observed[k]) for k in keys):
            result["why"] = f"Missing positive aligned {metric} for all three fiscal years"
            return result
    latest = recent[0]
    shares_rec = next((r for r in h.get("annual_diluted_shares", [])
                       if (r["period_start"], r["period_end"]) ==
                       (latest["period_start"], latest["period_end"])), None)
    if not shares_rec or shares_rec["value"] <= 0 or not math.isfinite(shares_rec["value"]):
        result["why"] = "Latest full-year ordinary share count unavailable"
        return result
    for record in recent + [shares_rec]:
        if date.fromisoformat(record["period_end"]) > asof:
            result["why"] = "Financial observation period_end is after evaluation date"
            return result

    bs = h.get("latest_balance_sheet") or {}
    denom_shares = float(bs.get("ordinary_shares") or shares_rec["value"])
    net_cash_twd = float(bs.get("net_cash")) if bs.get("net_cash") is not None else 0.0
    net_cash_per_share = net_cash_twd / denom_shares

    normalized_fcf = float(median(r["value"] for r in recent))
    fcf_per_share = normalized_fcf / denom_shares
    ttm = h.get("ttm") or {}
    ttm_fcf = ttm.get("free_cash_flow") if ttm.get("status") == "available" else None
    ttm_fcf_per_share = (float(ttm_fcf) / denom_shares) if (ttm_fcf is not None and ttm_fcf > 0) else None

    scenarios = {}
    for name, multiple in TW_FCF_MULTIPLES:
        median_ev_eq_per_share = round(fcf_per_share * multiple + net_cash_per_share, 2)
        item = {
            "indicative_twd_per_share": median_ev_eq_per_share,
            "fcf_multiple": multiple,
            "median_fcf_component_twd": round(fcf_per_share * multiple, 2),
            "net_cash_component_twd": round(net_cash_per_share, 2),
        }
        if ttm_fcf_per_share is not None:
            item["indicative_ttm_fcf_twd_per_share"] = round(ttm_fcf_per_share * multiple + net_cash_per_share, 2)
        scenarios[name] = item

    ttm_pe_scenarios = None
    ttm_eps = ttm.get("basic_eps") if ttm.get("status") == "available" else None
    if ttm_eps is not None and ttm_eps > 0:
        ttm_pe_scenarios = {
            name: {
                "indicative_twd_per_share": round(float(ttm_eps) * multiple, 2),
                "pe_multiple": multiple,
                "ttm_basic_eps_twd": float(ttm_eps),
            }
            for name, multiple in TW_PE_MULTIPLES
        }

    result.update({
        "status": "illustrative_only",
        "method": "ev_bridged_three_year_median_fcf_and_ttm_pe_scenarios",
        "currency": "TWD",
        "fair_value_scenarios": scenarios,
        "ttm_pe_scenarios": ttm_pe_scenarios,
        "exchange_multiples": h.get("exchange_multiples"),
        "asof": asof.isoformat(),
        "latest_fiscal_end": latest["period_end"],
        "latest_balance_sheet_end": bs.get("period_end", latest["period_end"]),
        "normalized_annual_fcf_twd": normalized_fcf,
        "ttm_fcf_twd": ttm_fcf,
        "fcf_twd_per_ordinary_share": round(fcf_per_share, 4),
        "ttm_fcf_twd_per_ordinary_share": round(ttm_fcf_per_share, 4) if ttm_fcf_per_share is not None else None,
        "net_cash_twd": net_cash_twd,
        "net_cash_twd_per_ordinary_share": round(net_cash_per_share, 4),
        "annual_fcf_observations": recent,
        "denominator": {
            "value": denom_shares,
            "unit": "shares",
            "basis": "ordinary_share_capital_divided_by_10_twd_par_reconciled_with_twse_t187ap03",
            "period_end": bs.get("period_end", latest["period_end"]),
        },
        "assumptions": {
            "historical_years": 3,
            "annual_fcf": "operating cash flow minus reported positive PP&E capital expenditure",
            "normalization": "median of latest three complete consecutive fiscal years (FY2023-FY2025) plus TTM comparison",
            "ev_to_equity_bridge": "add verified balance-sheet net cash (CashAndCashEquivalents minus BondsPayable and LongtermBorrowings)",
            "ttm_pe_basis": "trailing 4-quarter basic EPS (when share count drift < 0.5%) times 20x/25x/30x illustrative P/E multiples",
            "multiple_basis": "illustrative sensitivity bands only; not empirically calibrated or a target price",
        },
        "why": "Illustrative EV-bridged P/FCF and TTM P/E scenario sensitivities only; no executable entry/exit, stop-loss, target price, or buy/sell recommendation",
    })
    return result


def evaluate_valuation(issuer, asof):
    result = {
        "status": "not_evaluated", "method": None, "fair_value_scenarios": None,
        "entry_zone": None, "stop_loss": None, "target_price": None,
        "why": "Insufficient verified annual statements for a defensible valuation",
    }
    if issuer.get("market") == "tw":
        return _evaluate_tw_valuation(issuer, asof, result)
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
