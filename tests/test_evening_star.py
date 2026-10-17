from pathlib import Path
import pandas as pd
import pytest
import yaml
from market_research.strategies import get_strategy
from market_research.validation import DataQualityError
from scripts import strategy_research

ROOT = Path(__file__).resolve().parents[1]
VECTORS = yaml.safe_load((ROOT / "tests/fixtures/evening_star.yaml").read_text())["cases"]


def frame(rows):
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"],
        index=pd.Index(pd.bdate_range("2026-08-03", periods=len(rows)).date, name="date")
    ).assign(volume=1000)


@pytest.mark.parametrize("case", VECTORS, ids=lambda row: row["id"])
def test_specification_vectors(case):
    strat = get_strategy("sakata_evening_star")
    bars = frame(case["rows"])
    if case["expected"] == "invalid_data":
        with pytest.raises(DataQualityError):
            strat.scan("tw", "TEST.TW", bars, {})
    else:
        result = strat.scan("tw", "TEST.TW", bars, {})
        assert result.matched == (case["expected"] == "match")
        assert result.strategy_version == "0.1.0"
        assert result.trade_date == str(bars.index[-1])
        if case["expected"] == "insufficient_history":
            assert result.metrics["observation"] == "insufficient_history"


def test_no_lookahead_and_repeated_observation():
    strat = get_strategy("sakata_evening_star")
    bars = frame(VECTORS[0]["rows"])
    assert not strat.scan("us", "TEST", bars.iloc[:-1], {}).matched
    first = strat.scan("us", "TEST", bars, {})
    assert first.matched
    future = frame([[107, 109, 105, 106]])
    future.index = [pd.Timestamp(bars.index[-1]) + pd.Timedelta(days=1)]
    extended = pd.concat([bars, future])
    assert strat.scan("us", "TEST", extended.iloc[:len(bars)], {}) == first


@pytest.mark.parametrize("params", [
    {"prior_trend_bars": 1}, {"prior_trend_bars": 2.3},
    {"first_body_to_range_min": 0}, {"star_to_first_body_max": float("nan")},
    {"third_reversal_of_first_body_min": 1.1}, {"unknown": 1}
])
def test_invalid_parameters(params):
    with pytest.raises(ValueError):
        get_strategy("sakata_evening_star").scan(
            "us", "TEST", frame(VECTORS[0]["rows"]), params)


def test_legitimate_flat_bar_is_not_corrupt():
    strat = get_strategy("sakata_evening_star")
    bars = frame(VECTORS[0]["rows"])
    bars.loc[bars.index[2], ["open", "high", "low", "close"]] = 102
    assert strat.scan("tw", "TEST.TW", bars, {}).matched
    bars = frame(VECTORS[0]["rows"])
    bars.loc[bars.index[-1], ["open", "high", "low", "close"]] = 108
    assert not strat.scan("tw", "TEST.TW", bars, {}).matched


def test_evening_star_is_disabled_and_has_no_long_only_backtest():
    config = yaml.safe_load((ROOT / "config/strategies.yaml").read_text())["strategies"]
    row = next(item for item in config if item["id"] == "sakata_evening_star")
    assert row["enabled"] is False
    assert strategy_research.select_variant("sakata_evening_star")["direction"] == "bearish"
