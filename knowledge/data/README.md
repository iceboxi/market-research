# 歷史資料

抓取日：2026-11-20｜資料到 2026-11-19 收盤｜用途：推論和回測的歷史對照。非買賣建議。

## 怎麼用

- **推論需要歷史對照時，先從這裡算**，例如「過去發生過幾次、之後怎麼走」。寫出樣本數、期間、用了哪個檔案，以及最強的反例。樣本少照樣寫推論，但要標明樣本數。
- **不能偷看未來**：
  - 融資、法人、跌停結構是當天晚上公布的，訊號最快用隔天收盤。
  - 月營收次月 10 日起才能用，季報照法定期限（[method-timing-revenue.md](../method-timing-revenue.md#公布日對齊)）。
- **這是快照，不會每天更新**。要更新就重跑下面的程式，整批覆蓋，PR 寫明抓取日。
- **pipeline 每天算的數字以 pipeline 為準**（價格位置、檢視區、論點狀態），這裡只用來做歷史對照。

## 檔案

| 檔案 | 內容 | 期間 | 來源 | 對應的規則 |
| --- | --- | --- | --- | --- |
| [market/taiex_daily.csv](market/taiex_daily.csv) | 加權指數日線（開高低收、成交金額）和加權報酬指數 | 1999-01-05 起；報酬指數 2003-01-02 起 | FinMind `TaiwanStockPrice`（`TAIEX`）、`TaiwanStockTotalReturnIndex` | 大盤參考價位、單日大跌 |
| [market/margin_daily.csv](market/margin_daily.csv) | 上市融資餘額（張、元）、融券餘額，融資買進、賣出、現金償還（張） | 2001-01-03 起 | FinMind `TaiwanStockTotalMarginPurchaseShortSale` | 籌碼止穩、融資斷頭 |
| [market/institutional_daily.csv](market/institutional_daily.csv) | 三大法人買賣超（元）。自營商 2014-11 以前只有合計 `Dealer_net`，之後分成自行買賣和避險 | 2004-04-07 起 | FinMind `TaiwanStockTotalInstitutionalInvestors` | 外資賣超縮小 |
| [market/etf_daily.csv](market/etf_daily.csv) | 0050、00631L 收盤，沒有還原 | 0050 2003-06-30 起；00631L 2014-10-31 起 | FinMind `TaiwanStockPrice` | 0050 分批、00631L 耗損 |
| [market/limit_down_days.csv](market/limit_down_days.csv) | 事件日和隔天的跌停結構：跌幅達門檻的家數、鎖死沒有委買的家數、鎖單合計和中位數、盤中碰過跌停的家數、官方漲跌停家數 | 2004-02-11 起，111 個事件日 | 證交所 `MI_INDEX`（`type=ALLBUT0999`） | 被迫賣出 |
| [market/limit_down_locked_stocks.csv](market/limit_down_locked_stocks.csv) | 事件日鎖死跌停的個股和鎖單張數，以及隔天的漲跌 | 同上 | 同上 | 被迫賣出：鎖單少、隔夜衝擊 |
| [market/day_trading_days.csv](market/day_trading_days.csv) | 事件日、前一天和隔天的當沖成交股數、買賣金額和占市場比重 | 資料 2014-01-06 起；事件日 2015-08-21 起，42 個 | 證交所 `TWTB4U` | 流動性 |
| [market/disposition_stocks.csv](market/disposition_stocks.csv) | 上市股票的處置公告：公布日、代號、處置期間、第幾次處置 | 處置期間在 2004 年以後的公告（最早公布日 2003-12-26） | 證交所 `announcement/punish` | 處置股家數 |
| `stocks/<代號>_daily.csv` | 日線、本益比、P/B、殖利率、總報酬指數 | 日線 1999 年或上市日起；本益比 2005-09-02 起（群聯 2007-01-02） | FinMind `TaiwanStockPrice`、`TaiwanStockPER`；總報酬指數自己算 | 衛星股本益比檢視區、記憶體 P/B v2 |
| `stocks/<代號>_quarterly.csv` | 損益（`is_`，單季）：營收、毛利、營業利益、稅後淨利、歸屬母公司淨利、EPS。資產負債（`bs_`，季底）：資產、負債、母公司權益、存貨、現金。營業現金流（`cf_ytd_`，年初累計） | 1990–2002 年起，各檔不同，到 2026 Q3 | FinMind `TaiwanStockFinancialStatements`、`TaiwanStockBalanceSheet`、`TaiwanStockCashFlowsStatement` | ROE、P×Q、避開條件 |
| `stocks/<代號>_month_revenue.csv` | 月營收（元） | 2002-01 起（奇鋐 2002-09、群聯 2003-05） | FinMind `TaiwanStockMonthRevenue` | 論點檢查、月營收動能 |
| `stocks/<代號>_actions.csv` | 除權息日的現金股利、每 10 股配股，以及減資換算比例 | 2005 起 | FinMind `TaiwanStockDividend`、`TaiwanStockCapitalReductionReferencePrice` | 總報酬指數 |
| [macro/fred_monthly.csv](macro/fred_monthly.csv) | 23 個美國景氣指標：初領失業救濟金、零售銷售、實質個人消費支出、耐久財訂單、消費者信心、CPI、利率、信用利差、油價、美元、民間投資等 | 1990-01 起，各序列不同 | FRED | 景氣階段 |
| [macro/us_indices_daily.csv](macro/us_indices_daily.csv) | 費半、S&P 500、那斯達克收盤 | 1990-01-02 起；費半 1994-05-04 起 | yfinance（`^SOX`、`^GSPC`、`^IXIC`） | 景氣階段、隔夜外部衝擊 |

個股：衛星股 2330 台積電、2317 鴻海、2454 聯發科、2356 英業達、3017 奇鋐；產業觀察 2408 南亞科、2344 華邦電、8299 群聯（上櫃）。

## 定義

- **普通股**：四碼、不是 0 開頭的上市股票。
- **門檻**：漲跌幅限制減 0.5 個百分點。2015-06-01 以前限制是 7%，之後是 10%，所以門檻是 6.5% 和 9.5%，和 [method-forced-selling.md](../method-forced-selling.md) 的「跌幅 ≥ 9.5%」相同。
- **收盤跌幅達門檻**（`close_down_over_threshold`）：收盤跌幅 ≥ 門檻。漲的一邊（`close_up_over_threshold`）同理。
- **鎖死、沒有委買**（`locked_no_bid`）：收盤跌幅達門檻，收盤價等於最後揭示賣價，而且沒有最後揭示買價。鎖單是最後揭示賣量（張）。
- **盤中碰過跌停**（`low_down_over_threshold`）：最低價的跌幅達門檻。
- **事件日**：加權指數收盤跌 3% 以上，`role` 是 `event`；隔一個交易日是 `next`；當沖統計另外收前一個交易日，`role` 是 `prior`。
- **金額單位**：元。融資、融券是張。三大法人是買進減賣出。

## 限制

- **只有上市市場**。上櫃的收盤行情（櫃買中心 `dailyQuotes`）只回溯到 2025-04-07，沒有收進來。群聯是上櫃股，日線來自 FinMind。
- **修正後的版本**：財報、月營收、FRED 是現在的版本，不是當時公布的數字。FRED 當時的版本要查 ALFRED。
- **本益比、P/B** 是證交所每天公布的值，用當時的近四季 EPS，沒有還原分割。
- **總報酬指數**（`total_return_index`）：
  - 加回現金股利、股票股利，並用參考價處理減資，算法和 [backtest-memory-rules.md](../backtest-memory-rules.md#回測程式) 相同。
  - FinMind 的除權息紀錄 2005 年才開始，所以從 2005-01-03 起算。
  - 單日變動超過漲跌幅限制 1 個百分點、又沒有公司行動紀錄時，從那天重新起算：鴻海 2009-06-02、英業達 2009-07-15（兩家 2009 年的除權息沒有紀錄）、南亞科 2009-08-26（減資沒有紀錄）。其他 5 檔從 2005-01-03 起。
  - 漲跌幅以內的缺漏查不出來，例如少一筆小額現金股利。
- **收盤價沒有還原**：
  - 0050 在 2025-06-18 一股拆四（188.65 → 47.57）。
  - 00631L 在 2026-03-31 一股拆 23（443.15 → 19.26）。
  - 分割前後不能直接比，要先換算。
- **跌停結構**：
  - `close_down_over_threshold` 是收盤跌幅達門檻的家數，比官方跌停家數多，因為有些股票收在門檻和跌停價之間。例如 11/19 是 158 檔，官方是 128 檔。
  - 官方漲跌停家數（`official_*`）在事件日中，2011-08-05 以後才有。
  - 鎖單張數 2006 年起才有，更早的留空。
  - 和 [method-forced-selling.md](../method-forced-selling.md#回測核對) 人工查的 9 天對照：鎖死家數和鎖單合計有 8 天相同。2025-04-07 這裡是 918 檔、3,130,084 張，人工是 925 檔、3,242,615 張。2026-07-29、11/03 的鎖單中位數是 496.5、134 張，人工是 513、146 張，家數和合計相同。差異沒有查原因。
- **融資、法人的最後一天**是當晚的初值，隔天可能小幅修正。
- **信用利差**：ICE 高收益債利差（`BAMLH0A0HYM2`）在 FRED 只有 2023-11 以後的資料，長期比較用 Baa 公司債和 10 年期公債的利差（`BAA10Y`）。
- **FRED 月資料的寫法**：日、週資料取當月平均；季資料（`PNFI`、`GPDIC1`、`PCECC96`）放在每季的第一個月。
- **處置公告**只收四碼、不是 0 開頭的股票，不含權證和 ETF。
- **核對**：2026-11-19 的加權指數收盤、成交金額、融資、融券、三大法人，和 [market-tw.md](../market-tw.md) 直接查證交所的數字相同。

## 重抓

只用 Python 標準函式庫（美股指數要 yfinance，用專案的環境）：

```text
python3 -I knowledge/data/fetch_history.py <輸出資料夾> --end <最後一個收盤日>
uv run --frozen python -I knowledge/data/fetch_us_indices.py <輸出資料夾>/macro/us_indices_daily.csv <最後一個收盤日>
```

`--only market,stocks,limits,macro` 可以只抓一部分。`limits` 要先有 `market/taiex_daily.csv`。證交所每次請求間隔 3.5 秒，全部跑完約 20 分鐘。
