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
    a = p.parse_args()
    result = run_scan(a.market, a.period, a.out, a.config_dir,
                      include_snapshot=a.include_snapshot, check_twse=a.check_twse)
    print(result)
    if result["error_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
