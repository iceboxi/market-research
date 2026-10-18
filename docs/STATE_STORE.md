# Shared metadata store — operations history

`scripts/state_store.py` provides the shared stdlib-only `GitStateStore.read()` /
`commit()` interface. The first migrated consumer is health history in
`scripts/monitor.py`. Event baselines and prospective receipts still use their
existing owners; this change does not make the whole repository PR-only.

## Canonical state and compatibility

The `research-state` branch contains `.state-store.json` and namespaced JSON
metadata. Health records live at
`operations/history/YYYY/MM/YYYYMMDD-run-ID.json`. No application files,
OHLCV series or disclosure bodies belong in this tree.

The manifest records namespace schema, authority branch, current count / SHA-256
and the initial legacy import's main SHA, prefix, count and SHA-256. Hashes use
UTF-8 JSON with sorted keys, no ASCII escaping, no non-finite numbers and compact
separators. Integrity is checked before reading or merging any namespace.

`monitor.archive(record)` keeps its logical `history/...` return value for
existing callers. `archive_history(record)` additionally returns a versioned
persistence receipt. `monitor.history()` reads the canonical namespace and
checks health identity/path consistency. Local `monitor.read()` still reads
individual run artifacts; it is not a competing long-term history reader.

Only explicit `initialize_history()` migration imports legacy main history;
ordinary archive/read never initializes authority or falls back to main. A
missing/corrupt initialized store, including a deleted remote branch, is a
failure, not a new baseline. Legacy tracked history remains read-only and is not
deleted. Reinitialization is not a recovery procedure for lost production state.

## Ordering, failure and concurrency

Analysis stays on its original checkout and revision. Git uses detached
temporary worktrees, ordinary fast-forward pushes and at most three attempts;
each retry reads the latest remote state and reruns the domain merge. Reads do
not use shared `FETCH_HEAD` as authority.

History is append-only: same key and same content is idempotent, while different
content for an existing key fails. Concurrent distinct keys are retained. A
source failure's critical health record can still be archived; source health and
persistence success are separate fields. Transport, schema, integrity and push
errors cannot report durable success.

The scan's separate `health-state-RUN_ID` Artifact includes code SHA, state commit,
main before/after, migration proof, source health and run URL. Failure receipts
retain failure status, IO stage and available provenance, including a known
persisted commit if a later probe fails. An uncertain write is marked
`outcome_unknown`, not "not written". Artifact retention is 14 days;
the data branch is the durable owner.

## Production cutover

Before merging this migration, pause all legacy health writers (`EOD market
scan` and the operations permission smoke test) and wait for their running jobs
to finish. Also check any manually dispatched runs. Import from the latest main
only while these writers are quiescent. After deploying the new code, dispatch
`State-store live acceptance` on main with `bootstrap_operations=true` while both
legacy workflows remain paused. This explicit step checks disabled states and
unfinished jobs, imports and fresh-reads operations, and records the migration
proof in its Artifact. Then resume workflows and use a real manual scan to verify
history write / fresh read and inspect the receipt.

If an initialized namespace is damaged, stop writes and repair or explicitly
migrate forward. Do not reset the data branch or resume the old writer against
stale main history. Prospective, event, lock and remaining smoke/manual side
effects have separate migration gates. Do not enable strict main protection
until those gates have been handled.

## Validation and remaining gates

`State-store live acceptance` runs real bare-Git integration tests, then writes
explicitly synthetic metadata to `research-state-validation`, performs a fresh
read and an identical retry, and checks that main and the analysis revision did
not move. Ordinary PR/push/manual acceptance has no Issue-write permission and
does not touch production state. Only explicit main dispatch with the bootstrap
input enables production migration. Existing synthetic `ops_validation` health
archives are also routed to the validation branch. Artifacts contain receipts and
the validated state snapshot.

The synthetic receipt intentionally does not claim market-data coverage. A real
source EOD dispatch after deployment verifies production operations separately.
Natural cron, event/prospective migration, financial evidence retention and
notification delivery remain separate gates; neither tests nor manual dispatch
prove strategy effectiveness.
