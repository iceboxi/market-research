"""Fetch the historical research dataset kept under knowledge/data (one-off, not scheduled).

Usage:
    python3 -I fetch_history.py <out_dir> [--end YYYY-MM-DD] [--only market,stocks,limits,macro]

Sources are free and need no key: FinMind v4 API (anonymous), TWSE rwd JSON and FRED
fredgraph CSV. US indices come from a separate yfinance step (see README). Stdlib only.
Values are what each source serves on the fetch day: FinMind statements and FRED series are
the current revised versions, not the first-published ones.
"""
import argparse
import csv
import io
import json
import os
import ssl
import statistics
import sys
import time
import urllib.parse
import urllib.request
from datetime import date

FINMIND = "https://api.finmindtrade.com/api/v4/data"
TWSE = "https://www.twse.com.tw/rwd/zh"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="
UA = {"User-Agent": "Mozilla/5.0 (market-research history fetch)"}
PAUSE = {"finmind": 1.2, "twse": 3.5, "fred": 1.0}

# Python 3.13 turns on VERIFY_X509_STRICT, which rejects the TWSE certificate chain
# ("Missing Subject Key Identifier"). Certificate and hostname checks stay on.
CTX = ssl.create_default_context()
CTX.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)

STOCKS = ["2330", "2317", "2454", "2356", "3017", "2408", "2344", "8299"]
QUARTERLY_TYPES = {
    "TaiwanStockFinancialStatements": ["Revenue", "GrossProfit", "OperatingIncome", "IncomeAfterTaxes",
                                       "EquityAttributableToOwnersOfParent", "EPS"],
    "TaiwanStockBalanceSheet": ["TotalAssets", "Liabilities", "EquityAttributableToOwnersOfParent",
                                "Inventories", "CashAndCashEquivalents"],
    "TaiwanStockCashFlowsStatement": ["CashFlowsFromOperatingActivities"],
}
# Daily or weekly FRED series are averaged by month; monthly and quarterly ones are kept as is.
FRED_SERIES = ["ICSA", "UNRATE", "PAYEMS", "RSAFS", "PCEC96", "DGORDER", "NEWORDER", "UMCSENT",
               "CPIAUCSL", "PCEPILFE", "INDPRO", "DFF", "DGS10", "DGS2", "T10Y2Y", "MORTGAGE30US",
               "BAMLH0A0HYM2", "BAA10Y", "DCOILWTICO", "DTWEXBGS", "PNFI", "GPDIC1", "PCECC96"]
EVENT_DROP_PCT = -3.0
MI_INDEX_FIRST = date(2004, 2, 11)
TWTB4U_FIRST = date(2014, 1, 6)
LIMIT_10PCT_FROM = date(2015, 6, 1)
LOCK_QTY_FIRST = date(2006, 1, 1)
TRI_FIRST = "2005-01-03"  # first session of the year FinMind dividend records begin


