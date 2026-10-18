from datetime import date
import math
import pandas as pd

from market_research.market_data import DailyBars
from market_research.price_context import analyze_price_context, render_price_context


def daily(close=100.0, price_basis="twse_official_unadjusted"):
    days = pd.bdate_range(end="2026-10-16", periods=81).date
    frame = pd.DataFrame({
        "open": [close] * 81, "high": [close + 2] * 81,
        "low": [close - 2] * 81, "close": [close] * 81,
        "volume": [100] * 81,
    }, index=pd.Index(days, name="date"))
    md = {
        "price_basis": price_basis, "source": "test_daily",
        "last_date": "2026-10-16", "expected_completed_session": "2026-10-16",
        "input_sha256": "a" * 64,
        "execution_price_basis": "fixture_execution_proxy",
    }
    return DailyBars(frame, md, ())


def test_constant_daily_ranges_and_no_fabricated_trade_plan():
    r = analyze_price_context(daily(), "tw")
    assert r["status"] == "observation_only"
    assert r["atr"]["absolute"] == 4
    assert r["levels"]["support_20d"] == 98
    assert r["levels"]["resistance_20d"] == 102
    assert r["levels"]["support_observation_band"]["lower"] == 96
    assert r["levels"]["structural_invalidation_reference"] == 94
    assert r["entry_zone"] is r["stop_loss"] is r["target_price"] is None
    assert r["executable"] is False
    assert "NOT buy prices" in "\n".join(render_price_context(r))


def test_signal_day_high_must_not_change_prior_resistance():
    data = daily()
    data.frame.loc[data.frame.index[-1], "high"] = 150
    r = analyze_price_context(data, "tw")
    assert r["levels"]["resistance_20d"] == 102
    assert r["atr"]["absolute"] > 4
    assert r["reference_state"] == "inside_prior_20d_range"


def test_stale_and_incomplete_history_fail_closed():
    data = daily()
    data.metadata["expected_completed_session"] = "2026-10-19"
    assert analyze_price_context(data, "tw")["status"] == "not_evaluated"
    data = daily()
    data.frame = data.frame.iloc[-40:]
    assert analyze_price_context(data, "tw")["status"] == "not_evaluated"
    data = daily()
    data.warnings = ({"reason": "stale_history_allowed_for_research"},)
    assert analyze_price_context(data, "tw")["status"] == "not_evaluated"


def test_large_unexplained_gap_blocks_levels():
    data = daily()
    idx = data.frame.index[-5]
    data.frame.loc[idx, ["open", "high", "low", "close"]] = [130, 132, 128, 130]
    r = analyze_price_context(data, "tw")
    assert r["status"] == "not_evaluated"
    assert "gap" in r["why"]


def test_invalid_price_and_unsupported_basis_rejected():
    data = daily()
    data.frame.loc[data.frame.index[-2], "close"] = math.nan
    assert analyze_price_context(data, "tw")["status"] == "not_evaluated"
    assert analyze_price_context(daily(), "us")["status"] == "not_evaluated"


def test_us_adjusted_context_never_executable():
    data = daily(price_basis="yahoo_adj_close_ratio_adjusted_ohlc")
    r = analyze_price_context(data, "us")
    assert r["status"] == "observation_only"
    assert r["currency"] == "USD"
    assert r["executable"] is False
    assert r["stop_loss"] is None
