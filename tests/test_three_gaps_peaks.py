from datetime import date
import pandas as pd
import pytest
from market_research.strategies import get_strategy
from market_research.validation import DataQualityError

def frame(rows, start="2026-09-01"):
    return pd.DataFrame(rows,columns=["open","high","low","close"],
        index=pd.Index(pd.bdate_range(start,periods=len(rows)).date,name="date")).assign(volume=1000)

def three_gaps_rows(up=True):
    vals=[]
    for i in range(5):
        base=100+i*1.2 if up else 120-i*1.2
        vals.append([base,base+1,base-1,base])
    for low,high in ([(109,112),(115,118),(121,124),(127,130)] if up else
                      [(105,108),(99,102),(93,96),(87,90)]):
        vals.append([low+1,high,low,low+2])
    return vals

def test_us_adjusted_full_gap_up_and_down():
    for suffix,up in (("up",True),("down",False)):
        s=get_strategy("sakata_three_gaps_"+suffix)
        df=frame(three_gaps_rows(up))
        # Weekday-only BDays; no US holidays in Sep 1-11 2026.
        result=s.scan("us","TEST",df,{})
        assert result.matched,result.metrics
        assert result.metrics["observation"]=="adjusted_price_window_only"
        assert not s.scan("us","TEST",df.iloc[:-1],{}).matched

def test_tw_gaps_refuse_unadjusted_corporate_action_prices():
    df=frame(three_gaps_rows(True))
    report=get_strategy("sakata_three_gaps_up").scan("tw","2330.TW",df,{})
    assert not report.matched
    assert report.metrics["observation"]=="corporate_actions_unverified"

def test_gaps_cannot_accept_missing_exchange_session():
    df=frame(three_gaps_rows(True))
    # Remove a trading session inside the four gap bars, while retaining 9 rows.
    df.index=pd.Index([*df.index[:-1],date(2026,9,14)],name="date")
    assert not get_strategy("sakata_three_gaps_up").scan("us","TEST",df,{}).matched

def test_gaps_fail_closed_on_invalid_prices():
    df=frame(three_gaps_rows(True))
    df.loc[df.index[-1],"high"]=1
    with pytest.raises(DataQualityError):
        get_strategy("sakata_three_gaps_up").scan("us","TEST",df,{})

def test_peaks_not_enough_bars_or_invalid_data():
    for name in ("sakata_three_mountains_triple_top",
                 "sakata_three_mountains_head_shoulders"):
        s=get_strategy(name)
        df=frame([[100,101,99,100]]*10)
        assert s.scan("tw","TEST",df,{}).metrics["observation"]=="insufficient_history"
        df=frame([[100,101,99,100]]*35)
        df.iloc[-1,df.columns.get_loc("close")]=-1
        with pytest.raises(DataQualityError):
            s.scan("tw","TEST",df,{})

def test_invalid_parameters_fail_closed():
    with pytest.raises(ValueError):
        get_strategy("sakata_three_gaps_up").scan("us","TEST",frame(three_gaps_rows()),{"prior_trend_bars":2.5})
    with pytest.raises(ValueError):
        get_strategy("sakata_three_mountains_triple_top").scan("tw","TEST",frame([[100,101,99,100]]*35),{"pivot_side_bars":0})

def test_only_red_soldiers_live():
    import yaml
    from pathlib import Path
    cfg=yaml.safe_load((Path(__file__).resolve().parents[1]/"config/strategies.yaml").read_text())
    assert [x["id"] for x in cfg["strategies"] if x["enabled"]]==["sakata_three_soldiers"]


def peaks_fixture(head=False):
    # Local highs at indices 12, 20, 28; their two-bar right-side
    # confirmations are known before the neckline break on index 35.
    close = [97+i*1.5 for i in range(12)] + [105.0]*24
    heights = [106.0]*36
    for i, value in ((12,118.),(20,125. if head else 119.),(28,118.5)):
        heights[i] = value
    lows = [v-2 for v in close]
    for i in (16,24):
        lows[i]=95.0
    close[34]=105.0
    close[35]=92.0
    highs=[max(h,c+1) for h,c in zip(heights,close)]
    opens=[c+0.3 for c in close]
    return frame(list(zip(opens,highs,lows,close)))


@pytest.mark.parametrize("strategy_id,head",[
    ("sakata_three_mountains_triple_top",False),
    ("sakata_three_mountains_head_shoulders",True),
])
def test_confirmed_three_peaks_only_on_breakout(strategy_id,head):
    s=get_strategy(strategy_id)
    df=peaks_fixture(head)
    assert not s.scan("us","TEST",df.iloc[:-1],{}).matched
    result=s.scan("us","TEST",df,{})
    assert result.matched,result.metrics
    assert result.metrics["breakout_confirmation_date"]==str(df.index[-1])
    assert result.metrics["third_pivot_confirmed"]!=str(df.index[-1])
