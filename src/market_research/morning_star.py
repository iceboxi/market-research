"""Specified Morning Star 0.1.0: completed candle observations, not orders."""
import math
import pandas as pd
from .strategy_contract import ScreenResult
from .validation import DataQualityError


class SakataMorningStar:
    id = "sakata_morning_star"
    version = "0.1.0"

    DEFAULTS = {
        "prior_trend_bars": 5,
        "prior_decline_min_pct": 2.0,
        "first_body_to_range_min": 0.6,
        "star_to_first_body_max": 0.3,
        "third_body_to_range_min": 0.5,
        "third_recovery_of_first_body_min": 0.5,
    }

    def scan(self, market, symbol, data, params):
        unknown = set(params) - set(self.DEFAULTS)
        if unknown:
            raise ValueError(f"Unknown Morning Star parameter: {sorted(unknown)}")
        config = {**self.DEFAULTS, **params}
        n = config["prior_trend_bars"]
        if type(n) is not int or not 2 <= n <= 50:
            raise ValueError("prior_trend_bars must be integer in [2,50]")
        for key in self.DEFAULTS.keys() - {"prior_trend_bars"}:
            v = config[key]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f"Invalid Morning Star parameter: {key}")
            upper = 100 if key == "prior_decline_min_pct" else 1
            lower_exclusive = key in {"first_body_to_range_min", "third_body_to_range_min"}
            if v > upper or v < 0 or (lower_exclusive and v == 0):
                raise ValueError(f"Invalid Morning Star parameter range: {key}")
        if not len(data):
            raise ValueError("Empty candles cannot establish a signal date")
        needed = n + 3
        if len(data) < needed:
            return ScreenResult(market, symbol, self.id, self.version, str(data.index[-1]),
                                False, {"observation": "insufficient_history",
                                        "required_bars": needed}, "Not enough completed candles")
        # Runtime loader validates all bars; direct plugin calls validate the
        # exact observation window to fail closed on corrupt fixtures.
        df = data.iloc[-needed:]
        required = ["open", "high", "low", "close"]
        if not set(required).issubset(df.columns):
            raise DataQualityError(f"{symbol}: missing OHLC fields")
        values = df[required].apply(pd.to_numeric, errors="coerce")
        if not math.isfinite(float(values.to_numpy(dtype=float).sum())) or (values <= 0).to_numpy().any():
            raise DataQualityError(f"{symbol}: invalid OHLC")
        if ((values["high"] < values[["open", "low", "close"]].max(axis=1)) |
            (values["low"] > values[["open", "high", "close"]].min(axis=1)) |
            (values["high"] <= values["low"])).any():
            raise DataQualityError(f"{symbol}: inconsistent OHLC")
        previous = values.iloc[:n]["close"]
        decline = (previous.iloc[0] - previous.iloc[-1]) / previous.iloc[0] * 100
        one, star, three = [values.iloc[-i] for i in (3, 2, 1)]
        first_body = one["open"] - one["close"]
        checks = {
            "prior_decline": decline >= config["prior_decline_min_pct"],
            "first_bearish": first_body > 0,
            "first_long_body": first_body / (one["high"]-one["low"]) >= config["first_body_to_range_min"],
            "star_small_body": abs(star["close"]-star["open"]) <= config["star_to_first_body_max"] * first_body,
            "star_below_first_close": max(star["open"], star["close"]) <= one["close"],
            "third_bullish": three["close"] > three["open"],
            "third_body": (three["close"]-three["open"]) / (three["high"]-three["low"]) >= config["third_body_to_range_min"],
            "third_recovery": first_body > 0 and (
                (three["close"]-one["close"]) / first_body >= config["third_recovery_of_first_body_min"]),
        }
        return ScreenResult(market, symbol, self.id, self.version, str(data.index[-1]),
                            bool(all(checks.values())),
                            {"pattern": "morning_star", "prior_decline_pct": round(float(decline), 6),
                             "conditions": {k: bool(v) for k,v in checks.items()}},
                            "Three completed candle research observation; no trading instruction")
