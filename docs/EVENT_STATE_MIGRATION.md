# Official event state migration — M01 / Issue #9

The official watch now reads the `events` namespace of the existing
`GitStateStore` instead of accessing a competing local `event_state` directory
or pushing the application `main` branch. Canonical state is in
`research-state/events/event_state/{market}/{symbol}.json`. The embedded
`event_state` prefix deliberately preserves original legacy path identities.
No full financials, price histories or disclosure bodies are committed.

## Production bootstrap

Explicit one-time migration from the tracked legacy main `event_state` prefix:
disable the existing **Official disclosure watch** workflow and wait for any
in-flight jobs to finish **before starting the production migration**.
PR #15 has already been merged, but this does not mean its event namespace was
bootstrapped. After deploying this bootstrap-isolation fix to main, run the
separate **Official event state bootstrap** workflow on main with
`confirm_migration=true`. The bootstrap script checks (via GitHub
API) that the old event-watch workflow remains manually disabled, has no
unfinished runs, and that the main revision matches `GITHUB_SHA`. After a
successful Artifact inspection, re-enable Official disclosure watch and run
it twice manually. The bootstrap uses a separate workflow specifically to
avoid requiring a disabled event watcher to launch its own migration. The real remote namespace must
not already have a conflicting owner or corrupt data.

Subsequent normal dispatches and scheduled runs **never** bootstrap. The
restore step reads the canonical namespace and writes only the runner-local
input tree. If its namespace is absent, corrupt, inaccessible or deleted,
the run fails; it will not silently treat prior seen events as a new baseline.

Healthy source proposals are merged independently; partial source coverage
still fails the overall workflow **after** healthy records are persisted.
The watcher / archive / restore receipts, eligible count, source coverage,
authority proof, state commit, main before/after and code revision should be
inspected in the run Artifact.

## Separate acceptance gates

- PR Unit tests and temporary bare-Git persistence tests.
- Live production bootstrap on `main`, verifying migration proof and main
  unchanged; inspect `bootstrap_receipt.json`.
- Two real TWSE manual dispatches with restore, deduplication, persisted state
  and Artifact inspection. Natural new events are not guaranteed: a second
  run with no new IDs can still prove no duplicate review.
- Natural `event=schedule` operations and separate TW/US scan gates remain
  tracked in Issue #14; manual runs do not satisfy them.

No event observation is automatically a trading instruction, news sentiment
prediction or full-fidelity historical market event replay.

## Concurrent work and restore safety

Unrelated PR merges may advance main while a watch is archiving. The archive
records before/after main and an unchanged analysis checkout; it does not claim
that other Agents are forbidden from merging. Production bootstrap is stricter:
the legacy import proof and final main revision must match the dispatched SHA.
Restore requires a fresh, empty output directory to prevent stale local baseline
files being mistaken for canonical state.

## Empty legacy event history (Run #39196950385)

The former main branch may contain **zero** `event_state/` files, as in
[failed Bootstrap #39196950385](https://github.com/iceboxi/market-research/actions/runs/39196950385).
Git does not store empty directories; the old `GitStateStore.commit` ran
`git add events` even though no such files existed. The corrected writer
stages the `.state-store.json` manifest alone for a verified zero-record
initialization. This is safe *only* through the explicitly gated bootstrap.

A successful bootstrap with zero legacy events creates an `events`
authority with `record_count=0`, an import source SHA and SHA-256 checksum
in the `research-state/.state-store.json` manifest. The `events/` directory
will not appear in the Git tree until the first validated event is saved;
**do not interpret its absence as an uninitialized namespace**. Inspect the
manifest and successful bootstrap receipt before re-enabling the watcher.

Keep Official disclosure watch disabled until the fix has passed PR tests,
merged into main, and the controlled bootstrap has succeeded. If a failed
attempt left a partial or corrupt authority, stop and inspect the authority
rather than reinitializing or erasing state.
