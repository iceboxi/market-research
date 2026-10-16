# Strategy Specification — Version 1

Define strategy rules independently from data ingestion or backtest execution.
This contract is intended to let new plugins use the existing runner unchanged.

## Mandatory fields

- Stable strategy ID and version; a rule change requires a new version.
- Market, instrument type, supported bar frequency and price basis.
- Required input fields and minimum finalized-candle history.
- Exact signal predicate, comparisons, parameters and their bounds.
- Signal confirmation timestamp and explicit lookahead prohibition.
- Missing data, market suspension, stale bars and corporate-action behavior.
- Entry, exit, holding horizon, risk limits and estimated transaction costs:
  these may be unspecified for a SCREENING-ONLY pattern; do not invent them.
- Deterministic positive / negative / boundary / invalid-input tests.
- Manifest provenance: code commit, input hash, strategy ID/version/params.

## Sakata bullish three soldiers — screening-only 0.1.0

- This is a quantified research interpretation, not all five Sakata methods.
- Three consecutive completed bullish daily candles with rising closes.
- Second/third opens within previous candle real bodies, including bounds.
- At least 50% candle body-to-range and at most 25% upper-shadow-to-range.
- Prior five closes show decline of at least 2%.
- Signal is available only after the third close.
- No inherent buy order, profit target or exit is implied.
- Current simulator assumes following-day open and five-session exit as
  hypotheses, not attributes of the pattern.
- TWSE uses unadjusted OHLC; Yahoo uses adjusted OHLC. Corporate actions and
  tradability need separate research before execution decisions.

## Acceptance of future strategies

Every strategy must pass determinism, positive/negative/boundary fixture
tests, schema contract checks and offline replay. No trading orders or
automatic investment recommendations in this project.
