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
TW_INCOME_CI = "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci"
TW_BALANCE_CI = "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_ci"
TW_PROFIT_L = "https://openapi.twse.com.tw/v1/opendata/t187ap17_L"
TW_DIVIDEND_L = "https://openapi.twse.com.tw/v1/opendata/t187ap45_L"
TW_VALUATION_L = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

# FinMind TaiwanStockInfo category -> TWSE t187ap03_L 產業別. Derived 2026-10-29 by
# joining every TWSE listed row with FinMind: 1070/1098 equal, 26 unresolved, 2 differ
# (其他 vs. an older specific sector), none across sector 17. Umbrella index groups
# such as 電子工業 are deliberately absent.
FINMIND_TWSE_INDUSTRY = {
    "水泥工業": "01", "食品工業": "02", "塑膠工業": "03", "紡織纖維": "04", "電機機械": "05",
    "電器電纜": "06", "玻璃陶瓷": "08", "造紙工業": "09", "鋼鐵工業": "10", "橡膠工業": "11",
    "汽車工業": "12", "建材營造": "14", "航運業": "15", "觀光餐旅": "16", "觀光事業": "16",
    "金融保險": "17", "貿易百貨": "18", "其他": "20", "化學工業": "21", "生技醫療業": "22",
    "油電燃氣業": "23", "半導體業": "24", "電腦及週邊設備業": "25", "光電業": "26",
    "通信網路業": "27", "電子零組件業": "28", "電子通路業": "29", "資訊服務業": "30",
    "其他電子業": "31", "綠能環保": "35", "數位雲端": "36", "運動休閒": "37", "居家生活": "38",
    "存託憑證": "91",
}

from .financial_history import normalize_sec_history, normalize_tw_financial_history
from .event_risk import (
    TW_SHAREHOLDER_ANNOUNCE_URL, TW_SHAREHOLDER_MEETING_URL, sec_filing_events, unknown,
)

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


def tw_report_date(value):
    """Original ROC/Gregorian export date; never a publication timestamp."""
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{7,8}", value):
        raise ValueError("Invalid TW export date")
    year = int(value[:-4]) + (1911 if len(value) == 7 else 0)
    return date(year, int(value[-4:-2]), int(value[-2:]))


def finmind_tw_identity(ticker, get):
    """Name and TWSE sector from FinMind when t187ap03_L is unavailable; no share data."""
    url = f"{FINMIND_URL}?dataset=TaiwanStockInfo&data_id={ticker}"
    body = get(url)
    if not (isinstance(body, dict) and body.get("status") == 200 and isinstance(body.get("data"), list)):
        raise ValueError("FinMind TaiwanStockInfo did not return data")
    rows = [r for r in body["data"] if isinstance(r, dict) and r.get("type") == "twse" and
            str(r.get("stock_id") or "").strip() == ticker]
    names = {str(r.get("stock_name") or "").strip() for r in rows} - {""}
    codes = {FINMIND_TWSE_INDUSTRY[r.get("industry_category")] for r in rows
             if r.get("industry_category") in FINMIND_TWSE_INDUSTRY}
    if len(codes) > 1:
        codes.discard("20")  # FinMind keeps 其他 beside a newer specific sector
    dates = {str(r.get("date") or "").replace("-", "") for r in rows}
    if len(names) != 1 or len(codes) != 1 or not all(re.fullmatch(r"[0-9]{8}", d) for d in dates):
        raise ValueError(f"{ticker}: FinMind identity or TWSE sector not unique")
    row = {"公司代號": ticker, "公司簡稱": names.pop(), "產業別": codes.pop(), "出表日期": max(dates)}
    return row, url


