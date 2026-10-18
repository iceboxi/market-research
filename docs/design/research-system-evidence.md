# Research System — 現況與證據

查核日期：2026-10-19。程式基準：`759947836c329edda8017805a8c6842fc8f337d8`。
本文件是規劃時的 evidence snapshot，不是持續維護的工作進度表。工作狀態從 GitHub Issues / PR 讀取。

## GitHub 實際觀察

| 項目 | 實際結果 | 證據 |
| --- | --- | --- |
| main | 7599478，已合併既有公司研究與官方事件功能 | [commit](https://github.com/iceboxi/market-research/commit/759947836c329edda8017805a8c6842fc8f337d8) |
| Open PR | 查核時無 | GitHub PR list；不能假設後續仍無 |
| 工作 Issue | 官方事件 state 工作已建立，依使用者新指示暫停實作、解除認領 | [Issue #9](https://github.com/iceboxi/market-research/issues/9) |
| Unit tests | 此基準 SHA success | [Run 39148598573](https://github.com/iceboxi/market-research/actions/runs/39148598573) |
| EOD scan | push run success；Artifact：22 requested / 22 scanned、errors=0、signals=0、兩市場最新 session 2026-10-16 | [Run 39148598546](https://github.com/iceboxi/market-research/actions/runs/39148598546) |
| Company report | push run success；2330.TW、schema=3、complete=true、financial=unavailable、valuation=not_evaluated、event source=available | [Run 39148598505](https://github.com/iceboxi/market-research/actions/runs/39148598505) |
| SEC live acceptance | workflow runs total_count=0；Secret 清單無 SEC_USER_AGENT | GitHub workflow runs / secret names API；未讀取 secret 值 |
| Official disclosure watch | workflow runs total_count=0 | GitHub workflow runs API |
| main protection | protected=false；rulesets=[] | GitHub branches / rulesets API；不代表未來不可改 |

以上 push runs 不是自然 schedule 驗收；沒有 SEC、watch persistence、研究通知或策略有效性的通過證據。本次下載並檢查上述 scan / company Artifacts，未重新執行來源請求。

## A / B / C / D 現況

| 能力 | CURRENT | 缺口 / 限制 | Code / test evidence |
| --- | --- | --- | --- |
| A 主動掃描 | 22 檔 curated universe；掃描 health/session/hash gate；最多三檔候選重用 B | 不是全市場；無 signal 是正常結果；二次下載可能 drift | `config/markets.yaml:1`；`scripts/scan_company_research.py:21`、`:71`、`:94`、`:109` |
| B 公司研究 | shared `company_report.run`；schema v3；JSON / Markdown | complete 只表示 name + technical available，不含財報/事件/估值充分性 | `scripts/company_report.py:29`、`:88`、`:95`；`tests/test_company_report.py:26` |
| SEC 財報 | annual 10-K / 10-K/A，5 原始 metric + FCF，最多六年，實際期間配對 | 無完整季度、TTM、cash/debt/current shares；filed 日期不等於 intraday 公開時間 | `src/market_research/financial_history.py:10`、`:19`、`:39`、`:69`；`tests/test_financial_valuation.py:66` |
| TW 財報 | profile + 最新月營收，TWD_thousands，缺值不補零 | 無 audited IFRS 三表；沒有 fundamentals historical as-of gate | `src/market_research/fundamentals.py:58`、`:86`、`:95`、`:109` |
| 估值 | 三年正 FCF median 的 10/15/20x sensitivity；SIC 6000–6999 排除 | illustrative_only；未校準倍數、股數/負債/現金/公司行動與 forward model 未齊 | `src/market_research/valuation.py:10`、`:27`、`:58`、`:82`；`docs/FINANCIAL_VALUATION.md:28` |
| 技術觀察 | 共用行情、prior 20/60-session range、ATR14、stale/gap gate | executable=false；不是進出場價 | `src/market_research/market_data.py:92`；`src/market_research/price_context.py:28`、`:66`、`:120` |
| C 持續追蹤 | 2330.TW；initial baseline 不通知；新 ID 要求 review；保留最多 2,000 IDs | bounded cache；沒有研究重跑與通知 delivery；partial run 跳過整批 archive | `config/event_watchlist.yaml:1`；`src/market_research/event_monitor.py:63`、`:90`；`.github/workflows/event-watch.yml:44` |
| D 官方事件 | TWSE current daily / SEC recent filings 共用 adapter；same-UTC-day SEC 全排除 | 不是完整 history、未來財報行程、公司行動或內容影響研究 | `src/market_research/event_risk.py:15`、`:81`、`:101`、`:125`、`:131`；`docs/EVENT_RISK_V1.md:30` |
| 運作監控 | health + incident Issue、schedule watchdog、prospective receipt | GitHub scheduler 自身不獨立；history health 不是整個 job 最終狀態 | `scripts/monitor.py:19`、`:130`；`scripts/watchdog.py:36`；`.github/workflows/scan.yml:41`、`:59` |
| 策略驗證 | historical holdout、cost/prospective gate 明確阻擋 | 不足以支持策略啟用或投資建議 | `scripts/research_gate.py:96`；`docs/strategies/HOLDOUT_METHOD.md:9` |

Pilot 內含金融業及 SPY；現有行情掃描可保留，company research 應先辨識 instrument type / model eligibility，不能為 ETF 假設普通 issuer 10-K，也不能為金融業強套 FCF。

## 現有 side effects 與遷移範圍

| Writer / reader | CURRENT | 遷移注意 |
| --- | --- | --- |
| event_watch_archive | switch 最新 main、直接 HEAD:main | 保留 baseline、拒絕來源不相容、不要誤作首次執行；`scripts/event_watch_archive.py:18`、`:24`、`:50` |
| monitor.archive | history metadata 寫 main，且切換呼叫端 checkout | 後續 prospective 可能換 revision；`scripts/monitor.py:104`、`:111`、`:121`；`.github/workflows/scan.yml:79`、`:87` |
| prospective_archive | immutable session receipt 寫 main | 相同內容可重跑、衝突硬失敗；`scripts/prospective_archive.py:17`、`:27`、`:39` |
| fingerprint | 只有三個設定檔，不含 code revision | 新 cohort 必須釘住 code/provider/calendar 與設定版本；`scripts/prospective_journal.py:12` |
| dependency lock | main ref 直接更新 uv.lock 並 push main | lock 是程式資產，應轉 PR；不搬進 state branch；`.github/workflows/lock.yml:24` |
| ops permission smoke | 修改 YAML 的 branch push 就可寫 main history、建立/關閉 synthetic Issue | 變更前閱讀 side effects；需 ref / mode guard；`.github/workflows/ops-validation.yml:3`、`:37` |
| scheduled/manual scan | push 不寫 state；manual 無 main ref 限制 | PR 驗證不得寫 production namespace；`.github/workflows/scan.yml:79` |

main tree 當時只有 history，沒有 event_state / prospective；這只反映該 commit，遷移仍須重新讀最新 remote。既有資料不自動刪除；切換後 legacy 位置是唯讀歷史，不得缺新 state 就回退並覆蓋 baseline。

## 官方來源查核

以下是文件查核，並非已通過 runner live acceptance。

- TWSE 官方服務可依年度/季度查三表；損益與現金流有累計語意。最新 OpenAPI schema 不能證明歷次公開時間與修訂版本完整。[MOPS 手冊](https://dsp.twse.com.tw/public/static/downloads/announcement/official/R-1130603962-1.pdf)、[財務比較說明](https://mopsfin.twse.com.tw/terms)、[TWSE OpenAPI](https://openapi.twse.com.tw/)、[一般業損益 schema](https://data.gov.tw/dataset/91998)、[一般業 BS schema](https://data.gov.tw/dataset/94831)。因此 `出表日期` 與 `published_at` 不得混用。
- SEC companyfacts 是跨 filings 的標準 facts 聚合，不等於完整財報；acceptance、filing date 與公開可取得時間不同，沒有 exact availability 證據時不能宣稱 intraday no-lookahead。[SEC APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)、[SEC FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions)。
- 季度與累計必須按 duration 判定；amendment 不代表全面重編。[10-Q 規範](https://www.ecfr.gov/current/title-17/chapter-II/part-210/section-210.10-01)、[AAPL 10-Q](https://www.sec.gov/Archives/edgar/data/320193/000032019325000073/aapl-20250628.htm)。
- schedule 是 best effort；Artifact 可過期或隨 run 刪除，不能作唯一長期 baseline。[GitHub schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)、[Artifact retention](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/remove-workflow-artifacts)。
- fast-forward ref 更新需要處理競爭，concurrency group 不能取代 ref 檢查。Issues 與 Git commit 沒有共同 transaction，不能保證 exactly-once 通知或收件。[Git refs](https://docs.github.com/en/rest/git/refs#update-a-reference)、[Concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)、[Issue comments](https://docs.github.com/en/rest/issues/comments#create-an-issue-comment)。

## 已核對測試 seam

既有 tests 有 annual future/restatement/period mismatch、financial sector gate、價格 stale/no-lookahead、watch baseline/new ID/source failure、watchdog 暖機與 prospective hash/immutable checks。這些測試可以重用，但不能取代 persistence race、官方來源 live、自然 cron 與 notification crash-window 驗收。

此規劃不把原功能分支的未提交 archive 原型當成已完成實作；後續實作須依有效 spec 重新整合。
