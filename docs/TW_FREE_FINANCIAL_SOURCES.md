# 台股免費財報與估值 inputs 來源調查

查核日期：2026-10-19（Asia/Taipei）。範圍：年度／季度損益、資產負債、現金流、EPS、股數與估值 inputs。這是規劃用研究筆記；供應者文件可行性、少量網頁讀取、production live acceptance 分開記錄。

目前交付範圍已確認先完成 2330 整條流程；可公開保存來源允許的精簡證據。條件未知的 raw payload／PDF 只留下 metadata／連結，不新增私人儲存。**當下／向後累積的研究先交付；不以還原歷史首次公開時刻作為當下報告的前置條件。**

## 結論與建議次序

**台股三表有免費候選路徑，不需要等待 `SEC_USER_AGENT`。** 建議先以 FinMind 單股三表、TWSE 開放資料與台積公司 IR 做小樣本選型，台積公司 IR 財報作獨立數值 oracle。選型同時核對實際 coverage 與本專案公開報告／證據保存的可用範圍，通過後才接進 `2330.TW` 最新研究；不能只因 FinMind Free 可查詢，就推定適合公開資料出口。是否能公開保存／重發布原始資料，需依各來源分別判斷，不能由 SDK license 推定。

| 路徑 | 能補的能力 | 免費／帳號／額度 | 2330 證據與現況 | 建議角色 |
| --- | --- | --- | --- | --- |
| FinMind REST API | 三表、基本 EPS、股利；歷史 PER/PBR/殖利率另有 dataset | 單股三表在 Free；文件列每小時 300 次、註冊 600 次；Free 限非商業，實際配額仍需確認 | 官方三表範例直接使用 `2330`；本次未成功取得 live JSON | 內部非商業研究的優先候選，先驗證單股／少量季度 |
| TWSE OpenAPI／政府資料開放平臺 | 最新損益、資產負債、公司基本資料及發行股數；官方市場倍數 | 所查特定資料集標示免費、政府資料開放授權條款第 1 版；不需付費 SDK | catalog 有一般業財報與股數欄位；本次 raw API 未取得 | 既有台股來源延伸、官方核對與較明確的開放資料輸出 |
| 台積公司 IR | 2330 年度與期中完整財報，季度簡明三表、EPS、加權平均股數 | 網頁與 PDF 可免費閱讀，未要求帳號；未找到大量擷取或再散布的全面授權 | 已開啟 2025 全年、2026 上半年完整 PDF，以及 2026 Q3 四頁簡明三表 | 2330 的具體備援與獨立 oracle；保留逐公司 adapter 成本 |
| FinLab | 三表／EPS、股價、財務指標與發布日對齊工具 | 需登入；現行免費台股資料截至 2023-12-31，最新需 VIP | 官方 EPS catalog 有台股歷史；本次未登入驗證 2330 | 舊年度研究與工具參考；不選作免費最新資料主路徑 |
| Yahoo 股市／Yahoo Finance＋yfinance | 頁面三表、EPS；yfinance 有年度／季度財報與股數 API | SDK 免費；Yahoo 沒有在所查資料提供可依賴的免費額度承諾，使用條款另有自動存取限制 | 本次 2330 台灣三表網址未成功取得，國際站回 429，停止重試 | 人工參照與待驗證候選；不作第一個無人排程來源 |
| twstock | 台股價量、證券代碼；不補三表 | MIT code；實際資料權利仍看 TWSE／TPEx | upstream 有 `Stock('2330')` 範例 | 只有既有行情 adapter 確實需要時才評估，不為補財報新增它 |

