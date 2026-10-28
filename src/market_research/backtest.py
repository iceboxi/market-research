"""Exploratory long-only, single-symbol Sakata research. No trading orders."""
import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, time, timezone
from hashlib import sha256
from pathlib import Path
from random import Random
from statistics import median
from zoneinfo import ZoneInfo
import json
import os

import numpy as np
import pandas as pd
import yaml

from .provider import RoutedDailyProvider
from .strategies import get_strategy
from .market_data import load_daily_bars
from .snapshots import ReplayProvider, write_snapshot, write_index


@dataclass(frozen=True)
class Settings:
    warmup_bars: int = 30
    hold_bars: int = 5
    commission_bps: float = 10
    slippage_bps: float = 5
    tw_sell_tax_bps: float = 30
    us_sell_tax_bps: float = 0
    seed: int = 42
    trials: int = 100

    def validate(self):
        if self.warmup_bars < 8 or self.hold_bars < 1 or self.trials < 1:
            raise ValueError("Invalid warmup, holding period or random trials")
        if min(self.commission_bps, self.slippage_bps,
               self.tw_sell_tax_bps, self.us_sell_tax_bps) < 0:
            raise ValueError("Negative trading costs")
        if (self.commission_bps + self.slippage_bps +
                max(self.tw_sell_tax_bps, self.us_sell_tax_bps)) >= 10000:
            raise ValueError("Trading cost too large")


def costs(market, cfg):
    entry = (cfg.commission_bps + cfg.slippage_bps) / 10000
    tax = cfg.tw_sell_tax_bps if market == "tw" else cfg.us_sell_tax_bps
    return entry, entry + tax / 10000


def equity_curve(opens, entries, first, hold, buy_cost, sell_cost):
    """Cash or 100%-notional position, valued at each daily opening price."""
    entry_events = set(entries)
    exit_events = {index + hold for index in entries}
    equity, invested = 1., False
    values = [equity]
    for index in range(first, len(opens)):
        if index > first and invested:
            equity *= float(opens[index] / opens[index - 1])
        if index in exit_events:
            equity *= (1 - sell_cost)
            invested = False
        if index in entry_events:
            equity /= (1 + buy_cost)
            invested = True
        values.append(equity)
    if invested:
        raise ValueError("Unclosed position")
    return values


def drawdown(equity):
    peak, worst = 1., 0.
    for value in equity:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1.)
    return 100 * worst


def random_entries(first, last, count, hold, rng):
    candidates = list(range(first, last + 1))
    rng.shuffle(candidates)
    chosen = []
    for index in candidates:
        if all(abs(index - earlier) >= hold for earlier in chosen):
            chosen.append(index)
            if len(chosen) == count:
                break
    if len(chosen) != count:
        raise ValueError("Cannot generate same-count random entries")
    return sorted(chosen)


