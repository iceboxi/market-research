"""Verify gh wire payloads and pagination at the subprocess boundary."""
import json
import subprocess

import pytest

from scripts.research_github import GitHubResearchSink


def test_paginated_issue_search_ignores_prs_and_posts_literal_json(monkeypatch):
    calls = []
    marker = "<!-- fixed -->"
    body = marker + '\n繁體中文\nLiteral `code` $HOME $(false) "quotes"'
    def command(args, **kwargs):
        calls.append((args, kwargs))
        if "--paginate" in args:
            data = [[{"number": 1, "body": "other"}], [
                {"number": 2, "body": body}, {"number": 3, "body": body, "pull_request": {}}]]
        else:
            data = {"number": 2, "body": body}
        return subprocess.CompletedProcess(args, 0, json.dumps(data), "")
    monkeypatch.setattr("scripts.research_github.subprocess.run", command)
    sink = GitHubResearchSink("owner/repo")
    assert [v["number"] for v in sink.find(marker)] == [2]
    sink.create("Title", body)
    sink.update(2, body)
    assert "--slurp" in calls[0][0]
    assert "state=all&per_page=100" in calls[0][0][4]
    assert json.loads(calls[1][1]["input"]) == {"title": "Title", "body": body}
    assert json.loads(calls[2][1]["input"]) == {"body": body}
    assert all("shell" not in kwargs for _, kwargs in calls)


def test_api_failure_does_not_expose_raw_response(monkeypatch):
    monkeypatch.setattr("scripts.research_github.subprocess.run", lambda *a, **kw:
                        subprocess.CompletedProcess(a, 1, "secret response", "secret error"))
    with pytest.raises(RuntimeError, match="GitHub Issues request failed") as error:
        GitHubResearchSink("owner/repo").find("marker")
    assert "secret" not in str(error.value)
