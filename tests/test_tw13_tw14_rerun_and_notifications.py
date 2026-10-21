"""TW13 (recoverable rerun triggers & checkpoint) and TW14 (GitHub change notifications) tests."""
from copy import deepcopy
import subprocess

import pytest

from market_research.research_snapshot import prepare_snapshot
from scripts.research_state import (
    CHECKPOINT,
    SUBJECT,
    archive,
    initialize,
    notification_marker,
    notification_path,
    notify,
    publication_path,
    publish,
    read,
    reconcile_rerun_triggers,
    render_notification,
)
from scripts.state_store import GitStateStore
from test_research_snapshot import identity, report
from test_research_state import repo


class SinkWithComments:
    repository = "owner/repo"

    def __init__(self):
        self.issues = {}
        self.comments = {}
        self.creates = self.updates = self.comment_creates = 0
        self.timeout_after_write = False
        self.timeout_after_comment = False

    def find(self, marker):
        return [deepcopy(v) for v in self.issues.values() if marker in v["body"]]

    def get(self, number):
        return deepcopy(self.issues[number])

    def create(self, title, body):
        self.creates += 1
        number = 900 + self.creates
        self.issues[number] = {"number": number, "body": body, "state": "open", "locked": False}
        if self.timeout_after_write:
            raise TimeoutError("reply lost after issue create")
        return self.get(number)

    def update(self, number, body):
        self.updates += 1
        self.issues[number]["body"] = body
        if self.timeout_after_write:
            raise TimeoutError("reply lost after issue update")
        return self.get(number)

    def find_comments(self, number, marker):
        return [deepcopy(c) for c in self.comments.get(number, []) if marker in c["body"]]

    def create_comment(self, number, body):
        self.comment_creates += 1
        cid = 5000 + self.comment_creates
        entry = {"id": cid, "body": body}
        self.comments.setdefault(number, []).append(entry)
        if self.timeout_after_comment:
            raise TimeoutError("reply lost after comment create")
        return deepcopy(entry)


def test_tw13_checkpoint_baseline_crash_recovery_and_failure_retention(repo):
    _, _, store = repo
    initialize(store)

    # 1. First observation initializes checkpoint baseline without enqueuing historic events
    r1 = reconcile_rerun_triggers(
        store, canonical_event_ids=["tw-material-001", "tw-material-002"], financial_version="ifrs-2026-06-30"
    )
    assert r1["trigger_status"] == "baseline_initialized"
    assert r1["pending_rerun"] is None
    cp1 = read(store)["records"][CHECKPOINT]
    assert cp1["consumed_event_ids"] == ["tw-material-001", "tw-material-002"]
    assert cp1["consumed_financial_version"] == "ifrs-2026-06-30"

    # 2. Re-running with identical canonical event IDs and version is idempotent and does not enqueue
    r2 = reconcile_rerun_triggers(
        store, canonical_event_ids=["tw-material-001", "tw-material-002"], financial_version="ifrs-2026-06-30"
    )
    assert r2["trigger_status"] == "up_to_date"
    assert r2["pending_rerun"] is None

    # 3. Canonical event baseline advances (e.g. watcher succeeded and crashed before research);
    # next reconciliation detects the delta between canonical events and research checkpoint.
    r3 = reconcile_rerun_triggers(
        store,
        canonical_event_ids=["tw-material-001", "tw-material-002", "tw-material-003"],
        financial_version="ifrs-2026-09-30",
    )
    assert r3["trigger_status"] == "rerun_pending"
    assert r3["new_event_ids"] == ["tw-material-003"]
    assert set(r3["pending_rerun"]["reasons"]) == {"new_official_events", "financial_version_changed"}

    # 4. If research run is partial/failed, archiving the partial snapshot MUST NOT clear pending_rerun
    failed_snap = prepare_snapshot(
        report("2026-10-19T12:00:00+00:00", False), identity("100", "2026-10-19T12:01:00+00:00")
    )
    archive(failed_snap, store, consumed_event_ids=["tw-material-003"], consumed_financial_version="ifrs-2026-09-30")
    cp_after_fail = read(store)["records"][CHECKPOINT]
    assert cp_after_fail["pending_rerun"] is not None
    assert cp_after_fail["consumed_event_ids"] == ["tw-material-001", "tw-material-002"]
    assert cp_after_fail["consumed_financial_version"] == "ifrs-2026-06-30"

    # 5. Subsequent successful research run atomically archives snapshot + publication + advances checkpoint
    good_snap = prepare_snapshot(
        report("2026-10-20T12:00:00+00:00", True), identity("101", "2026-10-20T12:01:00+00:00")
    )
    archive(good_snap, store, consumed_event_ids=["tw-material-003"], consumed_financial_version="ifrs-2026-09-30")
    records = read(store)["records"]
    cp_after_good = records[CHECKPOINT]
    assert cp_after_good["pending_rerun"] is None
    assert "tw-material-003" in cp_after_good["consumed_event_ids"]
    assert cp_after_good["consumed_financial_version"] == "ifrs-2026-09-30"
    assert cp_after_good["last_completed_snapshot_id"] == good_snap["id"]
    assert records[SUBJECT]["pending_publication_id"] is not None


