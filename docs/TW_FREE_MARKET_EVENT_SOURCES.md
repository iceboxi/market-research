# 台股免費行情、營收、事件與新聞來源調查

查核日：2026-10-19（Asia/Taipei）。用途：支援台股優先 workflow 與可交付工作拆分。本文是來源調查，未宣稱已完成 provider、live-data 或自然排程驗收；三表與估值模型另依財報來源調查處理。

規劃範圍已確認先完成 2330 整條流程；使用者接受在來源允許範圍內公開保存精簡證據。未知歷史 publication 只限制 historical `asof`／回測聲明，不阻塞已取得資料的當下報告與從現在開始保存的 prospective evidence；資料取用及公開保留條件則按具體來源判斷。

## 建議採用範圍

先延伸現有 TWSE 路徑，讓 2330 的行情、月營收、公司資訊與官方事件進入同一份報告。免費官方 JSON／CSV 足以支援這條流程；歷史月營收、公告行程與新聞採各自小型驗收後加入。Yahoo 股市有實際可讀的營收、行事曆、基本資料及新聞頁面，可作外連與人工核對入口；這次沒有取得可宣稱通過的直接抓取結果。

| workflow 用途 | 建議 primary | fallback／補充 | 目前能支持的交付與限制 |
| --- | --- | --- | --- |
| 日行情與技術觀察 | TWSE 官方日 OHLCV；擴到上櫃時另接 TPEx | FinMind `TaiwanStockPrice`；twstock 作接法參考 | 先維持明確 raw price basis；不同來源與交易範圍須比較，不默默混接 |
| 公司行動／還原價 | 官方除權息、減資、分割事件與 raw 行情分開保存 | yfinance 作獨立比較候選；FinMind 還原價屬付費項目 | 先揭露公司行動與價格跳空；完整還原價另驗收，不以 raw 冒充 adjusted |
| 當期月營收 | TWSE OpenAPI／MOPS 開放 CSV | FinMind 月營收、Yahoo 營收頁人工核對 | 可以先完成當期報告；歷史比較只使用實際取得的月份與版本 |
| 官方重大訊息 | TWSE／MOPS 每日重大訊息開放資料 | TPEx／MOPS 上櫃資料、公司 IR | 有事件可要求重新研究；來源失敗不能顯示「無事件」 |
| 法說／財報行程 | 已公告的公司 IR 日期、官方公告或行程頁 | Yahoo 個股行事曆人工核對 | 先做 2330；法說、財報董事會、財報申報日各自有證據，不能互代 |
| 公司基本資訊 | TWSE／MOPS 上市與上櫃公司基本資料 | FinMind `TaiwanStockInfo`、Yahoo profile | 支援公司身分、產業、上市日、股數及官方網站；當期資料不代表歷史時點資料 |
| 新聞摘要與延伸閱讀 | 官方公司新聞／公告作事實根據 | FinMind 新聞索引候選、Yahoo 新聞外連 | 先提供來源／日期／連結與可驗證摘要；不複製整篇、不以標題情緒當交易訊號 |

這是規劃建議；來源事實、取用條件及尚待驗證項目如下。

## 官方 JSON／CSV：免費、較適合正式 primary

