"""Data quality checks: reject corrupt rows rather than generating signals."""
from datetime import date
import numpy as np
import pandas as pd


class DataQualityError(ValueError):
    pass


def validate_daily(data: pd.DataFrame, symbol: str, minimum_rows: int = 22,
                   market_today: date | None = None) -> dict:
    cols = {"open", "high", "low", "close", "volume"}
    if not cols.issubset(data.columns):
        raise DataQualityError(f"{symbol}: missing {cols - set(data.columns)}")
    if data.index.has_duplicates:
        raise DataQualityError(f"{symbol}: duplicate dates")
    if not data.index.is_monotonic_increasing:
        raise DataQualityError(f"{symbol}: unsorted dates")
    if len(data) < minimum_rows:
        raise DataQualityError(f"{symbol}: only {len(data)} bars; need {minimum_rows}")
    price = data[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    volume = pd.to_numeric(data["volume"], errors="coerce")
    if not np.isfinite(price.to_numpy(dtype=float)).all():
        raise DataQualityError(f"{symbol}: invalid OHLC")
    if not np.isfinite(volume.to_numpy(dtype=float)).all():
        raise DataQualityError(f"{symbol}: invalid volume")
    if (price <= 0).to_numpy().any() or (volume < 0).any():
        raise DataQualityError(f"{symbol}: negative volume or nonpositive price")
    if ((price["high"] < price[["open","low","close"]].max(axis=1)) |
        (price["low"] > price[["open","high","close"]].min(axis=1))).any():
        raise DataQualityError(f"{symbol}: inconsistent OHLC ranges")
    today = market_today or pd.Timestamp.now(tz="UTC").date()
    if data.index[-1] > today:
        raise DataQualityError(f"{symbol}: future date")
    return {
        "symbol": symbol, "status": "valid", "bars": len(data),
        "first_date": str(data.index[0]), "last_date": str(data.index[-1]),
        "zero_volume_bars": int((volume == 0).sum()),
    }
