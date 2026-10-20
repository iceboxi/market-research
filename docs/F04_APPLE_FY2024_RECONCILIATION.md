# F04-C — Apple FY2024 first-party SEC revenue reconciliation

Scope: manually transcribed **reported consolidated net sales** (USD millions), from actual EDGAR reports. These are illustrative source-observed arithmetic tests, **not** a live SEC CompanyFacts ingestion, approved publication-time history, or proof that revised filings are interchangeable. No SEC raw content is stored.

| Period | Fiscal period end | Cumulative net sales (USD millions) | Source accession | Filed |
|---|---|---:|---|---|
| Q1 | 2023-12-30 | 119,575 | [10-Q 0000320193-24-000006](https://www.sec.gov/Archives/edgar/data/320193/000032019324000006/aapl-20231230.htm) | 2024-02-02 |
| H1 | 2024-03-30 | 210,328 | [10-Q 0000320193-24-000069](https://www.sec.gov/Archives/edgar/data/320193/000032019324000069/aapl-20240330.htm) | 2024-05-03 |
| Nine months | 2024-06-29 | 296,105 | [10-Q 0000320193-24-000081](https://www.sec.gov/Archives/edgar/data/320193/000032019324000081/aapl-20240629.htm) | 2024-08-02 |
| Full year | 2024-09-28 | 391,035 | [10-K 0000320193-24-000123](https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm) | 2024-11-01 |

Comparison: official [Oct 31, 2024 earnings 8-K exhibit (accession 0000320193-24-000120)](https://www.sec.gov/Archives/edgar/data/320193/000032019324000120/a8-kex991q4202409282024.htm) reports fourth-quarter net sales **94,930 USD millions**, matching **391,035 − 296,105**. Derived Q2 = **90,753**; Q3 = **85,777**. No statement of exact intraday first-availability is made.

In `tests/test_aapl_fy2024_sec_reconciliation.py`, each amount is multiplied by 1,000,000 to preserve original USD scale. The common source field identifies the SEC EDGAR evidence collection while original filing accessions remain on every observation; links above identify the individual filings. An operator-assigned `comparability_key` is provisional and **not proof of SEC amendment lineage**.

**Cutoff guard:** the October 31 8-K was filed before November 1's 10-K; the 10-K full-year amount must not become historically visible when replaying an October 31 cutoff. The 8-K directly published Q4 but is **not** used as a substitute 10-K/YTD source in this test. `asof=2024-11-01` is date-only and not precise public availability within that day.

**Unresolved:** independent original XBRL taxonomy tag mapping to these line items, exact API response provenance, per-filing amendment / corrections proof, durable first-seen, SEC compliant automated ingestion with real user-agent, generalization to multiple fiscal calendars, EPS/share semantics and production TTM acceptance. This exercise cannot make a real investment recommendation or enable valuation/trading. `source_acceptance` remains `not_evaluated`.
