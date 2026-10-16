"""Deterministic indicators with explicit lookback and denominator semantics."""
import numpy as np
import pandas as pd


def rsi_wilder(closes: pd.Series, period: int = 14) -> float | None:
    """Wilder RSI with SMA seed; flat = 50, all gains = 100, all losses = 0."""
    if period < 2:
        raise ValueError("RSI period must be >= 2")
    a = closes.to_numpy(dtype=float)
    if len(a) < period + 1 or not np.isfinite(a).all():
        return None
    changes = np.diff(a)
    gains, losses = np.maximum(changes, 0), np.maximum(-changes, 0)
    gain, loss = float(gains[:period].mean()), float(losses[:period].mean())
    for g, l in zip(gains[period:], losses[period:]):
        gain = (gain * (period - 1) + g) / period
        loss = (loss * (period - 1) + l) / period
    if gain == 0 and loss == 0:
        return 50.0
    if loss == 0:
        return 100.0
    return float(100 - 100 / (1 + gain / loss))


def relative_volume(volumes: pd.Series, window: int = 20) -> float | None:
    """Current bar divided by preceding N bars average; excludes current bar."""
    if window < 1:
        raise ValueError("Volume window must be >= 1")
    if len(volumes) < window + 1:
        return None
    base = float(volumes.iloc[-window-1:-1].mean())
    if not np.isfinite(base) or base <= 0:
        return None
    return float(volumes.iloc[-1] / base)
