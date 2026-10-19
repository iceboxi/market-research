"""Synthetic-only remote Actions acceptance with correlated child evidence.

A successful dispatch response is NOT proof that a workflow or Artifact passed.
This intentionally does not access production state, market sources or secrets.
"""
import argparse
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
from uuid import uuid4
from zipfile import ZipFile

CHILD = "synthetic-acceptance-child.yml"
ARTIFACT = "synthetic-contract-"


class AcceptanceError(RuntimeError):
    pass


def validate(receipt, sha, correlation):
    if not isinstance(receipt, dict):
        raise AcceptanceError("Child receipt is not JSON object")
    required = {"schema_version", "kind", "correlation", "code_sha",
                "coverage", "result"}
    if not required.issubset(receipt):
        raise AcceptanceError("Missing required child receipt fields")
    if (type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1
            or receipt["kind"] != "synthetic_remote_acceptance"
            or receipt["correlation"] != correlation or receipt["code_sha"] != sha
            or receipt["coverage"] != "synthetic_only"
            or receipt["result"] != "passed"):
        raise AcceptanceError("Child schema, revision, coverage or outcome mismatch")
    return receipt


def choose_child(runs, correlation, sha):
    title = "synthetic-acceptance-" + correlation
    matched = [x for x in runs if x.get("display_title") == title]
    if len(matched) > 1:
        raise AcceptanceError("Ambiguous child workflow correlation")
    if not matched:
        return None
    child = matched[0]
    if (child.get("head_sha") != sha or child.get("event") != "workflow_dispatch"
            or child.get("head_branch") != "main"):
        raise AcceptanceError("Wrong child head SHA, ref or workflow event")
    return child


def check_artifact(artifacts, correlation, zip_bytes, sha):
    wanted = ARTIFACT + correlation
    matched = [x for x in artifacts if x.get("name") == wanted]
    if len(matched) != 1 or matched[0].get("expired", False):
        raise AcceptanceError("Required child artifact missing, ambiguous or expired")
    if matched[0].get("size_in_bytes", 0) <= 0:
        raise AcceptanceError("Empty child artifact")
    try:
        with ZipFile(io.BytesIO(zip_bytes)) as archive:
            paths = [p for p in archive.namelist() if not p.endswith("/")]
            if paths != ["receipt.json"]:
                raise AcceptanceError("Unexpected artifact contract files")
            content = archive.read("receipt.json")
            if len(content) > 65536:
                raise AcceptanceError("Child receipt exceeds limit")
            receipt = json.loads(content)
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        raise AcceptanceError("Invalid child artifact ZIP/JSON") from exc
    return validate(receipt, sha, correlation)


class Github:
    def __init__(self, repo, token, api="https://api.github.com"):
        self.repo, self.token, self.api = repo, token, api

    def request(self, path, method="GET", data=None, binary=False):
        payload = json.dumps(data).encode() if data is not None else None
        request = urllib.request.Request(
            self.api + "/repos/" + self.repo + "/" + path,
            data=payload, method=method,
            headers={"Authorization": "Bearer " + self.token,
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as resp:
                raw = resp.read()
                return raw if binary else json.loads(raw) if raw else {}
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            raise AcceptanceError("GitHub API request failed: " + type(exc).__name__) from exc


def run(github, sha, correlation, poll=15, attempts=30, sleep=time.sleep):
    """Return proof for the exact child, never merely the dispatch status."""
    github.request("actions/workflows/" + CHILD + "/dispatches", "POST",
                   {"ref": "main", "inputs": {"correlation": correlation, "expected_sha": sha}})
    for _ in range(attempts):
        response = github.request("actions/workflows/" + CHILD + "/runs?event=workflow_dispatch&per_page=100")
        child = choose_child(response.get("workflow_runs", []), correlation, sha)
        if child is not None and child.get("status") == "completed":
            if child.get("conclusion") != "success":
                raise AcceptanceError("Child run failed: " + str(child.get("conclusion")))
            run_id = child["id"]
            response = github.request(f"actions/runs/{run_id}/artifacts?per_page=100")
            artifacts = response.get("artifacts", [])
            named = [a for a in artifacts if a.get("name") == ARTIFACT + correlation]
            if len(named) != 1:
                raise AcceptanceError("Required child artifact missing")
            blob = github.request(f"actions/artifacts/{named[0]['id']}/zip", binary=True)
            receipt = check_artifact(artifacts, correlation, blob, sha)
            return {
                "schema_version": 1, "status": "passed", "code_sha": sha,
                "correlation": correlation, "child_run_id": run_id,
                "child_run_url": child["html_url"],
                "artifact_id": named[0]["id"], "child_receipt": receipt,
                "scope": "synthetic_contract_only; not market-data/live/schedule acceptance",
            }
        sleep(poll)
    raise AcceptanceError("No completed correlated child within bounded polling budget")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=Path("remote_acceptance"))
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    result = {"schema_version": 1, "status": "failed",
              "scope": "synthetic_contract_only; not market-data/live/schedule acceptance"}
    try:
        repo = os.environ["GITHUB_REPOSITORY"]
        sha = os.environ["GITHUB_SHA"]
        if (os.environ.get("GITHUB_REF") != "refs/heads/main" or
                os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"):
            raise AcceptanceError("Manual main workflow_dispatch required")
        correlation = uuid4().hex
        result.update(run(Github(repo, os.environ["GH_TOKEN"]), sha, correlation))
    except (AcceptanceError, KeyError, ValueError) as exc:
        result["error"] = str(exc)
        raise
    finally:
        result["checked_at_utc"] = datetime.now(timezone.utc).isoformat()
        (args.out / "acceptance.json").write_text(json.dumps(result, indent=2) + "\n")
        (args.out / "summary.md").write_text(
            "# Synthetic remote child acceptance\n\n" +
            f"Result: **{result['status']}**\n\n" +
            f"Child: {result.get('child_run_url', 'unavailable')}\n\n" +
            "Only validates child run identity, immutable SHA and synthetic artifact contract.\n"
        )


if __name__ == "__main__":
    main()
