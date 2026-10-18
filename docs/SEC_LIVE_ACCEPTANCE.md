# SEC live financial acceptance

After setting repository Actions secret `SEC_USER_AGENT` to a genuine contact
name and email, open **Actions → SEC live annual financial acceptance → Run
workflow**, enter `AAPL` and inspect the resulting summary and 14-day
`acceptance.json` / `acceptance.md` Artifact.

This workflow fetches current **real SEC filings** independent of Yahoo market
data, so it distinguishes SEC integration failure from historical price-data
failure. The CLI is `uv run --no-sync python -m scripts.sec_live_acceptance
--symbol AAPL --out sec_acceptance`.

**Pass** means SEC issuer identity is present, annual USD/10-K source contract
is coherent, and each of annual revenue, income, operating cash flow,
capital expenditures, diluted average shares and derived free cash flow has at
least one annual observation. The report records the count for each metric,
the SIC code, valuation status and the exact reasons it was blocked.

Pass does **not** mean three annual periods align, that debt/current shares are
reconciled, or that price forecasts are trustworthy. Those gates remain in
`evaluate_valuation()` and may still return `not_evaluated`. Use the
resulting report to prioritize gaps without silently inventing data.
