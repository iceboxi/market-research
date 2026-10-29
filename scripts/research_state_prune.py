"""Prune early-pipeline and unchanged duplicate research versions (#127).

A deliberate, reviewed removal from research-state. The dry run prints the exact records
and a digest; `--apply --expect DIGEST` removes them only when the plan recomputed on a
fresh read still has that digest, and only if the remaining state validates.

Removed: versions before a stock's first one with financial research, and completed
versions `unchanged` against the previous kept one; plus acked publications and
notifications that reference them. Kept: the subject's latest / last-success version,
the checkpoint's last completed version, and the published or pending publication and
notification with every version they reference.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re

from market_research.research_comparison import compare_snapshots
from scripts.research_state import (
    notification_path, publication_path, read, snapshot_path, validate_records,
)
from scripts.state_store import GitStateStore, StateError

SUBJECT_RE = re.compile(r"subjects/tw/([0-9]{4,6}\.TW)\.json")


def _refs(record):
    comparison = record.get("comparison") or {}
    return {ref for ref in (record.get("snapshot_id"), record.get("last_success_id"),
                            comparison.get("previous_snapshot_id"),
                            *(comparison.get("last_good_snapshot_ids") or {}).values()) if ref}


def _symbol_plan(records, symbol):
    snaps = sorted((v for p, v in records.items() if p.startswith(f"snapshots/tw/{symbol}/")),
                   key=lambda s: (s["observed_at_utc"], s["id"]))
    full = [i for i, s in enumerate(snaps) if (s.get("readiness") or {}).get("financial") == "available"]
    reasons, previous = {}, None
    for i, snap in enumerate(snaps):
        if full and i < full[0]:
            reasons[snap["id"]] = "early_pipeline_before_first_full_research"
            continue
        if snap["execution"]["status"] != "completed":
            continue
        if previous is not None and compare_snapshots(previous, snap, {}).get("categories") == ["unchanged"]:
            reasons[snap["id"]] = "unchanged_vs_previous_kept"
            continue
        previous = snap
    subject = records.get(f"subjects/tw/{symbol}.json") or {}
    checkpoint = records.get(f"checkpoints/tw/{symbol}.json") or {}
    protected = {subject.get("latest_observation_id"), subject.get("last_success_id"),
                 checkpoint.get("last_completed_snapshot_id")}
    live_pubs = {subject.get(k) for k in ("published_publication_id", "pending_publication_id")} - {None}
    live_notes = {subject.get(k) for k in ("published_notification_id", "pending_notification_id")} - {None}
    for pid in live_pubs:
        protected |= _refs(records[publication_path(pid, symbol)])
    for nid in live_notes:
        protected |= _refs(records[notification_path(nid, symbol)])
    pruned = set(reasons) - protected
    remove = {snapshot_path(i, symbol) for i in pruned}
    for path, value in records.items():
        if path.startswith((f"publications/tw/{symbol}/", f"notifications/tw/{symbol}/")) and _refs(value) & pruned:
            remove.add(path)
    for path, value in records.items():
        if (path.startswith(f"notifications/tw/{symbol}/") and
                publication_path(value["publication_id"], symbol) in remove):
            remove.add(path)
    live = {publication_path(i, symbol) for i in live_pubs} | {notification_path(i, symbol) for i in live_notes}
    if remove & live:
        raise StateError("Prune plan would remove a live publication or notification")
    return remove, [{"symbol": symbol, "id": s["id"], "observed_at_utc": s["observed_at_utc"],
                     "session": (s.get("technical") or {}).get("session"), "reason": reasons[s["id"]]}
                    for s in snaps if s["id"] in pruned]


def plan(records, branch):
    """Records to remove, the pruned versions, and a digest of the exact removal list."""
    remove, versions = set(), []
    for symbol in sorted(m.group(1) for m in map(SUBJECT_RE.fullmatch, records) if m):
        symbol_remove, symbol_versions = _symbol_plan(records, symbol)
        remove |= symbol_remove
        versions += symbol_versions
    kept = {p: v for p, v in records.items() if p not in remove}
    validate_records(kept, branch)
    ordered = sorted(remove)
    return {"remove": ordered, "versions": versions, "records_before": len(records),
            "records_after": len(kept), "digest": sha256(json.dumps(ordered).encode()).hexdigest()}


def apply(store, expect):
    """Remove exactly the approved plan; refuse if the fresh plan differs."""
    current = plan(read(store)["records"], store.branch)
    if current["digest"] != expect:
        raise StateError("Prune plan differs from the approved digest; rerun the dry run")

    def merge(records):
        fresh = plan(records, store.branch)
        if fresh["digest"] != expect:
            raise StateError("Prune plan changed during the write; rerun the dry run")
        return {p: v for p, v in records.items() if p not in set(fresh["remove"])}
    return {**current, "write": store.commit("research", merge, remove=frozenset(current["remove"]))}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state-branch", choices=("research-state", "research-state-validation"),
                        default="research-state")
    parser.add_argument("--apply", action="store_true", help="remove the planned records")
    parser.add_argument("--expect", help="digest printed by the dry run that was approved")
    parser.add_argument("--out", type=Path, default=Path("research_state_prune.json"))
    args = parser.parse_args()
    store = GitStateStore(branch=args.state_branch)
    if args.apply:
        if not args.expect:
            parser.error("--apply requires --expect DIGEST from an approved dry run")
        result = {"mode": "apply", **apply(store, args.expect)}
    else:
        result = {"mode": "dry_run", **plan(read(store)["records"], store.branch)}
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "remove"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
