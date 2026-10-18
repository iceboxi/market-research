"""Point-in-time annual comparison without conflating research and trading advice."""
from datetime import date
import math

METRICS = ("annual_revenue", "annual_net_income", "annual_operating_cash_flow",
           "annual_capex", "annual_free_cash_flow", "annual_diluted_shares")


def compare_financials(issuer, asof):
    result = {"status": "unavailable", "source": None, "currency": "USD",
              "rows": [], "coverage": {k: 0 for k in METRICS}, "warnings": []}
    if issuer.get("market") != "us":
        result["warnings"].append("Taiwan IFRS annual statements unavailable; monthly revenue is not annual financials")
        return result
    history = issuer.get("financial_history") or {}
    if history.get("currency") != "USD" or history.get("period_type") != "annual_10k":
        result["warnings"].append("Normalized SEC annual USD statements unavailable")
        return result
    result["source"] = history.get("source")
    periods = {}
    for metric in METRICS:
        for item in history.get(metric, []):
            try:
                start, end, filed = [date.fromisoformat(item[x]) for x in
                                     ("period_start", "period_end", "filed")]
                value = item["value"]
            except (ValueError, KeyError, TypeError):
                continue
            if (not isinstance(value, (int, float)) or isinstance(value, bool)
                    or not math.isfinite(value) or end > asof or filed > asof
                    or not 330 <= (end - start).days <= 380):
                continue
            periods.setdefault((start.isoformat(), end.isoformat()), {})[metric] = item
    # The same fiscal end with a different fiscal start cannot be merged.
    by_end = {}
    for (start, end), metrics in periods.items():
        if end not in by_end or len(metrics) > len(by_end[end][1]):
            by_end[end] = (start, metrics)
    for end in sorted(by_end, reverse=True)[:6]:
        start, facts = by_end[end]
        values = {k: facts[k]["value"] if k in facts else None for k in METRICS}
        sources = {k: {"filed": v["filed"], "source": v.get("source", history.get("source")),
                       "accession": v.get("accession"), "taxonomy_tag": v.get("taxonomy_tag")}
                   for k, v in facts.items()}
        for metric in facts:
            result["coverage"][metric] += 1
        revenue = values["annual_revenue"]
        def margin(metric):
            v = values[metric]
            return round(100 * v / revenue, 2) if v is not None and revenue is not None and revenue > 0 else None
        row = {"period_start": start, "period_end": end, "metrics": values,
               "net_margin_pct": margin("annual_net_income"),
               "fcf_margin_pct": margin("annual_free_cash_flow"),
               "missing_metrics": [k for k in METRICS if k not in facts],
               "filing_provenance": sources}
        result["rows"].append(row)
    if result["rows"]:
        result["status"] = "available"
        if len(result["rows"]) < 3:
            result["warnings"].append("Fewer than three comparable fiscal years")
        for row in result["rows"][:3]:
            if row["missing_metrics"]:
                result["warnings"].append(row["period_end"] + " missing " + ", ".join(row["missing_metrics"]))
    else:
        result["warnings"].append("No annual SEC fiscal years available as of report date")
    return result


def research_status(financial, valuation, technical):
    if valuation["status"] == "illustrative_only":
        stage = "illustrative_valuation_available"
    elif financial["status"] == "available":
        stage = "financial_review_only"
    else:
        stage = "preliminary_only"
    matches = [x["strategy_id"] for x in technical.get("observations", [])
               if x.get("active") and x.get("matched")]
    return {"stage": stage, "valuation_reason": valuation.get("why"),
            "technical_status": technical.get("status"),
            "active_pattern_observations": matches, "entry_exit_status": "not_evaluated",
            "investment_recommendation": "not_available"}


def render_financial_research(financial, readiness):
    lines = ["", "## Annual financial comparison", ""]
    if financial["status"] != "available":
        lines.append("Comparable annual statements unavailable; cannot infer them from monthly revenue.")
    else:
        lines += ["SEC annual 10-K, original USD (shares for diluted counts); missing facts show —, not 0.",
                  "", "| Fiscal end | Revenue | Net income | Operating CF | Capex | FCF | Diluted shares | Net margin | FCF margin |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for row in financial["rows"]:
            vals = row["metrics"]
            def fmt(k):
                v = vals[k]
                return f"{v:,.0f}" if v is not None else "—"
            def pct(k):
                v = row[k]
                return f"{v:.2f}%" if v is not None else "—"
            lines.append(
                f"| {row['period_end']} | {fmt('annual_revenue')} | "
                f"{fmt('annual_net_income')} | {fmt('annual_operating_cash_flow')} | "
                f"{fmt('annual_capex')} | {fmt('annual_free_cash_flow')} | "
                f"{fmt('annual_diluted_shares')} | {pct('net_margin_pct')} | {pct('fcf_margin_pct')} |"
            )
        lines += ["", "SEC source: " + str(financial["source"]),
                  "Filing dates, accession and taxonomy tags for each metric: report.json."]
    if financial["warnings"]:
        lines += ["", "**Financial coverage limitations**"]
        lines.extend("- " + v for v in financial["warnings"])
    lines += ["", "## Research readiness", "",
              "**" + readiness["stage"] + "**",
              "Valuation: " + str(readiness["valuation_reason"]),
              "Active technical observations: " + (", ".join(readiness["active_pattern_observations"]) or "none"),
              "No validated trading entry, stop-loss or target. No buy/sell recommendation."]
    return lines
