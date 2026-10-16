# Market Research v0.1

Public-source research proof of concept for **Taiwan and US end-of-day stocks**. It is not a trading or order execution system.

Python package with authoritative TWSE daily historical OHLCV for listed Taiwan stocks and Yahoo/yfinance for US symbols, defensive quality checks, and interchangeable screening strategies. The default is a Sakata-inspired bullish three soldiers pattern; legacy RSI and MA examples are disabled.

## Sakata three soldiers (pilot, not validated trading advice)

This is a precise *research interpretation*, not an implementation of all
five Sakata methods or a proven buy/sell system. The active condition requires:
five prior daily closes falling by at least 2% from first to last; three
consecutive bullish bars with successively rising closes; second and third
opens inside previous real bodies; each real body >= 50% of daily range; and
each upper wick <= 25% of the range. The thresholds are adjustable hypotheses.
Signal is only observable **after the third close**; hypothetical execution
cannot occur before the following session. Evaluate with out-of-sample
backtests, costs, and benchmarks before any live trading.

RSI is retained as disabled reference code, not used by the scheduled scanner.

## Market coverage and request cost

The pilot universe now includes **10 TWSE-listed Taiwanese stocks and 12 US
stocks**, not the full markets. Default scheduled period is **6mo**:
TWSE STOCK_DAY requires one official monthly request per ticker, so this
downloads **7 months x 10 = 70 requests** instead of 13 x 10 = 130.
The adjustable period can still be changed back to 1y for research. The
TWSE client reuses HTTP connections per symbol and throttles requests.
For whole-market scans we should switch to a bulk daily data pipeline rather
than scaling this per-ticker historical endpoint indefinitely.

US yfinance OHLC bars are adjusted using Yahoo's Adj Close / Close factor for
each day; trading volume is deliberately left unchanged (reported shares).
TWSE bars stay officially unadjusted. Data-quality artifacts record both
price bases. Do not directly compare raw Taiwanese prices to adjusted US
prices or treat unadjusted Taiwan prices as corporate-action-neutral.


## Run with GitHub Actions

- **Unit tests** workflow runs on push and pull request.
- **EOD market scan** can run manually with **Run workflow** for tw, us, or both; it also runs on a weekday schedule.
- Download the 14-day Artifact: manifest.json, data_quality.json, screening_results.json, signals.json, summary.md.
- You can ask ChatGPT to read the artifact from GitHub where supported, or upload the downloaded ZIP into this conversation.

## Run locally

Install Python 3.12 and uv, then run:

    uv python install 3.12
    uv sync --extra dev
    uv run --no-sync pytest
    uv run --no-sync market-scan --market both --period 1y --check-twse --out output

Symbols are in config/markets.yaml; toggle strategies in config/strategies.yaml.

## Limits

TWSE reports **raw, unadjusted** prices and **shares** for .TW tickers; corporate actions can affect indicator calculations. Yahoo Finance via yfinance is unofficial and subject to data quality and usage restrictions. Historical corporate actions and data freshness must be reviewed. This public repository intentionally does not publish raw full-history market CSV by default. Taiwan price/volume are sourced directly from TWSE (not Yahoo); the optional crosscheck only applies to nonofficial Taiwan adapters. No match is a legitimate result, not a license to invent candidates.

This repository currently covers only a handful of example tickers. It is **not** a whole-exchange scanner. No automatic trading, VPS, AI API, Serenity analysis, or backtesting is included. Dependency versions are constrained but there is no checked-in uv.lock yet; generate and commit one after networked resolution.


## Foundation: freshness and offline replay

`market-scan --strict-freshness` validates the latest completed XTAI/XNYS session, with a 60-minute safety delay after the close. Calendar outages or unexpected official closures still require review. The default remains diagnostic/non-strict until live freshness behavior has passed CI. Local opt-in snapshots can be created with `market-scan --snapshot-output snapshots/` and replayed with `market-scan --replay-dir snapshots/`. Snapshots are gitignored and must not be uploaded to this public repository without redistribution rights. Read `docs/STRATEGY_SPEC.md` before implementing new strategies. This project already has a manual exploratory backtest workflow.


## Shared market-data contract

Scan and Backtest now call the same `load_daily_bars` boundary in `market_data.py` for source routing, completed-session exclusion, OHLCV checks, checksum, metadata, and strict-freshness policy. Backtest also accepts `--replay-dir snapshots/` and `--snapshot-output snapshots/` for privately retained input history. Analysis price basis is tracked separately from execution price basis: dividend-adjusted US opening prices are **not executable fills**. The backtest remains an exploratory proxy, not a broker-realistic simulator.