def twse_fundamentals(symbol, get=json_get, *, financial_get=None, asof=None):
    """TWSE-listed equities only; no assumption that all are generic industry."""
    if not re.fullmatch(r"[0-9]{4,6}\.TW", symbol):
        raise ValueError("Use a valid TWSE listed symbol, e.g. 2330.TW")
    ticker = symbol.removesuffix(".TW")
    ext_get = financial_get or (get if get is json_get else None)
    profile_source = {"source": TW_PROFILE}
    try:
        profile = get(TW_PROFILE)
        if not isinstance(profile, list):
            raise ValueError("TWSE profile endpoint must return a list")
        rows = [r for r in profile if isinstance(r, dict) and
                str(pick(r, "公司代號", "公司代碼") or "").strip() == ticker]
        if len(rows) != 1:
            raise ValueError(f"{symbol}: not uniquely found in TWSE listed-company profile")
        row = rows[0]
    except (httpx.HTTPError, ValueError, TypeError, KeyError, OSError) as primary:
        # Natural run 40706446471: TWSE served an HTML security page here.
        if ext_get is None:
            raise
        try:
            row, url = finmind_tw_identity(ticker, ext_get)
        except (httpx.HTTPError, ValueError, TypeError, KeyError, OSError) as fallback:
            raise primary from fallback
        profile_source = {"source": url, "fallback_for": TW_PROFILE,
                          "primary_error": type(primary).__name__}
    output = {
        "symbol": symbol, "market": "tw",
        "company_name": pick(row, "公司名稱", "公司簡稱"),
        "industry_code": pick(row, "產業別", "產業別代碼"),
        "listing_date": pick(row, "上市日期"),
        "paid_in_capital_twd": number(pick(row, "實收資本額", "實收資本額(元)")),
        "par_value_desc": pick(row, "普通股每股面額"),
        "profile": {
            "source": profile_source["source"],
            "reported_at": pick(row, "出表日期"),
            **{k: v for k, v in profile_source.items() if k != "source"},
        },
        "facts": [],
        "warnings": [],
    }
    if "fallback_for" in profile_source:
        output["warnings"].append(
            f"TWSE company profile unavailable: {profile_source['primary_error']}; "
            "identity from FinMind TaiwanStockInfo")
    # OGDL listed-company profile: an observed issued ordinary-share snapshot.
    # Not the EPS weighted-average (basic/diluted) denominator or historical float.
    shares_label = "已發行普通股數或TDR原股發行股數"
    raw_shares = row.get(shares_label)
    reported = pick(row, "出表日期")
    if raw_shares is None or not str(raw_shares).strip():
        output["warnings"].append("TWSE issued ordinary shares unavailable")
    elif not re.fullmatch(r"[0-9][0-9,]*", str(raw_shares).strip()):
        output["warnings"].append("TWSE issued ordinary shares invalid or ambiguous")
    else:
        shares = int(str(raw_shares).replace(",", ""))
        if shares <= 0:
            output["warnings"].append("TWSE issued ordinary shares must be positive")
        else:
            output["issued_shares"] = {
                "value": shares, "unit": "shares",
                "share_class": "issued_ordinary_shares",
                "basis": "current_profile_snapshot_not_weighted_average_or_diluted",
                "source": TW_PROFILE, "reported_at": reported,
                "published_at": None, "first_seen_at": None,
                "source_field": shares_label,
                "retention_policy": "twse_listed_profile_ogdl_v1",
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
                    "yoy_pct": number(pick(r, "營業收入-去年同月增減(%)", "去年同月增減(%)")),
                    "mom_pct": number(pick(r, "營業收入-上月比較增減(%)", "上月比較增減(%)")),
                    "cumulative_revenue_twd_thousands": number(pick(r, "累計營業收入-當月累計營收", "當月累計營收")),
                    "cumulative_yoy_pct": number(pick(r, "累計營業收入-前期比較增減(%)", "前期比較增減(%)")),
                })
            else:
                output["warnings"].append("TWSE monthly revenue is unavailable for this issuer")
        else:
            output["warnings"].append("TWSE monthly revenue not uniquely identified")
    except (httpx.HTTPError, ValueError, KeyError, OSError) as exc:
        output["warnings"].append("TWSE monthly revenue unavailable: "+type(exc).__name__)

    if ext_get is not None and str(output.get("industry_code") or "").strip().zfill(2) != "17":
        cutoff_date = asof if isinstance(asof, date) else date.today()
        twse_bundle = {"profile": row}
        for key, url, code_field in (
            ("income", TW_INCOME_CI, "公司代號"),
            ("balance", TW_BALANCE_CI, "公司代號"),
            ("profitability", TW_PROFIT_L, "公司代號"),
            ("valuation", TW_VALUATION_L, "Code"),
        ):
            try:
                rows_data = ext_get(url)
                if isinstance(rows_data, list):
                    matched = [x for x in rows_data if isinstance(x, dict) and str(x.get(code_field, "")).strip() == ticker]
                    if len(matched) == 1:
                        rep_dt = pick(matched[0], "出表日期", "Date")
                        try:
                            if rep_dt and tw_report_date(rep_dt) > cutoff_date:
                                continue
                        except ValueError:
                            pass
                        twse_bundle[key] = matched[0]
            except Exception as exc:
                output["warnings"].append(f"TWSE {key} source unavailable: {type(exc).__name__}")
        try:
            div_rows = ext_get(TW_DIVIDEND_L)
            if isinstance(div_rows, list):
                twse_bundle["dividends"] = [
                    x for x in div_rows if isinstance(x, dict) and str(x.get("公司代號", "")).strip() == ticker
                ]
        except Exception as exc:
            output["warnings"].append(f"TWSE dividends source unavailable: {type(exc).__name__}")

        event_source_errors = {}
        if "dividends" not in twse_bundle:
            event_source_errors["dividends"] = "unavailable"
        for key, url in (
            ("shareholder_announce", TW_SHAREHOLDER_ANNOUNCE_URL),
            ("shareholder_meeting", TW_SHAREHOLDER_MEETING_URL),
        ):
            try:
                agm_rows = ext_get(url)
                if isinstance(agm_rows, list):
                    twse_bundle[key] = agm_rows
                else:
                    event_source_errors[key] = "invalid_shape"
            except Exception as exc:
                event_source_errors[key] = type(exc).__name__

        finmind_bundle = {}
        for key, ds in (
            ("income", "TaiwanStockFinancialStatements"),
            ("balance", "TaiwanStockBalanceSheet"),
            ("cashflow", "TaiwanStockCashFlowsStatement"),
            ("dividend_result", "TaiwanStockDividendResult"),
        ):
            try:
                f_url = f"{FINMIND_URL}?dataset={ds}&data_id={ticker}&start_date=2023-01-01"
                resp = ext_get(f_url)
                if isinstance(resp, dict) and resp.get("status") == 200 and isinstance(resp.get("data"), list):
                    finmind_bundle[key] = resp["data"]
            except Exception as exc:
                output["warnings"].append(f"FinMind {key} unavailable: {type(exc).__name__}")

        try:
            news_start = f"{max(2023, cutoff_date.year)}-01-01"
            news_url = f"{FINMIND_URL}?dataset=TaiwanStockNews&data_id={ticker}&start_date={news_start}"
            news_resp = ext_get(news_url)
            if isinstance(news_resp, dict) and news_resp.get("status") == 200 and isinstance(news_resp.get("data"), list):
                finmind_bundle["news"] = news_resp["data"]
            else:
                event_source_errors["finmind_news"] = "invalid_shape"
        except Exception as exc:
            event_source_errors["finmind_news"] = type(exc).__name__

        output["event_calendar_raw"] = {
            "shareholder_announce": twse_bundle.get("shareholder_announce"),
            "shareholder_meeting": twse_bundle.get("shareholder_meeting"),
            "dividends": twse_bundle.get("dividends"),
            "finmind_news": finmind_bundle.get("news"),
            "source_errors": event_source_errors,
        }

        if finmind_bundle.get("income") and finmind_bundle.get("balance") and finmind_bundle.get("cashflow"):
            history = normalize_tw_financial_history(
                ticker, cutoff_date, finmind=finmind_bundle, twse=twse_bundle, source=TW_INCOME_CI,
            )
            output["financial_history"] = history
            output["warnings"].extend(history.get("warnings", []))

    if "financial_history" not in output or len(output["financial_history"].get("annual_free_cash_flow", [])) < 3:
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


