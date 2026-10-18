"""Public health archive contract against a real, isolated Git remote."""
from contextlib import chdir
import json
import hashlib
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import monitor
from scripts.state_store import GitStateStore, StateError
from scripts.state_store_acceptance import bootstrap_operations


class HealthStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / "origin.git"
        self.repo = self.root / "checkout"
        self.git("init", "--bare", "--initial-branch=main", str(self.remote))
        self.git("clone", str(self.remote), str(self.repo))
        self.git("config", "user.name", "Test", cwd=self.repo)
        self.git("config", "user.email", "test@example.invalid", cwd=self.repo)
        self.repo.joinpath("application.txt").write_text("application code\n")
        self.legacy = self.record("100")
        old = self.repo / "history/2026/10/20261019-run-100.json"
        old.parent.mkdir(parents=True)
        old.write_text(json.dumps(self.legacy))
        self.git("add", ".", cwd=self.repo)
        self.git("commit", "-m", "Application with legacy history", cwd=self.repo)
        self.git("push", "origin", "main", cwd=self.repo)
        self.main_sha = self.git("rev-parse", "main", cwd=self.remote)
        self.git("switch", "-c", "feature", cwd=self.repo)
        monitor.initialize_history(GitStateStore(self.repo))

    def git(self, *args, cwd=None, check=True):
        result = subprocess.run(["git", *args], cwd=cwd, check=check,
                                capture_output=True, text=True)
        return result.stdout.strip() if check else result

    def record(self, run_id="101", health="healthy"):
        return {"schema_version": 1, "run_id": run_id,
                "observed_at_utc": "2026-10-19T12:00:00+00:00",
                "run_url": "https://github.com/example/repo/actions/runs/" + run_id,
                "market": "tw", "event": "workflow_dispatch", "health": health,
                "reasons": [], "requested": 2, "scanned": 2, "errors": 0,
                "signals": 0, "mismatches": 0, "expected_warnings": 0,
                "unexpected_warnings": 0, "session_dates": {}, "input_hashes": [],
                "strategies": []}

    def test_archive_preserves_main_and_analysis_checkout(self):
        with chdir(self.repo):
            location = monitor.archive(self.record())
        self.assertEqual(location, "history/2026/10/20261019-run-101.json")
        self.assertEqual(self.git("rev-parse", "main", cwd=self.remote), self.main_sha)
        self.assertEqual(self.git("branch", "--show-current", cwd=self.repo), "feature")
        tree = self.git("ls-tree", "-r", "--name-only", "research-state", cwd=self.remote)
        self.assertNotIn("application.txt", tree)
        self.assertIn("operations/history/2026/10/20261019-run-100.json", tree)
        self.assertIn("operations/history/2026/10/20261019-run-101.json", tree)

    def test_import_fresh_read_and_identical_rerun(self):
        store = GitStateStore(self.repo)
        first = monitor.archive_history(self.record(), store)
        self.assertEqual(first["status"], "archived")
        proof = first["authority"]["legacy_import"]
        self.assertEqual(proof["source_sha"], self.main_sha)
        self.assertEqual(proof["record_count"], 1)
        result = monitor.history(GitStateStore(self.repo))
        self.assertEqual(result["records"]["history/2026/10/20261019-run-100.json"], self.legacy)
        self.assertEqual(result["records"][first["path"]], self.record())
        second = monitor.archive_history(self.record(), GitStateStore(self.repo))
        self.assertEqual(second["status"], "already_current")
        self.assertEqual(first["state_commit"], second["state_commit"])

    def test_same_key_conflict_does_not_overwrite_evidence(self):
        store = GitStateStore(self.repo)
        first = monitor.archive_history(self.record(), store)
        with self.assertRaises(StateError):
            monitor.archive_history(self.record(health="critical"), store)
        self.assertEqual(store.read("operations")["head"], first["state_commit"])

    def test_source_failure_is_archived_without_becoming_healthy(self):
        failed = {**self.record(), "health": "critical", "reasons": ["missing_run_artifacts"],
                  "requested": None, "scanned": None, "errors": None}
        result = monitor.archive_history(failed, GitStateStore(self.repo))
        self.assertEqual(result["source_health"], "critical")
        saved = monitor.history(GitStateStore(self.repo))["records"][result["path"]]
        self.assertEqual(saved, failed)

    def test_raw_prices_and_unsafe_identity_are_rejected_before_write(self):
        head = self.git("rev-parse", "research-state", cwd=self.remote)
        for bad in ({**self.record(), "close": [1, 2, 3]},
                    {**self.record(), "input_hashes": [{"market": "tw", "symbol": "2330.TW",
                     "date": "2026-10-19", "sha256": {"close": [1, 2, 3]}}]},
                    {**self.record(), "reasons": [{"close": [1, 2, 3]}]},
                    {**self.record(), "scanned": {"close": [1, 2, 3]}},
                    {**self.record(), "run_id": "../main"},
                    {**self.record(), "observed_at_utc": "2026-10-19T12:00:00"}):
            with self.subTest(bad=bad):
                with self.assertRaises((StateError, ValueError)):
                    monitor.archive_history(bad, GitStateStore(self.repo))
        self.assertEqual(self.git("rev-parse", "research-state", cwd=self.remote), head)

    def peer(self):
        peer = self.root / "peer"
        self.git("clone", "--branch", "research-state", str(self.remote), str(peer))
        self.git("config", "user.name", "Other writer", cwd=peer)
        self.git("config", "user.email", "peer@example.invalid", cwd=peer)
        return peer

    def test_deleted_or_corrupt_state_cannot_fall_back_to_legacy(self):
        monitor.archive_history(self.record(), GitStateStore(self.repo))
        peer = self.peer()
        path = peer / "operations/history/2026/10/20261019-run-100.json"
        path.unlink()
        self.git("add", "--all", cwd=peer)
        self.git("commit", "-m", "Simulate damaged store", cwd=peer)
        self.git("push", "origin", "research-state", cwd=peer)
        head = self.git("rev-parse", "research-state", cwd=self.remote)
        with self.assertRaises(StateError):
            monitor.history(GitStateStore(self.repo))
        with self.assertRaises(StateError):
            monitor.archive_history(self.record("103"), GitStateStore(self.repo))
        self.assertEqual(self.git("rev-parse", "research-state", cwd=self.remote), head)

    def test_incompatible_authority_is_not_a_first_run(self):
        monitor.archive_history(self.record(), GitStateStore(self.repo))
        peer = self.peer()
        path = peer / ".state-store.json"
        manifest = json.loads(path.read_text())
        manifest["schema_version"] = 99
        path.write_text(json.dumps(manifest))
        self.git("add", ".", cwd=peer)
        self.git("commit", "-m", "Unsupported schema", cwd=peer)
        self.git("push", "origin", "research-state", cwd=peer)
        with self.assertRaises(StateError):
            monitor.history(GitStateStore(self.repo))

    def test_missing_migration_proof_is_corruption(self):
        monitor.archive_history(self.record(), GitStateStore(self.repo))
        peer = self.peer()
        path = peer / ".state-store.json"
        manifest = json.loads(path.read_text())
        del manifest["namespaces"]["operations"]["legacy_import"]
        path.write_text(json.dumps(manifest))
        self.git("add", ".", cwd=peer)
        self.git("commit", "-m", "Damaged migration proof", cwd=peer)
        self.git("push", "origin", "research-state", cwd=peer)
        with self.assertRaises(StateError):
            monitor.history(GitStateStore(self.repo))

    def test_unavailable_remote_does_not_initialize_state(self):
        self.git("remote", "set-url", "origin", str(self.root / "missing.git"), cwd=self.repo)
        with self.assertRaises(StateError):
            monitor.archive_history(self.record(), GitStateStore(self.repo))
        self.assertEqual(self.git("rev-parse", "main", cwd=self.remote), self.main_sha)

    def test_rejected_push_emits_failure_receipt_and_cleans_own_worktree(self):
        hook = self.remote / "hooks/pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        report = self.root / "health.json"
        report.write_text(json.dumps(self.record()))
        receipt = self.root / "receipt.json"
        cli = Path(monitor.__file__).resolve()
        result = subprocess.run([sys.executable, str(cli), "archive", "--report", str(report),
                                 "--receipt", str(receipt)], cwd=self.repo,
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(receipt.read_text())["status"], "failed")
        self.assertIn("after 3 attempts", json.loads(receipt.read_text())["error"])
        self.assertEqual(json.loads(receipt.read_text())["main_before"], self.main_sha)
        self.assertEqual(json.loads(receipt.read_text())["authority"]["legacy_import"]["source_sha"], self.main_sha)
        self.assertEqual(self.git("worktree", "list", "--porcelain", cwd=self.repo).count("worktree "), 1)
        self.assertEqual(self.git("branch", "--show-current", cwd=self.repo), "feature")

    def test_deleted_branch_cannot_silently_rebootstrap(self):
        monitor.archive_history(self.record(), GitStateStore(self.repo))
        self.git("update-ref", "-d", "refs/heads/research-state", cwd=self.remote)
        with self.assertRaises(StateError):
            monitor.archive_history(self.record("102"), GitStateStore(self.repo))
        self.assertNotEqual(self.git("show-ref", "--verify", "refs/heads/research-state",
                                     cwd=self.remote, check=False).returncode, 0)

    def test_successful_push_then_failed_probe_keeps_known_commit(self):
        class ProbeFailure(GitStateStore):
            probes = 0

            def main_head(inner):
                inner.probes += 1
                if inner.probes > 1:
                    raise StateError("Simulated post-push transport failure")
                return super().main_head()

        with self.assertRaises(StateError) as caught:
            monitor.archive_history(self.record(), ProbeFailure(self.repo))
        self.assertTrue(hasattr(caught.exception, "receipt"))
        receipt = caught.exception.receipt
        self.assertEqual(receipt["persistence_status"], "archived")
        self.assertEqual(receipt["state_commit"],
                         self.git("rev-parse", "research-state", cwd=self.remote))
        self.assertEqual(receipt["main_before"], self.main_sha)

    def test_production_bootstrap_rejects_feature_branch_dispatch(self):
        out = self.root / "blocked-bootstrap"
        with patch.dict("os.environ", {"GITHUB_REF": "refs/heads/feature",
                                        "GITHUB_EVENT_NAME": "workflow_dispatch"}):
            with self.assertRaises(ValueError):
                bootstrap_operations(out)
        receipt = json.loads(out.joinpath("receipt.json").read_text())
        self.assertEqual(receipt["acceptance"], "failed")
        self.assertEqual(receipt["writer_checks"], [])

    def test_uncertain_push_keeps_candidate_and_migration_evidence(self):
        class LostAcknowledgement(GitStateStore):
            def _git(inner, *args, **kwargs):
                result = super()._git(*args, **kwargs)
                if args[0] == "push":
                    raise StateError("Transport lost after sending write")
                return result

        with self.assertRaises(StateError) as caught:
            monitor.archive_history(self.record(), LostAcknowledgement(self.repo))
        receipt = caught.exception.receipt
        self.assertEqual(receipt["persistence_status"], "outcome_unknown")
        self.assertIsNone(receipt["state_commit"])
        self.assertEqual(receipt["candidate_commit"],
                         self.git("rev-parse", "research-state", cwd=self.remote))
        self.assertEqual(receipt["authority"]["legacy_import"]["source_sha"], self.main_sha)

    def test_cleanup_failure_retains_authority_of_the_persisted_commit(self):
        class CleanupFailure(GitStateStore):
            def _git(inner, *args, **kwargs):
                result = super()._git(*args, **kwargs)
                if args[:2] == ("worktree", "remove"):
                    raise StateError("Cleanup verification failed after write")
                return result

        with self.assertRaises(StateError) as caught:
            monitor.archive_history(self.record(), CleanupFailure(self.repo))
        receipt = caught.exception.receipt
        snapshot = monitor.history(GitStateStore(self.repo))
        self.assertEqual(receipt["persistence_status"], "archived")
        self.assertEqual(receipt["state_commit"], snapshot["head"])
        self.assertEqual(receipt["authority"], snapshot["authority"])

    def race_hook(self, competing_record):
        peer = self.peer()
        relative = monitor.history_key(competing_record)
        peer.joinpath("operations", relative).write_text(json.dumps(competing_record))
        manifest_path = peer / ".state-store.json"
        manifest = json.loads(manifest_path.read_text())
        records = {str(p.relative_to(peer / "operations")): json.loads(p.read_text())
                   for p in peer.joinpath("operations").rglob("*.json")}
        # Encode the documented integrity format for an independent writer.
        raw = json.dumps(records, sort_keys=True, ensure_ascii=False,
                         allow_nan=False, separators=(",", ":")).encode()
        manifest["namespaces"]["operations"].update(
            record_count=len(records), content_sha256=hashlib.sha256(raw).hexdigest())
        manifest_path.write_text(json.dumps(manifest))
        self.git("add", ".", cwd=peer)
        self.git("commit", "-m", "Competing writer", cwd=peer)
        competitor = self.git("rev-parse", "HEAD", cwd=peer)
        self.git("fetch", str(peer), "HEAD", cwd=self.remote)
        sentinel = shlex.quote(str(self.root / "race-fired"))
        remote = shlex.quote(str(self.remote))
        hook = self.remote / "hooks/pre-receive"
        hook.write_text(
            "#!/bin/sh\nset -eu\n"
            f"if [ ! -f {sentinel} ]; then\n"
            f"  touch {sentinel}\n"
            "  env -u GIT_QUARANTINE_PATH -u GIT_OBJECT_DIRECTORY "
            "-u GIT_ALTERNATE_OBJECT_DIRECTORIES "
            f"git --git-dir={remote} update-ref refs/heads/research-state {competitor}\n"
            "fi\n")
        hook.chmod(0o755)
        return competitor

    def test_concurrent_distinct_keys_remerge_after_real_rejected_push(self):
        monitor.archive_history(self.record(), GitStateStore(self.repo))
        self.race_hook(self.record("102"))
        result = monitor.archive_history(self.record("103"), GitStateStore(self.repo))
        self.assertEqual(result["attempts"], 2)
        records = monitor.history(GitStateStore(self.repo))["records"]
        self.assertEqual(set(records), {
            "history/2026/10/20261019-run-100.json", "history/2026/10/20261019-run-101.json",
            "history/2026/10/20261019-run-102.json", "history/2026/10/20261019-run-103.json"})

    def test_concurrent_same_key_conflict_preserves_competing_evidence(self):
        monitor.archive_history(self.record(), GitStateStore(self.repo))
        competitor = self.race_hook(self.record("103", "critical"))
        with self.assertRaises(StateError):
            monitor.archive_history(self.record("103"), GitStateStore(self.repo))
        self.assertEqual(self.git("rev-parse", "research-state", cwd=self.remote), competitor)
        saved = monitor.history(GitStateStore(self.repo))["records"]
        self.assertEqual(saved["history/2026/10/20261019-run-103.json"]["health"], "critical")

    def test_other_namespace_is_preserved(self):
        store = GitStateStore(self.repo)
        monitor.archive_history(self.record(), store)
        store.commit("audit", lambda old: {**old, "checks/probe.json": {"status": "test"}},
                     legacy_prefix="absent", initialize=True)
        monitor.archive_history(self.record("102"), store)
        self.assertEqual(store.read("audit")["records"], {"checks/probe.json": {"status": "test"}})


if __name__ == "__main__":
    unittest.main()
