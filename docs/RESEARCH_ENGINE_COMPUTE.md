# I01 — shared company research computation (non-breaking v4 extension)

`market_research.research_engine.compute_research(issuer, technical, event_feed,
symbol, market, now)` is the deterministic, network-free computation seam for
the existing A/B company report and future C watchlist refresh.

**Inputs are already fetched evidence.** Fetching TWSE/SEC issuer facts,
verifying trading-session OHLC, scanning configured strategy patterns and
retrieving official event feeds remain in `scripts.company_report.run()`.
The extracted pure core owns evaluation of evidence, official events, sector
eligibility, existing annual financial comparison, guarded illustrative
valuation and research readiness. It does NOT fetch current market data,
write Git state, download filings, or render/write Artifacts.

The existing v4 report fields, Markdown sections, pipeline-only `complete`
and `scripts.company_report.run()` signature remain compatible.
`research_readiness.components` adds evidence-scoped independent statuses
for issuer, source evidence, valuation provenance, annual financials,
technical prices/patterns, illustrative valuation, official events, trade-plan
and final recommendation. Each status describes that **component**, never an
overall verdict or investible rating. Source error or partial coverage does
not imply no event or automatic buy/sell. Legacy `stage` and other fields
remain untouched to avoid breaking candidate scan and downstream consumers.

**Time contract:** existing on-demand SEC collection still uses prior
America/New_York filing date when the publication time is unknown. The pure
compute seam applies the same conservative annual as-of to financial and
valuation functions; other event-source publication precision is separate.

**Further work:** I01 remains a broader Epic plan; this PR only extracts
the pure computation seam and scoped readiness statuses. Longitudinal
research revision identity, snapshot persistence/outbox, richer sector
modeling and A/B/C live integration remain independent Issues.
Validation: offline fixtures and PR Unit; company-research Live TWSE Workflow;
US SEC Live Acceptance requires SEC_USER_AGENT configuration and is distinct.
