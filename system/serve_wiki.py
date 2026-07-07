#!/usr/bin/env python3
"""Owner-only local Lifehug wiki viewer."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import html
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from lifehug_core import (
    ANSWERS_DIR,
    CLASSIFICATIONS_DIR,
    COVERAGE_FILE,
    FOCUS_RECS_FILE,
    NEIGHBORHOODS_FILE,
    QUESTION_CANDIDATES_FILE,
    QUESTION_QUEUE_FILE,
    QUESTIONS_FILE,
    ROTATION_FILE,
    SOURCE_LINT_FINDINGS_FILE,
    SOURCE_MANIFEST_FILE,
    STATE_DIR,
    WIKI_DIR,
    load_config,
    parse_categories,
    parse_questions,
    read_json,
    slugify,
)
from entity_roster import ENTITY_TYPES, load_roster
from question_candidates import check_quality, _infer_category
from progress import verdict
from roadmap import focus_fill, load_roadmap, rebuild_roadmap


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


def page_field(path: Path, key: str) -> str:
    """Read a single frontmatter scalar (e.g. `title`, `project`) from a page."""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            head = fh.read(1024)
        m = re.search(rf'^{re.escape(key)}:\s*"?(.+?)"?\s*$', head, re.MULTILINE)
        if m:
            return m.group(1).strip()
    except OSError:
        pass
    return ""


def page_title(path: Path) -> str:
    """Friendly page label: frontmatter `title:` if present, else prettified stem."""
    return page_field(path, "title") or path.stem.replace("-", " ").title()


def nav_html(active_rel: str | None = None) -> str:
    """Grouped, collapsible sidebar. The author's own life-story section leads
    (their self-portrait hub + the life-story arcs), then content groups
    (People, Projects, Themes, …), then meta pages at the bottom. The compile
    log is omitted."""
    cfg = load_config()
    full_name = cfg.get("full_name") or cfg.get("name") or "Me"
    hub_slug = slugify(full_name)

    meta_links: list[Path] = []
    groups: dict[str, list[Path]] = {}
    for p in wiki_pages():
        if p.parent == WIKI_DIR:  # top-level page (index.md, log.md, SCHEMA.md)
            if p.stem.lower() == "log":
                continue  # the compile log doesn't belong in the nav
            meta_links.append(p)
        else:
            groups.setdefault(p.parent.name, []).append(p)

    life_pages = groups.get("life", [])
    hub = next((p for p in life_pages if p.stem == hub_slug), None)

    def link(p: Path, cls: str, label: str | None = None) -> str:
        rel = str(p.relative_to(WIKI_DIR.parent))
        active = " active" if active_rel == rel else ""
        text = html.escape(label if label is not None else page_title(p))
        return f'<a class="{cls}{active}" href="/page/{quote(rel)}">{text}</a>'

    def items_html(items: list[Path]) -> str:
        """Item links for a group, sub-grouped by `section:` frontmatter when
        present (e.g. Etherfuse arcs nest under an 'Etherfuse' sub-label)."""
        plain = [p for p in items if not page_field(p, "section")]
        subs: dict[str, list[Path]] = {}
        for p in items:
            sec = page_field(p, "section")
            if sec:
                subs.setdefault(sec, []).append(p)
        out = [link(p, "sidebar-item") for p in plain]
        for sec in sorted(subs):
            out.append(f'<div class="sidebar-subgroup">{html.escape(sec)}</div>')
            out += [link(p, "sidebar-item sub") for p in subs[sec]]
        return "".join(out)

    def group_block(gtype: str, label: str, rows: str, count: int) -> str:
        # Groups start collapsed (overview first); JS re-expands any the user
        # previously opened. See the expandedGroups localStorage logic below.
        return (
            f'<div class="sidebar-group collapsed" data-group="{html.escape(gtype)}">'
            f'<div class="sidebar-group-header" onclick="toggleGroup(\'{html.escape(gtype)}\')">'
            f'<span class="sidebar-group-main"><span class="chevron">&#9660;</span>'
            f'<span class="sidebar-group-title">{html.escape(label)}</span></span>'
            f'<span class="count">{count}</span></div>'
            f'<div class="sidebar-items">{rows}</div></div>'
        )

    parts: list[str] = []
    # Life section first: the person's self-portrait hub, then the arcs.
    if life_pages:
        arcs = sorted((p for p in life_pages if p is not hub), key=lambda p: page_title(p).lower())
        rows = (link(hub, "sidebar-item", "Who I am") if hub else "") + items_html(arcs)
        count = (1 if hub else 0) + len(arcs)
        parts.append(group_block("life", full_name, rows, count))

    ordered = [t for t in _TYPE_PRIORITY if t in groups] + \
              [t for t in groups if t not in _TYPE_PRIORITY and t != "life"]
    for gtype in ordered:
        items = sorted(groups[gtype], key=lambda p: page_title(p).lower())
        if not items:
            continue
        rows = items_html(items)
        count = len(items)
        # People also carries a pointer to the life hub (the author themselves).
        if gtype == "people" and hub:
            rows = link(hub, "sidebar-item", f"{full_name} →") + rows
            count += 1
        parts.append(group_block(gtype, _GROUP_LABELS.get(gtype, gtype.replace("_", " ").title()),
                                  rows, count))

    # Meta pages last, set apart — Index first, then the rest (Page Structure).
    if meta_links:
        meta_sorted = sorted(meta_links, key=lambda p: (p.stem.lower() != "index", page_title(p).lower()))
        parts.append('<div class="sidebar-meta">'
                     + "".join(link(p, "sidebar-top") for p in meta_sorted) + "</div>")
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
    # Italics: single *…* or _…_ (bold already consumed above). The underscore
    # form uses word-boundary guards so snake_case identifiers and file paths
    # (e.g. source_manifest.json) aren't turned into emphasis.
    text = re.sub(r"\*([^*\n]+)\*", r"<em>\1</em>", text)
    text = re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"<em>\1</em>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


# Hamburger menu groups: what you can DO, what helps you REFLECT, the LIBRARY
# of material, and the SYSTEM's internals. A view registered in VIEWS but not
# claimed by any group falls into System automatically, so adding a view is
# still one registry entry.
VIEW_GROUPS = [
    ("Do", ["queue", "candidates", "recommendations", "book"]),
    ("Reflect", ["mirror", "timeline", "graph"]),
    ("Library", ["artifacts", "question-bank", "sources", "privacy"]),
    ("System", ["status", "focuses", "coverage", "entities", "reports"]),
]


def menu_html() -> str:
    """The hamburger dropdown: registered views grouped by VIEW_GROUPS
    (Do / Reflect / Library / System). Adding a view to VIEWS automatically
    adds it here (under its group, or System if unclaimed) and at
    /views/<slug>."""
    labels = {slug: label for slug, label, _ in VIEWS}
    claimed = {s for _, slugs in VIEW_GROUPS for s in slugs}
    leftovers = [slug for slug, _, _ in VIEWS if slug not in claimed]
    parts = []
    for group_title, slugs in VIEW_GROUPS:
        present = [s for s in slugs if s in labels]
        if group_title == "System":
            present += leftovers
        if not present:
            continue
        parts.append(f'<div class="menu-title">{html.escape(group_title)}</div>')
        parts.extend(
            f'<a class="menu-item" href="/views/{s}">{html.escape(labels[s])}</a>'
            for s in present
        )
    return (
        '<div class="menu-wrap">'
        '<button class="menu-btn" id="menuBtn" aria-label="Views menu" onclick="toggleMenu(event)">'
        '<span></span><span></span><span></span></button>'
        f'<div class="menu-dropdown" id="menuDropdown">{"".join(parts)}</div>'
        '</div>'
    )


def layout(title: str, body: str, active_rel: str | None = None, wide: bool = False) -> bytes:
    nav = nav_html(active_rel)
    menu = menu_html()
    main_cls = "wide" if wide else ""
    doc = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} · Lifehug</title>
  <style>
    :root {{
      --bg: #fbfaf7; --panel: #f4f0e8; --panel-hover: #ece5d8;
      --ink: #202124; --ink-strong: #2f271c; --ink-soft: #5a4d3c; --ink-mid: #6b5d49;
      --muted: #8a7a63; --muted-2: #9a8c75;
      --accent: #987b55; --link: #7c4f1d;
      --line: #ddd8cf; --line-soft: #e5dfd5; --border-strong: #c8c2b8;
      --card-bg: #fff; --card-warm: #fffdf9;
    }}
    body {{ margin: 0; font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: var(--ink); background: var(--bg); }}
    header {{ height: 52px; display: flex; align-items: center; gap: 16px; padding: 0 20px; border-bottom: 1px solid #ddd8cf; background: #fff; position: sticky; top: 0; z-index: 20; }}
    header a {{ color: #202124; text-decoration: none; font-weight: 650; }}
    form {{ margin-left: auto; }}
    input {{ border: 1px solid #c8c2b8; border-radius: 6px; padding: 7px 9px; min-width: 220px; }}
    /* Hamburger menu */
    .menu-wrap {{ position: relative; }}
    .menu-btn {{ display: flex; flex-direction: column; justify-content: center; gap: 4px; width: 36px; height: 34px;
      padding: 0 8px; background: #fff; border: 1px solid #c8c2b8; border-radius: 6px; cursor: pointer; }}
    .menu-btn:hover {{ background: #f4f0e8; }}
    .menu-btn span {{ display: block; height: 2px; background: #5a4d3c; border-radius: 2px; }}
    .menu-dropdown {{ display: none; position: absolute; right: 0; top: calc(100% + 6px); min-width: 220px;
      background: #fff; border: 1px solid #ddd8cf; border-radius: 8px; box-shadow: 0 8px 24px rgba(60,50,30,0.16);
      padding: 6px; z-index: 30; }}
    .menu-dropdown.open {{ display: block; }}
    .menu-title {{ font-size: 11px; font-weight: 700; letter-spacing: 0.6px; text-transform: uppercase; color: #9a8c75; padding: 6px 10px 4px; }}
    .menu-item {{ display: block; color: #3f3428; text-decoration: none; padding: 7px 10px; border-radius: 6px; font-size: 14px; }}
    .menu-item:hover {{ background: #f0eadd; }}
    .shell {{ display: grid; grid-template-columns: 300px 1fr; min-height: calc(100vh - 53px); }}
    nav {{ border-right: 1px solid #ddd8cf; padding: 14px 10px; overflow: auto; background: #f4f0e8; }}
    .sidebar-top {{ display: block; color: #3f3428; text-decoration: none; padding: 5px 8px; font-size: 14px; font-weight: 600; }}
    .sidebar-meta {{ margin-top: 14px; padding-top: 8px; border-top: 1px solid #ddd8cf; }}
    .sidebar-meta .sidebar-top {{ font-weight: 500; color: #6b5d49; font-size: 13px; }}
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
    .sidebar-subgroup {{ padding: 4px 8px 2px 22px; font-size: 10px; font-weight: 700; letter-spacing: 0.6px;
      text-transform: uppercase; color: #9a8c75; }}
    .sidebar-item.sub {{ padding-left: 34px; }}
    .sidebar-item:hover {{ background: #ece5d8; }}
    .sidebar-item.active {{ background: #e6dcc8; border-left-color: #987b55; color: #2f271c; font-weight: 600; }}
    main {{ max-width: 860px; padding: 32px 44px 80px; }}
    main.wide {{ max-width: none; padding: 24px 28px 28px; }}
    h1 {{ font-size: 34px; line-height: 1.15; margin: 0 0 20px; }}
    h2 {{ margin-top: 34px; border-bottom: 1px solid #e5dfd5; padding-bottom: 6px; }}
    blockquote {{ border-left: 4px solid #987b55; margin-left: 0; padding-left: 16px; color: #50463b; }}
    code {{ background: #eee7dc; padding: 1px 4px; border-radius: 4px; }}
    a {{ color: #7c4f1d; }}
    .muted {{ color: #8a7a63; font-size: 14px; }}
    .empty {{ color: #9a8c75; font-style: italic; padding: 8px 0; }}
    .view-desc {{ color: #6b5d49; font-size: 15px; line-height: 1.5; margin: -8px 0 24px; max-width: 680px; }}
    /* Dashboard primitives */
    .barwrap {{ display: flex; align-items: center; gap: 10px; margin: 4px 0; }}
    .bar {{ flex: 1; height: 12px; background: #ece5d8; border-radius: 6px; overflow: hidden; max-width: 520px; }}
    .bar-fill {{ height: 100%; border-radius: 6px; }}
    .bar-label {{ font-size: 13px; color: #6b5d49; white-space: nowrap; }}
    .badge {{ display: inline-block; color: #fff; font-size: 11px; font-weight: 650; padding: 2px 8px; border-radius: 10px; vertical-align: middle; }}
    table.dash {{ border-collapse: collapse; width: 100%; margin: 10px 0 24px; font-size: 14px; }}
    table.dash th {{ text-align: left; border-bottom: 2px solid #ddd8cf; padding: 6px 10px; color: #6b5d49; font-size: 12px; text-transform: uppercase; letter-spacing: 0.4px; }}
    table.dash td {{ border-bottom: 1px solid #eee5d8; padding: 6px 10px; vertical-align: top; }}
    table.dash tr:hover td {{ background: #f6f1e8; }}
    .focus-row {{ padding: 12px 0; border-bottom: 1px solid #eee5d8; }}
    .focus-head {{ display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }}
    .focus-label {{ font-weight: 650; }}
    .focus-sub {{ color: #8a7a63; font-size: 13px; margin-top: 2px; }}
    .cov-row {{ display: flex; align-items: center; gap: 10px; padding: 5px 0; }}
    .cov-cat {{ width: 230px; font-weight: 650; flex-shrink: 0; }}
    .cov-name {{ font-weight: 400; color: #8a7a63; font-size: 13px; }}
    details.qb-cat, details.art-group {{ margin-bottom: 8px; border: 1px solid #e5dfd5; border-radius: 8px; overflow: hidden; background: #fffdf9; }}
    details.qb-cat > summary, details.art-group > summary {{ list-style: none; cursor: pointer; display: flex; align-items: center; gap: 12px;
      padding: 10px 14px; background: #f4f0e8; }}
    details.qb-cat > summary::-webkit-details-marker, details.art-group > summary::-webkit-details-marker {{ display: none; }}
    details.qb-cat > summary::before, details.art-group > summary::before {{ content: "\\25B8"; color: #9a8c75; font-size: 12px; flex: 0 0 auto;
      transition: transform 0.15s; }}
    details.qb-cat[open] > summary::before, details.art-group[open] > summary::before {{ transform: rotate(90deg); }}
    details.qb-cat > summary:hover, details.art-group > summary:hover {{ background: #ece5d8; }}
    .qb-cat-title, .art-group-title {{ font-weight: 650; flex: 0 0 auto; min-width: 200px; }}
    .art-group-counts {{ margin-left: auto; text-align: right; color: #8a7a63; font-size: 13px; }}
    .art-group-body {{ padding: 4px 16px 14px; }}
    .art-group-body h3 {{ margin-bottom: 2px; }}
    .rev-footer a {{ display: inline-block; padding: 0 6px; border: 1px solid #d8cdbb;
      border-radius: 4px; text-decoration: none; margin-right: 2px; }}
    .rev-footer a:hover {{ background: #ece5d8; }}
    .rev-diff ins {{ background: #dcedc8; text-decoration: none; }}
    .rev-diff del {{ background: #f8d7d5; }}
    details.qb-cat > summary .barwrap {{ flex: 1; margin: 0; }}
    .qb-list {{ list-style: none; padding: 8px 16px 12px; margin: 0; }}
    .qb-list li {{ padding: 3px 0; }}
    .qb-list .q-done {{ color: #6b5d49; }}
    .qb-list .q-mark {{ display: inline-block; width: 16px; }}
    .qb-list .q-id {{ font-weight: 650; color: #7c4f1d; margin-right: 4px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; margin: 8px 0 24px; }}
    .card {{ background: #fff; border: 1px solid #e5dfd5; border-radius: 10px; padding: 14px 16px; }}
    .card-val {{ font-size: 26px; font-weight: 700; color: #3f3428; }}
    .card-lbl {{ font-size: 13px; color: #6b5d49; }}
    .card .sub {{ font-size: 12px; color: #9a8c75; margin-top: 2px; }}
    /* Home action hub — calm invitations, never guilt metrics */
    .hub {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; margin: 18px 0 26px; }}
    .hub-card {{ background: var(--card-warm); border: 1px solid var(--line-soft); border-left: 4px solid var(--accent);
      border-radius: 10px; padding: 16px 18px 14px; display: flex; flex-direction: column; gap: 6px; }}
    .hub-kicker {{ font-size: 11px; font-weight: 700; letter-spacing: 0.8px; text-transform: uppercase; color: var(--muted-2); }}
    .hub-title {{ font-weight: 650; font-size: 16px; color: var(--ink-strong); line-height: 1.3; }}
    .hub-body {{ font-size: 14px; color: var(--ink-soft); line-height: 1.5; }}
    .hub-why {{ font-size: 12px; color: var(--muted); }}
    .hub-cta {{ margin-top: auto; padding-top: 8px; }}
    .hub-cta a {{ display: inline-block; font-size: 13px; font-weight: 600; color: var(--link); text-decoration: none;
      border: 1px solid #d8cdbb; border-radius: 6px; padding: 5px 12px; }}
    .hub-cta a:hover {{ background: var(--panel-hover); }}
    .statstrip {{ display: flex; flex-wrap: wrap; gap: 8px 26px; padding: 14px 2px 0; margin-top: 6px;
      border-top: 1px solid var(--line-soft); color: var(--muted); font-size: 13px; }}
    .statstrip b {{ color: var(--ink-mid); font-weight: 650; }}
    .home-foot {{ margin-top: 26px; font-size: 14px; color: var(--muted); }}
    #graph {{ width: 100%; height: calc(100vh - 150px); border: 1px solid #e5dfd5; border-radius: 10px; background: #fffdf9; }}
    .graph-legend {{ font-size: 13px; color: #6b5d49; margin: 6px 0 10px; }}
    .graph-legend span {{ margin-right: 14px; }}
    @media (max-width: 820px) {{ .shell {{ grid-template-columns: 1fr; }} nav {{ display: none; }} main {{ padding: 24px; }} }}
  </style>
</head>
<body>
  <header>
    <a href="/">Lifehug</a>
    <form action="/search"><input name="q" placeholder="Search"></form>
    {menu}
  </header>
  <div class="shell"><nav>{nav}</nav><main class="{main_cls}">{body}</main></div>
  <script>
    var KEY = "lifehug.expandedGroups";
    function loadExpanded() {{ try {{ return new Set(JSON.parse(localStorage.getItem(KEY)) || []); }} catch (e) {{ return new Set(); }} }}
    function toggleGroup(type) {{
      var el = document.querySelector('.sidebar-group[data-group="' + type + '"]');
      if (!el) return;
      el.classList.toggle('collapsed');
      var set = loadExpanded();
      el.classList.contains('collapsed') ? set.delete(type) : set.add(type);
      localStorage.setItem(KEY, JSON.stringify(Array.from(set)));
    }}
    // Groups render collapsed by default; re-open any the user expanded before.
    loadExpanded().forEach(function (type) {{
      var el = document.querySelector('.sidebar-group[data-group="' + type + '"]');
      if (el) el.classList.remove('collapsed');
    }});
    function toggleMenu(e) {{ if (e) e.stopPropagation(); document.getElementById('menuDropdown').classList.toggle('open'); }}
    document.addEventListener('click', function (e) {{
      var w = document.querySelector('.menu-wrap');
      var d = document.getElementById('menuDropdown');
      if (w && d && !w.contains(e.target)) d.classList.remove('open');
    }});
  </script>
</body>
</html>"""
    return doc.encode("utf-8")


