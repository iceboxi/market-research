from pathlib import Path
import pandas as pd
import pytest
import yaml

from market_research.strategies import get_strategy
from market_research.validation import DataQualityError
from market_research.backtest import backtest_symbol, Settings

ROOT = Path(__file__).resolve().parents[1]
VECTORS = yaml.safe_load((ROOT / "tests/fixtures/morning_star.yaml").read_text())["cases"]


def candles(rows):
    idx = pd.bdate_range("2026-09-01", periods=len(rows)).date
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"],
                        index=pd.Index(idx, name="date")).assign(volume=1000)


@pytest.mark.parametrize("case", VECTORS, ids=lambda case: case["id"])
def test_specification_vectors_run_against_real_plugin(case):
    strategy = get_strategy("sakata_morning_star")
    df = candles(case["rows"])
    if case["expected"] == "invalid_data":
        with pytest.raises(DataQualityError):
            strategy.scan("tw", "TEST.TW", df, {})
    else:
        result = strategy.scan("tw", "TEST.TW", df, {})
        assert result.matched is (case["expected"] == "match")
        assert result.strategy_version == "0.1.0"
        assert result.trade_date == str(df.index[-1])
        if case["expected"] == "insufficient_history":
            assert result.metrics["observation"] == "insufficient_history"


def test_deterministic_and_no_lookahead():
    s = get_strategy("sakata_morning_star")
    pattern = candles(VECTORS[0]["rows"])
    before = s.scan("us", "TEST", pattern.iloc[:-1], {})
    signal = s.scan("us", "TEST", pattern, {})
    assert not before.matched
    assert signal.matched
    later = pd.concat([pattern, candles([[101, 103, 100, 102]]).set_axis(
        [pd.Timestamp(pattern.index[-1]) + pd.Timedelta(days=1)])])
    assert s.scan("us", "TEST", later.iloc[:len(pattern)], {}) == signal
    assert s.scan("us", "TEST", pattern, {}) == signal


@pytest.mark.parametrize("params", [
    {"prior_trend_bars": 1},
    {"prior_trend_bars": 2.5},
    {"first_body_to_range_min": 0},
    {"star_to_first_body_max": float("nan")},
    {"third_recovery_of_first_body_min": 1.2},
    {"unknown": 1},
])
def test_bad_parameters_fail_closed(params):
    with pytest.raises(ValueError):
        get_strategy("sakata_morning_star").scan(
            "us", "TEST", candles(VECTORS[0]["rows"]), params)


def test_morning_star_backtest_uses_next_session_open():
    df = candles(VECTORS[0]["rows"])
    # 30 warmup bars preceding the signal, with no prior star pattern.
    pre = candles([[112, 113, 110, 111]] * 30)
    df = pd.concat([pre, df], ignore_index=True)
    df.index = pd.Index(pd.bdate_range("2026-07-01", periods=len(df)).date, name="date")
    df["execution_open"] = df["open"] * 1.03
    post = candles([[106, 107, 105, 106]] * 7)
    post.index = pd.Index(pd.bdate_range(df.index[-1], periods=8).date[1:], name="date")
    post["execution_open"] = post["open"] * 1.03
    df = pd.concat([df, post])
    strategy = get_strategy("sakata_morning_star")
    summary, trades = backtest_symbol(df, "us", "TEST", strategy, {}, Settings(trials=5))
    assert summary["strategy_id"] == "sakata_morning_star"
    assert trades
    assert trades[0]["signal_date"] == str(df.index[37])
    assert trades[0]["entry_date"] == str(df.index[38])
    assert trades[0]["entry_open"] == pytest.approx(df["execution_open"].iloc[38])


def test_not_enabled_by_default():
    enabled = [x["id"] for x in yaml.safe_load(
        (ROOT / "config/strategies.yaml").read_text())["strategies"] if x["enabled"]]
    assert enabled == ["sakata_three_soldiers"]


def test_flat_daily_bar_is_valid_but_not_a_morning_star():
    # TWSE sometimes reports a legitimate flat trading bar (H = L = O = C).
    # Validation must not reject the whole ticker or divide by zero.
    df = candles(VECTORS[0]["rows"])
    df.iloc[1, df.columns.get_loc("open")] = 109
    df.iloc[1, df.columns.get_loc("high")] = 109
    df.iloc[1, df.columns.get_loc("low")] = 109
    df.iloc[1, df.columns.get_loc("close")] = 109
    assert get_strategy("sakata_morning_star").scan("tw", "TEST.TW", df, {}).matched
    first_flat = candles(VECTORS[0]["rows"])
    for key in ("open", "high", "low", "close"):
        first_flat.loc[first_flat.index[-3], key] = 100
    assert not get_strategy("sakata_morning_star").scan("tw", "TEST.TW", first_flat, {}).matched
    third_flat = candles(VECTORS[0]["rows"])
    for key in ("open", "high", "low", "close"):
        third_flat.loc[third_flat.index[-1], key] = 101
    assert not get_strategy("sakata_morning_star").scan("tw", "TEST.TW", third_flat, {}).matched
