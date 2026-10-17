# Strategy evidence acceptance policy v1

This repository is a **research screening system, not a trade recommendation engine**. Strategy implementation coverage (10/10) does not imply statistical or tradable effectiveness.

## Decision states

- **Engineering passed:** reproducible, covered tests, correctly timestamped observations and complete source metadata.
- **Historical evidence insufficient:** fewer than 20 nonoverlapping five-session labelled events *per market*, fewer than three contributing symbols per market, or fewer than eight events in either chronological half of the test section.
- **Blocked for deployment:** no genuinely new observations accumulated after the strategy and universe were frozen; no independent price/corporate-action and full execution-cost ledgers; no family-wise testing control. This remains blocked even if retrospective sample-count conditions pass.

The quantitative thresholds are conservative research-process gates, not scientifically justified minimum statistical power. Observations from different symbols can be correlated; two halves of an already examined year are NOT independent walk-forward validation. Profit-factor, win rate, "alpha" and simulated short returns MUST NOT be presented from incomplete evidence.

## Cost sensitivity

The policy records illustrative 30/60/120-basis-point round-trip stress levels, but these do **not** constitute a verified execution-cost model and do not permit performance claims. A separate execution design would need borrow fees, short availability, exchange fees, commissions, taxes, spreads, slippage, corporate actions and dividends. TWSE raw OHLC can have ex-dividend/ex-right discontinuities and must not be treated as a company-action-cleansed price history.

## What this version actually implements

- `scripts/holdout_evaluation.py`: deterministic 70/30 historical date split, five-session embargo, five-session forward *analytical-close* labels, overlap thinning, zero-signal and insufficient-evidence statuses, no look-ahead.
- `scripts/research_gate.py`: sanity-checks complete TW/US historical reports, counts supporting symbols and observations across both halves, and ALWAYS blocks deployment when prospective/cost/company-action criteria are unmet.
- `scripts/prospective_journal.py`: fail-closed **journal format and eligibility contract** for new daily scan metadata after 2026-10-18. No prospective forward outcome is asserted, and no unattended future journal capture is claimed until that workflow has been separately integrated and verified. The freeze fingerprint covers current strategy config, market universe and catalog. Changing any of them must create a new cohort, rather than mixing cohorts.

## Exit conditions before further consideration

1. Freeze the exact strategy code hash, parameters, ticker selection, provider conventions and calendar, and preserve the fingerprint.
2. Record genuinely future daily completed-session signals, with an immutable receipt recorded at observation time; distinguish operational failures from no signals.
3. After each horizon matures, attach independent end-of-period labels and audited split/dividend treatment, without altering the earlier receipt.
4. Independently verify realistic fills and all costs; account for overlapping events and correlated symbols.
5. Pre-register benchmarks, multiple-comparison control and pass/fail thresholds before reviewing future outcomes.
6. Explicit human investment/research review. **No automatic strategy activation or trade orders.**

A CI green result means the research pipeline ran and data contracts passed. It does **not** mean a strategy passed the investment evidence gate.