# ---------------------------------------------------------------------------
# Dashboard views (hamburger menu)
#
# Read-only inspection surfaces over live state, rendered on each request so they
# always reflect the current system. Each builder returns (title, body_html,
# wide). The VIEWS registry below drives both the menu and the /views/<slug>
# routes — adding a view is one new entry. (Loop status: Loop-adjacent.)
# ---------------------------------------------------------------------------

_BADGE_COLORS = {
    "red": "#b3543f", "yellow": "#c79a2e", "green": "#3f8f4f",
    "early": "#b3543f", "developing": "#c79a2e", "ready": "#3f8f4f",
    "saturated": "#5a7d9a", "default": "#8a7a63",
}


def _ratio_color(r: float) -> str:
    if r >= 0.7:
        return "#3f8f4f"
    if r >= 0.3:
        return "#c79a2e"
    return "#b3543f"


def _bar(ratio: float, label: str = "") -> str:
    r = max(0.0, min(1.0, float(ratio)))
    pct = round(r * 100)
    lab = f'<span class="bar-label">{html.escape(label)}</span>' if label else ""
    return (f'<div class="barwrap"><div class="bar"><div class="bar-fill" '
            f'style="width:{pct}%;background:{_ratio_color(r)}"></div></div>{lab}</div>')


def _badge(text, kind: str = "default") -> str:
    color = _BADGE_COLORS.get(str(kind).lower(), _BADGE_COLORS["default"])
    return f'<span class="badge" style="background:{color}">{html.escape(str(text))}</span>'


def _empty(msg: str) -> str:
    return f'<p class="empty">{msg}</p>'


