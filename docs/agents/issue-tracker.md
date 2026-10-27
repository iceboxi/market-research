# Issue tracker: GitHub

本 repository 的 spec、實作工作與驗收證據使用 `iceboxi/market-research` GitHub Issues。從 git remote 核對 repository；使用 `gh` 或已連接的 GitHub tools，避免依賴對話狀態。

## 讀取與發布

- 讀取 Issue：`gh issue view N --repo iceboxi/market-research --json number,title,body,labels,assignees,comments`。
- 建立 Issue：`gh issue create --repo iceboxi/market-research --title "..." --body-file <file>`。skill 說「publish to the issue tracker」即建立 Issue；「fetch the relevant ticket」即依上一條讀取。
- 列出候選：`gh issue list --repo iceboxi/market-research --state open --label ready-for-agent --json number,title,assignees`；逐一核對 native blocking links 與關聯 PR。
- 多行 Issue / PR / comment 使用 UTF-8 暫存檔加 `--body-file`，或工具的結構化 body 參數。
- spec 使用 `to-spec`，工作拆分使用 `to-tickets`。新規劃先提供完整清單供使用者確認，再批次建立；尚待決策的內容保留 discovery gate。
- 每張工作 Issue 包含 Goal、Design Reference、Scope / Non-goals、輸入輸出契約、Acceptance criteria、Dependencies、驗收層級、必要來源與 Handoff；引用設計相關段落，不複製整份文件。

## Epic、依賴與認領

- Epic 使用 native sub-issues 分組。GitHub 依賴 API 的 `issue_id` 是 numeric database ID，不是 Issue number 或 node ID。
- Sub-issue：`gh issue create --parent EPIC ...` 或 `gh issue edit EPIC --add-sub-issue CHILD`。
- 依賴：`gh issue create --blocked-by N,N ...` 或 `gh issue edit CHILD --add-blocked-by BLOCKER`（gh 2.94+）。舊版 gh 才用 `POST repos/iceboxi/market-research/issues/CHILD/dependencies/blocked_by`，body 為 `issue_id: BLOCKER_DATABASE_ID`。若平台確實不支援，才使用 body 的 `Blocked by` 並註明限制。
- 未完成 blocker 數：`gh api repos/iceboxi/market-research/issues/N --jq .issue_dependencies_summary.blocked_by`（只計 open；0 才可領取）。`gh issue view N --json blockedBy` 也會列出已關閉 blocker，需過濾 `state == "OPEN"`。
- 只認領沒有未完成 blocker、沒有其他執行者／Open PR 的 Ready 工作。先 assign authenticated user，再留言 agent/session 名稱、範圍、branch、基準 SHA 與預計驗收。
- Assignee 與留言是協調紀錄，並非原子鎖。認領後重新讀取；同帳號的多 Agent 也要用 session / branch 區別。發現同時認領時先協調，較晚的 Agent 暫停重疊修改。
- 使用 feature branch / 隔離 worktree。開始新工作時確認最新 main；不 force push、reset 或覆蓋其他 Agent 分支。

## 交付與關閉

PR 連結實作 Issue；最新 commit 經 CI 與受影響 gate 驗證後才能宣稱通過。合併後核對 main SHA 與 Actions。

關閉時先 `gh issue comment` 留說明再 `gh issue close`；對已關閉 Issue 使用 `gh issue close --comment` 會遺失留言且仍回傳 0。

若尚待自然 schedule，實作 Issue 可在交付範圍完成後關閉，但必須連結仍開啟的 operational acceptance Issue；後者記錄 due slot、run event、SHA、資料 coverage、持久化與通知證據，不能以 dispatch 取代。

Handoff 留在 Issue / PR：完成與未完成事項、精確 branch/commit、Run URL、Artifact、已知 gate、下一個入口。不要使用 PROJECT_STATUS 作第二份任務狀態。

## PRs as a request surface

**PRs as a request surface: no.** 外部 PR 不自動進入 triage queue。

## Wayfinding operations

只在需要跨 session 的 decision map 時使用；未有此需求時不新增 map 或 labels。

- Map：單一 Issue，label `wayfinder:map`，body 保存 Destination / Notes / Decisions so far / Fog。
- Child ticket：map 的 native sub-issue，label `wayfinder:<type>`（research / prototype / grilling / task），不假裝是 ready-for-agent implementation。
- Frontier：`gh api repos/iceboxi/market-research/issues/MAP/sub_issues` 取開啟的 children，排除有 open blocker 或已有 assignee 者，依 map 順序取第一張。
- Claim：`gh issue edit N --add-assignee @me`，為該 session 第一個寫入。
- Resolve：先留言答案、再 close，最後在 map 的 Decisions so far 補 gist 與連結。
