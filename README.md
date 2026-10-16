# Market Research v0.1

Public-source research proof of concept for **Taiwan and US end-of-day stocks**. It is not a trading or order execution system.

Python package with authoritative TWSE daily historical OHLCV for listed Taiwan stocks and Yahoo/yfinance for US symbols, defensive quality checks, and interchangeable screening strategies (Wilder RSI + relative volume, and optional 20-bar moving average breakout).

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
