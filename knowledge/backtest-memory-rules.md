# 記憶體規則回測：南亞科 2010–2026

最後更新：2026-11-06｜標的：2408 南亞科｜規則版本：[README](README.md#固定標準)「固定標準」（2026-11-05，含同日更正）

非買賣建議。

## 結論

**這套規則沒有通過景氣循環的驗證。**

- 「考慮買進」之後的 12 個月平均報酬 +12.7%（中位數 +9.5%），低於全部月份的平均 +52.0%（中位數 +11.2%）。
- 2018-05 的高點（月底收盤 99.6）規則給「考慮買進」。2024-12 到現在連續 24 個月都是「觀望」，期間月底收盤從 29.25 漲到 543.0。
- 「避開」條件在三次大谷底（2015-07、2020-08、2022-09）都有亮起。避開之後 12 個月平均反而有 +33.2%，上漲機率 75%，等於在谷底叫人離場。

失敗的原因是結構性的，不是調參數就能解決（見「診斷」）。所以 2026-11-05 的判斷（南亞科、華邦電觀望，群聯避開）只是依規則算出的結果，不能當成有驗證根據的判斷。

## 方法

- **評估時點**：每月最後一個交易日評估一次，從 2010-09 到 2026-10，再加上 2026-11-05，共 195 次。從 2010-09 開始，是因為 PBR 資料從 2005-09 才有，五年百分位要先累積五年。
- **只用當時已經公布的資料**（no-lookahead）：
  - 月營收：次月 10 日之後才可以用。
  - 季報：依法定期限，Q1 為 5/15、Q2 為 8/14、Q3 為 11/14、Q4 為隔年 3/31。實際公布通常更早，所以這是保守的做法。
  - PBR：證交所每天公布，當天可以用。
- **規則**：照 README 的固定標準計算 Bull／Base／Bear、報酬風險比和避開條件。每股淨值用「收盤 ÷ PBR」，和 pipeline 相同。五年 P50／P80 用線性內插，和 pipeline 的 `numpy.percentile` 相同。檢查：2026-11-05 的 P80 倍數算出 2.69，pipeline 11/04 是 2.684。
- **回測不到的條件**：
  - 「合約價由漲轉跌」：沒有免費的歷史資料。
  - 「營業現金流＋存貨」：FinMind 的資產負債表和現金流量表從 2013 年才有，所以只能從那時開始算。
- **報酬**：FinMind 的還原股價要付費，所以用原始股價自己還原：加回現金股利，並處理 2014-09-09 的 10:1 減資，算成總報酬指數。策略比較時每次切換扣 0.3%，沒有計算其他成本。

## 結果

### 依判斷分組

資料期間 2010-09 到 2025-10，共 182 個月有完整的 12 個月後報酬。

| 判斷 | 月數 | 12 個月後平均 | 中位數 | 上漲機率 | 12 個月內平均最大回落 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 全部 | 182 | +52.0% | +11.2% | 58% | −42.7% |
| 考慮買進 | 66 | +12.7% | +9.5% | 58% | −36.4% |
| 觀望 | 68 | +103.4% | −11.0% | 46% | −53.1% |
| 避開 | 48 | +33.2% | +29.3% | 75% | −36.8% |

- 觀望的平均被 2025–2026 年的大漲拉高，中位數其實是 −11.0%。
- 如果只看下個月：避開之後平均 −0.27%，全部月份是 +2.17%。所以避開條件短期內確實躲掉了一些弱勢，但拉長到 12 個月反而比較好。

### 簡單策略

每月依判斷調整，每次切換扣 0.3%，期間 2010-09 到 2026-11：

| 策略 | 終值 | 年化 | 最大回落 | 切換次數 |
| --- | ---: | ---: | ---: | ---: |
| 買進持有 | 2.67 倍 | +6.3% | −93.9% | — |
| 只在「考慮買進」時持有 | 1.34 倍 | +1.8% | −47.1% | 24 |
| 「避開」時空手，其他時間持有 | 5.00 倍 | +10.5% | −91.5% | 39 |

「避開時空手」的終值較高，但最大回落還是 −91.5%：2010–2012 年的崩跌一樣沒躲掉。

### 主要高低點時的判斷

高低點的定義是：前後 12 個月內，總報酬指數的最高點或最低點。2014-09 以前是減資前的股價。

| 月底 | 高／低 | 收盤 | PBR 百分位 | 最新一季 EPS | 判斷 |
| --- | --- | ---: | ---: | ---: | --- |
| 2010-09 | 高 | 21.15 | P85 | −0.31 | 觀望 |
| 2012-11 | 低 | 1.30 | P82 | −0.64 | 觀望 |
| 2013-04 | 高 | 6.50 | P100 | −0.45 | 避開 |
| 2014-05 | 高 | 8.29 | P82 | 0.26 | 觀望 |
| 2015-07 | 低 | 34.25 | P21 | 2.61 | **避開** |
| 2018-05 | 高 | 99.60 | P49 | 2.39 | **考慮買進** |
| 2018-10 | 低 | 51.40 | P2 | 3.68 | 考慮買進 |
| 2020-08 | 低 | 51.90 | P3 | 1.05 | **避開** |
| 2021-02 | 高 | 96.50 | P83 | 0.53 | 觀望 |
| 2022-09 | 低 | 48.95 | P2 | 2.12 | **避開** |
| 2023-12 | 高 | 78.00 | P71 | −0.81 | 觀望 |
| 2024-12 | 低 | 29.25 | P0 | −0.48 | 觀望 |
| 2026-08 | 高 | 543.00 | P96 | 14.66 | 觀望 |

六次低點中，只有 2018-10 給出「考慮買進」，三次給「避開」。七次高點中，2018-05 給了「考慮買進」。

## 診斷：為什麼失敗

**1. 景氣循環股不適合用最新一季的 EPS。**

- 谷底時 EPS 是負的，Base（最新一季 × 2）反而比 Bear（零獲利）還差，報酬風險比變成負數。結果規則永遠不會在虧損的谷底給出「考慮買進」，2012 年和 2024 年都是這樣。195 次評估中有 64 次 EPS 為負。
- 復甦初期 EPS 還很小，股價卻已經漲了好幾倍。

**2. 報酬風險比實際上退化成「P/B 低於中位數，而且 EPS 為正」。** 66 次「考慮買進」中有 60 次，是因為股價已經低於 Bear 價值，下跌空間算出來是零。

**3. 虧損期會扭曲 P/B 百分位。**

- 虧損讓淨值縮水，P/B 反而變高：2012-11 谷底時 P/B 在 P82，看起來很貴。
- 這些高 P/B 留在五年視窗裡，又讓 2018-05 高點的 P/B 只有 P49，看起來不貴。
- 歷史分布分成兩群時，P80 會突然跳動。2021–2025 年的 P/B 偏低，2026 年偏高，所以 P80 倍數在 2026-09 底還是 1.59，到 10 月底就變成 2.60。

**4. 月營收連續 2 個月月減是落後訊號。** 營收還在下滑時，股價往往已經見底，所以三次大谷底規則都叫人避開。這是根據上面的結果推論的，還沒有用合約價資料驗證。

## 對目前判斷的影響

- [memory.md](memory.md) 2026-11-05 的判斷都來自這套規則。回測顯示，這套規則在南亞科上沒有擇時能力。
- 回測算出 2026-11-05 的報酬風險比是 0.18，memory.md 是 0.44，原因是用的 EPS 不同：回測依法定期限，只能用 Q2 的 EPS 14.66；memory.md 用的是已經提早公布的 Q3 EPS 25.40。

## 建議修改（待討論，還沒改）

1. **Base 和 Bear 改用整個循環的獲利，不用最新一季。** 例如 Base 用過去 5 年的平均季 EPS，Bear 允許虧損，用過去 5 年最差的連續 4 季。
2. **避開條件改用領先訊號**，例如合約價方向或庫存，不再用月營收月減。
3. **低 P/B 要加上「淨值沒有被虧損侵蝕」的條件**，避開 2010–2012 那種價值陷阱：當時虧損讓淨值一路縮水，最後在 2014 年 10:1 減資彌補虧損。
4. **先在南亞科重跑修改後的規則，再拿華邦電、群聯做樣本外驗證**，避免只對南亞科過度擬合。

## 限制

- 只有一檔股票，約 16 年，大概 4 次循環，樣本很小。
- 合約價條件沒辦法回測。
- 除了切換成本，沒有計算交易稅費、流動性，也沒有處理停牌日。
- 只用 FinMind 一個資料來源，沒有和證交所原始資料逐筆核對。

<details>
<summary>回測程式（Python 標準函式庫，資料是 FinMind 免費 API 下載的 JSON）</summary>

```python
"""No-lookahead backtest of knowledge/README.md fixed rules on one TW stock (FinMind free data).

Usage: python3 -I bt_rules.py <data_dir> <out_csv>
Availability rules (conservative, IFRS-era statutory deadlines):
  monthly revenue for month m -> 10th of month m+1
  quarter Q1/Q2/Q3/Q4 -> 05-15 / 08-14 / 11-14 / next 03-31
  daily PBR (TWSE) -> same day
"""
import csv, json, sys
from datetime import date, timedelta

D, OUT = sys.argv[1], sys.argv[2]
load = lambda n: json.load(open(f"{D}/{n}.json"))["data"]
P = lambda s: date.fromisoformat(s)

# --- prices: total-return index (cash dividends on ex-date, 2014-09-09 10:1 capital reduction) ---
px = [r for r in load("TaiwanStockPrice") if r["close"] > 0]
divs = {}
for r in load("TaiwanStockDividend"):
    if r["CashExDividendTradingDate"]:
        divs[P(r["CashExDividendTradingDate"])] = r["CashEarningsDistribution"]
REDUCTION = {date(2014, 9, 9): 10.0}
days, close, tri = [], [], []
idx = 1.0
for i, r in enumerate(px):
    d = P(r["date"]); c = r["close"]
    if i:
        prev = close[-1] * REDUCTION.get(d, 1.0)
        idx *= (c + divs.get(d, 0.0)) / prev
    days.append(d); close.append(c); tri.append(idx)
pos = {d: i for i, d in enumerate(days)}

pbr = {P(r["date"]): r["PBR"] for r in load("TaiwanStockPER") if r["PBR"] > 0}
pbr_days = sorted(pbr)

rev = {(r["revenue_year"], r["revenue_month"]): r["revenue"] for r in load("TaiwanStockMonthRevenue")}

def quarters(name, field):
    out = {}
    for r in load(name):
        if r["type"] == field:
            out[P(r["date"])] = r["value"]
    return out
eps_q = quarters("TaiwanStockFinancialStatements", "EPS")
inv_q = quarters("TaiwanStockBalanceSheet", "Inventories")
eq_q = quarters("TaiwanStockBalanceSheet", "EquityAttributableToOwnersOfParent")
ocf_ytd = quarters("TaiwanStockCashFlowsStatement", "CashFlowsFromOperatingActivities")

def available(qend):
    m = qend.month
    return {3: date(qend.year, 5, 15), 6: date(qend.year, 8, 14), 9: date(qend.year, 11, 14),
            12: date(qend.year + 1, 3, 31)}[m]

def latest_quarters(series, t, n):
    qs = sorted(q for q in series if available(q) <= t)
    return qs[-n:] if len(qs) >= n else None

def ocf_quarter(q):
    prev = {3: None, 6: date(q.year, 3, 31), 9: date(q.year, 6, 30), 12: date(q.year, 9, 30)}[q.month]
    if q not in ocf_ytd: return None
    if prev is None: return ocf_ytd[q]
    return None if prev not in ocf_ytd else ocf_ytd[q] - ocf_ytd[prev]

def pct(vals, q):  # numpy.percentile linear
    k = (len(vals) - 1) * q / 100; f = int(k); c = min(f + 1, len(vals) - 1)
    return vals[f] + (vals[c] - vals[f]) * (k - f)

def month_ends(start, end):
    out = {}
    for d in days:
        if start <= d <= end: out[(d.year, d.month)] = d
    return sorted(out.values())

rows = []
evals = month_ends(date(2010, 9, 1), date(2026, 10, 31)) + [date(2026, 11, 5)]
for t in evals:
    if t not in pbr: continue
    i = pos[t]; c = close[i]; b = pbr[t]
    window = sorted(v for d, v in pbr.items() if t - timedelta(days=5 * 365 + 1) <= d <= t)
    m20, m50, m80 = (pct(window, q) for q in (20, 50, 80))
    rank = sum(1 for v in window if v <= b) / len(window) * 100
    bv = c / b
    q = latest_quarters(eps_q, t, 1)
    eps = eps_q[q[0]] * (10.0 if q[0] < date(2014, 9, 9) <= t else 1.0)
    bull = (bv + 4 * eps) * b
    base = (bv + 2 * eps) * min(b, m80)
    bear = bv * m50
    base_ret, bear_ret = base / c - 1, bear / c - 1
    if bear_ret >= 0:
        ratio = float("inf") if base_ret > 0 else float("-inf")
    else:
        ratio = base_ret / -bear_ret
    # avoid 1: latest two available single-month MoM both negative
    m = (t.year, t.month - 1) if t.day >= 10 else (t.year, t.month - 2)
    def back(ym, k):
        y, mm = ym; mm -= k
        while mm <= 0: y -= 1; mm += 12
        return (y, mm)
    r0, r1, r2 = (rev.get(back(m, k)) for k in (0, 1, 2))
    avoid_rev = None if None in (r0, r1, r2) else (r0 < r1 and r1 < r2)
    # avoid 3: OCF negative 2 quarters and inventory > 50% of equity (statements from 2013)
    lq = latest_quarters(ocf_ytd, t, 2)
    avoid_cf = None
    if lq:
        o = [ocf_quarter(x) for x in lq]
        if None not in o and lq[-1] in inv_q and lq[-1] in eq_q:
            avoid_cf = all(v < 0 for v in o) and inv_q[lq[-1]] > 0.5 * eq_q[lq[-1]]
    avoid = bool(avoid_rev) or bool(avoid_cf)
    state = "避開" if avoid else ("考慮買進" if ratio >= 1 else "觀望")
    fwd = {}
    for months in (6, 12):
        target = t + timedelta(days=round(months * 30.44))
        j = next((k for k in range(i, len(days)) if days[k] >= target), None)
        fwd[months] = None if j is None else tri[j] / tri[i] - 1
    j12 = next((k for k in range(i, len(days)) if days[k] >= t + timedelta(days=365)), None)
    mdd = None
    if j12:
        peak = tri[i]; mdd = 0.0
        for k in range(i, j12 + 1):
            peak = max(peak, tri[k]); mdd = min(mdd, tri[k] / peak - 1)
    rows.append(dict(date=t.isoformat(), close=c, pbr=b, rank=round(rank, 1), m50=round(m50, 3), m80=round(m80, 3),
                     eps_q=q[0].isoformat(), eps=round(eps, 2), base_ret=round(base_ret, 4), bear_ret=round(bear_ret, 4),
                     ratio=ratio if abs(ratio) == float("inf") else round(ratio, 3),
                     avoid_rev=avoid_rev, avoid_cf=avoid_cf, state=state,
                     fwd6=None if fwd[6] is None else round(fwd[6], 4), fwd12=None if fwd[12] is None else round(fwd[12], 4),
                     mdd12=None if mdd is None else round(mdd, 4), tri=round(tri[i], 6)))

with open(OUT, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print(len(rows), "rows ->", OUT)
```

下載資料：對每個資料集執行 `https://api.finmindtrade.com/api/v4/data?dataset=<資料集>&data_id=2408&start_date=2000-01-01`，存成 `<資料集>.json`。資料集包括 `TaiwanStockPER`、`TaiwanStockPrice`、`TaiwanStockMonthRevenue`、`TaiwanStockFinancialStatements`、`TaiwanStockBalanceSheet`、`TaiwanStockCashFlowsStatement`、`TaiwanStockDividend`。2026-11-06 下載。

程式裡的減資日期（2014-09-09，10:1）只適用南亞科。換股票之前，要改成該股的減資或分割紀錄（FinMind `TaiwanStockCapitalReductionReferencePrice`）。

</details>
