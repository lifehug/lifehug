#!/usr/bin/env python3
"""Owner-only local Lifehug wiki viewer."""

from __future__ import annotations

import argparse
import html
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from lifehug_core import WIKI_DIR


def wiki_pages():
    if not WIKI_DIR.exists():
        return []
    return sorted(p for p in WIKI_DIR.rglob("*.md") if p.is_file())


def strip_frontmatter(text: str) -> str:
    return re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, count=1, flags=re.DOTALL)


def render_markdown(text: str) -> str:
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
            out.append(f"<li>{linkify(html.escape(line[2:]))}</li>")
        elif line.startswith("> "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<blockquote>{linkify(html.escape(line[2:]))}</blockquote>")
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<p>{linkify(html.escape(line))}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def linkify(text: str) -> str:
    def repl(match):
        label = match.group(1)
        slug = label.strip().lower().replace(" ", "-")
        return f'<a href="/search?q={quote(label)}">[[{html.escape(label)}]]</a>'

    text = re.sub(r"\[\[([^\]]+)\]\]", repl, text)
    text = re.sub(
        r"\[([^\]]+)\]\((wiki/[^\)]+)\)",
        lambda m: f'<a href="/page/{quote(m.group(2))}">{m.group(1)}</a>',
        text,
    )
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


def layout(title: str, body: str) -> bytes:
    pages = wiki_pages()
    nav = "\n".join(
        f'<a href="/page/{quote(str(p.relative_to(WIKI_DIR.parent)))}">{html.escape(str(p.relative_to(WIKI_DIR)))}</a>'
        for p in pages
    )
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
    nav {{ border-right: 1px solid #ddd8cf; padding: 18px; overflow: auto; background: #f4f0e8; }}
    nav a {{ display: block; color: #3f3428; text-decoration: none; padding: 5px 0; font-size: 14px; }}
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
    <a href="/">Lifehug Wiki</a>
    <a href="/search">Search</a>
    <form action="/search"><input name="q" placeholder="Search wiki"></form>
  </header>
  <div class="shell"><nav>{nav}</nav><main>{body}</main></div>
</body>
</html>"""
    return doc.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def send_html(self, title, body, status=200):
        payload = layout(title, body)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            index = WIKI_DIR / "index.md"
            text = index.read_text(encoding="utf-8") if index.exists() else "# Lifehug Wiki\n\nRun `python3 system/wiki_compile.py`."
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
            self.send_html(page.stem, render_markdown(page.read_text(encoding="utf-8", errors="replace")))
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
