# F03 narrow date-only SEC acceptance gate

Company report SEC annual facts are filtered at the source adapter using
the prior New York calendar day, not the UTC date of generation. SEC
companyfacts exposes a filing date, but does not supply independent proof
that a specific filing was public before a same-day intraday cutoff.
Therefore on-demand reports do not use *any* filing dated the current
America/New_York day in annual metrics, comparisons or illustrative
valuation. The event feed keeps its separate event-publication contract.

The source-evidence date-only classification uses the same New York
calendar for SEC filings. Historical comparatives, specific amendment
versions and exact publication timestamps still require separate F03
source-version acceptance; passing this narrow guard is not proof of
fully point-in-time SEC historical replay.

No data source, sector eligibility, state-store writer, broker interface or
trading recommendation is added. GitHub Actions Unit and on-demand company
research validation remain mandatory.
