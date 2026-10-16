"""Independent TWSE listed-stock daily price/volume cross-check."""
from datetime import date

import httpx

TWSE_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"


def parse_twse_roc_date(value: str) -> date:
    y, m, d = map(int, value.split("/"))
    return date(y + 1911, m, d)


def twse_close_check(symbol: str, trade_date: date, yahoo_close: float,
                     yahoo_volume: float, get=None) -> dict:
    if not symbol.endswith(".TW"):
        return {"status": "not_applicable"}
    request = get or httpx.get
    try:
        response = request(
            TWSE_URL,
            params={"response": "json", "date": trade_date.strftime("%Y%m01"),
                    "stockNo": symbol.split(".")[0]},
            headers={"User-Agent": "market-research/0.1"},
            timeout=15,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("stat") != "OK":
            raise ValueError(f"TWSE status: {body.get('stat')}")
        header = body["fields"]
        date_col, close_col, vol_col = (header.index(k) for k in ("日期","收盤價","成交股數"))
        for row in body["data"]:
            if parse_twse_roc_date(row[date_col]) != trade_date:
                continue
            close = float(str(row[close_col]).replace(",", ""))
            vol = float(str(row[vol_col]).replace(",", ""))
            close_diff = abs(yahoo_close-close)/close*100 if close else None
            vol_diff = abs(yahoo_volume-vol)/vol*100 if vol else None
            equal = close_diff is not None and vol_diff is not None and close_diff <= 0.5 and vol_diff <= 5.0
            return {
                "status": "verified" if equal else "mismatch",
                "official_source": "TWSE_STOCK_DAY", "date": trade_date.isoformat(),
                "twse_close": close, "twse_volume_shares": int(vol),
                "close_difference_pct": round(close_diff,4) if close_diff is not None else None,
                "volume_difference_pct": round(vol_diff,4) if vol_diff is not None else None,
            }
        return {"status": "not_available", "reason": "trade date not in official response"}
    except (ValueError, KeyError, TypeError, httpx.HTTPError) as exc:
        return {"status": "unavailable", "reason": str(exc)}
