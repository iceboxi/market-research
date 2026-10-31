from datetime import date, datetime, timezone
import json
import pandas as pd
import pytest
from market_research.indicators import rsi_wilder, relative_volume
from market_research.strategies import get_strategy
from market_research.runner import run_scan
from market_research.validation import validate_daily, DataQualityError
from market_research.twse import twse_close_check, parse_twse_roc_date, parse_stock_day, TwseDailyProvider
from market_research.provider import RoutedDailyProvider


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
            return {"stat":"OK","fields":["日期","成交股數","開盤價","最高價","最低價","收盤價"],"data":[["115/10/16","2,000,000","1,190","1,210","1,180","1,200"]]}
    def get(url, **kwargs):
        return Response()
    assert twse_close_check("2330.TW",date(2026,10,16),1200,2000000,get=get)["status"] == "verified"

def test_twse_period_parse_and_units():
    payload = {"stat":"OK",
        "fields":["日期","成交股數","成交金額","開盤價","最高價","最低價","收盤價","漲跌價差","成交筆數","註記"],
        "data":[["115/10/15","58,486,711","100","2,400.00","2,450.00","2,390.00","2,440.00","0","123",""],
                ["115/10/16","0","0","--","--","--","--","--","0",""]]}
    parsed = parse_stock_day(payload, "2330.TW")
    assert len(parsed) == 1
    assert parsed.iloc[0]["volume"] == 58486711
    assert parsed.iloc[0]["close"] == 2440.0


def test_official_monthly_history_and_router():
    from datetime import date
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"stat":"OK",
                    "fields":["日期","成交股數","開盤價","最高價","最低價","收盤價"],
                    "data":[["115/10/15","1,234,567","20.00","21.00","19.00","20.50"]]}
    requests = []
    def fake_get(url, **kwargs):
        month = kwargs["params"]["date"]
        requests.append(month)
        class MonthlyResponse:
            def raise_for_status(self):
                pass
            def json(self):
                y = int(month[:4]) - 1911
                mm = int(month[4:6])
                return {"stat":"OK",
                        "fields":["日期","成交股數","開盤價","最高價","最低價","收盤價"],
                        "data":[[f"{y}/{mm:02d}/15","1,234,567","20.00","21.00","19.00","20.50"]]}
        return MonthlyResponse()
    twse = TwseDailyProvider(get=fake_get, today=date(2026,10,17),
                             request_pause_seconds=0)
    df = twse.load("2330.TW", "3mo")
    assert len(requests) == 4
    assert len(df) == 4
    assert df["volume"].iloc[-1] == 1234567
    assert df.index.is_monotonic_increasing
    class FakeUs:
        source = "test_us"
        def load(self, symbol, period="1y"):
            return fake_frame()
    router = RoutedDailyProvider(taiwan=twse, united_states=FakeUs())
    assert router.provider_for("2330.TW").source == twse.source
    assert router.provider_for("AAPL").source == "test_us"


def test_yahoo_adjusted_ohlc_preserves_reported_volume():
    from market_research.provider import YahooDailyProvider
    class Ticker:
        def history(self, **kwargs):
            return pd.DataFrame({
                "Open": [99.0, 102.0], "High": [103.0, 106.0],
                "Low": [97.0, 101.0], "Close": [100.0, 105.0],
                "Adj Close": [95.0, 105.0], "Volume": [1000, 1200],
            }, index=pd.date_range("2026-10-14", periods=2))
    provider = YahooDailyProvider(ticker_factory=lambda symbol: Ticker())
    df = provider.load("AAPL")
    assert df["open"].iloc[0] == pytest.approx(94.05)
    assert df["close"].iloc[0] == pytest.approx(95.0)
    assert df["volume"].tolist() == [1000, 1200]
    assert df["execution_open"].tolist() == pytest.approx([99., 102.])


def test_yahoo_missing_adjusted_close_is_rejected():
    from market_research.provider import YahooDailyProvider
    class Ticker:
        def history(self, **kwargs):
            return pd.DataFrame({
                "Open": [99.0], "High": [103.0], "Low": [97.0],
                "Close": [100.0], "Adj Close": [float("nan")],
                "Volume": [1000],
            }, index=pd.date_range("2026-10-14", periods=1))
    with pytest.raises(ValueError, match="adjusted close"):
        YahooDailyProvider(ticker_factory=lambda symbol: Ticker()).load("AAPL")


