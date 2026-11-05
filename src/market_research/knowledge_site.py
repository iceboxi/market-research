"""Static pages for the `knowledge/` Markdown files, published next to the research site.

Read-only presentation layer (#173). `knowledge/README.md` becomes `index.html`; every
other `knowledge/<name>.md` becomes `<name>.html`. Rendering covers the Markdown subset
the knowledge base uses (headings, paragraphs, nested lists, pipe tables, fenced code,
links, bold, strikethrough, inline code, `<br>` inside table cells). Any other text is
escaped and shown as-is, so no input raises: a malformed file degrades its own page
instead of blocking the daily Pages deploy.
"""

from __future__ import annotations

from datetime import datetime, timezone
import html
from pathlib import Path
import re
from typing import Callable
from zoneinfo import ZoneInfo

from market_research.research_site import CSS

TAIPEI = ZoneInfo("Asia/Taipei")
DEFAULT_REPO_URL = "https://github.com/iceboxi/market-research"
INDEX_SOURCE = "README.md"

KB_CSS = """
.md{padding:8px 0 0}.md h1{font-size:24px;margin:22px 0 6px;line-height:1.3}
.md h2{margin:34px 0 12px;padding-top:18px;border-top:1px solid var(--line)}
.md h3{margin:26px 0 10px}.md p{margin:8px 0}.md ul,.md ol{padding-left:22px;margin:6px 0}.md li{margin:4px 0}
.md pre{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:10px 12px;overflow-x:auto}
.md pre code{white-space:pre;word-break:normal;font-size:13px}.md del{color:var(--muted)}
.md td{min-width:72px}.md thead th{white-space:normal}
.secnav a[aria-current=page]{color:var(--text);border-bottom-color:var(--accent)}
"""

_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_LIST_ITEM = re.compile(r"^( *)([-*+]|\d+[.)])\s+(.*)$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def _e(value: str) -> str:
    return html.escape(value, quote=True)


def slugify(text: str) -> str:
    """GitHub-style heading anchor: lowercase, drop punctuation, spaces to hyphens."""
    plain = re.sub(r"[`*~]|\[([^\]]*)\]\([^)]*\)", lambda m: m.group(1) or "", text)
    return re.sub(r"[^\w\- ]", "", plain.lower()).replace(" ", "-")


class LinkMapper:
    """Rewrites Markdown link targets for the published knowledge pages."""

    def __init__(self, pages: set[str], repo_url: str = DEFAULT_REPO_URL, branch: str = "main"):
        self.pages = pages  # source file names, e.g. {"README.md", "memory.md"}
        self.blob = f"{repo_url.rstrip('/')}/blob/{branch}/"

    def __call__(self, target: str) -> str:
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("#"):
            return target
        path, _, frag = target.partition("#")
        suffix = f"#{frag}" if frag else ""
        if path in self.pages:
            return ("index.html" if path == INDEX_SOURCE else path[:-3] + ".html") + suffix
        parts: list[str] = ["knowledge"]
        for part in path.split("/"):
            if part == "..":
                if parts:
                    parts.pop()
            elif part not in ("", "."):
                parts.append(part)
        return self.blob + "/".join(parts) + suffix


def render_inline(text: str, link: Callable[[str], str]) -> str:
    codes: list[str] = []

    def stash(m: re.Match[str]) -> str:
        codes.append(f"<code>{_e(m.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"

    out = _e(re.sub(r"`([^`]+)`", stash, text))
    out = out.replace("&lt;br&gt;", "<br>")
    out = re.sub(r"&lt;(https?://\S+?)&gt;", r'<a href="\1">\1</a>', out)  # autolink; already escaped
    out = _LINK.sub(lambda m: f'<a href="{_e(link(html.unescape(m.group(2))))}">{m.group(1)}</a>', out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"~~(.+?)~~", r"<del>\1</del>", out)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], out)


