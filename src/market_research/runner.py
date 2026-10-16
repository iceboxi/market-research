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

from .provider import YahooDailyProvider
from .strategies import get_strategy
from .validation import validate_daily
from .twse import twse_close_check


def save(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def run_scan(market="both", period="1y", out=Path("output"), config_dir=Path("config"),
             provider=None, include_snapshot=False, check_twse=False, now=None, verifier=None):
    markets = yaml.safe_load((config_dir / "markets.yaml").read_text())["markets"]
    strategies = [s for s in yaml.safe_load((config_dir / "strategies.yaml").read_text())["strategies"] if s["enabled"]]
    selected = list(markets) if market == "both" else [market]
    if any(m not in markets for m in selected) or not strategies:
        raise ValueError("Unknown market or no strategies")
    provider = provider or YahooDailyProvider()
    now = now or datetime.now(timezone.utc)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": 1, "generated_at_utc": now.astimezone(timezone.utc).isoformat(),
                "git_sha": os.getenv("GITHUB_SHA"), "github_run_id": os.getenv("GITHUB_RUN_ID"),
                "market": selected, "period": period, "interval": "1d", "data_source": provider.source,
                "strategies": [{"id": s["id"], "version": get_strategy(s["id"]).version,
                                 "params": s.get("params", {})} for s in strategies],
                "snapshot_included": include_snapshot}
    quality = {"symbols": [], "errors": [], "warnings": []}
    results, snapshots = [], []
    for m in selected:
        today = now.astimezone(ZoneInfo(markets[m]["timezone"])).date()
        for symbol in markets[m]["symbols"]:
            try:
                df = provider.load(symbol, period)
                # Never screen an intraday US candle as if it were finalized.
                market_time = now.astimezone(ZoneInfo(markets[m]["timezone"]))
                if m == "us" and market_time.time() < time(16, 30) and df.index[-1] == today:
                    quality["warnings"].append({"market": m, "symbol": symbol,
                        "excluded_date": str(df.index[-1]),
                        "reason": "in_progress_us_session_bar_excluded"})
                    df = df.iloc[:-1]
                # A provider may create a placeholder with missing OHLC for the
                # newest session. Record it explicitly; never forward-fill prices.
                if len(df) and df[["open", "high", "low", "close"]].iloc[-1].isna().any():
                    quality["warnings"].append({"market": m, "symbol": symbol,
                        "excluded_date": str(df.index[-1]),
                        "reason": "incomplete_trailing_ohlc_excluded"})
                    df = df.iloc[:-1]
                checked = validate_daily(df, symbol, market_today=today)
                checked.update({"market": m, "as_of_market_date": str(today),
                    "freshness": "current_calendar_date" if str(df.index[-1]) == str(today) else "check_exchange_holiday_or_feed_delay",
                    "input_sha256": sha256(df.to_csv().encode()).hexdigest()})
                if check_twse and m == "tw":
                    checked["twse_spot_check"] = (verifier or twse_close_check)(
                        symbol, df.index[-1], float(df["close"].iloc[-1]), float(df["volume"].iloc[-1]))
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
    signals = [r for r in results if r["matched"]]
    manifest.update({"scanned_symbols": len(quality["symbols"]), "error_count": len(quality["errors"]),
                     "matching_signals": len(signals), "warning_count": len(quality["warnings"]),
                     "result_status": "complete" if not quality["errors"] else "partial_or_failed"})
    save(out / "manifest.json", manifest)
    save(out / "data_quality.json", quality)
    save(out / "screening_results.json", results)
    save(out / "signals.json", signals)
    if include_snapshot and snapshots:
        pd.concat(snapshots, ignore_index=True).to_csv(out / "market_data.csv", index=False)
    summary = ["# Daily market scan (research only)", "", f"Source: {provider.source}",
               f"Symbols: {manifest['scanned_symbols']} | Errors: {manifest['error_count']}",
               f"Matches: {len(signals)}", "", "## Matches"]
    summary.extend(f"- {r['symbol']}: {r['strategy_id']} {r['metrics']}" for r in signals)
    if quality["errors"]:
        summary.append("## Failures")
        summary.extend(f"- {e['symbol']}: {e['reason']}" for e in quality["errors"])
    summary.append("No matches is a valid outcome; this is not trading advice.")
    (out / "summary.md").write_text("\n".join(summary) + "\n")
    return manifest
