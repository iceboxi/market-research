"""US index daily closes for knowledge/data/macro (yfinance; run with `uv run --frozen python -I`).

Usage: python -I fetch_us_indices.py <out_csv> <end YYYY-MM-DD>
"""
import csv, sys
from datetime import date, timedelta
import yfinance as yf

out, end = sys.argv[1], date.fromisoformat(sys.argv[2])
tickers = {"^SOX": "sox", "^GSPC": "spx", "^IXIC": "nasdaq"}
rows = {}
for t, col in tickers.items():
    h = yf.Ticker(t).history(start="1990-01-01", end=(end + timedelta(days=1)).isoformat(), auto_adjust=False)
    for ts, c in h["Close"].items():
        rows.setdefault(ts.date().isoformat(), {})[col] = round(float(c), 2)
    print(t, len(h), h.index[0].date(), h.index[-1].date())
with open(out, "w", newline="") as f:
    w = csv.writer(f, lineterminator="\n")
    w.writerow(["date"] + list(tickers.values()))
    for d in sorted(rows):
        w.writerow([d] + [rows[d].get(c, "") for c in tickers.values()])
