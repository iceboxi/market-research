"""Black Three Crows v0.1.0: a bearish closed-candle observation only.

Research-specific mirrored counterpart to SakataThreeSoldiers: previous five
closes rising, three falling bearish bodies, opens within previous body, and
limited lower shadows. This plugin does not express short/trading orders.
"""
import math

import numpy as np
import pandas as pd

from .strategy_contract import ScreenResult
from .validation import DataQualityError


class SakataBlackThreeCrows:
    id = "sakata_black_three_crows"
    version = "0.1.0"
    DEFAULTS = {
        "prior_trend_bars": 5,
        "prior_rise_min_pct": 2.0,
        "min_body_to_range": 0.5,
        "max_lower_shadow_to_range": 0.25,
    }

    def scan(self, market: str, symbol: str, data: pd.DataFrame,
             params: dict) -> ScreenResult:
        unknown = set(params) - self.DEFAULTS.keys()
        if unknown:
            raise ValueError(f"Unknown Black Three Crows parameter: {sorted(unknown)}")
        config = {**self.DEFAULTS, **params}
        n = config["prior_trend_bars"]
        if type(n) is not int or not 2 <= n <= 50:
            raise ValueError("prior_trend_bars must be integer in [2,50]")
        for key in self.DEFAULTS.keys() - {"prior_trend_bars"}:
            value = config[key]
            if (isinstance(value, bool) or not isinstance(value, (int, float)) or
                    not math.isfinite(value)):
                raise ValueError(f"Invalid Black Three Crows parameter: {key}")
            lo = 0.0
            hi = 100.0 if key == "prior_rise_min_pct" else 1.0
            if value < lo or value > hi or (key == "min_body_to_range" and value == lo):
                raise ValueError(f"Invalid Black Three Crows parameter range: {key}")

        if data.empty:
            raise ValueError("Black Three Crows needs dated candle history")
        needed = n + 3
        if len(data) < needed:
            return ScreenResult(
                market, symbol, self.id, self.version, str(data.index[-1]), False,
                {"observation": "insufficient_history", "required_bars": needed},
                "Not enough completed candles",
            )

        window = data.iloc[-needed:]
        required = ["open", "high", "low", "close"]
        if not set(required).issubset(window.columns):
            raise DataQualityError(f"{symbol}: missing OHLC fields")
        prices = window[required].apply(pd.to_numeric, errors="coerce")
        values = prices.to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values <= 0).any():
            raise DataQualityError(f"{symbol}: invalid OHLC")
        if ((prices["high"] < prices[["open", "low", "close"]].max(axis=1)) |
            (prices["low"] > prices[["open", "close", "high"]].min(axis=1))).any():
            raise DataQualityError(f"{symbol}: inconsistent OHLC")

        previous = prices.iloc[:n]["close"]
        gain_pct = float((previous.iloc[-1] - previous.iloc[0]) / previous.iloc[0] * 100)
        o = prices["open"].iloc[-3:].to_numpy(dtype=float)
        h = prices["high"].iloc[-3:].to_numpy(dtype=float)
        l = prices["low"].iloc[-3:].to_numpy(dtype=float)
        c = prices["close"].iloc[-3:].to_numpy(dtype=float)
        spreads = h - l
        ranges_valid = bool((spreads > 0).all())
        bearish = bool((c < o).all())
        falling = bool((c[1:] < c[:-1]).all())
        opens_within = bool(((o[1:] <= o[:-1]) & (o[1:] >= c[:-1])).all())
        if ranges_valid:
            body_ok = bool(((o - c) / spreads >= config["min_body_to_range"]).all())
            lower_shadow_ok = bool((((c - l) / spreads >= 0) &
                                    ((c - l) / spreads <=
                                     config["max_lower_shadow_to_range"])).all())
        else:
            # Legitimate zero-range sessions are allowed as input; signal
            # candles must have positive range to satisfy body and wick rules.
            body_ok = lower_shadow_ok = False
        checks = {
            "prior_rise": gain_pct >= config["prior_rise_min_pct"],
            "three_bearish_candles": bearish,
            "falling_closes": falling,
            "opens_in_previous_body": opens_within,
            "body_ok": body_ok,
            "lower_shadows_ok": lower_shadow_ok,
        }
        return ScreenResult(
            market, symbol, self.id, self.version, str(data.index[-1]),
            bool(all(checks.values())),
            {"pattern": "bearish_black_three_crows",
             "prior_rise_pct": round(gain_pct, 6),
             "conditions": {key: bool(value) for key, value in checks.items()}},
            "Bearish three-candle observation after third close; no short or exit instruction",
        )
