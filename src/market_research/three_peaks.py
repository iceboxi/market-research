"""Three confirmed swing highs with neckline break on the current close."""
import math
import numpy as np
import pandas as pd
from .strategy_contract import ScreenResult
from .validation import DataQualityError

class ThreePeaks:
    id = None
    shape = None
    version = "0.1.0"
    DEFAULTS = {"pivot_side_bars":2,"prior_trend_bars":5,
        "prior_rise_min_pct":2.0,"peak_tolerance_pct":5.0,
        "min_peak_separation_bars":3,"max_pattern_bars":90,
        "neckline_break_min_pct":0.2}

    def scan(self,market,symbol,data,params):
        cfg={**self.DEFAULTS,**params}
        if set(params)-self.DEFAULTS.keys():
            raise ValueError("Unknown peaks parameter")
        for key in ("pivot_side_bars","prior_trend_bars","min_peak_separation_bars","max_pattern_bars"):
            if type(cfg[key]) is not int or not 1<=cfg[key]<=365:
                raise ValueError("Invalid integer parameter")
        if cfg["prior_trend_bars"]<2 or cfg["max_pattern_bars"]<3*cfg["pivot_side_bars"]+4:
            raise ValueError("Invalid history limits")
        for key in ("prior_rise_min_pct","peak_tolerance_pct","neckline_break_min_pct"):
            v=cfg[key]
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=100:
                raise ValueError("Invalid percent parameter")
        if data.empty:
            raise ValueError("Empty candles")
        date=str(data.index[-1])
        n=cfg["prior_trend_bars"]+3*(2*cfg["pivot_side_bars"]+1)+2
        if len(data)<n:
            return ScreenResult(market,symbol,self.id,self.version,date,False,
                {"observation":"insufficient_history","required_bars":n},"Not enough completed bars")
        keys=["open","high","low","close"]
        if not set(keys).issubset(data.columns):
            raise DataQualityError("Missing OHLC")
        p=data[keys].apply(pd.to_numeric,errors="coerce")
        arr=p.to_numpy(dtype=float)
        if not np.isfinite(arr).all() or (arr<=0).any() or ((p.high<p[["open","low","close"]].max(axis=1))|(p.low>p[["open","high","close"]].min(axis=1))).any():
            raise DataQualityError("Invalid OHLC")
        side=cfg["pivot_side_bars"]
        highs=p.high.to_numpy(dtype=float)
        lows=p.low.to_numpy(dtype=float)
        close=p.close.to_numpy(dtype=float)
        pivots=[i for i in range(side,len(p)-side) if
            (highs[i]>highs[i-side:i]).all() and
            (highs[i]>highs[i+1:i+side+1]).all()]
        result=None
        end=len(p)-1
        for x in range(len(pivots)-1,1,-1):
            k=pivots[x]
            if end-k>cfg["max_pattern_bars"] or end<=k+side:
                continue
            for y in range(x-1,0,-1):
                j=pivots[y]
                if k-j<cfg["min_peak_separation_bars"]:
                    continue
                for z in range(y-1,-1,-1):
                    i=pivots[z]
                    if j-i<cfg["min_peak_separation_bars"] or k-i>cfg["max_pattern_bars"] or i<cfg["prior_trend_bars"]:
                        continue
                    trend=close[i-cfg["prior_trend_bars"]:i]
                    if (trend[-1]-trend[0])/trend[0]*100<cfg["prior_rise_min_pct"]:
                        continue
                    peaks=[highs[i],highs[j],highs[k]]
                    tol=cfg["peak_tolerance_pct"]/100
                    if self.shape=="triple":
                        good=(max(peaks)-min(peaks))/max(peaks)<=tol
                    else:
                        good=(peaks[1]>max(peaks[0],peaks[2])*(1+tol/2) and abs(peaks[0]-peaks[2])/max(peaks[0],peaks[2])<=tol)
                    if not good:
                        continue
                    neckline=min(float(lows[i+1:j].min()),float(lows[j+1:k].min()))
                    cutoff=neckline*(1-cfg["neckline_break_min_pct"]/100)
                    if close[end]<cutoff and close[end-1]>=cutoff and not np.any(close[k+side:end]<cutoff):
                        result=(i,j,k,neckline)
                        break
                if result: break
            if result: break
        metrics={"observation":"confirmed_neckline_break" if result else "no_confirmed_break"}
        if result:
            i,j,k,line=result
            metrics.update({"pivot_dates":[str(data.index[t]) for t in (i,j,k)],
                "third_pivot_confirmed":str(data.index[k+side]),
                "breakout_confirmation_date":date,"neckline":round(line,6)})
        return ScreenResult(market,symbol,self.id,self.version,date,bool(result),metrics,
            "Confirmed bearish neckline observation, no short or execution order")

class SakataTripleTop(ThreePeaks):
    id="sakata_three_mountains_triple_top"
    shape="triple"

class SakataHeadShoulders(ThreePeaks):
    id="sakata_three_mountains_head_shoulders"
    shape="head_shoulders"
