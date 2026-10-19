# GitHub Actions 操作指南（非開發者入口）

> 專案採 Remote-first。日常研究不需要在本機安裝 Python、uv 或下載行情。
> 這份文件給「要使用研究系統的人」；CI、state migration、策略驗收請由工程人員依 Issue 管理。

## 最常用的 3 個入口

| 需求 | Workflow | 如何執行 | 哪裡看結果 |
| --- | --- | --- | --- |
| 台股／美股盤後掃描 | [EOD market scan](https://github.com/iceboxi/market-research/actions/workflows/scan.yml) | 自動排程；要人工測試就 Run workflow，選擇 `main` 與 TW/US/both | Run Summary 和 `market-scan-...` Artifact；符合執行條件時還會有 `candidate-research-...` |
| 指定公司個股研究 | [On-demand company research](https://github.com/iceboxi/market-research/actions/workflows/company-research.yml) | Run workflow → `main` → 輸入 `2330.TW` 或 `AAPL` | `company-report-...` Artifact，含 `report.json`、`report.md` |
| 追蹤官方事件變化 | [Official disclosure watch](https://github.com/iceboxi/market-research/actions/workflows/event-watch.yml) | 正式 state migration 完成後由排程自動執行；必要時由工程人員人工 dispatch | `official-event-watch-...` Artifact，包括來源覆蓋、狀態恢復、保存與差異 receipt |

### 下載結果

1. 進入該 Workflow，點開最上方最近完成的 Run（或指定執行日期）。
2. 看畫面中的 Summary 與各 job 結果。綠勾只代表該 Run 的程式工作成功，**不代表投資策略有效**。
3. 需要研究細節時，於 Run 頁面下方找到 **Artifacts**，下載對應 ZIP。
4. 可把 Run URL 或下載 ZIP 交給 ChatGPT／本地 Agent 討論。GitHub Actions Artifact 目前多數僅保留 **14 天**；長期研究證據須另行保存合法且必要的精簡資料。

**研究限制：** 目前股票範圍是 pilot，估值有研究示意用途。事件已觀察 ≠ 利多／利空；ATR、支撐壓力 ≠ 可執行停損目標；系統尚未提供完整可信的交易建議，亦未自動下單。

## 正式事件監控尚需一次性遷移

[Issue #9：官方事件 state](https://github.com/iceboxi/market-research/issues/9) 是正式上線 gate。

- 前次 [Bootstrap Run #39196950385](https://github.com/iceboxi/market-research/actions/runs/39196950385) **失敗**：舊事件目錄為空，導致 `git add events` 找不到路徑。
- 修復已透過 [PR #27](https://github.com/iceboxi/market-research/pull/27) 合併。修復後的 Unit／State-store acceptance 綠燈 **不代表正式 Bootstrap 已成功**。
- **事件監控仍需保持停用**，由具 GitHub Actions 權限者在 [Official event state bootstrap](https://github.com/iceboxi/market-research/actions/workflows/event-state-bootstrap.yml) 建立**新的** `main` Run，勾選 `confirm_migration=true`；**不要 Re-run 舊失敗 Run**。
- 必須檢查 `bootstrap_receipt.json` 和 `research-state/.state-store.json` 的 `namespaces.events`；如果 `record_count=0`，這是合法的空基線，可能還沒有可見的 `events/` 目錄。
- Bootstrap 成功後重新啟用事件監控，**循序**手動執行兩次真實 TWSE 觀察，比對 `restore_receipt.json`、`watch_receipt.json`、`state_receipt.json`。如果來源失敗，不可把「沒有事件」宣稱為驗收通過。
- 自然排程仍由 [Issue #14](https://github.com/iceboxi/market-research/issues/14) 獨立驗收。

詳細 migration runbook：[EVENT_STATE_MIGRATION.md](EVENT_STATE_MIGRATION.md)。**一般使用者不應自行重新初始化、修改或刪除 `research-state`。**

## 其他常見操作與問題

| 現象 | 應先查看什麼 | 應找哪個入口 |
| --- | --- | --- |
| 掃描沒有候選標的 | `signals.json`、`health_report.json`：0 signals 可能是正常結果 | EOD market scan |
| US 公司研究失敗或缺少 SEC 資料 | `SEC_USER_AGENT` Actions Secret 是否已配置有效聯絡方式；SEC 來源/覆蓋率 | On-demand company research；工程檢查 SEC live acceptance |
| TWSE 資料不足／當天還未收盤 | `data_quality.json`、來源狀態、最新已完成交易日 | EOD market scan |
| 事件監控失敗 | 是否已完成 #9 正式遷移；查看恢復／來源／持久化 receipts，不要重做 baseline | Official disclosure watch |
| 工作流程顯示成功但報告沒有完整買賣價 | 查看 `readiness`、`not_evaluated` 與來源證據；這是不同層級的 gate | Company report；相關研究 Issue |
| 排程沒有發動 | 查看實際 `event=schedule` Run 及 [#14](https://github.com/iceboxi/market-research/issues/14) | EOD schedule watchdog（工程入口） |

## 排程狀態怎麼看

[EOD schedule watchdog](https://github.com/iceboxi/market-research/actions/workflows/watchdog.yml) 的 Summary 會列出觀測時間、判定中的 slot、grace、下一次預期排程（UTC 與臺灣時間），以及同時間 window 內最後成功的自然 job。`not_created` 表示回傳範圍內沒有對應 run，`queued` 是已建立但等待執行，`in_progress` 是尚未完成，`execution_failed` 是已結束但失敗。這些分類與資料來源健康分開；仍須查看 scan Artifact，確認實際市場、資料日期與 coverage。

台股名目排程為臺灣平日 19:30；watchdog 名目排程為每日 12:15。兩者都可能延遲。2 小時 grace 只決定何時可判定 slot 過期，**不會安排在 grace 到期那刻執行檢查**。最近名目 slot 尚在 grace 內時，摘要會另外標示；下一次預期時間也不等於 GitHub 保證的開始時間。

若長時間沒有新 Summary，請工程人員用唯讀入口 `python3 -m scripts.watchdog --repo iceboxi/market-research --probe --out schedule_output` 取得當下 JSON／Markdown feedback，核對 workflow 是否 active、default branch、cron 與真正的 `event=schedule` runs。未找到 run 時保留根因未確認，不能以手動或 push 綠燈替代自然驗收，也不要重做 baseline。此 probe 不寫 state 或 incident Issue；資料僅涵蓋 API 回傳範圍，實際市場仍需 Artifact 證實。

## GitHub 多 Agent 工作方式

新功能以 [AGENTS.md](../AGENTS.md) / [GitHub Issue tracker](agents/issue-tracker.md) 為準。新 Agent 先確認最新 main、開啟的 PR 與 Issue 認領，再用獨立 branch、PR、GitHub Actions 驗收。可從 [交接 Issue #11](https://github.com/iceboxi/market-research/issues/11) 取得整體進度。避免將聊天紀錄當成唯一事實來源。
