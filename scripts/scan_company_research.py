"""Convert verified EOD scan matches into bounded, source-linked research.

Research is never a buy signal. This does not send alerts or place orders.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re

from scripts.company_report import run as run_company_report

SAFE_TICKER = re.compile(r"(?:[0-9]{4,6}\\.TW|[A-Z][A-Z0-9.-]{0,9})\\Z")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def candidates(manifest, quality, signals, health):
    """Reject incomplete/stale/misidentified scan artifacts before any network I/O."""
    if health.get("health") != "healthy" or health.get("scan_outcome") != "success":
        raise ValueError("Scan health must be healthy before company research")
    if manifest.get("strict_freshness") is not True:
        raise ValueError("Strict completed-session freshness required")
    if manifest.get("error_count") != 0 or quality.get("errors"):
        raise ValueError("No incomplete ticker coverage allowed")
    if manifest.get("official_mismatch_count") != 0:
        raise ValueError("Official market close mismatch")
    if manifest.get("scanned_symbols") != len(quality.get("symbols", [])):
        raise ValueError("Quality coverage mismatches manifest")
    if manifest.get("matching_signals") != len(signals):
        raise ValueError("Signal count mismatches scan manifest")
    accepted = {
        (r["id"], r["version"]) for r in manifest.get("strategies", [])
    }
    rows = {}
    for item in quality["symbols"]:
        key = (item.get("market"), item.get("symbol"))
        if key in rows:
            raise ValueError("Duplicated symbol in scan quality artifact")
        rows[key] = item
    seen = {}
    for item in signals:
        market, symbol = item.get("market"), item.get("symbol")
        if not isinstance(symbol, str) or not SAFE_TICKER.fullmatch(symbol):
            raise ValueError("Unsafe ticker in signal artifact")
        if (market == "tw") != symbol.endswith(".TW") or market not in ("tw", "us"):
            raise ValueError("Market/symbol mismatch in signal")
        entry = rows.get((market, symbol))
        if not entry:
            raise ValueError("Signal has no validated matching quality row")
        if item.get("trade_date") != entry.get("last_date"):
            raise ValueError("Signal date differs from verified last market session")
        if (item.get("strategy_id"), item.get("strategy_version")) not in accepted:
            raise ValueError("Signal strategy is not configured and versioned")
        checksum = entry.get("input_sha256")
        if not isinstance(checksum, str) or not re.fullmatch(r"[a-f0-9]{64}", checksum):
            raise ValueError("No SHA-256 tying signal to checked price history")
        key = (market, symbol)
        row = seen.setdefault(key, {
            "market": market, "symbol": symbol, "last_session": item["trade_date"],
            "scan_sha256": checksum, "signals": [],
        })
        if item["strategy_id"] not in row["signals"]:
            row["signals"].append(item["strategy_id"])
    return sorted(seen.values(), key=lambda r: (r["market"], r["symbol"]))


def execute(scan_dir, out, max_candidates=3, research_fn=run_company_report,
            sec_user_agent=None, now=None):
    if not 1 <= max_candidates <= 20:
        raise ValueError("Use 1..20 research candidates per scan")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Timezone-aware evaluation time required")
    scan_dir, out = Path(scan_dir), Path(out)
    result = {
        "schema_version": 1, "generated_utc": now.isoformat(),
        "scan_run_id": None, "status": "blocked",
        "candidate_count": 0, "attempted_count": 0, "deferred_count": 0,
        "candidate_reports": [], "error": None,
        "disclaimer": "Automated research observations only, not investment recommendations",
    }
    try:
        manifest = load(scan_dir / "manifest.json")
        quality = load(scan_dir / "data_quality.json")
        signals = load(scan_dir / "signals.json")
        health = load(scan_dir / "health_report.json")
        result["scan_run_id"] = health.get("run_id")
        matches = candidates(manifest, quality, signals, health)
        result["candidate_count"] = len(matches)
        result["deferred_count"] = max(0, len(matches) - max_candidates)
        selected = matches[:max_candidates]
        result["attempted_count"] = len(selected)
        result["status"] = "no_candidates" if not matches else "complete"
        for candidate in selected:
            market, symbol = candidate["market"], candidate["symbol"]
            record = dict(candidate, status="pending", report_path=None, reason=None)
            result["candidate_reports"].append(record)
            if market == "us" and not sec_user_agent:
                record.update(status="blocked_configuration",
                              reason="SEC_USER_AGENT required for SEC company fundamentals")
                result["status"] = "partial"
                continue
            target = out / symbol
            try:
                report = research_fn(symbol, out=target, now=now,
                                     sec_user_agent=sec_user_agent)
                tech = report.get("technical", {})
                if not report.get("complete") or tech.get("status") != "available":
                    record.update(status="blocked_research_data",
                                  reason="Company research identity/technical data incomplete")
                elif (tech.get("last_session") != candidate["last_session"] or
                      tech.get("input_sha256") != candidate["scan_sha256"]):
                    record.update(status="blocked_data_drift",
                                  reason="Researched daily input hash or session differs from source scan")
                else:
                    record.update(status="research_ready",
                                  report_path=f"{symbol}/report.json",
                                  readiness=report.get("research_readiness", {}).get("stage"),
                                  valuation_status=report.get("valuation", {}).get("status"))
                if record["status"] != "research_ready":
                    result["status"] = "partial"
            except Exception as exc:
                record.update(status="research_failed", reason=type(exc).__name__)
                result["status"] = "partial"
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        result["status"] = "blocked"
        result["error"] = str(exc)
    out.mkdir(parents=True, exist_ok=True)
    (out / "candidate_index.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    lines = ["## EOD candidate company research", "",
             f"Status: **{result['status']}**",
             f"Candidates: {result['candidate_count']}; attempted: {result['attempted_count']}; "
             f"deferred by cap: {result['deferred_count']}", ""]
    if result["error"]:
        lines.append("Blocked: " + result["error"])
    for item in result["candidate_reports"]:
        lines.append(f"- {item['symbol']} ({', '.join(item['signals'])}): "
                     f"{item['status']} {item.get('reason') or ''}")
    lines += ["", "No ranking, targets, buy/sell alerts or broker orders. "
              "A healthy scan is not proof of investment value."]
    (out / "candidate_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--scan-dir", type=Path, default=Path("output"))
    p.add_argument("--out", type=Path, default=Path("output/candidate_research"))
    p.add_argument("--max-candidates", type=int, default=3)
    a = p.parse_args()
    result = execute(a.scan_dir, a.out, a.max_candidates,
                     sec_user_agent=os.getenv("SEC_USER_AGENT"))
    print((a.out / "candidate_summary.md").read_text(encoding="utf-8"))
    if result["status"] not in ("complete", "no_candidates"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
