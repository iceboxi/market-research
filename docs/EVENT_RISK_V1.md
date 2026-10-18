# Event and official-disclosure risk contract (v1)

This is the first, conservative event-risk layer shared by Mode B company
research and Mode A automatic candidate reports (which invoke the same
report engine). It does not classify news as bullish/bearish or create prices.

Official source adapters:

- TWSE [listed-company daily material disclosures](https://openapi.twse.com.tw/v1/opendata/t187ap04_L):
  reads the current snapshot with the company's ROC speech date/time,
  records a short disclosure subject, timestamps and source. **Publication
  (speech) time, not event-occurrence date, controls what could be known.**
  Cannot reconstruct prior snapshots from the current endpoint. If snapshots
  are stale/empty/unparseable or evaluation is historical, coverage is
  `unavailable`. This is NOT a comprehensive news history.
- US [SEC company submissions](https://www.sec.gov/search-filings/edgar-application-programming-interfaces):
  reuses the existing SEC submissions lookup to extract recent 10-K,
  10-Q, 8-K, 20-F and 6-K metadata. The acceptance timestamp, when
  available, controls same-day lookahead. Filing date alone cannot establish
  intraday availability; such same-day rows are excluded. The submission
  is **not proof of a surprise or favorable/unfavorable earnings**.

`official_events`: status, limited coverage, observed event records, source
and `upcoming_earnings=not_verified`. `event_risk`: a
`manual_review_required` flag for filings within the last seven calendar
days; `coverage_incomplete` when no verifiable source; or
`no_recent_observed_events` (explicitly limited to verified source
coverage). A report's lack of observed events is NEVER proof of low risk.

Future event calendars, earnings release times, exchange trading suspensions,
corporate-action calendars, relative surprise vs estimates, and news sentiment
require independent verified sources and separate acceptance. No automatic
trade recommendation or price changes are authorized.

Report JSON schema_version increments from 2 to 3; scan artifact contracts
are unaffected. This version avoids persisting full third-party disclosure
bodies in public Artifacts. All dates are point-in-time bounded. For US
reports, SEC_USER_AGENT is still mandatory. The event adapter can report
unavailable without breaking the existing pipeline but clearly identifies
coverage limits.