def _h2(text: str) -> str:
    return f"<h2>{html.escape(text)}</h2>"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a table. Header text is escaped; row cells are pre-rendered HTML
    (callers escape their own text)."""
    if not rows:
        return _empty("None.")
    thead = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f'<table class="dash"><thead><tr>{thead}</tr></thead><tbody>{body}</tbody></table>'


def _pct(x: float) -> str:
    return format(x, ".0%")


def view_focuses():
    roadmap = load_roadmap()
    if not roadmap.get("focuses"):
        try:
            roadmap = rebuild_roadmap(write=False)
        except Exception:
            roadmap = {"focuses": []}
    focuses = roadmap.get("focuses", [])
    if not focuses:
        return ("Focuses", "<h1>Focuses</h1>" + _empty("No focuses yet — add one with <code>lifehug focus-new</code>."), False)
    questions = parse_questions(QUESTIONS_FILE.read_text(encoding="utf-8")) if QUESTIONS_FILE.exists() else []
    rows = []
    total_answered = total_target = 0
    for focus in focuses:
        fill = focus_fill(focus, questions)
        total_answered += fill["answered"]
        total_target += fill["target"]
        tag, label = verdict(fill["saturation"])
        if fill["saturated"]:
            tag, label = "SATURATED", "well-known — maintenance"
        sat = fill["saturation"]
        lbl = html.escape(str(focus.get("label", "?")))
        node = focus.get("wiki_node")
        if node:
            lbl = f'<a href="/page/{quote(str(node))}">{lbl}</a>'
        badges = _badge(focus.get("tier", "?"))
        phase = focus.get("phase", "active")
        if phase != "active":
            badges += " " + _badge(phase)
        badges += " " + _badge(tag, tag.lower())
        meta = (html.escape(str(focus.get("objective", ""))) + " → "
                + html.escape(str(focus.get("deliverable", "-"))) + " ["
                + html.escape(",".join(focus.get("categories", []))) + "]")
        barlabel = f"{fill['answered']}/{fill['target']} · {_pct(sat)} · {label}"
        rows.append(
            '<div class="focus-row"><div class="focus-head">'
            f'<span class="focus-label">{lbl}</span> {badges}</div>'
            + _bar(sat, barlabel)
            + f'<div class="focus-sub">{meta}</div></div>'
        )
    overall = total_answered / total_target if total_target else 0
    foot = (f'<p class="muted">Overall: {total_answered}/{total_target} answered '
            f'({_pct(overall)} toward current targets)</p>')
    return ("Focuses", "<h1>Focuses</h1>" + "".join(rows) + foot, False)


def view_coverage():
    cats = (read_json(COVERAGE_FILE, default={}) or {}).get("categories", {})
    if not cats:
        return ("Coverage", "<h1>Coverage</h1>" + _empty("No coverage data yet."), False)
    names = parse_categories(QUESTIONS_FILE.read_text(encoding="utf-8")) if QUESTIONS_FILE.exists() else {}
    items = []
    for cid, c in cats.items():
        total = c.get("total", 0)
        answered = c.get("answered", 0)
        ratio = answered / total if total else 0
        name = (names.get(cid) or {}).get("name", "")
        items.append((ratio, cid, name, answered, total, c.get("status", "red")))
    items.sort(key=lambda x: x[0])
    rows = [
        '<div class="cov-row"><span class="cov-cat">'
        + html.escape(cid) + (f' <span class="cov-name">({html.escape(name)})</span>' if name else "")
        + "</span>"
        + _bar(ratio, f"{answered}/{total} · {_pct(ratio)}")
        + " " + _badge(status, status) + "</div>"
        for ratio, cid, name, answered, total, status in items
    ]
    return ("Coverage", "<h1>Coverage</h1>" + "".join(rows), False)


def view_question_bank():
    if not QUESTIONS_FILE.exists():
        return ("Question Bank", "<h1>Question Bank</h1>" + _empty("No question bank."), False)
    md = QUESTIONS_FILE.read_text(encoding="utf-8")
    questions = parse_questions(md)
    cats = parse_categories(md)
    by_cat: dict[str, list[dict]] = {}
    for q in questions:
        by_cat.setdefault(str(q["category"]), []).append(q)
    parts = ["<h1>Question Bank</h1>"]
    for cid in sorted(by_cat):
        qs = by_cat[cid]
        answered = sum(1 for q in qs if q["answered"])
        total = len(qs)
        ratio = answered / total if total else 0
        name = (cats.get(cid) or {}).get("name", "")
        head = cid + (": " + name if name else "")
        lis = []
        for q in qs:
            done = bool(q["answered"])
            mark = "✓" if done else "○"
            cls = "q-done" if done else "q-open"
            lis.append(
                f'<li class="{cls}"><span class="q-mark">{mark}</span>'
                f'<span class="q-id">{html.escape(str(q["id"]))}</span>'
                f'{html.escape(str(q["text"]))}</li>'
            )
        parts.append(
            '<details class="qb-cat"><summary>'
            f'<span class="qb-cat-title">{html.escape(head)}</span>'
            + _bar(ratio, f"{answered}/{total} · {_pct(ratio)}")
            + '</summary><ul class="qb-list">' + "".join(lis) + "</ul></details>"
        )
    return ("Question Bank", "".join(parts), False)


def view_candidates():
    cands = (read_json(QUESTION_CANDIDATES_FILE, default={}) or {}).get("candidates", [])
    if not cands:
        return ("Candidates", "<h1>Question Candidates</h1>" + _empty("No candidates yet."), False)
    # Quality is not stored on candidates — it's computed on demand by
    # check_quality (same scorer the classifier/promotion gate use). Category
    # is only stamped at review time; until then infer it from the candidate's
    # neighborhood (target_category → neighborhood topic_type → bank letter).
    neighborhoods = read_json(NEIGHBORHOODS_FILE, default={}) or {}
    cat_names = parse_categories(QUESTIONS_FILE.read_text(encoding="utf-8")) if QUESTIONS_FILE.exists() else {}
    by_status: dict[str, list[dict]] = {}
    for c in cands:
        by_status.setdefault(c.get("status", "candidate"), []).append(c)
    parts = ["<h1>Question Candidates</h1>"]
    for status in sorted(by_status):
        group = by_status[status]
        parts.append(_h2(f"{status} ({len(group)})"))
        rows = []
        for c in group:
            stored = (c.get("quality") or {}).get("score")
            try:
                score = stored if isinstance(stored, (int, float)) else \
                    check_quality(str(c.get("text", "")), source_path=c.get("source_path")).get("score")
            except Exception:
                score = None
            letter = _infer_category(c, neighborhoods)
            if letter:
                name = (cat_names.get(letter) or {}).get("name", "")
                cat_cell = html.escape(letter + (f" ({name})" if name else ""))
            else:
                cat_cell = '<span class="muted">unassigned</span>'
            rows.append([
                html.escape(str(c.get("text", ""))[:300]),
                format(c.get("priority", 0) or 0, ".2f"),
                (format(score, ".2f") if isinstance(score, (int, float)) else "—"),
                cat_cell,
                html.escape(str(c.get("story_function") or "—")),
                html.escape(str(c.get("source_path") or "—")),
            ])
        parts.append(_table(["Question", "Priority", "Quality", "Category", "Story fn", "Source"], rows))
    return ("Candidates", "".join(parts), False)


def view_entities():
    parts = ["<h1>Entity Candidates</h1>"]
    for etype in ENTITY_TYPES:
        # Only show entities still in the candidate stage — anything that has
        # graduated (page-eligible) or already maps to a Focus has a wiki page,
        # so it's visible in the wiki itself and shouldn't be repeated here.
        ents = [
            e for e in load_roster(etype).get("entities", [])
            if not e.get("page_eligible") and not e.get("maps_to_focus")
        ]
        parts.append(_h2(f"{etype.title()} ({len(ents)})"))
        if not ents:
            parts.append(_empty("No candidates — none pending graduation."))
            continue
        rows = []
        for e in sorted(ents, key=lambda x: x.get("score", 0) or 0, reverse=True):
            rows.append([
                html.escape(str(e.get("name", "?"))),
                html.escape(", ".join(e.get("aliases", []) or [])) or "—",
                format(e.get("score", 0) or 0, ".1f"),
                str(e.get("unique_answers", 0) or 0),
                ("yes" if e.get("qualifies") else "no"),
            ])
        parts.append(_table(["Name", "Aliases", "Score", "Answers", "Qualifies"], rows))
    return ("Entity Candidates", "".join(parts), False)


def loop_stats() -> dict:
    """One shared snapshot of the Loop's counters — feeds both The Loop view
    and the home page's stats strip, so the numbers can never disagree."""
    rot = read_json(ROTATION_FILE, default={}) or {}
    cov = (read_json(COVERAGE_FILE, default={}) or {}).get("categories", {})
    cands = (read_json(QUESTION_CANDIDATES_FILE, default={}) or {}).get("candidates", [])
    queue = read_json(QUESTION_QUEUE_FILE, default={}) or {}
    manifest = (read_json(SOURCE_MANIFEST_FILE, default={}) or {}).get("sources", {})
    lint = read_json(SOURCE_LINT_FINDINGS_FILE, default={}) or {}
    recs = (read_json(FOCUS_RECS_FILE, default={}) or {}).get("recommendations", [])

    total = sum(c.get("total", 0) for c in cov.values())
    answered = sum(c.get("answered", 0) for c in cov.values())
    greens = sum(1 for c in cov.values() if c.get("status") == "green")
    cand_by_status: dict[str, int] = {}
    for c in cands:
        s = c.get("status", "candidate")
        cand_by_status[s] = cand_by_status.get(s, 0) + 1
    open_cands = cand_by_status.get("candidate", 0) + cand_by_status.get("needs_review", 0)
    pending_recs = sum(1 for r in recs if r.get("status") == "pending")
    q_items = queue.get("queue", [])
    # Answered state lives in the question bank, not the queue's own status field
    # (nothing writes delivery back), so derive queue progress from the bank.
    answered_ids = ({str(q["id"]) for q in parse_questions(QUESTIONS_FILE.read_text(encoding="utf-8")) if q.get("answered")}
                    if QUESTIONS_FILE.exists() else set())
    q_answered = sum(1 for q in q_items if str(q.get("question_id", "")) in answered_ids)

    names = rot.get("pass_names") or []
    cur = rot.get("current_pass")
    pass_name = names[cur - 1] if isinstance(cur, int) and 1 <= cur <= len(names) else ""

    return {
        "pass_num": cur,
        "pass_name": pass_name,
        "questions_asked": rot.get("questions_asked", 0),
        "answered": answered,
        "total": total,
        "greens": greens,
        "open_cands": open_cands,
        "pending_recs": pending_recs,
        "sources": len(manifest),
        "lint_open": lint.get("open_count", len([f for f in lint.get("findings", []) if f.get("status", "open") == "open"])),
        "queue_answered": q_answered,
        "queue_total": len(q_items),
        "queue_expires": queue.get("expires_at"),
    }


def view_status():
    s = loop_stats()
    answered, total = s["answered"], s["total"]
    cur, pass_name = s["pass_num"], s["pass_name"]

    def card(label, value, sub=""):
        s = f'<div class="sub">{html.escape(sub)}</div>' if sub else ""
        return (f'<div class="card"><div class="card-val">{html.escape(str(value))}</div>'
                f'<div class="card-lbl">{html.escape(label)}</div>{s}</div>')

    cards = [
        card("Pass", (f"{cur} · {pass_name}" if pass_name else cur) if cur else "—"),
        card("Questions asked", s["questions_asked"]),
        card("Answered", f"{answered}/{total}", f"{_pct(answered / total if total else 0)} coverage"),
        card("Green categories", s["greens"]),
        card("Open candidates", s["open_cands"]),
        card("Sources captured", s["sources"]),
        card("Open lint findings", s["lint_open"]),
        card("Pending focus recs", s["pending_recs"]),
        card("Queue answered", f"{s['queue_answered']}/{s['queue_total']}", "expires " + str(s["queue_expires"] or "—")),
    ]
    grid = '<div class="cards">' + "".join(cards) + "</div>"
    return ("The Loop", "<h1>The Loop — System Status</h1>" + grid, False)


# ---------------------------------------------------------------------------
# Home action hub (v99)
#
# The home page answers "what should I do next?" with a few calm invitation
# cards — never a backlog, never guilt metrics. Each card grounds itself in
# real material, says why it's here now, and offers one verb. A small stats
# strip below shows state (not debt). Design notes: 3–5 cards max, at most one
# heavy introspective card, absence reads as stillness.
# ---------------------------------------------------------------------------

SECOND_VOICE_OFFERS_FILE = STATE_DIR / "second_voice_offers.json"

# Left-rule accent per invitation kind. Calm palette — no reds on the home page.
_HUB_ACCENTS = {
    "chapter": "#3f8f4f",
    "sit_with": "#5a7d9a",
    "question": "#987b55",
    "review": "#c79a2e",
    "perennial": "#7c4f1d",
    "second_voice": "#8a7a63",
    "memory": "#9a8c75",
    "quiet": "#c8c2b8",
}


def _daily_pick(n: int) -> int:
    """Stable index for today — the same pick all day, a fresh one tomorrow.
    (hash() is salted per process, so use a real digest.)"""
    today = datetime.date.today().isoformat()
    return int(hashlib.sha1(today.encode("utf-8")).hexdigest(), 16) % max(1, n)


def _invitation(kind, kicker, title, body, why="", href="", cta=""):
    return {"kind": kind, "kicker": kicker, "title": title, "body": body,
            "why": why, "href": href, "cta": cta}


def _hub_card_chapter():
    """A chapter that crossed READY and has no draft yet — the strongest verb."""
    import book as book_mod  # noqa: PLC0415
    for b in book_mod.compute_books():
        for ch in b["chapters"]:
            if ch.get("ready_to_draft") and not ch.get("has_draft"):
                depth = (f' and {ch["scene_slots_filled"]}/{ch["scene_slots_total"]} scene slots filled'
                         if ch.get("scene_slots_total") else "")
                return _invitation(
                    "chapter", "Chapter ready",
                    f'“{ch["category_name"]}” is ready to draft',
                    f'{ch["answered"]} of {ch["total"]} questions answered in '
                    f'{b.get("label", "the book")} — enough material to write from.',
                    why=f'it crossed {ch["verdict"]}{depth}',
                    href="/views/book", cta="Open the book map")
    return None


def _reflection_pool() -> list[tuple[str, str, str]]:
    """(kind, text, source) for every classifier-extracted contradiction and
    self-understanding insight — the raw material the Mirror synthesizes."""
    pool: list[tuple[str, str, str]] = []
    if not CLASSIFICATIONS_DIR.exists():
        return pool
    for path in sorted(CLASSIFICATIONS_DIR.glob("*.json")):
        data = read_json(path, default={}) or {}
        source = str(data.get("source_path", path.stem))
        for c in data.get("contradictions") or []:
            if isinstance(c, str) and c.strip():
                pool.append(("tension", c.strip(), source))
        for i in data.get("self_understanding_insights") or []:
            if isinstance(i, str) and i.strip():
                pool.append(("insight", i.strip(), source))
    return pool


def _sit_with_from_mirror() -> list[str]:
    """The synthesized Mirror's own Sit-with picks (v100), if the page exists."""
    page = WIKI_DIR / "self" / "mirror.md"
    if not page.exists():
        return []
    text = page.read_text(encoding="utf-8", errors="replace")
    if "## Sit with" not in text:
        return []
    tail = text.split("## Sit with", 1)[1].split("\n## ", 1)[0]
    return [ln.lstrip("-*0123456789. ").strip()
            for ln in tail.splitlines() if ln.strip().startswith(("-", "*", "1.", "2.", "3."))]


def _hub_card_sit_with():
    """One thing to sit with — the synthesized Mirror's pick when it exists,
    else a deterministic daily pick over the raw classifier signals. A single
    heavy card, never more."""
    picks = _sit_with_from_mirror()
    if picks:
        return _invitation(
            "sit_with", "Worth sitting with",
            "From this week's Mirror",
            picks[_daily_pick(len(picks))],
            why="distilled from your own words",
            href="/views/mirror", cta="Open the Mirror")
    pool = _reflection_pool()
    if not pool:
        return None
    kind, text, source = pool[_daily_pick(len(pool))]
    stem = Path(source).stem
    if len(text) > 320:
        text = text[:317] + "…"
    title = ("A tension worth sitting with" if kind == "tension"
             else "Something you seem to know about yourself")
    return _invitation(
        "sit_with", "Worth sitting with", title, text,
        why=f"noticed in your own words · {stem}",
        href="/views/mirror", cta="Open the Mirror")


def _hub_card_next_question():
    """The week's next unanswered planned question, ready when the author is."""
    queue = read_json(QUESTION_QUEUE_FILE, default={}) or {}
    items = queue.get("queue", [])
    if not items or not QUESTIONS_FILE.exists():
        return None
    md = QUESTIONS_FILE.read_text(encoding="utf-8")
    bank = parse_questions(md)
    text_by_id = {str(q["id"]): str(q["text"]) for q in bank}
    answered_ids = {str(q["id"]) for q in bank if q.get("answered")}
    for q in items:
        qid = str(q.get("question_id", ""))
        if qid and qid not in answered_ids:
            text = str(q.get("text") or text_by_id.get(qid, ""))
            if not text:
                continue
            why = str(q.get("reason") or q.get("story_function") or "")
            return _invitation(
                "question", "When you're ready",
                "This week's next question",
                f"[{qid}] {text}",
                why=why, href="/views/queue", cta="See the week's plan")
    return None


