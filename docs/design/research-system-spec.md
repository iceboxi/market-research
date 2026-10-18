# Research System — Implementation Spec 草案

Revision: 2026-10-19-r2。基準：`main@759947836c329edda8017805a8c6842fc8f337d8`。
此為待發布至 GitHub 的 spec 草案，供本次確認與設計說明使用；尚非已發布 Issue，也不是工作進度表。GitHub 發布後以該 spec 的明確版本與已確認決策為 implementation authority。

## Problem Statement

使用者需要可靠的台美股研究與持續追蹤，並讓不同 Agent 可從 GitHub 恢復工作。現在已有 A/B 共用行情與初步公司報告、C 官方事件 baseline、D 申報事件 metadata，但財報/估值/持久化/通知/排程驗收仍有缺口。單一 complete 與 workflow success 不能表達研究充分性，也不能證明策略有效。

## Solution

保留既有模組，以 source/time/version 明確的研究證據為中心，讓 A 掃描、B 指定個股與 C 追蹤呼叫同一研究 engine；D 作共用事件研究能力。GitHub Actions 執行有時限的工作，`research-state` branch 保存 compact durable evidence / baseline / outbox / operations metadata，GitHub Issues 接收重新研究通知。程式、設定與正式文件經 PR 進 main。

先完成既有 10 TWSE + 12 US pilot。掃描 universe 不改；金融業、ETF 與來源不支援 issuer 仍可保留行情觀察，但明確分類其財報與模型 `not_evaluated`，不假設全部 22 檔能用同一估值。

## User Stories

1. 作為研究使用者，我要從盤後候選與指定股票得到同契約報告，以便比較相同證據。
2. 我要看到 company identity / instrument type，以免把 ETF、金融業與一般公司混用。
3. 我要知道每個數值的單位、期間、合併/個別、來源版本與時間證據。
4. 我要缺值明確呈現 unknown，而不是零或臆測值。
5. 我要年度、季度、累計、TTM 與修訂分開，以免不可比資料產生假成長。
6. 我要系統只使用評估 cutoff 當時可證實可用的數據。
7. 我要區分公開時間、accepted time、filed date、first seen 與 retrieved time。
8. 我要台股官方三表來源不能證明發布時間時，歷史研究明確受限。
9. 我要 SEC 真實 annual / quarterly coverage 有獨立 runner 證據。
10. 我要看到正式估值模型的適用性、資料對帳、假設版本、敏感度與失效條件。
11. 我要未校準的 10/15/20x sensitivity 保留 illustrative 標記。
12. 我要技術價位只是觀察證據；缺交易價格或成本契約時不產生風險報酬數值。
13. 我要官方申報、財報行程、公司行動與事件內容分開顯示。
14. 我要不知道未來財報日期時明確 not_verified，不從往年日期推算。
15. 我要新一期財報與同一期修訂觸發不同的研究變更結果。
16. 我要來源中斷不抹除原 baseline，也不被解讀為沒有風險。
17. 我要首次觀察只建立 baseline，同一事件重跑不反覆通知。
18. 我要事件觸發、研究重跑與通知可在失敗後恢復。
19. 我要通知附 evidence 與重新研究原因，保留未評估內容，不自動宣稱利多/利空。
20. 我要能在 Artifact 到期後，依持有權限與保留契約比較舊新研究證據。
21. 作為 Agent，我要從單一 Issue 取得 scope、spec revision、設計參照與驗收條件。
22. 我要有沒有完成 blocker、認領者與 PR 的 Ready 工作才可領取。
23. 我要以最新 SHA 的遠端驗證交付，不引用舊 commit 綠燈。
24. 我要實作完成與自然 schedule 驗收可分開追蹤。
25. 作為維運者，我要失敗、partial coverage、未持久化與未投遞可分辨，並能手動重跑。
26. 我要 metadata 不寫回 main，且嚴格 PR-only 宣稱有完整 writer/reader migration 證據。
27. 我要相同研究輸入與模型版本的 A/B/C 核心結果一致。
28. 我要策略有效性另用樣本外、成本、公司行動與偏差研究驗證，不由 CI 綠燈推論。

