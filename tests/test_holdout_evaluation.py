from datetime import datetime, timezone
import pandas as pd
import pytest

from scripts.holdout_evaluation import fixed_holdout, evaluate_market
from market_research.strategy_contract import ScreenResult


class SignalAt:
    id = "test"
    version = "0.1"
    def __init__(self, signal_positions):
        self.positions = set(signal_positions)
        self.seen = []
    def scan(self, market, symbol, df, params):
        idx = len(df)-1
        self.seen.append(idx)
        return ScreenResult(market, symbol, self.id, self.version,
                            str(df.index[-1]), idx in self.positions, {}, "test")


def bars(n=100):
    ix = pd.Index(pd.bdate_range("2026-02-02", periods=n).date, name="date")
    opens = [100 + i * 0.1 for i in range(n)]
    return pd.DataFrame({"open": opens, "high": [v+2 for v in opens],
                         "low": [v-2 for v in opens], "close": [v+1 for v in opens],
                         "volume": [1000]*n, "execution_open": opens}, index=ix)


def test_temporal_boundaries_and_no_lookahead():
    strategy = SignalAt({69,70,74,75,79,80,95,97,99})
    result = fixed_holdout(bars(),strategy,"us","TEST","bullish",{})
    assert result["training_end"] == str(bars().index[69])
    assert result["first_test_date"] == str(bars().index[75])
    assert [e["signal_date"] for e in result["events"]] == [
        str(bars().index[75]),str(bars().index[80])]
    assert result["censored_no_future_label"] == 3
    assert result["raw_holdout_signals"] == 6
    assert 69 not in strategy.seen and 74 not in strategy.seen
    assert result["evidence_status"] == "insufficient_independent_events"
    assert result["event_mean_directional_pct"] is None


def test_no_events_means_no_evidence():
    result = fixed_holdout(bars(),SignalAt(set()),"us","TEST","bearish",{})
    assert result["raw_holdout_signals"] == 0
    assert result["evidence_status"] == "no_signals"


def test_future_prices_do_not_change_prior_asof_signals():
    strategy = SignalAt({75})
    result = fixed_holdout(bars(),strategy,"us","TEST","bullish",{})
    assert result["events"][0]["signal_date"] == str(bars().index[75])
    assert result["events"][0]["label_end_date"] == str(bars().index[80])


def test_tiny_history_fails_closed():
    with pytest.raises(ValueError,match="insufficient"):
        fixed_holdout(bars(40),SignalAt({35}),"us","TEST","bullish",{})


def test_bad_embargo_rejected():
    with pytest.raises(ValueError,match="embargo"):
        fixed_holdout(bars(),SignalAt(set()),"us","TEST","bullish",{},embargo=2)


def test_production_strategy_not_eligible(tmp_path):
    import shutil
    cfg=tmp_path/"config"
    cfg.mkdir()
    root=__import__("pathlib").Path(__file__).resolve().parents[1]
    for file in ("markets.yaml","strategies.yaml"):
        shutil.copyfile(root/"config"/file,cfg/file)
    with pytest.raises(ValueError,match="disabled"):
        evaluate_market("tw",["sakata_three_soldiers"],"1y",tmp_path/"out",cfg)
