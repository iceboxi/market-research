import json
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import pytest
from scripts.morning_star_research import research_config, run_study, verify

def make_data():
    idx = pd.bdate_range("2026-08-03", periods=55).date
    df = pd.DataFrame({"open": [112.0]*55, "high": [113.0]*55,
        "low": [110.0]*55, "close": [111.0]*55, "volume": [1000]*55},
        index=pd.Index(idx, name="date"))
    pattern = [
        [112,113,110,111], [111,112,109,110], [110,111,108,109],
        [109,110,107,108], [108,109,106,107], [107,108,99,100],
        [99,101,98,100], [100,105,99,104]]
    for i, row in enumerate(pattern):
        df.loc[df.index[35+i], ["open", "high", "low", "close"]] = row
    df["execution_open"] = df["open"]
    return df

def configs(path, enabled=False):
    path.mkdir(parents=True)
    (path/"markets.yaml").write_text("markets:\n  tw:\n    timezone: Asia/Taipei\n    symbols: [2330.TW]\n")
    (path/"strategies.yaml").write_text(
        "strategies:\n  - id: sakata_three_soldiers\n    enabled: true\n    params: {}\n"
        f"  - id: sakata_morning_star\n    enabled: {str(enabled).lower()}\n    params: {{}}\n")
    (path/"backtest.yaml").write_text("backtest:\n  trials: 3\n")

class Provider:
    source = "synthetic_fixture"
    def load(self, symbol, period="1y"):
        return make_data()

def test_study_is_isolated_and_snapshot_parity_verified(tmp_path):
    cfg = tmp_path/"config"
    configs(cfg)
    result = run_study("tw", "1y", tmp_path/"out", cfg, Provider(),
        datetime(2026, 11, 17, tzinfo=timezone.utc), strict_freshness=False)
    assert result["symbols_scanned"] == 1
    assert result["same_snapshot_hashes_verified"]
    assert result["all_historical_observations"] >= 1
    assert result["closed_simulated_trades"] >= 1
    assert not list((tmp_path/"out").rglob("*.csv"))
    assert result["final_session_signals"] == 0
    assert json.loads((tmp_path/"out/study.json").read_text())["strategy_id"] == "sakata_morning_star"
    assert "enabled: false" in (cfg/"strategies.yaml").read_text()

def test_fails_if_production_strategy_is_enabled(tmp_path):
    cfg = tmp_path/"config"
    configs(cfg, enabled=True)
    with pytest.raises(ValueError, match="enabled in production"):
        research_config(cfg, tmp_path/"alternate")

def test_hash_mismatch_is_rejected():
    backtest = {"strategies": [{"id":"sakata_morning_star","version":"0.1.0","params":{}}],
        "requested":1,"scanned":1,"error_count":0,"strict_freshness":False}
    scan = {"strategies":[{"id":"sakata_morning_star","version":"0.1.0","params":{}}],
        "requested_symbols":1,"scanned_symbols":1,"error_count":0,
        "strict_freshness":False,"matching_signals":0}
    rows=[{"market":"tw","symbol":"2330.TW","input_sha256":"a","last_date":"2026-10-16"}]
    quality={"symbols":[{"market":"tw","symbol":"2330.TW","input_sha256":"b","last_date":"2026-10-16"}]}
    with pytest.raises(ValueError, match="different OHLCV hashes"):
        verify(backtest,scan,rows,quality,[],{"params":{}},"tw")
