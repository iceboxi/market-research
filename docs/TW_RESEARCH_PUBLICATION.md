# 2330 研究版本與固定入口

既有 GitStateStore 的 `research` namespace 保存允許公開的精簡證據。報告呈現在固定 GitHub Issue；開發 Issue 繼續只記錄工作與驗收。[前後變化](TW_RESEARCH_COMPARISON.md) 與[每日固定研究](TW_DAILY_RESEARCH.md) 共用此 owner 與 publisher；自然排程另行驗收。

## 執行與權限

[Research publication acceptance](https://github.com/iceboxi/market-research/actions/workflows/research-publication.yml) 提供兩種明確的 dispatch：

- `mode=validation`：寫 `research-state-validation`，建立／更新有驗證 marker 的固定 Issue。第一次顯式建立空 research namespace；實際取得 2330 來源，保存 snapshot 後刻意遺失一次 GitHub 成功回覆，再由獨立 Python process 對帳與 ACK。
- `mode=production`：只允許最新 main 的手動 dispatch。首次必須明確選 `initialize_research=true`，後續使用 false；一般保存不會自動建立或重置 authority。研究來源失敗仍可產生 partial snapshot；CI 綠燈只代表保存／發布契約通過。

以上為本 workflow 的手動入口。每日 TW／both 的 `scan.yml` runtime 另外可提交同一份已計算報告，使用受限 daily context 與共用發布序列；此路徑不可 initialize production，詳見每日研究契約。

workflow 使用現有 GitHub standard runner、`contents: write` 與 `issues: write`；只有 detached state worktree 寫入專用 branch。分析 checkout、main 與其他 namespace 的 owner 不變。validation 與既有 state-store acceptance 共用 concurrency group；production publisher 有獨立序列化 group。沒有新增 schedule、通知、下單或修改既有 company-research workflow 的副作用。

本機／其他 writer 不應在 workflow 外同時呼叫 publisher。Git FF retry 可處理 archive 與 ACK 的競爭，無法提供跨 GitHub Issue／Git 的 exactly-once transaction。

## 保存契約

namespace 上限為 2,000 個 records／5,000,000 canonical JSON bytes；snapshot 上限 20,000 bytes。快照寫入時會省略網站可以重建的內容（#137）：固定的 `ogdl_datasets` 清單、行事曆事件中與整份行事曆相同的 `timezone`，以及等於該類別固定資料集的公告 `source`。達到上限會明確失敗，不自動刪除歷史。刪除只能經人工審核（#127）：`python -m scripts.research_state_prune` 乾跑時列出要刪除的確切 records 與 digest，內容包括第一個含財報版本之前的早期版本、和前一個保留版本相比 unchanged 的重複版本，以及引用它們的 acked 發布與通知；現行發布、通知、latest、last_success 與 checkpoint 引用的版本一律保留。`--apply --expect DIGEST` 只有在 fresh read 重新計算出相同 digest、且刪除後的 state 仍通過驗證時才會執行；`GitStateStore.commit` 只允許刪除 `remove=` 明列的 records。只有 `2330.TW`，新增標的須先擴充與驗證契約。

- `snapshots/tw/2330.TW/<sha256>.json`：schema v2，新增 started_at_utc，與 evaluation cutoff、觀測時間分開；既有 v1 保持可讀，不回填未知開始時間。immutable checksum 覆蓋時間、run identity、執行結果與精簡證據。
- `subjects/tw/2330.TW.json`：schema v2，latest observation、last-success、pending／published publication、固定 Issue number 與 creation_attempted 的唯一 owner。可讀既有 v1；下次 archive／ACK 升級為 v2。v1 未確認建立結果時視為曾嘗試，不能假設可以再次 POST。
- `publications/tw/2330.TW/<sha256>.json`：固定頁面的 snapshot／last-success references、renderer version、body checksum、pending／superseded／acked 與 Issue identity。

snapshot 與 pending 同 commit。latest 依觀測時間排序；last-success 沿用原報告 `complete` 的資料流程結果，不能當作財報／估值／建議已完成。晚到的舊 snapshot 不覆蓋較新的失敗結果；舊版 ACK 不清除新版 pending。

當下台股研究先在記憶體取得單次輸入 batch（每個來源只抓一次，失敗也保存為當次失敗），再固定 cutoff，以同批輸入完成 session／freshness 與研究計算。明確傳入 now 的歷史 cutoff 不會向後移動。原始 batch 不進 Git／Artifact。profile 的無效或未來出表日降級為未驗證身分，行情／事件仍可交付；codec 也防禦性略過該身分證據。

保留政策依 [來源公開保存查證](TW_SOURCE_USAGE_VERIFICATION.md)，其中 TW02 的 profile／monthly 已於 2026-10-20 逐項查證官方 catalog：

- 精確匹配 TWSE profile、monthly revenue 開放 API 才保存公司名稱與最多 12 筆月營收；數值附 metric、原始 ROC 期別、單位、出表日、source、policy version。未來期別／出表日不得進入當次證據。出表日不是公司實際公告時點；只記錄首次觀測，不推定歷史盤中可知時間。
- 其他未確認來源不保存數值或全文，只留去除 query／fragment 的公開 HTTPS source link 與受限 metadata。
- 行情只保存 status、session、freshness、source identifier、price basis、input checksum；事件只保存 source、status、snapshot date、coverage。原始 OHLCV、公告內文、PDF、provider response、未知欄位均不在 schema 內。
- 缺值保留 null／空證據；readiness 逐項保留 unavailable／not_evaluated。Artifact 僅 14 天且未保留完整輸入，因此不宣稱完整 replay，也不假裝已做前後比較。

[基本資料 catalog 18419](https://data.gov.tw/dataset/18419) 與[月營收 catalog 18420](https://data.gov.tw/dataset/18420) 均列金融監督管理委員會證券期貨局為提供機關、2015 年上架、政府資料開放授權條款第 1 版，並指向 TWSE OpenAPI 的 OAS。這是兩個具名 dataset 的採用依據；不擴張到所有網站資料。schema 與固定頁面同時保留提供機關、dataset 名稱／catalog、年份、未指定的 dataset version 與[授權連結](https://data.gov.tw/license)，履行顯名要求。

## 發布恢復

固定 marker 包含 state branch／市場／標的。無已知 Issue 時掃描所有分頁的 open／closed Issues 對帳；只接受唯一 marker、受 owner 保存的 body checksum、open 且未 locked 的頁面。已知 Issue 被刪除、marker 移除、手動修改內容或出現重複 marker 時停止覆寫，保留 pending，交由人員確認 identity／內容。

建立前先在 Git 保存 creation_attempted；此外部結果不明的 fence 屬於 subject，換新版 snapshot 也會保留。外部呼叫失敗或 timeout 一律不立即重送；可能已成功寫入。下次執行先找 marker／檢查 body，相同內容直接 ACK。列表暫時沒有 marker 時保持 outcome_unknown，絕不把「尚未看到」解讀成「尚未建立」。recover process 對此狀況最多做四次對帳查詢，等待 2／4／6 秒，沒有第二次 POST；超過上限留待下次恢復。若建立實際未成功，仍需人員查證與明確修復 fence，不能自動清除。API 成功但 Git ACK 失敗時記 `ack_pending`；再次對帳可恢復。沒有承諾 exactly-once。

Artifacts 包含 `snapshot.json`、`research_state.json`、保存／發布 receipt、`report.md`、`summary.md`；完整來源 report 只放 ephemeral temp directory。receipt 記錄 state commit、run URL、main／checkout 前後與 pending／Issue identity。validation、正式初始化、正式 live publication、自然 schedule 必須各自記錄證據。

需要恢復待發布工作時，從 main dispatch 同一 workflow 的 production mode。一般執行會先保存當次 observation，再對帳最新固定頁面；沒有完成的 snapshot 仍保留歷史。自訂恢復入口可呼叫 `scripts.research_publication --recover-only --state-branch research-state`，同樣限 main dispatch 且需同一 concurrency group。
