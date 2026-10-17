import pandas as pd
import pytest
from market_research.strategies import get_strategy
from market_research.validation import DataQualityError

RISING = [
 [100,101,99,100],[100,102,99,101],[101,103,100,102],
 [102,104,101,103],[103,105,102,104],
 [104,111,103,110],
 [109,110,107,108],[108,109,106,107],[107,108,105,106],
 [108,113,107,112],
]

def candles(rows):
    return pd.DataFrame(rows, columns=["open","high","low","close"],
                        index=pd.Index(pd.bdate_range("2026-08-03",periods=len(rows)).date,name="date")).assign(volume=1000)

def inverted(rows):
    return [[220-o,220-l,220-h,220-c] for o,h,l,c in rows]

@pytest.mark.parametrize("name,rows", [
 ("sakata_rising_three_methods",RISING),
 ("sakata_falling_three_methods",inverted(RISING)),
])
def test_positive_and_no_lookahead(name,rows):
    s=get_strategy(name)
    df=candles(rows)
    assert s.scan("tw","TEST.TW",df,{}).matched
    assert not s.scan("tw","TEST.TW",df.iloc[:-1],{}).matched
    assert s.scan("tw","TEST.TW",df,{})==s.scan("tw","TEST.TW",df,{})

@pytest.mark.parametrize("name,rows", [
 ("sakata_rising_three_methods",RISING),
 ("sakata_falling_three_methods",inverted(RISING)),
])
def test_boundaries_invalid_data_and_flat_candles(name,rows):
    s=get_strategy(name)
    df=candles(rows)
    broken=df.copy()
    broken.iloc[-1,broken.columns.get_loc("close")]=broken.iloc[-5]["close"]
    assert not s.scan("us","TEST",broken,{}).matched
    outside=df.copy()
    outside.iloc[-3,outside.columns.get_loc("high")]=outside.iloc[-5]["high"]+1
    assert not s.scan("us","TEST",outside,{}).matched
    invalid=df.copy()
    invalid.iloc[-1,invalid.columns.get_loc("high")]=1
    with pytest.raises(DataQualityError):
        s.scan("us","TEST",invalid,{})
    flat=df.copy()
    flat.loc[flat.index[-1],["open","high","low","close"]]=100
    assert not s.scan("us","TEST",flat,{}).matched

@pytest.mark.parametrize("params",[{"prior_trend_bars":1},{"prior_trend_bars":2.1},{"impulse_body_to_range_min":0},{"final_body_to_range_min":float("nan")},{"unknown":2}])
def test_invalid_parameters(params):
    with pytest.raises(ValueError):
        get_strategy("sakata_rising_three_methods").scan("tw","TEST",candles(RISING),params)
