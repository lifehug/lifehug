#!/usr/bin/env python3
"""Owner-only local Lifehug wiki viewer."""

from __future__ import annotations

import argparse
import html
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from lifehug_core import WIKI_DIR, slugify


def wiki_pages():
    if not WIKI_DIR.exists():
        return []
    return sorted(p for p in WIKI_DIR.rglob("*.md") if p.is_file())


# Slug-collision priority when two page types share a stem (e.g. a person and a
# theme both named "family"). Lower index wins.
_TYPE_PRIORITY = [
    "people",
    "relationships",
    "projects",
    "themes",
    "places",
    "periods",
    "self",
    "lifes_work",
    "objects",
]


# Friendly labels + display order for sidebar groups, keyed by page-type dir.
_GROUP_LABELS = {
    "people": "People",
    "relationships": "Relationships",
    "themes": "Themes",
    "projects": "Projects",
    "places": "Places",
    "periods": "Periods",
    "self": "Self",
    "lifes_work": "Life's Work",
    "objects": "Objects",
}


def page_title(path: Path) -> str:
    """Friendly page label: frontmatter `title:` if present, else prettified stem."""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            head = fh.read(1024)
        m = re.search(r'^title:\s*"?(.+?)"?\s*$', head, re.MULTILINE)
        if m:
            return m.group(1).strip()
    except OSError:
        pass
    return path.stem.replace("-", " ").title()


def nav_html(active_rel: str | None = None) -> str:
    """Grouped, collapsible sidebar. Top-level pages (index/log) link directly;
    type folders become collapsible sections with a caret, count, and titles."""
    top_links: list[Path] = []
    groups: dict[str, list[Path]] = {}
    for p in wiki_pages():
        if p.parent == WIKI_DIR:  # top-level (index.md, log.md)
            top_links.append(p)
        else:
            groups.setdefault(p.parent.name, []).append(p)

    def link(p: Path, cls: str) -> str:
        rel = str(p.relative_to(WIKI_DIR.parent))
        active = " active" if active_rel == rel else ""
        return f'<a class="{cls}{active}" href="/page/{quote(rel)}">{html.escape(page_title(p))}</a>'

    parts: list[str] = [link(p, "sidebar-top") for p in top_links]

    ordered = [t for t in _TYPE_PRIORITY if t in groups] + [t for t in groups if t not in _TYPE_PRIORITY]
    for gtype in ordered:
        items = sorted(groups[gtype], key=lambda p: page_title(p).lower())
        if not items:
            continue
        label = html.escape(_GROUP_LABELS.get(gtype, gtype.replace("_", " ").title()))
        rows = "".join(link(p, "sidebar-item") for p in items)
        parts.append(
            f'<div class="sidebar-group" data-group="{html.escape(gtype)}">'
            f'<div class="sidebar-group-header" onclick="toggleGroup(\'{html.escape(gtype)}\')">'
            f'<span class="sidebar-group-main"><span class="chevron">&#9660;</span>'
            f'<span class="sidebar-group-title">{label}</span></span>'
            f'<span class="count">{len(items)}</span></div>'
            f'<div class="sidebar-items">{rows}</div></div>'
        )
    return "\n".join(parts)


def page_index() -> dict[str, str]:
    """Map each page slug (filename stem) to its /page/ relative path.

    Lets [[wikilinks]] resolve to real pages instead of search. On collision,
    the page whose parent directory ranks earliest in _TYPE_PRIORITY wins.
    """
    index: dict[str, str] = {}
    chosen_rank: dict[str, int] = {}
    for page in wiki_pages():
        slug = page.stem
        parent = page.parent.name
        rank = _TYPE_PRIORITY.index(parent) if parent in _TYPE_PRIORITY else len(_TYPE_PRIORITY)
        if slug in chosen_rank and chosen_rank[slug] <= rank:
            continue
        chosen_rank[slug] = rank
        index[slug] = str(page.relative_to(WIKI_DIR.parent))
    return index


