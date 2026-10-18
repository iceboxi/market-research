"""Shared, metadata-only Git store with namespace integrity and bounded retries.

Domain callers supply the merge policy. Git operations use detached temporary
worktrees, never the caller's analysis checkout, and never push main.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

BRANCH = "research-state"
MANIFEST = ".state-store.json"
BOT = ("-c", "user.name=github-actions[bot]", "-c",
       "user.email=41898282+github-actions[bot]@users.noreply.github.com")


class StateError(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      allow_nan=False, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def safe_path(value):
    if not isinstance(value, str) or not value or any(
        not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", part)
        for part in value.split("/")
    ) or not value.endswith(".json"):
        raise StateError("Unsafe metadata path")
    return value


class GitStateStore:
    def __init__(self, repo=Path("."), branch=BRANCH):
        if branch not in (BRANCH, "research-state-validation"):
            raise StateError("Only dedicated state branches may be written")
        self.repo = Path(repo).resolve()
        self.branch = branch

    def _git(self, *args, cwd=None, check=True, input=None):
        try:
            result = subprocess.run(["git", *args], cwd=cwd or self.repo,
                                    text=True, capture_output=True, input=input,
                                    timeout=30)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise StateError("Git state operation unavailable") from error
        if check and result.returncode:
            raise StateError("Git state operation failed: " + result.stderr.strip())
        return result

    def _remote_head(self, branch, missing=False):
        result = self._git("ls-remote", "--exit-code", "origin", "refs/heads/" + branch,
                           check=False)
        if missing and result.returncode == 2:
            return None
        if result.returncode:
            raise StateError("Cannot read remote state authority: " + result.stderr.strip())
        fields = result.stdout.split()
        if len(fields) != 2:
            raise StateError("Unexpected remote ref response")
        head = fields[0]
        if not re.fullmatch(r"[a-f0-9]{40,64}", head):
            raise StateError("Invalid remote head")
        return head

    def main_head(self):
        return self._remote_head("main")

    def _fetch(self, branch, missing=False):
        head = self._remote_head(branch, missing)
        if head is not None:
            # FETCH_HEAD is shared by worktrees; never use it as read authority.
            self._git("fetch", "--no-tags", "--no-write-fetch-head", "origin",
                      "refs/heads/" + branch)
        return head

    def _tree(self, head, prefix=None):
        args = ["--", prefix] if prefix else []
        listing = self._git("ls-tree", "-rz", "--full-tree", head, *args).stdout
        files = {}
        try:
            for item in listing.split("\0"):
                if not item:
                    continue
                metadata, path = item.split("\t", 1)
                mode, kind, blob = metadata.split()
                if mode != "100644" or kind != "blob":
                    raise StateError("State must contain regular JSON metadata files")
                if path != MANIFEST:
                    safe_path(path)
                files[path] = json.loads(self._git("cat-file", "blob", blob).stdout)
            canonical(files)
        except (ValueError, TypeError) as error:
            raise StateError("Corrupt JSON metadata") from error
        return files

    def _load(self):
        head = self._fetch(self.branch, missing=True)
        if head is None:
            return None, {"schema_version": 1, "namespaces": {}}, {}
        files = self._tree(head)
        manifest = files.pop(MANIFEST, None)
        if (not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or
                not isinstance(manifest.get("namespaces"), dict) or
                not manifest["namespaces"]):
            raise StateError("Missing or incompatible state authority manifest")
        namespaces = manifest["namespaces"]
        if any(path.split("/", 1)[0] not in namespaces for path in files):
            raise StateError("Unowned metadata in state tree")
        for name, authority in namespaces.items():
            if not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
                raise StateError("Invalid namespace")
            records = {p[len(name) + 1:]: v for p, v in files.items()
                       if p.startswith(name + "/")}
            if (not isinstance(authority, dict) or authority.get("schema_version") != 1 or
                    authority.get("branch") != self.branch or
                    authority.get("record_count") != len(records) or
                    authority.get("content_sha256") != digest(records)):
                raise StateError("Corrupt or incompatible namespace: " + name)
            proof = authority.get("legacy_import")
            if (not isinstance(proof, dict) or
                    not re.fullmatch(r"[a-f0-9]{40,64}", str(proof.get("source_sha"))) or
                    not re.fullmatch(r"[a-z][a-z0-9_-]*", str(proof.get("prefix"))) or
                    type(proof.get("record_count")) is not int or proof["record_count"] < 0 or
                    not re.fullmatch(r"[a-f0-9]{64}", str(proof.get("content_sha256")))):
                raise StateError("Corrupt namespace migration proof: " + name)
        return head, manifest, files

    def read(self, namespace):
        head, manifest, files = self._load()
        authority = manifest["namespaces"].get(namespace)
        return {"status": "available" if authority else "uninitialized", "head": head,
                "authority": authority,
                "records": {p[len(namespace) + 1:]: v for p, v in files.items()
                            if p.startswith(namespace + "/")}}

    def commit(self, namespace, merge, *, legacy_prefix=None):
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", namespace):
            raise StateError("Invalid namespace")
        code_sha = self._git("rev-parse", "HEAD").stdout.strip()
        for attempt in range(1, 4):
            head, manifest, files = self._load()
            authority = manifest["namespaces"].get(namespace)
            records = {p[len(namespace) + 1:]: v for p, v in files.items()
                       if p.startswith(namespace + "/")}
            if authority is None:
                if legacy_prefix is None or not re.fullmatch(r"[a-z][a-z0-9_-]*", legacy_prefix):
                    raise StateError("Explicit legacy import is required for namespace initialization")
                legacy_sha = self._fetch("main")
                records = self._tree(legacy_sha, legacy_prefix)
                authority = {"schema_version": 1, "branch": self.branch,
                             "legacy_import": {"source_sha": legacy_sha,
                                               "prefix": legacy_prefix,
                                               "record_count": len(records),
                                               "content_sha256": digest(records)}}
            updated = merge(json.loads(canonical(records)))
            if not isinstance(updated, dict) or not records.keys() <= updated.keys():
                raise StateError("Merge must preserve all previously owned records")
            for path in updated:
                safe_path(path)
            if namespace in manifest["namespaces"] and canonical(updated) == canonical(records):
                return {"schema_version": 1, "status": "already_current", "state_branch": self.branch,
                        "state_commit": head, "namespace": namespace, "attempts": attempt,
                        "code_sha": code_sha, "authority": authority}
            authority = {**authority, "record_count": len(updated),
                         "content_sha256": digest(updated)}
            manifest["namespaces"][namespace] = authority
            base = head
            if base is None:
                empty = self._git("mktree", input="").stdout.strip()
                base = self._git(*BOT, "commit-tree", empty, "-m",
                                 "state: initialize metadata store").stdout.strip()
            with tempfile.TemporaryDirectory(prefix="research-state-") as temp:
                worktree = Path(temp) / "checkout"
                self._git("worktree", "add", "--detach", str(worktree), base)
                try:
                    writes = {namespace + "/" + p: v for p, v in updated.items()}
                    writes[MANIFEST] = manifest
                    for path, value in writes.items():
                        dest = worktree / path
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_text(json.dumps(value, indent=2, sort_keys=True,
                                                   ensure_ascii=False, allow_nan=False) + "\n",
                                        encoding="utf-8")
                    self._git("add", "--", namespace, MANIFEST, cwd=worktree)
                    self._git(*BOT, "commit", "-m", "state: update " + namespace, cwd=worktree)
                    saved = self._git("rev-parse", "HEAD", cwd=worktree).stdout.strip()
                    pushed = self._git("push", "origin", "HEAD:refs/heads/" + self.branch,
                                       cwd=worktree, check=False)
                    if pushed.returncode == 0:
                        return {"schema_version": 1, "status": "archived", "state_branch": self.branch,
                                "state_commit": saved, "namespace": namespace,
                                "attempts": attempt, "code_sha": code_sha,
                                "authority": authority}
                finally:
                    self._git("worktree", "remove", "--force", str(worktree))
        raise StateError("Fast-forward state write failed after 3 attempts: " + pushed.stderr.strip())