def get(url, host, tries=4):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=180, context=CTX) as r:
                body = r.read()
            time.sleep(PAUSE[host])
            return body
        except Exception as ex:  # network or throttling; back off and retry
            wait = 20 * (attempt + 1) if host != "twse" else 60 * (attempt + 1)
            print(f"  retry {attempt + 1} {url[:110]}: {ex}; sleep {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"failed: {url}")


def finmind(dataset, data_id=None, start="1990-01-01", end=None):
    q = {"dataset": dataset, "start_date": start}
    if data_id:
        q["data_id"] = data_id
    if end:
        q["end_date"] = end
    j = json.loads(get(FINMIND + "?" + urllib.parse.urlencode(q), "finmind"))
    if j.get("msg") != "success":
        raise RuntimeError(f"FinMind {dataset} {data_id}: {j.get('msg')}")
    return j["data"]


def twse(path, **params):
    params["response"] = "json"
    j = json.loads(get(f"{TWSE}/{path}?" + urllib.parse.urlencode(params), "twse"))
    if j.get("stat") not in ("OK", None):
        return None
    return j


def write(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    print(f"  wrote {path} ({len(rows)} rows)")


def num(s):
    s = (s or "").replace(",", "").strip()
    if s in ("", "--", "---", "X"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fmt(x, nd=4):
    if x is None:
        return ""
    if isinstance(x, float):
        return f"{x:.{nd}f}".rstrip("0").rstrip(".")
    return x


def roc(s):  # '113/07/19' -> '2024-07-19'
    y, m, d = s.strip().split("/")
    return f"{int(y) + 1911:04d}-{int(m):02d}-{int(d):02d}"


# ---------------------------------------------------------------- market

def market(out, end):
    print("market")
    px = finmind("TaiwanStockPrice", "TAIEX", "1999-01-01", end)
    tri = {r["date"]: r["price"] for r in finmind("TaiwanStockTotalReturnIndex", "TAIEX", "2003-01-01", end)}
    write(f"{out}/market/taiex_daily.csv",
          ["date", "open", "high", "low", "close", "trading_money", "return_index"],
          [[r["date"], r["open"], r["max"], r["min"], r["close"], r["Trading_money"], fmt(tri.get(r["date"]))]
           for r in px if r["close"] > 0])

    by_day = {}
    for r in finmind("TaiwanStockTotalMarginPurchaseShortSale", None, "2001-01-01", end):
        by_day.setdefault(r["date"], {})[r["name"]] = r
    rows = []
    for d in sorted(by_day):
        x = by_day[d]
        g = lambda n, k: x[n][k] if n in x else ""
        rows.append([d, g("MarginPurchase", "TodayBalance"), g("MarginPurchaseMoney", "TodayBalance"),
                     g("ShortSale", "TodayBalance"), g("MarginPurchase", "buy"), g("MarginPurchase", "sell"),
                     g("MarginPurchase", "Return")])
    write(f"{out}/market/margin_daily.csv",
          ["date", "margin_balance_lots", "margin_balance_money", "short_balance_lots",
           "margin_buy_lots", "margin_sell_lots", "margin_cash_return_lots"], rows)

    names = ["Foreign_Investor", "Foreign_Dealer_Self", "Investment_Trust", "Dealer", "Dealer_self",
             "Dealer_Hedging", "total"]
    by_day = {}
    for r in finmind("TaiwanStockTotalInstitutionalInvestors", None, "2004-01-01", end):
        by_day.setdefault(r["date"], {})[r["name"]] = r["buy"] - r["sell"]
    write(f"{out}/market/institutional_daily.csv", ["date"] + [f"{n}_net" for n in names],
          [[d] + [by_day[d].get(n, "") for n in names] for d in sorted(by_day)])

    etf = {}
    for sym in ["0050", "00631L"]:
        for r in finmind("TaiwanStockPrice", sym, "2003-01-01", end):
            if r["close"] > 0:
                etf.setdefault(r["date"], {})[sym] = r["close"]
    write(f"{out}/market/etf_daily.csv", ["date", "close_0050", "close_00631L"],
          [[d, etf[d].get("0050", ""), etf[d].get("00631L", "")] for d in sorted(etf)])


# ---------------------------------------------------------------- stocks

def total_return_index(px, divs, reductions):
    cash, stock = {}, {}
    for r in divs:
        if r.get("CashExDividendTradingDate"):
            d = r["CashExDividendTradingDate"]
            cash[d] = cash.get(d, 0) + (r["CashEarningsDistribution"] or 0) + (r["CashStatutorySurplus"] or 0)
        s = (r["StockEarningsDistribution"] or 0) + (r["StockStatutorySurplus"] or 0)
        if s > 0 and r.get("StockExDividendTradingDate"):
            d = r["StockExDividendTradingDate"]
            stock[d] = stock.get(d, 0) + s
    red = {r["date"]: r["PostReductionReferencePrice"] / r["ClosingPriceonTheLastTradingDay"]
           for r in reductions if r["ClosingPriceonTheLastTradingDay"]}
    actions = sorted(set(cash) | set(stock) | set(red))
    # A close-to-close move beyond the daily price limit (+1 point of slack) needs a corporate
    # action. FinMind's dividend records start in 2005, and some reductions are missing (2408 on
    # 2009-08-26), so the index starts in 2005 and restarts after any such move with no record.
    start = TRI_FIRST
    for a, b in zip(px, px[1:]):
        limit = 10.0 if b["date"] >= LIMIT_10PCT_FROM.isoformat() else 7.0
        if b["date"] not in actions and abs(b["close"] / a["close"] - 1) * 100 > limit + 1.0:
            start = max(start, b["date"])
    out, idx, prev = {}, 1.0, None
    for r in px:
        d, c = r["date"], r["close"]
        if d < start:
            continue
        if prev is not None:
            factor = (1 + stock.get(d, 0) / 10) / red.get(d, 1.0)
            idx *= (c * factor + cash.get(d, 0.0)) / prev
        out[d] = idx
        prev = c
    return out, [[d, fmt(cash.get(d)), fmt(stock.get(d)), fmt(red.get(d), 6)] for d in actions]


def stocks(out, end):
    print("stocks")
    for sid in STOCKS:
        print(" ", sid)
        px = [r for r in finmind("TaiwanStockPrice", sid, "1999-01-01", end) if r["close"] > 0]
        per = {r["date"]: r for r in finmind("TaiwanStockPER", sid, "2005-01-01", end)}
        divs = finmind("TaiwanStockDividend", sid, "1999-01-01", end)
        reds = finmind("TaiwanStockCapitalReductionReferencePrice", sid, "1999-01-01", end)
        tri, actions = total_return_index(px, divs, reds)
        rows = []
        for r in px:
            p = per.get(r["date"], {})
            rows.append([r["date"], r["open"], r["max"], r["min"], r["close"], r["Trading_Volume"],
                         r["Trading_money"], fmt(p.get("PER")), fmt(p.get("PBR")), fmt(p.get("dividend_yield")),
                         fmt(tri.get(r["date"]), 6)])
        write(f"{out}/stocks/{sid}_daily.csv",
              ["date", "open", "high", "low", "close", "volume_shares", "trading_money", "per", "pbr",
               "dividend_yield", "total_return_index"], rows)
        write(f"{out}/stocks/{sid}_actions.csv",
              ["date", "cash_dividend", "stock_dividend_per_10_shares", "capital_reduction_ratio"], actions)

        q = {}
        cols = []
        for ds, types in QUARTERLY_TYPES.items():
            prefix = {"TaiwanStockFinancialStatements": "is_", "TaiwanStockBalanceSheet": "bs_",
                      "TaiwanStockCashFlowsStatement": "cf_ytd_"}[ds]
            seen = set()
            for r in finmind(ds, sid, "1990-01-01", end):
                if r["type"] in types:
                    q.setdefault(r["date"], {})[prefix + r["type"]] = r["value"]
                    seen.add(r["type"])
            missing = set(types) - seen
            if missing:
                print(f"    {ds}: no {sorted(missing)}")
            cols += [prefix + t for t in types]
        write(f"{out}/stocks/{sid}_quarterly.csv", ["quarter_end"] + cols,
              [[d] + [fmt(q[d].get(c)) for c in cols] for d in sorted(q)])

        rev = finmind("TaiwanStockMonthRevenue", sid, "2001-01-01", end)
        write(f"{out}/stocks/{sid}_month_revenue.csv", ["year", "month", "revenue"],
              sorted([r["revenue_year"], r["revenue_month"], r["revenue"]] for r in rev))


# ---------------------------------------------------------------- limit-down structure

def read_taiex(out):
    with open(f"{out}/market/taiex_daily.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    days = [date.fromisoformat(r["date"]) for r in rows]
    close = [float(r["close"]) for r in rows]
    pct = [None] + [(close[i] / close[i - 1] - 1) * 100 for i in range(1, len(close))]
    return days, pct


def parse_quotes(j):
    """Common stocks (four-digit code not starting with 0) from the MI_INDEX closing-quote table."""
    table = next((t for t in j.get("tables", []) if "每日收盤行情" in (t.get("title") or "")), None)
    if table is None:
        return None, None
    f = {n: i for i, n in enumerate(table["fields"])}
    stocks = {}
    for row in table["data"]:
        code = row[f["證券代號"]].strip()
        if len(code) != 4 or not code.isdigit() or code[0] == "0":
            continue
        close, chg = num(row[f["收盤價"]]), num(row[f["漲跌價差"]])
        if close is None or chg is None:
            continue
        sign = row[f["漲跌(+/-)"]]
        signed = -chg if "-" in sign else (chg if "+" in sign else 0.0)
        prev = close - signed
        if prev <= 0:
            continue
        stocks[code] = {
            "name": row[f["證券名稱"]].strip(), "close": close, "pct": signed / prev * 100,
            "low_pct": ((num(row[f["最低價"]]) or close) / prev - 1) * 100,
            "high_pct": ((num(row[f["最高價"]]) or close) / prev - 1) * 100,
            "bid": num(row[f["最後揭示買價"]]), "ask": num(row[f["最後揭示賣價"]]),
            "ask_qty": num(row[f["最後揭示賣量"]]),
        }
    official = next((t for t in j.get("tables", []) if t.get("title") == "漲跌證券數合計"), None)
    counts = {}
    if official:
        for typ, _, stock in official["data"]:
            if "(" in stock:
                n, k = stock.rstrip(")").split("(")
                counts[typ] = (int(n.replace(",", "")), int(k.replace(",", "")))
    return stocks, counts


def limits(out, end):
    print("limits")
    days, pct = read_taiex(out)
    end_d = date.fromisoformat(end)
    events = [i for i, d in enumerate(days) if MI_INDEX_FIRST <= d <= end_d and pct[i] is not None
              and pct[i] <= EVENT_DROP_PCT]
    print(f"  {len(events)} event days with TAIEX <= {EVENT_DROP_PCT}%")
    wanted = {}
    for i in events:
        wanted[i] = "event"
        if i + 1 < len(days) and days[i + 1] <= end_d:
            wanted.setdefault(i + 1, "next")
    quotes, agg = {}, []
    for i in sorted(wanted):
        d = days[i]
        j = twse("afterTrading/MI_INDEX", date=d.strftime("%Y%m%d"), type="ALLBUT0999")
        stocks_, counts = parse_quotes(j) if j else (None, None)
        if not stocks_:
            print(f"  {d}: no quotes")
            continue
        quotes[d] = stocks_
        limit = 10.0 if d >= LIMIT_10PCT_FROM else 7.0
        thr = limit - 0.5
        down = [s for s in stocks_.values() if s["pct"] <= -thr]
        locked = [s for s in down if not s["bid"] and s["ask"] == s["close"]]
        # MI_INDEX leaves the last ask volume blank before 2006: lots unknown, not zero.
        lots = [s["ask_qty"] for s in locked]
        if d < LOCK_QTY_FIRST or any(x is None for x in lots):
            lots = None
        up = [s for s in stocks_.values() if s["pct"] >= thr]
        touch = [s for s in stocks_.values() if s["low_pct"] <= -thr]
        off_down = counts.get("下跌(跌停)", (None, None))[1] if counts else None
        off_up = counts.get("上漲(漲停)", (None, None))[1] if counts else None
        agg.append([d.isoformat(), wanted[i], fmt(pct[i], 2), limit, len(stocks_), len(down), len(locked),
                    "" if lots is None else int(sum(lots)),
                    fmt(statistics.median(lots), 1) if lots else "", len(touch), len(up),
                    fmt(off_down), fmt(off_up)])
        print(f"  {d} {wanted[i]} taiex {pct[i]:.2f}% down {len(down)} locked {len(locked)}")
    write(f"{out}/market/limit_down_days.csv",
          ["date", "role", "taiex_pct", "limit_pct", "common_stocks", "close_down_over_threshold", "locked_no_bid",
           "locked_lots_sum", "locked_lots_median", "low_down_over_threshold", "close_up_over_threshold",
           "official_stock_limit_down", "official_stock_limit_up"], agg)

    rows = []
    for i in events:
        d = days[i]
        if d not in quotes:
            continue
        nd = days[i + 1] if i + 1 < len(days) else None
        thr = (10.0 if d >= LIMIT_10PCT_FROM else 7.0) - 0.5
        for code, s in sorted(quotes[d].items()):
            if s["pct"] <= -thr and not s["bid"] and s["ask"] == s["close"]:
                nxt = quotes.get(nd, {}).get(code)
                rows.append([d.isoformat(), code, s["name"], fmt(s["pct"], 2), fmt(s["ask_qty"]),
                             nd.isoformat() if nd else "", fmt(nxt["pct"], 2) if nxt else ""])
    write(f"{out}/market/limit_down_locked_stocks.csv",
          ["date", "code", "name", "pct", "locked_lots", "next_date", "next_pct"], rows)

    dt_rows = []
    role = {}
    for i in (i for i in events if days[i] >= TWTB4U_FIRST):
        role[i] = "event"
    for i in list(role):
        role.setdefault(i - 1, "prior")
        if i + 1 < len(days) and days[i + 1] <= end_d:
            role.setdefault(i + 1, "next")
    for i in sorted(role):
        d = days[i]
        j = twse("dayTrading/TWTB4U", date=d.strftime("%Y%m%d"), selectType="All")
        t = next((t for t in (j or {}).get("tables", []) if "統計資訊" in (t.get("title") or "")), None)
        if not t or not t.get("data"):
            print(f"  TWTB4U {d}: none")
            continue
        v = t["data"][0]
        dt_rows.append([d.isoformat(), role[i], fmt(pct[i], 2)] + [fmt(num(x)) for x in v[:6]])
    write(f"{out}/market/day_trading_days.csv",
          ["date", "role", "taiex_pct", "dt_shares", "dt_shares_pct", "dt_buy_money", "dt_buy_money_pct",
           "dt_sell_money", "dt_sell_money_pct"], dt_rows)

    rows = []
    for y in range(2004, end_d.year + 1):
        s, e = date(y, 1, 1), min(date(y, 12, 31), end_d)
        j = twse("announcement/punish", startDate=s.strftime("%Y%m%d"), endDate=e.strftime("%Y%m%d"))
        data = (j or {}).get("data") or []
        f = {n: i for i, n in enumerate((j or {}).get("fields") or [])}
        n_stock = 0
        for r in data:
            code = str(r[f["證券代號"]]).strip()
            if len(code) != 4 or not code.isdigit() or code[0] == "0":
                continue
            period = str(r[f["處置起迄時間"]]).replace("~", "～").split("～")
            rows.append([roc(r[f["公布日期"]]), code, str(r[f["證券名稱"]]).strip(), r[f["累計"]],
                         str(r[f["處置條件"]]).strip(), roc(period[0]) if len(period) == 2 else "",
                         roc(period[1]) if len(period) == 2 else "", str(r[f["處置措施"]]).strip()])
            n_stock += 1
        print(f"  punish {y}: {len(data)} rows, {n_stock} stocks")
    rows = sorted({tuple(r) for r in rows})  # a period that spans New Year shows up in both years
    write(f"{out}/market/disposition_stocks.csv",
          ["announce_date", "code", "name", "count_in_period", "condition", "start", "end", "measure"], rows)


# ---------------------------------------------------------------- macro

def macro(out, end):
    print("macro")
    series = {}
    for sid in FRED_SERIES:
        text = get(FRED + sid, "fred").decode("utf-8")
        r = csv.reader(io.StringIO(text))
        next(r)
        buckets = {}
        for d, v in r:
            if d > end or v in ("", "."):
                continue
            buckets.setdefault(d[:7], []).append(float(v))
        series[sid] = {m: sum(v) / len(v) for m, v in buckets.items()}
        print(f"  {sid}: {min(buckets)}..{max(buckets)}")
    months = sorted({m for s in series.values() for m in s if m >= "1990-01"})
    write(f"{out}/macro/fred_monthly.csv", ["month"] + FRED_SERIES,
          [[m] + [fmt(series[s].get(m)) for s in FRED_SERIES] for m in months])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--end", default=date.today().isoformat())
    ap.add_argument("--only", default="market,stocks,limits,macro")
    a = ap.parse_args()
    steps = {"market": market, "stocks": stocks, "limits": limits, "macro": macro}
    for name in a.only.split(","):
        steps[name](a.out, a.end)


if __name__ == "__main__":
    main()
