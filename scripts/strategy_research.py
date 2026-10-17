"""Shared, opt-in, strategy-independent EOD research runner.

An eligible implemented strategy can be selected without editing production
config or adding a new workflow. Inputs are obtained exactly once per ticker
and shared across a backtest (bullish only) and a replayed final-session scan.
Raw price snapshots are temporary and never uploaded as public artifacts.
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

CATALOG = Path(__file__).resolve().parents[1] / "docs/strategies/catalog.yaml"
RESEARCHABLE = {"implemented", "validated_for_research"}
STRATEGY_DIRECTIONS = {"bullish", "bearish", "exhaustion_observation"}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def select_variant(strategy_id, catalog_path=CATALOG):
    catalog = yaml.safe_load(Path(catalog_path).read_text(encoding="utf-8"))
    entries = [v for v in catalog["variants"] if v["id"] == strategy_id]
    if len(entries) != 1:
        raise ValueError(f"Strategy must appear exactly once in catalog: {strategy_id}")
    variant = entries[0]
    if variant["status"] not in RESEARCHABLE:
        raise ValueError(f"Strategy {strategy_id} is not implemented: {variant['status']}")
    if variant["direction"] not in STRATEGY_DIRECTIONS:
        raise ValueError(f"Unknown strategy direction: {variant['direction']}")
    implementation = get_strategy(strategy_id)
    if implementation.version != str(variant["version"]):
        raise ValueError(f"Catalog/runtime version mismatch: {strategy_id}")
    return variant


def research_config(source, target, strategy_id):
    """Create an isolated config for one previously disabled, implemented strategy."""
    variant = select_variant(strategy_id)
    source, target = Path(source), Path(target)
    production = yaml.safe_load((source / "strategies.yaml").read_text(encoding="utf-8"))["strategies"]
    matches = [s for s in production if s["id"] == strategy_id]
    if len(matches) != 1:
        raise ValueError(f"Strategy {strategy_id} must have one explicit config entry")
    if matches[0]["enabled"] is not False:
        raise ValueError(f"Refusing research mode: {strategy_id} is enabled in production")
    selected = {"id": strategy_id, "enabled": True, "params": matches[0].get("params", {})}
    target.mkdir(parents=True, exist_ok=True)
    for filename in ("markets.yaml", "backtest.yaml"):
        shutil.copyfile(source / filename, target / filename)
    (target / "strategies.yaml").write_text(
        yaml.safe_dump({"strategies": [selected]}, sort_keys=False), encoding="utf-8"
    )
    return selected


def verify(backtest, scan, inputs, quality, signals, selected, market, strategy_id):
    """Fail closed on missing stocks, unexpected strategies or source-hash drift."""
    strategy = get_strategy(strategy_id)
    expected = {"id": strategy_id, "version": strategy.version, "params": selected["params"]}
    if scan["strategies"] != [expected]:
        raise ValueError("Scan strategy/version/parameters differ from selected strategy")
    if backtest is not None and backtest["strategies"] != [expected]:
        raise ValueError("Backtest strategy/version/parameters differ from selected strategy")
    if backtest is not None and scan["strict_freshness"] != backtest["strict_freshness"]:
        raise ValueError("Session-completeness policies differ")
    if scan["requested_symbols"] != scan["scanned_symbols"] or scan["error_count"]:
        raise ValueError("Scan had missing or failed tickers")
    if backtest is not None and (
        backtest["requested"] != backtest["scanned"] or backtest["error_count"]
    ):
        raise ValueError("Backtest had missing or failed tickers")
    if len(signals) != scan["matching_signals"]:
        raise ValueError("Final-session signal count mismatch")
    s_rows = quality["symbols"]
    if len(s_rows) != scan["requested_symbols"] or len(inputs) != len(s_rows):
        raise ValueError("Incomplete per-ticker input provenance")
    def identity(rows):
        keys = [(r["market"], r["symbol"]) for r in rows]
        if len(set(keys)) != len(keys) or any(r["market"] != market for r in rows):
            raise ValueError("Duplicate or cross-market input records")
        return {(r["market"], r["symbol"]): (r["input_sha256"], r["last_date"]) for r in rows}
    if identity(inputs) != identity(s_rows):
        raise ValueError("Backtest and scan inputs have different OHLCV hashes/dates")
    if any(r["strategy_id"] != strategy_id or
           r["strategy_version"] != strategy.version for r in signals):
        raise ValueError("Unexpected signal strategy/version")
    return True


def historical_observations(provider, market, symbols, strategy_id, params, minimum_bars=1):
    """Each prefix is an as-of-date observation; never a simulated trade."""
    if minimum_bars < 1:
        raise ValueError("minimum_bars must be positive")
    strategy = get_strategy(strategy_id)
    results = []
    for symbol in symbols:
        bars = provider.load(symbol)
        for end in range(minimum_bars, len(bars) + 1):
            observation = strategy.scan(market, symbol, bars.iloc[:end], params)
            if observation.matched:
                results.append({
                    "market": market, "symbol": symbol,
                    "strategy_id": observation.strategy_id,
                    "strategy_version": observation.strategy_version,
                    "confirmation_date": observation.trade_date,
                    "observation": "confirmed_daily_pattern",
                })
    return results


def run_study(strategy_id, market, period="1y", out=Path("research_output"),
              config_dir=Path("config"), provider=None, now=None,
              strict_freshness=True):
    if market not in ("tw", "us"):
        raise ValueError("Choose one market: tw or us")
    variant = select_variant(strategy_id)
    bullish = variant["direction"] == "bullish"
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="strategy-research-") as temp:
        root = Path(temp)
        selected = research_config(config_dir, root / "config", strategy_id)
        snapshot_dir = root / "snapshots"
        backtest = None
        if bullish:
            backtest = run_backtest(
                market, period, out / "backtest", config_dir=root / "config",
                provider=provider, now=now, snapshot_output=snapshot_dir,
                strict_freshness=strict_freshness
            )
            if backtest["error_count"]:
                raise RuntimeError("Backtest failed; inspect backtest/data_quality.json")
            scan = run_scan(
                market, period, out / "scan", config_dir=root / "config",
                replay_dir=snapshot_dir, now=now, strict_freshness=strict_freshness
            )
            inputs = read_json(out / "backtest/inputs.json")
        else:
            # Backtest is currently long-only; bearish or exhaustion patterns
            # MUST NEVER be silently interpreted as long entry signals.
            scan = run_scan(
                market, period, out / "scan", config_dir=root / "config",
                provider=provider, now=now, snapshot_output=snapshot_dir,
                strict_freshness=strict_freshness
            )
            inputs = read_json(out / "scan/data_quality.json")["symbols"]
        quality = read_json(out / "scan/data_quality.json")
        signals = read_json(out / "scan/signals.json")
        verify(backtest, scan, inputs, quality, signals, selected, market, strategy_id)
        universe = yaml.safe_load(
            (root / "config/markets.yaml").read_text(encoding="utf-8")
        )["markets"]
        symbols = universe[market]["symbols"]
        observations = historical_observations(
            ReplayProvider(snapshot_dir), market, symbols, strategy_id,
            selected["params"], variant.get("min_completed_bars", 1)
        )
        observed = {(r["symbol"], r["confirmation_date"]) for r in observations}
        if any((r["symbol"], r["trade_date"]) not in observed for r in signals):
            raise ValueError("Latest-session signals missing from historical observations")
        counts = Counter(r["symbol"] for r in observations)
        output = {
            "schema_version": 1, "study": "isolated_strategy_research",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "market": market, "period": period,
            "strategy_id": strategy_id, "strategy_version": get_strategy(strategy_id).version,
            "strategy_direction": variant["direction"], "parameters": selected["params"],
            "completed_session_validation": strict_freshness,
            "symbols_requested": scan["requested_symbols"],
            "symbols_scanned": scan["scanned_symbols"], "error_count": scan["error_count"],
            "data_contract_verified": True, "same_snapshot_hashes_verified": True,
            "final_session_signals": len(signals),
            "all_historical_observations": len(observations),
            "observations_per_symbol": {symbol: counts[symbol] for symbol in symbols},
            "backtest_status": "exploratory_long_only" if bullish else "skipped_unsupported_direction",
            "closed_simulated_trades": backtest["trade_count"] if backtest else None,
            "warning_count": max(scan["warning_count"],
                                 backtest["warning_count"] if backtest else 0),
            "data_sources": sorted({row["source"] for row in inputs}),
            "cautions": [
                "Curated pilot universe, not the full exchange.",
                "Historical observations are in-sample, not evidence of predictive value.",
                "A pattern observation is not a trading instruction.",
                "Long-only five-session backtest uses illustrative price-only fill proxies.",
                "Bearish/exhaustion patterns are observation-only, never automatically longed.",
                "Cash dividends and corporate actions are not fully modeled.",
                "Licensed price snapshots are ephemeral and never redistributed in Artifacts.",
            ],
        }
        (out / "historical_observations.json").write_text(
            json.dumps(observations, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        (out / "study.json").write_text(
            json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        lines = [
            f"# {strategy_id} {output['strategy_version']} — {market.upper()} isolated research",
            "",
            "Research only. Strategy remains disabled in production.",
            "",
            f"- Input period: {period}; valid tickers: {output['symbols_scanned']}/{output['symbols_requested']}",
            f"- Latest-session matches: {output['final_session_signals']}",
            f"- All historical pattern observations: {len(observations)}",
            f"- Backtest status: {output['backtest_status']}",
            f"- Closed long-only simulated trades: {output['closed_simulated_trades']}",
            f"- Input hash parity: {output['same_snapshot_hashes_verified']}",
            f"- Warnings: {output['warning_count']}; errors: {output['error_count']}",
            "",
            "| Symbol | Historical observations |",
            "| --- | ---: |",
        ]
        lines.extend(f"| {symbol} | {counts[symbol]} |" for symbol in symbols)
        lines += ["", "Observations are not trades and do not establish profitability."]
        (out / "study.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return output


def main():
    p = argparse.ArgumentParser(description="Research one disabled, implemented strategy")
    p.add_argument("--strategy", required=True, help="Implemented catalog ID, disabled in production")
    p.add_argument("--market", required=True, choices=["tw", "us"])
    p.add_argument("--period", default="1y", choices=["6mo", "1y", "2y"])
    p.add_argument("--out", type=Path, default=Path("research_output"))
    args = p.parse_args()
    result = run_study(args.strategy, args.market, args.period, args.out)
    print((args.out / "study.md").read_text(encoding="utf-8"))
    if result["error_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