def _hub_card_review():
    """Candidates and focus ideas waiting for the author's eye — counts only,
    one card, never a backlog listing."""
    s = loop_stats()
    open_cands, pending_recs = s["open_cands"], s["pending_recs"]
    if not open_cands and not pending_recs:
        return None
    bits = []
    if open_cands:
        bits.append(f"{open_cands} follow-up question{'s' if open_cands != 1 else ''} "
                    "proposed from your answers")
    if pending_recs:
        bits.append(f"{pending_recs} focus idea{'s' if pending_recs != 1 else ''}")
    href = "/views/candidates" if open_cands else "/views/recommendations"
    cta = "Review candidates" if open_cands else "Review focus ideas"
    return _invitation(
        "review", "For your eye",
        "A few things wait for review",
        " · ".join(bits) + ". They stay parked until you promote them.",
        href=href, cta=cta)


def _hub_card_perennial():
    """A yearly return-and-contrast question that has come due."""
    from question_candidates import generate_due_perennials  # noqa: PLC0415
    due = generate_due_perennials(dry_run=True)
    if not due:
        return None
    _, perennial_id = due[0]
    return _invitation(
        "perennial", "A yearly return",
        f"{perennial_id} has come around again",
        "A perennial question is due — you'll answer it with last year's "
        "answer alongside, so the contrast becomes part of the story.",
        href="/views/question-bank", cta="See the question bank")


def _hub_card_second_voice():
    """This month's gentlest offer: if it comes up naturally, ask someone."""
    data = read_json(SECOND_VOICE_OFFERS_FILE, default={}) or {}
    month = datetime.date.today().strftime("%Y-%m")
    offers = [o for o in data.get("offered", [])
              if o.get("month") == month and not o.get("acknowledged_at")]
    if not offers:
        return None
    offer = offers[_daily_pick(len(offers))]
    person = str(offer.get("person", ""))
    key = str(offer.get("key", ""))
    question = key.split("::", 1)[1].replace("-", " ") if "::" in key else ""
    body = (f"If it comes up naturally, you might ask {person}: “{question}?”"
            if question else f"If it comes up naturally, ask {person} about a shared moment.")
    href = cta = ""
    person_page = WIKI_DIR / "people" / f"{slugify(person)}.md"
    if person_page.exists():
        rel = str(person_page.relative_to(WIKI_DIR.parent))
        href, cta = f"/page/{quote(rel)}", "Read their page"
    return _invitation(
        "second_voice", "If it comes up",
        f"A question for {person}",
        body + " Their answer becomes a second voice in the archive.",
        why="this month's second-voice offer — it expires silently if ignored",
        href=href, cta=cta)


def _hub_card_memory():
    """On This Day-style resurfacing: one old answer (≥90 days), verbatim-ish."""
    if not ANSWERS_DIR.exists():
        return None
    today = datetime.date.today()
    entries: list[tuple[str, Path]] = []
    for p in sorted(ANSWERS_DIR.glob("*.md")):
        try:
            head = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(r'^answered_date:\s*"?([0-9]{4}-[0-9]{2}-[0-9]{2})"?', head, re.MULTILINE)
        if not m:
            continue
        try:
            answered = datetime.date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if (today - answered).days >= 90:
            entries.append((m.group(1), p))
    if not entries:
        return None
    date_str, path = entries[_daily_pick(len(entries))]
    text = path.read_text(encoding="utf-8", errors="replace")
    parts = text.split("---")
    body = parts[-1] if len(parts) >= 3 else text
    body = re.sub(r"^#.*$", "", body, flags=re.MULTILINE)
    body = " ".join(body.split())
    excerpt = body[:260] + ("…" if len(body) > 260 else "")
    return _invitation(
        "memory", "From your archive",
        f"You wrote this on {date_str}",
        f"“{excerpt}”",
        why=f"answer {path.stem}, resurfaced",
        href=f"/search?q={quote(path.stem)}", cta="Find it in the wiki")


def home_data() -> dict:
    """Assemble the home hub: up to 4 priority invitations + the standing
    memory slot. Every builder is failure-wrapped — one broken card must never
    take down the front page."""
    builders = [_hub_card_chapter, _hub_card_sit_with, _hub_card_next_question,
                _hub_card_review, _hub_card_perennial, _hub_card_second_voice]
    cards = []
    for fn in builders:
        if len(cards) >= 4:
            break
        try:
            card = fn()
        except Exception:  # noqa: BLE001 — a broken loader is that card's problem only
            card = None
        if card:
            cards.append(card)
    try:
        memory = _hub_card_memory()
    except Exception:  # noqa: BLE001
        memory = None
    if memory:
        cards.append(memory)
    try:
        stats = loop_stats()
    except Exception:  # noqa: BLE001
        stats = {}
    return {"invitations": cards, "stats": stats}


def _hub_card_html(card: dict) -> str:
    accent = _HUB_ACCENTS.get(card["kind"], _HUB_ACCENTS["quiet"])
    why = f'<div class="hub-why">{html.escape(card["why"])}</div>' if card.get("why") else ""
    cta = ""
    if card.get("href") and card.get("cta"):
        cta = (f'<div class="hub-cta"><a href="{html.escape(card["href"])}">'
               f'{html.escape(card["cta"])}</a></div>')
    return (f'<div class="hub-card" style="border-left-color:{accent}">'
            f'<div class="hub-kicker">{html.escape(card["kicker"])}</div>'
            f'<div class="hub-title">{html.escape(card["title"])}</div>'
            f'<div class="hub-body">{html.escape(card["body"])}</div>'
            f"{why}{cta}</div>")


def view_home():
    """The home page: a few invitations, then a quiet strip of state."""
    data = home_data()
    cards = data["invitations"]
    if not cards:
        cards = [_invitation(
            "quiet", "All quiet",
            "The loop is fed",
            "Nothing waits on you right now. Wander the wiki, or just live "
            "some more life — the questions will find you.")]
    s = data["stats"]
    strip = ""
    if s:
        total, answered = s.get("total", 0), s.get("answered", 0)
        pieces = [
            f"<span><b>{answered}</b> of <b>{total}</b> answered</span>",
            f"<span><b>{_pct(answered / total if total else 0)}</b> coverage</span>",
            f"<span><b>{s.get('sources', 0)}</b> sources</span>",
            f"<span><b>{s.get('greens', 0)}</b> green categories</span>",
        ]
        if s.get("queue_total"):
            pieces.append(f"<span>queue <b>{s['queue_answered']}/{s['queue_total']}</b></span>")
        strip = '<div class="statstrip">' + "".join(pieces) + "</div>"
    body = (
        "<h1>Today</h1>"
        '<p class="view-desc">A few invitations, ready when you are.</p>'
        '<div class="hub">' + "".join(_hub_card_html(c) for c in cards) + "</div>"
        + strip
        + '<p class="home-foot">Browsing instead? The compiled wiki lives in the '
          'sidebar — or start at the <a href="/page/wiki/index.md">index</a>.</p>'
    )
    return ("Today", body, False)


def view_mirror():
    """The Mirror (v100): this week's synthesized introspection edition on top,
    the raw classifier signals browsable beneath. A cadenced edition, not a
    live profile — synthesis happens weekly, not on page load."""
    parts = ["<h1>Mirror</h1>"]
    page = WIKI_DIR / "self" / "mirror.md"
    if page.exists():
        text = page.read_text(encoding="utf-8", errors="replace")
        generated = page_field(page, "generated_at")
        if generated:
            parts.append(f'<p class="muted">This week\'s edition · generated {html.escape(generated)}</p>')
        body_html = render_markdown(text)
        # The page carries its own "# Mirror" title; drop the duplicate h1.
        body_html = body_html.replace("<h1>Mirror</h1>", "", 1)
        parts.append(body_html)
    else:
        parts.append(_empty(
            "No Mirror edition yet. The weekly maintenance synthesizes one from "
            "your classified answers — or run "
            "<code>python3 system/lifehug.py mirror-compile</code> now."))

    # Raw feed beneath the synthesis — every signal, with its source.
    try:
        import mirror as mirror_mod  # noqa: PLC0415
        entries = mirror_mod.load_mirror_entries()
    except Exception:  # noqa: BLE001
        entries = []
    if entries:
        parts.append(_h2("The raw signals"))
        parts.append('<p class="muted">Everything the classifier has noticed, unsynthesized. '
                     'Each line cites the source it came from.</p>')
        groups = [("contradiction", "Tensions"), ("insight", "Insights"),
                  ("position", "Stated positions")]
        for kind, label in groups:
            rows = [e for e in entries if e["kind"] == kind]
            if not rows:
                continue
            items = "".join(
                f'<li>{html.escape(e["text"])} '
                f'<span class="muted">· {html.escape(e["source_short"])}</span></li>'
                for e in rows)
            parts.append(
                f'<details class="qb-cat"><summary>'
                f'<span class="qb-cat-title">{html.escape(label)}</span>'
                f'<span class="art-group-counts">{len(rows)}</span></summary>'
                f'<ul class="qb-list">{items}</ul></details>')
    return ("Mirror", "".join(parts), False)


def view_queue():
    queue = read_json(QUESTION_QUEUE_FILE, default={}) or {}
    items = queue.get("queue", [])
    if not items:
        return ("Question Queue", "<h1>Question Queue</h1>" + _empty("No active queue. Build one with <code>lifehug planner-queue</code>."), False)
    # Queue items store only the question id + category letter — resolve the
    # human-readable question text, category name, and (crucially) the real
    # answered state from the question bank, which is the source of truth. The
    # queue's own status field only tracks delivery, and nothing writes it back
    # on answer, so a queued question you've answered would otherwise still read
    # "queued". Deriving from the bank keeps the view honest.
    md = QUESTIONS_FILE.read_text(encoding="utf-8") if QUESTIONS_FILE.exists() else ""
    bank = parse_questions(md) if md else []
    text_by_id = {str(q["id"]): str(q["text"]) for q in bank}
    answered_ids = {str(q["id"]) for q in bank if q.get("answered")}
    cat_names = parse_categories(md) if md else {}
    done = sum(1 for q in items if str(q.get("question_id", "")) in answered_ids)
    total = len(items)
    remaining = total - done
    progress = _bar(done / total if total else 0,
                    f"{done} of {total} answered · {remaining} remaining")
    head = (progress + f'<p class="muted">Generated {html.escape(str(queue.get("generated_at", "?")))} · '
            f'expires {html.escape(str(queue.get("expires_at", "?")))}</p>')
    rows = []
    for q in items:
        qid = str(q.get("question_id", ""))
        letter = str(q.get("category", ""))
        name = (cat_names.get(letter) or {}).get("name", "")
        cat_cell = html.escape(letter + (f" ({name})" if name else ""))
        text = str(q.get("text") or text_by_id.get(qid, ""))
        if qid in answered_ids:
            status = _badge("answered", "green")
        elif q.get("status") == "delivered" or q.get("delivered_at"):
            status = _badge("delivered", "saturated")
        else:
            status = _badge("queued", "yellow")
        rows.append([
            html.escape(qid),
            cat_cell,
            html.escape(text[:300]) or '<span class="muted">—</span>',
            html.escape(str(q.get("story_function") or q.get("reason") or "—")),
            status,
        ])
    return ("Question Queue", "<h1>Question Queue</h1>" + head + _table(["ID", "Category", "Question", "Why", "Status"], rows), False)


def view_sources():
    manifest = (read_json(SOURCE_MANIFEST_FILE, default={}) or {}).get("sources", {})
    findings = (read_json(SOURCE_LINT_FINDINGS_FILE, default={}) or {}).get("findings", [])
    parts = ["<h1>Source Integrity</h1>"]
    open_findings = [f for f in findings if f.get("status", "open") == "open"]
    parts.append(_h2(f"Open lint findings ({len(open_findings)})"))
    if open_findings:
        rows = [[
            _badge(f.get("severity", "?"), "red" if f.get("severity") == "error" else "yellow"),
            html.escape(str(f.get("type", ""))),
            html.escape(str(f.get("path", ""))),
            html.escape(str(f.get("message", ""))),
            html.escape(str(f.get("fixability", ""))),
        ] for f in open_findings]
        parts.append(_table(["Sev", "Type", "Path", "Message", "Fix"], rows))
    else:
        parts.append(_empty("No open findings."))
    by_type: dict[str, list[dict]] = {}
    for s in manifest.values():
        by_type.setdefault(s.get("type", "unknown"), []).append(s)
    parts.append(_h2(f"Captured sources ({len(manifest)})"))
    if not manifest:
        parts.append(_empty("No sources tracked yet."))
    for t in sorted(by_type):
        parts.append(f"<h3>{html.escape(t)} ({len(by_type[t])})</h3>")
        rows = [[
            html.escape(str(s.get("title", s.get("source_id", "?")))),
            html.escape(str(s.get("captured_at") or s.get("first_seen_at") or "—")),
            html.escape(str(s.get("source_medium", "—"))),
            _badge("changed", "yellow") if s.get("changed_since_first_seen") else _badge("stable", "green"),
        ] for s in by_type[t]]
        parts.append(_table(["Title", "Captured", "Medium", "Integrity"], rows))
    return ("Source Integrity", "".join(parts), False)