def backtest_symbol(df, market, symbol, strategy, params, cfg):
    cfg.validate()
    n = len(df)
    first = cfg.warmup_bars
    last_entry = n - cfg.hold_bars - 1
    if last_entry < first:
        raise ValueError(f"{symbol}: insufficient complete bars for backtest")
    # Signal predicates consume analysis OHLC; filled prices are a separate
    # price-only quote-open proxy. Avoid using dividend-adjusted opens for fills.
    opens = df["execution_open"].to_numpy(dtype=float) if "execution_open" in df else df["open"].to_numpy(dtype=float)
    if not np.isfinite(opens).all() or (opens <= 0).any():
        raise ValueError(f"{symbol}: invalid opening prices")
    entries, signal_indices = [], []
    skipped = 0
    # On signal session j only data[:j+1] are available.
    for j in range(first - 1, last_entry):
        signal = strategy.scan(market, symbol, df.iloc[:j + 1], params)
        if not signal.matched:
            continue
        entry = j + 1       # Entry at the NEXT trading session's OPEN.
        if entries and entry < entries[-1] + cfg.hold_bars:
            skipped += 1
            continue
        entries.append(entry)
        signal_indices.append(j)
    buy, sell = costs(market, cfg)
    trades = []
    for j, entry in zip(signal_indices, entries):
        exit_i = entry + cfg.hold_bars
        price_ratio = float(opens[exit_i] / opens[entry])
        trades.append({
            "market": market, "symbol": symbol,
            "strategy_id": strategy.id, "strategy_version": strategy.version,
            "signal_date": str(df.index[j]),
            "entry_date": str(df.index[entry]), "exit_date": str(df.index[exit_i]),
            "entry_open": float(opens[entry]), "exit_open": float(opens[exit_i]),
            "gross_return_pct": (price_ratio - 1) * 100,
            "net_return_pct": (price_ratio * (1 - sell) / (1 + buy) - 1) * 100,
        })
    equity = equity_curve(opens, entries, first, cfg.hold_bars, buy, sell)
    buy_hold_equity = [1.] + [
        float(opens[i] / opens[first] / (1 + buy) *
              ((1 - sell) if i == n - 1 else 1.))
        for i in range(first, n)
    ]
    trial_returns = []
    if entries:
        salt = sha256(f"{cfg.seed}:{market}:{symbol}:{strategy.id}".encode()).digest()
        rng = Random(int.from_bytes(salt[:8], "big"))
        for _ in range(cfg.trials):
            sampled = random_entries(first, last_entry, len(entries), cfg.hold_bars, rng)
            outcome = equity_curve(opens, sampled, first, cfg.hold_bars, buy, sell)
            trial_returns.append((outcome[-1] - 1) * 100)
    summary = {
        "market": market, "symbol": symbol, "strategy_id": strategy.id,
        "strategy_version": strategy.version,
        "start_date": str(df.index[first]), "last_date": str(df.index[-1]),
        "bars": n, "closed_trades": len(trades),
        "skipped_overlapping_signals": skipped,
        "return_convention": "price_only_excludes_dividend_cashflows",
        "execution_open_field": "execution_open" if "execution_open" in df else "open_fixture_fallback",
        "strategy_net_return_pct": (equity[-1] - 1) * 100,
        "strategy_max_drawdown_pct": drawdown(equity),
        "win_rate_pct": (
            100 * sum(t["net_return_pct"] > 0 for t in trades) / len(trades)
            if trades else None
        ),
        "buy_hold_net_return_pct": (buy_hold_equity[-1] - 1) * 100,
        "buy_hold_max_drawdown_pct": drawdown(buy_hold_equity),
        "random_median_net_return_pct": median(trial_returns) if trial_returns else None,
        "random_trials": len(trial_returns),
    }
    return summary, trades


