# 2330 研究前後變化

固定報告與當次 Artifact 使用同一份 pure `compare_snapshots` 結果。比較對象是系統已觀測、允許保存的精簡證據；不推定歷史當時可知，也不因數值變化產生買賣建議。

| 分類 | 判定 |
| --- | --- |
| baseline | 首次沒有前次 snapshot |
| unchanged | 保留的可比證據未變；Run ID、開始／cutoff／觀測時間、出表日刷新不算變化 |
| new_period | 已有可比月營收 baseline，新取得另一原始期別 |
| revision | 相同期別、source／unit／policy 的必要數值更正，或已確認公司名稱變化 |
| coverage_change | 身分／營收／行情／事件來源退化或恢復、stale、分項 readiness／事件 coverage 改變 |
| model_change | 都有 model identity 且不同；表示研究／策略版本或設定契約變更，不等於新財報 |
| incomparable | 缺可比數值、來源／價格基準改變、schema 改變、只知行情 checksum 改變但未留行情、舊模型 identity 缺失、歷史 cutoff 反向 |

同一期別更正只列必要前後值，不把月營收當年度獲利，也不計來源口徑不一致的假成長。來源失敗不刪除舊 snapshot。固定頁面在目前不可用的部分顯示「最近可用」的觀測日期與 evidence reference，明確標示不是本次資料；恢復後可用同 owner 保留的 baseline 判斷更正。

## 相容與保存

- snapshot v1／v2 保持可讀。v2 可以帶有嚴格 64-hex `model_identity`，是既有研究契約版本、策略版本／設定與 market config 的 canonical digest；不以整個 Git SHA 代替模型版本，也不保存完整 config／原始行情。舊 snapshot 沒有此欄位時明列 model_identity_not_retained，不補猜。
- 新 publication 使用 schema／renderer v2，新增 immutable comparison references（前次 snapshot 與四個 component 的 last-good IDs），與 snapshot／pending 同 commit。所有 evidence value 仍由 snapshot 擁有，不另存一份數值 baseline。
- renderer v1 保持原始輸出與 body checksum；validator 分版本讀取。相同 snapshot／comparison refs 重跑 idempotent；較新 pending 與既有 creation_attempted fence 保留。
- 既有 `RESEARCH_CONTRACT_VERSION` 與每個策略的 version 表示模型契約；改變相應計算／口徑時更新對應版本。source unavailable 不改 model identity。
- Artifact 新增 `comparison.json`、`comparison.md`；`report.md` 含完全相同的 comparison Markdown。原始 batch／OHLCV／公告全文仍不保存；其數值／內容變化無法還原，限制明列。沒有新增研究通知或每日 schedule。

## 驗收層級

`tests/test_research_comparison.py` 驗證獨立 fixtures 的分類，`tests/test_research_state.py` 驗證真實 Git 保存 refs 與 last-good；既有 publisher tests 覆蓋新版 publication 的 ACK／競爭與未知結果。

`python -m scripts.research_diff_replay --self-test --out <directory>` 使用本機 temp bare remote 與兩個獨立 runner process，固定 fixture 1000→1100，驗證 baseline→revision 及 Artifact／固定報告一致。receipt 明列 controlled_fixture_not_live_data，絕不寫正式／validation GitHub state 或 Issue。Actions 將此受控證據保存於 `controlled_replay/`，再另跑真實 2330 live publication；兩者不能互相替代。
