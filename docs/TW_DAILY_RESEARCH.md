# 台股每日固定研究

`EOD market scan` 的 TW／both schedule 或手動執行會研究固定 2330，即使掃描為 `no_candidates`。US 保持既有候選入口；push 僅做原本的 scan／CI，不發布固定報告。cron、策略啟用與掃描 universe 不變。

## 資料與去重

每日 coordinator 重用 `company_report.run`、既有 candidate coordinator 與 research publisher。固定 2330 先取本次來源，再固定 evaluation cutoff；指定歷史 cutoff 則不移動。每個 ticker 的本次計算／錯誤會共用，同時命中候選時不重算。

候選仍需通過 scan health、strict freshness、session 與 input hash gates。固定研究明示自己的資料範圍，不能因其成功就宣稱 scan 候選關聯成立。另一標的來源失敗、scan 不健康或候選漂移時，已取得的固定／其他健康結果仍輸出；整體 partial 不包裝成成功。

固定完整報告只在暫存工作目錄計算，發布沿用 compact snapshot allowlist；只有真正被選中的候選保留原有 candidate report 格式。沒有公開原始行情 batch、provider response 或公告全文。研究 namespace 仍由原 owner 保存，未新增另一份 checkpoint 或數值 baseline；既有 renderer1／2 不改。

## 固定發布與序列

main 的 `scan.yml`、TW／both、schedule／dispatch 才能以 daily context 寫 production；其他分支的實際 TW dispatch 使用 validation namespace／頁面。daily 不可 initialize production，缺 authority 時失敗並保留 receipt。

TW runtime job 與既有手動 publisher 共用 `research-publication-production`，validation 共用 `research-state-validation`。兩個 workflow 使用 `cancel-in-progress: false`、`queue: max`，避免新的共用序列使既有 pending scan 被另一個發布取代。[GitHub concurrency 文件](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency) 說明其最多100筆等候限制；它不保證 GitHub 準時建立自然 schedule。

發布使用同一份已計算 report，沿用 snapshot／pending 原子保存、marker 對帳、ACK 與 fresh-process recovery。production 仍核對最新 main／固定分析 checkout；未知投遞或權限失敗保留既有 outbox，不重建 authority。預先計算的 report 不會在 publisher 再抓一批來源。

## 執行成果

`candidate-research-<market>-<run>` Artifact 增加：

- `daily_summary.md`／`daily_receipt.json`：候選計數、固定資料日期／cutoff、來源 coverage、readiness 與發布結果。
- `fixed_research/`：既有 publisher 的 snapshot、state receipt、report、comparison 與固定入口連結。
- 原有 `candidate_index.json`／`candidate_summary.md`／真正候選的報告路徑維持。

失敗也會輸出每日摘要；若發布本身失敗，固定頁面仍可能是舊版本，須看當次 daily receipt 與 publisher receipt。原始 `market-scan-*` Artifact 仍在候選研究之前上傳，不包含新增的每日結果。

| 既有副作用 | 本次行為 |
| --- | --- |
| scan／health report | 保持；額外 fixed research 不改 scan 的健康結論 |
| operations archive／receipt | 保持原 main schedule／dispatch 條件與 owner |
| incident Issue | 保持原 scan health 語意；每日研究有獨立結果 |
| prospective guard／observe／archive | 原 schedule-only 條件、模式與實作保持 |
| 固定研究發布 | TW／both runtime 新增；與手動發布共用序列及 owner |

## 驗收層級

coordinator tests 驗證零候選、同標的去重、drift、來源／發布失敗、手動核心一致與歷史 cutoff；publication runner tests 另以真實 bare Git、獨立 gh process emulator 與 fresh publisher 驗證預算與外部 body。真正 TW dispatch 的來源、Artifact、固定頁／state 與最新 SHA 另記 GitHub Issue。自然兩個連續 eligible slots 仍須獨立 operational acceptance，dispatch 不能替代。
