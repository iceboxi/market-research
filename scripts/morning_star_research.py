"""Isolated live Morning Star study; NEVER enables production signals.

Capture a single authorized temporary OHLCV snapshot per market, run the
exploratory backtest, replay identical data for the last-session scan, and
enumerate all historical pattern observations without imposing a trade hold.
Raw CSV snapshots are deleted when the process exits and never go in Artifacts.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile

import yaml

from market_research.backtest import run_backtest
from market_research.runner import run_scan
from market_research.snapshots import ReplayProvider
from market_research.strategies import get_strategy

STRATEGY_ID = "sakata_morning_star"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def research_config(source, target):
    """Create private research-only config; production strategies.yaml stays untouched."""
    source, target = Path(source), Path(target)
    production = yaml.safe_load((source / "strategies.yaml").read_text())["strategies"]
    original = [x for x in production if x["id"] == STRATEGY_ID]
    if len(original) != 1:
        raise ValueError("Morning Star must have exactly one production config entry")
    if original[0]["enabled"]:
        raise ValueError("Refusing research mode: Morning Star is enabled in production")
    selected = {"id": STRATEGY_ID, "enabled": True, "params": original[0]["params"]}
    target.mkdir(parents=True, exist_ok=True)
    for file in ("markets.yaml", "backtest.yaml"):
        shutil.copyfile(source / file, target / file)
    (target / "strategies.yaml").write_text(
        yaml.safe_dump({"strategies": [selected]}, sort_keys=False),
        encoding="utf-8"
    )
    return selected


def verify(backtest, scan, inputs, quality, signals, selected, market):
    """Stop the study if only a subset of symbols was checked or prices diverged."""
    expected = [STRATEGY_ID]
    if [s["id"] for s in backtest["strategies"]] != expected:
        raise ValueError("Backtest used an unexpected strategy")
    if [s["id"] for s in scan["strategies"]] != expected:
        raise ValueError("Scan used an unexpected strategy")
    if backtest["strategies"][0]["params"] != selected["params"]:
        raise ValueError("Research params differ from catalog selection")
    if scan["strict_freshness"] != backtest["strict_freshness"]:
        raise ValueError("Session-completeness policy diverged")
    if backtest["requested"] != backtest["scanned"] or backtest["error_count"]:
        raise ValueError("Backtest had missing or failed tickers")
    if scan["requested_symbols"] != scan["scanned_symbols"] or scan["error_count"]:
        raise ValueError("Scan had missing or failed tickers")
    if len(inputs) != scan["scanned_symbols"] or len(quality["symbols"]) != len(inputs):
        raise ValueError("Source provenance missing")
    if len(signals) != scan["matching_signals"]:
        raise ValueError("Final-session signal count mismatch")
    b_hashes = {(row["market"], row["symbol"]): row["input_sha256"] for row in inputs}
    s_hashes = {(row["market"], row["symbol"]): row["input_sha256"] for row in quality["symbols"]}
    if b_hashes != s_hashes:
        raise ValueError("Backtest and scan inputs have different OHLCV hashes")
    if any(row["market"] != market for row in inputs):
        raise ValueError("Unexpected market in research data")
    if any(s["strategy_id"] != STRATEGY_ID or s["strategy_version"] != "0.1.0"
           for s in signals):
        raise ValueError("Unexpected final-session signal version")
    return True


def historical_observations(provider, market, symbols, params, minimum_bars=8):
    """Scan each as-of prefix, never future candles; NOT a trade history."""
    strategy = get_strategy(STRATEGY_ID)
    findings = []
    for symbol in symbols:
        history = provider.load(symbol)
        for end in range(minimum_bars, len(history) + 1):
            result = strategy.scan(market, symbol, history.iloc[:end], params)
            if result.matched:
                findings.append({
                    "market": market, "symbol": symbol,
                    "strategy_id": result.strategy_id,
                    "strategy_version": result.strategy_version,
                    "confirmation_date": result.trade_date,
                    "observation": "confirmed_daily_pattern",
                    # No raw candle prices or adjusted OHLCV are published.
                })
    return findings


def run_study(market, period="1y", out=Path("research_output"),
              config_dir=Path("config"), provider=None, now=None,
              strict_freshness=True):
    if market not in ("tw", "us"):
        raise ValueError("Use a single market: tw or us")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="morning-star-study-") as root:
        workspace = Path(root)
        selected = research_config(config_dir, workspace / "config")
        snapshots = workspace / "snapshots"
        backtest = run_backtest(market, period, out / "backtest",
                                config_dir=workspace / "config", provider=provider,
                                snapshot_output=snapshots, now=now,
                                strict_freshness=strict_freshness)
        if backtest["error_count"]:
            raise RuntimeError("Backtest failed; inspect backtest/data_quality.json")
        scan = run_scan(market, period, out / "scan", config_dir=workspace / "config",
                        replay_dir=snapshots, now=now,
                        strict_freshness=strict_freshness)
        inputs = read_json(out / "backtest" / "inputs.json")
        scan_quality = read_json(out / "scan" / "data_quality.json")
        signals = read_json(out / "scan" / "signals.json")
        verify(backtest, scan, inputs, scan_quality, signals, selected, market)
        universe = yaml.safe_load((workspace / "config" / "markets.yaml").read_text())["markets"]
        symbols = universe[market]["symbols"]
        findings = historical_observations(ReplayProvider(snapshots), market,
                                           symbols, selected["params"])
        final = {(s["symbol"], s["trade_date"]) for s in signals}
        historical = {(s["symbol"], s["confirmation_date"]) for s in findings}
        if not final.issubset(historical):
            raise ValueError("Final-session signals are inconsistent with historical scans")
        counts = Counter(item["symbol"] for item in findings)
        summary = {
            "schema_version": 1, "study": "morning_star_isolated_exploratory",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "market": market, "period": period, "strategy_id": STRATEGY_ID,
            "strategy_version": get_strategy(STRATEGY_ID).version,
            "parameters": selected["params"],
            "completed_session_validation": strict_freshness,
            "symbols_requested": backtest["requested"],
            "symbols_scanned": backtest["scanned"],
            "error_count": backtest["error_count"] + scan["error_count"],
            "data_contract_verified": True,
            "same_snapshot_hashes_verified": True,
            "final_session_signals": len(signals),
            "all_historical_observations": len(findings),
            "observations_per_symbol": {s: counts[s] for s in symbols},
            "closed_simulated_trades": backtest["trade_count"],
            "warning_count": max(backtest["warning_count"], scan["warning_count"]),
            "data_sources": sorted({row["source"] for row in inputs}),
            "cautions": [
                "This is a hand-picked 10 TW / 12 US ticker universe, not full-market coverage.",
                "All historical observations are in-sample; no strategy efficacy conclusion.",
                "A confirmed pattern is not necessarily an executable trade.",
                "Backtest uses illustrative next-open five-session price-only returns.",
                "Cash dividends and all corporate actions are not fully modeled.",
                "Market snapshots were temporary and are not published in Artifacts.",
            ],
        }
        (out / "historical_observations.json").write_text(
            json.dumps(findings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (out / "study.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        lines = [
            f"# Morning Star v0.1.0 — independent {market.upper()} research",
            "",
            "Not investment advice; production Morning Star remains disabled.",
            "",
            f"- Market: {market}; period: {period}",
            f"- Validated tickers: {summary['symbols_scanned']}/{summary['symbols_requested']}",
            f"- Latest-session matches: {summary['final_session_signals']}",
            f"- Confirmed historical patterns: {summary['all_historical_observations']}",
            f"- Closed exploratory trades: {summary['closed_simulated_trades']}",
            f"- Input hash parity: {summary['same_snapshot_hashes_verified']}",
            f"- Warnings: {summary['warning_count']}; errors: {summary['error_count']}",
            "",
            "| Symbol | Confirmed historical patterns |",
            "| --- | ---: |",
        ]
        lines += [f"| {s} | {counts[s]} |" for s in symbols]
        lines += ["", "Pattern frequencies are NOT historical trade counts or evidence of profitability.",
                  "See scan/ and backtest/ for complete research metadata and limitations."]
        (out / "study.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--market", choices=["tw", "us"], required=True)
    p.add_argument("--period", choices=["6mo", "1y", "2y"], default="1y")
    p.add_argument("--out", type=Path, default=Path("research_output"))
    a = p.parse_args()
    result = run_study(a.market, a.period, a.out)
    print((a.out / "study.md").read_text())
    if result["error_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
