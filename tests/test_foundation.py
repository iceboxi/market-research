from datetime import datetime, timezone
from pathlib import Path
import json
import pandas as pd
import pytest
from market_research.snapshots import write_snapshot, write_index, ReplayProvider
from market_research.market_calendar import expected_complete_session, require_complete_session, StaleMarketData
from market_research.data_contract import verify_scan_artifacts


def sample():
    dates = pd.bdate_range("2026-09-01", periods=40).date
    return pd.DataFrame({"open": [10.] * 40, "high": [11.] * 40,
        "low": [9.] * 40, "close": [10.] * 40, "volume": [100] * 40},
        index=pd.Index(dates, name="date"))


def test_checksummed_replay_and_corruption(tmp_path):
    original = sample()
    record = write_snapshot(tmp_path, "2330.TW", original, "TWSE")
    write_index(tmp_path, [record])
    replay = ReplayProvider(tmp_path).load("2330.TW")
    pd.testing.assert_frame_equal(original, replay, check_dtype=False)
    (tmp_path / "2330.TW.csv").write_text("tampered!")
    with pytest.raises(ValueError, match="checksum mismatch"):
        ReplayProvider(tmp_path).load("2330.TW")


def test_calendar_weekend_and_early_session():
    # Fri 2026-10-16, 04:00 UTC: before US close; should expect Thu.
    before = datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc)
    assert str(expected_complete_session("us", before)) == "2026-10-15"
    # Sat Taiwan, fully completed Fri 2026-10-16.
    saturday = datetime(2026, 10, 17, 2, 0, tzinfo=timezone.utc)
    assert str(expected_complete_session("tw", saturday)) == "2026-10-16"
    assert require_complete_session("tw", "2026-10-16", saturday)["status"] == "complete"
    with pytest.raises(StaleMarketData):
        require_complete_session("tw", "2026-10-15", saturday)


def test_contract_detects_missing_coverage():
    manifest = {"schema_version": 1, "requested_symbols": 2,
        "scanned_symbols": 1, "error_count": 0, "matching_signals": 0}
    with pytest.raises(ValueError, match="cover"):
        verify_scan_artifacts(manifest, {"symbols": [{}], "errors": []}, [], [])


def test_opt_in_scan_replay(tmp_path):
    from market_research.runner import run_scan
    class Fake:
        source = "fixture"
        def load(self, symbol, period="1y"): return sample()
    config = tmp_path / "config"
    config.mkdir()
    (config / "markets.yaml").write_text(
        "markets:\n  tw:\n    timezone: Asia/Taipei\n    symbols:\n      - 2330.TW\n")
    (config / "strategies.yaml").write_text(
        "strategies:\n  - id: sakata_three_soldiers\n    enabled: true\n    params: {}\n")
    a = run_scan("tw", config_dir=config, out=tmp_path/"a",
        provider=Fake(), snapshot_output=tmp_path/"snap",
        now=datetime(2026, 11, 17, tzinfo=timezone.utc))
    b = run_scan("tw", config_dir=config, out=tmp_path/"b",
        replay_dir=tmp_path/"snap", now=datetime(2026, 11, 17, tzinfo=timezone.utc))
    assert a["error_count"] == b["error_count"] == 0
    assert json.loads((tmp_path/"a"/"signals.json").read_text()) == json.loads(
        (tmp_path/"b"/"signals.json").read_text()
    )


def test_scan_without_enabled_strategies_is_price_only(tmp_path):
    # #117: production config has no pattern strategy; prices and health still run.
    from market_research.runner import run_scan
    class Fake:
        source = "fixture"
        def load(self, symbol, period="1y"): return sample()
    config = tmp_path / "config"
    config.mkdir()
    (config / "markets.yaml").write_text(
        "markets:\n  tw:\n    timezone: Asia/Taipei\n    symbols:\n      - 2330.TW\n      - 0050.TW\n")
    (config / "strategies.yaml").write_text(
        "strategies:\n  - id: sakata_three_soldiers\n    enabled: false\n    params: {}\n")
    result = run_scan("tw", config_dir=config, out=tmp_path / "out", provider=Fake(),
                      now=datetime(2026, 11, 17, tzinfo=timezone.utc))
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text())
    assert result["scanned_symbols"] == 2 and result["error_count"] == 0
    assert manifest["strategies"] == [] and manifest["matching_signals"] == 0
    assert json.loads((tmp_path / "out" / "screening_results.json").read_text()) == []


def test_shared_daily_contract_same_source_for_scan_and_backtest():
    from market_research.market_data import load_daily_bars
    class Provider:
        source = "fixture"
        def load(self, symbol, period="1y"): return sample()
    stamp = datetime(2026, 11, 17, tzinfo=timezone.utc)
    daily = load_daily_bars(Provider(), "tw", "2330.TW", "1y",
                            stamp, "Asia/Taipei", strict_freshness=False)
    assert daily.metadata["contract_version"] == 1
    assert daily.metadata["price_basis"] == "twse_official_unadjusted"
    assert len(daily.frame) == 40


def test_backtest_uses_same_verified_replay_and_data_hash(tmp_path):
    from market_research.backtest import run_backtest
    from market_research.runner import run_scan
    class Provider:
        source = "fixture"
        def load(self, symbol, period="1y"): return sample()
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "markets.yaml").write_text(
        "markets:\n  tw:\n    timezone: Asia/Taipei\n    symbols:\n      - 2330.TW\n")
    (cfg / "strategies.yaml").write_text(
        "strategies:\n  - id: sakata_three_soldiers\n    enabled: true\n    params: {}\n")
    (cfg / "backtest.yaml").write_text("backtest:\n  trials: 5\n")
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)
    run_scan("tw", config_dir=cfg, out=tmp_path / "scan", provider=Provider(),
             snapshot_output=tmp_path / "snap", now=now)
    manifest = run_backtest("tw", "1y", tmp_path / "backtest", cfg,
                            replay_dir=tmp_path / "snap", now=now)
    assert manifest["error_count"] == 0
    scan_quality = json.loads((tmp_path / "scan" / "data_quality.json").read_text())
    backtest_inputs = json.loads((tmp_path / "backtest" / "inputs.json").read_text())
    assert scan_quality["symbols"][0]["input_sha256"] == backtest_inputs[0]["input_sha256"]


def test_snapshot_replay_preserves_full_precision_ohlcv_hash(tmp_path):
    from hashlib import sha256
    from market_research.snapshots import write_snapshot, write_index, ReplayProvider
    df = sample().astype(float)
    df["open"] = [10.123456789123456 + i * 0.00000000123456789
                  for i in range(len(df))]
    df["high"] = df["open"] + 2.0
    df["low"] = df["open"] - 2.0
    df["close"] = df["open"] + 0.1000000001234
    df["adj_close"] = df["open"] * 0.9734567891234
    df["execution_open"] = df["open"] * 1.0234567891234
    record = write_snapshot(tmp_path, "AAPL", df, "yahoo_fixture")
    write_index(tmp_path, [record])
    replay = ReplayProvider(tmp_path).load("AAPL")
    assert sha256(df.to_csv().encode()).hexdigest() == sha256(
        replay.to_csv().encode()).hexdigest()
