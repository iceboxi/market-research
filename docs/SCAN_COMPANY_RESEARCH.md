# Mode A: EOD scan -> source-linked candidate company research (pilot)

After the existing real EOD scanner and `health_report.json` succeed, scheduled
and manually dispatched runs now invoke `scripts.scan_company_research`.
**No new strategy is enabled**. Only matching enabled-version strategies that
appear in `signals.json` become research candidates.

Before any company/API request the job requires: healthy scan; strict freshness;
complete symbol coverage; zero official price mismatches; exact matching
strategy ID/version, market symbol, completed session and input checksum.
Repeated matching strategies for one symbol produce **one company report**.
Default maximum is three symbols per run, deterministically sorted alphabetically
within market (not ranked by expected returns). Additional matches are counted
as deferred, not silently discarded.

Reports are generated using the SAME `scripts.company_report.run()` used by
Mode B. The company research downloads market prices a second time and checks
its latest session and SHA-256 against the original scan. Data drift blocks
association of the report with the scan signal and appears as a failure, not a
fabricated actionable trade.

`output/candidate_research/candidate_index.json` records every selected
symbol, matching strategies, failure status and references; completed
reports are saved under `candidate_research/SYMBOL/report.json` and `.md`.
US research additionally requires `SEC_USER_AGENT`; when missing the
candidate is marked `blocked_configuration` and the research stage fails
visibly. A zero-signal scan produces a successful `no_candidates` receipt
without fetching any issuers. The research stage does not post notifications
or place orders, and does not upgrade unvalidated patterns to buy advice.

Workflow push-triggered scans are excluded from research orchestration to
avoid redundant public issuer API calls during development. The pipeline
may be **healthy as a market-data scan** while candidate research is partial;
these statuses intentionally remain separate.
