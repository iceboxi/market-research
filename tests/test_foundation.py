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
