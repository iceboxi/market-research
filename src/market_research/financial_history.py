"""Normalized, point-in-time SEC annual 10-K financial observations.

Amounts are kept in original USD, never scaled into millions. The original
start/end dates, filing dates, taxonomy tags and accessions remain attached.
"""
from datetime import date, datetime
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

# F04-A: direct quarter observations, intentionally independent of FY/YTD facts.
# Do not infer fiscal Q number from calendar dates or manufacture a fourth quarter.
DIRECT_QUARTER_METRICS = {
    "quarterly_revenue": ("USD", METRICS["annual_revenue"][1]),
    "quarterly_gross_profit": ("USD", ("GrossProfit",)),
    "quarterly_net_income": ("USD", METRICS["annual_net_income"][1]),
    "quarterly_basic_eps": ("USD/shares", ("EarningsPerShareBasic",)),
    "quarterly_diluted_eps": ("USD/shares", ("EarningsPerShareDiluted",)),
    "quarterly_operating_cash_flow": ("USD", METRICS["annual_operating_cash_flow"][1]),
    "quarterly_capex": ("USD", METRICS["annual_capex"][1]),
}


def direct_quarter_version_trace(raw, tags, unit, asof, source, limit=12):
    """Read SEC-reported *direct* 75–106 day quarterly durations only.

    "filed" is a date-only conservative eligibility bound, NOT a precise
    publication timestamp. Caller owns issuer identity and its history.
    No YTD subtraction, annual/FY inference or 10-K-based synthetic Q4.
    """
    if not isinstance(asof, date) or isinstance(asof, datetime):
        raise TypeError("asof must be a date without a time-of-day")
    if not 1 <= limit <= 32 or not tags:
        raise ValueError("Invalid trace limit or concept candidates")
    concepts = raw.get("facts", {}).get("us-gaap", {})
    grouped = {}
    conflicting_spans = set()
    for priority, tag in enumerate(tags):
        facts = concepts.get(tag, {}).get("units", {}).get(unit, [])
        for row in facts:
            if row.get("form") not in ("10-Q", "10-Q/A", "10-K", "10-K/A"):
                continue
            try:
                start = date.fromisoformat(row["start"])
                end = date.fromisoformat(row["end"])
                filed = date.fromisoformat(row["filed"])
                original_value = row["val"]
                if isinstance(original_value, bool):
                    continue
                value = float(original_value)
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if (not 75 <= (end - start).days <= 106 or end > asof
                    or filed < end or filed > asof or not math.isfinite(value)):
                continue
            accession = row.get("accn")
            if not isinstance(accession, str) or not accession.strip():
                continue
            span = (start.isoformat(), end.isoformat())
            key = (span, filed.isoformat(), accession, tag)
            record = {
                "value": value, "unit": unit, "period_start": span[0],
                "period_end": span[1], "filed": filed.isoformat(),
                "taxonomy_tag": tag, "accession": accession,
                "form": row["form"], "source": source,
            }
            previous = grouped.get(key)
            if previous is not None and (previous["value"] != value
                                         or previous["form"] != record["form"]):
                conflicting_spans.add(span)
            else:
                grouped[key] = record

    spans = {}
    for (span, _, _, _), record in grouped.items():
        spans.setdefault(span, []).append(record)
    traces = []
    for span in sorted(set(spans) | conflicting_spans,
                       key=lambda s: (s[1], s[0]), reverse=True)[:limit]:
        versions = spans.get(span, [])
        # Same-day distinct accessions cannot be ordered by date-only evidence.
        # Competing taxonomy tags with different numbers in the same filing
        # cannot be treated as interchangeable either.
        by_day = {}
        by_accession = {}
        for item in versions:
            by_day.setdefault(item["filed"], set()).add(item["accession"])
            by_accession.setdefault((item["filed"], item["accession"]), set()).add(item["value"])
        ambiguous = (span in conflicting_spans or
                     any(len(ids) > 1 for ids in by_day.values()) or
                     any(len(values) > 1 for values in by_accession.values()))
        ranked = sorted(versions, key=lambda r: (
            r["filed"], -tags.index(r["taxonomy_tag"]), r["accession"]), reverse=True)
        traces.append({
            "period_start": span[0], "period_end": span[1],
            "status": "ambiguous_filing_versions" if ambiguous else "available",
            "versions": ranked[:12], "version_count": len(versions),
            "selected": ranked[0] if ranked and not ambiguous else None,
            "availability_precision": "filing_date_only_not_intraday",
            "publication_time_verified": False,
            "first_seen_at": None,
        })
    return traces


