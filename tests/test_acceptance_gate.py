"""Offline negative and success evidence for correlated Actions acceptance."""
import io
import json
from zipfile import ZipFile
import pytest
from scripts.acceptance_gate import AcceptanceError, check_artifact, choose_child, run, validate

SHA = "a" * 40
CORR = "corr-123"


def child(status="completed", conclusion="success", sha=SHA, title=None):
    return {"id": 100, "head_sha": sha, "event": "workflow_dispatch",
            "head_branch": "main", "display_title": title or
            "synthetic-acceptance-" + CORR, "status": status,
            "conclusion": conclusion, "html_url": "https://github.com/test/actions/runs/100"}


def receipt(**patch):
    return {"schema_version": 1, "kind": "synthetic_remote_acceptance",
            "correlation": CORR, "code_sha": SHA, "coverage": "synthetic_only",
            "result": "passed", **patch}


def archive(content):
    mem = io.BytesIO()
    with ZipFile(mem, "w") as z:
        z.writestr("receipt.json", json.dumps(content))
    return mem.getvalue()


def artifacts(**patch):
    return [{"name": "synthetic-contract-" + CORR, "id": 88,
             "size_in_bytes": 100, "expired": False, **patch}]


def test_correct_child_requires_revision_and_event():
    assert choose_child([child()], CORR, SHA)["id"] == 100
    assert choose_child([child()], "another", SHA) is None
    for row in (child(sha="b"*40), {**child(), "event": "push"},
                {**child(), "head_branch": "feature"}):
        with pytest.raises(AcceptanceError):
            choose_child([row], CORR, SHA)


def test_missing_corrupt_and_expired_artifact_block():
    good = archive(receipt())
    assert check_artifact(artifacts(), CORR, good, SHA)["result"] == "passed"
    for data, blob in (([], good), (artifacts(expired=True), good),
                       (artifacts(), b"invalid zip"), (artifacts(), archive(receipt(coverage="partial"))),
                       (artifacts(), archive(receipt(code_sha="b"*40))),
                       (artifacts(), archive(receipt(result="failed"))),
                       (artifacts(), archive(receipt(schema_version=2)))):
        with pytest.raises((AcceptanceError, Exception)):
            check_artifact(data, CORR, blob, SHA)


class StubGithub:
    def __init__(self, state="success"):
        self.state = state
        self.calls = []

    def request(self, path, method="GET", data=None, binary=False):
        self.calls.append((path, method, data))
        if path.endswith("/dispatches"):
            return {}
        if path.endswith("/runs?event=workflow_dispatch&per_page=100"):
            return {"workflow_runs": [child(conclusion="failure" if self.state == "failed" else "success")]}
        if path.endswith("/artifacts?per_page=100"):
            return {"artifacts": artifacts()}
        if path.endswith("/zip"):
            return archive(receipt())
        raise AssertionError(path)


def test_dispatch_alone_cannot_pass_but_verified_child_and_receipt_can():
    github = StubGithub()
    result = run(github, SHA, CORR, attempts=1, sleep=lambda x: None)
    assert result["status"] == "passed"
    assert result["child_run_id"] == 100
    assert github.calls[0][1] == "POST"
    assert github.calls[0][2]["inputs"]["expected_sha"] == SHA
    with pytest.raises(AcceptanceError, match="Child run failed"):
        run(StubGithub("failed"), SHA, CORR, attempts=1, sleep=lambda x: None)


def test_missing_child_never_promotes_dispatch_to_success():
    class NoChild(StubGithub):
        def request(self, path, method="GET", data=None, binary=False):
            if path.endswith("/runs?event=workflow_dispatch&per_page=100"):
                return {"workflow_runs": []}
            return super().request(path, method, data, binary)
    with pytest.raises(AcceptanceError, match="No completed"):
        run(NoChild(), SHA, CORR, poll=0, attempts=2, sleep=lambda x: None)
