# TW17 多標的研究架構與逐檔隔離設計規範

## 1. 專案背景與目標

依據 [Issue #65: [TW17] 擴至既有台股 10 檔，逐檔隔離與適用性](https://github.com/iceboxi/market-research/issues/65) 及 [Issue #48 Parent Epic](https://github.com/iceboxi/market-research/issues/48)，在 `2330.TW`（台積電）端到端研究與工作區驗收完成後，下一步為擴展至 `config/markets.yaml` 中定義的 10 檔台股候選清單。

**核心目標**：
- 讓既有 10 檔台股標的皆能取得固定研究與 coverage 狀態。
- **逐檔隔離（Fault Isolation）**：單一標的之資料來源失敗、連線超時、缺欄位或解析異常，不得中斷或影響其他標的之正常處理與發布。
- **模型適用性明確標示**：嚴格區分一般產業與金融控股業；金融業不套用一般製造業之營業利益、營業現金流、自由現金流（FCF）與 P/FCF 估值模型。
- **維持單一 State Owner**：沿用既有 `research-state` 分支結構與對帳出版流程，不引入其他 main writer。

---

## 2. 10 檔候選標的清單與分類

依據 `config/markets.yaml`：

| 標的代碼 | 公司名稱 | 產業別 | 研究模型分類 | 估值模型適用性 |
| :--- | :--- | :--- | :--- | :--- |
| `2330.TW` | 台積電 (TSMC) | 半導體晶圓代工 | 一般產業（製造業） | 適用（FCF / TTM P/E） |
| `2303.TW` | 聯電 (UMC) | 半導體晶圓代工 | 一般產業（製造業） | 適用（FCF / TTM P/E） |
| `2454.TW` | 聯發科 (MediaTek) | IC 設計 | 一般產業（IC 設計） | 適用（FCF / TTM P/E） |
| `2317.TW` | 鴻海 (Foxconn) | 電子代工製造 (EMS) | 一般產業（硬體製造） | 適用（FCF / TTM P/E） |
| `2382.TW` | 廣達 (Quanta) | 電腦及週邊設備 (ODM) | 一般產業（硬體製造） | 適用（FCF / TTM P/E） |
| `2308.TW` | 台達電 (Delta) | 電子零組件 / 電源 | 一般產業（硬體製造） | 適用（FCF / TTM P/E） |
| `3711.TW` | 日月光投控 (ASE) | 半導體封裝測試 (OSAT) | 一般產業（製造業） | 適用（FCF / TTM P/E） |
| `2881.TW` | 富邦金 (Fubon) | 金融控股業（壽險/銀行） | 金融控股業 | **不適用（not_evaluated）** |
| `2882.TW` | 國泰金 (Cathay) | 金融控股業（壽險/銀行） | 金融控股業 | **不適用（not_evaluated）** |
| `2891.TW` | 中信金 (CTBC) | 金融控股業（銀行/人壽） | 金融控股業 | **不適用（not_evaluated）** |

---

## 3. 金融控股業模型適用性規範（Domain Rules）

### 3.1 為什麼一般產業財務與估值模型不適用於金融控股公司？
1. **無營業毛利與營業成本概念**：金融業損益表核心為淨利息收益（Net Interest Income）、手續費收益、投資損益與保險業務淨收益，不具備一般製造業之「營業收入 − 營業成本 = 營業毛利」。
2. **現金流量表結構差異**：銀行的放款與存款吸收、保險公司的保費收取與準備金提存均計入現金流量，其「營業現金流」並非營業盈餘的真實現金轉化，無法計算 `FCF = 營業現金流 − 資本支出`。
3. **高槓桿為核心營運模式**：金融業負債主要為客戶存款與保險責任準備金，不可與一般企業之「公司債與銀行長短期借款」相提並論；計算「淨現金（現金 − 有息負債）」在金融業毫無財務意義。

### 3.2 系統契約定義
針對 `2881.TW`、`2882.TW`、`2891.TW`：
- `readiness["instrument"] = "candidate_for_financial_holding_research"` 或 `"financial_holding_unsupported_by_industrial_model"`
- `readiness["valuation"] = "not_evaluated"`（絕不強制計算 P/FCF 或 EV-bridge）
- `readiness["financial"]`：
  - 若已建立金融業專屬損益對帳表，標示 `available`；
  - 若僅有一般工業版財報解析器，標示 `financial_holding_parser_unavailable` 或 `not_evaluated`。
- `readiness["technical"]`：行情資料（TWSE STOCK_DAY）正常支援，標示 `available`。
- `readiness["events"]`：重大訊息與除權息公告正常支援，標示 `available`。
- `readiness["trade_plan"] = "not_evaluated"`
- `readiness["recommendation"] = "not_available"`

---

## 4. 逐檔隔離架構（Per-Stock Fault Isolation）

### 4.1 核心原則：Fail-Soft & Zero Cross-Contamination
在批次研究迴圈中：
```python
for symbol in tw_universe:
    try:
        process_stock(symbol)
    except Exception as exc:
        record_stock_failure(symbol, exc)
        continue  # 保證其他標的繼續執行
```

### 4.2 狀態保存分檔結構
移除 `scripts/research_state.py` 內部的 `2330.TW` hardcode，將存儲路徑標準化：
- 快照路徑：`snapshots/tw/{symbol}/{snapshot_id}.json`
- 標的主題：`subjects/tw/{symbol}.json`
- 檢查點：`checkpoints/tw/{symbol}.json`
- 出版紀錄：`publications/tw/{symbol}/{publication_id}.json`
- 變更通知：`notifications/tw/{symbol}/{notification_id}.json`

### 4.3 異常狀態分類
當某標的發生異常時：
1. **Network / HTTP Timeout / Rate Limit (429)**：
   - 記錄該標的狀態為 `execution.status = "degraded"`，原因為 `source_timeout`。
   - 保留前一版本快照（last_good snapshot），不更新 `last_success_id`。
2. **Missing Columns / Parser Failure**：
   - 記錄 `readiness[module] = "unavailable"`，錯誤細節存於 `execution.notes`。
   - 其他模組（如行情、事件）若成功仍正常存入快照。
3. **Atomic State Write**：
   - 各標的獨立生成快照物件，最後統一由 `save_batch()` 一次提交 Git commit，或逐檔建立 state records；單檔錯誤不寫入該檔新快照，不污染已對帳之歷史。

---

## 5. API 預算控制與全市場快照共用（Resource & Quota Sharing）

### 5.1 共用全市場日快照
- **TWSE 全市場收盤與本益比表（BWIBBU_ALL）**：
  一次請求取得全市場上市公司代碼、本益比、殖利率與股價淨值比。10 檔標的共享此一份快照，不需要發出 10 次請求。
- **TWSE 每日個股收盤行情（STOCK_DAY）**：
  每日收盤行情若透過日報表或逐檔端點，嚴格控制間隔（請求間距 ≥ 1.0 秒），避免觸發 TWSE 429 限制。
- **MOPS 公開資訊觀測站重大訊息（t187ap04_L）**：
  當日全市場重大訊息清單一次取得，本地過濾 10 檔標的事件。

### 5.2 請求配額與執行時間紀錄
每個快照物件之 `attribution` 與 `execution` 節點中記錄：
- `request_count`: 該標的專屬之外部 API 呼叫次數。
- `shared_requests_used`: 引用之共用全市場快照編號。
- `duration_ms`: 該標的研究運算耗時。

---

## 6. 靜態研究工作區（Research Workspace）整合

現有 `src/market_research/research_site.py` 已經完整具備多標的呈現架構：
1. **標的搜尋選單（Stock Search Picker）**：動態依據 `site-data` 中的 `stocks` 陣列進行篩選與切換。
2. **標的就緒度面板（Readiness Ribbon）**：不同標的依據其自身之 `readiness` 物件顯示各自的檢驗代碼。
3. **無估值情境優雅降級**：當金融股 `valuation = "not_evaluated"` 時，工作區顯示標準空狀態提示（`"此研究版本沒有估值情境，估值狀態：未評估"`），不破壞頁面結構。
4. **URL 同步**：支援 `?symbol=2303.TW` 或 `?symbol=2881.TW` 直接定位。

---

## 7. 驗收階層與推進步驟

1. **Unit / Contract Tests**：
   - 驗證 `research_state.py` 支援任意合法 TWSE symbol。
   - 驗證金融股進入時，模型自動標明為 `not_evaluated`。
   - 驗證批次處理時，單檔 mock failure 不中斷其他標的。
2. **Fixture Integration Tests**：
   - 提供至少一檔非金融業（如 `2303.TW` 或 `2454.TW`）與一檔金融業（如 `2881.TW`）之完整靜態 fixture，驗證報表生成與工作區渲染。
3. **Live Acceptance (TW17 Gate)**：
   - 在 GitHub Actions 執行擴大後的 10 檔批次掃描，產出 10 檔快照與發布紀錄，確認無跨標的污染與崩潰。