def normalize_sec_direct_quarters(raw, asof, source, limit=12):
    """Separate, direct-only SEC quarterly evidence; no reporting/valuation wiring.

    Exact fiscal start/end and accession are kept per value. Derived margin is
    eligible only when both filing legs refer to the SAME period and accession.
    """
    result = {
        "source": source, "asof": asof.isoformat(), "currency": "USD",
        "period_type": "direct_quarter_only_no_ytd_derivation",
        "quarterly_version_trace": {}, "gross_margin_pct": [],
        "publication_time_verified": False,
    }
    for metric, (unit, tags) in DIRECT_QUARTER_METRICS.items():
        trace = direct_quarter_version_trace(raw, tags, unit, asof, source, limit=limit)
        result["quarterly_version_trace"][metric] = trace
        result[metric] = [record["selected"] for record in trace
                          if record["status"] == "available" and record["selected"] is not None]

    revenues = {(r["period_start"], r["period_end"]): r
                for r in result["quarterly_revenue"]}
    for gross in result["quarterly_gross_profit"]:
        key = (gross["period_start"], gross["period_end"])
        revenue = revenues.get(key)
        if (revenue is None or revenue["value"] <= 0 or
                revenue["accession"] != gross["accession"] or
                revenue["filed"] != gross["filed"] or
                revenue["unit"] != gross["unit"]):
            continue
        result["gross_margin_pct"].append({
            "value": round(100 * gross["value"] / revenue["value"], 2),
            "unit": "percent", "period_start": key[0], "period_end": key[1],
            "accession": gross["accession"], "filed": gross["filed"],
            "derivation": "same_accession_gross_profit_divided_by_revenue",
            "gross_profit": gross, "revenue": revenue, "source": source,
        })
    return result


TW_QUARTERS = {
    "03-31": (1, "01-01"),
    "06-30": (2, "04-01"),
    "09-30": (3, "07-01"),
    "12-31": (4, "10-01"),
}


def _clean_number(raw, scale=1.0):
    if raw is None or isinstance(raw, bool):
        return None
    text = str(raw).strip().replace(",", "")
    if not text or text in ("-", "--", "N/A", "null", "None"):
        return None
    try:
        val = float(text) * scale
        return val if math.isfinite(val) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _finmind_table(rows, code, asof):
    if not isinstance(rows, list):
        return {}, ["FinMind dataset missing or not a list"]
    table = {}
    warnings = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("stock_id", "")).strip() != code:
            return {}, [f"Foreign stock_id {row.get('stock_id')} in FinMind dataset"]
        dt_str = str(row.get("date", "")).strip()
        concept = str(row.get("type", "")).strip()
        val = _clean_number(row.get("value"))
        if not dt_str or not concept or val is None or dt_str[5:] not in TW_QUARTERS:
            continue
        try:
            dt = date.fromisoformat(dt_str)
        except ValueError:
            continue
        if dt > asof:
            continue
        key = (dt_str, concept)
        if key in seen and table[dt_str][concept] != val:
            return {}, [f"Conflicting duplicate FinMind row for {dt_str} {concept}"]
        seen.add(key)
        table.setdefault(dt_str, {})[concept] = val
    return table, warnings