def strip_frontmatter(text: str) -> str:
    return re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, count=1, flags=re.DOTALL)


def render_markdown(text: str, index: dict[str, str] | None = None) -> str:
    if index is None:
        index = page_index()
    text = strip_frontmatter(text)
    out = []
    in_list = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            if in_list:
                out.append("</ul>")
                in_list = False
            continue
        if line.startswith("# "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("### "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{linkify(html.escape(line[2:]), index)}</li>")
        elif line.startswith("> "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<blockquote>{linkify(html.escape(line[2:]), index)}</blockquote>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<p>{linkify(html.escape(line), index)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def linkify(text: str, index: dict[str, str] | None = None) -> str:
    index = index or {}

    def repl(match):
        label = match.group(1)
        slug = slugify(label)
        target = index.get(slug)
        if target:
            # Resolve to the real page — graph navigation, not a re-query.
            href = f"/page/{quote(target)}"
        else:
            # Unknown/forward link: fall back to search so it still does something.
            href = f"/search?q={quote(label)}"
        return f'<a href="{href}">[[{html.escape(label)}]]</a>'

    text = re.sub(r"\[\[([^\]]+)\]\]", repl, text)
    text = re.sub(
        r"\[([^\]]+)\]\((wiki/[^\)]+)\)",
        lambda m: f'<a href="/page/{quote(m.group(2))}">{m.group(1)}</a>',
        text,
    )
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


def layout(title: str, body: str, active_rel: str | None = None) -> bytes:
    nav = nav_html(active_rel)
    doc = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} · Lifehug</title>
  <style>
    body {{ margin: 0; font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #202124; background: #fbfaf7; }}
    header {{ height: 52px; display: flex; align-items: center; gap: 16px; padding: 0 20px; border-bottom: 1px solid #ddd8cf; background: #fff; position: sticky; top: 0; }}
    header a {{ color: #202124; text-decoration: none; font-weight: 650; }}
    form {{ margin-left: auto; }}
    input {{ border: 1px solid #c8c2b8; border-radius: 6px; padding: 7px 9px; min-width: 220px; }}
    .shell {{ display: grid; grid-template-columns: 300px 1fr; min-height: calc(100vh - 53px); }}
    nav {{ border-right: 1px solid #ddd8cf; padding: 14px 10px; overflow: auto; background: #f4f0e8; }}
    .sidebar-top {{ display: block; color: #3f3428; text-decoration: none; padding: 5px 8px; font-size: 14px; font-weight: 600; }}
    .sidebar-group {{ margin-top: 6px; }}
    .sidebar-group-header {{ display: flex; align-items: center; justify-content: space-between;
      padding: 6px 8px; cursor: pointer; user-select: none; border-radius: 6px; color: #2f271c; font-weight: 650; font-size: 13px; }}
    .sidebar-group-header:hover {{ background: #ece5d8; }}
    .sidebar-group-main {{ display: flex; align-items: center; gap: 6px; }}
    .chevron {{ display: inline-block; font-size: 9px; color: #8a7a63; transition: transform 0.15s; }}
    .sidebar-group.collapsed .chevron {{ transform: rotate(-90deg); }}
    .sidebar-group.collapsed .sidebar-items {{ display: none; }}
    .count {{ font-size: 11px; color: #9a8c75; font-weight: 600; }}
    .sidebar-items {{ padding: 2px 0 4px; }}
    .sidebar-item {{ display: block; color: #5a4d3c; text-decoration: none; padding: 4px 8px 4px 22px;
      font-size: 13px; border-left: 3px solid transparent; border-radius: 0 4px 4px 0; white-space: nowrap;
      overflow: hidden; text-overflow: ellipsis; }}
    .sidebar-item:hover {{ background: #ece5d8; }}
    .sidebar-item.active {{ background: #e6dcc8; border-left-color: #987b55; color: #2f271c; font-weight: 600; }}
    main {{ max-width: 860px; padding: 32px 44px 80px; }}
    h1 {{ font-size: 34px; line-height: 1.15; margin: 0 0 20px; }}
    h2 {{ margin-top: 34px; border-bottom: 1px solid #e5dfd5; padding-bottom: 6px; }}
    blockquote {{ border-left: 4px solid #987b55; margin-left: 0; padding-left: 16px; color: #50463b; }}
    code {{ background: #eee7dc; padding: 1px 4px; border-radius: 4px; }}
    a {{ color: #7c4f1d; }}
    @media (max-width: 820px) {{ .shell {{ grid-template-columns: 1fr; }} nav {{ display: none; }} main {{ padding: 24px; }} }}
  </style>
</head>
<body>
  <header>
    <a href="/">Lifehug</a>
    <a href="/search">Search</a>
    <form action="/search"><input name="q" placeholder="Search wiki"></form>
  </header>
  <div class="shell"><nav>{nav}</nav><main>{body}</main></div>
  <script>
    var KEY = "lifehug.collapsedGroups";
    function loadCollapsed() {{ try {{ return new Set(JSON.parse(localStorage.getItem(KEY)) || []); }} catch (e) {{ return new Set(); }} }}
    function toggleGroup(type) {{
      var el = document.querySelector('.sidebar-group[data-group="' + type + '"]');
      if (!el) return;
      el.classList.toggle('collapsed');
      var set = loadCollapsed();
      el.classList.contains('collapsed') ? set.add(type) : set.delete(type);
      localStorage.setItem(KEY, JSON.stringify(Array.from(set)));
    }}
    loadCollapsed().forEach(function (type) {{
      var el = document.querySelector('.sidebar-group[data-group="' + type + '"]');
      if (el) el.classList.add('collapsed');
    }});
  </script>
</body>
</html>"""
    return doc.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def send_html(self, title, body, status=200, active_rel=None):
        payload = layout(title, body, active_rel)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            index = WIKI_DIR / "index.md"
            text = index.read_text(encoding="utf-8") if index.exists() else "# Lifehug\n\nRun `python3 system/wiki_compile.py`."
            self.send_html("Index", render_markdown(text))
            return

        if parsed.path.startswith("/page/"):
            rel_path = Path(unquote(parsed.path[len("/page/"):]))
            if rel_path.is_absolute() or ".." in rel_path.parts:
                self.send_html("Invalid path", "<h1>Invalid path</h1>", status=400)
                return
            page = WIKI_DIR.parent / rel_path
            if not page.exists() or WIKI_DIR not in page.resolve().parents:
                self.send_html("Not found", "<h1>Not found</h1>", status=404)
                return
            active_rel = str(page.relative_to(WIKI_DIR.parent))
            self.send_html(page_title(page), render_markdown(page.read_text(encoding="utf-8", errors="replace")),
                           active_rel=active_rel)
            return

        if parsed.path == "/search":
            query = parse_qs(parsed.query).get("q", [""])[0].strip().lower()
            rows = []
            for page in wiki_pages():
                text = page.read_text(encoding="utf-8", errors="replace")
                if not query or query in text.lower() or query in page.stem.lower():
                    rows.append(
                        f'<li><a href="/page/{quote(str(page.relative_to(WIKI_DIR.parent)))}">'
                        f"{html.escape(str(page.relative_to(WIKI_DIR)))}</a></li>"
                    )
            title = "Search"
            body = f"<h1>Search</h1><p>{len(rows)} result(s)</p><ul>{''.join(rows)}</ul>"
            self.send_html(title, body)
            return

        self.send_html("Not found", "<h1>Not found</h1>", status=404)


def main():
    parser = argparse.ArgumentParser(description="Serve the owner-only Lifehug wiki")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host; keep 127.0.0.1 for owner-only local use")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Lifehug wiki serving at http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()