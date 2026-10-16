import pandas as pd
import pytest
from random import Random

from market_research.backtest import Settings, backtest_symbol, costs, random_entries, equity_curve
from market_research.strategies import ScreenResult


def candles(n=65):
    opens=[100.0 + x for x in range(n)]
    dates=pd.bdate_range("2026-06-01",periods=n).date
    return pd.DataFrame({"open":opens,"high":[x+3 for x in opens],
                         "low":[x-3 for x in opens],"close":[x+1 for x in opens],
                         "volume":[1000]*n}, index=pd.Index(dates,name="date"))


class FixedSignals:
    id="fixed_signal"
    version="test"
    def __init__(self, indices=(29,30,40)):
        self.indices=set(indices)
        self.calls=[]
    def scan(self,market,symbol,history,params):
        self.calls.append(len(history))
        return ScreenResult(market,symbol,self.id,self.version,str(history.index[-1]),
                            len(history)-1 in self.indices,{},"synthetic")


def test_next_open_costs_and_nonoverlap():
    df=candles()
    strategy=FixedSignals()
    cfg=Settings(trials=8)
    out,trades=backtest_symbol(df,"tw","TEST.TW",strategy,{},cfg)
    assert out["closed_trades"] == 2
    assert out["skipped_overlapping_signals"] == 1
    assert trades[0]["signal_date"] == str(df.index[29])
    assert trades[0]["entry_date"] == str(df.index[30])
    assert trades[0]["exit_date"] == str(df.index[35])
    assert trades[0]["net_return_pct"] == pytest.approx(
        ((df["open"].iloc[35]/df["open"].iloc[30]) *
         (1-0.0045)/(1+0.0015)-1)*100)
    assert max(strategy.calls) <= len(df)-cfg.hold_bars-1


def test_no_signal_no_random_or_win_rate():
    out,trades=backtest_symbol(candles(),"us","TEST",FixedSignals(()),{},
                               Settings(trials=8))
    assert trades == []
    assert out["win_rate_pct"] is None
    assert out["random_median_net_return_pct"] is None


def test_seed_and_random_positions():
    a=random_entries(30,75,6,5,Random(12))
    b=random_entries(30,75,6,5,Random(12))
    assert a == b
    assert all(y-x>=5 for x,y in zip(a,a[1:]))
    s1,_=backtest_symbol(candles(),"us","TEST",FixedSignals(),{},Settings(trials=8))
    s2,_=backtest_symbol(candles(),"us","TEST",FixedSignals(),{},Settings(trials=8))
    assert s1["random_median_net_return_pct"] == s2["random_median_net_return_pct"]


def test_equity_mark_to_market():
    vals=equity_curve([100,120,80,110,110,110], [0], 0, 4, 0, 0)
    assert vals[-1] == pytest.approx(1.1)
    assert min(vals) == pytest.approx(0.8)


def test_invalid_settings_and_small_history():
    with pytest.raises(ValueError):
        Settings(hold_bars=0).validate()
    with pytest.raises(ValueError):
        Settings(trials=0).validate()
    with pytest.raises(ValueError,match="insufficient"):
        backtest_symbol(candles(15),"us","TEST",FixedSignals(),{},Settings())


def test_us_signal_uses_adjusted_prices_but_fill_uses_quote_open():
    df = candles(65)
    df["execution_open"] = df["open"] * 1.2
    cfg = Settings(trials=3)
    summary, trades = backtest_symbol(df, "us", "TEST", FixedSignals((29,)), {}, cfg)
    assert summary["execution_open_field"] == "execution_open"
    assert trades[0]["entry_open"] == pytest.approx(df["execution_open"].iloc[30])
    assert trades[0]["entry_open"] != df["open"].iloc[30]
    assert summary["return_convention"] == "price_only_excludes_dividend_cashflows"


def test_tw_source_has_explicit_unadjusted_execution_open():
    from market_research.market_data import load_daily_bars
    from datetime import datetime, timezone
    class TW:
        source = "twse_stock_day_official_raw_ohlcv"
        def load(self, symbol, period):
            return candles()
    daily = load_daily_bars(TW(), "tw", "2330.TW", "1y",
        datetime(2026, 11, 16, tzinfo=timezone.utc), "Asia/Taipei")
    assert "execution_open" in daily.frame
    assert daily.metadata["dividend_cashflows_included"] is False
    assert daily.metadata["execution_price_basis"] == "twse_raw_open_proxy_not_guaranteed_fill"


def test_us_production_source_rejects_missing_execution_price_proxy():
    from market_research.market_data import load_daily_bars
    from datetime import datetime, timezone
    class US:
        source = "yahoo_finance_via_yfinance"
        def load(self, symbol, period):
            return candles()
    with pytest.raises(ValueError, match="missing unadjusted-for-dividends"):
        load_daily_bars(US(), "us", "TEST", "1y",
                        datetime(2026, 11, 16, tzinfo=timezone.utc),
                        "America/New_York")
