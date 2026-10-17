"""Interchangeable, deterministic stock screening rules. No orders."""
import pandas as pd

from .indicators import relative_volume, rsi_wilder
from .strategy_contract import ScreenResult, ScreeningStrategy
from .morning_star import SakataMorningStar
from .evening_star import SakataEveningStar
from .black_three_crows import SakataBlackThreeCrows


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



class SakataThreeSoldiers:
    """An explicit *research variant* of Sakata red three soldiers; no trades."""
    id = "sakata_three_soldiers"
    version = "0.1.0"

    def scan(self, market: str, symbol: str, data: pd.DataFrame,
             params: dict) -> ScreenResult:
        n = int(params.get("prior_trend_bars", 5))
        decline = float(params.get("prior_decline_min_pct", 2))
        min_body = float(params.get("min_body_to_range", 0.5))
        max_upper = float(params.get("max_upper_shadow_to_range", 0.25))
        if n < 2 or decline < 0:
            raise ValueError("Invalid prior_trend_bars or prior_decline_min_pct")
        if not 0 < min_body <= 1 or not 0 <= max_upper < 1:
            raise ValueError("Invalid candle proportions")
        if len(data) < n + 3:
            return ScreenResult(market, symbol, self.id, self.version,
                str(data.index[-1]), False, {"observation": "insufficient_history",
                "required_bars": n + 3}, "Not enough completed candles")
        previous = data.iloc[-n-3:-3]["close"].astype(float)
        pct = float((previous.iloc[0] - previous.iloc[-1]) /
                    previous.iloc[0] * 100)
        o = data["open"].iloc[-3:].astype(float).to_numpy()
        h = data["high"].iloc[-3:].astype(float).to_numpy()
        l = data["low"].iloc[-3:].astype(float).to_numpy()
        c = data["close"].iloc[-3:].astype(float).to_numpy()
        spread = h - l
        bullish = bool((c > o).all())
        rising = bool((c[1:] > c[:-1]).all())
        within = bool(((o[1:] >= o[:-1]) & (o[1:] <= c[:-1])).all())
        ranges_valid = bool((spread > 0).all())
        body_ok = ranges_valid and bool(((c-o) / spread >= min_body).all())
        shadow_ok = ranges_valid and bool((((h-c) / spread >= 0) &
                                            ((h-c) / spread <= max_upper)).all())
        trend_ok = bool(pct >= decline)
        matched = bool(all((bullish, rising, within, body_ok, shadow_ok, trend_ok)))
        return ScreenResult(
            market, symbol, self.id, self.version, str(data.index[-1]),
            matched,
            {"pattern": "bullish_three_soldiers", "prior_decline_pct": round(pct, 4),
             "minimum_prior_decline_pct": decline, "min_body_to_range": min_body,
             "max_upper_shadow_to_range": max_upper,
             "three_bullish_candles": bullish, "rising_closes": rising,
             "opens_in_previous_body": within, "body_ok": body_ok,
             "upper_shadows_ok": shadow_ok, "prior_decline_ok": trend_ok},
            "Sakata-inspired K-line observation; not a trade recommendation",
        )


STRATEGIES = {"rsi_volume": RsiVolume, "ma_breakout": MaBreakout,
              "sakata_three_soldiers": SakataThreeSoldiers,
              "sakata_morning_star": SakataMorningStar,
              "sakata_evening_star": SakataEveningStar,
              "sakata_black_three_crows": SakataBlackThreeCrows}


def get_strategy(name: str) -> ScreeningStrategy:
    if name not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {name}")
    return STRATEGIES[name]()
