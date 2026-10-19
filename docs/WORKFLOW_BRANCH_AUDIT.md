# Workflows & Branches Audit — Issue #28，初版盤點

**盤點基準：** 2026-10-19，`main@ac6339ba`；包含 `main` 19 個 GitHub Actions workflow YAML、21 條遠端分支（3 條長期用途 + 18 條 feature/docs/fix）。這是**靜態 code/config 盤點**，不是宣稱某 workflow 實際成功或所有分支已可刪。

本文件是 Issue #28 的「低風險第一階段」：**不會停用、合併任何 Workflow，也不會刪除分支、修改 Settings 或繞過 #9/#14 的 live gates**。

## A. 19 個 Workflow 的使用面與風險

| YAML | 現有名稱 | 分類 / 觸發 | 主要用途與副作用 | 建議 |
| --- | --- | --- | --- | --- |
| `scan.yml` | EOD market scan | **[User]** 排程、手動、path-filtered push | 市場掃描／候選研究；在 schedule/dispatch 時寫 operations state、health Issue、prospective 等 | 保留正式入口，後續將驗收 push 與正式 schedule 的副作用分離 |
| `company-research.yml` | On-demand company research | **[User]** 手動、path-filtered push | 指定 ticker 研究、下載 Artifact；目前沒有正式交易行為 | 保留正式入口；push 測試日後可透過 CI 分工 |
| `event-watch.yml` | Official disclosure watch | **[User]** 排程、手動 | 官方事件觀察；持久化 `research-state/events`；**#9 migration 尚未完成，須停用至通過** | 保留，需完成 #9 後才正式啟用 |
| `watchdog.yml` | EOD schedule watchdog | **[Ops]** 排程、手動 | 查真正 schedule Run，異常時寫 incident Issues | 保留，#14 自然排程驗收仍需 |
| `test.yml` | Unit tests | **[CI]** PR、path-filtered push、手動 | 檢查依賴與單元測試，唯讀 | 必要 PR gate；注意 paths 與 required-check 的相容性 |
| `state-store-acceptance.yml` | State-store live acceptance | **[CI/Ops]** path-filtered push、手動 | 共用 state 端到端驗收；顯式 dispatch 可 bootstrap operations，具寫入權限 | 必須區分安全測試和正式遷移 |
| `sec-live-acceptance.yml` | SEC live annual financial acceptance | **[CI / Data]** 手動 | 真實 SEC 財報覆蓋驗收，需 `SEC_USER_AGENT` | 保留，實際資料來源 gate |
| `remote-acceptance.yml` | Correlated remote acceptance | **[CI]** 手動 | 驗收 dispatch 關聯，需 actions: write | 保留工程驗收；與 synthetic child 是關聯測試 |
| `synthetic-acceptance-child.yml` | Synthetic acceptance child | **[CI]** 被前者 dispatch、手動 | 接受 expected SHA/correlation，輸出合成 Artifact，唯讀 | 工程內部，勿當日常使用入口 |
| `ops-live-acceptance.yml` | Operations live acceptance | **[Ops/CI]** path-filtered push、手動 | 檢查排程 API，觸發實際 scan；有 actions: write | 保留運作驗收，需避免與自然 schedule 混淆 |
| `ops-validation.yml` | Operations permission smoke test | **[Ops/CI]** workflow 檔案 path-filtered push | 合成寫入權限／incident 測試，具 contents/issues: write | 只在需要時驗證；評估與 ops acceptance 是否重複 |
| `prospective-bootstrap.yml` | Prospective state bootstrap | **[Migration]** 明確手動確認 | 舊 prospective → canonical state 遷移；可寫 state | **#19 尚需人為 gate，不能停用／刪除** |
| `event-state-bootstrap.yml` | Official event state bootstrap | **[Migration]** 明確手動確認 | 舊事件狀態 → `research-state/events`；需先停用 watcher | **#9 尚未通過，不能停用／刪除** |
| `strategy-research.yml` | Isolated strategy research | **[Research]** 手動、path-filtered push | 獨立技術型態驗證、研究 Artifact | 保留共用策略實驗入口 |
| `backtest.yml` | Exploratory Sakata backtest | **[Research]** 手動、path-filtered push | 歷史回測研究（非真實成交） | 檢視與 strategy-research 功能重疊，先保留 |
| `holdout.yml` | Historical holdout quality evaluation | **[Research]** 手動、path-filtered push | 樣本外研究測試，無下單 | 必要策略有效性研究 gate |
| `research-gate.yml` | Research readiness gate | **[Research/CI]** 手動、path-filtered push | 組合 holdout 指標與研究准入條件 | 保留 gate，不與產品投資決策混為一談 |
| `final-acceptance.yml` | Final Sakata research acceptance | **[Research/CI]** 手動、workflow-file path push | 跨市場／型態綜合實驗 | 先評估與 isolated/holdout/gate 的差異，後續整合可共用 runner |
| `lock.yml` | Generate dependency lock | **[CI/Build]** 手動、path-filtered push | 產生 uv.lock，main 上可能 commit，具 contents: write | 保留工程用，評估改成 PR-only 提案避免主分支直接寫入 |

分類總覽：**3 個日常使用者入口 + 1 個排程監督 + 15 個工程／研究／驗收／遷移入口**。不代表 19 個每天都會執行；多數只在變更指定檔案或人工驗收時觸發。最終目標是**操作入口收斂**，不是為了數字強迫把安全隔離的寫入流程整合。

