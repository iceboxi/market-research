from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

import pytest

from market_research.knowledge_site import LinkMapper, build_knowledge_site, render_markdown, slugify

KB = Path(__file__).resolve().parents[1] / "knowledge"
TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def _markdown_tables(text: str) -> int:
    lines, fenced, count = text.split("\n"), False, 0
    for i, line in enumerate(lines[:-1]):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced and line.lstrip().startswith("|") and TABLE_SEP.match(lines[i + 1]):
            count += 1
    return count


@pytest.mark.parametrize("path", sorted(KB.glob("*.md")), ids=lambda p: p.name)
def test_every_knowledge_file_renders_all_tables_and_headings(path: Path):
    text = path.read_text(encoding="utf-8")
    body, title = render_markdown(text, LinkMapper({p.name for p in KB.glob("*.md")}))
    assert title, "each knowledge file starts with an H1"
    assert body.count("<table>") == _markdown_tables(text) > 0
    headings = sum(1 for line in text.split("\n") if re.match(r"^#{1,6}\s", line))
    assert len(re.findall(r"<h[1-6] id=", body)) == headings
    assert "|---" not in body and "| ---" not in body, "table syntax leaked into the page"
    for row in re.findall(r"<tr>(.*?)</tr>", body):
        assert row.count("<td") + row.count("<th") >= 1


def test_link_rewrite_targets():
    link = LinkMapper({"README.md", "memory.md"}, repo_url="https://github.com/o/r")
    assert link("memory.md") == "memory.html"
    assert link("README.md#固定標準") == "index.html#固定標準"
    assert link("../docs/TECHNICAL_PRICE_CONTEXT.md") == "https://github.com/o/r/blob/main/docs/TECHNICAL_PRICE_CONTEXT.md"
    assert link("https://example.com/a?b=1&c=2") == "https://example.com/a?b=1&c=2"
    assert link("#local") == "#local"


def test_inline_markup_and_escaping():
    md = ("# T\n\n| a | b |\n| --- | ---: |\n| **x**<br>y | `<i>` ~~old~~ [m](memory.md) |\n\n"
          "<script>alert(1)</script> [q](https://e.com/?a=1&b=2) <https://e.com/x?a=1&b=2>")
    body, _ = render_markdown(md, LinkMapper({"memory.md"}))
    assert '<a href="https://e.com/x?a=1&amp;b=2">https://e.com/x?a=1&amp;b=2</a>' in body
    assert "<strong>x</strong><br>y" in body
    assert '<td class="num"><code>&lt;i&gt;</code> <del>old</del> <a href="memory.html">m</a></td>' in body
    assert "<script>" not in body and "&lt;script&gt;" in body
    assert 'href="https://e.com/?a=1&amp;b=2"' in body


def test_nested_lists_close_in_order():
    md = "- a\n  - b\n    1. c\n- d\n\n1. **e**\n   - f\n2. g"
    body, _ = render_markdown(md)
    assert body == ("<ul><li>a<ul><li>b<ol><li>c</li></ol></li></ul></li><li>d</li></ul>\n"
                    "<ol><li><strong>e</strong><ul><li>f</li></ul></li><li>g</li></ol>")


def test_heading_anchors_match_github_and_dedupe():
    assert slugify("固定標準") == "固定標準"
    assert slugify("2026-11-05　P×Q 篩選：美股") == "2026-11-05pq-篩選美股"
    body, _ = render_markdown("## 推論\n\n## 推論")
    assert 'id="推論"' in body and 'id="推論-1"' in body


@pytest.mark.parametrize("md", ["```text\nunclosed", "| a |\n| --- |", "**open", "[x](", "\t- tab\n      - deep",
                                "|", "#", "- \n-", "\x00", "~~"])
def test_malformed_input_never_raises(md: str):
    body, _ = render_markdown(md)
    assert isinstance(body, str)


def test_build_writes_index_first_with_nav_and_footer(tmp_path: Path):
    src = tmp_path / "kb"
    src.mkdir()
    (src / "README.md").write_text("# 知識庫\n\n| 檔案 |\n| --- |\n| [memory.md](memory.md) |\n", encoding="utf-8")
    (src / "memory.md").write_text("# 記憶體\n\n見 [README](README.md#知識庫)。\n", encoding="utf-8")
    written = build_knowledge_site(src, tmp_path / "out", sha="abcdef1234",
                                   generated=datetime(2026, 11, 6, 1, 0, tzinfo=timezone.utc))
    assert [p.name for p in written] == ["index.html", "memory.html"]
    index = written[0].read_text(encoding="utf-8")
    page = written[1].read_text(encoding="utf-8")
    assert '<a href="memory.html">memory.md</a>' in index
    assert '<a href="index.html#知識庫">README</a>' in page
    assert '<a href="memory.html" aria-current="page">記憶體</a>' in page
    assert '<a class="toplink" href="../">個股研究</a>' in page
    assert "commit <code>abcdef1</code>" in page and "2026-11-06 09:00（台北）" in page
    assert "<title>記憶體 — 知識庫</title>" in page
