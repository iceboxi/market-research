# On-demand company research — MVP

Use [On-demand company research](https://github.com/iceboxi/market-research/actions/workflows/company-research.yml) → **Run workflow** → enter a single stock code (e.g. `2330.TW`, `AAPL`). The workflow runs tests, loads public issuer fundamentals and completed daily bars, evaluates all ten Sakata research variants, and uploads `report.md` + `report.json` as a 14-day Artifact. Triggering it does not alter the EOD watchlist or activate any strategy.

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
