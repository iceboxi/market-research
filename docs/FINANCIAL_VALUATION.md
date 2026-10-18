# Annual SEC financial normalization & illustrative valuation

On-demand company research now records annual US financial history, with 10-K /
10-K/A provenance as known **at the evaluation date**. It extracts annual
revenue, net income, operating cash flow, positive property/plant/equipment
capital expenditures, annual diluted-average share counts and FCF
(operating cash flow minus positive PP&E spending). Only equal fiscal-year
durations are paired; comparison-year facts are de-duplicated; future filings
and quarterly durations are excluded. Metadata retains SEC accession,
source URL, filing date, fiscal start/end and original unit.

## Strict research valuation gate

The new P/FCF sensitivity **does not calculate intrinsic value or a trade
recommendation**. For US non-financial operating firms, the report displays
conservative / base / optimistic illustrative per-share scenarios at **10x /
15x / 20x** the **median of three consecutive annual positive free cash flows**,
divided by latest annual diluted-average shares. The multiples are fixed
exploratory assumptions, **not sector-calibrated or a forward cash-flow model**.

Conditions required: verified SEC SIC (financial/insurance/real-estate SIC
6000–6999 excluded); aligned annual revenue and positive earnings; three
consecutive, positive, source-dated annual FCF periods; latest diluted-average
shares; latest fiscal year not stale; and no filings after evaluation date.
Missing any condition returns `not_evaluated`. `entry_zone`, `stop_loss`,
`target_price` and `decision` remain non-actionable.

`illustrative_only` is **not** a completed, defensible valuation. Debt and
cash reconciliation, net borrowing, current share count, stock splits,
forward FCF, risk-adjusted discounting, market comparables and full financial
sector models remain absent. The 10/15/20x historical multiples must not be
interpreted as validated price targets.

Taiwan `2330.TW` remains `not_evaluated` until audited annual IFRS/MOPS
statements and cash flows can be reliably normalized with filing dates and
shares. Monthly TWSE revenue is *not* a substitute.

For US live tests, configure `SEC_USER_AGENT` with a real contact name
and email; the adapter additionally reads SEC submissions metadata for SIC.
The exact AAPL run must be validated separately in GitHub Actions.
