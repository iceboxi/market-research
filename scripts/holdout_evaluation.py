"""Fixed historical chronological holdout diagnostics, not prospective validation.

NO fitting / threshold search; evaluate frozen strategy versions only. For each
ticker, the first 70% of complete sessions precedes an explicit 5-bar embargo.
Only subsequent dates can supply held-out observations. The 5-day forward
analytical-close change is a descriptive label, NEVER a broker fill or P&L.
No raw price histories are written into public Artifacts.
"""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from market_research.market_data import load_daily_bars
from market_research.provider import RoutedDailyProvider
from market_research.strategies import get_strategy
from scripts.strategy_research import select_variant

DIRECTION = {"bullish": 1, "bearish": -1, "exhaustion_observation": None}
MIN_EVENTS_TO_INTERPRET = 20


def fixed_holdout(frame, strategy, market, symbol, direction,
                  params, train_fraction=0.70, horizon=5, embargo=5,
                  min_train=60, min_test=20):
    """Consume strictly as-of prefixes for signals; forward labels never feed scan."""
    if not 0.5 <= train_fraction <= 0.9:
        raise ValueError("train_fraction must be 0.5 .. 0.9")
    if type(horizon) is not int or horizon < 1:
        raise ValueError("horizon must be positive integer")
    if type(embargo) is not int or embargo < horizon:
        raise ValueError("embargo must be at least the outcome horizon")
    if direction not in DIRECTION:
        raise ValueError("unknown direction")
    if len(frame) < min_train + embargo + horizon + min_test:
        raise ValueError(f"{symbol}: insufficient sessions for held-out evaluation")
    if not frame.index.is_unique or not frame.index.is_monotonic_increasing:
        raise ValueError(f"{symbol}: unordered or duplicate dates")
    split = int(len(frame) * train_fraction)
    first_test = split + embargo
    if split < min_train or len(frame) - first_test - horizon < min_test:
        raise ValueError(f"{symbol}: split does not leave enough training/test sessions")
    prices = pd.to_numeric(frame["close"], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(prices).all() or (prices <= 0).any():
        raise ValueError(f"{symbol}: invalid adjusted analytical closes")
    good_until = len(frame) - horizon
    baseline = [
        float(100 * (prices[t + horizon] / prices[t] - 1))
        for t in range(first_test, good_until)
    ]
    if not baseline:
        raise ValueError("no fully observable test labels")
    sign = DIRECTION[direction]
    accepted = []
    raw_signals = 0
    censored = 0
    overlap_dropped = 0
    abstentions = 0
    last_accepted = -horizon
    for t in range(first_test, len(frame)):
        # The strategy is NEVER supplied candles after session t.
        result = strategy.scan(market, symbol, frame.iloc[:t + 1], params)
        if result.strategy_id != strategy.id or result.strategy_version != strategy.version:
            raise ValueError("unexpected strategy identity/version in research signal")
        if result.trade_date != str(frame.index[t]):
            raise ValueError("strategy signal date differs from current as-of date")
        if result.metrics.get("observation") == "corporate_actions_unverified":
            abstentions += 1
        if not result.matched:
            continue
        raw_signals += 1
        if t + horizon >= len(frame):
            censored += 1
            continue
        if t - last_accepted < horizon:
            overlap_dropped += 1
            continue
        raw_change = float(100 * (prices[t + horizon] / prices[t] - 1))
        accepted.append({
            "signal_date": str(frame.index[t]),
            "label_end_date": str(frame.index[t + horizon]),
            "forward_analytical_close_change_pct": round(raw_change, 6),
            "directional_diagnostic_pct": (
                round(raw_change * sign, 6) if sign is not None else None
            ),
        })
        last_accepted = t
    count = len(accepted)
    # Never print a headline "average return" for a tiny hand-picked sample.
    adequate = count >= MIN_EVENTS_TO_INTERPRET and sign is not None
    diagnostic = (
        sum(x["directional_diagnostic_pct"] for x in accepted) / count
        if adequate else None
    )
    return {
        "symbol": symbol,
        "sessions": len(frame),
        "training_end": str(frame.index[split - 1]),
        "first_test_date": str(frame.index[first_test]),
        "test_end_date": str(frame.index[-1]),
        "horizon_sessions": horizon,
        "embargo_sessions": embargo,
        "baseline_eligible_dates": len(baseline),
        "baseline_mean_directional_pct": (
            round(sum(baseline) * sign / len(baseline), 6)
            if sign is not None else None
        ),
        "raw_holdout_signals": raw_signals,
        "nonoverlapping_labeled_events": count,
        "censored_no_future_label": censored,
        "overlap_dropped": overlap_dropped,
        "corporate_action_abstentions": abstentions,
        "event_mean_directional_pct": round(diagnostic, 6) if adequate else None,
        "evidence_status": (
            "abstained_unverified_corporate_actions"
            if abstentions == len(frame) - first_test else
            "no_signals" if raw_signals == 0 else
            "insufficient_independent_events" if not adequate else
            "descriptive_only_no_inference"
        ),
        "events": accepted,
    }


def evaluate_market(market, strategy_ids, period="1y", out=Path("holdout_output"),
                    config_dir=Path("config"), provider=None, now=None,
                    strict_freshness=True):
    if market not in ("tw", "us"):
        raise ValueError("Choose one market")
    if not strategy_ids or len(set(strategy_ids)) != len(strategy_ids):
        raise ValueError("Nonempty unique strategy ID list required")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    configs = yaml.safe_load((Path(config_dir) / "strategies.yaml").read_text())["strategies"]
    configurations = {s["id"]: s for s in configs}
    if len(configurations) != len(configs):
        raise ValueError("Duplicate configured strategies")
    active = [s["id"] for s in configs if s["enabled"]]
    variants = {}
    for name in strategy_ids:
        variant = select_variant(name)
        if name not in configurations or configurations[name]["enabled"] is not False:
            raise ValueError(f"{name} must be explicitly disabled in production")
        variants[name] = (variant, get_strategy(name), configurations[name].get("params", {}))
    markets = yaml.safe_load((Path(config_dir) / "markets.yaml").read_text())["markets"]
    universe = markets[market]["symbols"]
    now = now or datetime.now(timezone.utc)
    provider = provider or RoutedDailyProvider()
    records, errors = [], []
    for symbol in universe:
        try:
            daily = load_daily_bars(provider, market, symbol, period, now,
                                    markets[market]["timezone"], strict_freshness)
            for name, (variant, strategy, params) in variants.items():
                observation = fixed_holdout(daily.frame, strategy, market, symbol,
                                             variant["direction"], params)
                # Hash the exact normalized price series evaluated, not source bytes.
                records.append({
                    "strategy_id": name, "strategy_version": strategy.version,
                    "direction": variant["direction"],
                    "market": market, "price_basis": daily.metadata["price_basis"],
                    "source": daily.metadata["source"],
                    "input_sha256": daily.metadata["input_sha256"],
                    "config_sha256": sha256(json.dumps(params, sort_keys=True).encode()).hexdigest(),
                    **observation,
                })
        except Exception as exc:
            errors.append({"symbol": symbol, "type": type(exc).__name__, "reason": str(exc)})
    # NEVER describe a partial collection as a complete study.
    complete = not errors and len(records) == len(universe) * len(strategy_ids)
    result = {
        "schema_version": 1, "study": "retrospective_fixed_chronological_holdout",
        "market": market, "period": period,
        "timestamp_utc": now.astimezone(timezone.utc).isoformat(),
        "strategy_ids": strategy_ids, "production_enabled_unchanged": active,
        "training_fraction": 0.70, "forward_horizon_sessions": 5,
        "embargo_sessions": 5, "min_independent_events_for_summary": MIN_EVENTS_TO_INTERPRET,
        "requested_symbols": len(universe), "evaluated_rows": len(records),
        "error_count": len(errors), "complete": complete,
        "errors": errors, "rows": records,
        "cautions": [
            "Retrospective temporal holdout, NOT a prospective or untouched independent sample.",
            "Strategy variants and this curated ticker universe were designed using historical observations.",
            "No parameter tuning is performed within this run; prior research selection bias remains.",
            "Directional forward analytical close differences are not trade returns or short-selling P&L.",
            "A five-bar gap separates training cutoff and evaluation; last five days are censored.",
            "Events within the same five-day horizon are thinned for descriptive counts only.",
            "The unconditional baseline uses overlapping forward windows; it is descriptive, not a significance test.",
            "TWSE cash dividends/corporate actions can distort unadjusted closes; US uses adjusted analytical closes.",
            "No raw licensed OHLCV data is published in this report.",
            "With fewer than 20 nonoverlapping events per symbol no event mean is reported.",
        ],
    }
    (out / "holdout.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Historical chronological holdout — NOT prospective validation",
        "", f"Market: {market}; period: {period}; strategies: {', '.join(strategy_ids)}",
        f"Symbols: {len(universe)}; complete: {complete}; errors: {len(errors)}",
        "Train: first 70% of completed daily sessions; embargo: 5; label horizon: 5 sessions.",
        "At least 20 non-overlapping observations per ticker needed to show a descriptive event mean.",
        "",
        "| Strategy | Symbol | Raw events | Labeled non-overlap | Absent future labels | Status |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    lines.extend(
        f"| {r['strategy_id']} | {r['symbol']} | {r['raw_holdout_signals']} | "
        f"{r['nonoverlapping_labeled_events']} | {r['censored_no_future_label']} | "
        f"{r['evidence_status']} |" for r in records
    )
    lines += ["", "No signal, insufficient events, and unsupported data basis are distinct outcomes.",
              "No strategy activation, orders, portfolio construction or investment advice."]
    if errors:
        lines += ["", "## Failures"]
        lines.extend(f"- {e['symbol']}: {e['type']}: {e['reason']}" for e in errors)
    (out / "holdout.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if not complete:
        raise RuntimeError("Holdout incomplete: inspect holdout.json for errors")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", required=True, choices=["tw", "us"])
    parser.add_argument("--strategies", default="sakata_morning_star,sakata_evening_star")
    parser.add_argument("--period", default="1y", choices=["1y", "2y"])
    parser.add_argument("--out", type=Path, default=Path("holdout_output"))
    args = parser.parse_args()
    result = evaluate_market(args.market,
                             [s.strip() for s in args.strategies.split(",")],
                             args.period, args.out)
    print((args.out / "holdout.md").read_text(encoding="utf-8"))
    if not result["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
