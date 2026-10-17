# Sakata v0.1 Research Engineering Acceptance

**Baseline:** 2026-10-17 (UTC), [GitHub Actions run 39056472471](https://github.com/iceboxi/market-research/actions/runs/39056472471). The baseline is the run's checked-out revision; documentation may be newer. This is **engineering research acceptance**, **not** validation of forecasting accuracy or expected returns.

## Scope and controls

- 10/10 research variants have versioned implemented strategies in `docs/strategies/catalog.yaml` and `src/market_research/strategies.py`.
- Only `sakata_three_soldiers` remains enabled in production (`config/strategies.yaml`).
- All four newly added families/variants are disabled in production; isolated runs use temporary config and check selected strategy version, market data coverage and input-hash parity.
- Research input coverage is **10 curated TW equities + 12 curated US symbols**, over one year. This is neither full-market coverage nor an out-of-sample predictive test.
- All 8 jobs completed successfully, including real-source fetches, test suite and artifact upload.
- The official TWSE raw OHLC series are unadjusted; US Yahoo analytical OHLC are adjusted by Adj Close ratio. They are **not interchangeable as evidence of a real executable gap**.

## Newly implemented four variants: live research baseline

| Strategy | TW scanned | TW historical observations | US scanned | US historical observations | Latest-session TW / US |
| --- | ---: | ---: | ---: | ---: | --- |
| `sakata_three_gaps_up` | 10/10 | 0 (TW abstains) | 12/12 | 0 | 0 / 0 |
| `sakata_three_gaps_down` | 10/10 | 0 (TW abstains) | 12/12 | 0 | 0 / 0 |
| `sakata_three_mountains_triple_top` | 10/10 | 31 | 12/12 | 59 | 0 / 2 |
| `sakata_three_mountains_head_shoulders` | 10/10 | 20 | 12/12 | 27 | 0 / 0 |

The two *latest-session* US triple-top observations were META and AVGO on **2026-10-16**, as recorded by this specific immutable run. These are **model-defined neckline observations**, not short orders, sell advice, or forecasts. Changing the quantification, season, universe or price-adjustment policy changes the results.

**Data errors:** zero across all eight research jobs. **Historical observation count is not trade count**. All four are observation-only within this acceptance matrix; the existing long-only exploratory backtester is skipped for bearish/exhaustion directions.

## Fail-closed limitations

1. **Taiwan three-gaps intentionally abstain.** The TWSE adapter has no audited corporate-action adjustment feed. Therefore zero TW gap observations mean **unsupported/unverified price discontinuity interpretation**, *not* evidence that there were no physical price gaps.
2. **US three-gaps:** strict full-range non-overlap over four consecutive XNYS sessions, three gaps at least 0.2%, previous directional trend. Yahoo dividend-adjusted analytical OHLC make this an *adjusted-price pattern*, not an exchange-executable opening gap.
3. **Three-peaks:** locally confirmed highs require two right-side complete sessions. The first neckline cross is evaluated only after the third pivot's confirmation; no backdating to a pivot's trading date. Quantified pivot separation, 5% tolerance and 0.2% neckline break are research conventions.
4. **Risk not modeled:** no short-borrow availability, dividend/corporate-action cashflow ledger, realistic slippage/liquidity capacity or forward walk-test. An implemented pattern does not establish profitable or actionable trades.
5. **GitHub cron:** scheduled scan/watchdog have their own operational acceptance and execution observations. The eight-job research matrix does not establish that natural cron scheduling is always reliable.

## Operational repeatability

Run a single candidate with [Isolated strategy research](https://github.com/iceboxi/market-research/actions/workflows/strategy-research.yml), selecting its ID and market/period. Use [the eight-job acceptance workflow](https://github.com/iceboxi/market-research/actions/workflows/final-acceptance.yml) to rerun all newly completed variants. Research artifacts include standardized `study.json`, `study.md`, and `historical_observations.json`; raw vendor OHLC CSV is not published.

**Engineering milestone conclusion:** implemented research plugin coverage 10/10. **Not concluded:** strategy performance, price-gap validity on unadjusted TWSE history, broker execution, or profitable signals.
