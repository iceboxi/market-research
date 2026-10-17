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

This repository currently covers only a handful of example tickers. It is **not** a whole-exchange scanner. No automatic trading, VPS, AI API, or Serenity analysis is included. An exploratory backtesting module exists, but no automated broker execution is supported. Python dependency resolution is pinned in the committed uv.lock.


## Foundation: freshness and offline replay

`market-scan --strict-freshness` validates the latest completed XTAI/XNYS session, with a 60-minute safety delay after the close. Calendar outages or unexpected official closures still require review. The default remains diagnostic/non-strict until live freshness behavior has passed CI. Local opt-in snapshots can be created with `market-scan --snapshot-output snapshots/` and replayed with `market-scan --replay-dir snapshots/`. Snapshots are gitignored and must not be uploaded to this public repository without redistribution rights. Read `docs/STRATEGY_SPEC.md` before implementing new strategies. This project already has a manual exploratory backtest workflow.


## Shared market-data contract

Scan and Backtest now call the same `load_daily_bars` boundary in `market_data.py` for source routing, completed-session exclusion, OHLCV checks, checksum, metadata, and strict-freshness policy. Backtest also accepts `--replay-dir snapshots/` and `--snapshot-output snapshots/` for privately retained input history. Analysis price basis is tracked separately from execution price basis: dividend-adjusted US opening prices are **not executable fills**. The backtest remains an exploratory proxy, not a broker-realistic simulator.


## Price-model safety (research vs simulated execution)

US **signal candles** are adjusted using Yahoo Adj Close / Close, but a
separate `execution_open` column preserves Yahoo's quoted Open without cash
dividend adjustment. TWSE stores its unadjusted Open as `execution_open`.
The backtester explicitly uses `execution_open` for price-only entry and exit
calculations. Yahoo historic quote Open may already be split-adjusted, and
neither provider guarantees executable prices. **Cash dividends, distributions,
exchange fees and full corporate actions are not fully modeled.** Backtest
returns are price-only exploratory metrics, not investor total returns.

The daily data contract records the analysis price basis, execution proxy,
dividend-handling limitations, and SHA-256 of the complete input, including
`execution_open`.


## Reproducible CI dependencies

The GitHub Runner-generated `uv.lock` is committed to main. Unit, scan and backtest workflows verify `uv lock --check` and install with `uv sync --locked`. Dependency updates are reviewed through the separate `Generate dependency lock` workflow. A generated lock file is not itself a full market-data snapshot.

## Operations history and issue alerts

For scheduled and manually dispatched scans, a small metadata-only JSON report
is appended under history/YYYY/MM, with run ID, dates, status, strategy versions
and input hashes. Full raw OHLCV is **not committed to public GitHub**.
Each run also produces health_report.json and health_report.md as Artifacts.

Expected provisional-session warnings do not create an incident. Missing
results, partial coverage and failed sources create a critical incident;
unexpected warnings are degraded. Issues named "[market-health] EOD scan MARKET"
are deduplicated: future failures comment on the same open Issue, and a healthy
later run closes it. GitHub's Watch/notification settings determine whether
these Issue events reach you.

Push-triggered validation scans deliberately do not archive history or open
operator Issues. Branch push restrictions can prevent archiving, in which case
the Action records an error rather than pretending history was saved.


## Watchdog onboarding gate

`EOD schedule watchdog` checks the actual scheduled GitHub Actions events, not push/manual run success. First eligible monitored slots are explicit in `config/operations.json` (TW 2026-10-19 11:30 UTC, US 2026-10-20 00:45 UTC), preventing false missing-run alerts for cron slots that preceded deployment. Before the first due slot the watchdog reports `warming_up` without creating Issues. Its own cron is a best-effort GitHub schedule; a separate external heartbeat would be needed to detect GitHub-wide scheduler failure.


## Operational acceptance and first live schedule

The `Operations live acceptance` workflow probes GitHub scheduled-run metadata in read-only mode (`python3 -m scripts.watchdog --repo OWNER/REPO --probe`) and triggers a real `workflow_dispatch` TW scan. The dispatched scan exercises long-term metadata archiving and issue sync; its run/Artifact must be inspected separately. No test Issue is created by the probe. The independent watchdog does not alarm for slots preceding `config/operations.json`'s first live slot. Metadata-only `history/` commits do not trigger unnecessary unit-test workflows.