def three_soldiers_frame():
    dates = pd.bdate_range("2026-10-05", periods=8).date
    return pd.DataFrame({
        "open": [110.5,108.5,106.5,104.5,102.5,101,103,106],
        "high": [111,109,107,105,103,104.4,107.5,110.5],
        "low": [109,107,105,103,101,100.5,102.5,105.5],
        "close": [110,108,106,104,102,104,107,110],
        "volume": [1000]*8,
    }, index=pd.Index(dates, name="date"))


def test_sakata_three_soldiers_positive_and_negatives():
    s = get_strategy("sakata_three_soldiers")
    p = {"prior_trend_bars": 5, "prior_decline_min_pct": 2.0,
         "min_body_to_range": 0.5, "max_upper_shadow_to_range": 0.25}
    df = three_soldiers_frame()
    assert s.scan("tw", "2330.TW", df, p).matched
    broken_close = df.copy()
    broken_close.iloc[-1, broken_close.columns.get_loc("close")] = 105.
    assert not s.scan("tw", "2330.TW", broken_close, p).matched
    long_wick = df.copy()
    long_wick.iloc[-1, long_wick.columns.get_loc("high")] = 118.
    assert not s.scan("tw", "2330.TW", long_wick, p).matched
    no_decline = df.copy()
    no_decline.iloc[:5, no_decline.columns.get_loc("close")] = [102,103,104,105,106]
    assert not s.scan("tw", "2330.TW", no_decline, p).matched


def test_sakata_rejects_invalid_params_and_short_history():
    s = get_strategy("sakata_three_soldiers")
    assert not s.scan("us", "AAPL", three_soldiers_frame().iloc[-5:], {}).matched
    with pytest.raises(ValueError, match="prior_trend_bars"):
        s.scan("us", "AAPL", three_soldiers_frame(), {"prior_trend_bars": 1})
    with pytest.raises(ValueError, match="proportions"):
        s.scan("us", "AAPL", three_soldiers_frame(), {"min_body_to_range": 0.0})


def test_production_scan_enables_no_pattern_strategy():
    from pathlib import Path
    import yaml
    config = yaml.safe_load((Path(__file__).resolve().parents[1] /
                             "config/strategies.yaml").read_text())
    assert [x["id"] for x in config["strategies"] if x["enabled"]] == []  # #117


@pytest.mark.parametrize("error", [
    "ReadTimeout",
    "RemoteProtocolError",  # server dropped a kept-alive connection (#155)
])
def test_twse_retries_transient_failure_without_losing_month(error):
    import httpx
    calls = []
    class Response:
        def __init__(self, month): self.month = month
        def raise_for_status(self): pass
        def json(self):
            year = int(self.month[:4])-1911
            month = int(self.month[4:6])
            return {"stat":"OK","fields":["日期","成交股數","開盤價","最高價","最低價","收盤價"],
                    "data":[[f"{year}/{month:02d}/15","1000","20","21","19","20"]]}
    def flaky(url, **kwargs):
        month = kwargs["params"]["date"]
        calls.append(month)
        if len(calls) == 1:
            raise getattr(httpx, error)("temporary TWSE failure")
        return Response(month)
    provider = TwseDailyProvider(get=flaky, today=date(2026,10,17),
                                  request_pause_seconds=0, timeout_retries=2)
    result = provider.load("2330.TW", "3mo")
    assert len(result) == 4
    assert len(calls) == 5  # first month twice; remaining three months once


def test_twse_fails_closed_when_the_server_keeps_disconnecting(monkeypatch):
    import httpx
    sleeps, calls = [], []
    monkeypatch.setattr("market_research.twse.time.sleep", sleeps.append)
    def dropped(url, **kwargs):
        calls.append(kwargs["params"]["date"])
        raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
    provider = TwseDailyProvider(get=dropped, today=date(2026,10,17),
                                  request_pause_seconds=0, timeout_retries=2)
    with pytest.raises(ValueError, match="TWSE 2330.TW: failed months: 2026-07-01: "
                                         "Server disconnected without sending a response."):
        provider.load("2330.TW", "3mo")
    assert calls[:3] == ["20260701"] * 3 and len(calls) == 12  # 3 attempts per month
    assert sleeps == [1, 2] * 4


def test_twse_does_not_retry_invalid_official_payload():
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"stat": "Unexpected format"}
    calls = []
    def bad(url, **kwargs):
        calls.append(1)
        return Response()
    provider = TwseDailyProvider(get=bad, today=date(2026,10,17),
                                  request_pause_seconds=0, timeout_retries=2)
    with pytest.raises(ValueError, match="failed months"):
        provider.load("2330.TW", "3mo")
    assert len(calls) == 4
