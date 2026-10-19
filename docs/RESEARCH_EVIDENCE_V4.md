# F01 research evidence and instrument gates — company report JSON schema v4

The company report now exposes issuer_eligibility and source_evidence.
This does not claim to establish actual investment returns or trading
execution prices.

## Instrument eligibility

- US: require SEC submissions entityType = operating and valid SIC evidence
  before applying the legacy illustrative non-financial corporate P/FCF
  scenario calculation. Financial/insurance/real-estate SIC 6000–6999
  remains ineligible; missing or non-operating entity type, missing SIC,
  funds/ETFs/trusts and unsupported security identities are unknown.
  The SEC filer type is not proof of a particular ticker share class;
  security_class_verified is false.
- Taiwan: a matching official TWSE company profile with an industry code
  identifies a listed-company issuer; industry code 17 is financial
  and requires a dedicated valuation contract. Missing company/industry
  source is unknown. This update does not add audited Taiwan IFRS facts.
- All instrument gates are distinct from the legacy complete flag:
  complete only indicates an available company name and successful
  technical data/strategy pipeline. It does NOT certify investment research.

## Evidence semantics

The source_evidence block describes each observed raw or derived metric's
value/null, original unit and scale, currency, period, origin, accession(s)
when available, retrieval time, availability precision and parser contract.
Retrieval at a certain instant is NOT proof the source was published then.

SEC filed date is *date only*, with no authoritative intraday timestamp
in companyfacts. On-demand company reports now conservatively fetch
SEC annual companyfacts using only filing dates strictly earlier than the
evaluation's UTC date, so amendments dated that same day cannot leak into
morning reports. This is conservative, not proof of exact SEC publication
at an earlier instant. Separate timestamp-bearing source evidence is
required for trustworthy past intraday replay.

TWSE profile/monthly-revenue endpoints are current snapshots; their
reported dates are not source_publication_at. The facts remain a separate
monthly research observation and are explicitly *not verified* for a
historical evaluation cutoff. No current snapshot is asserted to be
audited, a historical snapshot, or an annual IFRS statement.

## Compatibility and further gates

The on-demand company report schema_version changes v3 → v4, adding
source_evidence and issuer_eligibility while leaving the legacy complete
and scan outputs intact. Every new numeric valuation scenario remains
illustrative only, and unverified or unsupported issuers fail closed.
Future discovery is still needed for historical Taiwan publication times,
verified security share classes, audited IFRS statements, SEC
revisions/availability to sub-day precision, and the actual valuation
and execution-price models.

Tests run on GitHub Actions Python 3.12 and the committed uv.lock.
Passing unit tests does not imply full SEC or TW source acceptance.
