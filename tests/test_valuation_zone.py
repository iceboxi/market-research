"""#114: historical P/E review zone for watchlist satellites."""
from datetime import date, timedelta
from pathlib import Path

import pytest

from market_research.valuation_zone import (
    MIN_PER_SAMPLES, evaluate_valuation_zone, load_watchlist, per_window_start,
)

CUTOFF = date(2026, 10, 29)
SOURCE = "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPER&data_id=2330&start_date=2021-10-29"
SATELLITE = {"thesis": None, "valuation_zone": {"percentiles": (20, 50, 80)}}
ROOT = Path(__file__).resolve().parents[1]


def per_rows(values, code="2330", end=CUTOFF):
    # One row per calendar day back from `end`; values[0] is the oldest.
    n = len(values)
    return [{"date": (end - timedelta(days=n - 1 - i)).isoformat(), "stock_id": code,
             "dividend_yield": 1.5, "PER": v, "PBR": 5.0} for i, v in enumerate(values)]


def uniform():
    # 1,001 P/E values 10.00..20.00: linear percentiles 20/50/80 are 12/15/18 exactly.
    return [10 + i / 100 for i in range(1001)]


def ttm(eps=40.0, end="2026-09-30", status="available"):
    return {"status": status, "basic_eps": eps, "period_start": "2025-10-01",
            "period_end": end, "quarters": ["2025Q4", "2026Q1", "2026Q2", "2026Q3"],
            "eps_derivation": "sum_of_four_quarters_within_0.5pct_share_drift"}


def price(close=600.0, session="2026-10-29"):
    return {"close": close, "session": session, "source": "twse_stock_day_official_raw_ohlcv"}


def zone(rows=None, *, settings=SATELLITE, eps=None, close=None, **kw):
    history = {"source": SOURCE, "rows": per_rows(uniform()) if rows is None else rows}
    return evaluate_valuation_zone(
        "2330.TW", CUTOFF, settings, kw.get("history", history),
        eps or ttm(), close or price(), **{k: v for k, v in kw.items() if k != "history"})


def test_percentile_band_times_ttm_eps_gives_review_prices():
    result = zone()
    assert result["status"] == "available" and result["reason"] is None
    assert result["method"] == "historical_per_percentile_x_ttm_eps"
    assert result["pe_band"] == {"low": 12.0, "mid": 15.0, "high": 18.0}
    assert result["review_prices_twd"] == {"low": 480.0, "mid": 600.0, "high": 720.0}
    assert result["zone"] == "fair"
    history = result["per_history"]
    assert history["samples"] == 1001 and history["source"] == SOURCE
    assert history["window_start"] == "2021-10-29" and history["last_date"] == "2026-10-29"
    assert history["latest_per"] == 20.0
    assert result["eps"]["ttm_basic_eps"] == 40.0
    assert result["eps"]["period_end"] == "2026-09-30"
    assert result["price"]["close"] == 600.0
    assert result["disclaimer"] == "檢視區，非買賣建議"


@pytest.mark.parametrize("close,expected", [
    (479.99, "below_low"), (480.0, "fair"), (720.0, "fair"), (720.01, "above_high"),
])
def test_zone_boundaries_belong_to_fair(close, expected):
    assert zone(close=price(close))["zone"] == expected


def test_per_after_cutoff_or_before_window_is_never_used():
    rows = per_rows(uniform())
    rows.append({"date": "2026-10-30", "stock_id": "2330", "PER": 900.0})
    rows.append({"date": "2021-10-28", "stock_id": "2330", "PER": 900.0})
    result = zone(rows)
    assert result["pe_band"] == {"low": 12.0, "mid": 15.0, "high": 18.0}
    assert result["per_history"]["samples"] == 1001
    assert result["per_history"]["last_date"] == "2026-10-29"


def test_non_positive_per_rows_are_excluded_not_zero_filled():
    rows = per_rows(uniform()) + per_rows([0.0, -3.0, None], end=CUTOFF - timedelta(days=1200))
    assert zone(rows)["per_history"]["samples"] == 1001


@pytest.mark.parametrize("eps,reason", [
    (ttm(status="not_evaluated"), "TTM EPS"),
    (ttm(eps=None), "TTM EPS"),
    (ttm(eps=0.0), "not positive"),
    (ttm(eps=-1.5), "not positive"),
    (ttm(end="2026-04-11"), "stale"),
    (ttm(end="2026-12-31"), "after evaluation cutoff"),
])
def test_unusable_eps_is_not_evaluated(eps, reason):
    result = zone(eps=eps)
    assert result["status"] == "not_evaluated" and result["zone"] == "not_evaluated"
    assert reason in result["reason"]
    assert result["review_prices_twd"] is None


def test_ttm_ending_exactly_at_age_limit_is_still_current():
    assert zone(eps=ttm(end="2026-04-12"))["status"] == "available"


def test_insufficient_per_samples_is_not_evaluated_at_the_boundary():
    enough = per_rows([15.0] * MIN_PER_SAMPLES)
    assert zone(enough)["status"] == "available"
    result = zone(enough[1:])
    assert result["status"] == "not_evaluated"
    assert f"{MIN_PER_SAMPLES - 1} PER samples" in result["reason"]