def view_recommendations():
    data = read_json(FOCUS_RECS_FILE, default={}) or {}
    recs = data.get("recommendations", [])
    dismissed = data.get("dismissed", [])
    pending = [r for r in recs if r.get("status") == "pending"]
    others = [r for r in recs if r.get("status") != "pending"]
    parts = ["<h1>Focus Recommendations</h1>"]
    parts.append(_h2(f"Pending ({len(pending)})"))
    if pending:
        rows = [[
            html.escape(str(r.get("entity", "?"))),
            html.escape(str(r.get("type", "?"))),
            format(r.get("score", 0) or 0, ".1f"),
            html.escape(str(r.get("evidence_strength", "—"))),
            str(r.get("mention_count", 0)),
            html.escape(",".join(r.get("cross_categories", []))),
            html.escape(str(r.get("reason", ""))[:240]),
        ] for r in sorted(pending, key=lambda r: r.get("score", 0) or 0, reverse=True)]
        parts.append(_table(["Entity", "Type", "Score", "Evidence", "Mentions", "Cats", "Reason"], rows))
    else:
        parts.append(_empty("No pending recommendations."))
    if others:
        parts.append(_h2(f"Acted on ({len(others)})"))
        parts.append(_table(["Entity", "Status"],
                            [[html.escape(str(r.get("entity", "?"))), html.escape(str(r.get("status", "?")))] for r in others]))
    if dismissed:
        parts.append(_h2(f"Dismissed ({len(dismissed)})"))
        parts.append(_table(["Entity", "Reason"],
                            [[html.escape(str(r.get("entity", "?"))), html.escape(str(r.get("dismiss_reason", "")))] for r in dismissed]))
    return ("Focus Recommendations", "".join(parts), False)


# --- Graph view -------------------------------------------------------------

def _frontmatter_block(text: str) -> str:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    return m.group(1) if m else ""


def _fm_list(fm: str, key: str) -> list[str]:
    """Parse a simple YAML list (`key:` followed by `  - "..."` lines)."""
    out: list[str] = []
    m = re.search(rf"^{re.escape(key)}:\s*\n((?:[ \t]+-.*\n?)+)", fm, re.MULTILINE)
    if not m:
        return out
    for line in m.group(1).splitlines():
        item = line.strip()
        if item.startswith("-"):
            item = item[1:].strip().strip('"').strip("'")
            item = item.strip("[]")  # [[slug]] → slug
            if item:
                out.append(item)
    return out


def graph_data() -> dict:
    """Build the entity graph from compiled wiki pages: nodes = pages (sized by
    sources_count, colored by focus saturation where known), edges = related
    links weighted by shared sources."""
    sat_by_path: dict[str, float] = {}
    try:
        questions = parse_questions(QUESTIONS_FILE.read_text(encoding="utf-8")) if QUESTIONS_FILE.exists() else []
        for f in load_roadmap().get("focuses", []):
            node = f.get("wiki_node")
            if node:
                sat_by_path[node] = focus_fill(f, questions)["saturation"]
    except Exception:
        pass

    nodes = []
    slug_to_id: dict[str, str] = {}
    sources_by_id: dict[str, set] = {}
    related_by_id: dict[str, list[str]] = {}
    for p in wiki_pages():
        if p.parent == WIKI_DIR:
            continue  # skip index/log/schema
        text = p.read_text(encoding="utf-8", errors="replace")
        fm = _frontmatter_block(text)
        rel = str(p.relative_to(WIKI_DIR.parent))
        try:
            sc = int(page_field(p, "sources_count") or 0)
        except ValueError:
            sc = 0
        node = {"id": rel, "label": page_title(p), "type": p.parent.name, "sources": sc}
        sat = sat_by_path.get(rel)
        if sat is not None:
            node["sat"] = round(sat, 3)
        nodes.append(node)
        slug_to_id[p.stem] = rel
        sources_by_id[rel] = set(_fm_list(fm, "sources"))
        related_by_id[rel] = [slugify(r) for r in _fm_list(fm, "related")]

    edges = []
    seen = set()
    for nid, related in related_by_id.items():
        for rslug in related:
            tgt = slug_to_id.get(rslug)
            if not tgt or tgt == nid:
                continue
            key = tuple(sorted([nid, tgt]))
            if key in seen:
                continue
            seen.add(key)
            shared = len(sources_by_id.get(nid, set()) & sources_by_id.get(tgt, set()))
            edges.append({"source": nid, "target": tgt, "weight": 1 + shared})
    return {"nodes": nodes, "edges": edges}


_GRAPH_HTML = """<h1>Graph</h1>
<div class="graph-legend">
  <span>Node size = sources feeding the page</span>
  <span>Fill = focus saturation (red→green) or entity type</span>
  <span>Edge width = shared-source strength</span>
  <span style="color:#9a8c75">Click a node to open its page</span>
</div>
<svg id="graph"></svg>
<script>
(function () {
  var TYPE_COLORS = {
    people: '#7c4f1d', relationships: '#9a6b3f', themes: '#5a7d9a', projects: '#3f8f6a',
    places: '#8a7a3f', periods: '#6b5d49', self: '#9a5a7a', lifes_work: '#3f6f8f',
    objects: '#8f6f3f', life: '#7c4f1d'
  };
  function satColor(s) { return s >= 0.7 ? '#3f8f4f' : (s >= 0.3 ? '#c79a2e' : '#b3543f'); }
  var svg = document.getElementById('graph');
  var NS = 'http://www.w3.org/2000/svg';

  fetch('/views/graph.json').then(function (r) { return r.json(); }).then(function (data) {
    var nodes = data.nodes, edges = data.edges;
    if (!nodes.length) { svg.outerHTML = '<p class="empty">No compiled pages yet. Run <code>lifehug compile</code>.</p>'; return; }
    var rect = svg.getBoundingClientRect();
    var W = rect.width || 900, H = rect.height || 600;
    var byId = {};
    nodes.forEach(function (n, i) {
      n.r = 7 + Math.sqrt(n.sources || 0) * 4;
      n.x = W / 2 + Math.cos(i) * 180 + (i % 7) * 12;
      n.y = H / 2 + Math.sin(i) * 180 + (i % 5) * 12;
      n.vx = 0; n.vy = 0;
      n.fill = (n.sat != null) ? satColor(n.sat) : (TYPE_COLORS[n.type] || '#8a7a63');
      byId[n.id] = n;
    });
    edges = edges.filter(function (e) { return byId[e.source] && byId[e.target]; });

    // Simple force simulation: repulsion + link springs + centering.
    var K_REP = 5200, K_SPRING = 0.02, LINK_LEN = 90, CENTER = 0.015, DAMP = 0.86;
    function tick() {
      for (var i = 0; i < nodes.length; i++) {
        var a = nodes[i];
        for (var j = i + 1; j < nodes.length; j++) {
          var b = nodes[j];
          var dx = a.x - b.x, dy = a.y - b.y;
          var d2 = dx * dx + dy * dy || 0.01;
          var d = Math.sqrt(d2);
          var f = K_REP / d2;
          var fx = f * dx / d, fy = f * dy / d;
          a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
        }
      }
      edges.forEach(function (e) {
        var a = byId[e.source], b = byId[e.target];
        var dx = b.x - a.x, dy = b.y - a.y;
        var d = Math.sqrt(dx * dx + dy * dy) || 0.01;
        var f = K_SPRING * (d - LINK_LEN);
        var fx = f * dx / d, fy = f * dy / d;
        a.vx += fx; a.vy += fy; b.vx -= fx; b.vy -= fy;
      });
      nodes.forEach(function (n) {
        n.vx += (W / 2 - n.x) * CENTER; n.vy += (H / 2 - n.y) * CENTER;
        n.vx *= DAMP; n.vy *= DAMP;
        n.x += n.vx; n.y += n.vy;
        n.x = Math.max(n.r, Math.min(W - n.r, n.x));
        n.y = Math.max(n.r, Math.min(H - n.r, n.y));
      });
    }
    for (var s = 0; s < 320; s++) tick();

    function el(name, attrs) {
      var e = document.createElementNS(NS, name);
      for (var k in attrs) e.setAttribute(k, attrs[k]);
      return e;
    }
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    edges.forEach(function (e) {
      var a = byId[e.source], b = byId[e.target];
      svg.appendChild(el('line', { x1: a.x, y1: a.y, x2: b.x, y2: b.y,
        stroke: '#d8cdb8', 'stroke-width': Math.min(6, e.weight) }));
    });
    nodes.forEach(function (n) {
      var g = el('g', { cursor: 'pointer' });
      g.appendChild(el('circle', { cx: n.x, cy: n.y, r: n.r, fill: n.fill,
        stroke: '#fff', 'stroke-width': 1.5 }));
      var t = el('text', { x: n.x, y: n.y - n.r - 4, 'text-anchor': 'middle',
        'font-size': 11, fill: '#3f3428' });
      t.textContent = n.label;
      g.appendChild(t);
      g.addEventListener('click', function () { window.location = '/page/' + encodeURI(n.id); });
      svg.appendChild(g);
    });
  }).catch(function (err) {
    svg.outerHTML = '<p class="empty">Could not load graph: ' + err + '</p>';
  });
})();
</script>"""


def view_graph():
    return ("Graph", _GRAPH_HTML, True)


_TIMELINE_CSS = """<style>
.tl { position: relative; margin: 1.5em 0 2em 0; padding-left: 34px; }
.tl::before { content: ""; position: absolute; left: 11px; top: 0; bottom: 0;
  width: 2px; background: #987b55; opacity: .55; }
.tl-period { display: block; position: relative; margin: 0 0 10px 0; }
.tl-period[open] { margin-bottom: 2.2em; }
.tl-period > summary::after { content: ""; position: absolute; left: -30px; top: 12px;
  width: 16px; height: 16px; border-radius: 50%; background: #6b5d49;
  border: 3px solid #fbfaf7; box-shadow: 0 0 0 2px #6b5d49; }
.tl-period h2 { margin: 0 0 .1em 0; }
.tl-period > summary, .tl-unplaced > summary { cursor: pointer; list-style: none;
  position: relative; display: flex; align-items: center; flex-wrap: wrap;
  gap: 10px; padding: 10px 14px; background: #f4f0e8;
  border: 1px solid #e5dfd5; border-radius: 8px; }
.tl-period > summary:hover, .tl-unplaced > summary:hover { background: #ece5d8; }
.tl-period > summary::-webkit-details-marker,
.tl-unplaced > summary::-webkit-details-marker { display: none; }
.tl-period > summary::before, .tl-unplaced > summary::before { content: "▸";
  color: #9a8c75; font-size: 12px; flex: 0 0 auto; transition: transform .15s; }
.tl-period[open] > summary::before, .tl-unplaced[open] > summary::before {
  transform: rotate(90deg); }
.tl-period > summary h2, .tl-unplaced > summary h2 { display: inline;
  margin: 0; font-size: 1.05em; font-weight: 650; }
.tl-period[open] > summary { margin-bottom: .5em; }
.tl-summary-counts { margin-left: auto; text-align: right; }
.tl-chapterband { display: inline-block; margin-left: .6em; padding: .1em .6em;
  border: 1px dashed #987b55; border-radius: 12px; color: #7c4f1d;
  font-size: .82em; background: #f8f3ea; }
.tl-dot { position: relative; margin: .55em 0 .55em 6px; padding: .45em .7em;
  background: #fff; border: 1px solid #e5dfd5; border-radius: 8px; }
.tl-dot::before { content: ""; position: absolute; left: -29px; top: .85em;
  width: 9px; height: 9px; border-radius: 50%; background: var(--dotc, #8a7a63); }
.tl-dot.undated::before { background: #fff; border: 2px dashed #9a8c75;
  width: 7px; height: 7px; }
.tl-evidence { color: #8a7a63; font-size: .82em; }
.tl-gap { margin: .55em 0 .55em 6px; padding: .5em .7em; border-radius: 8px;
  background: #f6ecd9; border: 1px solid #d8c193; color: #8a6d3b; font-size: .9em; }
.tl-chips { margin: .3em 0 .3em 6px; }
.tl-chip { display: inline-block; margin: .15em .25em .15em 0; padding: .12em .55em;
  border-radius: 10px; font-size: .82em; background: #f4f0e8;
  border: 1px solid #e5dfd5; }
.tl-unplaced { display: block; margin-top: 2em; padding: 0;
  border: 1px dashed #d8c193; border-radius: 10px; background: #fdf9f0; }
.tl-unplaced[open] { padding-bottom: .6em; }
.tl-unplaced > summary { background: #f6ecd9; border: none; border-radius: 9px; }
.tl-unplaced[open] > summary { border-radius: 9px 9px 0 0; margin-bottom: .3em; }
.tl-unplaced > .tl-dot, .tl-unplaced > .tl-chips { margin-left: 14px;
  margin-right: 14px; }
.tl-foot { margin-top: 2em; color: #8a7a63; font-size: .88em;
  border-top: 1px solid #e5dfd5; padding-top: .8em; }
</style>"""

_TL_TYPE_COLORS = {"person": "#7c4f1d", "place": "#8a7a3f",
                   "object": "#8f6f3f", "project": "#3f8f6a"}


