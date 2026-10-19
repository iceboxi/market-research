# F05 — Taiwan IFRS official-source discovery (2330 pilot)

Status: **DISCOVERY INCOMPLETE / F06 NOT UNBLOCKED**. Verified by read-only
GitHub-hosted runner on 2026-10-19 UTC; see
[Live Run #39220050275](https://github.com/iceboxi/market-research/actions/runs/39220050275)
and its [source-probe Artifact](https://github.com/iceboxi/market-research/actions/runs/39220050275/artifacts/12171366581).
First attempt #39219974862 failed in a local Unicode bytes literal test and **never
reached source discovery**; second run fixed it and completed all tests and network reads.

## Observed sources and limits

| Source / official interface | Real HTTP / 2330 observed | What is proven | What is NOT proven |
| --- | --- | --- | --- |
| TWSE OpenAPI Swagger `/v1/swagger.json` | HTTP 200 | Public specification lists `t187ap06_L_ci` IS and `t187ap07_L_ci` BS | No matching cash-flow endpoint found in this live Swagger; absence here does not prove no MOPS source exists |
| TWSE `/v1/opendata/t187ap06_L_ci` — general-industry comprehensive income | HTTP 200; 1050 listed rows, **one** 2330 row | Current aggregate source contains issuer-identified IS shape; row keys include `年度`, `季別`, `出表日期`, `營業收入`, `本期淨利（淨損）`, EPS | That row is **not independently verified as 2024 Q4**, historic revision, exact time of release or audited/consolidated comparable full fiscal income |
| TWSE `/v1/opendata/t187ap07_L_ci` — general-industry balance sheet | HTTP 200; 1050 rows, **one** 2330 row | Current aggregate issuer-identified BS shape; keys include `年度`, `季別`, `出表日期`, assets/liabilities/equity | Same missing 2024 Q4 identity, exact publication timestamp, history, consolidation scope and revision |
| MOPS `/mops/web/t164sb05` — cash-flow query | HTTP 200, HTML landing | The endpoint is reachable in CI | **Not a fetched 2330/2024 Q4 CF statement**: no confirmed form controls/cashflow table markers in sampled returned HTML |

### Cross-statement acceptance matrix

- Issuer identity: **2330** positively identified in two **current** TWSE JSON aggregate responses.
- Period: response schemas advertise year/quarter/report date keys, but this probe did **not record or validate** the values for specific fiscal period `2024-Q4`.
- Three statements matched on one fiscal period / same issuer: **not verified**.
- Consolidated vs standalone report scope and unit: **not verified**.
- Signed/released filing, original document ID, annual vs cumulative quarter, restatement lineage: **not verified**.
- Actual published_at, first_seen_at and as-of historical availability: **not verified**. `出表日期` does not equal exact published_at; `retrieved_at` does not imply earlier availability.
- Real-cash-flow retrieval: **not verified**. Need official XBRL/download documentation, permitted access, compatible issuer-period-scope and version evidence.
- Redistribution / historical retention: **not fully cleared**. Government Open Data dataset metadata for the IS/BS resources separately refers to Government Open Data License v1; verify applicability to each specific machine endpoint and intended republication and confirm any other constraints. MOPS dynamic HTML/XBRL acquisition/redistribution remains unverified; no broad scraper is approved.

## Sources and legal/discovery references

- [TWSE OpenAPI Swagger](https://openapi.twse.com.tw/) — officially listed financial statement endpoints and usage link.
- [Official MOPS](https://mops.twse.com.tw/mops/web/index) — navigation includes balance sheet, comprehensive income, cash-flow, XBRL single-company/batch download and financial report correction queries. UI availability **is not** a committed API contract.
- [TWSE site terms](https://www.twse.com.tw/zh/terms/use.html); [Taiwan Open Government Data License](https://data.gov.tw/license).
- [General-industry income dataset](https://data.gov.tw/dataset/91998) and [general-industry balance dataset](https://data.gov.tw/dataset/94831) — verify official metadata and reuse requirements separately.

## Evidence and reproducibility

The bounded read-only `scripts/tw_ifrs_discovery.py` is a one-shot
research probe, not a data adapter. It captures **source URLs, HTTP codes,
schema/column names, structural issuer match, timestamps, and explicit
unknown flags**, never full third-party statements or value fields. The
preliminary analysis is preserved in the GitHub Actions Artifact, not
deployed as a new schedule. `tests/test_tw_ifrs_discovery.py` tests 200
landing without data, missing issuer, source failures and no value leakage.

To reproduce on a new runner, use an **explicit reviewed workflow or a
manual GitHub Actions execution** that runs:
`uv run --no-sync pytest tests/test_tw_ifrs_discovery.py` then
`uv run --no-sync python -m scripts.tw_ifrs_discovery --out ifrs_discovery_output`.
Probe outputs are evidence, not investment financial inputs. **Do not**
install this as a recurring scraper.

## Next discovery checkpoints (separate Issue work, not silently completed)

1. Confirm TWSE current general-company IS/BS fiscal year and quarter field
   semantics (ROC vs Gregorian, accumulated vs quarter, published_at), currency/unit and consolidation scope; verify one audited issuer+period by original report.
2. Find and document a **sanctioned** official MOPS/XBRL document or export interface for CF with permitted automated access. If unavailable, record unsupported status, avoid fragile form POST replay.
3. Obtain an actual 2330 quarter/year **BS+IS+CF with same scope and period**, source document identifiers, plus one documented correction/restatement example (original and amendment) and published timestamps or first-seen prospective policy.
4. Check official data-use and redistribution/license terms per source. Until clear, do not persist bulk statements or publish their content; store compact permitted evidence only.
5. Only after above, finalize the F06 normalized IFRS report adapter, with as-of fail-closed, year-over-year/quartile fixtures, A/B/C shared engine integration and independent real GH Actions acceptance.

**Recommendation:** Keep F05 **open** with `needs-info` or a follow-up discovery gate.
Do not label the financial integration `complete`, compute intrinsic stock
fair value from monthly revenue, or close F06 solely because public webpages
exist.
