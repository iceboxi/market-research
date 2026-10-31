"""TPEx-listed (.TWO) daily bars from FinMind TaiwanStockPrice (#144); TWD, shares.

The dataset carries no reference price, so `reference_price` is NaN on every day and
price watch treats each day like a TWSE 'X' (不比價) day: unadjusted, with a day's
move beyond the split ratio making the measures that cover it not_evaluated. FinMind's
`spread` is not used as a base: for 8299 on 2026-06-30, close minus spread sat above
the previous close, which no ex-dividend reference does. Missing days are never filled.
"""
from dataclasses import dataclass
from datetime import date, datetime
import re
from zoneinfo import ZoneInfo

import pandas as pd

from .fundamentals import FINMIND_URL, json_get
from .twse import COLUMNS, LOOKBACK_MONTHS

PRICE_DATASET = "TaiwanStockPrice"


def finmind_price_url(ticker, start):
    """FinMind daily OHLCV from `start` (YYYY-MM-DD)."""
    return f"{FINMIND_URL}?dataset={PRICE_DATASET}&data_id={ticker}&start_date={start}"


def parse_finmind_price(payload, symbol):
    """Raw OHLCV frame; zero-volume (suspended) days are excluded, not priced."""
    if not (isinstance(payload, dict) and payload.get("status") == 200 and
            isinstance(payload.get("data"), list)):
        raise ValueError(f"FinMind {PRICE_DATASET} {symbol}: invalid response shape")
    code = symbol.split(".")[0]
    records = []
    for row in payload["data"]:
        if str(row.get("stock_id", "")).strip() != code:
            raise ValueError(f"FinMind {PRICE_DATASET}: foreign stock_id {row.get('stock_id')}")
        if row.get("Trading_Volume") == 0:
            continue
        records.append({"date": date.fromisoformat(str(row["date"])[:10]),
                        "open": float(row["open"]), "high": float(row["max"]),
                        "low": float(row["min"]), "close": float(row["close"]),
                        "volume": int(row["Trading_Volume"])})
    if not records:
        raise ValueError(f"FinMind {PRICE_DATASET} {symbol}: no daily candles")
    frame = pd.DataFrame(records)
    if frame["date"].duplicated().any():
        raise ValueError(f"FinMind {PRICE_DATASET} {symbol}: duplicate trading dates")
    frame = frame.sort_values("date").set_index("date")
    frame["adj_close"] = float("nan")
    frame["execution_open"] = frame["open"]
    frame["reference_price"] = float("nan")
    return frame[COLUMNS]


@dataclass
class FinMindTpexDailyProvider:
    """Unadjusted OHLC and shares traded for TPEx-listed .TWO stocks."""
    get: object = None
    today: object = None
    source: str = "finmind_taiwan_stock_price_raw_ohlcv"

    def load(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        if not re.fullmatch(r"[0-9]{4,6}[A-Z]?\.TWO", symbol):
            raise ValueError(f"FinMind TPEx provider supports .TWO tickers, got {symbol}")
        if period not in LOOKBACK_MONTHS:
            raise ValueError(f"Unsupported period: {period}")
        current = self.today or datetime.now(ZoneInfo("Asia/Taipei")).date()
        first = current.year * 12 + current.month - LOOKBACK_MONTHS[period]
        start = date(first // 12, first % 12 + 1, 1)
        url = finmind_price_url(symbol.split(".")[0], start.isoformat())
        return parse_finmind_price((self.get or json_get)(url), symbol)
