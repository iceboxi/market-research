"""TWSE official monthly daily bars; prices TWD, volume in shares.

The STOCK_DAY endpoint reports one listed symbol per calendar month.
This adapter never forward-fills missing official trading records.
"""
from dataclasses import dataclass
from datetime import date, datetime
import time
from contextlib import nullcontext
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

TWSE_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
REQUIRED = ("日期", "成交股數", "開盤價", "最高價", "最低價", "收盤價")


def parse_twse_roc_date(value: str) -> date:
    y, m, d = map(int, value.split("/"))
    return date(y + 1911, m, d)


def _number(s: str) -> float:
    return float(str(s).replace(",", "").strip())


def parse_stock_day(payload: dict, symbol: str) -> pd.DataFrame:
    """Parse one STOCK_DAY response. Non-trading/zero-volume rows are excluded."""
    if payload.get("stat") != "OK":
        raise ValueError(f"TWSE {symbol}: {payload.get('stat', 'unknown status')}")
    headers = payload["fields"]
    columns = [headers.index(name) for name in REQUIRED]
    records = []
    for values in payload.get("data", []):
        day = parse_twse_roc_date(values[columns[0]])
        try:
            vol = _number(values[columns[1]])
            o, h, l, c = (_number(values[col]) for col in columns[2:])
        except (ValueError, TypeError):
            # A suspension / non-trading row is not a synthetic price candle.
            if str(values[columns[1]]).replace(",", "").strip() in ("0", "--", "-"):
                continue
            raise ValueError(f"TWSE {symbol}: unexpected missing prices on {day}")
        if vol == 0:
            continue
        records.append({"date": day, "open": o, "high": h, "low": l,
                        "close": c, "volume": int(vol)})
    return pd.DataFrame(records, columns=["date", "open", "high", "low", "close", "volume"])


def _month_starts(from_date: date, to_date: date):
    start = from_date.year * 12 + from_date.month - 1
    end = to_date.year * 12 + to_date.month - 1
    for n in range(start, end + 1):
        yield date(n // 12, n % 12 + 1, 1)


@dataclass
class TwseDailyProvider:
    """Official unadjusted OHLC and shares traded for TWSE-listed .TW stocks."""
    get: object = None
    today: object = None
    request_pause_seconds: float = 0.20
    source: str = "twse_stock_day_official_raw_ohlcv"

    def load(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        if not symbol.endswith(".TW") or not symbol.split(".")[0].isdigit():
            raise ValueError(f"TWSE provider supports listed .TW ticker, got {symbol}")
        # Exact 1-year lookback includes a warm-up month for 14/20-day signals.
        lookbacks = {"3mo": 4, "6mo": 7, "1y": 13, "2y": 25}
        if period not in lookbacks:
            raise ValueError(f"Unsupported TWSE period: {period}")
        current = self.today or datetime.now(ZoneInfo("Asia/Taipei")).date()
        last_month_id = current.year * 12 + current.month - 1
        first_id = last_month_id - (lookbacks[period] - 1)
        from_month = date(first_id // 12, first_id % 12 + 1, 1)
        frames, failures = [], []
        months = list(_month_starts(from_month, current))
        # Keep one HTTP connection for all months of a single ticker;
        # this significantly reduces TLS handshakes on GitHub runners.
        client = (httpx.Client(timeout=20, follow_redirects=True,
                   headers={"User-Agent": "market-research/0.1 (research-only)",
                            "Accept": "application/json"})
                  if self.get is None else nullcontext())
        with client as session:
            request = self.get or session.get
            for index, month in enumerate(months):
                try:
                    response = request(
                        TWSE_URL, params={"response": "json",
                                          "date": month.strftime("%Y%m01"),
                                          "stockNo": symbol.split(".")[0]}, timeout=20,
                    )
                    response.raise_for_status()
                    frame = parse_stock_day(response.json(), symbol)
                    if not frame.empty:
                        frames.append(frame)
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                    failures.append(f"{month}: {exc}")
                if self.request_pause_seconds > 0 and index != len(months) - 1:
                    time.sleep(self.request_pause_seconds)
        if failures:
            # Partial history silently changes RSI and volume averages.
            raise ValueError(f"TWSE {symbol}: failed months: {'; '.join(failures)}")
        if not frames:
            raise ValueError(f"TWSE {symbol}: no official historical candles")
        merged = pd.concat(frames, ignore_index=True)
        if merged["date"].duplicated().any():
            raise ValueError(f"TWSE {symbol}: duplicate official trading dates")
        merged = merged.sort_values("date").set_index("date")
        merged.index.name = "date"
        # 'adj_close' is intentionally NaN: these are unadjusted official prices.
        merged["adj_close"] = float("nan")
        merged["execution_open"] = merged["open"]
        return merged[["open", "high", "low", "close", "volume", "adj_close", "execution_open"]]


def twse_close_check(symbol: str, trade_date: date, yahoo_close: float,
                     yahoo_volume: float, get=None) -> dict:
    """Legacy diagnostic when Yahoo is used for Taiwan; not for official-primary data."""
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
        frame = parse_stock_day(body, symbol)
        matches = frame.loc[frame["date"] == trade_date]
        if matches.empty:
            return {"status": "not_available", "reason": "date not available"}
        row = matches.iloc[0]
        close_diff = abs(yahoo_close - row["close"]) / row["close"] * 100
        vol_diff = abs(yahoo_volume - row["volume"]) / row["volume"] * 100
        return {
            "status": "verified" if close_diff <= .5 and vol_diff <= 5 else "mismatch",
            "official_source": "TWSE_STOCK_DAY", "date": trade_date.isoformat(),
            "twse_close": float(row["close"]), "twse_volume_shares": int(row["volume"]),
            "close_difference_pct": round(close_diff, 4),
            "volume_difference_pct": round(vol_diff, 4),
        }
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        return {"status": "unavailable", "reason": str(exc)}
