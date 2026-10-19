## A1 + B1 prospective cutover contract (2026-10-19)

User approved **A1 stable research-method cohorts** and **B1 controlled migration**.
New schema v2 observations pin exact `code_sha` per run, but cohort comparison
uses `config_sha256`, `provider_sha256`, `calendar_sha256` and
`method_sha256`. Unrelated docs and code changes do not automatically cause
new cohorts. Method changes must be reviewed and frozen anew. Schema v1 is not
retroactively rewritten or silently compared to schema v2.

The EOD workflow uses repository variable `PROSPECTIVE_STATE_MODE`:
- absent or `legacy`: previous schema v1 collection and legacy main writer
  (preserves current operational behavior until controlled cutover);
- `canonical`: schema v2 source SHA / method fingerprint, guarded metadata-only
  `GitStateStore` writer and fresh-read receipt. It **never** falls back to main;
- any other value: explicit failure, no prospective archive.

**Do not turn `PROSPECTIVE_STATE_MODE` to canonical until controlled
bootstrap has passed and no legacy run is active.** The operator must disable
EOD market scan, wait for in-flight jobs, run separate **Prospective state
bootstrap** with `confirm_migration=true` on main, inspect authority proof,
then set the variable to `canonical` before re-enabling scan. Initial and
second real scheduled sample acceptance must be evidenced by genuine
`event=schedule` runs; no manual scan manufactures prospective observation.
The existing operations/history namespace must remain unchanged.

Do not start a v2 cohort silently on the existing v1 freeze if v1 exists;
the unchanged-freeze v1-v2 boundary requires explicit new method-cohort
approval and a separate freeze policy. GitHub Actions unit/push CI do not
demonstrate production bootstrap or actual scheduled execution.
