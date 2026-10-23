# Agent skills

## Issue tracker

本專案使用 GitHub Issues 保存 spec、工作範圍與驗收證據。開始或交接工作前閱讀 [issue-tracker.md](docs/agents/issue-tracker.md)。先核對 origin/main、Open PR、Issue 認領與進行中 Actions；handoff 只供定位。

## Triage labels

Issue 狀態用語見 [triage-labels.md](docs/agents/triage-labels.md)。依賴使用 GitHub native blocking links；Assignee 與認領留言共同記錄執行者。

## Domain docs

採 single-context。探索領域規則前依 [domain.md](docs/agents/domain.md) 閱讀已存在的 glossary 與 ADR。

## Engineering and delivery

- 每個獨立工作使用自己的 feature branch / worktree 與 PR；保留其他 Agent 的分支與修改。避免同時修改相同模組，遇到重疊先協調 Issue 範圍。
- 修改 repository workflow 前，額外確認寫入、通知、排程與下游 side effects。
- 採 remote-first：Python 3.12、uv、已提交 uv.lock；GitHub Actions 是最終執行與驗證環境。本地只需適當的輕量檢查。
- 行為變更包含正常、缺失資料、來源失敗與必要的 no-lookahead regression verification。
- PR 記錄問題、契約、A/B/C/D 影響、最新 SHA、Run URL、Artifact 結果與限制。符合 repository 規則且最新 commit 檢查通過時，可依使用者授權合併自己負責的 PR。
- 區分 unit、integration、live-data 與正式 schedule 驗收。PR 合併不等於 schedule gate 完成；仍待排程驗收時保留獨立 operational acceptance Issue。
- 投資研究保留來源與日期，缺值不補零；未驗證訊號、估值情境、ATR 與支撐壓力不能冒充買賣價格。證據不足用 not_evaluated；不啟用自動下單。

## Planning

GitHub Issues / PR 是工作進度來源。正式設計放 docs/design/，不另外維護 PROJECT_STATUS 任務清單。