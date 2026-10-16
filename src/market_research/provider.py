"""Source adapters. No network calls when importing this module."""
from dataclasses import dataclass
from typing import Callable, Protocol

import pandas as pd


class DataProvider(Protocol):
    source: str

    def load(self, symbol: str, period: str = "1y") -> pd.DataFrame: ...


@dataclass
class YahooDailyProvider:
    """Unofficial Yahoo/yfinance personal-use historical candles."""
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
        return frame[["open", "high", "low", "close", "volume", "adj_close"]]


@dataclass
class RoutedDailyProvider:
    """Use authoritative TWSE candles for .TW; Yahoo Finance for US.

    Never mix two sources within a stock's RSI or volume lookback window.
    """
    taiwan: DataProvider | None = None
    united_states: DataProvider | None = None
    source: str = "routed_daily_twse_for_tw_yahoo_for_us"

    def __post_init__(self):
        if self.taiwan is None:
            from .twse import TwseDailyProvider
            self.taiwan = TwseDailyProvider()
        if self.united_states is None:
            self.united_states = YahooDailyProvider()

    def provider_for(self, symbol: str) -> DataProvider:
        return self.taiwan if symbol.endswith(".TW") else self.united_states

    def load(self, symbol: str, period: str = "1y") -> pd.DataFrame:
        return self.provider_for(symbol).load(symbol, period)
