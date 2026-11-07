# 記憶體規則回測：v1 與 v2

最後更新：2026-11-06｜標的：2408 南亞科（設計 v2 時參考過，屬於樣本內）、2344 華邦電與 8299 群聯（樣本外）｜規則：[README](README.md#固定標準)

非買賣建議。

## 結論

- **v1（2026-11-05 版）沒有通過驗證。**
  - 南亞科「考慮買進」之後 12 個月的中位數報酬只有 +9.5%，低於全部月份的 +11.2%。
  - 2025–2026 年大漲期間一直是「觀望」。三次大谷底都亮起「避開」，2018 年的高點反而給出「考慮買進」。
- **v2（2026-11-06 版）在三檔股票上都比 v1 好**，所以 README 的固定標準改用 v2。
  - 「考慮買進」之後 12 個月的中位數報酬：南亞科 +22.5%、華邦電 +52.7%、群聯 +18.7%，都高於各自全部月份的中位數（+11.2%、+12.8%、+12.2%）。
  - 主要谷底的判斷：南亞科 6 次中有 4 次給出「考慮買進」，華邦電和群聯都是 6 次全中。
  - 「觀望」之後 12 個月的中位數報酬，三檔都是負的（−23.4%、−3.1%、−8.4%）。
- **v2 的弱點是太早下車**：它是均值回歸的規則，在景氣循環谷底附近買，獲利一超過過去 5 年的平均就轉為「觀望」。
  - 這一波它在 2024-07 進場，2025-09 就轉為觀望：南亞科在 73 元、華邦電在 34 元、群聯在 706 元。之後的漲幅它都沒有參與。
  - 如果這次的景氣循環真的跟過去不同（結構性變化），v2 會一直低估價值。

## 規則版本

| | v1（2026-11-05） | v2（2026-11-06） |
| --- | --- | --- |
| Base | （淨值 + 最新一季 EPS × 2）× min（目前 PBR，P80） | 淨值 ×（1 + 過去 20 季平均季 ROE × 4）× P50 |
| Bear | 淨值 × P50（零獲利） | 淨值 ×（1 + 過去 5 年最差的連續 4 季 ROE）× P20 |
| 避開 | 月營收連續 2 個月月減；營業現金流連續 2 季為負且存貨超過淨值一半 | 最近 4 季 ROE 合計低於 −10%；營業現金流連續 2 季為負且存貨超過淨值一半 |
| 考慮買進 | 沒有避開條件，且報酬風險比 ≥ 1 | 同左 |

v2 為什麼這樣改：

- **用過去 20 季的平均獲利**：景氣循環股不能只看最新一季。虧損的谷底會讓 Base 變成負數，高峰時又會高估。
- **ROE ＝ 季 EPS ÷ 季底的每股淨值**：用比率表示，就不會受到減資或股票股利造成的每股數字斷層影響。
- **Bear 用最差的連續 4 季加上 P20**：代表谷底獲利加上谷底評價。這樣 Bear 一定不會高於 Base，也就修正了 v1「Bear 比 Base 樂觀」的問題。
- **「淨值一年被侵蝕超過一成」就避開**：用來排除 2010–2012 年南亞科那種價值陷阱。
- **拿掉月營收月減**：它是落後訊號，v1 的回測顯示它會在谷底叫人離場。

v2 的 Base 和 Bear 都不會隨股價變動，所以考慮買進價位就是（Base + Bear）÷ 2。

## 方法

- **評估方式**：每月最後一個交易日評估一次，最後再加上 2026-11-05。南亞科、華邦電從 2010-09 開始，群聯因為 PBR 資料從 2007 年才有，從 2012-05 開始。
- **只用當時已經公布的資料**（no-lookahead）：
  - 月營收：次月 10 日之後才可以用。
  - 季報：依法定期限，Q1 為 5/15、Q2 為 8/14、Q3 為 11/14、Q4 為隔年 3/31。（2026-11-07 更正：這是現行期限。2010 年度以前的年報是隔年 4/30，2012 年以前的半年報合併報表最晚是 9/14。照舊期限重跑，只有南亞科 2011-03、2011-04 的 v2 從避開變成觀望，結論不變，見[公布日對齊的回測核對](method-timing-revenue.md#回測核對)。）
  - PBR：證交所每天公布，當天可以用。
- **計算細節**：
  - 每股淨值用「收盤 ÷ PBR」，和 pipeline 相同。五年 P20／P50／P80 用線性內插，和 pipeline 的 `numpy.percentile` 相同。
  - 2026-11-05 南亞科的 P80 倍數算出來是 2.69，pipeline 11/04 是 2.684。
- **回測不到的條件**：
  - 「合約價由漲轉跌」：沒有免費的歷史資料。
  - 現金流和存貨條件：FinMind 的資產負債表和現金流量表從 2013 年才有。
  - 投資吸引力和研究優先級的排序：還沒有回測。
- **報酬**：FinMind 的還原股價要付費，所以用原始股價自己還原：加回現金股利和股票股利，並用參考價處理減資，算成總報酬指數。策略比較時每次切換扣 0.3%，沒有計算其他成本。
- **v1 一致性檢查**：新程式算出的南亞科 v1 判斷，和 v1 單獨回測的 195 個月結果完全相同。

## 結果：依判斷分組的 12 個月後報酬

| 標的 | 判斷 | 月數 | 平均 | 中位數 | 上漲機率 |
| --- | --- | ---: | ---: | ---: | ---: |
| 南亞科 | 全部 | 182 | +52.0% | +11.2% | 58% |
| 南亞科 | v1 考慮買進 | 66 | +12.7% | +9.5% | 58% |
| 南亞科 | v1 觀望 | 68 | +103.4% | −11.0% | 46% |
| 南亞科 | v1 避開 | 48 | +33.2% | +29.3% | 75% |
| 南亞科 | v2 考慮買進 | 97 | +86.1% | +22.5% | 70% |
| 南亞科 | v2 觀望 | 53 | −1.7% | −23.4% | 30% |
| 南亞科 | v2 避開 | 32 | +37.6% | +32.9% | 66% |
| 華邦電 | 全部 | 182 | +54.4% | +12.8% | 58% |
| 華邦電 | v1 考慮買進 | 31 | +65.7% | +31.0% | 77% |
| 華邦電 | v1 觀望 | 118 | +59.1% | −0.8% | 49% |
| 華邦電 | v1 避開 | 33 | +26.9% | +24.0% | 73% |
| 華邦電 | v2 考慮買進 | 42 | +183.5% | +52.7% | 93% |
| 華邦電 | v2 觀望 | 140 | +15.7% | −3.1% | 48% |
| 華邦電 | v2 避開 | 0 | — | — | — |
| 群聯 | 全部 | 162 | +34.6% | +12.2% | 72% |
| 群聯 | v1 考慮買進 | 107 | +41.6% | +15.5% | 79% |
| 群聯 | v1 觀望 | 23 | +22.7% | −8.8% | 43% |
| 群聯 | v1 避開 | 32 | +19.7% | +14.4% | 66% |
| 群聯 | v2 考慮買進 | 128 | +38.7% | +18.7% | 80% |
| 群聯 | v2 觀望 | 31 | +21.7% | −8.4% | 39% |
| 群聯 | v2 避開 | 3 | −6.4% | −12.9% | 33% |

- 南亞科 v2 的「避開」是 2011–2013 年淨值大幅侵蝕的期間，裡面包含 2012-11 的谷底，所以避開之後的報酬是正的。這個條件躲掉了 2010–2012 年的崩跌，但也錯過了谷底反彈。
- 群聯的 v2 有 79% 的月份是「考慮買進」，鑑別力不高。

## 結果：主要高低點

高低點的定義是：前後 12 個月內，總報酬指數的最高點或最低點。

| 標的 | 低點給出「考慮買進」 | 高點沒有給出「考慮買進」 |
| --- | --- | --- |
| 南亞科 | v1：6 次中 1 次（2018-10）<br>v2：6 次中 4 次（2018-10、2020-08、2022-09、2024-12）。2012-11 是避開，2015-07 是觀望 | v1：7 次中 6 次<br>v2：7 次中 6 次。兩版都在 2018-05 的高點給出「考慮買進」 |
| 華邦電 | v1：6 次中 4 次<br>v2：6 次中 6 次 | v1、v2 都是 6 次中 6 次 |
| 群聯 | v1、v2 都是 6 次中 6 次 | v1：6 次中 4 次（2013-05、2015-05 給出考慮買進）<br>v2：6 次中 5 次（2015-05） |

## 結果：簡單策略

每月依判斷調整，每次切換扣 0.3%。

| 標的 | 策略 | 終值 | 年化 | 最大回落 | 切換次數 |
| --- | --- | ---: | ---: | ---: | ---: |
| 南亞科 | 買進持有 | 2.67 倍 | +6.3% | −93.9% | — |
| 南亞科 | v1 只在考慮買進時持有 | 1.35 倍 | +1.9% | −47.1% | 24 |
| 南亞科 | v2 只在考慮買進時持有 | 3.06 倍 | +7.2% | −49.1% | 10 |
| 南亞科 | v2 避開時空手 | 10.03 倍 | +15.3% | −65.8% | 3 |
| 華邦電 | 買進持有 | 19.71 倍 | +20.3% | −65.1% | — |
| 華邦電 | v1 只在考慮買進時持有 | 1.10 倍 | +0.6% | −38.8% | 30 |
| 華邦電 | v2 只在考慮買進時持有 | 6.25 倍 | +12.0% | −40.3% | 24 |
| 群聯 | 買進持有 | 12.76 倍 | +19.2% | −50.7% | — |
| 群聯 | v1 只在考慮買進時持有 | 2.77 倍 | +7.3% | −40.1% | 42 |
| 群聯 | v2 只在考慮買進時持有 | 11.43 倍 | +18.3% | −40.0% | 24 |
| 群聯 | v2 避開時空手 | 19.35 倍 | +22.7% | −50.7% | 4 |

「只在考慮買進時持有」只是用來檢查進場訊號，不是完整的策略：它一轉為觀望就賣出。在華邦電這種長期大漲的股票上，總報酬會輸給買進持有，但最大回落比較小。

## v1 為什麼失敗（2026-11-06 診斷）

1. **最新一季 EPS 不適合景氣循環股。** 谷底時 EPS 是負的，Base 反而比 Bear（零獲利）還差，所以規則永遠不會在虧損的谷底喊買。南亞科 195 次評估中，有 64 次 EPS 為負。
2. **報酬風險比實際上退化了。** 南亞科 66 次「考慮買進」中，有 60 次只是因為股價已經低於 Bear 價值。
3. **虧損期會扭曲 P/B 百分位。** 南亞科 2012-11 谷底時 P/B 在 P82，2018-05 高點反而只有 P49。歷史分布分成兩群時，P80 也會突然跳動：2026-09 底是 1.59，10 月底變成 2.60。
4. **月營收連續 2 個月月減是落後訊號。** 南亞科 2015-07、2020-08、2022-09 三次大谷底都叫人避開。

v2 修正了 1、2、4。第 3 點還在：2018-05 的高點，v2 一樣給出「考慮買進」。

## 限制

- **樣本外有限**：南亞科是設計 v2 時參考過的樣本。華邦電、群聯雖然是樣本外，但同產業、同一段期間，只能算橫向的樣本外，不是時間上的樣本外。
- **門檻可能有偏誤**：−10% 的淨值侵蝕門檻，是看過南亞科的虧損幅度之後才定的。
- **群聯的訊號鑑別力不高。**
- **結構性變化**：v2 會在大漲初期就下車。目前的論點問題（「吃緊會持續多久」）正好是 v2 回答不了的。
- **其他**：
  - 合約價條件和排序標準都沒有回測。
  - 除了切換成本，沒有計算其他交易成本。
  - 只用月底評估。
  - 只用 FinMind 一個資料來源。

## 回測程式

只用 Python 標準函式庫。輸入是 FinMind 免費 API 下載的 JSON，同一支程式同時算出 v1 和 v2。

下載資料：對每個資料集執行 `https://api.finmindtrade.com/api/v4/data?dataset=<資料集>&data_id=<代號>&start_date=2000-01-01`，存成 `<資料集>.json`。資料集包括 `TaiwanStockPER`、`TaiwanStockPrice`、`TaiwanStockMonthRevenue`、`TaiwanStockFinancialStatements`、`TaiwanStockBalanceSheet`、`TaiwanStockCashFlowsStatement`、`TaiwanStockDividend`、`TaiwanStockCapitalReductionReferencePrice`。資料是 2026-11-06 下載的。

執行：`python3 -I bt_v2.py <資料夾> <輸出.csv>`

```python
"""No-lookahead backtest of the knowledge/ fixed rules, v1 (2026-11-05) and v2 (2026-11-06), on one TW stock.

Usage: python3 -I bt_v2.py <data_dir> <out_csv>
<data_dir> holds FinMind JSON: TaiwanStockPER, TaiwanStockPrice, TaiwanStockMonthRevenue,
TaiwanStockFinancialStatements, TaiwanStockBalanceSheet, TaiwanStockCashFlowsStatement,
TaiwanStockDividend, TaiwanStockCapitalReductionReferencePrice.
Availability: revenue month m -> 10th of m+1; quarter -> 05-15 / 08-14 / 11-14 / next 03-31; PBR same day.
"""
import csv, json, sys
from datetime import date, timedelta

D, OUT = sys.argv[1], sys.argv[2]
load = lambda n: json.load(open(f"{D}/{n}.json"))["data"]
P = lambda s: date.fromisoformat(s)
INF = float("inf")

cash_div, stock_div = {}, {}  # corporate actions
for r in load("TaiwanStockDividend"):
    if r["CashExDividendTradingDate"]:
        d = P(r["CashExDividendTradingDate"]); cash_div[d] = cash_div.get(d, 0) + r["CashEarningsDistribution"] + r["CashStatutorySurplus"]
    s = r["StockEarningsDistribution"] + r["StockStatutorySurplus"]
    if s > 0 and r["StockExDividendTradingDate"]:
        d = P(r["StockExDividendTradingDate"]); stock_div[d] = stock_div.get(d, 0) + s
reduction = {P(r["date"]): r["PostReductionReferencePrice"] / r["ClosingPriceonTheLastTradingDay"]
             for r in load("TaiwanStockCapitalReductionReferencePrice")}

def share_factor(d):  # new shares per old share on day d
    return (1 + stock_div.get(d, 0) / 10) / reduction.get(d, 1.0)

px = [r for r in load("TaiwanStockPrice") if r["close"] > 0]
days, close, tri = [], [], []
idx = 1.0
for i, r in enumerate(px):
    d = P(r["date"]); c = r["close"]
    if i:
        idx *= (c * share_factor(d) + cash_div.get(d, 0.0)) / close[-1]
    days.append(d); close.append(c); tri.append(idx)
pos = {d: i for i, d in enumerate(days)}

def eps_scale(q_end, t):  # convert per-share figures dated q_end into shares outstanding at t
    f = 1.0
    for d in list(reduction) + list(stock_div):
        if q_end < d <= t: f /= share_factor(d)
    return f

pbr = {P(r["date"]): r["PBR"] for r in load("TaiwanStockPER") if r["PBR"] > 0}
rev = {(r["revenue_year"], r["revenue_month"]): r["revenue"] for r in load("TaiwanStockMonthRevenue")}

def quarters(name, field):
    return {P(r["date"]): r["value"] for r in load(name) if r["type"] == field}
eps_q = quarters("TaiwanStockFinancialStatements", "EPS")
inv_q = quarters("TaiwanStockBalanceSheet", "Inventories")
eq_q = quarters("TaiwanStockBalanceSheet", "EquityAttributableToOwnersOfParent")
ocf_ytd = quarters("TaiwanStockCashFlowsStatement", "CashFlowsFromOperatingActivities")

def available(q):
    return {3: date(q.year, 5, 15), 6: date(q.year, 8, 14), 9: date(q.year, 11, 14), 12: date(q.year + 1, 3, 31)}[q.month]

def last_q(series, t, n):
    qs = sorted(q for q in series if available(q) <= t)
    return qs[-n:] if len(qs) >= n else None

def ocf_quarter(q):
    prev = {3: None, 6: date(q.year, 3, 31), 9: date(q.year, 6, 30), 12: date(q.year, 9, 30)}[q.month]
    if q not in ocf_ytd: return None
    if prev is None: return ocf_ytd[q]
    return None if prev not in ocf_ytd else ocf_ytd[q] - ocf_ytd[prev]

def bvps_on(d):  # book value per share at quarter end = close / PBR on the last trading day <= d; ROE_q = EPS / this
    k = max((x for x in pbr if x <= d and x in pos), default=None)
    return None if k is None or d - k > timedelta(days=10) else close[pos[k]] / pbr[k]
roe_q = {}
for q, e in eps_q.items():
    b = bvps_on(q)
    if b: roe_q[q] = e / b

def pct(vals, q):
    k = (len(vals) - 1) * q / 100; f = int(k); c = min(f + 1, len(vals) - 1)
    return vals[f] + (vals[c] - vals[f]) * (k - f)

def ratio_of(base, bear, c):
    if bear >= c: return INF
    return (base / c - 1) / (1 - bear / c)

month_end = {}
for d in days: month_end[(d.year, d.month)] = d
evals = sorted(v for v in month_end.values() if v >= date(2010, 1, 1))
rows = []
for t in evals:
    if t not in pbr: continue
    window = sorted(v for d, v in pbr.items() if t - timedelta(days=5 * 365 + 1) <= d <= t)
    if min(pbr) > t - timedelta(days=5 * 365 - 30): continue  # need a full 5-year PBR window
    rq = last_q(roe_q, t, 20)
    if not rq: continue
    i = pos[t]; c = close[i]; b = pbr[t]; bv = c / b
    m20, m50, m80 = (pct(window, q) for q in (20, 50, 80))
    rank = sum(1 for v in window if v <= b) / len(window) * 100
    # ---- v1 (README 2026-11-05) ----
    q1 = last_q(eps_q, t, 1)[0]
    eps = eps_q[q1] * eps_scale(q1, t)
    base1 = (bv + 2 * eps) * min(b, m80); bear1 = bv * m50
    ratio1 = ratio_of(base1, bear1, c) if not (bear1 >= c and base1 <= c) else -INF
    ym = (t.year, t.month - 1) if t.day >= 10 else (t.year, t.month - 2)
    def back(ymv, k):
        y, mm = ymv; mm -= k
        while mm <= 0: y -= 1; mm += 12
        return (y, mm)
    r0, r1, r2 = (rev.get(back(ym, k)) for k in (0, 1, 2))
    avoid_rev = None not in (r0, r1, r2) and r0 < r1 < r2
    lq = last_q(ocf_ytd, t, 2); avoid_cf = False
    if lq:
        o = [ocf_quarter(x) for x in lq]
        if None not in o and lq[-1] in inv_q and lq[-1] in eq_q:
            avoid_cf = all(v < 0 for v in o) and inv_q[lq[-1]] > 0.5 * eq_q[lq[-1]]
    v1 = "避開" if (avoid_rev or avoid_cf) else ("考慮買進" if ratio1 >= 1 else "觀望")
    # ---- v2 (2026-11-06): through-cycle ROE, trough case, book-value erosion guard ----
    roes = [roe_q[q] for q in rq]
    roe_norm = sum(roes) / len(roes)
    roe_worst4 = min(sum(roes[k:k + 4]) for k in range(len(roes) - 3))
    roe_ttm = sum(roes[-4:])
    base2 = bv * (1 + 4 * roe_norm) * m50
    bear2 = bv * (1 + roe_worst4) * m20
    ratio2 = ratio_of(base2, bear2, c)
    avoid_erosion = roe_ttm < -0.10
    v2 = "避開" if (avoid_erosion or avoid_cf) else ("考慮買進" if ratio2 >= 1 else "觀望")
    def fwd(n_days):
        j = next((k for k in range(i, len(days)) if days[k] >= t + timedelta(days=n_days)), None)
        return None if j is None else tri[j] / tri[i] - 1
    rows.append(dict(date=t.isoformat(), close=c, pbr=b, rank=round(rank, 1), m20=round(m20, 3), m50=round(m50, 3),
                     m80=round(m80, 3), eps=round(eps, 3), roe_norm=round(roe_norm, 4), roe_worst4=round(roe_worst4, 4),
                     roe_ttm=round(roe_ttm, 4), base1=round(base1, 2), bear1=round(bear1, 2), ratio1=ratio1 if abs(ratio1) == INF else round(ratio1, 3),
                     base2=round(base2, 2), bear2=round(bear2, 2), ratio2=ratio2 if ratio2 == INF else round(ratio2, 3),
                     avoid_rev=avoid_rev, avoid_cf=avoid_cf, avoid_erosion=avoid_erosion, v1=v1, v2=v2,
                     fwd12=fwd(365), tri=tri[i]))
with open(OUT, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
print(OUT.split("/")[-1], len(rows), "rows", rows[0]["date"], "→", rows[-1]["date"])
```
