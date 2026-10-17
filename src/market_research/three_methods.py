"""Five-candle continuation patterns, completed bars only. No orders."""
import math
import numpy as np
import pandas as pd
from .strategy_contract import ScreenResult
from .validation import DataQualityError

class ThreeMethods:
    id = None
    direction = None
    version = "0.1.0"
    DEFAULTS = {
        "prior_trend_bars": 5, "prior_trend_min_pct": 2.0,
        "impulse_body_to_range_min": 0.6,
        "middle_body_to_first_body_max": 0.5,
        "final_body_to_range_min": 0.5,
    }

    def scan(self, market, symbol, data, params):
        if set(params) - self.DEFAULTS.keys():
            raise ValueError("Unknown three-methods parameter")
        cfg = {**self.DEFAULTS, **params}
        n = cfg["prior_trend_bars"]
        if type(n) is not int or not 2 <= n <= 50:
            raise ValueError("Invalid prior_trend_bars")
        for k in self.DEFAULTS.keys() - {"prior_trend_bars"}:
            v = cfg[k]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError("Invalid three-methods parameter")
            if not (0 <= v <= (100 if k == "prior_trend_min_pct" else 1)):
                raise ValueError("Parameter outside range")
            if k in ("impulse_body_to_range_min", "final_body_to_range_min") and v == 0:
                raise ValueError("Nonzero body threshold required")
        if data.empty:
            raise ValueError("Missing dated candles")
        needed = n + 5
        if len(data) < needed:
            return ScreenResult(market,symbol,self.id,self.version,str(data.index[-1]),
                False,{"observation":"insufficient_history","required_bars":needed},"Insufficient history")
        data = data.iloc[-needed:]
        cols = ["open","high","low","close"]
        if not set(cols).issubset(data.columns):
            raise DataQualityError("Missing OHLC")
        p = data[cols].apply(pd.to_numeric, errors="coerce")
        v = p.to_numpy(dtype=float)
        if not np.isfinite(v).all() or (v <= 0).any():
            raise DataQualityError("Invalid OHLC")
        if ((p.high < p[["open","low","close"]].max(axis=1)) |
            (p.low > p[["open","high","close"]].min(axis=1))).any():
            raise DataQualityError("Inconsistent OHLC")
        sign = 1 if self.direction == "bullish" else -1
        previous = p.iloc[:n].close
        movement = sign * (previous.iloc[-1]-previous.iloc[0])/previous.iloc[0]*100
        bars = p.iloc[-5:]
        first, middle, last = bars.iloc[0], bars.iloc[1:4], bars.iloc[4]
        first_body = sign*(first.close-first.open)
        last_body = sign*(last.close-last.open)
        first_range, last_range = first.high-first.low, last.high-last.low
        checks = {
            "prior_trend": bool(movement >= cfg["prior_trend_min_pct"]),
            "first_direction": bool(first_body > 0),
            "first_impulse": bool(first_range > 0 and first_body/first_range >= cfg["impulse_body_to_range_min"]),
            "three_opposite_middle_candles": bool((sign*(middle.close-middle.open) < 0).all()),
            "middle_inside_first_range": bool(((middle.high <= first.high) & (middle.low >= first.low)).all()),
            "middle_small_bodies": bool((abs(middle.close-middle.open) <= cfg["middle_body_to_first_body_max"]*first_body).all()),
            "final_direction": bool(last_body > 0),
            "final_impulse": bool(last_range > 0 and last_body/last_range >= cfg["final_body_to_range_min"]),
            "final_breakout": bool(sign*(last.close-first.close)>0),
        }
        return ScreenResult(market,symbol,self.id,self.version,str(data.index[-1]),
            all(checks.values()),{"pattern":self.id,"conditions":checks,"prior_trend_pct":float(movement)},
            "Five-candle continuation observation, not an order")

class SakataRisingThreeMethods(ThreeMethods):
    id = "sakata_rising_three_methods"
    direction = "bullish"

class SakataFallingThreeMethods(ThreeMethods):
    id = "sakata_falling_three_methods"
    direction = "bearish"
