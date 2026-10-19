"""Guard the exclusive prospective state owner before scheduled research.

Fail closed if an initialized canonical namespace would overlap the legacy
main writer or if the canonical writer has not been bootstrapped.
"""
import argparse
import os

from scripts.state_store import GitStateStore, StateError


def require_owner(mode, store=None):
    if mode not in ("legacy", "canonical"):
        raise StateError("Invalid prospective owner mode")
    current = (store or GitStateStore()).read("prospective")
    status = current.get("status")
    if mode == "legacy" and status == "available":
        raise StateError("Canonical prospective authority exists: legacy main writer must stop")
    if mode == "canonical" and status != "available":
        raise StateError("Canonical prospective authority missing; explicit bootstrap required")
    if status not in ("available", "uninitialized"):
        raise StateError("Cannot establish prospective state owner")
    return mode


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", default=os.getenv("PROSPECTIVE_STATE_MODE", "legacy"))
    args = p.parse_args()
    print("Prospective state writer:", require_owner(args.mode))


if __name__ == "__main__":
    main()