@pytest.mark.parametrize("history,reason", [
    (None, "TaiwanStockPER unavailable"),
    ({"source": SOURCE, "rows": per_rows([15.0] * 800, code="2317")}, "stock_id"),
])
def test_missing_or_foreign_per_history_is_not_evaluated(history, reason):
    result = zone(history=history)
    assert result["status"] == "not_evaluated" and reason in result["reason"]


def test_missing_close_or_future_session_is_not_evaluated():
    assert "close" in zone(close={"close": None, "session": None, "source": None})["reason"]
    assert "after evaluation cutoff" in zone(close=price(session="2026-10-30"))["reason"]


def test_percentile_override_and_fixed_multiple_override():
    custom = zone(settings={"thesis": None, "valuation_zone": {"percentiles": (10, 50, 90)}})
    assert custom["pe_band"] == {"low": 11.0, "mid": 15.0, "high": 19.0}
    assert custom["percentiles"] == [10, 50, 90]
    fixed = zone(settings={"thesis": None, "valuation_zone": {"pe_multiples": (12, 16, 20)}},
                 history=None)
    assert fixed["status"] == "available"
    assert fixed["method"] == "configured_pe_multiples_x_ttm_eps"
    assert fixed["review_prices_twd"] == {"low": 480.0, "mid": 640.0, "high": 800.0}
    assert fixed["per_history"] is None


def test_non_satellite_is_not_evaluated():
    result = zone(settings=None)
    assert result["status"] == "not_evaluated" and "watchlist" in result["reason"]


def test_window_start_handles_leap_day():
    assert per_window_start(CUTOFF) == date(2021, 10, 29)
    assert per_window_start(date(2028, 2, 29)) == date(2023, 2, 28)


def write_config(tmp_path, watchlist, symbols=("2330.TW", "2317.TW", "0050.TW")):
    (tmp_path / "markets.yaml").write_text(
        "markets:\n  tw:\n    timezone: Asia/Taipei\n    symbols:\n"
        + "".join(f"      - {s}\n" for s in symbols))
    (tmp_path / "watchlist.yaml").write_text(watchlist)
    return tmp_path


def test_production_watchlist_is_the_five_satellites_with_theses():
    satellites = load_watchlist(ROOT / "config")
    assert sorted(satellites) == ["2317.TW", "2330.TW", "2356.TW", "2454.TW", "3017.TW"]
    assert all(s["valuation_zone"] == {"percentiles": (20, 50, 80)} for s in satellites.values())
    assert all(s["thesis"] and "失效條件" in s["thesis"] for s in satellites.values())


def test_watchlist_override_is_normalized(tmp_path):
    config = write_config(tmp_path, "satellites:\n  2317.TW:\n    thesis: 代工龍頭\n"
                          "    valuation_zone:\n      pe_multiples: [10, 12.5, 15]\n")
    assert load_watchlist(config) == {
        "2317.TW": {"thesis": "代工龍頭", "valuation_zone": {"pe_multiples": (10.0, 12.5, 15.0)},
                    "revenue_check": {"consecutive_months": 3, "yoy_below_pct": 0.0}}}


@pytest.mark.parametrize("body,message", [
    ("satellites:\n  2454.TW:\n    thesis: null\n", "not a scanned tw symbol"),
    ("satellites:\n  0050.TW:\n    thesis: null\n", "ETF"),
    ("satellites:\n  2330.TW:\n    valuation_zone:\n      percentiles: [20, 50, 80]\n"
     "      pe_multiples: [10, 15, 20]\n", "either percentiles or pe_multiples"),
    ("satellites:\n  2330.TW:\n    valuation_zone:\n      percentiles: [50, 20, 80]\n",
     "three increasing"),
    ("satellites:\n  2330.TW:\n    valuation_zone:\n      percentiles: [0, 50, 100]\n",
     "between 0 and 100"),
    ("satellites:\n  2330.TW:\n    valuation_zone:\n      pe_multiples: [0, 5, 10]\n",
     "positive"),
    ("satellites:\n  2330.TW:\n    target: 1000\n", "unknown"),
])
def test_invalid_watchlist_is_a_config_error(tmp_path, body, message):
    with pytest.raises(ValueError, match=message):
        load_watchlist(write_config(tmp_path, body))


def test_missing_watchlist_means_no_satellites(tmp_path):
    (tmp_path / "markets.yaml").write_text("markets:\n  tw:\n    symbols: []\n")
    assert load_watchlist(tmp_path) == {}


def test_share_count_change_falls_back_to_the_twse_four_quarter_sum():
    # basic_eps stays strict (None above 0.5% share drift); the zone uses TWSE's P/E basis.
    drifted = {**ttm(eps=None), "eps_derivation": "not_evaluated", "quarter_eps_sum": 40.0,
               "share_count_max_drift_pct": 7.47}
    result = zone(eps=drifted)
    assert result["status"] == "available"
    assert result["eps"]["ttm_basic_eps"] == 40.0
    assert result["eps"]["derivation"] == "sum_of_four_quarters_twse_pe_basis"
    assert result["review_prices_twd"] == {"low": 480.0, "mid": 600.0, "high": 720.0}
    strict = zone()
    assert strict["eps"]["derivation"] == "sum_of_four_quarters_within_0.5pct_share_drift"


def test_no_quarter_sum_still_blocks_the_zone():
    missing = {**ttm(eps=None), "eps_derivation": "not_evaluated", "quarter_eps_sum": None}
    result = zone(eps=missing)
    assert result["status"] == "not_evaluated" and result["reason"].startswith("TTM EPS unavailable")
