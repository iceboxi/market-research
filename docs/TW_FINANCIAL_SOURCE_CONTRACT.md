# 2330 免費財報來源採用契約

本契約承接 [TW05 #50](https://github.com/iceboxi/market-research/issues/50)、[TW06 #58](https://github.com/iceboxi/market-research/issues/58)、[TW07 #59](https://github.com/iceboxi/market-research/issues/59)、[TW10 #55](https://github.com/iceboxi/market-research/issues/55)、[TW11 #60](https://github.com/iceboxi/market-research/issues/60)、[TW12 #62](https://github.com/iceboxi/market-research/issues/62) 與已確認的 [spec](design/tw-workflow-spec.md)。文獻、程式測試、runner 實取與正式導入各自驗收；最新 Run／SHA／Artifact 證據留在 Issue，不在文件維護第二份任務狀態。

## 第一個 Gate：2330 資料完整性矩陣（Data Completeness Matrix）

| 資料項目 | 來源 | 實際期間 | 驗證結果 | 是否可進研究 |
| --- | --- | --- | --- | --- |
| 年度三表（損益表、資產負債表、現金流量表） | FinMind（`TaiwanStockFinancialStatements` / `TaiwanStockBalanceSheet` / `TaiwanStockCashFlowsStatement`）＋ TWSE OpenAPI（`t187ap06_L_ci` / `t187ap07_L_ci` / `t187ap45_L`）交叉對帳 | FY2023、FY2024、FY2025（三個完整會計年度，`2023-01-01` 至 `2025-12-31`） | **pass**（營收、毛利、營業利益、稅後淨利、歸屬母公司淨利、基本 EPS、營業現金流、CAPEX、自由現金流、現金、總資產、總負債、應付公司債、長期借款、權益、普通股股本全數到位且跨來源核對一致） | **是** |
| 季度／累計／TTM 財報與財務比率 | FinMind（2023Q1–2026Q2 共 14 季）＋ TWSE OpenAPI（`t187ap06_L_ci` 115Q2 累計損益、`t187ap07_L_ci` 115Q2 資產負債、`t187ap17_L` 獲利能力比率、`t187ap45_L` 單季歸屬母公司淨利） | 最新單季 2026Q2、最新累計 2026-H1（`2026-01-01` 至 `2026-06-30`）、連續四季 TTM（2025Q3–2026Q2） | **pass**（透過單季歸屬母公司淨利與累計損益表確定性辨識單季 vs 累計 YTD 口徑，無把累計當單季或把月營收當年度財報） | **是** |
| 股數／除權息與公司行動 | TWSE OpenAPI（`t187ap03_L` 已發行普通股數與實收資本額、`t187ap45_L` 各季股利分派與董事會決議日、`BWIBBU_ALL` 殖利率／本益比／股價淨值比）＋ FinMind（`TaiwanStockBalanceSheet` 普通股股本、`TaiwanStockDividendResult` 除息參考價與填息紀錄） | 2023–2026Q2 普通股股數（`25,932,071,000` 至 `25,932,370,067` 股，面額 10 元）與季配息紀錄（每股 3.0 → 7.0 元） | **pass**（已發行普通股數與資產負債表普通股股本÷10 完全吻合；季配息與除權息紀錄完整；稀釋加權平均股數未由免費 API 直接提供，明確標註改採普通股股數與基本 EPS 口徑） | **是** |
| 行情／重大公告與事件 | 既有日 K 行情 adapter（真實歷史 OHLCV 與最新交易日收盤）＋ TWSE OpenAPI（`t187ap04_L` 每日重大訊息、`t187ap05_L` 每月營業收入） | 最新完整交易日 OHLCV、近 12 個月營收（至 11509）、當日重大訊息與法說／股利事件 | **pass**（含價格基準 `unadjusted`、session 日期、SHA-256 驗證與重大訊息覆蓋邊界說明） | **是** |

## 選型與雙軌公開保存政策（Dual-Track Retention Contract）

| 路徑 | 角色與採用邊界 | 帳號／quota | 公開出口政策 |
| --- | --- | --- | --- |
| FinMind 單股三表與除息 REST | 2330 歷史三表（2023Q1–2026Q2）與除息結果的自動化計算來源；每次執行必與 TWSE OpenAPI 獨立對帳 | 不送 token；Free 單股 300 次／小時，GitHub-hosted Runner 實測 HTTP 200 | **禁止將 FinMind 原始 JSON payload 寫入 public repo 或 `research-state` 分支**；僅允許在研究計算後，將與 TWSE 對帳通過的衍生研究摘要、期間、hash 與對帳狀態呈現於報告與精簡 snapshot |
| TWSE OpenAPI（`t187ap03_L`、`t187ap04_L`、`t187ap05_L`、`t187ap06_L_ci`、`t187ap07_L_ci`、`t187ap17_L`、`t187ap45_L`、`BWIBBU_ALL`） | 政府資料開放授權條款第 1.0 版（OGDL-1.0）之官方權威來源；提供公司基本資料、月營收、當期累計損益表、期末資產負債表、獲利能力比率、單季盈餘與股利分派、交易所每日估值倍數 | 無 token；GitHub-hosted Runner 實測全部 HTTP 200 | 適用 **OGDL-1.0**，允許公開保存原始數值與衍生指標，並於報告與 snapshot 顯名標示來源機關與資料集 |
| TSMC IR 四頁合併簡明財報 PDF | 獨立人工／離線核對 oracle（2025 年度、2026 上半年） | 免費閱讀；GitHub-hosted Runner 因 Akamai CDN 回傳 HTTP 403，自動切換至 TWSE OpenAPI 對帳路徑，不繞過封鎖 | 原文／全文不公開保存；僅保留 URL、頁碼、hash 與對帳狀態 |

來源與條款的精確依據見 [使用條件查證](TW_SOURCE_USAGE_VERIFICATION.md)；既有 [免費來源筆記](TW_FREE_FINANCIAL_SOURCES.md) 提供候選背景。SDK或parser的程式license不決定資料使用權。

## 可重現取樣與資料 identity

`scripts/tw_source_probe.py` 固定2330，對FinMind三個dataset各取2025-01-01至2026-06-30，再各取TWSE一般業IS／BS與兩份IR簡明PDF。payload／PDF僅在process記憶體，不寫raw檔；公開輸出為`source_adoption.json`與`.md`。每來源最多兩次；timeout及502／503／504可再試一次，402／403／429立即分類停止；回應上限5MB，不重放MOPS form或改用代理繞過封鎖。

FinMind回傳`stock_id=2330`、有效ISO日期、唯一(date,type)與finite value才進內部比較。資料`date`是period end，不是publication；本次只記first_seen，`published_at=null`、historical point-in-time／revision lineage均not_verified。已知first_seen之後的當下研究可以逐步交付，不需先還原歷史首次公開時間。

| 代表科目 | FinMind dataset／concept | IR依據與轉換 |
| --- | --- | --- |
| cash／assets | BalanceSheet：CashAndCashEquivalents／TotalAssets | 第1頁，期末instant，USD與NTD欄位分開；只取NTD |
| revenue／net income | FinancialStatements：Revenue／IncomeAfterTaxes | 第3頁年度／H1累計；分別驗證sum_quarters或reported_ytd，不從季末日期推定 |
| CFO／CAPEX | CashFlowsStatement：CashFlowsFromOperatingActivities／PropertyAndPlantAndEquipment | 第4頁累計欄；CAPEX只取Acquisitions，禁止混用同名disposal proceeds；支出保留負號 |
| EPS／shares | FinMind EPS為basic；無本票確認的diluted-average shares mapping | 第2頁是單季diluted EPS／百萬普通股；不與basic EPS直接對帳，不把capital stock當股數；1ADR=5普通股不能混用 |

比較限對帳過的六個代表科目，不代表整張財報所有concept或全部period已成立。IR金額是NTD百萬元；只有FinMind原值按TWD與IR相差不超過0.5百萬元的獨立rounding範圍時，該欄才記unit matched。不自動嘗試倍率直到對上。多種aggregation同時匹配、缺值、scope／currency／label不唯一均不採用，缺值不補零。

Oracle文件：[2025年度簡明PDF](https://investor.tsmc.com/english/encrypt/files/encrypt_file/reports/2026-02/cb73d5f4e019a8f6d7a494a0f8f6c6da2dfc4ee2/FS.pdf)、[2026H1簡明PDF](https://investor.tsmc.com/english/encrypt/files/encrypt_file/reports/2026-07/114aaca0fea2050e96b91fffbab9ed04ba09cd92/FS.pdf)。年度BS／年度IS／年度CF欄的audited標示與單季、H1的unaudited標示分開；這不等於已取得完整核閱報告或查核意見。兩份4頁格式是明確、有限的驗收樣本，格式變更即降級，不做模糊名稱配對。

## 執行與後續 gate

安裝`uv sync --extra dev --extra source-probe --locked`，執行`uv run --no-sync python -m scripts.tw_source_probe --out source_adoption_output`。可選parser是pypdf6.21.1（BSD-3-Clause，由uv.lock固定），不新增第二套parser或正式報告runtime dependency。專用Actions僅contents:read，沒有排程、state／Issue／通知寫入；初次feature push可在全新runner產證據，後續可手動觸發。

`current_source_acceptance=reconciled_current_sample`只表示兩個樣本的六項代表值已對帳；不是三年財報、最新每季coverage、EPS／股數mapping、公開數值出口或正式導入已完成。pipeline綠燈也可能輸出not_verified。probe不直接修改TW06／TW07／TW12或#34原MOPS來源gate；來源、數值出口或完整性不足時下游維持needs-info，Issue記錄實際替代路徑與缺口。保存、差異、固定研究、通知等不依賴缺失的財報能力而停止。