def view_timeline():
    """Timeline view (v79, #33) — the life graph projected onto time.

    Vertical spine of chrono-ordered periods; entities lined up by SOURCE
    OVERLAP (the shared source ids are shown as evidence); classifier events
    as dated/undated dots; the owner's Life Chapters as a parallel band; gaps
    rendered as first-class amber cards. Everything is a validation surface —
    wrong placements are feedback, not failures."""
    try:
        import timeline as tl_mod  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return ("Timeline", f"<h1>Timeline</h1>{_empty(f'timeline module unavailable: {html.escape(str(exc))}')}", False)

    data = tl_mod.timeline_data()
    periods = data["periods"]
    if not periods:
        return ("Timeline", "<h1>Timeline</h1>" + _empty(
            "No period pages yet — periods graduate from mentions as answers "
            "accumulate, and the timeline builds itself from them."), False)

    index = page_index()

    def link(title, page_rel=None, slug=None):
        target = page_rel or (index.get(slug) if slug else None)
        if target:
            return f'<a href="/page/{quote(target)}">{html.escape(title)}</a>'
        return f'<a href="/search?q={quote(title)}">{html.escape(title)}</a>'

    counts = data["counts"]
    parts = [_TIMELINE_CSS, "<h1>Timeline</h1>",
             f"<p class='muted'>{counts['periods']} periods · "
             f"{counts['entities_placed']} entities lined up · "
             f"{counts['events_placed']} moments placed"
             + (f" · {counts['events_unplaced'] + counts['entities_unplaced']} unplaced" 
                if (counts['events_unplaced'] or counts['entities_unplaced']) else "")
             + "</p>",
             "<p class='tl-evidence'>"
             "<a href='#' onclick=\"document.querySelectorAll('details.tl-period,details.tl-unplaced')"
             ".forEach(d=>d.open=true);return false\">expand all</a> · "
             "<a href='#' onclick=\"document.querySelectorAll('details.tl-period,details.tl-unplaced')"
             ".forEach(d=>d.open=false);return false\">collapse all</a></p>",
             "<div class='tl'>"]

    for period in periods:
        slug = period["slug"]
        title_html = link(period["name"], page_rel=period.get("page"))
        bands = "".join(
            f"<span class='tl-chapterband'>Ch.{c['number']} “{html.escape(c['title'])}”</span>"
            for c in data["chapters_by_period"].get(slug, []))
        chrono_note = "" if period["chrono"] is not None else             " (no chronological order yet)"

        # Collapsed-row counts — the period stays informative while folded.
        rows = data["entity_lineup"].get(slug, [])
        events_here = data["event_lineup"].get(slug, [])
        period_gaps = data["gaps_by_period"].get(slug, [])
        summary_bits = [f"{len(period['sources'])} source(s)"]
        if rows:
            summary_bits.append(f"{len(rows)} connection(s)")
        if events_here:
            summary_bits.append(f"{len(events_here)} moment(s)")
        if period_gaps:
            summary_bits.append(f"◌ {len(period_gaps)} gap(s)")
        parts.append(f"<details class='tl-period'><summary><h2>{title_html}{bands}</h2>"
                     f"<span class='tl-evidence tl-summary-counts'>"
                     f"{' · '.join(summary_bits)}{chrono_note}</span></summary>")

        # Entity chips — the graph lined up against this period.
        if rows:
            chips = []
            for row in rows:
                color = _TL_TYPE_COLORS.get(row["type"], "#8a7a63")
                also = (f" <span class='tl-evidence'>also: "
                        f"{', '.join(html.escape(a) for a in row['also_in'])}</span>"
                        if row["also_in"] else "")
                evidence = ", ".join(row["evidence"][:4])
                chips.append(
                    f"<span class='tl-chip' style='border-left:3px solid {color}'>"
                    f"{link(row['title'], page_rel=row['page'])}"
                    f" <span class='tl-evidence'>({html.escape(evidence)})</span>{also}</span>")
            parts.append(f"<div class='tl-chips'>{''.join(chips)}</div>")

        # Event dots — dated first (the loader sorts undated last); beyond a
        # visible cap the rest collapse so a rich period stays scannable.
        def _event_html(event):
            undated = "" if event["when_hint"] else " undated"
            when = (f"<strong>{html.escape(event['when_hint'])}</strong> — "
                    if event["when_hint"] else "<em>(undated)</em> — ")
            anchor = (f" <span class='tl-evidence'>· anchor: {html.escape(event['anchor'])}</span>"
                      if event["anchor"] else "")
            return (f"<div class='tl-dot{undated}'>{when}{html.escape(event['description'])}{anchor}"
                    f"<div class='tl-evidence'>source: {html.escape(event['source_short'])}</div></div>")

        visible, overflow = events_here[:10], events_here[10:]
        parts.extend(_event_html(e) for e in visible)
        if overflow:
            parts.append(f"<details><summary class='tl-evidence'>+ {len(overflow)} more moment(s)</summary>"
                         + "".join(_event_html(e) for e in overflow) + "</details>")

        # Gap cards for this period.
        for gap in period_gaps:
            hint = f" <span class='tl-evidence'>{html.escape(gap['hint'])}</span>" if gap.get("hint") else ""
            parts.append(f"<div class='tl-gap'>◌ {html.escape(gap['message'])}{hint}</div>")

        parts.append("</details>")
    parts.append("</div>")

    # Unplaced bucket — never force what can't be proven.
    if data["unplaced_events"] or data["unplaced_entities"]:
        unplaced_bits = []
        if data["unplaced_events"]:
            unplaced_bits.append(f"{len(data['unplaced_events'])} moment(s)")
        if data["unplaced_entities"]:
            unplaced_bits.append(f"{len(data['unplaced_entities'])} connection(s)")
        parts.append("<details class='tl-unplaced'><summary>"
                     "<h2>Unplaced — tell me where these belong</h2>"
                     f"<span class='tl-evidence tl-summary-counts'>"
                     f"{' · '.join(unplaced_bits)}</span></summary>")
        for event in data["unplaced_events"]:
            when = f"<strong>{html.escape(event['when_hint'])}</strong> — " if event["when_hint"] else ""
            parts.append(f"<div class='tl-dot undated' style='margin-left:0'>{when}"
                         f"{html.escape(event['description'])}"
                         f"<div class='tl-evidence'>source: {html.escape(event['source_short'])}</div></div>")
        if data["unplaced_entities"]:
            chips = "".join(
                f"<span class='tl-chip'>{link(row['title'], page_rel=row['page'])}</span>"
                for row in data["unplaced_entities"])
            parts.append(f"<div class='tl-chips'>{chips}</div>")
        parts.append("</details>")

    for gap in data["global_gaps"]:
        hint = f" <span class='tl-evidence'>{html.escape(gap['hint'])}</span>" if gap.get("hint") else ""
        parts.append(f"<div class='tl-gap'>◌ {html.escape(gap['message'])}{hint}</div>")

    parts.append(
        "<div class='tl-foot'>This is what I currently understand of your chronology — "
        "placements are proven by shared sources (shown in parentheses), never guessed. "
        "See something wrong? <code>lifehug.py fix &lt;source&gt; --wrong … --right …</code> "
        "or just tell the bot. Dates arrive as answers are classified — always your own "
        "time-words and landmark anchors, never inferred years.</div>")

    return "Timeline", "".join(parts), False


# Binary sidecar files inside an outputs/ folder that the viewer will link and
# serve (via /artifact-file/); anything else stays invisible.
ARTIFACT_ASSET_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
}

# Format id -> the phrase used after an occasion ("Mother's Day letter").
_FORMAT_PHRASES = {
    "letter": "letter",
    "unsent_letter": "unsent letter",
    "legacy_letter": "legacy letter",
    "tweet": "tweet",
    "instagram": "Instagram caption",
    "post": "post",
    "chapter": "chapter draft",
}


def _artifact_title(slug: str, fmt: str, occasion: str) -> str:
    """Human title: '<Occasion> <format phrase>' when an occasion is known,
    else the de-slugged folder name ('my-katie' -> 'My Katie')."""
    if occasion:
        return f"{occasion} {_FORMAT_PHRASES.get(fmt, fmt or 'piece')}"
    return " ".join(w.capitalize() for w in slug.split("-"))


def _artifact_output_dir(slug: str):
    """Resolve outputs/<slug> with the same traversal guards as /artifact-file/
    (v98). Returns the directory Path or None when the slug doesn't resolve."""
    from lifehug_core import REPO_DIR as _REPO  # noqa: PLC0415

    rel = Path(slug)
    if not slug or rel.is_absolute() or ".." in rel.parts or len(rel.parts) != 1:
        return None
    outputs_root = (_REPO / "outputs").resolve()
    target = _REPO / "outputs" / rel
    if not target.is_dir() or outputs_root not in target.resolve().parents:
        return None
    return target


def _artifact_version_numbers(art_dir) -> list[int]:
    import re as _re

    numbers = []
    for path in art_dir.glob("v*.md"):
        m = _re.match(r"^v(\d+)$", path.stem)
        if m:
            numbers.append(int(m.group(1)))
    return sorted(numbers)


def _artifact_version_meta(art_dir) -> tuple[dict, int | None]:
    """{version_number: entry} from artifact.json versions[], plus final_version."""
    data = read_json(art_dir / "artifact.json", default={}) or {}
    meta = {}
    for entry in data.get("versions", []) or []:
        try:
            meta[int(entry.get("version"))] = entry
        except (TypeError, ValueError):
            continue
    final = data.get("final_version")
    try:
        final = int(final) if final is not None else None
    except (TypeError, ValueError):
        final = None
    return meta, final


def artifact_version_html(slug: str, n: str):
    """(title, body) for one saved revision of an artifact, or None when the
    request doesn't resolve (bad slug, non-numeric n, missing vN.md)."""
    if not str(n).isdigit():
        return None
    number = int(n)
    art_dir = _artifact_output_dir(slug)
    if art_dir is None:
        return None
    path = art_dir / f"v{number}.md"
    if not path.is_file():
        return None
    meta, final = _artifact_version_meta(art_dir)
    numbers = _artifact_version_numbers(art_dir)
    entry = meta.get(number, {})
    title = _artifact_title(slug, "", "")
    star = " ★ final" if final == number else ""

    nav = ['<a href="/views/artifacts">← Artifacts</a>']
    if number - 1 in numbers:
        nav.append(f'<a href="/artifact-version/{quote(slug)}/{number - 1}">← v{number - 1}</a>')
        nav.append(f'<a href="/artifact-diff/{quote(slug)}/{number - 1}/{number}">Δ what changed in v{number}</a>')
    if number + 1 in numbers:
        nav.append(f'<a href="/artifact-version/{quote(slug)}/{number + 1}">v{number + 1} →</a>')
    bits = [str(entry.get("created_at", ""))[:10], str(entry.get("model", ""))]
    detail = " · ".join(b for b in bits if b)

    body = [f"<h1>{html.escape(title)} — v{number}{star}</h1>",
            f"<p><small>{' · '.join(nav)}{' · ' + html.escape(detail) if detail else ''}</small></p>"]
    if entry.get("feedback"):
        body.append(f"<p><small>Revision note: {html.escape(str(entry['feedback']))}</small></p>")
    body.append(f"<blockquote>{render_markdown(path.read_text(errors='replace'))}</blockquote>")
    return f"{title} — v{number}", "".join(body)


def _word_diff_html(old: str, new: str) -> tuple[str, int, int]:
    """Word-level diff as <ins>/<del> HTML plus (words_added, words_removed).
    Paragraph breaks are diffed as tokens so structure survives."""
    import difflib
    import re as _re

    def tokens(text):
        return _re.findall(r"\n{2,}|\S+", text)

    def rendered(chunk):
        return " ".join("<br><br>" if t.startswith("\n") else html.escape(t) for t in chunk)

    old_tokens, new_tokens = tokens(old), tokens(new)
    matcher = difflib.SequenceMatcher(a=old_tokens, b=new_tokens, autojunk=False)
    parts, added, removed = [], 0, 0
    for op, a1, a2, b1, b2 in matcher.get_opcodes():
        if op == "equal":
            parts.append(rendered(old_tokens[a1:a2]))
            continue
        if op in ("delete", "replace") and a2 > a1:
            parts.append(f"<del>{rendered(old_tokens[a1:a2])}</del>")
            removed += sum(1 for t in old_tokens[a1:a2] if not t.startswith("\n"))
        if op in ("insert", "replace") and b2 > b1:
            parts.append(f"<ins>{rendered(new_tokens[b1:b2])}</ins>")
            added += sum(1 for t in new_tokens[b1:b2] if not t.startswith("\n"))
    return " ".join(parts), added, removed


