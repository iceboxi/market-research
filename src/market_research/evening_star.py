"""Evening Star 0.1.0: bearish completed-candle observation, NOT a short order.

Research convention mirrors Morning Star on the price axis, with a five-close
uptrend, a strong first bullish candle, a small star, and bearish retracement.
"""
import math

import numpy as np
import pandas as pd

from .strategy_contract import ScreenResult
from .validation import DataQualityError


class SakataEveningStar:
    id = "sakata_evening_star"
    version = "0.1.0"
    DEFAULTS = {
        "prior_trend_bars": 5,
        "prior_rise_min_pct": 2.0,
        "first_body_to_range_min": 0.6,
        "star_to_first_body_max": 0.3,
        "third_body_to_range_min": 0.5,
        "third_reversal_of_first_body_min": 0.5,
    }

    def scan(self, market: str, symbol: str, data: pd.DataFrame,
             params: dict) -> ScreenResult:
        unknown = set(params) - self.DEFAULTS.keys()
        if unknown:
            raise ValueError(f"Unknown Evening Star parameter: {sorted(unknown)}")
        config = {**self.DEFAULTS, **params}
        n = config["prior_trend_bars"]
        if type(n) is not int or not 2 <= n <= 50:
            raise ValueError("prior_trend_bars must be integer in [2,50]")
        for key in self.DEFAULTS.keys() - {"prior_trend_bars"}:
            value = config[key]
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value)):
                raise ValueError(f"Invalid Evening Star parameter: {key}")
            upper = 100 if key == "prior_rise_min_pct" else 1
            strictly_positive = key in ("first_body_to_range_min", "third_body_to_range_min")
            if value < 0 or value > upper or (strictly_positive and value == 0):
                raise ValueError(f"Invalid Evening Star parameter range: {key}")
        if data.empty:
            raise ValueError("Evening Star needs a dated candle history")
        needed = n + 3
        if len(data) < needed:
            return ScreenResult(
                market, symbol, self.id, self.version, str(data.index[-1]),
                False, {"observation": "insufficient_history", "required_bars": needed},
                "Not enough completed candles"
            )

        window = data.iloc[-needed:]
        columns = ["open", "high", "low", "close"]
        if not set(columns).issubset(window.columns):
            raise DataQualityError(f"{symbol}: missing OHLC fields")
        prices = window[columns].apply(pd.to_numeric, errors="coerce")
        values = prices.to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values <= 0).any():
            raise DataQualityError(f"{symbol}: invalid OHLC")
        if ((prices["high"] < prices[["open", "low", "close"]].max(axis=1)) |
            (prices["low"] > prices[["open", "high", "close"]].min(axis=1)) |
            (prices["high"] < prices["low"])).any():
            raise DataQualityError(f"{symbol}: inconsistent OHLC")

        previous = prices.iloc[:n]["close"]
        rise_pct = (previous.iloc[-1] - previous.iloc[0]) / previous.iloc[0] * 100
        first, star, third = prices.iloc[-3], prices.iloc[-2], prices.iloc[-1]
        first_body = float(first["close"] - first["open"])
        first_range = float(first["high"] - first["low"])
        third_range = float(third["high"] - third["low"])
        checks = {
            "prior_rise": bool(rise_pct >= config["prior_rise_min_pct"]),
            "first_bullish": first_body > 0,
            "first_long_body": bool(first_range > 0 and first_body / first_range >= config["first_body_to_range_min"]),
            "star_small_body": bool(abs(star["close"] - star["open"]) <=
                                    config["star_to_first_body_max"] * first_body),
            "star_above_first_close": bool(min(star["open"], star["close"]) >= first["close"]),
            "third_bearish": bool(third["close"] < third["open"]),
            "third_body": bool(third_range > 0 and
                               (third["open"] - third["close"]) / third_range >=
                               config["third_body_to_range_min"]),
            "third_reversal": bool(first_body > 0 and
                                  (first["close"] - third["close"]) / first_body >=
                                  config["third_reversal_of_first_body_min"]),
        }
        return ScreenResult(
            market, symbol, self.id, self.version, str(data.index[-1]),
            all(checks.values()),
            {"pattern": "evening_star", "prior_rise_pct": round(float(rise_pct), 6),
             "conditions": checks},
            "Bearish three-candle observation after close; not an entry, short, or exit instruction",
        )