def _cells(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", body)]


def _table(lines: list[str], link: Callable[[str], str]) -> str:
    head = _cells(lines[0])
    aligns = ["num" if c.strip().endswith(":") and not c.strip().startswith(":") else ""
              for c in _cells(lines[1])]
    aligns += [""] * (len(head) - len(aligns))

    def cell(tag: str, value: str, i: int) -> str:
        cls = f' class="{aligns[i]}"' if i < len(aligns) and aligns[i] else ""
        return f"<{tag}{cls}>{render_inline(value, link)}</{tag}>"

    thead = "".join(cell("th", c, i) for i, c in enumerate(head))
    rows = []
    for line in lines[2:]:
        values = _cells(line)
        values += [""] * (len(head) - len(values))
        rows.append("<tr>" + "".join(cell("td", c, i) for i, c in enumerate(values)) + "</tr>")
    return (f'<div class="table-wrap"><table><thead><tr>{thead}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _list(lines: list[str], link: Callable[[str], str]) -> str:
    """Nested lists by indentation; non-item lines continue the previous item."""
    out: list[str] = []
    stack: list[tuple[int, str]] = []  # (indent, tag)
    open_item = False
    for line in lines:
        m = _LIST_ITEM.match(line)
        if not m:
            out.append(" " + render_inline(line.strip(), link))
            continue
        indent, marker, text = len(m.group(1)), m.group(2), m.group(3)
        tag = "ol" if marker[0].isdigit() else "ul"
        while stack and indent < stack[-1][0]:
            out.append(f"</li></{stack.pop()[1]}>")
        if not stack or indent > stack[-1][0]:
            stack.append((indent, tag))
            out.append(f"<{tag}>")
        elif open_item:
            out.append("</li>")
        out.append(f"<li>{render_inline(text, link)}")
        open_item = True
    while stack:
        out.append(f"</li></{stack.pop()[1]}>")
    return "".join(out)


def render_markdown(text: str, link: Callable[[str], str] = lambda t: t) -> tuple[str, str]:
    """Return (html body, first H1 text). Never raises on malformed input."""
    lines = text.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    title = ""
    used: dict[str, int] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.lstrip().startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].lstrip().startswith("```"):
                j += 1
            out.append(f"<pre><code>{_e(chr(10).join(lines[i + 1:j]))}</code></pre>")
            i = j + 1
            continue
        h = _HEADING.match(line)
        if h:
            level, raw = len(h.group(1)), h.group(2)
            slug = slugify(raw)
            n = used.get(slug, 0)
            used[slug] = n + 1
            anchor = slug if n == 0 else f"{slug}-{n}"
            if level == 1 and not title:
                title = re.sub(r"[`*~]", "", raw)
            out.append(f'<h{level} id="{_e(anchor)}">{render_inline(raw, link)}</h{level}>')
            i += 1
            continue
        if line.lstrip().startswith("|") and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
            j = i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            out.append(_table(lines[i:j], link))
            i = j
            continue
        if _LIST_ITEM.match(line):
            j = i + 1
            while j < len(lines) and lines[j].strip() and (
                    _LIST_ITEM.match(lines[j]) or lines[j].startswith(" ")):
                j += 1
            out.append(_list(lines[i:j], link))
            i = j
            continue
        j = i + 1
        while j < len(lines) and lines[j].strip() and not (
                _HEADING.match(lines[j]) or _LIST_ITEM.match(lines[j])
                or lines[j].lstrip().startswith(("```", "|"))):
            j += 1
        out.append("<p>" + "\n".join(render_inline(x.strip(), link) for x in lines[i:j]) + "</p>")
        i = j
    return "\n".join(out), title


def _page(title: str, body: str, nav: str, source: str, repo_url: str, sha: str, generated: datetime) -> str:
    stamp = generated.astimezone(TAIPEI).strftime("%Y-%m-%d %H:%M")
    commit = f"（commit <code>{_e(sha[:7])}</code>）" if sha else ""
    src = f"{repo_url.rstrip('/')}/blob/main/knowledge/{source}"
    return f"""<!DOCTYPE html>
<html lang="zh-Hant-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)} — 知識庫</title>
<style>{CSS}{KB_CSS}</style>
</head>
<body>
<a class="skip" href="#content">跳到內容</a>
<header class="topbar">
  <div class="topbar-inner">
    <div class="brand">Market Research<span>知識庫</span></div>
    <a class="toplink" href="../">個股研究</a>
  </div>
  <nav class="secnav" aria-label="知識庫檔案">{nav}</nav>
</header>
<div class="wrap">
  <main id="content" class="md" tabindex="-1">
{body}
  </main>
  <footer>來源：<a href="{_e(src)}">knowledge/{_e(source)}</a>{commit}；頁面產生於 {stamp}（台北）。研究整理，不是投資建議。</footer>
</div>
</body>
</html>
"""


def build_knowledge_site(src_dir: Path, out_dir: Path, *, repo_url: str = DEFAULT_REPO_URL,
                         sha: str = "", generated: datetime | None = None) -> list[Path]:
    """Render every `src_dir/*.md` into `out_dir`; return the written paths (index first)."""
    generated = generated or datetime.now(timezone.utc)
    sources = sorted(src_dir.glob("*.md"), key=lambda p: (p.name != INDEX_SOURCE, p.name))
    link = LinkMapper({p.name for p in sources}, repo_url=repo_url)
    rendered = []
    for path in sources:
        body, title = render_markdown(path.read_text(encoding="utf-8"), link)
        rendered.append((path, link(path.name), body, title or path.stem))
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for path, href, body, title in rendered:
        nav = "".join(f'<a href="{_e(h)}" aria-current="{"page" if h == href else "false"}">{_e(t)}</a>'
                      for _, h, _, t in rendered)
        target = out_dir / href
        target.write_text(_page(title, body, nav, path.name, repo_url, sha, generated), encoding="utf-8")
        written.append(target)
    return written
