from datetime import date, datetime, timezone
import json
import pandas as pd
import pytest
from market_research.indicators import rsi_wilder, relative_volume
from market_research.strategies import get_strategy
from market_research.runner import run_scan
from market_research.validation import validate_daily, DataQualityError
from market_research.twse import twse_close_check, parse_twse_roc_date


def fake_frame():
    closes = [200.0-i for i in range(31)]
    idx = pd.bdate_range("2026-08-03", periods=31).date
    return pd.DataFrame({"open": closes, "high": [v+1 for v in closes],
        "low": [v-1 for v in closes], "close": closes,
        "volume": [100]*30+[350]}, index=pd.Index(idx, name="date"))


class FakeProvider:
    source = "unit_test_synthetic_only"
    def load(self, symbol, period="1y"):
        if symbol == "FAIL":
            raise ConnectionError("test outage")
        return fake_frame()


def test_indicators():
    assert rsi_wilder(pd.Series([100]*31)) == pytest.approx(50)
    assert rsi_wilder(pd.Series(range(31))) == pytest.approx(100)
    assert rsi_wilder(pd.Series(range(31, 0, -1))) == pytest.approx(0)
    assert relative_volume(pd.Series([100]*20 + [300])) == pytest.approx(3)
    assert relative_volume(pd.Series([0]*20 + [300])) is None


def test_strategy():
    result = get_strategy("rsi_volume").scan("tw", "2330.TW", fake_frame(),
        {"rsi_period":14, "rsi_max":30, "volume_window":20, "volume_ratio_min":2})
    assert result.matched
    assert get_strategy("ma_breakout").id == "ma_breakout"


def test_validation():
    assert validate_daily(fake_frame(), "2330.TW")["status"] == "valid"
    df = fake_frame()
    df.iloc[-1, df.columns.get_loc("close")] = -1
    with pytest.raises(DataQualityError):
        validate_daily(df, "2330.TW")


def test_execution_and_failure(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg/"markets.yaml").write_text("markets:\n  tw:\n    timezone: Asia/Taipei\n    symbols:\n      - 2330.TW\n      - FAIL\n")
    (cfg/"strategies.yaml").write_text("strategies:\n  - id: rsi_volume\n    enabled: true\n    params:\n      volume_window: 20\n")
    result = run_scan("tw", out=tmp_path/"out", config_dir=cfg, provider=FakeProvider(),
                      now=datetime(2026,10,16,tzinfo=timezone.utc))
    assert result["matching_signals"] == 1
    assert result["error_count"] == 1
    assert json.loads((tmp_path/"out"/"signals.json").read_text())[0]["symbol"] == "2330.TW"


def test_twse():
    assert parse_twse_roc_date("115/10/16") == date(2026,10,16)
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"stat":"OK","fields":["日期","收盤價","成交股數"],"data":[["115/10/16","1,200","2,000,000"]]}
    def get(url, **kwargs):
        return Response()
    assert twse_close_check("2330.TW",date(2026,10,16),1200,2000000,get=get)["status"] == "verified"
