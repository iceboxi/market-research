"""Compatibility shim: the strategy-independent engine is strategy_research.

Keep the historical CLI and helper signatures; do not maintain a second
research implementation or GitHub Actions workflow for Morning Star.
"""
import argparse
from pathlib import Path
from scripts import strategy_research as core

STRATEGY_ID = "sakata_morning_star"
read_json = core.read_json


def research_config(source, target):
    return core.research_config(source, target, STRATEGY_ID)


def verify(backtest, scan, inputs, quality, signals, selected, market):
    return core.verify(backtest, scan, inputs, quality, signals, selected,
                       market, STRATEGY_ID)


def historical_observations(provider, market, symbols, params, minimum_bars=8):
    return core.historical_observations(
        provider, market, symbols, STRATEGY_ID, params, minimum_bars
    )


def run_study(market, period="1y", out=Path("research_output"),
              config_dir=Path("config"), provider=None, now=None,
              strict_freshness=True):
    return core.run_study(
        STRATEGY_ID, market, period, out, config_dir, provider,
        now, strict_freshness
    )


def main():
    p = argparse.ArgumentParser(description="Legacy Morning Star research CLI")
    p.add_argument("--market", choices=["tw", "us"], required=True)
    p.add_argument("--period", choices=["6mo", "1y", "2y"], default="1y")
    p.add_argument("--out", type=Path, default=Path("research_output"))
    args = p.parse_args()
    run_study(args.market, args.period, args.out)
    print((args.out / "study.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
