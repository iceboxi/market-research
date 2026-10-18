# Official event watchlist — Mode C foundation

A separate GitHub Actions schedule or manual dispatch checks a curated
watchlist without requiring a technical price signal or making a trade.
For the first pilot, only TWSE 2330.TW is enabled. Add AAPL after adding
the SEC_USER_AGENT Actions Secret. Source coverage is explicitly limited.

Every healthy run compares stable official event IDs with the previous
compact state saved to event_state/{market}/{symbol}.json on main.
The first run creates a baseline and **never alerts**. Later newly observed
official event IDs are recorded as requires_research_review. Older missing
IDs are kept in seen_ids so rolling feed windows do not generate duplicate
change notifications. The seen set is capped at 2000 IDs; it is a bounded
deduplication cache, not a complete event archive.

A partial/unavailable source does not update the baseline, pretend there
are no disclosures, or generate an investment signal. Future/out-of-order
or incompatible snapshots are also rejected. State only stores IDs,
timestamps and official source references, not copied disclosure bodies.

Outputs: event_watch_output/watch_receipt.json, watch_summary.md and
proposed_state; Actions retains the Artifact for 14 days. A successful run
pushes compact state to main using fast-forward retries, making the next
scheduled run compare against genuine previously observed disclosures.
No GitHub Issue alert or third-party notification is sent in this phase.
That requires its own reviewed delivery and deduplication contract.
A detected change is a *research review prompt*, not a bullish/bearish
classification or trading recommendation.

The SEC submissions API acceptanceDateTime has reported inconsistent
timezone interpretation; the parser conservatively **excludes all same
UTC-date filings** when deciding what was already public. Prior-day
filing metadata are retained; exchange-calendar intraday timing is not
claimed. Scheduled future earnings dates are NOT inferred.