## Implementation Decisions

### 已由使用者確認

- Remote-first、Python 3.12 + uv.lock、GitHub Actions，不新增常駐伺服器。
- 首次完整里程碑維持 pilot；金融業及不適用 instrument 不強套一般業估值。
- 一個 `research-state` data branch 是 mutable research/operations metadata 的 canonical storage；共用 state-store 是唯一持久化 interface。domain module 擁有 merge policy，不各自直接操作 Git。
- main 只經 PR 保存程式、設定與正式文件；現有三個 data writer 與 lock/smoke side effects 分階段遷移，過渡期間不宣稱 PR-only 相容。
- 第一版通知只用 GitHub Issues；不新增 Email/LINE，不包含自動下單。
- Skills 沿既有 upstream；Design Doc 是使用者要求的獨立說明，進度留在 Issues / PR，不建立 PROJECT_STATUS 任務清單。

### 研究資料與時間契約

- 每項可計算 fact 有 issuer、metric、value/null、unit/currency/scale、statement scope、period start/end、duration type、source URL、source document identity / version、retrieved_at、parser/schema version。
- source publication evidence 與 system first_seen 分開。exact time 不可證實時，保留 precision/unknown；歷史 cutoff 只接受有證據的 availability 或持有 snapshot 的 first_seen 已不晚於 cutoff。date-only 不擅自補當日 00:00，也不把 acceptanceDateTime 當 exact publication。
- 同一期間不同修訂保留版本；衍生 FCF/TTM/單季數保留所有 inputs，並驗證期間、單位、口徑與修訂可比。任一缺失即不計算，不跨年或跨公司盲配。
- portfolio / holdings 不在此產品契約；公開 branch 不保存個人資料。full raw OHLCV 與公告全文不進公開 state。
- 保存精簡 normalized evidence 與 replay 範圍的最終保留決策，待本輪確認；不能用過期 Artifact 索引假裝完整 replay。

### Engine 與輸出

- 從既有 company report flow 收斂 computation seam；保留已完成 adapters、comparison、valuation、price context 與 event parser，先 characterization 再逐步抽取。
- adapters 只做取得與來源正規化；研究 engine 在固定 cutoff 與版本下計算；renderer 只呈現；Actions coordinator 負責 ordering / deadline / retry / state IO。
- output 分開 pipeline outcome、source coverage、financial availability、valuation status、event coverage、research readiness、persistence、delivery。既有 complete 保留相容性且標明 legacy 意義；新增契約明確升 schema，不偷偷改義。
- snapshot identity 由 canonical normalized inputs、cutoff、code/parser/model/config versions 與資料 hash 決定；不以每次 generated_at 當內容變更。
- D 事件 metadata、內容證據、未來行程與財務影響分別處理；公告不等於方向。官方無法證實行程時維持 unknown。
- US 先行後的 TW cash/debt/shares 對帳、模型適用性、財報差異與 C 觸發，有明確的 source-specific 整合工作承接。TW 年度/季度正規化或固定輸入 parity 通過，不能代替這條完整路徑的 runner 證據；最終完整里程碑需等待它完成。

### State / runtime

