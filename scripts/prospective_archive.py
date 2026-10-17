"""Append-only session-keyed prospective metadata journal.

Never overwrite an existing session. On concurrent Git pushes retry from latest
main and verify the existing content; a conflicting entry is a hard failure.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time


def run(*args, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=True)


def archive(receipt):
    market = receipt["market"]
    session = receipt["session_date"]
    if market not in ("tw", "us") or len(session) != 10:
        raise ValueError("Invalid market/session")
    path = Path("prospective") / receipt["freeze_hash"][:16] / market / (session + ".json")
    raw = json.dumps(receipt, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    for attempt in range(3):
        run("git", "fetch", "origin", "main")
        run("git", "switch", "-C", "prospective-archive", "origin/main")
        if path.exists():
            old = json.loads(path.read_text(encoding="utf-8"))
            # Idempotent rerun on the same source run only.
            if old == receipt:
                return str(path)
            raise ValueError(f"Immutable prospective session already archived: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw, encoding="utf-8")
        run("git", "add", "--", str(path))
        run("git", "-c", "user.name=github-actions[bot]",
            "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
            "commit", "-m", f"prospective: {market} {session}")
        pushed = run("git", "push", "origin", "HEAD:main", check=False)
        if pushed.returncode == 0:
            return str(path)
        if attempt == 2:
            raise RuntimeError(pushed.stderr)
        time.sleep(attempt + 1)
    raise RuntimeError("Prospective append retry exhausted")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--receipt", type=Path, required=True)
    a = p.parse_args()
    print(archive(json.loads(a.receipt.read_text(encoding="utf-8"))))
