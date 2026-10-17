# Prospective research observation receipts — operational contract

`EOD market scan` now contains an additional **scheduled-only** research step. It runs only after a successful scheduled market scan and a healthy scan report; it does not run on `push` or manual `workflow_dispatch`, so CI research activity is never misclassified as prospective evidence.

1. The completed exchange session must be later than the 2026-10-18 freeze date, with exact single-market coverage and no price-source errors.
2. A temporary config enables all **nine currently disabled** research plugins in isolation. The production `strategies.yaml` file remains unchanged: only `sakata_three_soldiers` is live.
3. Candidate research re-fetches the same six-month period with strict completed-session freshness. **Every normalized input SHA-256 must match the immediately preceding official production scan**; otherwise the receipt is rejected, never approximated.
4. The metadata-only receipt carries a hash of catalog, strategy parameters and market universe, the source run URL, trading-session date, strategy versions, matches and abstention count. Raw vendor OHLCV data and simulated P&L are never stored.
5. `scripts/prospective_archive.py` appends one receipt to `prospective/<freeze-hash-prefix>/<market>/<YYYY-MM-DD>.json`. An identical rerun is idempotent; any conflicting record for the same market/session/hash fails. GitHub `contents: write` is supplied by the scheduled scanner. All archive errors remain visible as failed Action steps.
6. A new freeze cohort is required whenever configuration/catalog changes. Future program versions must additionally pin the exact source code version before any data is treated as scientifically independent.

**Status:** integration code and Unit tests are deployed. The first genuine post-freeze scheduled observations can only be verified after the next completed market sessions; this document is *not* evidence that any such observations already exist. A receipt does not include five-session outcomes, realized fills, borrowing availability, taxes, dividend cashflows, or a performance conclusion. The [evidence gate](EVIDENCE_POLICY.md) remains BLOCKED even when receipts accumulate.

Operational constraints: GitHub scheduled events may delay or be skipped; repeat provider queries can differ or fail; in these cases the scanner/job will surface a failure rather than write misleading prospective evidence. Changing the cohort without storing a new code hash is another methodological limitation pending a future release.
