# Historical holdout research quality — v0.1

Implemented as `scripts/holdout_evaluation.py`; CI `Historical holdout quality evaluation` runs a fixed two-strategy, TW+US 1-year diagnostic.

**Method:** chronological 70% pre-cutoff / five-completed-session embargo / 30% remaining test segment; labels are percentage analytical-close differences from a confirmed signal close to five sessions later. They are not trade fills or net P&L. No strategy parameters are fit or optimized. Evaluations use an as-of price prefix; any unobservable future label near the data end is censored. Events overlapping a previous accepted five-session event are removed from the *descriptive event sample*, never retroactively erased from the raw signal count. Price sources and SHA-256 hashes are recorded, but full vendor OHLCV is not shared.

**Evidence gate:** fewer than 20 nonoverlapping confirmed and labelled events *per ticker* suppresses event mean and returns `insufficient_independent_events`. No signals is a separate `no_signals` state. Three-gap observations on unadjusted TWSE data use `corporate_actions_unverified` abstention and must never be converted to zero-bias evidence. Stale or missing data fails CI; partial scans cannot claim complete evaluation.

**Important limitation:** because the research variants, tuned threshold conventions, and 22-symbol curated universe were chosen while inspecting historical data, this is a *retrospective historical holdout* and **not truly independent or prospective out-of-sample validation**. The unconditional five-session baseline is descriptive; its overlapping windows do not yield independent significance tests. Corporate actions and dividends remain material; realistic borrow, execution, FX, spreads and market impact are outside scope. There is no scientific basis here to activate an additional strategy or place any trades.

A stronger future stage requires prospectively frozen parameters/universe and months of newly acquired post-freeze data (ideally independent providers and complete exchange calendars), plus event clustering, multiple-testing control and properly adjusted execution/fill models.
