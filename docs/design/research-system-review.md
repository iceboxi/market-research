# Research System — Independent Review

Review skill：使用者已安裝的本地 `review`（Independent Technical Review）。本紀錄保存技術規劃審查，並非程式或運作驗收。

## Final verdict

```text
Review mode: INDEPENDENT
Verdict: ACCEPT
Subject: f4111f044f3e07766ba6b402a5af89bf43afc98d
Document revision: 2026-10-19-r2
Code baseline: 759947836c329edda8017805a8c6842fc8f337d8
Blocking findings: 0
Non-blocking findings: 0
Notes: 0
```

Reviewer 使用未參與設計的 fresh agent context。審查範圍為 implementation spec、獨立 Design Doc、工作拆分、repository evidence、AGENTS 與 skill 設定。查核涉及 ownership、canonical state、source/time/version、caller/side effects、migration、outbox failure windows、驗收依賴；實際讀取 code/tests，沒有執行來源請求或有副作用 workflow。

## Review rounds

初輪 subject `c42d0183370a6988226091d62c69cde4c6cef4de`，r1，結果為 ACCEPT WITH NON-BLOCKING NOTES：0 blocking / 1 non-blocking。

唯一 finding：US 先行的 cash/debt/shares 對帳、財報變更與 C 重研究，留下台股 source-specific 擴充需求，但未有明確工作承接；TW 財報正規化或固定 snapshot parity 本身不足以代表完整台股路徑通過。最終整體 gate 雖然仍保護，但已知前置工作可能在交接時缺 owner。

修正：新增台股端到端整合承接，包含 TW 幣別/scale/scope、現金負債/股數/公司行動、模型適用性、真實新期/修訂資料觸發、去重與失敗恢復；最終整體驗收明確依賴該成果，spec / Design Doc 同步語意。

第二輪對 `c42d018..f4111f0` 做 bounded re-review，確認上述 finding 已充分處理，結果為 ACCEPT，0 / 0 / 0。原本已接受的 ownership、時間、migration 與 outbox 契約仍成立。

## Acceptance basis

- A 已呼叫既有 B `run`，shared computation 是重用現有 seam，而非另造系統：`scripts/scan_company_research.py:109`、`scripts/company_report.py:29`。
- spec 明確收緊現有 `filed <= asof` 日期精度限制，沒有宣稱 intraday no-lookahead 已完成：`src/market_research/financial_history.py:41`。
- 三個 data writers、checkout 切換、lock 與 smoke side effects 均納入 migration；code pin 與單一 namespace authority 有明確 gate。
- baseline/pending research 與 checkpoint/outbox 的原子保存、ambiguous notification 的 reconciliation 已有契約；未承諾 exactly-once。
- Design Doc 不揭露個別工作 metadata；最終驗收不因核心 pipeline/舊綠燈自動達標。

## Pending decisions and reopen conditions

技術 ACCEPT **不代表使用者已同意以下兩項**：compact normalized evidence 的保留方式，以及將未決來源/估值/價格契約以 discovery gates 管理。它們在 spec / Design Doc 仍標示未決，不能據此把 downstream 標成 Ready。

以下情況需回有效 spec / 決策流程，並重估受影響部分：

- 不保留必要 compact evidence，導致長期 replay/comparison scope 改變。
- 來源無法提供時間、歷史版本、保留或再發布權利。
- 實作證據無法維持單一 owner、固定 revision、原子 pending 保存或安全對帳。
- 正式模型與價格契約改變輸入、輸出或驗收範圍。

r2 工作清單的粒度與依賴已獲使用者確認；compact evidence 與 discovery gates 兩項仍未回答，批次發布維持等待。使用者另已授權實作不受這兩題影響的 shared-store / operations 範圍，以及將文件 push / merge 供交接；其結果見 [後續證據](research-system-evidence.md#後續查核--shared-store-交付)。文件合併不變更本審查 subject 或代答未決事項，其餘 planned gates 不因文件合併自動通過。