- `research-state` namespaces 分開保存 schema authority / migration metadata、event baseline、compact evidence、research comparisons / pending reruns、notification outbox、operations history 與 prospective immutable receipts。
- store read 必須區分 missing initialized namespace 與 unavailable/corrupt/incompatible；後者停止該 namespace 寫入，不初始化新 baseline。個別 symbol failure 不阻擋已驗證健康 symbol；store 整體失效時不得回報 durable success。
- 每次 write 以剛讀取 head 為 parent、ordinary fast-forward / force=false；最多三次嘗試，每次重新讀取並依 domain merge。超過 budget、權限或 schema 問題明確失敗，不能 last-write-wins。prospective 同 key 不同 payload 是 conflict。
- 固定 code SHA / config / input hash 貫穿整個 run；state store 在隔離工作目錄操作，不切換 analysis checkout。job deadline 或取消前已持久化工作保留，下次由 durable pending records 恢復。
- 來源 retry 僅限 transient timeout/429/5xx，遵守來源 access policy 與 Retry-After，在 workflow deadline 內有限執行；身份、schema、資料時間錯誤不盲 retry。
- baseline advance 與 durable research pending record 必須同一 state commit；研究成功後，研究版本與 pending notification 亦同一 state commit。失敗不能先消耗 event 然後遺失下游工作。
- notification worker 先對帳 durable marker / 已回傳 Issue/comment ID，再送出，最後保存 delivered。state 與 GitHub Issues 無共同 transaction：提供可恢復且以穩定 key 抑制重複的至少一次嘗試，不承諾 exactly-once 或實際收件。
- 首次 baseline 不產生歷史事件通知；schema/source/model 變更進入明確 rebaseline/migration review，不把版本升級當市場事件。coverage incident 走 operations channel，與投資研究變更分開。
- concurrency group 只作減少競爭；Git ref 檢查仍必要。pending 被取消／schedule 遺失時，下一次成功 reconciliation 從 durable backlog 恢復；不保證 GitHub 整體停機仍可通知。

### Migration

- 對每個 namespace 保存 authority marker、legacy source SHA、輸入 count/hash 與 cutover evidence。先停舊 writer，從最新 main 匯入並核對，再切換 writer/reader；未 cutover 只用舊 owner，已 cutover 只用新 owner。
- 新 state 缺失/損壞時停止該 namespace，不回退舊 main 並當成新 baseline；legacy tracked files 作唯讀歷史，無本次自動刪除。
- history、event baseline、prospective 與所有 reader 包含在遷移；dependency lock 改 PR 交付，smoke/manual validation 使用獨立測試 namespace 與明確 mutation guard。
- 新 prospective cohort 釘住 code/provider/calendar/config versions；舊 cohort 不回填、不改標籤、不混合統計。
- 嚴格 main protection 在所有 writer/reader、lock、smoke 與權限 live gate 都通過後才啟用；不自行改 branch protection。

## Testing Decisions

主要 seam 為既有 company report / shared research output、watch receipt、state-store read/commit、notification delivery receipt 與 workflow run/Artifact contract。使用獨立 fixture/spec 值作 oracle，不照抄 implementation 重算 expected。

- unit：日期精度、期別與修訂、缺值、model eligibility、no-lookahead、hash determinism、狀態轉移。
- integration：本地 bare Git remote 的 fast-forward race / stale / corruption / main unchanged；GitHub adapter 的 timeout-after-create / rate limit / marker reconciliation；A/B/C 同 snapshot 核心結果一致。
- live-data：全新 runner 的 TWSE / SEC 指定 pilot、季度/修訂/公司行動真實案例；核對每個欄位與來源。不靠 mock 或 workflow success 判讀 coverage。
- live-operations：實際 data branch restore/write/retry、權限拒絕、通知建立/重跑對帳；固定最新 SHA。
- schedule：自然 event=schedule、明確 due slots / observation window、run 完成、來源 coverage、state 持久化、pending recovery 與 notification receipt；manual dispatch 僅為先行 gate。
- strategy efficacy：獨立 methodology / sample / cost / action / bias gates，與 engineering completion 分開。

## Out of Scope

本次只有規劃、skill 設定、Design Doc、review 與待確認的工作拆分；不交付新研究功能。第一個完整工程里程碑不含全市場、TPEx、金融業專用模型、ETF 穿透估值、非官方新聞/產業自動推論、持股管理、外部通知與自動交易。

正式估值模型、台股 publication/history 可得性、可執行價格/成本與再發布權利均需 discovery evidence；未完成的下游不標可直接實作。

## Further Notes

工作拆分草案另列，批次建立 GitHub Issues 前等待使用者確認。Design Doc 僅整理同一份 spec / work plan，不另外創造 owner 或契約。若外部 gate 不成立，回到 spec 調整 scope，不能捏造資料來達標。