矩陣依據：[FinMind 基本面](https://finmind.github.io/tutor/TaiwanMarket/Fundamental/)、[FinMind 方案](https://finmind.github.io/Pricing/)、[TWSE catalog](https://openapi.twse.com.tw/)、[TWSE 損益資料集](https://data.gov.tw/dataset/91998)、[公司基本資料](https://data.gov.tw/dataset/18419)、[TSMC 財務報表](https://investor.tsmc.com/chinese/financial-reports)、[FinLab 免費範圍](https://finlab.finance/docs/details/get_data/)、[yfinance upstream](https://github.com/ranaroussi/yfinance)、[twstock upstream](https://github.com/mlouielu/twstock)。

「文件可行」不代表「已接進 repository」。目前台股 `twse_fundamentals` 只處理公司 profile 與月營收，沒有三表 history；`evaluate_valuation` 直接排除非美股市場，後續也要求 USD／`annual_10k`。因此找到來源後，仍須交付台股 normalization 與台股 valuation 契約；單換來源不會自動完成估值。證據：[fundamentals.py:58](../src/market_research/fundamentals.py#L58)、[fundamentals.py:83](../src/market_research/fundamentals.py#L83)、[valuation.py:19](../src/market_research/valuation.py#L19)、[valuation.py:30](../src/market_research/valuation.py#L30)。

## FinMind：最值得先做小樣本驗證

- 三表 dataset 為 `TaiwanStockFinancialStatements`、`TaiwanStockBalanceSheet`、`TaiwanStockCashFlowsStatement`；單股帶 `data_id` 為 Free，全市場不帶 `data_id` 的下載需要較高方案。三表文件涵蓋上市、上櫃、興櫃，並提供 `2330` 範例。文件宣告損益歷史自 1990、資產負債自 2011、現金流自 2008，這是 dataset 整體區間，不能推定每家公司逐期完整。[基本面文件](https://finmind.github.io/tutor/TaiwanMarket/Fundamental/)、[供應者 dataset catalog](https://github.com/FinMind/FinMind-MCP/blob/master/knowledge/datasets.md)
- REST `GET https://api.finmindtrade.com/api/v4/data`，帶 `dataset`、`data_id=2330`、`start_date`、`end_date`；SDK 可以不用安裝，既有 HTTP client 即可做 adapter。免費額度文件為每小時 300 次、註冊會員 600 次；超額範例為 HTTP 402，應列為 quota 狀態，不無限 retry。配額與方案會變，啟用時再讀帳號的 `api_request_limit`。[方案與價格](https://finmind.github.io/Pricing/)、[用量與超額回應](https://finmind.github.io/api_usage_count/)
- 三表回傳 `date, stock_id, type, value, origin_name`。upstream SDK 明載三表 `date` 是財報期間截止日，**不是公告日**。應保留原始 `type`／`origin_name` 並建立明確 mapping；不存在的科目不能補零。[DataLoader source，三表 methods](https://github.com/FinMind/FinMind/blob/master/FinMind/data/data_loader.py#L881)
- 官方對 `EPS` 特別說明是單季基本 EPS；遇股票股利／分割，各季股數基準可能不同，不能一律以四季 EPS 相加推得可比較的 TTM EPS。其他 flow 科目的單季／累計語意與金額單位，仍要用跨 Q1、Q2、Q3、Q4 的公司原始財報核對，不能因 `date` 是季末就認定單季。[EPS 說明](https://finmind.github.io/tutor/TaiwanMarket/Fundamental/#taiwanstockfinancialstatements)
- `TaiwanStockMarketValue` 在基本面文件列為 Backer／Sponsor，不能把它當作免費股數／市值歷史來源。可先用官方當期股數與同日行情形成「當期市場觀察」，但這不能替代年度 diluted-average shares，也不能回填歷史股數。[市值 dataset 權限](https://finmind.github.io/tutor/TaiwanMarket/Fundamental/#taiwanstockmarketvalue)

軟體與資料使用必須拆開：FinMind Python SDK 為 [Apache-2.0](https://github.com/FinMind/FinMind/blob/master/LICENSE)；服務 [Pricing](https://finmind.github.io/Pricing/) 區分非商業與商業方案，並禁止原始資料再散布／鏡像 API。其 [資料授權說明](https://finmind.github.io/Disclaimer/) 要求自行確認對外公開的原始來源授權；Free 不是可把整批 JSON 提交公開 repo 的授權。這只影響使用 FinMind 的資料出口與用途，不應阻止其他來源、報告 renderer、health feedback 或排程觀測開發。

供應者 [2026-09-06 校正公告](https://finmind.github.io/WhatIsNew/) 明載曾回補 2024 上半年資產負債缺漏，另有後續下市／終止公開發行公司的原始歷史已無法補齊。推論：資料目前存在，不等於當時已存在或包含完整下市樣本；歷史回測需另設 revision 與 survivorship gate。

## TWSE：最新 snapshot、股數與市場估值觀察可分別交付

所查 [OpenAPI catalog](https://openapi.twse.com.tw/) 有 `t187ap06_L_ci`（一般業損益）與 `t187ap07_L_ci`（一般業資產負債）；金融、金控、保險、證券期貨、異業各有不同端點。不能把一般業欄位套在所有產業。這次未證實 catalog 有同等免費現金流端點、任意歷史年度／季別查詢及歷史公告版本，先列為未驗證，而非宣告官方永遠不提供。

[損益 dataset 91998](https://data.gov.tw/dataset/91998) 列出出表日期、年度、季別、營收、營業利益、母公司業主淨利與基本 EPS（元），標示免費、每 3 個月更新。[資產負債 dataset 94831](https://data.gov.tw/dataset/94831) 的官方搜尋索引列出同一資料集與授權網址；本次全文存取 timeout，欄位與單位仍需 live acceptance。

[基本資料 dataset 18419](https://data.gov.tw/dataset/18419) 有實收資本額、每股面額、私募股數、特別股，以及「已發行普通股數或 TDR 原股發行股數」，標示免費、每月更新。它適合顯示帶資料日期的 issued shares snapshot；不能當成 daily current float、EPS 加權平均股數，亦不能以最新值倒填過去市值。

官方 [個股日本益比、殖利率及股價淨值比](https://www.twse.com.tw/zh/trading/historical/bwibbu-day.html) 有依日期查詢，說明資料自 2005-09-02 提供。官方本益比使用已申報近滿四季財報及參考股數，EPS 為 0 或負數不計算；亦有「財報年／季」資訊。這條路徑能先產出明確標為官方市場比率的估值觀察，**不需要先自建完整 DCF**，但不能宣稱因此已有合理價、進場價或停損價。此頁面資料自動取得與公開輸出的條款，應對應到確切開放 dataset 再驗收。

已核對的特定政府開放資料適用 [政府資料開放授權條款第 1 版](https://data.gov.tw/license)，需標示來源；TWSE [一般網站條款](https://www.twse.com.tw/zh/terms/use.html) 對其他內容仍保留權利，不能將特定 dataset 的開放授權擴張到整站或所有 MOPS 文件。API 文件本身未提供本研究可確認的 SLA／統一 request quota，adapter 應低頻、cache、逾時即留下 source status。

## Issuer IR：2330 已有具體原始文件可用

[台積公司中文財務報表頁](https://investor.tsmc.com/chinese/financial-reports) 提供跨年度合併財報，列有 2025 全年、2026 第一季與上半年。本次已開啟 [2025 全年 PDF](https://investor.tsmc.com/sites/ir/financial-report/2025/TSMC%202025Q4%20Consolidated%20Financial%20Statements_C.pdf)（85 頁）與 [2026 上半年 PDF](https://investor.tsmc.com/sites/ir/financial-report/2026/TSMC%202026Q2%20Consolidated%20Financial%20Statements_C.pdf)（61 頁）。2025 全年附註明載金額除另註外為新台幣仟元，並分別列報告通過日期與財報期間，兩者不可混用為公開揭露時間。

[2026 Q3 結果頁](https://investor.tsmc.com/english/quarterly-results/2026/q3) 直接連到 [四頁 Financial Statements PDF](https://investor.tsmc.com/english/encrypt/files/encrypt_file/reports/2026-10/3a94d1034b9e6b22446b674f7aaf3d088a12a193/FS.pdf)。本次讀取並對第 2、4 頁執行 screenshot 核對；文件有：

| 文件頁 | 可取得 inputs | normalization 注意事項 |
| --- | --- | --- |
| 第 1 頁 | 現金、借款／公司債、資產、母公司權益等 | 資產負債是期末 snapshot；NTD 與 USD 欄位並列 |
| 第 2 頁 | 單季損益、diluted EPS、diluted weighted-average shares | 金額為百萬元；EPS 例外；股數標示百萬股 |
| 第 3 頁 | 前三季累計損益與 EPS／股數 | 不得與第 2 頁單季欄直接相加 |
| 第 4 頁 | 前三季累計及單季 CFO、capex、融資 cash flow | capex 是支出負號；先統一符號與期間再計 FCF |

該簡明 PDF 明載 `Unaudited`；不能因它放在 IR 就標為完整查核財報。文件亦載 1 ADR = 5 ordinary shares，台股應用普通股／TWD，不能混用 TSM ADR 的 USD per-share 值。完整年報／期中核閱資料與 earnings-release 簡明數字各保留 `statement_basis`、`assurance`、文件 URL 與頁碼。

這是**可立即做 2330 adapter 與 oracle 的原始資料路徑**，但不證明其他 pilot 公司有相同網站格式。來源頁有著作權聲明，未找到全面再散布條件；這是未知，不能改寫成「禁止研究」或「需要逐項另行申請」。依已確認的範圍，條件未知的完整文件不另存公開／私人儲存，只保留 URL、頁碼、hash、擷取時間等 metadata；來源允許的精簡證據照常交付。解析失敗只降低這家公司／這份文件的能力，不中斷其他有效來源。

### 可直接評估的開源 PDF parser

建議首選 [pdfplumber](https://github.com/jsvine/pdfplumber) 做 2330 表格抽取：upstream 提供 `Page.extract_tables()`、指定區域裁切、字元位置及 visual debugging，且列出 Python 3.12 的測試支援；程式是 [MIT](https://github.com/jsvine/pdfplumber/blob/stable/LICENSE.txt)。先讀本次可解析的 Q3 四頁 PDF，明確選擇 NTD 與單季／累計欄位，用獨立人工抄錄值核對；不把「抽出字串」當成三表驗收完成。此處只確認工具與用途，未安裝或實跑本專案 parser。

較小的文字抽取需求可用 [pypdf](https://github.com/py-pdf/pypdf)：`PdfReader(...).pages[n].extract_text(extraction_mode="layout")`，license 為 [BSD 三條件](https://github.com/py-pdf/pypdf/blob/main/LICENSE)。其 [官方說明](https://pypdf.readthedocs.io/en/stable/user/extract-text.html) 明載不提供 OCR，PDF 也沒有可靠的表格語意層。兩者的 code license 都不會變更輸入財報文件的使用條件；不預設要同時導入兩套。

## 資料實際存在、明確限制與未知條件

| 類型 | 已知狀況 | 對當下交付的處理 |
| --- | --- | --- |
| 官方文件實際有資料 | 2330 IR 完整年度／期中與 Q3 簡明 PDF 可讀，有三表、EPS、股數 | 可做 parser、oracle 與當下研究；揭露原始文件 assurance／單位／期別 |
| 來源明確限制 | FinMind Free 非商業、不得再散布原始資料；FinLab 免費截止日；Yahoo 已查條款含自動收集限制 | 只影響該來源用途／資料出口；必要時選其他已可用路徑 |
| 條件未知 | IR 全文件重發布、Yahoo 各部署情境的允許取得方式、部分 API 原始 payload 的當次存取 | 未確認的內容只存 metadata／連結；不將未知推成整條 workflow 停工 |
| 歷史證據尚不足 | 財報期末不等於公開日，未證明完整歷史版本 | 限制歷史回測宣稱；當下 observed facts 與後續 snapshot 比較可先做 |

## FinLab：免費歷史有用，免費最新不成立

現行 [官方 data.get 文件](https://finlab.finance/docs/details/get_data/) 明載免費台股資料截至 2023-12-31，最新已更新資料需 VIP；下載前登入，自動化還需對應憑證。這不是可用免費 trial 長期支撐最新排程的證據。

[EPS 官方 catalog](https://finlab.finance/data/financial-statements/eps) 顯示 `financial_statement:每股盈餘`、2013 起的台股歷史與免費截止日；[data API](https://finlab.finance/docs/reference/data/) 可用 `data.search(..., details=True)` 讀取 `auth`／`free_until`。其他三表科目、股數、2330 缺值與單位仍應逐項查 catalog／樣本，不依套件有「財報」名稱推定全部滿足。

FinLab 提供發布日對齊功能，但不因此替本專案證明所有歷史版本可重建。[2026-09-28 change log](https://finlab.finance/docs/change-log/) 表示新的 `as_of`／`version` 存取為付費、實驗性、當時約保留兩週，財報另用 `financial_statement_versions`；更正值可能無法還原當時數值。最新研究與嚴格歷史回測仍需分開驗收。

目前已查的 [finlab 2.2.10 發行 metadata](https://pypi.org/project/finlab/2.2.10/) 標示 `GPL-3.0-or-later`，不可沿用舊印象寫成 MIT；實際導入時核對選定版本。服務 [使用條款](https://studio.finlab.finance/en/terms) 對內容重製／散布與 API 商業使用另有約定，Python code license 不能取代資料授權。

## Yahoo／yfinance：保留候選，先驗證可用性與使用條件

[yfinance upstream](https://github.com/ranaroussi/yfinance) 是獨立社群工具，非 Yahoo 官方背書；程式 Apache-2.0，README 提醒實際資料權利依 Yahoo 條款。API 文件有 [年度／季度／trailing income statement](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.get_income_stmt.html)、[balance sheet](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.get_balance_sheet.html)、[cash flow](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.get_cashflow.html)。

目前 upstream [fundamentals source](https://github.com/ranaroussi/yfinance/blob/main/yfinance/scrapers/fundamentals.py#L106) 註記 Yahoo 一般最多回 4 年或 5 季；source 以 `asOfDate` 對齊並取 `reportedValue.raw`，不代表附帶歷史公開日／當時版本。推論：即使 2330 三表成功回傳，也較適合當下研究或交叉比對，不能承諾長期 point-in-time 回測。

本次 `https://tw.stock.yahoo.com/quote/2330.TW/income-statement` 未取到可解析內容；相同 symbol 的 balance-sheet／cash-flow-statement 回 404，國際 Yahoo Finance balance sheet 回 429，因此停止重試。這是本工具／當次請求的觀測，不足以斷言一般瀏覽器永遠無法查看，也不能冒稱 2330 的三表 coverage 已通過。

[Yahoo 官方服務條款](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html?ncid=mbr_idnedulnk00000001) 的搜尋索引明載自動收集需事先明確許可；條款全文本次回 999。臺灣條款的本輪查核見[行情與事件來源筆記](TW_FREE_MARKET_EVENT_SOURCES.md#yahoo-股市頁面內容確實存在直接抓取仍未通過)。直接抓頁面與透過 yfinance 都不因免費／開源自動取得大量抓取或再發布權。建議保留人工原文連結；若要無人排程，先完成「適用允許方式＋2330 coverage＋穩定性」局部 gate，不讓此候選阻塞其他可用資料路徑。

## 可直接納入交付條件的驗證範圍

以下是本研究提出的驗收建議，尚未執行 production 驗收：

1. **先交付當下 2330 研究。** 小量取得三表與當期 EPS，帶來源、原始單位、期間與 `retrieved_at`；已讀到的當期資料可用於當下研究。缺少歷史公開時間時，僅標記歷史回測能力未通過，不把最新研究整段設成不可用。
2. **用 IR 跨季 oracle 驗證 normalization。** 至少含一個 Q1、一個 Q2／Q3、一個全年：檢查單季／累計、TWD 元／仟元／百萬元、CAPEX 符號、普通股／ADR、basic／diluted EPS 與不同股數定義。預期值由來源文件頁面獨立擷取，不從 adapter 自己重算後當 oracle。
3. **四種日期分開。** `period_end`、來源公開日、供應者收錄日、擷取日各自記錄；`period_end`／出表日期／董事會通過日不能默認為原始公開日。歷史回測只使用在 as-of 已能證明可取得的版本；缺證據為 `not_evaluated`。
4. **估值觀察分兩層。** 官方 PER/PBR/殖利率可作帶日期的觀察；由 FCF／EPS 產生情境，另要求可比較期間、可靠 denominator 與明確模型。不能把資料來源完成算成合理價或買賣價完成。
5. **來源失敗有輸出。** 區分需要 token、quota、timeout、HTTP 封鎖、空資料、單位／期別未知、授權出口未確認、來源差異；本次 run 仍交付可用部分。只使用已通過驗證且允許的 fallback，不以「成功取得任何數字」掩蓋來源差異。
6. **依已確認的輸出範圍保存。** Facts provenance、fixture、raw payload、完整 PDF、Actions Artifact 分別記錄來源條件；公開保存來源允許的精簡證據，條件未知者只留 metadata／連結，不新增私人儲存。若某來源明確限制原始資料公開，縮小到被允許的輸出或換來源，不把限制擴張成整個 workflow 停工。

## 本次 read-only 查核紀錄與仍待確認項目

| 查核 | 實際結果 | 能支持的結論 |
| --- | --- | --- |
| FinMind 官方文件、方案、資料授權、SDK source | 成功閱讀 | 三表單股 Free 候選、參數、schema、期間非公告日與用途限制已確認 |
| FinMind 2330 2025 Q1 三表各 1 次 JSON 請求 | web 工具不可訪問；本地標準 HTTP 請求 DNS 解析失敗 | **未完成 live JSON 驗證**；不能認定 FinMind 服務本身故障或 2330 無資料 |
| TWSE swagger／政府損益及基本資料 catalog | 可讀；raw API 未取得，資產負債 catalog 全文 timeout | 端點與特定 dataset 的欄位／開放授權可規劃；payload freshness 未驗證 |
| TSMC 2025 全年、2026 H1、2026 Q3 簡明三表 PDF | 可讀；Q3 第 2、4 頁 screenshot 已執行 | 2330 有具體可讀原始文件，單季／累計與單位不同必須處理 |
| FinLab docs／EPS catalog／PyPI metadata | 可讀，未登入或下載資料 | 免費截止日與特定版本 code license 已確認，未證明帳號可取最新資料 |
| Yahoo 2330 三表網頁 | 台灣站未成功讀取，國際站 429；未繞過封鎖 | 僅為待驗證候選，本次不宣稱來源穩定或 coverage 通過 |

待確認項目應依能力掛局部 gate：FinMind 2330 真實回應與單位／flow basis、當期欄位完整性、來源使用情境；TWSE JSON 的最新期別與官方倍數可用出口；issuer IR 擷取／保存範圍；最新 diluted shares 與歷史公開日／版本。這些不阻塞不依賴它們的報告呈現、來源 health 與自然排程回饋。
