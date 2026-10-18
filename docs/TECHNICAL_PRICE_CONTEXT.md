# Research-only technical price context

This is a **non-actionable** companion to both Mode B on-demand reports and
Mode A reports (Mode A uses exactly the same `scripts.company_report.run`).
The report's `technical.price_context` contains data-grounded references:
previous 20/60 completed-session highs/lows excluding the current candle,
14-day arithmetic mean True Range (including the latest completed candle),
20-day average volume comparison, and support/resistance bands of ±0.5 ATR.
The structural invalidation *reference* is prior 20-session low minus 1 ATR.
These are descriptive research annotations, **not** trade stop-loss levels.

Safety conditions: require 61 completed daily bars, matching expected-completed
market session and data SHA, validated analysis price basis, finite/valid OHLCV,
non-zero ATR and no unreviewed >=20% opening gaps during the last 60 sessions.
If any check fails, `not_evaluated` provides a reason and no numeric levels.

Data caveats: Taiwan TWSE candles are official but unadjusted for corporate
actions; US Yahoo analytical OHLC are dividend-adjusted and cannot be used
directly as execution quotes. More subtle corporate actions can exist
without >=20% gaps. No brokerage costs, spreads, taxes, borrow constraints,
validated trading strategy or order-book liquidity are modeled.

Even when status is `observation_only`, `entry_zone`, `stop_loss` and
`target_price` are all null; `executable` is always false. The valuation
module also remains separate, and its multiples do not set these ranges.
No buy recommendations, confidence scores, executable stop loss or targets
are authorized by this output. Requires later independent risk-plan validation.

This adds `technical.price_context` to company report schema v2; scan artifact
contracts remain unchanged. The extra context uses already fetched OHLCV,
and does not cause additional market API requests.
