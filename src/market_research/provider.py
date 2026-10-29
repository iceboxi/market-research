"""Source adapters. No network calls when importing this module."""
from dataclasses import dataclass
from typing import Callable, Protocol

import pandas as pd
import numpy as np


class DataProvider(Protocol):
    source: str

    def load(self, symbol: str, period: str = "1y") -> pd.DataFrame: ...


@dataclass
class YahooDailyProvider:
    """Yahoo adjusted-close ratio applied to OHLC; volume remains shares."""
    ticker_factory: Callable | None = None
    source: str = "yahoo_finance_via_yfinance"

    def load(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        if self.ticker_factory is None:
            import yfinance as yf
            factory = yf.Ticker
        else:
            factory = self.ticker_factory
        raw = factory(symbol).history(
            period=period, interval="1d", auto_adjust=False,
            actions=False, raise_errors=True, timeout=20,
        )
        if raw is None or raw.empty:
            raise ValueError(f"{symbol}: no daily candles from provider")
        required = {"Open", "High", "Low", "Close", "Volume"}
        if not required.issubset(raw.columns):
            raise ValueError(f"{symbol}: missing columns {sorted(required-set(raw.columns))}")
        frame = raw.rename(columns={
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume", "Adj Close": "adj_close",
        }).copy()
        frame.index = pd.Index(pd.to_datetime(frame.index).date, name="date")
        if "adj_close" not in frame:
            frame["adj_close"] = float("nan")
        # Yahoo usually split-adjusts historical raw OHLC already. Adjust for
        # distributions using Adj Close / Close on each day's *entire* candle.
        # Do not adjust trading volume for cash dividends.
        adj = frame["adj_close"].to_numpy(dtype=float)
        close = frame["close"].to_numpy(dtype=float)
        factors = np.divide(adj, close, out=np.full_like(adj, np.nan),
                            where=np.isfinite(close) & (close > 0))
        if not np.isfinite(factors).all() or (factors <= 0).any():
            raise ValueError(f"{symbol}: missing/invalid Yahoo adjusted close")
        # Preserve Yahoo's reported (cash-dividend UNadjusted) opening price.
        # Historical quote opens may already be split-adjusted by Yahoo, so
        # this is a price-only fill proxy, not a broker execution record.
        frame["execution_open"] = frame["open"].astype(float)
        frame[["open", "high", "low", "close"]] = (
            frame[["open", "high", "low", "close"]].mul(factors, axis=0)
        )
        return frame[["open", "high", "low", "close", "volume", "adj_close", "execution_open"]]


@dataclass
class RoutedDailyProvider:
    """Use authoritative TWSE candles for .TW and TAIEX; Yahoo Finance for US.

    Never mix two sources within a stock's RSI or volume lookback window.
    """
    taiwan: DataProvider | None = None
    united_states: DataProvider | None = None
    taiwan_index: DataProvider | None = None
    source: str = "routed_daily_twse_for_tw_yahoo_for_us"

    def __post_init__(self):
        from .twse import TwseDailyProvider, TwseIndexProvider
        if self.taiwan is None:
            self.taiwan = TwseDailyProvider()
        if self.united_states is None:
            self.united_states = YahooDailyProvider()
        if self.taiwan_index is None:
            self.taiwan_index = TwseIndexProvider()

    def provider_for(self, symbol: str) -> DataProvider:
        from .twse import TAIEX
        if symbol == TAIEX:
            return self.taiwan_index
        return self.taiwan if symbol.endswith(".TW") else self.united_states

    def unscheduled_closures(self, market: str, now) -> tuple:
        provider = self.taiwan if market == "tw" else self.united_states
        check = getattr(provider, "unscheduled_closures", None)
        return tuple(check(market, now)) if check else ()

    def load(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        return self.provider_for(symbol).load(symbol, period)