def sec_fundamentals(symbol, asof, get=json_get, user_agent=None, evaluated_at=None):
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
    output["financial_history"] = normalize_sec_history(raw, asof, url)
    # SIC is a hard sector gate, not an inferred industry from ticker/name.
    try:
        submission_url = SEC_SUBMISSIONS.format(cik=cik)
        submission = fetch(submission_url)
        from datetime import datetime, timezone
        output["event_feed"] = sec_filing_events(submission, evaluated_at or datetime.combine(asof, datetime.min.time(), timezone.utc), submission_url)
        sic_raw = str(submission.get("sic") or "").strip()
        sic = int(sic_raw) if re.fullmatch(r"[0-9]{4}", sic_raw) else None
        output["industry"] = {"sic": sic, "source": submission_url}
        forms = (submission.get("filings") or {}).get("recent", {}).get("form", [])
        output["instrument_evidence"] = {
            "source": submission_url,
            "recent_form_types": sorted(set(x for x in forms if isinstance(x, str))) if isinstance(forms, list) else [],
        }
        if sic is None:
            output["warnings"].append("SEC SIC classification unavailable; valuation blocked")
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
        output["industry"] = {"sic": None, "source": SEC_SUBMISSIONS.format(cik=cik)}
        output["instrument_evidence"] = {"source": None, "recent_form_types": []}
        output["event_feed"] = unknown(SEC_SUBMISSIONS.format(cik=cik), "SEC submission metadata unavailable")
        output["warnings"].append("SEC industry classification unavailable: "+type(exc).__name__)
    output["warnings"].append(
        "Historical P/FCF scenarios are illustrative, not intrinsic value or executable trading levels"
    )
    return output
