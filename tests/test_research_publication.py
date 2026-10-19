"""Independent external system fake: a timeout can follow a real side effect."""
from copy import deepcopy

import pytest

from market_research.research_snapshot import prepare_snapshot
from scripts.research_state import SUBJECT, archive, initialize, publish, read, publication_path
from test_research_snapshot import report, identity
from test_research_state import repo  # real bare-Git fixture


class Sink:
    repository = "owner/repo"
    def __init__(self):
        self.issues = {}
        self.creates = self.updates = 0
        self.timeout_after_write = False
        self.before_return = lambda: None

    def find(self, marker):
        return [deepcopy(v) for v in self.issues.values() if marker in v["body"]]

    def get(self, number):
        return deepcopy(self.issues[number])

    def create(self, title, body):
        self.creates += 1
        number = 900 + self.creates
        self.issues[number] = {"number": number, "body": body, "state": "open", "locked": False}
        self.before_return()
        if self.timeout_after_write:
            raise TimeoutError("reply lost after write")
        return self.get(number)

    def update(self, number, body):
        self.updates += 1
        self.issues[number]["body"] = body
        if self.timeout_after_write:
            raise TimeoutError("reply lost after update")
        return self.get(number)


def setup(store):
    initialize(store)
    archive(prepare_snapshot(report(), identity()), store)


def test_timeout_after_creation_reconciles_without_duplicate_then_updates_same_issue(repo):
    _, _, store = repo
    setup(store)
    sink = Sink()
    sink.timeout_after_write = True
    first = publish(sink, store)
    assert first["status"] == "outcome_unknown"
    assert read(store)["records"][SUBJECT]["pending_publication_id"]
    # A fresh publisher sees the externally created Issue and ACKs without resending.
    second = publish(sink, store)
    assert second["status"] == "published"
    assert second["issue_number"] == 901
    assert (sink.creates, sink.updates) == (1, 0)
    assert publish(sink, store)["status"] == "already_current"
    sink.timeout_after_write = False
    newer = prepare_snapshot(report("2026-10-20T12:00:00+00:00", False),
                             identity("101", "2026-10-20T12:01:00+00:00"))
    archive(newer, store)
    assert publish(sink, store)["issue_number"] == 901
    assert (sink.creates, sink.updates) == (1, 1)
    assert "最近嘗試：2026-10-20" in sink.issues[901]["body"]


def test_ack_does_not_clear_newer_pending_created_during_delivery(repo):
    _, _, store = repo
    setup(store)
    old = read(store)["records"][SUBJECT]["pending_publication_id"]
    sink = Sink()
    sink.before_return = lambda: archive(prepare_snapshot(
        report("2026-10-20T12:00:00+00:00", False), identity("101", "2026-10-20T12:01:00+00:00")), store)
    result = publish(sink, store)
    assert result["status"] == "pending_newer"
    records = read(store)["records"]
    assert records[SUBJECT]["pending_publication_id"] != old
    assert records[publication_path(old)]["status"] == "acked"
    assert records[SUBJECT]["issue_number"] == 901
    assert publish(sink, store)["status"] == "published"


@pytest.mark.parametrize("damage", ["body", "marker", "closed", "duplicate", "permission"])
def test_external_changes_or_uncertain_identity_fail_closed_and_keep_pending(repo, damage):
    _, _, store = repo
    setup(store)
    sink = Sink()
    assert publish(sink, store)["status"] == "published"
    archive(prepare_snapshot(report("2026-10-20T12:00:00+00:00", False),
                             identity("101", "2026-10-20T12:01:00+00:00")), store)
    if damage == "body":
        sink.issues[901]["body"] += "manual edit"
    elif damage == "marker":
        sink.issues[901]["body"] = "marker removed"
    elif damage == "closed":
        sink.issues[901]["state"] = "closed"
    elif damage == "duplicate":
        sink.issues[902] = {**sink.issues[901], "number": 902}
    else:
        sink.find = lambda marker: (_ for _ in ()).throw(PermissionError())
    response = publish(sink, store)
    assert response["status"] in ("blocked", "outcome_unknown")
    assert read(store)["records"][SUBJECT]["pending_publication_id"]
    assert sink.creates == 1 and sink.updates == 0


def test_invisible_creation_is_not_repeated_even_after_a_new_snapshot(repo):
    """Observed in real run 39343829651: Issue list lagged a successful POST."""
    _, _, store = repo
    setup(store)
    class DelayedList(Sink):
        visible = False
        def find(self, marker):
            return super().find(marker) if self.visible else []
        def create(self, title, body):
            assert read(store)["records"][SUBJECT]["creation_attempted"] is True
            return super().create(title, body)
    sink = DelayedList()
    sink.timeout_after_write = True
    assert publish(sink, store)["status"] == "outcome_unknown"
    assert publish(sink, store)["reason"] == "marker_not_visible_after_attempt"
    archive(prepare_snapshot(report("2026-10-20T12:00:00+00:00", False),
                             identity("101", "2026-10-20T12:01:00+00:00")), store)
    assert publish(sink, store)["reason"] == "marker_not_visible_after_attempt"
    assert sink.creates == 1
    sink.visible = True
    sink.timeout_after_write = False
    assert publish(sink, store)["status"] == "published"
    assert read(store)["records"][SUBJECT]["issue_number"] == 901
    assert sink.creates == 1 and sink.updates == 1


def test_old_unconfirmed_subject_cannot_silently_assume_no_creation(repo):
    _, _, store = repo
    setup(store)
    def downgrade(records):
        records[SUBJECT]["schema_version"] = 1
        records[SUBJECT].pop("creation_attempted")
        return records
    store.commit("research", downgrade)
    sink = Sink()
    assert publish(sink, store)["reason"] == "marker_not_visible_after_attempt"
    assert sink.creates == 0


def test_failed_ack_retains_creation_fence_and_recovers_without_another_post(repo):
    import subprocess
    from scripts.state_store import GitStateStore
    checkout, _, store = repo
    setup(store)
    class RejectAck(GitStateStore):
        pushes = 0
        def _git(self, *args, **kwargs):
            if args and args[0] == "push":
                self.pushes += 1
                if self.pushes > 1:  # persist intent, then reject all ACK retries
                    return subprocess.CompletedProcess(args, 1, "", "rejected")
            return super()._git(*args, **kwargs)
    sink = Sink()
    assert publish(sink, RejectAck(checkout))["status"] == "ack_pending"
    subject = read(store)["records"][SUBJECT]
    assert subject["creation_attempted"] and subject["pending_publication_id"]
    assert subject["issue_number"] is None
    assert publish(sink, store)["status"] == "published"
    assert sink.creates == 1
