"""Strict three full-range windows over four consecutive completed sessions.

The TWSE source has *unadjusted* OHLC and no audited corporate-action feed:
TW patterns therefore abstain (matched=False) rather than mislabel dividend /
split price discontinuities. US observations use Yahoo analytical adjusted OHLC
and are labelled adjusted-price observations, NOT executable exchange gaps.
"""
import math
import numpy as np
import pandas as pd
import exchange_calendars as xcals

from .strategy_contract import ScreenResult
from .validation import DataQualityError


class ThreeGaps:
    id = None
    version = "0.1.0"
    direction = None
    DEFAULTS = {"prior_trend_bars": 5, "prior_trend_min_pct": 2.0,
                "minimum_full_gap_pct": 0.2}

    def scan(self, market, symbol, data, params):
        unknown = set(params) - self.DEFAULTS.keys()
        if unknown:
            raise ValueError(f"Unknown three-gaps parameter: {sorted(unknown)}")
        cfg = {**self.DEFAULTS, **params}
        n = cfg["prior_trend_bars"]
        if type(n) is not int or not 2 <= n <= 50:
            raise ValueError("Invalid prior_trend_bars")
        for key in self.DEFAULTS.keys() - {"prior_trend_bars"}:
            v = cfg[key]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 100:
                raise ValueError(f"Invalid three-gaps parameter: {key}")
        if market not in ("tw", "us"):
            raise ValueError("Unsupported market")
        if data.empty:
            raise ValueError("Empty price history")
        needed = n + 4
        if len(data) < needed:
            return ScreenResult(market, symbol, self.id, self.version, str(data.index[-1]),
                                False, {"observation": "insufficient_history",
                                        "required_bars": needed}, "Not enough completed sessions")
        subset = data.iloc[-needed:]
        columns = ["open", "high", "low", "close"]
        if not set(columns).issubset(subset.columns):
            raise DataQualityError(f"{symbol}: missing OHLC fields")
        p = subset[columns].apply(pd.to_numeric, errors="coerce")
        v = p.to_numpy(dtype=float)
        if not np.isfinite(v).all() or (v <= 0).any():
            raise DataQualityError(f"{symbol}: nonfinite or nonpositive OHLC")
        if ((p.high < p[["open", "low", "close"]].max(axis=1)) |
            (p.low > p[["open", "high", "close"]].min(axis=1))).any():
            raise DataQualityError(f"{symbol}: inconsistent OHLC")
        date = str(data.index[-1])
        if market == "tw":
            # No verified corporate action calendar is present; explicitly
            # refuse even a perfect pattern on unadjusted official prices.
            return ScreenResult(market, symbol, self.id, self.version, date, False,
                                {"observation": "corporate_actions_unverified",
                                 "price_basis": "twse_unadjusted"},
                                "Strict gap observation abstained: TWSE corporate actions unverified")
        dates = pd.DatetimeIndex(data.index[-4:]).normalize().tz_localize(None)
        if dates.has_duplicates or not dates.is_monotonic_increasing:
            raise DataQualityError(f"{symbol}: duplicate or unordered session dates")
        cal = xcals.get_calendar("XNYS")
        expected = cal.sessions_in_range(dates[0], dates[-1]).tz_localize(None)
        if list(expected) != list(dates):
            return ScreenResult(market, symbol, self.id, self.version, date, False,
                                {"observation": "nonconsecutive_exchange_sessions"},
                                "Missing US exchange session in four-bar pattern")
        sign = 1 if self.direction == "up" else -1
        trend = p.close.iloc[:n]
        pct = sign * (trend.iloc[-1] - trend.iloc[0]) / trend.iloc[0] * 100
        last = p.iloc[-4:]
        full_gap_pct = []
        for i in range(1, 4):
            before, after = last.iloc[i - 1], last.iloc[i]
            if sign == 1:
                gap = (after.low - before.high) / before.high * 100
            else:
                gap = (before.low - after.high) / before.low * 100
            full_gap_pct.append(float(gap))
        checks = {
            "prior_trend": bool(pct >= cfg["prior_trend_min_pct"]),
            "three_strict_windows": all(x > 0 for x in full_gap_pct),
            "gap_minimum": all(x >= cfg["minimum_full_gap_pct"] for x in full_gap_pct),
        }
        return ScreenResult(market, symbol, self.id, self.version, date,
                            all(checks.values()),
                            {"observation": "adjusted_price_window_only",
                             "price_basis": "us_yahoo_adjusted_analysis_ohlc",
                             "gap_percentages": [round(x, 6) for x in full_gap_pct],
                             "conditions": checks},
                            "Three adjusted-price full windows; NOT a verified executable gap or a reversal order")


class SakataThreeGapsUp(ThreeGaps):
    id = "sakata_three_gaps_up"
    direction = "up"


class SakataThreeGapsDown(ThreeGaps):
    id = "sakata_three_gaps_down"
    direction = "down"