def artifact_diff_html(slug: str, a: str, b: str):
    """(title, body) comparing two revisions of an artifact, or None when the
    request doesn't resolve."""
    if not (str(a).isdigit() and str(b).isdigit()):
        return None
    va, vb = int(a), int(b)
    art_dir = _artifact_output_dir(slug)
    if art_dir is None:
        return None
    path_a, path_b = art_dir / f"v{va}.md", art_dir / f"v{vb}.md"
    if not (path_a.is_file() and path_b.is_file()):
        return None
    meta, _final = _artifact_version_meta(art_dir)
    title = _artifact_title(slug, "", "")
    diff, added, removed = _word_diff_html(path_a.read_text(errors="replace"),
                                           path_b.read_text(errors="replace"))
    nav = ['<a href="/views/artifacts">← Artifacts</a>',
           f'<a href="/artifact-version/{quote(slug)}/{va}">v{va}</a>',
           f'<a href="/artifact-version/{quote(slug)}/{vb}">v{vb}</a>',
           f"{added} word(s) added", f"{removed} removed"]
    body = [f"<h1>{html.escape(title)} — v{va} → v{vb}</h1>",
            f"<p><small>{' · '.join(nav)}</small></p>"]
    entry = meta.get(vb, {})
    if entry.get("feedback"):
        body.append(f"<p><small>Revision note for v{vb}: {html.escape(str(entry['feedback']))}</small></p>")
    body.append(f'<blockquote class="rev-diff">{diff}</blockquote>')
    return f"{title} — v{va} → v{vb}", "".join(body)


def view_artifacts():
    """Artifacts view (v91) — outputs/ grouped by Focus, the same primitive the
    roadmap plans by: each group is the person/project the pieces belong to
    (resolved from the artifact's categories, subject as fallback). Groups
    render as collapsed full-width bars (v92, same idiom as Question Bank /
    Timeline) so the full suite of Focuses is scannable at a glance. Occasions
    (Mother's Day, birthdays) are badges, not groups. Essays without a Focus
    are the author's Thoughts (v98); other metadata orphans land in an Unfiled
    group with a repair hint. PDF/image sidecars are linked; every piece gets
    a revision footer (v98) with numbered version links and Δ diffs."""
    import re as _re

    from lifehug_core import REPO_DIR as _REPO  # noqa: PLC0415

    outputs = _REPO / "outputs"
    if not outputs.exists():
        return ("Artifacts", "<h1>Artifacts</h1>" + _empty(
            "No artifacts yet. Create one: <code>lifehug.py artifact new "
            "--format letter --subject Mom</code>"), False)

    roadmap_data = load_roadmap()
    if not roadmap_data.get("focuses"):
        try:
            roadmap_data = rebuild_roadmap(write=False)
        except Exception:
            roadmap_data = {"focuses": []}
    focuses = roadmap_data.get("focuses", [])
    cat_to_focus = {c: f for f in focuses for c in f.get("categories", [])}
    label_to_focus = {str(f.get("label", "")).lower(): f for f in focuses}

    arts = []
    for art_dir in sorted(outputs.iterdir()):
        if not art_dir.is_dir():
            continue
        meta_path = art_dir / "meta.yaml"
        fmt = subject = created = occasion = ""
        categories: list[str] = []
        if meta_path.exists():
            head = meta_path.read_text(errors="replace")

            def _field(key, _head=head):
                m = _re.search(rf"^{key}:\s*(.+)$", _head, _re.MULTILINE)
                return m.group(1).strip().strip("'\"") if m else ""

            fmt, subject, created, occasion = (
                _field(k) for k in ("format", "subject", "created", "occasion"))
            m = _re.search(r"^categories:\s*\[(.*?)\]", head, _re.MULTILINE)
            if m:
                categories = [c.strip().strip("'\"") for c in m.group(1).split(",") if c.strip()]
        versions = sorted(art_dir.glob("v*.md"),
                          key=lambda q: int(_re.match(r"v(\d+)", q.stem).group(1))
                          if _re.match(r"v(\d+)", q.stem) else 0)
        if not versions and not meta_path.exists():
            continue
        latest = versions[-1] if versions else None
        body = latest.read_text(errors="replace") if latest else ""
        art_json = read_json(art_dir / "artifact.json", default={}) or {}
        occasion = occasion or str(art_json.get("occasion") or "")
        focus = next((cat_to_focus[c] for c in categories if c in cat_to_focus), None)
        if focus is None and subject:
            focus = label_to_focus.get(subject.lower())
        version_meta, final_version = _artifact_version_meta(art_dir)
        arts.append({
            "slug": art_dir.name, "fmt": fmt, "subject": subject,
            "created": created, "occasion": occasion, "focus": focus,
            "n_versions": len(versions),
            "version_numbers": _artifact_version_numbers(art_dir),
            "version_meta": version_meta, "final_version": final_version,
            "words": len(_re.findall(r"[\w'’-]+", body)),
            "delivered": bool(art_json.get("delivered_at")),
            "promoted": bool(art_json.get("promoted_sources")),
            "latest_name": latest.name if latest else "", "body": body,
            "assets": sorted(p.name for p in art_dir.iterdir()
                             if p.is_file() and p.suffix.lower() in ARTIFACT_ASSET_TYPES),
        })

    if not arts:
        return ("Artifacts", "<h1>Artifacts</h1>" + _empty("No artifacts yet."), False)

    groups: dict[str, list[dict]] = {}
    for art in arts:
        if art["focus"]:
            key = art["focus"]["id"]
        elif art["fmt"] == "essay":
            # Opinion essays are the author's thoughts, not metadata orphans (v98).
            key = "__thoughts__"
        else:
            key = "__unfiled__"
        groups.setdefault(key, []).append(art)
    # Focus groups by most-recent artifact first; Thoughts then Unfiled last.
    special = ("__thoughts__", "__unfiled__")
    ordered = sorted((kv for kv in groups.items() if kv[0] not in special),
                     key=lambda kv: max(a["created"] for a in kv[1]), reverse=True)
    for key in special:
        if key in groups:
            ordered.append((key, groups[key]))

    sections = ["<h1>Artifacts</h1>",
                f"<p>{len(arts)} piece(s) in <code>outputs/</code>, grouped by Focus — "
                "the product payoff: letters, posts, captions, chapter drafts.</p>"]
    for _key, items in ordered:
        items.sort(key=lambda a: (a["created"], a["slug"]), reverse=True)
        focus = items[0]["focus"]
        if focus:
            label = str(focus.get("label", "?"))
            head = label
            if focus.get("type") == "person":
                # Distinct given names from the artifacts themselves ("Mom (Desi)").
                names = sorted({a["subject"].strip().title() for a in items
                                if a["subject"].strip()
                                and a["subject"].strip().lower() != label.lower()})
                if names:
                    head = f"{label} ({', '.join(names)})"
            head = html.escape(head)
            node = focus.get("wiki_node")
            if node:
                head = f'<a href="/page/{quote(str(node))}">{head}</a>'
            counts = (f"{len(items)} piece(s) · {focus.get('type', '?')} "
                      f"· → {focus.get('deliverable', '-')} "
                      f"· categories {','.join(focus.get('categories', []))}")
            sections.append(
                '<details class="art-group"><summary>'
                f'<span class="art-group-title">{head}</span>'
                f'<span class="art-group-counts">{html.escape(counts)}</span>'
                '</summary><div class="art-group-body">')
        elif _key == "__thoughts__":
            sections.append(
                '<details class="art-group"><summary>'
                '<span class="art-group-title">Thoughts</span>'
                f'<span class="art-group-counts">{len(items)} piece(s) · essays — '
                "the author's stated positions</span>"
                '</summary><div class="art-group-body">')
        else:
            sections.append(
                '<details class="art-group"><summary>'
                '<span class="art-group-title">Unfiled</span>'
                f'<span class="art-group-counts">{len(items)} piece(s) · no matching Focus</span>'
                '</summary><div class="art-group-body">'
                "<p><small>Add <code>subject:</code> / <code>categories:</code> to each "
                "folder's <code>meta.yaml</code> to file these under a Focus.</small></p>")
        for a in items:
            badges = _badge(a["fmt"] or "?", "default")
            if a["occasion"]:
                badges += " " + _badge(a["occasion"], "yellow")
            if a["delivered"]:
                badges += " " + _badge("delivered", "saturated")
            if a["promoted"]:
                badges += " " + _badge("promoted to source", "saturated")
            title = _artifact_title(a["slug"], a["fmt"], a["occasion"])
            meta_bits = [b for b in (
                a["created"] and f"created: {html.escape(a['created'])}",
                f"{a['n_versions']} version(s)",
                f"{a['words']:,} words",
                f"<code>{html.escape(a['slug'])}</code>") if b]
            meta_bits += [
                f'<a href="/artifact-file/{quote(a["slug"])}/{quote(n)}">{html.escape(n)}</a>'
                for n in a["assets"]]
            sections.append(f"<h3>{html.escape(title)} {badges}</h3>")
            sections.append(f"<p><small>{' · '.join(meta_bits)}</small></p>")
            if a["body"]:
                rendered = render_markdown(a["body"])
                sections.append(
                    f"<details><summary>Read {html.escape(a['latest_name'])}</summary>"
                    f"<blockquote>{rendered}</blockquote></details>")
            if a["version_numbers"]:
                # Revision footer (v98): one numbered link per saved version,
                # ★ marks the final, Δ compares a revision with its predecessor.
                links = []
                for vn in a["version_numbers"]:
                    entry = a["version_meta"].get(vn, {})
                    tip = " · ".join(str(bit) for bit in (
                        str(entry.get("created_at", ""))[:10],
                        entry.get("model", ""), entry.get("feedback", "")) if bit)
                    star = "★" if a["final_version"] == vn else ""
                    links.append(
                        f'<a href="/artifact-version/{quote(a["slug"])}/{vn}" '
                        f'title="{html.escape(tip)}">{vn}{star}</a>')
                    if vn - 1 in a["version_numbers"]:
                        links.append(
                            f'<a href="/artifact-diff/{quote(a["slug"])}/{vn - 1}/{vn}" '
                            f'title="what changed in v{vn}">Δ</a>')
                sections.append(
                    f'<p class="rev-footer"><small>Revisions: {" ".join(links)}</small></p>')
        sections.append("</div></details>")
    return "Artifacts", "".join(sections), False


def view_privacy_preview():
    """Preview of the future audience BUILDS: which pages' material could be
    rendered into each tier's build, per page sensitivity floors. This is
    metadata preview only — never a security boundary. The wiki itself is
    owner-only; audience surfaces will be separate, owner-reviewed builds."""
    from lifehug_core import sensitivity_visible

    tiers = ("public", "friends", "family")
    pages = [p for p in wiki_pages() if p.name not in ("index.md", "log.md", "SCHEMA.md", "timeline.md")]
    rows = []
    for page in sorted(pages):
        level = page_field(page, "sensitivity") or "private"
        if level == "personal":
            level = "private"  # legacy value from pre-v73 compiles
        rows.append((page, level))

    sections = [
        "<h1>Privacy Preview</h1>",
        "<p><strong>Preview only — not a security boundary.</strong> The wiki you are "
        "reading is permanently owner-only. Audience surfaces (public / friends / family) "
        "will be generated later as separate, owner-reviewed builds; this page shows which "
        "pages' material would be <em>eligible</em> for re-rendering into each build, based "
        "on each page's sensitivity floor (the most sensitive source it cites). Unlabeled "
        "sources default to <code>private</code>, so early numbers skew private — labels "
        "accumulate as the weekly classifier suggests them and you confirm.</p>",
    ]
    for tier in tiers:
        included = [(p_, lvl) for p_, lvl in rows if sensitivity_visible(lvl, tier)]
        hidden = len(rows) - len(included)
        sections.append(f"<h2>{tier.title()} build — {len(included)} page(s) eligible, {hidden} private to deeper tiers</h2>")
        if included:
            items = "".join(
                f'<li><a href="/page/{quote(str(p_.relative_to(WIKI_DIR.parent)))}">{html.escape(page_title(p_))}</a>'
                f' <small>({html.escape(lvl)})</small></li>'
                for p_, lvl in included)
            sections.append(f"<ul>{items}</ul>")
        else:
            sections.append("<p><em>Nothing eligible yet — label sources with --sensitivity, "
                            "or confirm the classifier's suggestions, and floors will open up.</em></p>")
    return "Privacy Preview", "".join(sections), False


