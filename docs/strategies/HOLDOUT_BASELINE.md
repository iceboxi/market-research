# Fixed chronological holdout baseline — 2026-10-17

Verified workflow: [Historical holdout quality evaluation #39057661025](https://github.com/iceboxi/market-research/actions/runs/39057661025). Both jobs succeeded with complete one-year real-source coverage and **zero data errors**. Detailed JSON/Markdown live in this run's separate TW/US Artifacts (14-day retention). Not prospective or untouched out-of-sample data.

| Frozen research pattern | TW 10 stocks: raw / labeled | US 12 stocks: raw / labeled | Adequate evidence? |
| --- | ---: | ---: | --- |
| `sakata_morning_star` | 1 / 1 | 0 / 0 | **No** |
| `sakata_evening_star` | 0 / 0 | 2 / 2 | **No** |

Each raw/labeled count refers only to the final chronological holdout segment, after a five-session embargo, with a five-session label horizon. Any event overlapping another is thinned for the labelled sample; none was censored in this baseline. **Below 20 nonoverlapping observations per ticker, no event-mean figure is reported.** No signals and insufficient events are deliberately distinct statuses.

Method is defined in [HOLDOUT_METHOD.md](HOLDOUT_METHOD.md). It uses analytical closes, not realistic executable opens, dividends, financing, borrow or short fills. Baseline comparisons use overlapping windows and are not formal significance tests. The 70/30 date cutoff was fixed for this run and no parameters were tuned, but earlier historical exploration of the strategies and hand-picked universe creates selection bias.

**Acceptance:** engineering pipeline and integrity checks pass. **Strategy decision:** insufficient holdout evidence to justify activating Morning Star or Evening Star. Production remains red-three-soldiers only. Obtaining real prospective, post-freeze observations and accounting for corporate actions are separate, unmet gates.
