"""Interchangeable, deterministic stock screening rules. No orders."""
from dataclasses import asdict, dataclass
from typing import Protocol

import pandas as pd

from .indicators import relative_volume, rsi_wilder


@dataclass(frozen=True)
class ScreenResult:
    market: str
    symbol: str
    strategy_id: str
    strategy_version: str
    trade_date: str
    matched: bool
    metrics: dict
    reason: str


class ScreeningStrategy(Protocol):
    id: str
    version: str

    def scan(self, market: str, symbol: str, data: pd.DataFrame,
             params: dict) -> ScreenResult: ...


class RsiVolume:
    id = "rsi_volume"
    version = "1.0.0"

    def scan(self, market: str, symbol: str, data: pd.DataFrame,
             params: dict) -> ScreenResult:
        rsi_period = int(params.get("rsi_period", 14))
        rsi_max = float(params.get("rsi_max", 30))
        volume_window = int(params.get("volume_window", 20))
        ratio_min = float(params.get("volume_ratio_min", 2))
        rsi = rsi_wilder(data["close"], rsi_period)
        ratio = relative_volume(data["volume"], volume_window)
        matched = rsi is not None and ratio is not None and rsi < rsi_max and ratio >= ratio_min
        return ScreenResult(
            market, symbol, self.id, self.version, str(data.index[-1]), bool(matched),
            {"rsi": rsi, "relative_volume": ratio,
             "rsi_threshold_exclusive": rsi_max,
             "volume_ratio_min_inclusive": ratio_min},
            "RSI below threshold AND volume >= preceding N-bar average multiple",
        )


class MaBreakout:
    id = "ma_breakout"
    version = "1.0.0"

    def scan(self, market: str, symbol: str, data: pd.DataFrame,
             params: dict) -> ScreenResult:
        n = int(params.get("ma_window", 20))
        if n < 2:
            raise ValueError("MA window must be >= 2")
        close = data["close"]
        ma = close.rolling(n).mean()
        previous_valid = len(close) >= n + 1 and pd.notna(ma.iloc[-2])
        matched = bool(previous_valid and close.iloc[-2] <= ma.iloc[-2] and close.iloc[-1] > ma.iloc[-1])
        return ScreenResult(
            market, symbol, self.id, self.version, str(data.index[-1]), matched,
            {"ma_window": n,
             "ma_current": float(ma.iloc[-1]) if pd.notna(ma.iloc[-1]) else None,
             "ma_previous": float(ma.iloc[-2]) if previous_valid else None,
             "close_current": float(close.iloc[-1])},
            "previous close <= previous MA AND current close > current MA",
        )


STRATEGIES = {"rsi_volume": RsiVolume, "ma_breakout": MaBreakout}


def get_strategy(name: str) -> ScreeningStrategy:
    if name not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {name}")
    return STRATEGIES[name]()