def view_book():
    """Book Assembly view (v75) — a chapter map for every book-project Focus.

    Each book gets a card: overall progress bar + a table of chapters with
    answered ratio, scene-slot depth (McAdams 5-slot from classifications), a
    verdict badge, and — for chapters not yet ready — the top few gap questions
    to record next. When a chapter is READY, offers the artifact command that
    would draft it. The point is a manuscript-shaped view of the archive, so
    the flagship deliverable stops being an abstract goal.
    """
    try:
        import book as book_mod  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return ("Book Assembly",
                f"<h1>Book Assembly</h1>{_empty(f'book module unavailable: {html.escape(str(exc))}')}",
                False)
    books = book_mod.compute_books()
    if not books:
        return ("Book Assembly",
                "<h1>Book Assembly</h1>" + _empty(
                    "No book-project Focuses yet. A Focus with "
                    "<code>deliverable=book</code> produces a chapter list."),
                False)

    sections = ["<h1>Book Assembly</h1>"]
    for b in books:
        sat = float(b.get("saturation") or 0)
        head_bar = _bar(sat,
                        f"{b['answered_questions']}/{b['total_questions']} "
                        f"answered · {_pct(sat)} · {b['chapters_ready']} of "
                        f"{b['chapter_count']} chapters ready")
        badges = _badge(b["verdict"], b["verdict"].lower())
        if b.get("primary"):
            badges = _badge("primary", "saturated") + " " + badges
        # Phase 2: manuscript rollup on the header — words drafted vs. target.
        drafted = int(b.get("drafted_words") or 0)
        target = int(b.get("manuscript_target") or 0)
        if drafted:
            ms = (f"📄 {drafted:,}/{target:,} words drafted "
                  f"({_pct(b.get('manuscript_ratio') or 0)})")
        else:
            ms = '<span class="muted">no drafts yet</span>'
        sections.append(
            '<div class="focus-row"><div class="focus-head">'
            f'<span class="focus-label">📖 {html.escape(str(b.get("label", "")))}</span> {badges}</div>'
            + head_bar
            + f'<div class="focus-sub">{html.escape(str(b.get("objective", "")))} '
            f'→ {html.escape(str(b.get("deliverable", "book")))} · {ms}</div></div>'
        )
        rows = []
        for ch in b["chapters"]:
            cid = html.escape(ch["category_id"])
            name = html.escape(ch["category_name"])
            hook = ch.get("manuscript_hook")
            if hook:
                name = f'<a href="/page/{quote(hook)}">{name}</a>'
            if ch["scene_slots_total"]:
                depth_cell = (f"{ch['scene_slots_filled']}/{ch['scene_slots_total']} "
                              f"({_pct(ch['scene_slot_ratio'])})")
            else:
                depth_cell = '<span class="muted">—</span>'
            gap_cell = "<span class='muted'>—</span>"
            if ch["gap_questions"]:
                bits = []
                for gap in ch["gap_questions"][:3]:
                    text = str(gap.get("text", ""))
                    if len(text) > 90:
                        text = text[:87] + "…"
                    bits.append(f"<code>{html.escape(gap['id'])}</code> {html.escape(text)}")
                gap_cell = "<br>".join(bits)
            elif ch["ready_to_draft"]:
                gap_cell = (f'<em>ready to draft — '
                            f'<code>lifehug.py artifact new --format chapter '
                            f'--subject "{html.escape(ch["category_name"])}" '
                            f'--categories {cid}</code></em>')
            # Phase 2: per-chapter draft column — word count of the latest
            # chapter-format artifact whose meta.yaml lists this category.
            if ch.get("has_draft"):
                draft_cell = (f"📄 {int(ch.get('drafted_words') or 0):,} words "
                              f"({_pct(ch.get('manuscript_ratio') or 0)})")
            else:
                draft_cell = '<span class="muted">—</span>'
            rows.append([
                cid,
                name,
                _bar(ch["saturation"], f"{ch['answered']}/{ch['total']} · {_pct(ch['saturation'])}"),
                depth_cell,
                draft_cell,
                _badge(ch["verdict"], ch["verdict"].lower()),
                gap_cell,
            ])
        sections.append(_table(["Cat", "Chapter", "Answered", "Scene depth", "Draft", "Verdict", "Next questions / draft"], rows))

    return ("Book Assembly", "".join(sections), True)


def view_reports():
    """Reports view (v86, issue #35) — the full weekly/monthly maintenance
    reports persisted under state/reports/. Telegram carries only the short
    counts-first summary; this is the document of record."""
    from lifehug_core import STATE_DIR as _STATE  # noqa: PLC0415

    reports_dir = _STATE / "reports"
    files = sorted(reports_dir.glob("*.md"), reverse=True) if reports_dir.exists() else []
    if not files:
        return ("Reports", "<h1>Reports</h1>" + _empty(
            "No maintenance reports yet — the weekly and monthly crons write "
            "them to <code>state/reports/</code>."), False)
    parts = ["<h1>Reports</h1>"]
    for i, path in enumerate(files[:24]):
        body = html.escape(path.read_text(encoding="utf-8", errors="replace"))
        open_attr = " open" if i == 0 else ""
        parts.append(
            f"<details{open_attr}><summary><strong>{html.escape(path.stem)}</strong>"
            f" <span class='muted'>({path.stat().st_size:,} bytes)</span></summary>"
            f"<pre style='white-space:pre-wrap'>{body}</pre></details>")
    if len(files) > 24:
        parts.append(f"<p class='muted'>… {len(files) - 24} older report(s) in state/reports/</p>")
    return ("Reports", "".join(parts), False)


VIEWS = [
    # System overview first, with the graph right beneath it.
    ("status", "The Loop", view_status),
    ("mirror", "Mirror", view_mirror),
    ("graph", "Graph", view_graph),
    ("timeline", "Timeline", view_timeline),
    # Book assembly — the flagship-deliverable surface.
    ("book", "Book Assembly", view_book),
    # Focus block: focuses and their recommendations.
    ("focuses", "Focuses", view_focuses),
    ("recommendations", "Focus Recommendations", view_recommendations),
    # The question surfaces.
    ("question-bank", "Question Bank", view_question_bank),
    ("candidates", "Question Candidates", view_candidates),
    ("queue", "Question Queue", view_queue),
    # The rest.
    ("coverage", "Coverage", view_coverage),
    ("entities", "Entity Candidates", view_entities),
    ("sources", "Source Integrity", view_sources),
    ("artifacts", "Artifacts", view_artifacts),
    ("reports", "Reports", view_reports),
    ("privacy", "Privacy Preview", view_privacy_preview),
]
VIEW_MAP = {slug: fn for slug, _, fn in VIEWS}

# One-line explainer shown under each view's title: what the page is and what the
# data on it means. Plain text (may include simple inline HTML); injected after
# the <h1> so empty-state pages get it too.
VIEW_DESCRIPTIONS = {
    "status": "A live snapshot of the whole system — one card per moving part of the Loop: what pass you're on, how much you've answered, how many candidates and sources are waiting, and whether the weekly queue is being delivered.",
    "mirror": "What the archive has noticed about you. The weekly synthesis distills the classifier's contradictions, self-understanding insights, and stated positions into a short edition — tensions presented as coexisting truths in your own words, every claim cited. The raw signals stay browsable underneath. A place to visit and sit with, not a feed.",
    "book": "The manuscript view. Every book-project Focus becomes a card; each of its question categories becomes a chapter with an answered ratio, a scene-depth score (McAdams' 5-slot probe from the classifier), a readiness verdict, and either the next few gap questions to record or the artifact command to draft it. This is the flagship deliverable made visible.",
    "focuses": "Everything you're deliberately building toward — people, themes, or books. Each bar shows how full a Focus is against its target (answered / target), its tier, and whether it's early, developing, ready to draft, or saturated.",
    "coverage": "How much of each question category you've answered. The bar and colour show your ratio — RED (0–30%), YELLOW (30–70%), GREEN (70%+). Categories are sorted least-covered first, so the top of the list is where the story still needs you.",
    "graph": "Your life as a graph. Each node is a wiki page (people, places, periods, themes, Focuses); size reflects how many sources mention it and edges connect subjects that share sources. Click any node to open its page.",
    "question-bank": "The full master list of questions by category — answered (✓) and still open (○). This is the raw pool the daily question and the weekly planner draw from; it only ever grows.",
    "candidates": "Follow-up questions the weekly classifier proposed from your answers and stories, grouped by review status. These are <em>not</em> daily questions yet — they wait here until promoted into the question bank.",
    "entities": "People, places, periods, objects, and themes auto-detected across your answers that have <em>not</em> yet graduated into wiki pages. Once one graduates it drops off this list and appears in the wiki itself. Qualifies = it meets the bar to become a page.",
    "queue": "This week's planned questions — the ordered list the daily question pulls from before falling back to coverage rotation. Each row shows the question, its category, why it was chosen, and its status: answered (you've responded), delivered (sent, awaiting an answer), or queued (still waiting). Answered state is read from the question bank, so it stays accurate. The queue expires and is rebuilt weekly.",
    "sources": "The integrity ledger for every raw source (answers, stories, artifacts). Open lint findings flag metadata or manifest problems to repair; the captured-sources tables show what's tracked and whether any file has changed since it was first recorded.",
    "timeline": "The life graph projected onto time: chrono-ordered periods as the spine, with people, places, objects, and projects lined up by shared sources (the evidence is shown), dated moments from classified answers, your own Life Chapters as a parallel band, and gaps made explicit. A validation surface — wrong placements are feedback.",
    "artifacts": "Every piece in outputs/ — letters, posts, captions, essays, chapter drafts — grouped by the Focus it belongs to (the person or project, resolved from the artifact's categories). Each group is a collapsed bar showing its piece count; click to expand into the pieces, with occasions like Mother's Day as badges, versions, word count, delivered/promoted state, linked PDFs, and the latest text readable inline. Each piece ends with a revision footer — numbered links to every saved version (★ = final, hover for the revision note) and Δ links showing exactly what changed between versions. Essays without a Focus group under Thoughts; other pieces missing metadata land in Unfiled with a repair hint. This is where the archive becomes things you can actually give, post, or publish.",
    "privacy": "Which pages' material would be eligible for each future audience build (public / friends / family), from per-page sensitivity floors. Preview only — the wiki itself is permanently owner-only, and audience surfaces will be separate, owner-reviewed builds.",
    "reports": "The full weekly and monthly maintenance reports — every step's complete output, persisted under state/reports/. The Telegram message is just the counts summary; when it flags a failure or warning, this is where the detail lives.",
    "recommendations": "Entities the system thinks are strong enough to become their own Focus, ranked by evidence. Pending ones await your approval; acted-on and dismissed ones are kept for the record. Nothing here changes questions until you promote it.",
}


def _with_description(body: str, desc: str) -> str:
    """Insert a description paragraph right after the view's first <h1>."""
    marker = "</h1>"
    idx = body.find(marker)
    if idx == -1:
        return body
    idx += len(marker)
    return body[:idx] + f'<p class="view-desc">{desc}</p>' + body[idx:]


class Handler(BaseHTTPRequestHandler):
    def send_html(self, title, body, status=200, active_rel=None, wide=False):
        payload = layout(title, body, active_rel, wide)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            # Home is the action hub (v99). The wiki index stays reachable via
            # the sidebar's Index link (/page/wiki/index.md).
            try:
                title, body, wide = view_home()
            except Exception as exc:  # noqa: BLE001 — the front page must never 500
                title, body, wide = ("Today",
                                     f"<h1>Today</h1>{_empty('home hub error: ' + html.escape(str(exc)))}",
                                     False)
            self.send_html(title, body, wide=wide)
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

        if parsed.path.startswith("/artifact-file/"):
            # Binary sidecars (PDFs, images) inside outputs/<slug>/ — the
            # Artifacts view links them here since outputs/ lives outside the
            # wiki page tree. Allowlisted extensions only.
            from lifehug_core import REPO_DIR as _REPO  # noqa: PLC0415
            rel = Path(unquote(parsed.path[len("/artifact-file/"):]))
            if rel.is_absolute() or ".." in rel.parts or len(rel.parts) != 2:
                self.send_html("Invalid path", "<h1>Invalid path</h1>", status=400)
                return
            outputs_root = (_REPO / "outputs").resolve()
            target = _REPO / "outputs" / rel
            ctype = ARTIFACT_ASSET_TYPES.get(target.suffix.lower())
            if not ctype or not target.is_file() or outputs_root not in target.resolve().parents:
                self.send_html("Not found", "<h1>Not found</h1>", status=404)
                return
            payload = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if parsed.path.startswith("/artifact-version/"):
            # One saved revision of an artifact (v98) — outputs/<slug>/vN.md.
            parts = [unquote(p) for p in parsed.path[len("/artifact-version/"):].split("/") if p]
            result = artifact_version_html(*parts) if len(parts) == 2 else None
            if result is None:
                self.send_html("Not found", "<h1>Not found</h1>", status=404)
                return
            self.send_html(result[0], result[1])
            return

        if parsed.path.startswith("/artifact-diff/"):
            # Word-level comparison of two revisions (v98).
            parts = [unquote(p) for p in parsed.path[len("/artifact-diff/"):].split("/") if p]
            result = artifact_diff_html(*parts) if len(parts) == 3 else None
            if result is None:
                self.send_html("Not found", "<h1>Not found</h1>", status=404)
                return
            self.send_html(result[0], result[1])
            return

        if parsed.path == "/views/graph.json":
            payload = json.dumps(graph_data()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if parsed.path.startswith("/views/"):
            slug = parsed.path[len("/views/"):].strip("/")
            builder = VIEW_MAP.get(slug)
            if not builder:
                self.send_html("Not found", "<h1>Not found</h1>", status=404)
                return
            try:
                title, body, wide = builder()
                desc = VIEW_DESCRIPTIONS.get(slug)
                if desc:
                    body = _with_description(body, desc)
            except Exception as exc:  # a broken view shouldn't take down the server
                title, body, wide = ("View error", f"<h1>View error</h1><pre>{html.escape(repr(exc))}</pre>", False)
            self.send_html(title, body, wide=wide)
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