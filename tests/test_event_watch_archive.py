"""Real Git regression coverage for the public event-state archive boundary."""
from contextlib import chdir
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from market_research.event_monitor import build_snapshot
from scripts.event_watch_archive import archive


class EventStateArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.repo = self.root / "checkout"
        self.git("init", "--bare", "--initial-branch=main", str(self.remote))
        self.git("clone", str(self.remote), str(self.repo))
        self.git("config", "user.name", "Test", cwd=self.repo)
        self.git("config", "user.email", "test@example.invalid", cwd=self.repo)
        self.repo.joinpath("code.txt").write_text("application code\n")
        self.git("add", ".", cwd=self.repo)
        self.git("commit", "-m", "Initial application", cwd=self.repo)
        self.git("push", "origin", "main", cwd=self.repo)
        self.main_sha = self.git("rev-parse", "main", cwd=self.remote)
        self.git("switch", "-c", "feature", cwd=self.repo)
        self.proposals = self.root / "proposals"
        state = build_snapshot("2330.TW", "tw", {
            "status": "available", "source": "https://official.example/events",
            "coverage": "daily_snapshot",
            "events": [{"event_id": "tw-material-a"}],
        }, datetime(2026, 10, 19, 12, tzinfo=timezone.utc))
        self.write_proposal(state)

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd, check=True,
                              capture_output=True, text=True).stdout.strip()

    def write_proposal(self, state):
        path = self.proposals / state["market"] / (state["symbol"] + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state) + "\n")
        return path

    def test_archive_keeps_main_and_callers_branch_unchanged(self):
        with chdir(self.repo):
            self.assertEqual(archive(self.proposals), "archived")
        self.assertEqual(self.git("rev-parse", "main", cwd=self.remote), self.main_sha)
        self.assertEqual(self.git("branch", "--show-current", cwd=self.repo), "feature")
        files = self.git("ls-tree", "-r", "--name-only", "event-state", cwd=self.remote)
        self.assertEqual(files, "event_state/tw/2330.TW.json")


if __name__ == "__main__":
    unittest.main()
