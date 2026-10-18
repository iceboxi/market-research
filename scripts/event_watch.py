"""Independent official-event watchlist (research monitoring, no orders)."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import httpx
import yaml

from market_research.event_monitor import build_snapshot, compare_snapshots
from market_research.event_risk import tw_material_events, sec_filing_events, unknown
from market_research.fundamentals import SEC_SUBMISSIONS, SEC_TICKERS, json_get

ROOT = Path(__file__).resolve().parents[1]


def sec_events(symbol, now, user_agent, get=json_get):
    if not user_agent or "@" not in user_agent:
        return unknown("SEC", "SEC_USER_AGENT is not configured")
    try:
        listing = get(SEC_TICKERS, user_agent=user_agent)
        matches = [v for v in listing.values() if isinstance(v, dict)
                   and v.get("ticker", "").upper() == symbol]
        if len(matches) != 1:
            return unknown("SEC", "Ticker does not uniquely match SEC company mapping")
        cik = int(matches[0]["cik_str"])
        url = SEC_SUBMISSIONS.format(cik=cik)
        return sec_filing_events(get(url, user_agent=user_agent), now, url)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        return unknown("SEC", "SEC source or ticker mapping unavailable")


def read_previous(root, market, symbol):
    path = Path(root) / market / (symbol + ".json")
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def watch(config_path, state_root, out, now=None, tw_get=json_get,
          sec_get=json_get, user_agent=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Evaluation time requires timezone")
    data = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    items = data["symbols"]
    if not isinstance(items, list) or not items or len(items) > 30:
        raise ValueError("Watchlist must contain 1 to 30 symbols")
    out = Path(out)
    proposals = out / "proposed_state"
    reports = []
    for item in items:
        market = item["market"]
        symbol = item["symbol"]
        # Validate identity before calling any external API.
        build_snapshot(symbol, market, {"status": "unavailable"}, now)
        if market == "tw":
            feed = tw_material_events(symbol, now, tw_get)
        elif market == "us":
            feed = sec_events(symbol, now, user_agent, sec_get)
        else:
            raise ValueError("Unknown market")
        current = build_snapshot(symbol, market, feed, now)
        previous = read_previous(state_root, market, symbol)
        change, merged = compare_snapshots(previous, current)
        if merged is not None:
            dest = proposals / market / (symbol + ".json")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        reports.append({
            "market": market, "symbol": symbol, "event_source": feed.get("source"),
            "source_status": feed["status"], "coverage": feed.get("coverage"),
            "change_status": change["status"],
            "new_event_ids": change["new_event_ids"],
            "requires_research_review": change["notify"],
            "reason": change["reason"],
            "updated_state": merged is not None,
            "upcoming_earnings": "not_verified",
        })
    result = {
        "schema_version": 1,
        "generated_utc": now.astimezone(timezone.utc).isoformat(),
        "status": ("partial" if any(r["source_status"] != "available" or
                                    r["change_status"] == "state_incompatible"
                                    for r in reports) else "complete"),
        "reports": reports, "recommendations": "not_available",
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "watch_receipt.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["## Official event watchlist (research-only)", "",
             "Run: " + result["generated_utc"], "Status: " + result["status"], ""]
    for r in reports:
        lines.append(f"- {r['symbol']}: {r['change_status']} / {r['source_status']}; "
                     f"new IDs: {len(r['new_event_ids'])}; {r['reason']}")
    lines.extend(["", "First observed snapshot is a baseline, not an alert.",
                  "New IDs request research review, not buy/sell actions.",
                  "No upcoming earnings date verified; missing source does not mean no events."])
    (out / "watch_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path, default=ROOT / "config/event_watchlist.yaml")
    p.add_argument("--state", type=Path, default=ROOT / "event_state")
    p.add_argument("--out", type=Path, default=ROOT / "event_watch_output")
    args = p.parse_args()
    result = watch(args.config, args.state, args.out,
                   user_agent=os.getenv("SEC_USER_AGENT"))
    print((args.out / "watch_summary.md").read_text(encoding="utf-8"))
    if result["status"] != "complete":
        raise SystemExit("Some official event sources were unavailable; see receipt")


if __name__ == "__main__":
    main()
