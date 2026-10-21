"""GitHub Issues delivery adapter. No state ownership or retries here."""
import json
import re
import subprocess


class GitHubResearchSink:
    def __init__(self, repository):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Invalid GitHub repository")
        self.repository = repository
        self.endpoint = f"repos/{repository}/issues"

    def _request(self, endpoint, method="GET", payload=None, paginate=False):
        args = ["gh", "api", "--method", method, endpoint]
        if paginate:
            args += ["--paginate", "--slurp"]
        if payload is not None:
            args += ["--input", "-"]
        result = subprocess.run(args, text=True, capture_output=True, timeout=60,
                                input=json.dumps(payload, ensure_ascii=False) if payload is not None else None)
        if result.returncode:
            raise RuntimeError("GitHub Issues request failed")
        return json.loads(result.stdout)

    def find(self, marker):
        pages = self._request(self.endpoint + "?state=all&per_page=100", paginate=True)
        return [issue for page in pages for issue in page
                if "pull_request" not in issue and marker in (issue.get("body") or "")]

    def get(self, number):
        return self._request(f"{self.endpoint}/{number}")

    def create(self, title, body):
        return self._request(self.endpoint, "POST", {"title": title, "body": body})

    def update(self, number, body):
        return self._request(f"{self.endpoint}/{number}", "PATCH", {"body": body})

    def find_comments(self, number, marker):
        pages = self._request(f"{self.endpoint}/{number}/comments?per_page=100", paginate=True)
        return [comment for page in pages for comment in page
                if marker in (comment.get("body") or "")]

    def create_comment(self, number, body):
        return self._request(f"{self.endpoint}/{number}/comments", "POST", {"body": body})
