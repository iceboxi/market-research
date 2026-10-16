"""One normalized, validated daily market-data boundary for scans and backtests.

DailyBars.frame is the ANALYSIS OHLCV series. The separate execution_price_basis
metadata explicitly states whether its OHLC prices are realistic fill proxies.
No investment decisions should imply Yahoo dividend-adjusted prices are executable.
"""
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from zoneinfo import ZoneInfo

import pandas as pd

from .market_calendar import expected_complete_session, require_complete_session
from .validation import validate_daily

DATA_CONTRACT_VERSION = 1
PRICE_BASIS = {
    "tw": "twse_official_unadjusted",
    "us": "yahoo_adj_close_ratio_adjusted_ohlc",
}
EXECUTION_BASIS = {
    "tw": "twse_raw_open_proxy_not_guaranteed_fill",
    "us": "dividend_adjusted_open_not_executable_price",
}


@dataclass(frozen=True)
class DailyBars:
    frame: pd.DataFrame
    metadata: dict
    warnings: tuple[dict, ...]


def load_daily_bars(provider, market: str, symbol: str, period: str,
                    now: datetime, timezone: str,
                    strict_freshness: bool = False) -> DailyBars:
    if now.tzinfo is None:
        raise ValueError("now must have timezone")
    if market not in PRICE_BASIS:
        raise ValueError(f"Unsupported market: {market}")
    frame = provider.load(symbol, period)
    if frame.empty:
        raise ValueError(f"{symbol}: empty daily history")
    frame = frame.copy()
    expected = expected_complete_session(market, now)
    warnings = []
    last = pd.Timestamp(frame.index[-1]).date()
    # The same market-session rule applies to both daily screening and research
    # backtests. Unfinished session bars must never be used for signals.
    if last > expected:
        provisional = [str(day) for day in frame.index
                       if pd.Timestamp(day).date() > expected]
        warnings.append({
            "market": market, "symbol": symbol,
            "reason": "unfinalized_session_bars_excluded",
            "excluded_dates": provisional,
            "excluded_date": provisional[-1],
        })
        frame = frame.loc[[pd.Timestamp(d).date() <= expected for d in frame.index]]
        if frame.empty:
            raise ValueError(f"{symbol}: no completed sessions in daily history")
    local_date = now.astimezone(ZoneInfo(timezone)).date()
    checked = validate_daily(frame, symbol, market_today=local_date)
    if strict_freshness:
        checked["session"] = require_complete_session(market, frame.index[-1], now)
    elif pd.Timestamp(frame.index[-1]).date() < expected:
        warnings.append({
            "market": market, "symbol": symbol,
            "reason": "stale_history_allowed_for_research",
            "expected_session": expected.isoformat(),
            "latest_date": str(frame.index[-1]),
            "excluded_date": str(frame.index[-1]),
        })

    provider_for = (provider.provider_for(symbol)
                    if hasattr(provider, "provider_for") else provider)
    source = getattr(provider_for, "source", getattr(provider, "source", "unknown"))
    if source == "checksummed_local_replay" and hasattr(provider, "records"):
        source = provider.records[symbol]["source"]
    checked.update({
        "market": market, "symbol": symbol,
        "source": source, "contract_version": DATA_CONTRACT_VERSION,
        "price_basis": PRICE_BASIS[market],
        "execution_price_basis": EXECUTION_BASIS[market],
        "volume_unit": "reported_shares",
        "as_of_market_date": str(local_date),
        "last_date": str(frame.index[-1]),
        "expected_completed_session": expected.isoformat(),
        "input_sha256": sha256(frame.to_csv().encode("utf-8")).hexdigest(),
    })
    return DailyBars(frame=frame, metadata=checked, warnings=tuple(warnings))
