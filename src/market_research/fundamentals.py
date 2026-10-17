"""Source-traceable issuer fundamentals, separate from market OHLCV.

TWSE OpenAPI = latest company profile / monthly revenue snapshot only.
SEC = annual 10-K tagged US-GAAP facts, never infer annual from a quarter.
Never fill unavailable values by guessing; monetary units stay explicit.
"""
from datetime import date
import os
import re

import httpx

TW_PROFILE = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TW_REVENUE = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

def json_get(url, user_agent=None, client=None):
    headers = {"User-Agent": user_agent or "MarketResearch/0.1 public-research"}
    if client is not None:
        response = client.get(url, headers=headers, timeout=25, follow_redirects=True)
    else:
        with httpx.Client(follow_redirects=True, timeout=25) as requester:
            response = requester.get(url, headers=headers)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, (list, dict)):
        raise ValueError(f"Unexpected object shape from {url}")
    return payload


def number(value):
    """Safe number from TWSE string with thousands separators; None not zero."""
    if value is None or isinstance(value, bool):
        return None
    cleaned = str(value).replace(",", "").strip()
    if cleaned in ("", "-", "--", "N/A", "不適用"):
        return None
    try:
        value = float(cleaned)
    except (ValueError, OverflowError):
        return None
    import math
    return value if math.isfinite(value) else None


def pick(row, *labels):
    for name in labels:
        if name in row and str(row[name]).strip():
            return row[name]
    return None


def twse_fundamentals(symbol, get=json_get):
    """TWSE-listed equities only; no assumption that all are generic industry."""
    if not re.fullmatch(r"[0-9]{4,6}\.TW", symbol):
        raise ValueError("Use a valid TWSE listed symbol, e.g. 2330.TW")
    ticker = symbol.removesuffix(".TW")
    profile = get(TW_PROFILE)
    if not isinstance(profile, list):
        raise ValueError("TWSE profile endpoint must return a list")
    rows = [r for r in profile if isinstance(r, dict) and
            str(pick(r, "公司代號", "公司代碼") or "").strip() == ticker]
    if len(rows) != 1:
        raise ValueError(f"{symbol}: not uniquely found in TWSE listed-company profile")
    row = rows[0]
    output = {
        "symbol": symbol, "market": "tw",
        "company_name": pick(row, "公司名稱", "公司簡稱"),
        "industry_code": pick(row, "產業別", "產業別代碼"),
        "listing_date": pick(row, "上市日期"),
        "profile": {
            "source": TW_PROFILE,
            "reported_at": pick(row, "出表日期"),
        },
        "facts": [],
        "warnings": [],
    }
    # Monthly revenue is NOT GAAP/IFRS recognized annual revenue.
    # It may be absent for financial institutions or special issuers.
    try:
        revenue = get(TW_REVENUE)
        if not isinstance(revenue, list):
            raise ValueError("TWSE monthly revenue endpoint must return a list")
        matches = [r for r in revenue if isinstance(r, dict) and
                   str(pick(r, "公司代號", "公司代碼") or "").strip() == ticker]
        if len(matches) == 1:
            r = matches[0]
            value = number(pick(r, "當月營收", "營業收入-當月營收", "營業收入當月營收"))
            if value is not None:
                output["facts"].append({
                    "metric": "monthly_reported_revenue", "value": value,
                    "unit": "TWD_thousands",  # TWSE t187ap05_L published revenue unit
                    "period": pick(r, "資料年月", "資料年月份", "資料年月日"),
                    "reported_at": pick(r, "出表日期"),
                    "source": TW_REVENUE,
                    "comparability": "monthly_raw_not_annual_earnings",
                })
            else:
                output["warnings"].append("TWSE monthly revenue is unavailable for this issuer")
        else:
            output["warnings"].append("TWSE monthly revenue not uniquely identified")
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        output["warnings"].append("TWSE monthly revenue unavailable: "+type(exc).__name__)
    output["warnings"].append(
        "TWSE profile + monthly revenue do not constitute audited financial statements"
    )
    return output


def annual_filing_fact(facts, tags, unit, asof):
    """Most recent annual full-year 10-K fact FILED by asof; no fiscal Q4 assumption."""
    usgaap = facts.get("facts", {}).get("us-gaap", {})
    choices = []
    for tag in tags:
        concept = usgaap.get(tag, {})
        units = concept.get("units", {}).get(unit, [])
        for r in units:
            if r.get("form") not in ("10-K", "10-K/A"):
                continue
            if not (r.get("start") and r.get("end") and r.get("filed")):
                continue
            try:
                start = date.fromisoformat(r["start"])
                end = date.fromisoformat(r["end"])
                filed = date.fromisoformat(r["filed"])
                duration = (end - start).days
            except (TypeError, ValueError):
                continue
            if not 330 <= duration <= 380 or filed > asof or end > asof:
                continue
            value = number(r.get("val"))
            if value is None:
                continue
            choices.append((end, filed, tag, value, r.get("accn")))
    if not choices:
        return None
    end, filed, tag, value, accn = max(choices, key=lambda x:(x[0], x[1]))
    return {"value":value,"unit":unit,"period_end":end.isoformat(),
            "filed":filed.isoformat(),"taxonomy_tag":tag,
            "accession":accn,"form":"10-K"}


def sec_fundamentals(symbol, asof, get=json_get, user_agent=None):
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", symbol):
        raise ValueError("Unsupported US ticker format")
    ua = user_agent or os.getenv("SEC_USER_AGENT")
    if not ua or "@" not in ua:
        raise ValueError("SEC_USER_AGENT with genuine contact email is required for SEC fair access")
    def fetch(url):
        return get(url, user_agent=ua)
    tickers = fetch(SEC_TICKERS)
    if not isinstance(tickers, dict):
        raise ValueError("SEC company list is not a mapping")
    match = [x for x in tickers.values() if isinstance(x,dict) and
             x.get("ticker","").upper() == symbol]
    if len(match) != 1:
        raise ValueError(f"{symbol}: not uniquely found in SEC mapping")
    identity = match[0]
    cik = int(identity["cik_str"])
    url = SEC_FACTS.format(cik=cik)
    raw = fetch(url)
    if not isinstance(raw, dict) or raw.get("cik") != cik:
        raise ValueError("SEC company facts CIK mismatch")
    output = {"symbol":symbol,"market":"us","company_name":raw.get("entityName") or identity["title"],
              "cik":f"{cik:010d}","profile":{"source":SEC_TICKERS},"facts":[],"warnings":[]}
    tags = {
        "annual_revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax",
                           "Revenues","SalesRevenueNet"],
        "annual_net_income": ["NetIncomeLoss"],
    }
    for metric, candidates in tags.items():
        value = annual_filing_fact(raw,candidates,"USD",asof)
        if value is None:
            output["warnings"].append(f"SEC comparable {metric} 10-K concept unavailable")
            continue
        output["facts"].append({"metric":metric,**value,"source":url})
    output["warnings"].append(
        "SEC financial concepts vary by issuer and filing; no unverified EPS, TTM or valuation inferred"
    )
    return output
