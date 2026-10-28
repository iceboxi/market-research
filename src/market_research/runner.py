"""Run a market scan; preserve source provenance, findings, and failures."""
from dataclasses import asdict
from datetime import datetime, time, timezone
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import os

import pandas as pd
import yaml

from .provider import RoutedDailyProvider
from .market_data import load_daily_bars
from .snapshots import ReplayProvider, write_snapshot, write_index
from .data_contract import verify_scan_artifacts
from .strategies import get_strategy
from .validation import validate_daily
from .twse import twse_close_check


def save(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def run_scan(market="both", period="1y", out=Path("output"), config_dir=Path("config"),
             provider=None, include_snapshot=False, check_twse=False, now=None,
             verifier=None, snapshot_output=None, replay_dir=None,
             strict_freshness=False):
    markets = yaml.safe_load((config_dir / "markets.yaml").read_text())["markets"]
    strategies = [s for s in yaml.safe_load((config_dir / "strategies.yaml").read_text())["strategies"] if s["enabled"]]
    selected = list(markets) if market == "both" else [market]
    if any(m not in markets for m in selected):
        raise ValueError("Unknown market")
    if replay_dir and provider:
        raise ValueError('Cannot supply provider and replay directory together')
    provider = ReplayProvider(replay_dir) if replay_dir else (provider or RoutedDailyProvider())
    now = now or datetime.now(timezone.utc)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": 1, "generated_at_utc": now.astimezone(timezone.utc).isoformat(),
                "git_sha": os.getenv("GITHUB_SHA"), "github_run_id": os.getenv("GITHUB_RUN_ID"),
                "market": selected, "period": period, "interval": "1d", "data_source": provider.source,
                "strategies": [{"id": s["id"], "version": get_strategy(s["id"]).version,
                                 "params": s.get("params", {})} for s in strategies],
                "snapshot_included": include_snapshot}
    quality = {"symbols": [], "errors": [], "warnings": []}
    results, snapshots, records = [], [], []
    for m in selected:
        today = now.astimezone(ZoneInfo(markets[m]["timezone"])).date()
        # Live providers may confirm ad-hoc exchange closures; replay and
        # fixture providers keep the published calendar unchanged.
        closed = (tuple(provider.unscheduled_closures(m, now))
                  if strict_freshness and hasattr(provider, "unscheduled_closures") else ())
        if closed:
            manifest.setdefault("unscheduled_closures", {})[m] = [d.isoformat() for d in closed]
        for symbol in markets[m]["symbols"]:
            try:
                daily = load_daily_bars(provider, m, symbol, period, now,
                                        markets[m]["timezone"], strict_freshness,
                                        closed_sessions=closed)
                df = daily.frame
                checked = daily.metadata
                quality["warnings"].extend(daily.warnings)
                source = checked["source"]
                if m == "tw":
                    if source == "twse_stock_day_official_raw_ohlcv":
                        checked["official_data"] = "TWSE_STOCK_DAY_primary"
                    elif check_twse:
                        checked["twse_spot_check"] = (verifier or twse_close_check)(
                            symbol, df.index[-1], float(df["close"].iloc[-1]),
                            float(df["volume"].iloc[-1]))
                if snapshot_output:
                    records.append(write_snapshot(Path(snapshot_output), symbol, df, source))
                quality["symbols"].append(checked)
                if include_snapshot:
                    copy = df.reset_index().copy()
                    copy.insert(0, "symbol", symbol)
                    copy.insert(0, "market", m)
                    snapshots.append(copy)
                for strategy in strategies:
                    results.append(asdict(get_strategy(strategy["id"]).scan(
                        m, symbol, df, strategy.get("params", {}))))
            except Exception as exc:
                quality["errors"].append({"market": m, "symbol": symbol,
                                           "error_type": type(exc).__name__, "reason": str(exc)})
    if snapshot_output:
        write_index(Path(snapshot_output), records)
    signals = [r for r in results if r["matched"]]
    official_mismatches = sum(1 for entry in quality["symbols"] if entry.get("twse_spot_check", {}).get("status") == "mismatch")
    manifest.update({"sources_by_market": {"tw": "twse_stock_day_official_raw_ohlcv",
                                                      "us": "yahoo_finance_via_yfinance"},
                     "requested_symbols": sum(len(markets[m]["symbols"]) for m in selected),
                     "scanned_symbols": len(quality["symbols"]), "error_count": len(quality["errors"]),
                     "official_mismatch_count": official_mismatches,
                     "matching_signals": len(signals), "warning_count": len(quality["warnings"]),
                     "result_status": ("partial_or_failed" if quality["errors"] else
                                       "complete_with_data_warnings" if quality["warnings"] or official_mismatches else "complete")})
    manifest['strict_freshness'] = strict_freshness
    manifest['snapshot_policy'] = ('local_only' if snapshot_output else 'replay' if replay_dir else 'no_raw_export')
    verify_scan_artifacts(manifest, quality, results, signals)
    save(out / "manifest.json", manifest)
    save(out / "data_quality.json", quality)
    save(out / "screening_results.json", results)
    save(out / "signals.json", signals)
    if include_snapshot and snapshots:
        pd.concat(snapshots, ignore_index=True).to_csv(out / "market_data.csv", index=False)
    summary = ["# Daily market scan (research only)", "",
               "Sources: TW=TWSE official unadjusted; US=Yahoo adjusted OHLC (volume unchanged)",
               f"Symbols: {manifest['scanned_symbols']} | Errors: {manifest['error_count']}",
               f"Matches: {len(signals)}", "", "## Matches"]
    summary.extend(f"- {r['symbol']}: {r['strategy_id']} {r['metrics']}" for r in signals)
    for m, days in manifest.get("unscheduled_closures", {}).items():
        summary.append(f"Unscheduled exchange closures ({m}, official market record): {', '.join(days)}")
    if quality["warnings"]:
        summary.append("## Data warnings")
        summary.extend(f"- {w['symbol']} {w['reason']} on {w['excluded_date']}" for w in quality["warnings"])
    if quality["errors"]:
        summary.append("## Failures")
        summary.extend(f"- {e['symbol']}: {e['reason']}" for e in quality["errors"])
    summary.append("No matches is a valid outcome; this is not trading advice.")
    (out / "summary.md").write_text("\n".join(summary) + "\n")
    return manifest