def run_backtest(market="both", period="1y", out=Path("backtest_output"),
                 config_dir=Path("config"), provider=None, now=None,
                 replay_dir=None, snapshot_output=None, strict_freshness=False,
                 strategy_ids=None):
    markets = yaml.safe_load((config_dir / "markets.yaml").read_text())["markets"]
    configured = yaml.safe_load((config_dir / "strategies.yaml").read_text())["strategies"]
    if strategy_ids:
        # Research runs name their strategy; production enablement is separate (#117).
        unknown = set(strategy_ids) - {s["id"] for s in configured}
        if unknown:
            raise ValueError(f"Unknown strategy: {sorted(unknown)}")
        strategies = [s for s in configured if s["id"] in strategy_ids]
    else:
        strategies = [s for s in configured if s["enabled"]]
    if not strategies:
        raise ValueError("No enabled strategies")
    selection = list(markets) if market == "both" else [market]
    if any(m not in markets for m in selection):
        raise ValueError(f"Unknown market: {market}")
    cfg = Settings(**yaml.safe_load((config_dir / "backtest.yaml").read_text())["backtest"])
    cfg.validate()
    now = now or datetime.now(timezone.utc)
    if provider is not None and replay_dir is not None:
        raise ValueError("Provide either a provider or replay_dir")
    provider = ReplayProvider(replay_dir) if replay_dir else (provider or RoutedDailyProvider())
    out.mkdir(parents=True, exist_ok=True)
    results, trades, inputs, errors, warnings, snapshot_records = [], [], [], [], [], []
    for m in selection:
        local = now.astimezone(ZoneInfo(markets[m]["timezone"]))
        for symbol in markets[m]["symbols"]:
            try:
                daily = load_daily_bars(provider, m, symbol, period, now,
                                        markets[m]["timezone"], strict_freshness)
                df = daily.frame
                warnings.extend(daily.warnings)
                inputs.append(daily.metadata)
                if snapshot_output:
                    snapshot_records.append(write_snapshot(
                        Path(snapshot_output), symbol, df, daily.metadata["source"]
                    ))
                for sc in strategies:
                    result, history = backtest_symbol(
                        df, m, symbol, get_strategy(sc["id"]),
                        sc.get("params", {}), cfg
                    )
                    results.append(result)
                    trades.extend(history)
            except Exception as exc:
                errors.append({"market": m, "symbol": symbol,
                               "error": f"{type(exc).__name__}: {exc}"})
    if snapshot_output:
        write_index(Path(snapshot_output), snapshot_records)
    manifest = {
        "schema_version": 1, "study": "in_sample_exploratory",
        "generated_at_utc": now.astimezone(timezone.utc).isoformat(),
        "github_sha": os.getenv("GITHUB_SHA"), "github_run_id": os.getenv("GITHUB_RUN_ID"),
        "period": period,
        "data_contract_version": 1,
        "strict_freshness": strict_freshness,
        "snapshot_policy": "local_only" if snapshot_output else "replay" if replay_dir else "no_raw_export",
        "requested": sum(len(markets[m]["symbols"]) for m in selection),
        "scanned": len(inputs), "error_count": len(errors),
        "warning_count": len(warnings), "trade_count": len(trades),
        "settings": asdict(cfg),
        "strategies": [{"id": s["id"], "version": get_strategy(s["id"]).version,
                        "params": s.get("params", {})} for s in strategies],
        "limitations": [
            "Not an executable trading strategy or out-of-sample validation.",
            "TWSE prices unadjusted for splits/dividends; can distort results.",
            "US screening uses dividend-adjusted OHLC; backtest fills use Yahoo quote Open (possibly split adjusted).",
            "Performance is price-only: cash dividends and other corporate actions are not credited.",
            "No portfolio allocation, FX, market impact, or capital constraints.",
            "Random benchmark matches the number of non-overlapping trades.",
            "No raw historical OHLC data is redistributed by this public repository.",
        ],
    }
    for name, payload in [
        ("manifest.json", manifest), ("inputs.json", inputs),
        ("results.json", results), ("trades.json", trades),
        ("data_quality.json", {"errors": errors, "warnings": warnings}),
    ]:
        (out / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False,
                                           allow_nan=False) + "\n", encoding="utf-8")
    lines = [
        "# Exploratory backtest (not investment advice)", "",
        f"Scanned {len(inputs)}/{manifest['requested']}, errors {len(errors)}, "
        f"warnings {len(warnings)}, closed trades {len(trades)}", "",
        "| Symbol | Trades | Strategy net % | Buy/hold net % | Random median % | Max DD % |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in results:
        rnd = r["random_median_net_return_pct"]
        lines.append(
            f"| {r['symbol']} | {r['closed_trades']} | "
            f"{r['strategy_net_return_pct']:.2f} | "
            f"{r['buy_hold_net_return_pct']:.2f} | "
            f"{rnd:.2f}" if rnd is not None else
            f"| {r['symbol']} | {r['closed_trades']} | "
            f"{r['strategy_net_return_pct']:.2f} | "
            f"{r['buy_hold_net_return_pct']:.2f} | n/a"
        )
        lines[-1] += f" | {r['strategy_max_drawdown_pct']:.2f} |"
    lines.extend(["", "No trades means no evidence, not validated 0% expected return.",
                  "Buy-and-hold is continuously invested; strategy is in cash between signals.",
                  "Results are per ticker, not an investable portfolio."])
    if errors:
        lines.append("## Failed symbols")
        lines.extend(f"- {e['symbol']}: {e['error']}" for e in errors)
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", choices=["tw", "us", "both"], default="both")
    parser.add_argument("--period", choices=["3mo", "6mo", "1y", "2y"], default="1y")
    parser.add_argument("--out", type=Path, default=Path("backtest_output"))
    parser.add_argument("--replay-dir", type=Path)
    parser.add_argument("--snapshot-output", type=Path)
    parser.add_argument("--strict-freshness", action="store_true")
    parser.add_argument("--strategy", action="append", dest="strategies",
                        help="Backtest this configured strategy even if disabled in production")
    args = parser.parse_args()
    outcome = run_backtest(args.market, args.period, args.out,
                           replay_dir=args.replay_dir, snapshot_output=args.snapshot_output,
                           strict_freshness=args.strict_freshness, strategy_ids=args.strategies)
    print(json.dumps({"scanned": outcome["scanned"],
                      "errors": outcome["error_count"],
                      "trades": outcome["trade_count"]}))
    if outcome["error_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
