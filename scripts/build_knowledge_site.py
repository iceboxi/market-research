"""Render `knowledge/*.md` into static pages for the Pages site (#173).

Usage: python -m scripts.build_knowledge_site --src knowledge --out _site/knowledge
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from market_research.knowledge_site import DEFAULT_REPO_URL, build_knowledge_site


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, default=Path("knowledge"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--extra", type=Path, action="append", default=[],
                        help="generated Markdown page to add (#183 prediction scorecard)")
    parser.add_argument("--extra-label", default="排程產生", help="footer source label for --extra pages")
    parser.add_argument("--extra-url", default="", help="footer source link for --extra pages")
    args = parser.parse_args(argv)
    server, repo = os.getenv("GITHUB_SERVER_URL"), os.getenv("GITHUB_REPOSITORY")
    repo_url = f"{server}/{repo}" if server and repo else DEFAULT_REPO_URL
    extra = tuple((path, args.extra_label, args.extra_url or None) for path in args.extra)
    written = build_knowledge_site(args.src, args.out, repo_url=repo_url, sha=os.getenv("GITHUB_SHA", ""),
                                   extra=extra)
    if not written:
        raise SystemExit(f"no Markdown files in {args.src}")
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
