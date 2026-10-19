# F03 annual SEC filing versions — research safety slice

Historical SEC `companyfacts` contains comparisons and amendments. The
`annual_version_trace` output preserves up to six fiscal spans and twelve
versions per span, containing exact period, filed **date-only**, 10-K/10-K/A,
taxonomy tag, accession, source and value. It does **not** prove a first-seen
timestamp or an accurate historic SEC snapshot.

For conflicting records from the same accession/tag/filing date, or different
accessions for the same tag on a single filing date, the fiscal span is
ambiguous and is not accepted as a numeric annual metric. Identical copies
are deduplicated. No tie is broken by API ordering.

FCF is now derived only from operating cash flow and positive PP&E capex for
the exact same annual fiscal duration **and the same accession number**.
A 10-K/A cash-flow update without a matching amended capex component
cannot be silently combined with the older 10-K component; FCF is absent
until safe pairing evidence exists. The source fields and component
accessions remain present for auditing.

This implementation may intentionally reduce annual financial coverage for
partially amended filers. It does not promise the historical versions
available at intraday timestamps, nor backtestable first-seen information.
An independent SEC filing/accession live reconciliation and availability
acceptance still remain under F03/F02; this PR must not close that entire
program. No new market-data or trading functionality is added.
