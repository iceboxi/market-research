"""Command-line entry point."""
import argparse
from pathlib import Path
from .runner import run_scan


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--market", choices=["tw", "us", "both"], default="both")
    p.add_argument("--period", default="1y")
    p.add_argument("--out", type=Path, default=Path("output"))
    p.add_argument("--config-dir", type=Path, default=Path("config"))
    p.add_argument("--check-twse", action="store_true")
    p.add_argument("--include-snapshot", action="store_true")
    p.add_argument('--snapshot-output', type=Path, help='Local only, private raw snapshot')
    p.add_argument('--replay-dir', type=Path, help='Load a checksummed local snapshot')
    p.add_argument('--strict-freshness', action='store_true', help='Require latest completed exchange session')
    a = p.parse_args()
    result = run_scan(a.market, a.period, a.out, a.config_dir,
                      include_snapshot=a.include_snapshot, check_twse=a.check_twse,
                      snapshot_output=a.snapshot_output, replay_dir=a.replay_dir,
                      strict_freshness=a.strict_freshness)
    print(result)
    if result["error_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