def normalize_tw_financial_history(code, asof, finmind=None, twse=None, source=None):
    """Normalize and cross-reconcile Taiwan IFRS 3-statements, TTM, and corporate actions.

    Enforces single-quarter vs cumulative YTD disambiguation via TWSE OpenAPI
    reconciliation and EPS-to-Parent-Net-Income accounting invariants.
    """
    if not isinstance(asof, date) or isinstance(asof, datetime):
        raise TypeError("asof must be a date without a time-of-day")
    finmind = finmind or {}
    twse = twse or {}
    source_url = source or "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci"
    inc_table, w_inc = _finmind_table(finmind.get("income", []), code, asof)
    bal_table, w_bal = _finmind_table(finmind.get("balance", []), code, asof)
    cf_table, w_cf = _finmind_table(finmind.get("cashflow", []), code, asof)
    warnings = w_inc + w_bal + w_cf

    # Extract TWSE OpenAPI single-quarter parent net income map from t187ap45_L if present
    twse_q_ni = {}
    dividend_schedule = []
    for row in twse.get("dividends") or []:
        if not isinstance(row, dict) or str(row.get("公司代號", "")).strip() != code:
            continue
        roc_yr = _clean_number(row.get("股利年度") if row.get("股利年度") is not None else row.get("年度"))
        q_str = str(row.get("股利所屬年(季)度") or row.get("季別") or "").strip()
        q_num = int(q_str[1]) if len(q_str) >= 2 and q_str.startswith("第") and q_str[1].isdigit() else None
        if roc_yr and q_num in (1, 2, 3, 4):
            greg_yr = int(roc_yr) + 1911
            q_end = f"{greg_yr}-{('03-31', '06-30', '09-30', '12-31')[q_num - 1]}"
            try:
                if date.fromisoformat(q_end) > asof:
                    continue
            except ValueError:
                continue
            ni_val = _clean_number(row.get("本期淨利(淨損)(元)"))
            cash_div = _clean_number(
                row.get("股東配發-盈餘分配之現金股利(元/股)")
                if row.get("股東配發-盈餘分配之現金股利(元/股)") is not None
                else row.get("現金股利(元/股)")
            )
            stock_div = _clean_number(
                row.get("股東配發-盈餘轉增資配股(元/股)")
                if row.get("股東配發-盈餘轉增資配股(元/股)") is not None
                else row.get("股票股利(元/股)")
            )
            if ni_val is not None:
                twse_q_ni[q_end] = ni_val
            dividend_schedule.append({
                "period": f"{greg_yr}Q{q_num}",
                "period_end": q_end,
                "board_Or_approval_date_roc": str(row.get("董事會（擬議）股利分派日") or row.get("股東會日期") or "").strip() or None,
                "parent_net_income_twd": ni_val,
                "cash_dividend_per_share_twd": cash_div,
                "stock_dividend_per_share_twd": stock_div,
                "source": "https://openapi.twse.com.tw/v1/opendata/t187ap45_L",
            })
    dividend_schedule.sort(key=lambda r: r["period_end"], reverse=True)

    # Balance Sheet per quarter end
    balance_by_date = {}
    for dt_str in sorted(bal_table):
        b = bal_table[dt_str]
        cap_stock = b.get("OrdinaryShare") if b.get("OrdinaryShare") is not None else b.get("CapitalStock")
        ord_shares = round(cap_stock / 10.0) if cap_stock is not None and cap_stock > 0 else None
        cash = b.get("CashAndCashEquivalents")
        bonds = b.get("BondsPayable", 0.0) or 0.0
        lt_debt = b.get("LongtermBorrowings", 0.0) or 0.0
        st_debt = (b.get("ShortTermBorrowings", 0.0) or 0.0) + (b.get("CurrentPortionOfLongtermLiabilities", 0.0) or 0.0)
        has_debt_breakdown = any(k in b for k in ("BondsPayable", "LongtermBorrowings", "ShortTermBorrowings"))
        total_debt = (bonds + lt_debt + st_debt) if has_debt_breakdown else None
        net_cash = (cash - total_debt) if (cash is not None and total_debt is not None) else None
        balance_by_date[dt_str] = {
            "period_end": dt_str,
            "cash": cash,
            "total_assets": b.get("TotalAssets"),
            "total_liabilities": b.get("Liabilities"),
            "total_equity": b.get("Equity"),
            "parent_equity": b.get("EquityAttributableToOwnersOfParent"),
            "capital_stock": cap_stock,
            "ordinary_shares": ord_shares,
            "bonds_payable": b.get("BondsPayable"),
            "long_term_borrowings": b.get("LongtermBorrowings"),
            "total_debt": total_debt,
            "net_cash": net_cash,
        }

    # Reconcile TWSE OpenAPI t187ap06_L_ci & t187ap07_L_ci against FinMind
    twse_inc = twse.get("income") if isinstance(twse.get("income"), dict) else {}
    twse_bal = twse.get("balance") if isinstance(twse.get("balance"), dict) else {}
    twse_reconciled = False
    twse_reconciled_basis = None
    twse_period_end = None
    if str(twse_inc.get("公司代號", "")).strip() == code and str(twse_bal.get("公司代號", "")).strip() == code:
        roc_y = _clean_number(twse_inc.get("年度"))
        q_idx = _clean_number(twse_inc.get("季別"))
        if roc_y and q_idx in (1, 2, 3, 4):
            g_yr = int(roc_y) + 1911
            q_ends_for_ytd = [f"{g_yr}-{mmdd}" for mmdd in ("03-31", "06-30", "09-30", "12-31")[:int(q_idx)]]
            cand_end = q_ends_for_ytd[-1]
            if cand_end in inc_table and cand_end in bal_table:
                twse_period_end = cand_end
                f_inc = inc_table[cand_end]
                f_bal = bal_table[cand_end]
                t_rev = _clean_number(twse_inc.get("營業收入"), 1000.0)
                t_ni = _clean_number(twse_inc.get("本期淨利（淨損）"), 1000.0)
                t_assets = _clean_number(twse_bal.get("資產總計"), 1000.0)
                t_eq = _clean_number(twse_bal.get("權益總計"), 1000.0)
                sum_rev = sum(inc_table[d]["Revenue"] for d in q_ends_for_ytd) if all(d in inc_table and "Revenue" in inc_table[d] for d in q_ends_for_ytd) else None
                sum_ni = sum(inc_table[d]["IncomeAfterTaxes"] for d in q_ends_for_ytd) if all(d in inc_table and "IncomeAfterTaxes" in inc_table[d] for d in q_ends_for_ytd) else None
                ytd_match = (
                    t_rev is not None and f_inc.get("Revenue") is not None and abs(f_inc["Revenue"] - t_rev) <= 1000.0 and
                    t_ni is not None and f_inc.get("IncomeAfterTaxes") is not None and abs(f_inc["IncomeAfterTaxes"] - t_ni) <= 1000.0
                )
                sum_q_match = (
                    t_rev is not None and sum_rev is not None and abs(sum_rev - t_rev) <= 1000.0 and
                    t_ni is not None and sum_ni is not None and abs(sum_ni - t_ni) <= 1000.0
                )
                bal_match = (
                    t_assets is not None and f_bal.get("TotalAssets") is not None and abs(f_bal["TotalAssets"] - t_assets) <= 1000.0 and
                    t_eq is not None and f_bal.get("Equity") is not None and abs(f_bal["Equity"] - t_eq) <= 1000.0
                )
                if (ytd_match or sum_q_match) and bal_match:
                    twse_reconciled = True
                    twse_reconciled_basis = "reported_ytd" if ytd_match else "sum_quarters"

    # Standalone Quarter Income Statement & Cash Flow derivation by fiscal year
    years = sorted({d[:4] for d in set(inc_table) | set(cf_table)})
    standalone_quarters = {}
    cumulative_interims = {}
    FLOW_KEYS = ("Revenue", "GrossProfit", "OperatingIncome", "PreTaxIncome",
                 "IncomeAfterTaxes", "EquityAttributableToOwnersOfParent")
    REQUIRED_FLOW_KEYS = ("Revenue", "GrossProfit", "OperatingIncome", "IncomeAfterTaxes")

    for yr in years:
        q_dates = [f"{yr}-{mmdd}" for mmdd in ("03-31", "06-30", "09-30", "12-31")]
        prior_inc_sums = {k: 0.0 for k in FLOW_KEYS}
        prior_key_complete = {k: True for k in FLOW_KEYS}
        prior_eps_sum = 0.0
        prior_inc_complete = True
        prev_cf_ytd = None
        for idx, q_date in enumerate(q_dates, start=1):
            q_num, q_start_mmdd = TW_QUARTERS[q_date[5:]]
            q_start = f"{yr}-{q_start_mmdd}"
            inc = inc_table.get(q_date)
            cf = cf_table.get(q_date)
            bs = balance_by_date.get(q_date, {})
            if not inc:
                prior_inc_complete = False
                for k in FLOW_KEYS:
                    prior_key_complete[k] = False
                prev_cf_ytd = None
                continue
            eps = inc.get("EPS")
            parent_ni = inc.get("EquityAttributableToOwnersOfParent")
            if parent_ni is None:
                parent_ni = inc.get("IncomeAfterTaxes")
            shares = bs.get("ordinary_shares")
            # Determine if FinMind income flows on q_date are standalone 3M or cumulative YTD
            basis = None
            if q_num == 1:
                basis = "standalone_q1"
            else:
                if q_date in twse_q_ni and parent_ni is not None and abs(parent_ni - twse_q_ni[q_date]) <= max(5000.0, abs(twse_q_ni[q_date]) * 0.001):
                    basis = "standalone_reconciled_t187ap45"
                elif q_date == twse_period_end and twse_reconciled and twse_reconciled_basis == "reported_ytd":
                    basis = "ytd_reconciled_t187ap06"
                elif q_date == twse_period_end and twse_reconciled and twse_reconciled_basis == "sum_quarters":
                    basis = "standalone_reconciled_t187ap06_sum_quarters"
                elif shares and shares > 0 and parent_ni is not None and eps is not None:
                    implied = parent_ni / shares
                    if abs(implied - eps) <= 0.35:
                        basis = "standalone_eps_identity"
                    elif prior_inc_complete and abs(implied - (prior_eps_sum + eps)) <= 0.35:
                        basis = "ytd_eps_identity"
            if basis is None:
                warnings.append(f"Ambiguous standalone vs YTD income basis for {q_date}")
                prior_inc_complete = False
                for k in FLOW_KEYS:
                    prior_key_complete[k] = False
                continue

            if basis.startswith("ytd_"):
                if not prior_inc_complete:
                    warnings.append(f"Cannot derive standalone quarter for {q_date} without prior quarters")
                    continue
                q_flows = {
                    k: (inc[k] - prior_inc_sums[k]) if (inc.get(k) is not None and prior_key_complete[k]) else None
                    for k in FLOW_KEYS
                }
                cumulative_interims[q_date] = {
                    "period_label": f"{yr}-H1" if q_num == 2 else f"{yr}-9M" if q_num == 3 else f"{yr}-FY",
                    "period_start": f"{yr}-01-01",
                    "period_end": q_date,
                    "revenue": inc.get("Revenue"),
                    "gross_profit": inc.get("GrossProfit"),
                    "operating_income": inc.get("OperatingIncome"),
                    "pre_tax_income": inc.get("PreTaxIncome"),
                    "net_income": inc.get("IncomeAfterTaxes"),
                    "parent_net_income": inc.get("EquityAttributableToOwnersOfParent"),
                    "basic_eps": round(prior_eps_sum + eps, 2) if eps is not None else None,
                    "operating_cash_flow": cf.get("CashFlowsFromOperatingActivities") if cf else None,
                    "capex": abs(cf["PropertyAndPlantAndEquipment"]) if cf and cf.get("PropertyAndPlantAndEquipment") is not None and cf["PropertyAndPlantAndEquipment"] < 0 else None,
                    "free_cash_flow": (
                        cf["CashFlowsFromOperatingActivities"] - abs(cf["PropertyAndPlantAndEquipment"])
                        if cf and cf.get("CashFlowsFromOperatingActivities") is not None
                        and cf.get("PropertyAndPlantAndEquipment") is not None and cf["PropertyAndPlantAndEquipment"] < 0
                        else None
                    ),
                    "reconciled_twse_openapi": q_date == twse_period_end and twse_reconciled,
                }
            else:
                q_flows = {k: inc.get(k) for k in FLOW_KEYS}
                if q_num == 2 and prior_inc_complete and all(q_flows.get(k) is not None for k in ("Revenue", "GrossProfit", "OperatingIncome", "IncomeAfterTaxes")):
                    cumulative_interims[q_date] = {
                        "period_label": f"{yr}-H1",
                        "period_start": f"{yr}-01-01",
                        "period_end": q_date,
                        "revenue": prior_inc_sums["Revenue"] + q_flows["Revenue"],
                        "gross_profit": prior_inc_sums["GrossProfit"] + q_flows["GrossProfit"],
                        "operating_income": prior_inc_sums["OperatingIncome"] + q_flows["OperatingIncome"],
                        "pre_tax_income": (prior_inc_sums["PreTaxIncome"] + q_flows["PreTaxIncome"]) if (q_flows.get("PreTaxIncome") is not None and prior_key_complete["PreTaxIncome"]) else None,
                        "net_income": prior_inc_sums["IncomeAfterTaxes"] + q_flows["IncomeAfterTaxes"],
                        "parent_net_income": (prior_inc_sums["EquityAttributableToOwnersOfParent"] + q_flows["EquityAttributableToOwnersOfParent"]) if (q_flows.get("EquityAttributableToOwnersOfParent") is not None and prior_key_complete["EquityAttributableToOwnersOfParent"]) else None,
                        "basic_eps": round(prior_eps_sum + eps, 2) if eps is not None else None,
                        "operating_cash_flow": cf.get("CashFlowsFromOperatingActivities") if cf else None,
                        "capex": abs(cf["PropertyAndPlantAndEquipment"]) if cf and cf.get("PropertyAndPlantAndEquipment") is not None and cf["PropertyAndPlantAndEquipment"] < 0 else None,
                        "free_cash_flow": (
                            cf["CashFlowsFromOperatingActivities"] - abs(cf["PropertyAndPlantAndEquipment"])
                            if cf and cf.get("CashFlowsFromOperatingActivities") is not None
                            and cf.get("PropertyAndPlantAndEquipment") is not None and cf["PropertyAndPlantAndEquipment"] < 0
                            else None
                        ),
                        "reconciled_twse_openapi": q_date == twse_period_end and twse_reconciled,
                    }

            for k in FLOW_KEYS:
                if q_flows.get(k) is not None:
                    prior_inc_sums[k] += q_flows[k]
                else:
                    prior_key_complete[k] = False
                    if k in REQUIRED_FLOW_KEYS:
                        prior_inc_complete = False
            if eps is not None:
                prior_eps_sum += eps
            else:
                prior_inc_complete = False

            # Standalone quarterly cash flow from YTD CF
            q_cfo, q_capex, q_fcf = None, None, None
            if cf and cf.get("CashFlowsFromOperatingActivities") is not None and cf.get("PropertyAndPlantAndEquipment") is not None and cf["PropertyAndPlantAndEquipment"] < 0:
                cfo_ytd = cf["CashFlowsFromOperatingActivities"]
                capex_ytd = abs(cf["PropertyAndPlantAndEquipment"])
                if q_num == 1:
                    q_cfo, q_capex = cfo_ytd, capex_ytd
                    prev_cf_ytd = (cfo_ytd, capex_ytd)
                elif prev_cf_ytd is not None:
                    q_cfo = cfo_ytd - prev_cf_ytd[0]
                    q_capex = capex_ytd - prev_cf_ytd[1]
                    prev_cf_ytd = (cfo_ytd, capex_ytd)
                if q_cfo is not None and q_capex is not None:
                    q_fcf = q_cfo - q_capex
            else:
                prev_cf_ytd = None

            rev = q_flows.get("Revenue")
            def _pct(val):
                return round(100.0 * val / rev, 2) if val is not None and rev and rev > 0 else None

            standalone_quarters[q_date] = {
                "period_label": f"{yr}Q{q_num}",
                "period_start": q_start,
                "period_end": q_date,
                "basis": basis,
                "revenue": rev,
                "gross_profit": q_flows.get("GrossProfit"),
                "operating_income": q_flows.get("OperatingIncome"),
                "pre_tax_income": q_flows.get("PreTaxIncome"),
                "net_income": q_flows.get("IncomeAfterTaxes"),
                "parent_net_income": q_flows.get("EquityAttributableToOwnersOfParent"),
                "basic_eps": eps,
                "operating_cash_flow": q_cfo,
                "capex": q_capex,
                "free_cash_flow": q_fcf,
                "gross_margin_pct": _pct(q_flows.get("GrossProfit")),
                "operating_margin_pct": _pct(q_flows.get("OperatingIncome")),
                "net_margin_pct": _pct(q_flows.get("IncomeAfterTaxes")),
                "fcf_margin_pct": _pct(q_fcf),
                "ordinary_shares": shares,
            }

    # Build Annual History (FY2023, FY2024, FY2025)
    annual_records = {
        "annual_revenue": [],
        "annual_gross_profit": [],
        "annual_operating_income": [],
        "annual_net_income": [],
        "annual_parent_net_income": [],
        "annual_basic_eps": [],
        "annual_operating_cash_flow": [],
        "annual_capex": [],
        "annual_free_cash_flow": [],
        "annual_diluted_shares": [],
    }
    for yr in sorted(years, reverse=True):
        q_dates = [f"{yr}-{mmdd}" for mmdd in ("03-31", "06-30", "09-30", "12-31")]
        if not all(d in standalone_quarters for d in q_dates):
            continue
        fy_start, fy_end = f"{yr}-01-01", f"{yr}-12-31"
        # Statutory TWSE/MOPS annual filing deadline is March 31 of the following year
        statutory_filed = f"{int(yr) + 1}-03-31"
        filed_date = statutory_filed if statutory_filed <= asof.isoformat() else fy_end
        qs = [standalone_quarters[d] for d in q_dates]
        cf_end = cf_table.get(fy_end, {})
        bs_end = balance_by_date.get(fy_end, {})

        def _rec(val, unit, tag, accn_suffix):
            return {
                "value": float(val),
                "unit": unit,
                "period_start": fy_start,
                "period_end": fy_end,
                "filed": filed_date,
                "taxonomy_tag": tag,
                "accession": f"tw-ifrs-{code}-{yr}-{accn_suffix}",
                "form": "TW-IFRS-Annual",
                "source": source_url,
            }

        if all(q["revenue"] is not None for q in qs):
            annual_records["annual_revenue"].append(_rec(sum(q["revenue"] for q in qs), "TWD", "Revenue", "IS"))
        if all(q["gross_profit"] is not None for q in qs):
            annual_records["annual_gross_profit"].append(_rec(sum(q["gross_profit"] for q in qs), "TWD", "GrossProfit", "IS"))
        if all(q["operating_income"] is not None for q in qs):
            annual_records["annual_operating_income"].append(_rec(sum(q["operating_income"] for q in qs), "TWD", "OperatingIncome", "IS"))
        if all(q["net_income"] is not None for q in qs):
            annual_records["annual_net_income"].append(_rec(sum(q["net_income"] for q in qs), "TWD", "IncomeAfterTaxes", "IS"))
        if all(q["parent_net_income"] is not None for q in qs):
            annual_records["annual_parent_net_income"].append(_rec(sum(q["parent_net_income"] for q in qs), "TWD", "EquityAttributableToOwnersOfParent", "IS"))
        if all(q["basic_eps"] is not None for q in qs):
            annual_records["annual_basic_eps"].append(_rec(round(sum(q["basic_eps"] for q in qs), 2), "TWD/shares", "BasicEarningsPerShare", "IS"))

        cfo_val = cf_end.get("CashFlowsFromOperatingActivities")
        capex_raw = cf_end.get("PropertyAndPlantAndEquipment")
        if cfo_val is not None and capex_raw is not None and capex_raw < 0:
            cfo_rec = _rec(cfo_val, "TWD", "CashFlowsFromOperatingActivities", "CF")
            capex_rec = _rec(abs(capex_raw), "TWD", "PropertyAndPlantAndEquipment", "CF")
            annual_records["annual_operating_cash_flow"].append(cfo_rec)
            annual_records["annual_capex"].append(capex_rec)
            annual_records["annual_free_cash_flow"].append({
                "value": float(cfo_val - abs(capex_raw)),
                "unit": "TWD",
                "period_start": fy_start,
                "period_end": fy_end,
                "filed": filed_date,
                "derivation": "operating_cash_flow_minus_positive_capex",
                "operating_cash_flow": cfo_rec,
                "capex": capex_rec,
                "source": source_url,
            })
        if bs_end.get("ordinary_shares"):
            annual_records["annual_diluted_shares"].append(
                _rec(bs_end["ordinary_shares"], "shares", "IssuedOrdinarySharesFromCapitalStockPar10", "BS")
            )

    # Build 4-Quarter TTM from latest 4 consecutive standalone quarters
    sorted_q_dates = sorted(standalone_quarters)
    ttm = {"status": "not_evaluated", "reason": "Fewer than four consecutive verified quarters"}
    if len(sorted_q_dates) >= 4:
        last4_dates = sorted_q_dates[-4:]
        d0 = date.fromisoformat(last4_dates[0])
        d3 = date.fromisoformat(last4_dates[-1])
        if 260 <= (d3 - d0).days <= 280:
            q4 = [standalone_quarters[d] for d in last4_dates]
            if all(q["revenue"] is not None and q["net_income"] is not None for q in q4):
                ttm_rev = sum(q["revenue"] for q in q4)
                ttm_gp = sum(q["gross_profit"] for q in q4) if all(q["gross_profit"] is not None for q in q4) else None
                ttm_op = sum(q["operating_income"] for q in q4) if all(q["operating_income"] is not None for q in q4) else None
                ttm_ni = sum(q["net_income"] for q in q4)
                ttm_pni = sum(q["parent_net_income"] for q in q4) if all(q["parent_net_income"] is not None for q in q4) else None
                ttm_cfo = sum(q["operating_cash_flow"] for q in q4) if all(q["operating_cash_flow"] is not None for q in q4) else None
                ttm_capex = sum(q["capex"] for q in q4) if all(q["capex"] is not None for q in q4) else None
                ttm_fcf = (ttm_cfo - ttm_capex) if (ttm_cfo is not None and ttm_capex is not None) else None
                q_shares = [q["ordinary_shares"] for q in q4 if q.get("ordinary_shares")]
                share_drift = ((max(q_shares) - min(q_shares)) / min(q_shares)) if len(q_shares) == 4 and min(q_shares) > 0 else None
                ttm_eps = round(sum(q["basic_eps"] for q in q4), 2) if (
                    all(q["basic_eps"] is not None for q in q4) and share_drift is not None and share_drift <= 0.005
                ) else None
                def _tpct(v):
                    return round(100.0 * v / ttm_rev, 2) if v is not None and ttm_rev > 0 else None
                ttm = {
                    "status": "available",
                    "period_start": q4[0]["period_start"],
                    "period_end": q4[-1]["period_end"],
                    "quarters": [q["period_label"] for q in q4],
                    "quarter_ends": last4_dates,
                    "revenue": ttm_rev,
                    "gross_profit": ttm_gp,
                    "operating_income": ttm_op,
                    "net_income": ttm_ni,
                    "parent_net_income": ttm_pni,
                    "basic_eps": ttm_eps,
                    "eps_derivation": "sum_of_four_quarters_within_0.5pct_share_drift" if ttm_eps is not None else "not_evaluated",
                    "share_count_max_drift_pct": round(share_drift * 100.0, 6) if share_drift is not None else None,
                    "operating_cash_flow": ttm_cfo,
                    "capex": ttm_capex,
                    "free_cash_flow": ttm_fcf,
                    "gross_margin_pct": _tpct(ttm_gp),
                    "operating_margin_pct": _tpct(ttm_op),
                    "net_margin_pct": _tpct(ttm_ni),
                    "fcf_margin_pct": _tpct(ttm_fcf),
                }

    # Ex-dividend & corporate actions from FinMind TaiwanStockDividendResult + TWSE BWIBBU_ALL
    ex_dividend_events = []
    for row in finmind.get("dividend_result") or []:
        if not isinstance(row, dict) or str(row.get("stock_id", "")).strip() != code:
            continue
        dt_str = str(row.get("date", "")).strip()
        try:
            if date.fromisoformat(dt_str) > asof:
                continue
        except ValueError:
            continue
        raw_a = row.get("stock_and_cache_dividend")
        raw_b = row.get("stock_or_cache_dividend")
        val_a, val_b = _clean_number(raw_a), _clean_number(raw_b)
        div_val = val_a if val_a is not None else val_b
        div_type = str(raw_b if val_a is not None else raw_a or "").strip() or None
        ex_dividend_events.append({
            "ex_date": dt_str,
            "type": div_type,
            "dividend_per_share_twd": div_val,
            "before_price": _clean_number(row.get("before_price")),
            "reference_price": _clean_number(row.get("reference_price")),
        })
    ex_dividend_events.sort(key=lambda r: r["ex_date"], reverse=True)

    twse_val = twse.get("valuation") if isinstance(twse.get("valuation"), dict) else {}
    exchange_multiples = None
    if str(twse_val.get("Code", "")).strip() == code:
        exchange_multiples = {
            "date_roc": str(twse_val.get("Date", "")).strip() or None,
            "pe_ratio": _clean_number(twse_val.get("PEratio")),
            "pb_ratio": _clean_number(twse_val.get("PBratio")),
            "dividend_yield_pct": _clean_number(twse_val.get("DividendYield")),
            "source": "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL",
        }

    latest_bs_date = max(balance_by_date) if balance_by_date else None
    latest_bs = balance_by_date.get(latest_bs_date) if latest_bs_date else None
    latest_cum_date = max(cumulative_interims) if cumulative_interims else None
    latest_cum = cumulative_interims.get(latest_cum_date) if latest_cum_date else None
    if latest_cum and latest_cum_date:
        prior_yr_date = f"{int(latest_cum_date[:4]) - 1}{latest_cum_date[4:]}"
        prior_cum = cumulative_interims.get(prior_yr_date)
        if prior_cum and prior_cum.get("revenue") and latest_cum.get("revenue"):
            latest_cum["revenue_yoy_pct"] = round(
                100.0 * (latest_cum["revenue"] - prior_cum["revenue"]) / prior_cum["revenue"], 2
            )
        if prior_cum and prior_cum.get("net_income") and latest_cum.get("net_income"):
            latest_cum["net_income_yoy_pct"] = round(
                100.0 * (latest_cum["net_income"] - prior_cum["net_income"]) / prior_cum["net_income"], 2
            )

    return {
        "source": source_url,
        "asof": asof.isoformat(),
        "currency": "TWD",
        "period_type": "tw_ifrs_reconciled",
        "reconciled_twse_openapi": twse_reconciled,
        "reconciled_period_end": twse_period_end,
        **annual_records,
        "quarterly_statements": [standalone_quarters[d] for d in sorted(standalone_quarters, reverse=True)[:8]],
        "latest_cumulative_interim": latest_cum,
        "ttm": ttm,
        "balance_sheet_history": [balance_by_date[d] for d in sorted(balance_by_date, reverse=True)[:8]],
        "latest_balance_sheet": latest_bs,
        "dividend_schedule": dividend_schedule[:8],
        "ex_dividend_history": ex_dividend_events[:8],
        "exchange_multiples": exchange_multiples,
        "warnings": warnings,
    }