TWSE OpenAPI 官方入口明確提供介接，包含 `t187ap03_L`（公司基本資料）、`t187ap05_L`（月營收）、`t187ap04_L`（每日重大訊息）與行情相關 endpoint。OpenAPI 清單不能單獨證明歷史 coverage、每個欄位的公開時間或目前 runner 可達。[TWSE OpenAPI](https://openapi.twse.com.tw/)、[Swagger](https://openapi.twse.com.tw/v1/swagger.json)

| 資料 | 官方資源、機器取得方式 | 欄位及費用／帳號 | 時間語意與待驗證 |
| --- | --- | --- | --- |
| 上市日行情 | [官方資料集](https://data.gov.tw/dataset/11549) 提供 CSV；現有 adapter 使用 `https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date=YYYYMM01&stockNo=2330` | 資料集列日期、代號、OHLC、成交股數／金額／筆數、漲跌；免費。現有 adapter 未要求 token | 交易日期不是 publication time。整月查詢可供當下歷史行情分析；歷史修訂與當時可取得版本仍須 snapshot |
| 上櫃日行情 | [官方資料集](https://data.gov.tw/dataset/11371) 的 CSV 與 [TPEx OpenAPI](https://www.tpex.org.tw/openapi/) | OHLC、成交股數／金額／筆數、最後買賣價等；每日、免費，資料集未列 API key | 最新全市場行情與個股歷史資料是不同介面；[TPEx 歷史行情頁](https://www.tpex.org.tw/zh-tw/mainboard/trading/info/pricing.html) 有歷史日期與 CSV，實際機器契約需再驗收 |
| 上市月營收 | [官方資料集](https://data.gov.tw/dataset/18420)；JSON `https://openapi.twse.com.tw/v1/opendata/t187ap05_L`；[MOPS CSV](https://mopsfin.twse.com.tw/opendata/t187ap05_L.csv) | 公司代號、資料年月、當月／上月／去年同月、累計、YoY／MoM、備註與出表日期；免費，公開 GET | 出表日期不等於該公司這筆版本的公開時間。全市場 snapshot 需按公司及資料年月驗證，不能假設全市場都同時更新 |
| 上櫃月營收 | [官方資料集](https://data.gov.tw/dataset/56510) 提供 MOPS CSV | 欄位與上市月營收同類；每月、免費，未列 token | 優先跟隨資料集的下載連結；不要憑命名推定 TPEx 一定有 `_O` JSON。歷史／修訂版本尚待驗收 |
| 上市重大訊息 | [官方資料集](https://data.gov.tw/dataset/18415)；JSON `https://openapi.twse.com.tw/v1/opendata/t187ap04_L` | 發言日期／時間、公司代號、主旨、符合條款、事實發生日、說明、出表日期；每日、免費 | 發言日期／時間可保存為來源宣告時間；須保留原欄位並核對時區。事實發生日不能代替 publication time；每日 snapshot 不是歷史檔案 |
| 上櫃重大訊息 | [官方資料集](https://data.gov.tw/dataset/18418) 提供 MOPS CSV，另指向 TPEx OpenAPI | 與上市重大訊息同類欄位；每日、免費 | 官方來源可作當下觀察；錯過來源視窗不代表該期間沒有公告 |
| 公司基本資料 | [上市資料集](https://data.gov.tw/dataset/18419)、JSON `https://openapi.twse.com.tw/v1/opendata/t187ap03_L`；[上櫃資料集](https://data.gov.tw/dataset/25036)、[上櫃 MOPS CSV](https://mopsfin.twse.com.tw/opendata/t187ap03_O.csv) | 公司名稱／代號、產業、上市櫃日期、資本額、普通股數、編制報表類型、網址及出表日期等；免費 | 股數、董事長、產業等可能變動；最新值只能用於當下資料狀態，歷史估值分母不得直接回填最新股數 |
| 除權息預告 | [官方資料集](https://data.gov.tw/dataset/89748)、[CSV](https://www.twse.com.tw/exchangeReport/TWT48U_ALL?response=open_data) | 除權息日期、股票代號、現金股利、無償／現增配股率及認購價等；免費、不定期更新 | 事件日不是公告首次公開時間；預告可更改。這些欄位是公司行動輸入，未自行構成完整 adjusted OHLC／total return |

上述 data.gov.tw 資料集均明列政府資料開放授權條款第 1 版。該條款要求標示來源；它與一般網頁內容的取用條件分開。[開放資料授權](https://data.gov.tw/license)。TWSE 一般網站使用條款對未經同意的自動下載有明確限制，並把已授權政府資料開放平臺的資料列為智慧財產權限制之例外；因此應優先使用指定開放介面，另查原始 IR／HTML 文件的使用條件，不能把「官方網頁看得到」推成可任意爬取及再散布。[TWSE 使用條款，第 6、8 項](https://www.twse.com.tw/zh/terms/use.html)

官方免費介面本次未找到可依賴的硬性 request quota／SLA；規劃上採全市場 snapshot 一次取得、cache、保守 timeout／retry 與 429／403 feedback。這是工程建議，不是聲稱官方提供無限請求。上市月營收資料集詮釋資料目前寫「每 1 年」，不能拿此 metadata 當實際更新 SLA。[上市月營收資料集](https://data.gov.tw/dataset/18420)

## Yahoo 股市：頁面內容確實存在，直接抓取仍未通過

本次 web search 回傳 Yahoo 自己頁面的內容，能確認下列資訊形狀；這是搜尋索引觀察。直接 `open` 相同 URL 及 `.TW` 版本回報 404，`calendar/` 也回報 404。沒有改 header、代理或繞過封鎖；不能據此斷言一般瀏覽器無法開啟，也不能宣稱 production scraper 成功。

| 頁面 | 本次搜尋內容觀察 | 可用於 workflow 的方式 |
| --- | --- | --- |
| [2330 走勢](https://tw.stock.yahoo.com/quote/2330) | OHLC、成交量、行情資料時間與成交金額範圍註記 | 人工核對與外連；驗收時須比較是否包含盤後、零股、鉅額等交易，成交量不可直接假定與官方同範圍 |
| [2330 營收](https://tw.stock.yahoo.com/quote/2330/revenue) | 月／季／年選項，月營收、YoY／MoM、累計、單位仟元 | 適合人工對帳；頁面當前呈現及舊月份數字不證明原始公開時間、修訂版本或完整歷史 |
| [2330 基本](https://tw.stock.yahoo.com/quote/2330/profile) | 公司／產業／官方網站、股數、財務摘要與重要日期 | 基本資訊的人工 fallback；財務摘要不能取代可追溯三表版本 |
| [2330 行事曆](https://tw.stock.yahoo.com/quote/2330/calendar) | 日期、法說、除權息、股東會、停券等分類 | 作人工行程比對，不能把每個法說都視為 earnings release |
| [全市場行事曆](https://tw.stock.yahoo.com/calendar/) | 事件分類與當日公司清單 | 可當使用者入口連結；未驗證可靠機器接口與歷史更新版本 |
| [2330 新聞](https://tw.stock.yahoo.com/quote/2330/news)、[公告](https://tw.stock.yahoo.com/quote/2330/announcement) | 發布媒體、標題、節錄、相關公告 | 發現待閱讀來源與外連；Yahoo 為聚合平台，文中事實仍追至公告或原始來源 |

Yahoo 臺灣服務條款明列未經明確事前允許的自動化資料存取／收集限制，也限制建立競爭或實質替代資料服務。這個具體條件使「Yahoo 免費頁面」不能直接等同「可免費部署的排程資料 API」。先提供外連與人工核對；自動化 adapter 必須確認適用允許方式、資料保留及輸出範圍後才成為正式 fallback。[Yahoo 服務條款，第 2 節](https://legal.yahoo.com/tw/zh-hant/yahoo/terms/otos/index.html)

## 可利用的 open source 與免費資料服務

### yfinance：比較用行情工具，不是 Yahoo 官方授權

[upstream](https://github.com/ranaroussi/yfinance) 為 Apache-2.0，說明自身不隸屬 Yahoo，並提醒實際資料權利依 Yahoo 條款、API intended for personal use。套件免費不等於取得資料再散布授權；台灣 Yahoo 股市頁面與 Yahoo Finance API 也不能視為同一份契約。`download` 支援 `actions`、`auto_adjust`、`back_adjust`、`repair`，且 `end` 不含結束日；應明確指定參數並記錄套件版本。`auto_adjust=True` 會調整 OHLC，不能與現有 raw 行情無標記混用。[download API](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html)

建議：保留為個人研究的獨立價格／公司行動比較候選，不把它當無條件 production fallback；若使用，驗證 `2330.TW` 與至少一檔 `.TWO` 的單位、缺值、股利及分割跨日結果。沒有可依賴的公開固定免費額度或 SLA 證據，不承諾可全市場高頻抓取。

### twstock：TWSE／TPEx 既有接法可參考

[upstream](https://github.com/mlouielu/twstock) 為 MIT，來源為 TWSE／TPEx，支援歷史價格與即時查詢；README 提醒 request limit（每 5 秒 3 次），這是 maintainer 的說明，不能升格成官方保障。它適合參考 parser、代號與 provider 做法；對本專案已存在的 TWSE adapter，是否加依賴要先比較維護成本。MIT 只授權程式碼；它與 TWSE 共用上游，遇 TWSE 中斷不能視為獨立資料備援。內建買賣點邏輯也不是本專案已驗證策略。[twstock upstream README／LICENSE](https://github.com/mlouielu/twstock)

### FinMind：免費 token 有用，但 paid dataset 與資料權利須獨立判斷

[upstream README](https://github.com/FinMind/FinMind) 公告無 token 300 requests／hour；註冊並驗證信箱後加 token 為 600／hour，每週日 00:00–07:00 維護。SDK 為 Apache-2.0。官方文件使用 `GET https://api.finmindtrade.com/api/v4/data`，以 `dataset`、`data_id`、`start_date` 等參數及 token／Bearer header 查詢。這次沒有取得成功的 live response；以下是文件契約。

| dataset | 可回傳欄位／用途 | 免費範圍與 as-of 限制 |
| --- | --- | --- |
| `TaiwanStockInfo` | 名稱、代號、產業、`type`、日期 | 文件列一般資料集；同代號可能有轉板舊列，當期市場要依日期處理。不是完整歷史成分股／存續區間資料庫 |
| `TaiwanStockPrice` | `date`、OHLC、`Trading_Volume`、成交金額等 | 文件的一檔查詢未標為 backer 限定，全市場按日批次查詢為 paid。原始資料可能有 0／無公告價等語意，不能直接 ffill 冒充真實成交 |
| `TaiwanStockPriceAdj` | 回溯還原 OHLC | **明列 backer／sponsor，不能納入零費用基線**。以最新交易日為基準回溯計算，也不代表歷史當時所見版本 |
| `TaiwanStockMonthRevenue` | `revenue`、`revenue_year`、`revenue_month`、`date`、`create_time` | 可作歷史月營收候選；`date` 不能直接當公告日。`create_time` 自 2026-04-21 才有值，代表 FinMind 入庫日期；啟用當天初始化值不代表那些資料當日公告 |
| `TaiwanStockDividend`／`TaiwanStockDividendResult` | 股利政策、除權息結果 | 作公司行動補充；免費個股接口與必要欄位先驗收。不要憑 event date 反推 first publication |
| `TaiwanStockNews` | `date`、`stock_id`、`description`、`link`、`source`、`title` | 文件說單次請求只提供一天資料。適合新聞索引候選；日期的發布／轉載時區語意須另核對，`description` 可能含 HTML |

欄位與方案依據：[FinMind 技術面](https://finmind.github.io/tutor/TaiwanMarket/Technical/)、[基本面](https://finmind.github.io/tutor/TaiwanMarket/Fundamental/)、[新聞](https://finmind.github.io/tutor/TaiwanMarket/Others/)。FinMind 目前資料授權說明明確區分 API 使用權與資料再散布／轉售／鏡像；對外用途須確認原提供機關條件並標示來源。因此歷史研究候選可先小量驗收，不能因 SDK 開源就保存／發布所有資料。[FinMind 資料授權說明（2026-07-12 版）](https://finmind.github.io/Disclaimer/)

## 行程與官方新聞：2330 可以先做小範圍

台積公司 IR 有[季度法說資訊](https://investor.tsmc.com/english/quarterly-results/teleconference)，本次可讀會議日期、台灣時間及活動名稱；[IR 首頁](https://investor.tsmc.com/english) 列最新法說與月營收。這是 2330 行程與公司發布資料的直接來源，不保證所有台股有一致 API 或頁面格式。法說頁的活動日期只證明活動時間；頁面何時首次發布、是否曾改期及歷史版本仍需 first_seen／snapshot。

建議先把官方來源連結、明確活動時間與內容類型放進 2330 報告；沒有來源公布的下一次日期就呈現未確認。公司 IR 網頁與 PDF 的自動抓取、保留及公開輸出條件須逐來源記錄；若未驗證，使用可追溯的手動 fixture／核對資料與外連，讓其他已驗證資料照常出報告。

## 計算、報告與 workflow 的免費工具

既有 pandas／NumPy、HTTP client、交易日曆、JSON／Markdown renderer 與 GitStateStore 可直接重用，不需要先導入新的研究框架。pandas 為 [BSD-3-Clause](https://github.com/pandas-dev/pandas/blob/main/LICENSE)；工具授權不替代輸入資料條件。

本 repository 為公開專案；GitHub 官方說明 standard GitHub-hosted runners 的公開專案執行免費，larger runners 及 Artifact／cache storage 有各自額度與計費條件。因此先維持既有 standard runner、有限期 Artifacts 與精簡 state，不把儲存視為無限制免費。[GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)、[GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。固定研究入口可沿用 GitHub Issues，省去新增網站／常駐服務。

本次交付僅涵蓋既有 TWSE pilot；表中的 TPEx／`.TWO` 是來源範圍說明與未來候選，不加入這次 tickets 的必要驗收。

## 時間與 evidence 契約

沿用 repository `GLOSSARY.md:7` 的 Period、`GLOSSARY.md:11` 的 Publication time、`GLOSSARY.md:15` 的 First seen。任何新 adapter 至少分清：

- `period`／`event_date`：財務期間、交易日或活動日。
- `published_at`＋precision／原欄位：來源能證明的該版本公開時間；不確定就保留 unknown，不補成午夜精確時間。
- `first_seen_at`：本系統第一次實際取得這個版本的時間；FinMind 入庫時間、搜尋索引抓取日不能代替。
- `retrieved_at`、來源 URL、版本／內容 hash、單位、coverage 與失敗原因：界定這次使用哪些證據。

最新 JSON／CSV 可支持「當下報告」的已取得資料。歷史回測／`asof` 要另有當時已知版本、publication 證據或本系統 prospective snapshot；現在抓到舊期間數字不能宣稱當年已知。還原價含後來公司行動、最新股數、後來修訂的營收及最新新聞頁尤其要隔離。

## 與現有程式的接點

- 現有 `TwseDailyProvider` 已限定 `.TW`，抓每月行情，宣告 raw price basis；`adj_close` 刻意留 NaN（`src/market_research/twse.py:60`、`:68`、`:131`）。免費來源調查沒有理由先重寫這條已存在的 seam。
- `market_data.py:19`、`:98` 明確保留 TWSE unadjusted 與公司行動未調整的 metadata。新增 adjusted 或 `.TWO` provider 要連同契約修改與 regression evidence，不能只換 URL。
- `fundamentals.py:13`、`:58`、`:95` 已用 TWSE profile／當期月營收，並明列月營收不等於年度財報（`:109`）；可先把日期、比較欄位、coverage 接進實際輸出。
- `event_risk.py:35` 與 `:95` 已是 current daily snapshot；`:100` 明確不支援以當前 endpoint 重建歷史。新增行程與新聞應保留不同來源及 coverage，避免覆蓋官方事件 state。
- `event_monitor.py:56`、`:63` 已有失敗不更新 baseline、首次 baseline 不通知；免費 fallback 不能繞過這些行為。

## 可直接放進工作驗收的最小切片

| 切片 | 驗收輸出與獨立依據 | 失敗／缺值／no-lookahead 驗證 |
| --- | --- | --- |
| 官方行情與來源 feedback | 2330 最近一個完整交易月；同一交易範圍核對至少 3 日 OHLCV、單位、交易日與 price basis；另保存來源日期及結果 receipt | 無價／停牌不補零或合成 candle；403、timeout、舊資料分開呈現。`.TWO` 另用一檔上櫃公司驗收，不誤走 TWSE |
| 公司行動提示 | 取一個官方已知除息及一個分割／減資 fixture；報告能指出事件與 raw／adjusted 差別 | 不把還原價當執行價格；未來活動不能提前改寫 historical input；調整演算法以官方條件或獨立 fixture 對帳 |
| 月營收完整片段 | 2330 最近 3 個實際取得月份、去年同期、MoM／YoY；官方 CSV 或原始公告數字核對，保留 TWD／TWD_thousands 轉換 | 缺月不補零；來源失敗保留上次有效 evidence 並標 stale。某月更正版到達前的 `asof` 不可使用更正版 |
| 公告偵測到研究 | 兩次 state 比較：首次 baseline、相同公告不重複、新公告只觸發一次 review；輸出原始官方連結 | 來源部分失敗不清空 baseline；事實發生日、發言時間、first_seen 分開；超出 coverage 不顯示「無風險」 |
| 2330 行程 | 一筆來源明確的法說時間與一個改期 fixture；報告分活動日／已觀察時間／來源 | 未找到未來行程呈現 unknown；不把法說或法定期限推成已確認財報發布日；保留版本變化 |
| 公司資訊 | 上市 2330，加一檔上櫃 fixture；確認名稱／市場／股數／單位與來源日期 | 市場轉板及股數變更保留原證據；最新股數不能回填過去估值 |
| 新聞延伸閱讀 | 先 2330 某一天索引，輸出來源、標題、連結與日期；逐筆抽查來源，摘要只依實際讀到內容 | syndicated 相同文章去重；無法取得全文不編摘要；抓取失敗與當日無符合新聞分開；資料授權確認前不公開整批新聞內容 |

每個切片須產出可閱讀報告與 source receipt，讓使用者看到新增內容、缺口、更新時間及相較上次的改變。unit fixture、真實來源成功、手動 GitHub Actions、自然 schedule 分開記錄，不用測試通過替代 operational acceptance。

## 本次存取證據與限制

1. Web 可讀：官方 data.gov.tw metadata、TWSE 條款、FinMind 文件與 upstream、yfinance／twstock upstream、台積公司 IR；Yahoo 上述頁面的內容來自 web search 回傳的自有網域索引。
2. Web direct open：Yahoo 2330 的 revenue／calendar／news／profile（有無 `.TW`）回報 404；Yahoo terms direct open 回報 999，但 web search 可讀條款原文。TPEx OpenAPI 入口回報 403；TWSE 幾個 live JSON endpoint 回報工具無法存取。這些是工具觀察，並非已證明服務整體故障。
3. 官方 CSV 連結可由 data.gov.tw 追到實際 URL；web reader 回報 unsupported content-type，未解析 CSV 數值。Shell 一般 `urllib` 嘗試因 sandbox DNS 無法解析而失敗；未 escalation、未繞過限制。
4. 因此尚無本次 runner 上 Yahoo／FinMind／TPEx 資料抓取成功或跨來源數值一致的 live 證據。後續依上述最小切片補上，不把此限制擴大成整個台股 workflow 都不能前進。
