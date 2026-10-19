# F01 — evidence/time/instrument contract for company research

The on-demand report (also reused by Mode A candidate research) now emits
`source_evidence` (version 1), `instrument_eligibility` and explicit component
gates in `research_readiness`. Overall company report JSON increments to
schema_version **4**; the old `complete` value still only means issuer identity
and technical pipeline worked. This is **not** complete research, verified
valuation or investment advice.

**Source envelope:** raw value/null and original unit, USD/TWD/scale, reported
versus derived facts, fiscal start/end when present, document identity/tag,
original filing date, source URL, period, retrieval time and evaluated cutoff.
A SEC filing has **date-only** availability; the report never claims the
acceptance timestamp or publication time from that date. Same-cutoff-date
filings are unverified intraday. Historical TWSE profile and monthly-revenue
replay is unsupported; the latest endpoint is a current snapshot only.

**Instrument gate:** TWSE sector code 17 is financial/insurance (not generic
FCF); an unknown or unofficial TWSE profile is unknown. SEC investment-company
forms are classified fund/ETF before SIC; financial/real-estate SIC 6000–6999
requires a different model; unverified classification remains unknown.
Nonfinancial cases are only candidates, **not** certified to be valued.

**Valuation safety:** illustrative scenarios need an eligible issuer and dated
source inputs with original accession IDs on both FCF legs, predating the
intraday cutoff. A blocked gate prevents turning an illustrative scenario into
an unsupported company-research estimate. The historical XBRL revision
availability and exact SEC filing/publication semantics need independent F03;
TW annual IFRS and its report/revision history remain F05/F06.

The `technical` field remains independent; unsupported issuer valuation does
not erase valid daily price observations. No source time is fabricated, no
ETF portfolio-lookthrough is claimed, and missing values are not replaced by 0.

Source verification: TWSE official industry classification lists code 17 as
financial/insurance; see TWSE published industrial-sector code references.
All new behavior has offline fixtures; latest GitHub Actions is final execution
gate, with real source/data acceptance explicitly separate.