def test_tw14_baseline_and_unchanged_never_send_notifications(repo):
    _, _, store = repo
    initialize(store)
    sink = SinkWithComments()

    # 1. Baseline snapshot -> fixed report created, NO change notification queued or sent
    snap1 = prepare_snapshot(report("2026-10-19T12:00:00+00:00", True), identity("100", "2026-10-19T12:01:00+00:00"))
    archive(snap1, store)
    assert read(store)["records"][SUBJECT].get("pending_notification_id") is None
    assert publish(sink, store)["status"] == "published"
    assert notify(sink, store)["status"] == "already_current"
    assert sink.comment_creates == 0

    # 2. Pure timestamp update with identical research evidence -> unchanged, NO notification
    snap2 = prepare_snapshot(report("2026-10-20T12:00:00+00:00", True), identity("101", "2026-10-20T12:01:00+00:00"))
    archive(snap2, store)
    assert read(store)["records"][SUBJECT].get("pending_notification_id") is None
    assert publish(sink, store)["status"] == "published"
    assert notify(sink, store)["status"] == "already_current"
    assert sink.comment_creates == 0


def test_tw14_meaningful_change_notification_timeout_reconciliation_and_ack_failure(repo):
    checkout, _, store = repo
    initialize(store)
    sink = SinkWithComments()

    # Baseline
    snap1 = prepare_snapshot(report("2026-10-19T12:00:00+00:00", True), identity("100", "2026-10-19T12:01:00+00:00"))
    archive(snap1, store)
    assert publish(sink, store)["status"] == "published"

    # Revision (monthly revenue changed 1000 -> 1250) -> queues both pending_publication_id and pending_notification_id
    rep2 = report("2026-10-20T12:00:00+00:00", True)
    rep2["issuer"]["facts"][0]["value"] = 1250
    snap2 = prepare_snapshot(rep2, identity("101", "2026-10-20T12:01:00+00:00"))
    archive(snap2, store)

    subj = read(store)["records"][SUBJECT]
    notif_id = subj["pending_notification_id"]
    assert notif_id is not None

    # Cannot deliver notification before fixed report publication is ACKed
    assert notify(sink, store)["reason"] == "publication_not_yet_acked"
    assert publish(sink, store)["status"] == "published"

    # Simulate timeout after comment creation: comment exists on GitHub, local receives outcome_unknown
    sink.timeout_after_comment = True
    n1 = notify(sink, store)
    assert n1["status"] == "outcome_unknown"
    assert sink.comment_creates == 1
    assert read(store)["records"][notification_path(notif_id)]["creation_attempted"] is True
    assert read(store)["records"][SUBJECT]["pending_notification_id"] == notif_id

    # Retry reconciles via comment marker without creating a second comment
    sink.timeout_after_comment = False
    n2 = notify(sink, store)
    assert n2["status"] == "delivered"
    assert n2["comment_id"] == 5001
    assert sink.comment_creates == 1
    assert read(store)["records"][SUBJECT]["pending_notification_id"] is None
    assert read(store)["records"][SUBJECT]["published_notification_id"] == notif_id

    # Idempotent rerun does not post another comment
    assert notify(sink, store)["status"] == "already_current"
    assert sink.comment_creates == 1

    body = sink.comments[901][0]["body"]
    assert notification_marker(store.branch, notif_id) in body
    assert "1,000 → 1,250 TWD_thousands" in body
    assert "不構成任何買進、賣出" in body


def test_tw14_tampered_issue_or_comment_blocks_delivery_fail_closed(repo):
    _, _, store = repo
    initialize(store)
    sink = SinkWithComments()

    snap1 = prepare_snapshot(report("2026-10-19T12:00:00+00:00", True), identity("100", "2026-10-19T12:01:00+00:00"))
    archive(snap1, store)
    assert publish(sink, store)["status"] == "published"

    rep2 = report("2026-10-20T12:00:00+00:00", False)
    snap2 = prepare_snapshot(rep2, identity("101", "2026-10-20T12:01:00+00:00"))
    archive(snap2, store)
    assert publish(sink, store)["status"] == "published"

    # Tamper with fixed Issue state (locked) -> notification must fail closed as blocked
    sink.issues[901]["locked"] = True
    res = notify(sink, store)
    assert res["status"] == "blocked"
    assert res["reason"] == "external_issue_changed"
    assert sink.comment_creates == 0
