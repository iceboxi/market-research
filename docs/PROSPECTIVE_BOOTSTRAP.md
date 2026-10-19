# O02 — prospective bootstrap (opt-in, not activated)

This **separate** `Prospective state bootstrap` Action is only usable
after its PR is reviewed and merged on main. It does not run on PRs or
normal schedules. It requires `confirm_migration=true`, checks that
`EOD market scan` is manually disabled and has no pending/running runs,
requires the runner checkout SHA to equal remote main, and imports any
legacy `main/prospective/` history using the shared state store.

The migration produces a structured Artifact receipt with legacy-source
authority, state commit, manifest proof, record count, fresh-read
confirmation and main-before/after SHA. A zero-record legacy import
must still have an explicit authority marker; normal writers must never
automatically initialize it.

**Important:** The current scheduled prospective writer still points to
`main`; the bootstrap alone does not cut over a writer. Do not run it
until the complete write/read migration sequence and an approved code
cutover are ready. Do not restore a damaged namespace by rerunning
initialization. The first real post-cutover scan and later natural
schedule results require separate validation.
