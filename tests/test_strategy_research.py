"""Reusable research must not change production or turn bearish patterns into long trades."""
from datetime import datetime, timezone
import pandas as pd
import pytest
from scripts import strategy_research as research


def make_config(path):
    path.mkdir(parents=True)
    (path / "markets.yaml").write_text(
        "markets:\n  tw:\n    timezone: Asia/Taipei\n    symbols: [2330.TW]\n"
    )
    (path / "strategies.yaml").write_text(
        "strategies:\n"
        "  - id: sakata_three_soldiers\n    enabled: true\n    params: {}\n"
        "  - id: sakata_morning_star\n    enabled: false\n    params: {}\n"
    )
    (path / "backtest.yaml").write_text("backtest:\n  trials: 3\n")


class SyntheticMarket:
    source = "synthetic_fixture"

    def load(self, symbol, period="1y"):
        dates = pd.bdate_range("2026-08-03", periods=55).date
        frame = pd.DataFrame({
            "open": [112.] * 55, "high": [113.] * 55,
            "low": [110.] * 55, "close": [111.] * 55, "volume": [1000] * 55,
        }, index=pd.Index(dates, name="date"))
        pattern = [
            [112, 113, 110, 111], [111, 112, 109, 110],
            [110, 111, 108, 109], [109, 110, 107, 108],
            [108, 109, 106, 107], [107, 108, 99, 100],
            [99, 101, 98, 100], [100, 105, 99, 104],
        ]
        for offset, row in enumerate(pattern):
            frame.loc[frame.index[35 + offset], ["open", "high", "low", "close"]] = row
        frame["execution_open"] = frame["open"]
        return frame


def test_catalog_allows_only_implemented_variants():
    variant = research.select_variant("sakata_morning_star")
    assert variant["version"] == "0.1.0"
    with pytest.raises(ValueError, match="not implemented"):
        research.select_variant("sakata_black_three_crows")
    with pytest.raises(ValueError, match="exactly once"):
        research.select_variant("does_not_exist")


def test_active_production_strategy_cannot_be_repurposed(tmp_path):
    cfg = tmp_path / "config"
    make_config(cfg)
    with pytest.raises(ValueError, match="enabled in production"):
        research.research_config(cfg, tmp_path / "isolated", "sakata_three_soldiers")


def test_generic_study_matches_existing_morning_star_and_preserves_config(tmp_path):
    cfg = tmp_path / "config"
    make_config(cfg)
    original = (cfg / "strategies.yaml").read_bytes()
    report = research.run_study(
        "sakata_morning_star", "tw", "1y", tmp_path / "report",
        cfg, SyntheticMarket(), datetime(2026, 11, 17, tzinfo=timezone.utc),
        strict_freshness=False
    )
    assert report["strategy_id"] == "sakata_morning_star"
    assert report["strategy_version"] == "0.1.0"
    assert report["strategy_direction"] == "bullish"
    assert report["same_snapshot_hashes_verified"]
    assert report["all_historical_observations"] >= 1
    assert report["closed_simulated_trades"] >= 1
    assert report["backtest_status"] == "exploratory_long_only"
    assert (cfg / "strategies.yaml").read_bytes() == original
    assert not list((tmp_path / "report").rglob("*.csv"))


def test_nonbullish_never_enters_long_only_backtester(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    make_config(cfg)
    actual = research.select_variant("sakata_morning_star")
    monkeypatch.setattr(research, "select_variant",
                        lambda _: {**actual, "direction": "bearish"})
    report = research.run_study(
        "sakata_morning_star", "tw", "1y", tmp_path / "report",
        cfg, SyntheticMarket(), datetime(2026, 11, 17, tzinfo=timezone.utc),
        strict_freshness=False
    )
    assert report["backtest_status"] == "skipped_unsupported_direction"
    assert report["closed_simulated_trades"] is None
    assert not (tmp_path / "report" / "backtest").exists()


def test_verify_fails_on_wrong_source_hash_or_coverage():
    strategy = {"id": "sakata_morning_star", "version": "0.1.0", "params": {}}
    scan = {"strategies": [strategy], "requested_symbols": 1,
            "scanned_symbols": 1, "error_count": 0,
            "strict_freshness": False, "matching_signals": 0}
    backtest = {"strategies": [strategy], "requested": 1,
                "scanned": 1, "error_count": 0, "strict_freshness": False}
    row = {"market": "tw", "symbol": "2330.TW", "input_sha256": "a"*64,
           "last_date": "2026-10-16", "source": "synthetic_fixture"}
    args = ([row], {"symbols": [row]}, [], {"params": {}}, "tw", "sakata_morning_star")
    assert research.verify(backtest, scan, *args)
    mismatched = {**row, "input_sha256": "b"*64}
    with pytest.raises(ValueError, match="different OHLCV hashes"):
        research.verify(backtest, scan, [row], {"symbols": [mismatched]}, [],
                        {"params": {}}, "tw", "sakata_morning_star")
    scan["scanned_symbols"] = 0
    with pytest.raises(ValueError, match="missing or failed tickers"):
        research.verify(backtest, scan, *args)
