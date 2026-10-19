# On-demand company research — MVP

Use [On-demand company research](https://github.com/iceboxi/market-research/actions/workflows/company-research.yml) → **Run workflow** → enter a single stock code (e.g. `2330.TW`, `AAPL`). The workflow runs tests, loads public issuer fundamentals and completed daily bars, evaluates all ten Sakata research variants, and uploads `report.md`, `report.json` and `run_receipt.json` as a 14-day Artifact. Triggering it does not alter the EOD watchlist or activate any strategy.

The [first live TW verification](https://github.com/iceboxi/market-research/actions/runs/39059979742) succeeded using the TWSE public-company profile and monthly revenue services. On 2026-10-18 local time, its price section used the completed 2026-10-16 daily session. The research report is **preliminary**: issuer identification, the available revenue snapshot and reproducible technical observations. It is not the complete financial/valuation investment memo previously envisioned.

## Supported sources

- **Taiwan listed companies (`NNNN.TW`)**: TWSE [profile OpenAPI](https://openapi.twse.com.tw/v1/opendata/t187ap03_L) and [monthly revenue OpenAPI](https://openapi.twse.com.tw/v1/opendata/t187ap05_L); technical analysis from existing official unadjusted TWSE OHLCV. Monthly revenue values are displayed as **thousands of TWD**, with the original ROC month. Cannot infer annual revenue, EPS or intrinsic value from one snapshot.
- **US ticker (`AAPL`)**: the [SEC tickers index](https://www.sec.gov/files/company_tickers.json) resolves the CIK and [SEC companyfacts](https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json) yields qualifying completed annual 10-K USD financial facts, only if filed by the evaluation date; technical analysis from Yahoo adjusted price candles. Set repository Actions secret `SEC_USER_AGENT` to a **real contact name and email** before running US reports, as required by the SEC fair-access policy. This US live path requires separate end-to-end verification.
- Source URL, historical input checksum, price basis, fiscal or month period, latest completed trading date and data-quality warnings are saved. Raw vendor OHLCV remains excluded from public Artifacts.

## Still missing for a full investment opinion

1. Three or more years of normalized audited revenue, earnings, free cash flow, debt/share counts and issuer comparability (bank/insurance vs industrial firms).
2. Calendar/event reconciliation, verified split/dividend adjustments and TTM reporting-date consistency.
3. Sector-aware scenario valuation using explicit growth/margin/discount/multiple assumptions, with sensitivity and bearish/base/bullish ranges.
4. Separate technical entry/invalidating-price rules with commissions, tax, spread, short restrictions and measured slippage; no numerical target inferred directly from a candlestick.
5. Research orchestration/alerts that trigger reports only for selected candidates, plus versioned company watchlists and meaningful changes.
6. Independent strategy validity evaluation remains BLOCKED; no automatic trading or unsubstantiated buy recommendations.

The on-demand command is `uv run --no-sync python -m scripts.company_report --symbol 2330.TW --out company_output`.

The workflow currently supports only one ticker per run and does not change the curated scheduled 22-symbol universe. A green Run means the **data/report pipeline** worked, not that an investment thesis or valuation has been verified.

## 執行摘要與 run receipt

`report.md` 頂端的執行摘要分開列出公司身分、基本面數值、行情與官方事件的狀態、來源日期／範圍及處理方向，另列年度財報、估值與交易計畫的 readiness。行情過期會明確顯示；缺值不補零，缺少年度財報或模型時不產生買賣價格。

`run_receipt.json`（schema version 1）同時內嵌於 `report.json` 的 `run_receipt`，包含 execution、source coverage、research readiness 與輸出檔名。`report.json` 維持 schema version 4；legacy `complete` 仍只表示公司名稱存在且技術資料可用，因此即使 execution 為 `completed`，其他研究項目仍可能是 `unavailable` 或 `not_evaluated`。行情新鮮度需另看 `source_coverage.technical.freshness`。

台股 profile timeout、無唯一 issuer、月營收缺失、行情失敗或事件 coverage 不明，會在報告中保留其他仍可用的部分。公司身分未確認時只顯示輸入 ticker；CLI 在 legacy `complete=false` 時仍以非零狀態結束，既有 workflow 的 Summary 與 Artifact 步驟會保留已產生的報告。若 runner 或依賴無法啟動，則沒有報告可供承諾，須從 Actions log 診斷。

本入口的長期研究保存與通知投遞均標示 `not_attempted`；14 天 Artifact 不代表已建立可比較的 research snapshot。台股入口不需要 `SEC_USER_AGENT`。
