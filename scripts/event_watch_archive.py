"""Archive only event identifiers on main with fast-forward retry.

Artifact receipts are not scraped into Git. Any source-invalid update is omitted.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time

from market_research.event_monitor import compare_snapshots


def command(*args, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=True)


def archive(proposed_root, destination=Path("event_state")):
    source = Path(proposed_root)
    files = sorted(source.glob("*/*.json"))
    if not files:
        return "no_eligible_state"
    for attempt in range(3):
        command("git", "fetch", "origin", "main")
        command("git", "switch", "-C", "event-watch-archive", "origin/main")
        wrote = 0
        for path in files:
            candidate = json.loads(path.read_text(encoding="utf-8"))
            market, symbol = path.parent.name, path.stem
            if candidate.get("market") != market or candidate.get("symbol") != symbol:
                raise ValueError("Proposal identity mismatch")
            dest = Path(destination) / market / (symbol + ".json")
            old = json.loads(dest.read_text(encoding="utf-8")) if dest.exists() else None
            change, merged = compare_snapshots(old, candidate)
            if merged is None:
                if change["status"] == "state_incompatible":
                    raise ValueError(f"Cannot archive incompatible state for {symbol}")
                continue
            if old != merged:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
                command("git", "add", "--", str(dest))
                wrote += 1
        if not wrote:
            return "already_current"
        command("git", "-c", "user.name=github-actions[bot]",
                "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                "commit", "-m", "state: observed official disclosure IDs")
        pushed = command("git", "push", "origin", "HEAD:main", check=False)
        if pushed.returncode == 0:
            return "archived"
        if attempt == 2:
            raise RuntimeError("Event state CAS archive failed: " + pushed.stderr)
        time.sleep(1 + attempt)
    raise RuntimeError("Event state archive exhausted")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--proposed", type=Path, required=True)
    args = p.parse_args()
    print("Event state:", archive(args.proposed))


if __name__ == "__main__":
    main()