## B. Workflow 最終架構建議（先不執行）

1. **User-facing**：維持 3 個可辨識名稱，集中於 README/操作指南。後續經審查可用 `[User] EOD Scan`、`[User] Company Research`、`[User] Official Event Watch` 這類前綴，但 **改名可能影響跨 workflow references、監測及執行 gate**。
2. **CI**：將無副作用的 lint/unit/schema/adapter tests 保留為主要 Required PR gate；將成本較高的 live-source integration 獨立為驗收矩陣並記錄 head SHA／Artifact。**不要在未理解 status check 名稱和 path filter 前啟用嚴格 Branch Protection。**
3. **Research**：對 Sakata/backtest/holdout/final acceptance 先做執行路徑與 acceptance 差異對照；可共用 `workflow_call`／Composite Action 的依賴設置與 Artifact code，但不把不同研究門檻合併成同一結論。
4. **Ops & Migration**：state bootstrap 需要顯式授權、停用現有 writer、main-only 及舊/新 Authority；新規範驗收前 **不移除**。incident/watchdog 等保留獨立權限與副作用契約。是否封存單次 migration Workflow，依其 Issue 的正式 gate。
5. **Trigger audit**：檢查同一支分支 push 是否同時啟動 scan/backtest/research；可透過無副作用測試集中與 paths 過濾節省 Actions 資源，但不得讓 release/prospective/live test 被偷偷跳過。

## C. 21 條 Branch 盤點與清理條件

**永續／保留（3）：**
- `main`：唯一正式程式碼主線。
- `research-state`：正式、metadata-only state；**不是合併進 main 的 feature 分支**。
- `research-state-validation`：state 驗收用途；需先確認是否仍被 Actions 引用後再決定長期保留策略，現在不刪。

**已合併 PR 的同名分支（15，候選清理，尚未核對所有未合併獨立 Commit）：**

| 分支 | 已合併 PR | 清理前必要確認 |
| --- | --- | --- |
| `docs/codex-research-system-plan` | #10 | 比對 HEAD 與 PR head；設計文檔仍在 main |
| `feat/chat-f01-evidence-eligibility` | #23 | F01 合併，確定沒有額外 WIP |
| `feat/codex-issue-12` | #13 | state-store 已被 main 接收，不涉及 validation branch |
| `feat/company-research-v2` | #4 | 比對合併內容 |
| `feat/event-change-monitor` | #8 | 比對合併內容 |
| `feat/official-event-risk` | #7 | 比對合併內容 |
| `feat/prospective-state-o02` | #20 | **#19 實際 bootstrap 尚需確認**；先保留直到驗收／審查 |
| `feat/remote-acceptance-o04` | #18 | 確認 CI 入口仍在 main |
| `feat/scan-company-research` | #5 | 比對合併內容 |
| `feat/sec-history-valuation` | #2 | 比對合併內容 |
| `feat/sec-live-acceptance` | #3 | 確認沒有使用分支 ref 進行正式驗收 |
| `feat/technical-price-context` | #6 | 比對合併內容 |
| `fix/chat-f03-sec-filing-cutoff` | #26 | 比對合併內容 |
| `fix/empty-events-bootstrap` | #27 | **#9 bootstrap live 尚未成功**，先保留直到驗收／審查 |
| `fix/event-state-bootstrap-isolation` | #16 | **#9 bootstrap live 尚未成功**，先保留直到驗收／審查 |

**需特別審查、不可因名稱就刪（3）：**

| 分支 | 原因 |
| --- | --- |
| `feat/chat-event-state-store-m01` | #15 已合併，但遠端 Branch tip 不等於 PR #15 已合併的原始 head；可能有後續未合併實驗，需查 diff |
| `feat/chat-f01-source-eligibility` | #24 已關閉（未合併）；跨 Agent 重複 F01，確認未合併資料是否有可用價值再歸檔 |
| `feat/codex-event-state-reliability` | 舊 Codex WIP 明確標示 superseded；保留交接紀錄，需有人同意後清理 |

**沒有刪除任何分支。** GitHub squash merge 常導致 feature head 不是 `main` 祖先；光靠 `git branch --merged` 或分支時間不能判定是否可刪。後續清理應逐一對比 PR base/head/改動、分支剩餘 Commit、遠端依賴引用與 Issue 狀態，另在 Issue #28 記錄精確分支、理由及操作者。

## D. 後續的非破壞性操作與驗收

- [x] README 增加最常使用的 3 個 Workflow 入口（本次 PR）。
- [x] Actions 操作指南、19 Workflow 技術分類與 21 分支初步盤點（本次 PR）。
- [ ] #9 首次空事件狀態 Bootstrap 成功、兩次 TWSE 觀察及 receipt 證據。
- [ ] #14 真正 `event=schedule` 的 TW／US 期別驗收。
- [ ] #19 Prospective 正式 migration gate 完成。
- [ ] 逐一比對 Branch 額外 Commit 並提出確認後的清理計畫。
- [ ] 規劃名稱收斂、實測必要的 PR status checks / reusable workflows；不得因 UI 整潔省略必要安全 gate。
- [ ] 再由使用者同意後，以 GitHub 原生刪除 merged/closed branches，長期考慮 Settings → Pull Requests → Automatically delete head branches（永續 state branches 需例外）。

因為這是 **docs-only** 變更，只需最新 PR SHA 的 Unit/tests Required Check；不把與文件無關的 EOD 或 live-source 排程成功當成此 PR 驗收依據。
