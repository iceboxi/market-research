"""Restore/archive compact event state without switching the caller's checkout."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

from market_research.event_monitor import compare_snapshots, validate_snapshot

STATE_BRANCH = "event-state"
STATE_DIRECTORY = "event_state"
BOT = ("-c", "user.name=github-actions[bot]", "-c",
       "user.email=41898282+github-actions[bot]@users.noreply.github.com")


def command(*args, cwd=None, check=True, input=None):
    return subprocess.run(args, cwd=cwd, check=check, input=input,
                          text=True, capture_output=True)


def remote_state():
    """Only an explicitly missing ref permits bootstrap; transport errors fail."""
    ref = "refs/heads/" + STATE_BRANCH
    listed = command("git", "ls-remote", "--exit-code", "origin", ref, check=False)
    if listed.returncode not in (0, 2):
        raise RuntimeError("Cannot read remote event-state ref: " + listed.stderr)
    exists = listed.returncode == 0
    command("git", "fetch", "--no-tags", "origin", ref if exists else "refs/heads/main")
    commit = command("git", "rev-parse", "FETCH_HEAD").stdout.strip()
    return exists, commit


def read_states(commit, state_only=False):
    """Validate the complete tree before exporting any file."""
    args = [] if state_only else ["--", STATE_DIRECTORY]
    tree = command("git", "ls-tree", "-rz", commit, *args).stdout
    states = {}
    for entry in tree.split("\0"):
        if not entry:
            continue
        metadata, name = entry.split("\t", 1)
        mode, kind, blob = metadata.split()
        path = Path(name)
        if (mode != "100644" or kind != "blob" or len(path.parts) != 3 or
                path.parts[0] != STATE_DIRECTORY or path.suffix != ".json"):
            raise ValueError("Unexpected file in event state tree: " + name)
        state = json.loads(command("git", "cat-file", "blob", blob).stdout)
        validate_snapshot(state)
        if state["market"] != path.parts[1] or state["symbol"] != path.stem:
            raise ValueError("State path/identity mismatch")
        states[Path(*path.parts[1:])] = state
    return states


def write_states(destination, states):
    for relative, state in states.items():
        path = Path(destination) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")


def restore(destination):
    destination = Path(destination)
    if destination.exists():
        raise ValueError("Restore requires a new destination to avoid stale state")
    exists, commit = remote_state()
    states = read_states(commit, state_only=exists)
    destination.mkdir(parents=True)
    write_states(destination, states)
    return {"status": "restored" if exists else "bootstrap_from_main",
            "state_branch": STATE_BRANCH, "source_commit": commit,
            "state_count": len(states)}


def archive(proposed_root):
    return archive_result(proposed_root)["status"]


def archive_result(proposed_root):
    proposals = {}
    for path in sorted(Path(proposed_root).glob("*/*.json")):
        candidate = json.loads(path.read_text(encoding="utf-8"))
        validate_snapshot(candidate)
        if candidate["market"] != path.parent.name or candidate["symbol"] != path.stem:
            raise ValueError("Proposal identity mismatch")
        proposals[Path(path.parent.name) / path.name] = candidate
    if not proposals:
        return {"status": "no_eligible_state", "state_branch": STATE_BRANCH,
                "state_commit": None, "proposal_count": 0}
    for attempt in range(3):
        exists, commit = remote_state()
        states = read_states(commit, state_only=exists)
        changed = False
        for relative, candidate in proposals.items():
            old = states.get(relative)
            change, merged = compare_snapshots(old, candidate)
            if merged is None:
                raise ValueError("Cannot archive state: " + change["reason"])
            if merged != old:
                states[relative] = merged
                changed = True
        if exists and not changed:
            return {"status": "already_current", "state_branch": STATE_BRANCH,
                    "state_commit": commit, "proposal_count": len(proposals)}
        base = commit
        if not exists:
            # Root commit: retain neither application files nor its commit history.
            tree = command("git", "mktree", input="").stdout.strip()
            base = command("git", *BOT, "commit-tree", tree,
                           "-m", "state: initialize official event store").stdout.strip()
        with tempfile.TemporaryDirectory(prefix="event-state-") as temp:
            worktree = Path(temp) / "checkout"
            command("git", "worktree", "add", "--detach", str(worktree), base)
            try:
                write_states(worktree / STATE_DIRECTORY, states)
                command("git", "add", "--", STATE_DIRECTORY, cwd=worktree)
                command("git", *BOT, "commit", "-m",
                        "state: observed official disclosure IDs", cwd=worktree)
                saved = command("git", "rev-parse", "HEAD", cwd=worktree).stdout.strip()
                pushed = command("git", "push", "origin", "HEAD:refs/heads/" + STATE_BRANCH,
                                 cwd=worktree, check=False)
                if pushed.returncode == 0:
                    return {"status": "archived", "state_branch": STATE_BRANCH,
                            "state_commit": saved, "proposal_count": len(proposals)}
            finally:
                command("git", "worktree", "remove", "--force", str(worktree))
        # Retry against the new remote tree, never by force-pushing old state.
        if attempt == 2:
            raise RuntimeError("Event state fast-forward archive failed: " + pushed.stderr)
    raise RuntimeError("Event state archive exhausted")


def main():
    parser = argparse.ArgumentParser()
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--proposed", type=Path)
    operation.add_argument("--restore", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    receipt = {"schema_version": 1, "code_sha": os.getenv("GITHUB_SHA"),
               "run_url": (f"https://github.com/{os.getenv('GITHUB_REPOSITORY')}/actions/runs/"
                           f"{os.getenv('GITHUB_RUN_ID')}" if os.getenv("GITHUB_RUN_ID") else None)}
    try:
        receipt.update(restore(args.restore) if args.restore is not None
                       else archive_result(args.proposed))
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        receipt.update(status="failed", error=str(error))
        raise
    finally:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
