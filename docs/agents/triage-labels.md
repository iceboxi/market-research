# Triage labels

採 Matt 預設名稱，避免另設一套 status labels：

| Role / label | 用途 |
| --- | --- |
| needs-triage | 外部原始需求尚未整理 |
| needs-info | 缺需求、來源契約或可驗收決策 |
| ready-for-agent | 契約與驗收完整，可由 Agent 執行；仍須確認 blockers 與認領 |
| ready-for-human | 需要人提供授權、帳號或真實聯絡資訊 |
| wontfix | 已決定不做，Issue 說明原因 |

使用者介面的 Backlog = 尚未 Ready；Ready = ready-for-agent 且 blockers 已關閉、未認領；In Progress = 認領與開始留言；In Review = 連結 Open PR；Done = Issue 關閉且範圍驗收完成。Blocked 由未完成 native dependency 或 needs-info / ready-for-human 與原因表示。

狀態由 Issue、Assignee、blocking links 與 PR 推導，不在文件維護第二份逐項進度。已有 blocker 的 ready-for-agent ticket 也不能領取。to-tickets 產生且內容完整的工作不再做一次 triage；未決 discovery 與 downstream implementation 分開。
