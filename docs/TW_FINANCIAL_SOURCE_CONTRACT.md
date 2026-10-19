# 2330 免費財報來源採用契約

本契約承接 [TW05 #50](https://github.com/iceboxi/market-research/issues/50) 與已確認的 [spec](design/tw-workflow-spec.md)。文獻、程式測試、runner 實取與正式導入各自驗收；最新 Run／SHA／Artifact 證據留在 Issue，不在文件維護第二份任務狀態。

## 選型與出口

| 路徑 | 角色與目前採用邊界 | 帳號／quota | 公開出口 |
| --- | --- | --- | --- |
| FinMind 單股三表 REST | 2330 當下研究的候選；須逐次通過 issuer、period、schema、單位與代表性科目對帳，尚非 production adapter | 不送 token；Free 單股，文件300次／小時，註冊600；live是否免費另看receipt | raw禁止再散布；必要精簡數值／衍生值各自not_verified；probe只輸出metadata及不含數值／差額的結果 |
| TWSE 一般業損益／BS OpenAPI | 官方開放資料與允許公開數值的獨立來源；仍需確認同period／scope／單位，未補足CF | 無token；未確認統一SLA／quota，低頻取樣 | 兩個確切dataset適用OGDL1.0並須顯名；不把授權擴大到MOPS／IR |
| TSMC IR四頁合併簡明財報 | 2330的獨立oracle與人工備援；2025年度、2026上半年分開；不是通用全市場adapter | 免費閱讀；HTTP403即停止此路徑，不繞過封鎖 | 原文／全文不公開保存；必要數值出口not_verified，先保留URL／頁碼／hash／結果 |
| Yahoo／yfinance | 人工參照與待驗證候選；本probe不另發Yahoo請求，不以它繞過IR的403 | 無可靠免費quota承諾；條款與429限制仍適用 | 未成立，不作正式三表出口 |

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
