# Superseded WIP — event state

這個分支保存先前尚未提交的原型，供 [Issue #9](https://github.com/iceboxi/market-research/issues/9) 接手者參考。基準為 `759947836c329edda8017805a8c6842fc8f337d8`；此原型未完成驗收，與目前已確認的 shared-store 契約不同，尚不能合併。

## 可供檢視的內容

- `scripts/event_watch_archive.py`：隔離 Git worktree、restore / archive receipt 與有限 fast-forward retry 的早期原型。
- `src/market_research/event_monitor.py`：persisted snapshot validation 草稿。
- `tests/test_event_watch_archive.py`：real bare-Git regression 起點，測試仍使用舊 `event-state` branch。

## 接續方式

以最新 main 建立新的 feature branch，依 Issue #9 認領流程重用已合併的 `scripts/state_store.py` 與 `docs/STATE_STORE.md`。目前 main 已有 PR #13 / Issue #12 的 shared `research-state` store。

本原型仍另建 `event-state`、未串接現有 workflow 的新 CLI 參數，也未完成 per-source partial failure、namespace cutover、no-lookahead regression 與 TWSE 兩次 live acceptance。接手者可挑選有用的 domain validation / regression 構想，再依 shared-store 契約實作；整個原型不是可直接 cherry-pick 的完成品。

本分支不是認領紀錄；Issue #9 的 Assignee / 最新留言才是協作依據。完整規劃與交接入口為 Issue #11，正式文件由 main 的 AGENTS.md 導覽。
