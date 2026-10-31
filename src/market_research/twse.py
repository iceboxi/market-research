"""TWSE official monthly daily bars; prices TWD, volume in shares.

The STOCK_DAY endpoint reports one listed symbol per calendar month.
This adapter never forward-fills missing official trading records.

`reference_price` is TWSE's own base for the day's change (close minus the
published change). It equals the previous close except on corporate-action
days, e.g. a split; it is NaN on 'X' (不比價) days such as ex-dividend days.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
import time
from contextlib import nullcontext
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import httpx
import pandas as pd

from .market_calendar import expected_complete_session

TWSE_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
TWSE_MARKET_URL = "https://www.twse.com.tw/exchangeReport/FMTQIK"
TWSE_INDEX_URL = "https://www.twse.com.tw/indicesReport/MI_5MINS_HIST"
# Config code of the TWSE capitalization-weighted index (發行量加權股價指數).
TAIEX = "TAIEX"
REQUIRED = ("日期", "成交股數", "開盤價", "最高價", "最低價", "收盤價")
INDEX_REQUIRED = ("日期", "開盤指數", "最高指數", "最低指數", "收盤指數")
MARKET_REQUIRED = ("日期", "成交股數", "發行量加權股價指數", "漲跌點數")
COLUMNS = ["open", "high", "low", "close", "volume", "adj_close", "execution_open",
           "reference_price"]
# Exact 1-year lookback includes a warm-up month for 14/20-day signals.
LOOKBACK_MONTHS = {"3mo": 4, "6mo": 7, "1y": 13, "2y": 25}
# STOCK_DAY already had the same-day session by 15:15 Taipei (close + 1h45m);
# a session absent from the market-wide record is trusted as closed only
# well after that, so a slow publication is never mistaken for a closure.
CLOSURE_CONFIRMATION_LAG = timedelta(hours=6)
CLOSURE_LOOKBACK_SESSIONS = 5


def parse_twse_roc_date(value: str) -> date:
    y, m, d = map(int, value.split("/"))
    return date(y + 1911, m, d)


def _number(s: str) -> float:
    return float(str(s).replace(",", "").strip())


def _change(s: str) -> float:
    """Published change; NaN when TWSE marks the day 'X' (不比價) or omits it."""
    text = str(s).replace(",", "").strip()
    try:
        return float("nan") if text.startswith("X") else float(text)
    except ValueError:
        # Prices stay usable; consumers treat an unknown base like 'X'.
        return float("nan")


def parse_stock_day(payload: dict, symbol: str) -> pd.DataFrame:
    """Parse one STOCK_DAY response. Non-trading/zero-volume rows are excluded."""
    if payload.get("stat") != "OK":
        raise ValueError(f"TWSE {symbol}: {payload.get('stat', 'unknown status')}")
    headers = payload["fields"]
    columns = [headers.index(name) for name in REQUIRED]
    change = headers.index("漲跌價差") if "漲跌價差" in headers else None
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
        reference = c - _change(values[change]) if change is not None else float("nan")
        records.append({"date": day, "open": o, "high": h, "low": l,
                        "close": c, "volume": int(vol), "reference_price": round(reference, 4)})
    return pd.DataFrame(records, columns=["date", "open", "high", "low", "close", "volume",
                                          "reference_price"])


def _rows(payload: dict, required: tuple, label: str) -> list:
    if payload.get("stat") != "OK":
        raise ValueError(f"TWSE {label}: {payload.get('stat', 'unknown status')}")
    headers = payload["fields"]
    columns = [headers.index(name) for name in required]
    return [[values[i] for i in columns] for values in payload.get("data", [])]


def parse_index_history(payload: dict) -> pd.DataFrame:
    """Parse one MI_5MINS_HIST month of TAIEX daily OHLC; an empty month is empty."""
    records = []
    for values in _rows(payload, INDEX_REQUIRED, "MI_5MINS_HIST"):
        day = parse_twse_roc_date(values[0])
        try:
            o, h, l, c = (_number(v) for v in values[1:])
        except (ValueError, TypeError):
            # An index has no suspension rows; a blank value is malformed data.
            raise ValueError(f"TWSE MI_5MINS_HIST: missing index values on {day}")
        records.append({"date": day, "open": o, "high": h, "low": l, "close": c})
    return pd.DataFrame(records, columns=["date", "open", "high", "low", "close"])


def parse_market_turnover(payload: dict) -> pd.DataFrame:
    """Parse one FMTQIK month: market-wide shares traded, index close and change."""
    records = []
    for values in _rows(payload, MARKET_REQUIRED, "FMTQIK"):
        day = parse_twse_roc_date(values[0])
        try:
            volume, close, change = (_number(v) for v in values[1:])
        except (ValueError, TypeError):
            raise ValueError(f"TWSE FMTQIK: missing market values on {day}")
        records.append({"date": day, "volume": int(volume), "close": close,
                        "reference_price": round(close - change, 4)})
    return pd.DataFrame(records, columns=["date", "volume", "close", "reference_price"])


def merge_index_month(index: pd.DataFrame, market: pd.DataFrame) -> pd.DataFrame:
    """One month of TAIEX OHLC with FMTQIK volume and change; both must agree."""
    if set(index["date"]) != set(market["date"]):
        raise ValueError("TWSE TAIEX: MI_5MINS_HIST and FMTQIK trading dates differ")
    merged = index.merge(market, on="date", suffixes=("", "_market"))
    if ((merged["close"] - merged["close_market"]).abs() > 0.005).any():
        raise ValueError("TWSE TAIEX: MI_5MINS_HIST and FMTQIK closes differ")
    return merged[["date", "open", "high", "low", "close", "volume", "reference_price"]]


def _month_starts(from_date: date, to_date: date):
    start = from_date.year * 12 + from_date.month - 1
    end = to_date.year * 12 + to_date.month - 1
    for n in range(start, end + 1):
        yield date(n // 12, n % 12 + 1, 1)


def twse_traded_dates(month: date, get=None) -> set[date]:
    """Market-wide TWSE trading days of one month (FMTQIK)."""
    params = {"response": "json", "date": month.strftime("%Y%m01")}
    if get is None:
        response = httpx.get(TWSE_MARKET_URL, params=params, timeout=20, follow_redirects=True,
                             headers={"User-Agent": "market-research/0.1 (research-only)"})
    else:
        response = get(TWSE_MARKET_URL, params=params, timeout=20)
    response.raise_for_status()
    payload = response.json()
    if payload.get("stat") != "OK":
        raise ValueError(f"TWSE FMTQIK {month:%Y-%m}: {payload.get('stat', 'unknown status')}")
    column = payload["fields"].index("日期")
    return {parse_twse_roc_date(row[column]) for row in payload.get("data", [])}


def twse_unscheduled_closures(now: datetime, get=None) -> tuple[date, ...]:
    """Recent XTAI sessions that TWSE's market-wide record shows were not traded.

    exchange_calendars cannot know ad-hoc closures such as typhoon days. Any
    source problem, a session that may still be unpublished, or a window
    without a traded anchor returns () so strict freshness keeps the calendar.
    """
    calendar = xcals.get_calendar("XTAI")
    expected = pd.Timestamp(expected_complete_session("tw", now))
    sessions = list(calendar.sessions_window(expected, -CLOSURE_LOOKBACK_SESSIONS))
    try:
        traded = set()
        for month in sorted({date(s.year, s.month, 1) for s in sessions}):
            traded |= twse_traded_dates(month, get)
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return ()
    utc_now = pd.Timestamp(now).tz_convert("UTC")
    closures = []
    for session in reversed(sessions):
        if session.date() in traded:
            return tuple(sorted(closures))
        if utc_now < calendar.session_close(session) + CLOSURE_CONFIRMATION_LAG:
            return ()
        closures.append(session.date())
    return ()


def _load_monthly(provider, label: str, period: str, fetch) -> pd.DataFrame:
    """Every month of `period` from `fetch(request, month)`; any failed month fails closed."""
    if type(provider.timeout_retries) is not int or not 0 <= provider.timeout_retries <= 5:
        raise ValueError("timeout_retries must be an integer from 0 to 5")
    if period not in LOOKBACK_MONTHS:
        raise ValueError(f"Unsupported TWSE period: {period}")
    current = provider.today or datetime.now(ZoneInfo("Asia/Taipei")).date()
    last_month_id = current.year * 12 + current.month - 1
    first_id = last_month_id - (LOOKBACK_MONTHS[period] - 1)
    from_month = date(first_id // 12, first_id % 12 + 1, 1)
    frames, failures = [], []
    months = list(_month_starts(from_month, current))
    # Keep one HTTP connection for all months of a single ticker;
    # this significantly reduces TLS handshakes on GitHub runners.
    client = (httpx.Client(timeout=20, follow_redirects=True,
               headers={"User-Agent": "market-research/0.1 (research-only)",
                        "Accept": "application/json"})
              if provider.get is None else nullcontext())
    with client as session:
        request = provider.get or session.get
        for index, month in enumerate(months):
            for attempt in range(provider.timeout_retries + 1):
                try:
                    frame = fetch(request, month)
                    if not frame.empty:
                        frames.append(frame)
                    break
                except (httpx.TimeoutException, httpx.NetworkError,
                        httpx.RemoteProtocolError, httpx.HTTPStatusError) as exc:
                    # Only retry timeouts, broken or dropped connections and
                    # HTTP 429/5xx. Malformed official data must fail closed.
                    retryable = not isinstance(exc, httpx.HTTPStatusError) or (
                        exc.response.status_code == 429 or
                        500 <= exc.response.status_code <= 599
                    )
                    if not retryable or attempt == provider.timeout_retries:
                        failures.append(f"{month}: {exc}")
                        break
                    time.sleep(min(2 ** attempt, 4))
                except (ValueError, KeyError, TypeError) as exc:
                    failures.append(f"{month}: {exc}")
                    break
            if provider.request_pause_seconds > 0 and index != len(months) - 1:
                time.sleep(provider.request_pause_seconds)
    if failures:
        # Partial history silently changes RSI and volume averages.
        raise ValueError(f"TWSE {label}: failed months: {'; '.join(failures)}")
    if not frames:
        raise ValueError(f"TWSE {label}: no official historical candles")
    merged = pd.concat(frames, ignore_index=True)
    if merged["date"].duplicated().any():
        raise ValueError(f"TWSE {label}: duplicate official trading dates")
    merged = merged.sort_values("date").set_index("date")
    merged.index.name = "date"
    # 'adj_close' is intentionally NaN: these are unadjusted official prices.
    merged["adj_close"] = float("nan")
    merged["execution_open"] = merged["open"]
    return merged[COLUMNS]


def _json(request, url: str, params: dict) -> dict:
    response = request(url, params=params, timeout=20)
    response.raise_for_status()
    return response.json()


@dataclass
class TwseDailyProvider:
    """Official unadjusted OHLC and shares traded for TWSE-listed .TW stocks."""
    get: object = None
    today: object = None
    request_pause_seconds: float = 0.20
    timeout_retries: int = 2
    source: str = "twse_stock_day_official_raw_ohlcv"

    def unscheduled_closures(self, market: str, now: datetime) -> tuple[date, ...]:
        return twse_unscheduled_closures(now, get=self.get) if market == "tw" else ()

    def load(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        # Stocks are numeric; ETFs/ETNs may end in a letter, e.g. 00631L.
        if not re.fullmatch(r"[0-9]{4,6}[A-Z]?\.TW", symbol):
            raise ValueError(f"TWSE provider supports listed .TW ticker, got {symbol}")

        def fetch(request, month):
            return parse_stock_day(_json(request, TWSE_URL, {
                "response": "json", "date": month.strftime("%Y%m01"),
                "stockNo": symbol.split(".")[0]}), symbol)
        return _load_monthly(self, symbol, period, fetch)


@dataclass
class TwseIndexProvider:
    """Official TAIEX daily OHLC (MI_5MINS_HIST) with FMTQIK market-wide shares.

    FMTQIK also publishes the index close and change, so every month is
    cross-checked between the two official reports before it is used.
    """
    get: object = None
    today: object = None
    request_pause_seconds: float = 0.20
    timeout_retries: int = 2
    source: str = "twse_mi_5mins_hist_index_with_fmtqik_volume"

    def load(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        if symbol != TAIEX:
            raise ValueError(f"TWSE index provider supports {TAIEX}, got {symbol}")

        def fetch(request, month):
            params = {"response": "json", "date": month.strftime("%Y%m01")}
            index = parse_index_history(_json(request, TWSE_INDEX_URL, params))
            if self.request_pause_seconds > 0:
                time.sleep(self.request_pause_seconds)
            market = parse_market_turnover(_json(request, TWSE_MARKET_URL, params))
            return merge_index_month(index, market)
        return _load_monthly(self, symbol, period, fetch)


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
