# F01 source evidence and instrument suitability (first increment)

Company report schema v4 adds source_evidence and instrument_eligibility.
Original monetary units are kept, with explicit TWD_thousands scale.
SEC filed date has date-only precision; neither SEC submission acceptance
nor TWSE snapshot retrieval is independently verified publication time.
Unknown source availability is NOT made up as midnight or backfilled for
historical replay. The existing pipeline-only complete flag remains unchanged.

Financials and investment funds do not qualify for generic company FCF
scenarios. A verified nonfinancial SIC is a *candidate*, not definitive
identification of a tradable operating company or a fair-value claim.
TWSE monthly revenue cannot substitute for IFRS annual statements.

This intentionally does not close F01's full historical availability gate;
F03 must reconcile SEC filings/accessions/versions and F05/F06 the official
TW IFRS sources. No strategy validity or broker-executable levels are claimed.
