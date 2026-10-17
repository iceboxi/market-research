from pathlib import Path

import pandas as pd
import pytest
import yaml

from market_research.strategies import get_strategy
from market_research.validation import DataQualityError
from scripts import strategy_research

ROOT = Path(__file__).resolve().parents[1]
VECTORS = yaml.safe_load((ROOT / "tests/fixtures/black_three_crows.yaml").read_text())["cases"]


def frame(rows):
    dates = pd.bdate_range("2026-08-03", periods=len(rows)).date
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"],
                        index=pd.Index(dates, name="date")).assign(volume=1000)


@pytest.mark.parametrize("case", VECTORS, ids=lambda case: case["id"])
def test_specification_vectors(case):
    bars = frame(case["rows"])
    strategy = get_strategy("sakata_black_three_crows")
    if case["expected"] == "invalid_data":
        with pytest.raises(DataQualityError):
            strategy.scan("tw", "TEST.TW", bars, {})
    else:
        result = strategy.scan("tw", "TEST.TW", bars, {})
        assert result.matched == (case["expected"] == "match")
        assert result.strategy_version == "0.1.0"
        assert result.trade_date == str(bars.index[-1])
        if case["expected"] == "insufficient_history":
            assert result.metrics["observation"] == "insufficient_history"


def test_no_lookahead_and_repeated_same_prefix():
    strategy = get_strategy("sakata_black_three_crows")
    bars = frame(VECTORS[0]["rows"])
    assert not strategy.scan("us", "TEST", bars.iloc[:-1], {}).matched
    confirmed = strategy.scan("us", "TEST", bars, {})
    assert confirmed.matched
    extra = frame([[94, 96, 93, 95]])
    extra.index = [pd.Timestamp(bars.index[-1]) + pd.Timedelta(days=1)]
    append = pd.concat([bars, extra])
    assert strategy.scan("us", "TEST", append.iloc[:len(bars)], {}) == confirmed


@pytest.mark.parametrize("params", [
    {"prior_trend_bars": 1}, {"prior_trend_bars": 2.5},
    {"min_body_to_range": 0}, {"max_lower_shadow_to_range": -0.1},
    {"prior_rise_min_pct": float("nan")}, {"unknown": 3},
    {"max_lower_shadow_to_range": 1.1}
])
def test_invalid_parameters(params):
    with pytest.raises(ValueError):
        get_strategy("sakata_black_three_crows").scan(
            "us", "TEST", frame(VECTORS[0]["rows"]), params)


def test_flat_crow_no_signal_flat_trend_bar_allowed():
    strategy = get_strategy("sakata_black_three_crows")
    bars = frame(VECTORS[0]["rows"])
    bars.loc[bars.index[2], ["open", "high", "low", "close"]] = 102
    assert strategy.scan("tw", "TEST.TW", bars, {}).matched
    last_flat = frame(VECTORS[0]["rows"])
    last_flat.loc[last_flat.index[-1], ["open", "high", "low", "close"]] = 94
    assert not strategy.scan("tw", "TEST.TW", last_flat, {}).matched


def test_config_stays_disabled_and_generic_research_is_observation_only():
    settings = yaml.safe_load((ROOT / "config/strategies.yaml").read_text())["strategies"]
    enabled = [x["id"] for x in settings if x["enabled"]]
    assert enabled == ["sakata_three_soldiers"]
    entry = next(x for x in settings if x["id"] == "sakata_black_three_crows")
    assert entry["enabled"] is False
    assert strategy_research.select_variant("sakata_black_three_crows")["direction"] == "bearish"
