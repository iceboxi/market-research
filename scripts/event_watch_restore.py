"""Restore only verified canonical event state, no legacy fallback."""
import argparse
import json
from pathlib import Path

from scripts.event_watch_archive import event_state


def restore(out):
    state = event_state()
    root = Path(out)
    if root.exists() and any(root.iterdir()):
        raise ValueError("Restore output must be empty to prevent stale baseline reuse")
    for key, snapshot in state["records"].items():
        target = root / key.removeprefix("event_state/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    return {"schema_version": 1, "status": "restored",
            "state_commit": state["head"],
            "authority": state["authority"],
            "count": len(state["records"])}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=Path("event_watch_input"))
    p.add_argument("--receipt", type=Path, default=Path("event_watch_output/restore_receipt.json"))
    a = p.parse_args()
    result = {"status": "failed"}
    try:
        result = restore(a.out)
    except Exception as e:
        result = {"status": "failed", "error": str(e)}
        raise
    finally:
        a.receipt.parent.mkdir(parents=True, exist_ok=True)
        a.receipt.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
