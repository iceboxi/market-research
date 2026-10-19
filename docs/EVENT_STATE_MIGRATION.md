# Official event state migration — M01 / Issue #9

The official watch now reads the `events` namespace of the existing
`GitStateStore` instead of accessing a competing local `event_state` directory
or pushing the application `main` branch. Canonical state is in
`research-state/events/event_state/{market}/{symbol}.json`. The embedded
`event_state` prefix deliberately preserves original legacy path identities.
No full financials, price histories or disclosure bodies are committed.

## Production bootstrap

Explicit one-time migration from the tracked legacy main `event_state` prefix:
pause the previous event-watch workflow and wait for any in-flight jobs to
finish before deploying/cutting over. Deploy the PR-reviewed implementation
and use **Official disclosure watch → Run workflow → main →
bootstrap_events=true**. The bootstrap script checks both main event context
and matching `GITHUB_SHA` before importing. The real remote namespace must
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
