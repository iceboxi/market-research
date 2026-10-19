# O04 — Remote-first correlated acceptance (synthetic pilot)

GitHub Actions remains the final execution and validation platform. All
Pull Requests, **including docs-only PRs**, must receive a token-minimal
offline check on the exact PR head SHA. This avoids a missing required
check when changes affect only project planning documents.

The manually dispatched **Correlated remote acceptance** workflow runs
on main only. It dispatches **Synthetic acceptance child** on the same
main ref, with a unique correlation token and expected code SHA. The
parent polls for the child whose display title matches that token;
verifies the actual child run ID, head SHA, ref, event and successful
conclusion; downloads the corresponding ZIP Artifact, and validates
its receipt JSON, exact SHA, correlation, schema, outcome and source
coverage. A HTTP 204 dispatch, parent start, or mere Artifact presence
does **not** count as success. Missing/expired/bad/partial receipts
cause failure and a persisted failure receipt.

Both workflows are synthetic and intentionally do **not** access market
data, SEC_USER_AGENT, production state, secrets, or broker APIs. Their
success proves remote Actions orchestration and Artifact contract only.
It does NOT prove TWSE/SEC live ingestion, research correctness, schedule
acceptance (#14), or investment strategy effectiveness.

O04 follow-on gates for actual market-data workflows must apply the
same run-ID/SHA/Artifact rules with source-specific coverage assertions,
rather than labelling this synthetic pilot as a financial live test.
