# Market Research v0.1

Development uses GitHub Issues for work state, PRs for delivery, and Actions
for validation. Read [AGENTS.md](AGENTS.md) before taking work. The current
system planning proposal includes the [technical design](docs/design/research-system.md),
[implementation spec draft](docs/design/research-system-spec.md),
[Epic / Issue publication draft](docs/planning/research-system-issues.md), and
[repository evidence](docs/design/research-system-evidence.md).

Public-source research proof of concept for **Taiwan and US end-of-day stocks**. It is not a trading or order execution system.

Python package with authoritative TWSE daily historical OHLCV for listed Taiwan stocks and Yahoo/yfinance for US symbols, defensive quality checks, and interchangeable screening strategies. Since #117 no pattern strategy is enabled: the scheduled scan is price-only and the watchlist system (#111) uses valuation review zones instead. Sakata, RSI and MA definitions remain for research workflows.

## Sakata three soldiers (research only, disabled in production)

Disabled in the scheduled scan since #117 (holdout evidence insufficient); kept for research workflows.

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

The TW watchlist ([#111](https://github.com/iceboxi/market-research/issues/111))
is **3 TWSE stocks (2330, 2317, 2454) plus 2 ETFs (0050, 00631L)**; ETF codes
start with `00` and are monitored for price only, without issuer research.
The US list keeps 12 stocks. Default scheduled period is **6mo**:
TWSE STOCK_DAY requires one official monthly request per ticker, so this
downloads **7 months x 5 = 35 requests** instead of 13 x 5 = 65.
The adjustable period can still be changed back to 1y for research. The
TWSE client reuses HTTP connections per symbol and throttles requests.
For whole-market scans we should switch to a bulk daily data pipeline rather
than scaling this per-ticker historical endpoint indefinitely.

US yfinance OHLC bars are adjusted using Yahoo's Adj Close / Close factor for
each day; trading volume is deliberately left unchanged (reported shares).
TWSE bars stay officially unadjusted. Data-quality artifacts record both
price bases. Do not directly compare raw Taiwanese prices to adjusted US
prices or treat unadjusted Taiwan prices as corporate-action-neutral.



## GitHub Actions：日常操作入口（Remote-first）

**日常只需要認識 3 個入口**；其他驗收／回測／初始化工作流程是工程工具，不代表必須每天手動操作。完整的操作步驟、報告下載方式與失敗排查見 [Actions 操作指南](docs/ACTIONS_OPERATIONS_GUIDE.md)。

| 你要做的事 | GitHub Actions 入口 | 執行方式 |
| --- | --- | --- |
| 每日盤後掃描、產生候選名單 | [EOD market scan](https://github.com/iceboxi/market-research/actions/workflows/scan.yml) | 排程；必要時可 Run workflow |
| 指定股票研究，如 `2330.TW`、`AAPL` | [On-demand company research](https://github.com/iceboxi/market-research/actions/workflows/company-research.yml) | 手動 Run workflow |
| 追蹤官方重大公告是否變更 | [Official disclosure watch](https://github.com/iceboxi/market-research/actions/workflows/event-watch.yml) | 排程；**首次正式啟用前必須完成 Issue #9 遷移驗收** |

**目前部署注意：** [Issue #9](https://github.com/iceboxi/market-research/issues/9) 的事件 state Bootstrap 程式已修復，但正式遷移／連續兩次真實觀察尚未驗收，勿直接啟用或當成已經正常監控。[Issue #14](https://github.com/iceboxi/market-research/issues/14) 另行驗證真正的自然排程。 [Issue #28](https://github.com/iceboxi/market-research/issues/28) 負責 Actions／Branch 的收斂；[逐項盤點](docs/WORKFLOW_BRANCH_AUDIT.md) 保留技術驗收與必要的 state 分支，不以刪到特定數字為目標。

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

Satellite stocks get a valuation review zone ([#114](https://github.com/iceboxi/market-research/issues/114)):
the 20th/50th/80th percentiles of the stock's own daily P/E over the five years
up to the cutoff (FinMind `TaiwanStockPER`, positive P/E only) times trailing
four-quarter basic EPS give low / mid / high review prices, and the latest close
is placed `below_low`, `fair` or `above_high`. Missing or non-positive EPS, EPS
older than 200 days, or fewer than 720 P/E samples give `not_evaluated`.
`config/watchlist.yaml` lists the satellites (a subset of the scanned TW stocks,
never ETFs) with an optional thesis and percentile or fixed-multiple override.
The zone is a prompt to review, not a fair value, target or trade price.

The ETFs and the TAIEX benchmark (`benchmarks` in `config/markets.yaml`) get a
price watch ([#113](https://github.com/iceboxi/market-research/issues/113)) in the
daily TW run: latest close, drawdown from the 52-week high and distance from the
200-session moving average, from the latest completed session (strict freshness).
TAIEX comes from TWSE `MI_5MINS_HIST` OHLC, cross-checked against `FMTQIK`
(close, change, market-wide shares). The price watch loads 13 months, so it
costs 13 requests per ETF and 26 for TAIEX on top of the scan. Where TWSE
publishes a reference price different from the previous close (a split such as
00631L's 1-for-22 on 2026-03-31), earlier bars are rescaled by it; 'X' days
(ex-dividend) stay unadjusted and are listed. Less than 52 weeks or 200
sessions, or an unexplained gap on an 'X' day, gives `not_evaluated`. The daily
summary and the Pages "觀察名單總覽" show these rows with the satellites'
review zones; they are display only, never signals. The scan, backtests and
strategy research do not load benchmarks.

Satellites also get a thesis check ([#115](https://github.com/iceboxi/market-research/issues/115)):
`review` when year-over-year monthly revenue (FinMind `TaiwanStockMonthRevenue`)
stays below a threshold for consecutive months (default 3 months below 0 %,
`revenue_check` in `config/watchlist.yaml`), or when TWSE's daily material
information (`t187ap04_L`) lists an announcement for the stock on the evaluation
date. A month counts only once public at the cutoff (FinMind `create_time`, else
the 10th of the following month); a missing month, a lagging source or an
incomplete announcement snapshot gives `not_evaluated`, never `ok`. All three
satellites are also in `config/event_watchlist.yaml`. The report, daily summary
and Pages overview show the status and its basis; `review` asks for a re-read
of the thesis, not a trade.

One open Issue titled 觀察名單提醒 ([#116](https://github.com/iceboxi/market-research/issues/116))
tracks those two states. Its body is the current table and stores the last
evaluated state in a hidden marker; each main TW schedule or dispatch run
comments only when a satellite's zone or thesis status changes (old → new,
prices or basis, data date, run link), at most once per run. The first run
creates the Issue with a baseline comment; an unreadable stored state is
rebuilt and explained in a comment. `not_evaluated` is never a change: the last
evaluated value is kept and the body shows the gap. Branch, pull-request and
validation runs never write it.

The Pages site lists 2330 with its research-state history and, from each daily
TW run, the other satellites with today's version only (#125): they are rendered
from that run's reports, not stored in research-state, and a stock whose report
cannot become a valid snapshot is left out with its reason in the daily receipt.
The stock picker opens the full list (▾) and filters by code or name. The
overview, risk and valuation narrative written for TSMC's foundry business shows
only on 2330; every number in it comes from each stock's own data.

Each stock's latest version opens with a 新手 section (#126), ported from the
reviewed prototype: a five-condition health check from the public statements
(missing data is 資料不足, never a fail; financial and special industries are not
checked), where the price sits in the stock's own five-year P/E review zone, five
questions with charts, and a P/E calculator where the reader picks the multiple.
Rises are red and falls green, with arrows. Older versions show a one-line note
instead, which keeps the page about 20 kB per stored version lighter.

## Limits

TWSE reports **raw, unadjusted** prices and **shares** for .TW tickers; corporate actions can affect indicator calculations. Yahoo Finance via yfinance is unofficial and subject to data quality and usage restrictions. Historical corporate actions and data freshness must be reviewed. This public repository intentionally does not publish raw full-history market CSV by default. Taiwan price/volume are sourced directly from TWSE (not Yahoo); the optional crosscheck only applies to nonofficial Taiwan adapters. No match is a legitimate result, not a license to invent candidates.

This repository currently covers only a handful of example tickers. It is **not** a whole-exchange scanner. No automatic trading, VPS, AI API, or Serenity analysis is included. An exploratory backtesting module exists, but no automated broker execution is supported. Python dependency resolution is pinned in the committed uv.lock.


## Foundation: freshness and offline replay

`market-scan --strict-freshness` validates the latest completed XTAI/XNYS session, with a 60-minute safety delay after the close. For TW live scans, a recent XTAI session that TWSE's market-wide FMTQIK record still lacks 6 hours after the close (e.g. a typhoon closure) is treated as an unscheduled closure and recorded as `session.unscheduled_closures`; any FMTQIK failure keeps the calendar rule. Other calendar outages or unexpected closures still require review. The default remains diagnostic/non-strict until live freshness behavior has passed CI. Local opt-in snapshots can be created with `market-scan --snapshot-output snapshots/` and replayed with `market-scan --replay-dir snapshots/`. Snapshots are gitignored and must not be uploaded to this public repository without redistribution rights. Read `docs/STRATEGY_SPEC.md` before implementing new strategies. This project already has a manual exploratory backtest workflow.


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
is appended under operations/history/YYYY/MM on the `research-state` data branch,
with run ID, dates, status, strategy versions
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
Legacy main history is retained read-only; new writes use the shared metadata
store without switching the analysis checkout. See [STATE_STORE.md](docs/STATE_STORE.md)
for cutover, read/restore, integrity, receipts and validation gates.


## Watchdog onboarding gate

`EOD schedule watchdog` checks the actual scheduled GitHub Actions events, not push/manual run success. First eligible monitored slots are explicit in `config/operations.json` (TW 2026-10-28 07:40 UTC, the first slot after the TW cron moved from 11:30 UTC; the US cron was removed in #117, so only TW is monitored), preventing false missing-run alerts for cron slots that preceded deployment. Before the first due slot the watchdog reports `warming_up` without creating Issues. Its own cron is a best-effort GitHub schedule; a separate external heartbeat would be needed to detect GitHub-wide scheduler failure.

The Summary now shows the observation time, actual execution phase (`not_created`, `queued`, `in_progress`, `execution_failed`, `completed`), evaluated slot/grace, next nominal UTC/Taiwan slot and the last successful scheduled job within that market's time window. `created_at` and `run_started_at` are workflow-run metadata, not proof of runner/job start; inspect jobs/steps for that evidence. Runtime market and source health still need the scan Artifact. The existing 2-hour grace is an eligibility threshold; watchdog itself runs daily at `02:15 UTC` (`10:15 Asia/Taipei`), subject to delays, so it does not check exactly when grace expires. A scheduled run counts for a slot only if it was created within 8 hours of the nominal slot (observed natural delays: 4–6.2 h); a run not yet created when watchdog executes is still reported missing. The US and TW windows overlap 07:25–08:45 UTC, where `created_at` alone cannot identify the market. Missing/late-run root causes remain unverified without supporting evidence.

For a read-only engineering check, run `python3 -m scripts.watchdog --repo iceboxi/market-research --probe --out schedule_output`. This produces `schedule_feedback.json` and `schedule_feedback.md`, uses only Actions reads and does not sync incident Issues. It covers the latest 100 returned scheduled runs, not a complete history. GitHub documents possible schedule delays/drops and default-branch requirements in [schedule events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule); an enabled workflow alone does not establish the cause of a missing run.


## Operational acceptance and first live schedule

The read-only schedule probe (`python3 -m scripts.watchdog --repo OWNER/REPO --probe`, with `gh` auth) writes schedule feedback without creating Issues. The one-time `Operations live acceptance` workflow that wrapped it was removed on 2026-10-27 after its acceptance; dispatch `EOD market scan` directly when a manual TW run is needed, and inspect its run/Artifact separately. The independent watchdog does not alarm for slots preceding `config/operations.json`'s first live slot. Metadata-only `history/` commits do not trigger unnecessary unit-test workflows.


## Strategy-independent isolated research

Use the GitHub Actions workflow Isolated strategy research to choose a catalog strategy ID, market (tw/us/both), and history period. The generic code path is scripts/strategy_research.py. Only catalog entries marked implemented or validated_for_research, with explicitly disabled production config entries, may run; the normal scan is unchanged. The legacy Morning Star CLI now delegates to this common runner for compatibility. One temporary data snapshot feeds the research scan and (bullish-only) backtest, with input-hash parity checked before publication. Bearish or exhaustion observations never become long-only backtest trades. Published artifacts omit full raw market OHLCV. A new strategy only needs its specification, implementation, tests, catalog registration and explicit disabled config entry, not a new workflow.
