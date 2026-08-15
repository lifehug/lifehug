#!/usr/bin/env python3
"""Owner-only local Lifehug wiki viewer."""

from __future__ import annotations

import argparse
import contextlib
import datetime
import hashlib
import html
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

from lifehug_core import (
    ANSWERS_DIR,
    CLASSIFICATIONS_DIR,
    COVERAGE_FILE,
    FOCUS_RECS_FILE,
    NEIGHBORHOODS_FILE,
    QUESTION_CANDIDATES_FILE,
    QUESTION_QUEUE_FILE,
    QUESTIONS_FILE,
    REPO_DIR,
    ROTATION_FILE,
    SECOND_VOICE_OFFERS_FILE,
    SOURCE_LINT_FINDINGS_FILE,
    SOURCE_MANIFEST_FILE,
    SOURCES_DIR,
    STATE_DIR,
    WIKI_DIR,
    answer_body,
    load_config,
    parse_categories,
    parse_questions,
    read_json,
    read_text,
    slugify,
    split_frontmatter,
)
from entity_roster import ENTITY_TYPES, load_roster
from question_candidates import AUTO_PROMOTE_THRESHOLD, unified_quality_score, _infer_category
from progress import verdict
from recommend_focuses import FOCUS_READY_SCORE_FLOOR, focus_start_gate
from roadmap import focus_fill, load_roadmap, rebuild_roadmap
from vault_paths import open_vault_fd, read_vault_bytes

VIEWER_LOG = logging.getLogger("lifehug.viewer")


def _record_view_failure(operation: str, exc: Exception) -> None:
    VIEWER_LOG.error(
        "viewer read failed operation=%s exception_class=%s",
        operation,
        type(exc).__name__,
    )


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
        head = read_text(path, errors="replace")[:1024]
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


# Hamburger menu groups, split by what the owner is doing when they open the
# menu (v136): DO — surfaces that wait on their action (decide on proposals,
# make pieces); PLAN — the asking supply and its weekly schedule; REFLECT —
# the compiled life itself; SYSTEM — machinery health and inspection. The
# queue is a plan you read (the daily cron consumes it), not a Do; source
# integrity and the privacy preview inspect the machine, not the material.
# A view registered in VIEWS but not claimed by any group falls into System
# automatically, so adding a view is still one registry entry.
VIEW_GROUPS = [
    ("Do", ["review", "studio"]),
    ("Plan", ["queue", "foundation"]),
    ("Reflect", ["mirror", "timeline", "graph"]),
    ("System", ["status", "reports", "sources", "answers", "privacy"]),
]


def menu_html() -> str:
    """The hamburger dropdown: registered views grouped by VIEW_GROUPS
    (Do / Plan / Reflect / System). Adding a view to VIEWS automatically
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
    body {{ margin: 0; overflow-x: hidden; font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: var(--ink); background: var(--bg); }}
    header {{ height: 52px; display: flex; align-items: center; gap: 16px; padding: 0 20px; border-bottom: 1px solid #ddd8cf; background: #fff; position: sticky; top: 0; z-index: 20; }}
    header a {{ color: #202124; text-decoration: none; font-weight: 650; }}
    form {{ margin-left: auto; }}
    input {{ border: 1px solid #c8c2b8; border-radius: 6px; padding: 7px 9px; min-width: 220px; }}
    .drawer-toggle, .drawer-close, .drawer-head {{ display: none; }}
    .drawer-scrim {{ display: none; }}
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
    .shell {{ display: grid; grid-template-columns: 300px minmax(0, 1fr); min-height: calc(100vh - 53px); }}
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
    main {{ max-width: 860px; min-width: 0; padding: 32px 44px 80px; }}
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
    details.fnd-focus {{ margin-bottom: 10px; border: 1px solid #e5dfd5; border-radius: 8px; background: #fffdf9; overflow: hidden; }}
    details.fnd-focus > summary {{ list-style: none; cursor: pointer; padding: 12px 16px; }}
    details.fnd-focus > summary::-webkit-details-marker {{ display: none; }}
    details.fnd-focus > summary:hover {{ background: #f6f1e8; }}
    details.fnd-focus[open] > summary {{ border-bottom: 1px solid #eee5d8; }}
    details.fnd-focus > summary .focus-head::before {{ content: "\\25B8"; color: #9a8c75; font-size: 12px;
      margin-right: 2px; transition: transform 0.15s; }}
    details.fnd-focus[open] > summary .focus-head::before {{ transform: rotate(90deg); }}
    .fnd-cats {{ padding: 10px 14px 12px; }}
    .fnd-cats details.qb-cat {{ background: #fff; }}
    /* Studio (v127): projects and pieces nested inside a Focus group */
    .studio-project {{ margin: 0 0 16px; }}
    .studio-project > .focus-row {{ border-bottom: none; padding-bottom: 4px; }}
    .fnd-cats details.art-group {{ background: #fff; }}
    .fnd-cats > h3 {{ margin-top: 18px; }}
    details.studio-new > summary {{ background: #f6f1e8; }}
    h2.fnd-orphans {{ margin-top: 28px; }}
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
    /* Update observability (lifehug#84): The Loop's install-state card + last-update line */
    .update-status {{ margin: 4px 0 22px; padding: 12px 16px; border-radius: 10px;
      background: var(--card-warm); border: 1px solid var(--line-soft); }}
    .update-status.update-behind {{ border-left: 4px solid #987b55; }}
    .update-headline {{ font-size: 14px; font-weight: 650; color: var(--ink-strong); }}
    .update-cmd {{ margin-top: 4px; font-size: 13px; }}
    .update-cmd code {{ background: var(--panel-hover); padding: 2px 6px; border-radius: 4px; }}
    .update-diagnostic {{ margin-top: 6px; font-size: 13px; color: #8c2f28; }}
    .update-checked {{ margin-top: 4px; font-size: 12px; color: var(--muted); }}
    .update-last {{ margin: 0 0 22px; padding: 12px 16px; border-radius: 10px;
      background: var(--card-warm); border: 1px solid var(--line-soft); border-left: 4px solid #3f8f4f; }}
    .update-changelog {{ margin-top: 6px; font-size: 13px; color: var(--ink-soft); white-space: pre-wrap; }}
    .update-more {{ margin-top: 6px; font-size: 12px; color: var(--muted); }}
    .update-more summary {{ cursor: pointer; }}
    .update-more .update-changelog {{ margin-left: 4px; }}
    /* Write actions (v101) */
    .flash {{ background: #f0ead9; border: 1px solid #ddd0b2; border-radius: 8px; padding: 10px 14px;
      margin: 0 0 18px; font-size: 14px; color: var(--ink-soft); }}
    .jobpill {{ display: inline-block; font-size: 12px; font-weight: 650; padding: 1px 10px; border-radius: 10px;
      background: #e7e0d2; color: var(--ink-mid); }}
    .jobpill.succeeded {{ background: #dcedc8; color: #33691e; }}
    .jobpill.failed {{ background: #f8d7d5; color: #8c2f28; }}
    .btn {{ font: inherit; font-size: 13px; font-weight: 600; color: var(--link); background: var(--card-bg);
      border: 1px solid #d8cdbb; border-radius: 6px; padding: 5px 12px; cursor: pointer; }}
    .btn:hover {{ background: var(--panel-hover); }}
    .btn.quiet {{ color: var(--muted); font-weight: 500; }}
    .act-inline {{ display: inline-flex; gap: 6px; align-items: center; margin: 0; }}
    .act-inline select, .act-inline input {{ min-width: 0; padding: 4px 6px; font-size: 13px; }}
    .act-row {{ margin: 8px 0 20px; }}
    form.actform {{ margin: 0; }}
    textarea {{ width: 100%; box-sizing: border-box; border: 1px solid var(--border-strong); border-radius: 6px;
      padding: 8px 10px; font: 14px/1.5 inherit; background: var(--card-bg); }}
    label {{ display: block; font-size: 12px; color: var(--ink-mid); margin: 10px 0 3px; }}
    .art-actions {{ border: 1px solid var(--line-soft); border-radius: 10px; background: var(--card-warm);
      padding: 12px 16px 16px; margin: 14px 0; }}
    .art-actions summary {{ cursor: pointer; font-weight: 650; font-size: 14px; color: var(--ink-mid); }}
    .source-toolbar {{ display: flex; flex-wrap: wrap; gap: 8px; margin: -4px 0 20px; }}
    .source-toolbar a {{ display: inline-flex; align-items: center; min-height: 36px; box-sizing: border-box;
      border: 1px solid #d8cdbb; border-radius: 6px; padding: 6px 12px; text-decoration: none; font-size: 13px; font-weight: 600; }}
    .source-toolbar a:hover {{ background: var(--panel-hover); }}
    .source-meta {{ background: var(--card-warm); border: 1px solid var(--line-soft); border-radius: 10px;
      padding: 4px 16px 2px; margin: 0 0 26px; }}
    .source-meta table {{ margin-bottom: 8px; }}
    .source-body {{ overflow-wrap: anywhere; }}
    #graph {{ width: 100%; height: calc(100vh - 150px); border: 1px solid #e5dfd5; border-radius: 10px; background: #fffdf9; }}
    .graph-legend {{ font-size: 13px; color: #6b5d49; margin: 6px 0 10px; }}
    .graph-legend span {{ margin-right: 14px; }}
    @media (max-width: 820px) {{
      header {{ height: 60px; gap: 8px; padding: 0 12px; }}
      header > a {{ flex: 0 0 auto; }}
      header form {{ flex: 1 1 auto; min-width: 0; margin-left: 0; }}
      header form input {{ box-sizing: border-box; width: 100%; min-width: 0; min-height: 44px; }}
      .drawer-toggle, .drawer-close {{ display: inline-flex; align-items: center; justify-content: center; min-width: 44px; min-height: 44px;
        padding: 0; border: 1px solid var(--border-strong); border-radius: 6px; color: var(--ink-soft); background: var(--card-bg); font: inherit; cursor: pointer; }}
      .drawer-toggle:hover, .drawer-close:hover {{ background: var(--panel-hover); }}
      .drawer-toggle {{ font-size: 22px; line-height: 1; }}
      .drawer-close {{ font-size: 14px; font-weight: 650; }}
      .menu-btn {{ width: 44px; height: 44px; }}
      .menu-dropdown {{ position: fixed; right: 12px; top: 66px; width: min(300px, calc(100vw - 24px)); min-width: 0; max-height: calc(100vh - 78px); overflow-y: auto; }}
      .menu-item {{ min-height: 44px; box-sizing: border-box; padding: 11px 10px; }}
      .shell {{ grid-template-columns: minmax(0, 1fr); }}
      .drawer-scrim {{ position: fixed; inset: 0; z-index: 29; background: rgba(32, 33, 36, 0.32); }}
      body.drawer-open .drawer-scrim {{ display: block; }}
      nav {{ display: block; position: fixed; top: 0; bottom: 0; left: 0; z-index: 30; box-sizing: border-box; width: min(340px, 88vw); padding: 10px;
        transform: translateX(-105%); transition: transform 0.18s ease-out; box-shadow: 4px 0 22px rgba(60, 50, 30, 0.16); }}
      body.drawer-open nav {{ transform: translateX(0); }}
      .drawer-head {{ display: flex; align-items: center; justify-content: space-between; min-height: 44px; padding: 0 2px 8px; border-bottom: 1px solid var(--line); }}
      .drawer-title {{ color: var(--ink-strong); font-weight: 650; }}
      .sidebar-top {{ min-height: 44px; box-sizing: border-box; padding: 12px 8px; }}
      .sidebar-group-header {{ min-height: 44px; box-sizing: border-box; padding: 10px 8px; }}
      .sidebar-item {{ min-height: 44px; box-sizing: border-box; padding-top: 12px; padding-bottom: 12px; }}
      .sidebar-item.sub {{ padding-left: 34px; }}
      main, main.wide {{ box-sizing: border-box; width: 100%; padding: 24px 16px 48px; }}
      h1 {{ font-size: 30px; overflow-wrap: anywhere; }}
      .cov-row {{ align-items: flex-start; flex-wrap: wrap; }}
      .cov-cat {{ width: auto; flex: 1 1 180px; }}
      .hub {{ grid-template-columns: minmax(0, 1fr); }}
      .cards {{ grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); }}
      .qb-cat-title, .art-group-title {{ min-width: 0; }}
      .art-group-counts {{ white-space: nowrap; }}
      .source-toolbar a {{ min-height: 44px; }}
      table.dash {{ display: block; max-width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; }}
      #graph {{ min-width: 0; height: calc(100vh - 180px); }}
    }}
  </style>
</head>
<body>
  <header>
    <button class="drawer-toggle" id="drawerToggle" aria-label="Open wiki navigation" aria-controls="wikiDrawer" aria-expanded="false" onclick="openDrawer()">&#9776;</button>
    <a href="/">Lifehug</a>
    <form action="/search"><input name="q" placeholder="Search"></form>
    {menu}
  </header>
  <div class="drawer-scrim" id="drawerScrim" onclick="closeDrawer()"></div>
  <div class="shell"><nav id="wikiDrawer" aria-label="Compiled wiki navigation"><div class="drawer-head"><span class="drawer-title">Compiled wiki</span><button class="drawer-close" aria-label="Close wiki navigation" onclick="closeDrawer()">Close</button></div>{nav}</nav><main class="{main_cls}">{body}</main></div>
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
    function openDrawer() {{
      document.body.classList.add('drawer-open');
      document.getElementById('drawerToggle').setAttribute('aria-expanded', 'true');
      document.querySelector('#wikiDrawer .drawer-close').focus();
    }}
    function closeDrawer() {{
      document.body.classList.remove('drawer-open');
      document.getElementById('drawerToggle').setAttribute('aria-expanded', 'false');
    }}
    document.addEventListener('keydown', function (e) {{ if (e.key === 'Escape') closeDrawer(); }});
    document.querySelectorAll('#wikiDrawer a').forEach(function (link) {{ link.addEventListener('click', closeDrawer); }});
    // Job pill: poll a detached job's status file until it finishes (v101).
    (function () {{
      var pill = document.querySelector('.jobpill[data-job]');
      if (!pill) return;
      var id = pill.getAttribute('data-job');
      function tick() {{
        fetch('/jobs/' + id + '.json').then(function (r) {{ return r.json(); }}).then(function (j) {{
          var state = j.state || j.status;
          if (state === 'queued' || state === 'running' || state === 'safely-retryable') {{
            pill.textContent = state === 'running' ? 'running…' :
              (state === 'safely-retryable' ? 'ready to retry…' : 'queued…');
            setTimeout(tick, 3000); return;
          }}
          pill.textContent = state === 'succeeded' ? 'done ✓' : 'failed ✗';
          pill.classList.add(state);
          if (state === 'failed') pill.title = j.failure_code || 'command failed';
        }}).catch(function () {{ setTimeout(tick, 5000); }});
      }}
      setTimeout(tick, 2500);
    }})();
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


def _category_status(ratio: float) -> str:
    """Category status colour — same thresholds as lifehug_core.compute_coverage."""
    if ratio >= 0.7:
        return "green"
    if ratio >= 0.3:
        return "yellow"
    return "red"


def _foundation_category(cid: str, name: str, qs: list[dict]) -> str:
    """One collapsible category row: coverage bar, status badge, question list."""
    total = len(qs)
    answered = sum(1 for q in qs if q["answered"])
    ratio = answered / total if total else 0
    status = _category_status(ratio)
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
    return (
        '<details class="qb-cat"><summary>'
        f'<span class="qb-cat-title">{html.escape(head)}</span>'
        + _bar(ratio, f"{answered}/{total} · {_pct(ratio)}")
        + " " + _badge(status, status)
        + '</summary><ul class="qb-list">' + "".join(lis) + "</ul></details>"
    )


def view_foundation():
    """Focus → category → question drill-down: the supply side on one screen.

    Consolidates the old Focuses / Coverage / Question Bank views (v124).
    Every number is computed live from the question bank, so the levels can
    never disagree with each other the way the cached coverage.json could.
    The focus bar stays a saturation measure (answered / tier target); the
    category bars stay coverage measures (answered / total in the bank).
    """
    roadmap_data = load_roadmap()
    if not roadmap_data.get("focuses"):
        try:
            roadmap_data = rebuild_roadmap(write=False)
        except Exception:
            roadmap_data = {"focuses": []}
    focuses = roadmap_data.get("focuses", [])
    md = QUESTIONS_FILE.read_text(encoding="utf-8") if QUESTIONS_FILE.exists() else ""
    questions = parse_questions(md)
    cat_names = parse_categories(md)
    by_cat: dict[str, list[dict]] = {}
    for q in questions:
        by_cat.setdefault(str(q["category"]), []).append(q)
    if not focuses and not by_cat:
        return ("Foundation", "<h1>Foundation</h1>" + _empty(
            "No material yet — add a question bank, or a focus with "
            "<code>lifehug focus-new</code>."), False)

    def cat_ratio(cid: str) -> float:
        qs = by_cat.get(cid, [])
        return (sum(1 for q in qs if q["answered"]) / len(qs)) if qs else 0.0

    parts = ["<h1>Foundation</h1>"]
    total_answered = total_target = 0
    claimed: set[str] = set()
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
                + html.escape(str(focus.get("deliverable", "-"))))
        barlabel = f"{fill['answered']}/{fill['target']} · {_pct(sat)} · {label}"
        cats = list(focus.get("categories", []))
        claimed.update(cats)
        # Least-covered first within the focus — the top row is where the
        # story still needs you (the old Coverage view's ordering, kept).
        cats.sort(key=cat_ratio)
        cat_html = "".join(
            _foundation_category(c, (cat_names.get(c) or {}).get("name", ""),
                                 by_cat.get(c, []))
            for c in cats)
        parts.append(
            '<details class="fnd-focus"><summary>'
            '<div class="focus-head">'
            f'<span class="focus-label">{lbl}</span> {badges}</div>'
            + _bar(sat, barlabel)
            + f'<div class="focus-sub">{meta}</div>'
            + "</summary>"
            + '<div class="fnd-cats">'
            + (cat_html or _empty("No categories in this focus yet."))
            + "</div></details>"
        )
    orphans = sorted(c for c in by_cat if c not in claimed)
    if orphans:
        parts.append('<h2 class="fnd-orphans">Not part of any focus</h2>')
        parts.extend(
            _foundation_category(c, (cat_names.get(c) or {}).get("name", ""), by_cat[c])
            for c in orphans)
    if total_target:
        overall = total_answered / total_target
        parts.append(f'<p class="muted">Overall: {total_answered}/{total_target} answered '
                     f'({_pct(overall)} toward current targets)</p>')
    return ("Foundation", "".join(parts), False)


def _quality_cell_html(candidate: dict, quality_profile: dict | None) -> str:
    """Single Quality column cell (ADR 0008): the one unified score — priority
    × story-function multiplier − craft penalties — with a compact breakdown.
    Reads the STORED `candidate["quality"]` when an auto-promote run has
    stamped it; falls back to computing unified_quality_score() live
    (best-effort, marked "live") for candidates no run has touched yet. Never
    a second scoring path — same function the auto-promote ladder uses."""
    stored = candidate.get("quality")
    live = False
    unified: dict | None
    if isinstance(stored, dict) and isinstance(stored.get("score"), (int, float)):
        unified = stored
    else:
        live = True
        try:
            unified = unified_quality_score(candidate, quality_profile, existing_questions=None)
        except Exception:
            unified = None
    if not unified or not isinstance(unified.get("score"), (int, float)):
        return '<span class="muted">—</span>'

    score = float(unified["score"])
    score_html = f'<span class="q-score">{score:.2f}</span>'
    components = unified.get("components")
    if not isinstance(components, dict):
        # Stored before components were persisted (or a stripped fixture) —
        # show the score alone rather than fabricate a breakdown.
        return score_html

    priority = float(components.get("priority", 0) or 0)
    multiplier = float(components.get("story_function_multiplier", 1) or 1)
    penalty_total = float(components.get("penalty_total", 0) or 0)
    flags = [p.get("flag") for p in components.get("craft_penalties", []) or [] if p.get("flag")]
    penalty_note = f" −{penalty_total:.2f}" if penalty_total else ""
    title_bits = [f"priority {priority:.2f} × story-function multiplier {multiplier:.2f}"]
    if penalty_total:
        title_bits.append(f"− craft penalties {penalty_total:.2f}")
    title_bits.append(f"flags: {', '.join(flags)}" if flags else "flags: none")
    title = html.escape("; ".join(title_bits))
    breakdown = (
        f'<span class="q-breakdown muted" title="{title}">'
        f"({priority:.2f}×{multiplier:.2f}{penalty_note})</span>"
    )
    flag_html = f' <span class="q-flags muted">{html.escape(", ".join(flags))}</span>' if flags else ""
    live_html = ' <span class="q-live muted">live</span>' if live else ""
    return f"{score_html} {breakdown}{flag_html}{live_html}"


def _history_reason_cell(c: dict) -> str:
    """Decided-row (rejected/deferred/promoted/auto_promoted) cell showing
    BOTH the generator's provenance ``reason`` (why it was proposed) and the
    owner's ``decision_reason`` (why it was decided) — distinct fields since
    the decisions-feed-the-loop field-overwrite fix. Before that fix, a
    decision's reason clobbered the provenance text in place, so nothing
    here could ever have shown both; this is the viewer's first rendering
    of either for a decided row."""
    provenance = str(c.get("reason") or "").strip()
    decision = str(c.get("decision_reason") or "").strip()
    parts: list[str] = []
    if provenance:
        parts.append(f'<div class="q-provenance-reason muted">proposed: {html.escape(provenance[:240])}</div>')
    if decision:
        parts.append(f'<div class="q-decision-reason muted">owner: {html.escape(decision[:240])}</div>')
    return "".join(parts) if parts else '<span class="muted">—</span>'


def _candidates_section_html() -> str:
    """Question candidates lane of Review (v128) — the old view_candidates'
    body, unindented from its own page. Status groups render actionable-first
    (candidate, needs_review — the ones with a decision waiting) then the
    rest alphabetically, so the lane opens on what needs your eye.

    Quality is ONE column (ADR 0008, retiring the old separate Priority /
    Quality pair) — see _quality_cell_html()."""
    cands = (read_json(QUESTION_CANDIDATES_FILE, default={}) or {}).get("candidates", [])
    if not cands:
        return _empty("No candidates yet.")
    # Category is only stamped at review time; until then infer it from the
    # candidate's neighborhood (target_category → neighborhood topic_type →
    # bank letter).
    neighborhoods = read_json(NEIGHBORHOODS_FILE, default={}) or {}
    cat_names = parse_categories(QUESTIONS_FILE.read_text(encoding="utf-8")) if QUESTIONS_FILE.exists() else {}
    quality_profile: dict | None = None
    try:
        from quality_profile import load_profile  # noqa: PLC0415
        quality_profile = load_profile()
    except Exception:  # noqa: BLE001 — best-effort; live fallback still works without it
        quality_profile = None
    by_status: dict[str, list[dict]] = {}
    for c in cands:
        by_status.setdefault(c.get("status", "candidate"), []).append(c)
    actionable_order = [s for s in ("candidate", "needs_review") if s in by_status]
    rest_order = sorted(s for s in by_status if s not in ("candidate", "needs_review"))
    parts = []
    for status in actionable_order + rest_order:
        group = by_status[status]
        parts.append(f"<h3>{html.escape(status)} ({len(group)})</h3>")
        rows = []
        for c in group:
            letter = _infer_category(c, neighborhoods)
            if letter:
                name = (cat_names.get(letter) or {}).get("name", "")
                cat_cell = html.escape(letter + (f" ({name})" if name else ""))
            else:
                cat_cell = '<span class="muted">unassigned</span>'
            question_cell = html.escape(str(c.get("text", ""))[:300])
            reason = str(c.get("needs_review_reason") or "").strip()
            if status == "needs_review" and reason:
                # Park reason quotes the unified score and its craft flags
                # (see auto_promote_candidates()'s park() calls) — shown
                # here so the reason a candidate is waiting is visible
                # without leaving the table.
                question_cell += f'<div class="q-park-reason muted">parked: {html.escape(reason)}</div>'
            row = [
                question_cell,
                _quality_cell_html(c, quality_profile),
                cat_cell,
                html.escape(str(c.get("story_function") or "—")),
                html.escape(str(c.get("source_path") or "—")),
            ]
            if status in ("candidate", "needs_review"):
                row.append(_candidate_actions(c, letter, cat_names))
            else:
                row.append(_history_reason_cell(c))
            rows.append(row)
        parts.append(_table(["Question", "Quality", "Category", "Story fn", "Source", "Actions"], rows))
    return "".join(parts)


def _candidate_actions(c: dict, inferred: str | None, cat_names: dict) -> str:
    """Promote / defer / dismiss forms for one reviewable candidate (v101).
    Promote requires a category — the picker defaults to the inferred one."""
    cid = html.escape(str(c.get("id", "")))
    options = "".join(
        f'<option value="{html.escape(letter)}"{" selected" if letter == inferred else ""}>'
        f'{html.escape(letter)}</option>'
        for letter in sorted(cat_names))
    return (
        f'<form class="actform act-inline" method="post" action="/actions/candidate">'
        f'{_token_input()}<input type="hidden" name="id" value="{cid}">'
        f'<input type="hidden" name="op" value="promote">'
        f'<select name="category">{options}</select>'
        f'<button class="btn" type="submit">Promote</button></form> '
        f'<form class="actform act-inline" method="post" action="/actions/candidate">'
        f'{_token_input()}<input type="hidden" name="id" value="{cid}">'
        f'<input type="hidden" name="op" value="defer">'
        f'<button class="btn quiet" type="submit">Defer</button></form> '
        f'<form class="actform act-inline" method="post" action="/actions/candidate">'
        f'{_token_input()}<input type="hidden" name="id" value="{cid}">'
        f'<input type="hidden" name="op" value="dismiss">'
        f'<button class="btn quiet" type="submit">Dismiss</button></form>')


def _entities_section_html() -> str:
    """Entity candidates lane of Review (v128) — the old view_entities' body,
    unchanged, minus its own page title."""
    parts = []
    for etype in ENTITY_TYPES:
        # Only show entities still in the candidate stage — anything that has
        # graduated (page-eligible) or already maps to a Focus has a wiki page,
        # so it's visible in the wiki itself and shouldn't be repeated here.
        ents = [
            e for e in load_roster(etype).get("entities", [])
            if not e.get("page_eligible") and not e.get("maps_to_focus")
        ]
        parts.append(f"<h3>{html.escape(etype.title())} ({len(ents)})</h3>")
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
    return "".join(parts)


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


def _read_state_json(filename: str) -> dict:
    """A state/<filename> cache written by update.py, tolerant of it being
    missing OR corrupt (an interrupted write is not this viewer's problem
    to raise on) — either reads as "nothing cached yet"."""
    try:
        data = read_json(STATE_DIR / filename, default=None)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _load_update_check() -> dict:
    """The most recent `update.py --check` result, cached to
    state/update_check.json by --check itself (lifehug#84 item 2) so the
    viewer never runs git on page load."""
    return _read_state_json("update_check.json")


def _load_last_update() -> dict:
    """The changelogs crossed by the most recent `--apply`, written by
    update.py (lifehug#84 item 4)."""
    return _read_state_json("last_update.json")


def _update_summary(data: dict) -> dict | None:
    """Shared interpretation of a cached --check result for BOTH the Loop
    view's card and the home hub card (lifehug#84) — one place decides what
    the numbers mean so the two render sites can't drift apart.

    `available_version` (max of the tags-only `latest` and `main_version`,
    written by update.py) is the true "how far behind" number; `latest`
    keeps its own tags-only meaning for anyone still reading the raw JSON.
    `apply_reaches` is whether `--apply` (which only ever reaches the
    highest TAG) would actually do anything right now — under a tag lapse
    where the tag ceiling already equals `current`, it would be a no-op, and
    callers must not show it as a live command."""
    current, latest = data.get("current"), data.get("latest")
    if not isinstance(current, int) or not isinstance(latest, int):
        return None
    available_version = data.get("available_version")
    if not isinstance(available_version, int):
        available_version = latest
    return {
        "current": current,
        "available_version": available_version,
        "behind": max(0, available_version - current),
        "apply_reaches": latest > current,
        "tag_lapse": bool(data.get("tag_lapse")),
        "diagnostic": data.get("diagnostic"),
    }


def _update_status_html() -> str:
    """The Loop view's update card: installed version, latest available,
    releases behind, the one command to run (only when it would do
    something), and the tag-lapse diagnostic — all from the cached check,
    never a live git call."""
    data = _load_update_check()
    summary = _update_summary(data)
    if summary is None:
        return ('<div class="update-status update-unknown">'
                'Update status unknown — run <code>python3 system/update.py --check</code>.'
                '</div>')
    dead_apply = summary["tag_lapse"] and not summary["apply_reaches"]
    parts = [f'<div class="update-status {"update-behind" if summary["behind"] else "update-current"}">']
    if dead_apply:
        # The tag ceiling already equals `current` — --apply is a no-op.
        # The diagnostic IS the headline; no command to show.
        parts.append(f'<div class="update-headline">⚠️ {html.escape(str(summary["diagnostic"]))}</div>')
    elif summary["behind"]:
        parts.append(
            f'<div class="update-headline">Lifehug v{summary["available_version"]} is available — '
            f'{summary["behind"]} release{"s" if summary["behind"] != 1 else ""} behind '
            f'(installed v{summary["current"]}).</div>'
        )
        parts.append('<div class="update-cmd"><code>python3 system/update.py --apply</code></div>')
    else:
        parts.append(f'<div class="update-headline">Lifehug is current (v{summary["current"]}).</div>')
    if summary["diagnostic"] and not dead_apply:
        parts.append(f'<div class="update-diagnostic">⚠️ {html.escape(str(summary["diagnostic"]))}</div>')
    checked_at = data.get("checked_at")
    if checked_at:
        parts.append(f'<div class="update-checked">Checked {html.escape(str(checked_at))}</div>')
    parts.append("</div>")
    return "".join(parts)


def _changelog_entry_html(entry: dict) -> str:
    """One crossed-version changelog line. Tag annotations already follow
    the "vN: ..." convention (see tag_on_merge), so a naive `f"v{v}: " +
    text` prepend doubles the prefix — strip any existing leading "vN: "
    before adding our own label."""
    version = entry.get("version")
    text = str(entry.get("changelog") or "")
    if version is not None:
        text = re.sub(rf"^v{re.escape(str(version))}:\s*", "", text, count=1)
        label = f"v{version}: "
    else:
        label = ""
    return f'<div class="update-changelog">{html.escape(label + text)}</div>'


def _last_update_html() -> str:
    """A 'what changed' line for the most recent applied update, so an
    update is an event the owner sees rather than a silent file swap. Only
    the first crossed changelog renders inline; the rest collapse into a
    <details> so a many-version jump doesn't flood the Loop view."""
    data = _load_last_update()
    to_version = data.get("to_version")
    if not isinstance(to_version, int):
        return ""
    from_version = data.get("from_version")
    applied_at = data.get("applied_at")
    headline = f"Updated v{from_version} → v{to_version}" if isinstance(from_version, int) else f"Updated to v{to_version}"
    if applied_at:
        headline += f" · {applied_at}"
    entries = [e for e in (data.get("crossed") or []) if isinstance(e, dict) and e.get("changelog")]
    parts = [f'<div class="update-last"><div class="update-headline">{html.escape(headline)}</div>']
    if entries:
        parts.append(_changelog_entry_html(entries[0]))
        rest = entries[1:]
        if rest:
            parts.append(f'<details class="update-more"><summary>{len(rest)} more change'
                          f'{"s" if len(rest) != 1 else ""}</summary>')
            parts.extend(_changelog_entry_html(e) for e in rest)
            parts.append("</details>")
    parts.append("</div>")
    return "".join(parts)


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
    return ("The Loop", "<h1>The Loop — System Status</h1>" + grid
             + _update_status_html() + _last_update_html(), False)


# ---------------------------------------------------------------------------
# Home action hub (v99)
#
# The home page answers "what should I do next?" with a few calm invitation
# cards — never a backlog, never guilt metrics. Each card grounds itself in
# real material, says why it's here now, and offers one verb. A small stats
# strip below shows state (not debt). Design notes: 3–5 cards max, at most one
# heavy introspective card, absence reads as stillness.
# ---------------------------------------------------------------------------

# Left-rule accent per invitation kind. Calm palette — no reds on the home page.
_HUB_ACCENTS = {
    "chapter": "#3f8f4f",
    "sit_with": "#5a7d9a",
    "question": "#987b55",
    "review": "#c79a2e",
    "perennial": "#7c4f1d",
    "second_voice": "#8a7a63",
    "memory": "#9a8c75",
    "update": "#6f7f8c",
    "quiet": "#c8c2b8",
}


def _daily_pick(n: int) -> int:
    """Stable index for today — the same pick all day, a fresh one tomorrow.
    (hash() is salted per process, so use a real digest.)"""
    today = datetime.date.today().isoformat()
    return int(hashlib.sha1(today.encode("utf-8")).hexdigest(), 16) % max(1, n)


def _invitation(kind, kicker, title, body, why="", href="", cta="", extra=""):
    return {"kind": kind, "kicker": kicker, "title": title, "body": body,
            "why": why, "href": href, "cta": cta, "extra": extra}


def _hub_card_update():
    """A calm card when the vault is >=1 version behind on framework updates
    (lifehug#84 item 2) — reads the cached result written by
    `update.py --check`; never runs git itself. Not a backlog nag: it names
    the exact command and gets out of the way. Lowest-priority builder (see
    home_data): maintenance never displaces a content invitation or the
    standing memory slot."""
    data = _load_update_check()
    summary = _update_summary(data)
    if summary is None or summary["behind"] < 1:
        return None
    dead_apply = summary["tag_lapse"] and not summary["apply_reaches"]
    if dead_apply:
        # --apply would be a no-op right now (the tag ceiling already equals
        # `current`) — the diagnostic IS the message, no dead command shown.
        body = str(summary["diagnostic"])
        why = ""
    else:
        body = (f"{summary['behind']} release{'s' if summary['behind'] != 1 else ''} behind. "
                "python3 system/update.py --apply")
        why = summary["diagnostic"] or ""
    return _invitation(
        "update", "System",
        f"Lifehug v{summary['available_version']} is available",
        body, why=why, href="/views/status", cta="See update details")


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
                    href="/views/studio", cta="Open the Studio")
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
    href = "/views/review"
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
        href="/views/foundation", cta="Open the Foundation")


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
    ack = (f'<form class="actform act-inline" method="post" action="/actions/second-voice-ack">'
           f'{_token_input()}<input type="hidden" name="key" value="{html.escape(key)}">'
           f'<button class="btn quiet" type="submit">Got it</button></form>')
    return _invitation(
        "second_voice", "If it comes up",
        f"A question for {person}",
        body + " Their answer becomes a second voice in the archive.",
        why="this month's second-voice offer — it expires silently if ignored",
        href=href, cta=cta, extra=ack)


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
    take down the front page. `_hub_card_update` is last (owner ruling,
    lifehug#84): "invitations, never guilt metrics" — maintenance never
    displaces a content invitation, so it only appears when the first four
    builders leave a slot free."""
    builders = [_hub_card_chapter, _hub_card_sit_with, _hub_card_next_question,
                _hub_card_review, _hub_card_perennial, _hub_card_second_voice,
                _hub_card_update]
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
    cta_bits = []
    if card.get("href") and card.get("cta"):
        cta_bits.append(f'<a href="{html.escape(card["href"])}">{html.escape(card["cta"])}</a>')
    if card.get("extra"):
        cta_bits.append(card["extra"])  # pre-rendered HTML (e.g. an ack form)
    cta = f'<div class="hub-cta">{" ".join(cta_bits)}</div>' if cta_bits else ""
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
                f'<span class="muted">· {html.escape(e["source_short"])} · '
                f'<a href="/source-actions?ref={quote(e["source"])}">act</a></span></li>'
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


@dataclass(frozen=True)
class SourceBodyRead:
    """One source captured through its already-validated, no-follow fd."""

    ref: str
    text: str | None
    manifest_record: dict


def _manifest_source_record(ref: str) -> dict | None:
    """Manifest membership is the approval boundary for raw body reads."""
    manifest = (read_json(SOURCE_MANIFEST_FILE, default={}) or {}).get("sources", {})
    if not isinstance(manifest, dict):
        return None
    direct = manifest.get(ref)
    if isinstance(direct, dict):
        return direct
    matches = [record for record in manifest.values()
               if isinstance(record, dict) and record.get("source_path") == ref]
    return matches[0] if len(matches) == 1 else None


def read_source_ref(ref: str, *, include_body: bool = False) -> SourceBodyRead | None:
    """Validate and read one exact manifested source through the vault's
    no-follow I/O authority (vault_paths.open_vault_fd / read_vault_bytes).

    Deliberately reject normalization instead of repairing a request: absolute
    paths, dot segments, duplicate separators, encoded leftovers, backslashes,
    NULs, non-Markdown targets, directories, untracked files, and symlinks at
    any level fail closed. vault_paths pins a no-follow directory-descriptor
    walk from the answers/sources root to the final regular-file descriptor
    and re-verifies the parent binding before the final open, closing the
    validate / reopen race. This is the only raw source-body reader; route
    and link code must not resolve or open a source path itself.
    """
    if not isinstance(ref, str):
        return None
    raw = ref
    if not raw or raw != raw.strip() or "\x00" in raw or "\\" in raw or "%" in raw:
        return None
    try:
        relative = Path(raw)
    except (TypeError, ValueError):
        return None
    if relative.is_absolute() or relative.as_posix() != raw:
        return None
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        return None
    if relative.suffix.lower() != ".md":
        return None
    if relative.parts[0] == "answers":
        root, tail = ANSWERS_DIR, relative.parts[1:]
    elif relative.parts[0] == "sources":
        root, tail = SOURCES_DIR, relative.parts[1:]
    else:
        return None
    if not tail:
        return None
    record = _manifest_source_record(raw)
    if record is None:
        return None

    tail_path = Path(*tail)
    try:
        if include_body:
            content = read_vault_bytes(tail_path, vault_root=root)
        else:
            fd = open_vault_fd(tail_path, os.O_RDONLY, vault_root=root)
            os.close(fd)
            content = None
    except (FileNotFoundError, ValueError, OSError, TypeError):
        return None
    text = content.decode("utf-8", "replace") if content is not None else None
    return SourceBodyRead(raw, text, dict(record))


def source_href(ref: str) -> str | None:
    """Return the canonical viewer URL only for a manifested file readable now."""
    return f"/source/{quote(ref, safe='/')}" if read_source_ref(ref) else None


_SAFE_SOURCE_METADATA = (
    ("title", "Title"),
    ("type", "Type"),
    ("source_id", "Source ID"),
    ("question_id", "Question"),
    ("captured_at", "Captured"),
    ("source_medium", "Medium"),
    ("source_trust", "Trust"),
    ("authority", "Authority"),
    ("visibility", "Visibility"),
    ("status", "Status"),
    ("immutable", "Immutable"),
    ("schema_version", "Schema"),
    ("content_sha256", "Content hash"),
)


def source_document_html(ref: str) -> tuple[str, str] | None:
    """Render an approved raw source without changing it or derived state."""
    source = read_source_ref(ref, include_body=True)
    if source is None or source.text is None:
        return None
    frontmatter, body_text = split_frontmatter(source.text)
    metadata = dict(source.manifest_record)
    metadata.update({key: value for key, value in frontmatter.items()
                     if key in {name for name, _label in _SAFE_SOURCE_METADATA}})
    metadata["source_path"] = ref
    heading = re.search(r"^#\s+(.+?)\s*$", body_text, re.MULTILINE)
    title = str(metadata.get("title") or (heading.group(1).strip() if heading else "")
                or Path(source.ref).stem.replace("-", " ").title())
    rows = [[html.escape(label), html.escape(str(metadata[name]))]
            for name, label in _SAFE_SOURCE_METADATA
            if name in metadata and metadata[name] not in (None, "")]
    rows.insert(0, ["Path", f"<code>{html.escape(ref)}</code>"])
    toolbar = (
        '<div class="source-toolbar">'
        '<a href="/views/sources">Source Integrity</a>'
        f'<a href="/source-actions?ref={quote(ref)}">Reflect, correct, or retract</a>'
        '</div>'
    )
    body = (
        f"<h1>{html.escape(title)}</h1>"
        '<p class="view-desc">Read-only owner source. The original file remains immutable; '
        'changes belong in an additive reflection, correction, or retraction.</p>'
        + toolbar
        + '<div class="source-meta"><h2>Safe metadata</h2>'
        + _table(["Field", "Value"], rows)
        + '</div><article class="source-body">'
        + render_markdown(body_text)
        + "</article>"
    )
    return title, body


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
    by_type: dict[str, list[tuple[str, dict]]] = {}
    for key, s in manifest.items():
        by_type.setdefault(s.get("type", "unknown"), []).append((key, s))
    parts.append(_h2(f"Captured sources ({len(manifest)})"))
    if not manifest:
        parts.append(_empty("No sources tracked yet."))
    for t in sorted(by_type):
        parts.append(f"<h3>{html.escape(t)} ({len(by_type[t])})</h3>")
        rows = []
        for key, s in by_type[t]:
            ref = str(s.get("source_path") or key)
            href = source_href(ref)
            label = html.escape(str(s.get("title", s.get("source_id", "?"))))
            title_cell = f'<a href="{href}">{label}</a>' if href else label
            rows.append([
                title_cell,
                html.escape(str(s.get("captured_at") or s.get("first_seen_at") or "—")),
                html.escape(str(s.get("source_medium", "—"))),
                _badge("changed", "yellow") if s.get("changed_since_first_seen") else _badge("stable", "green"),
                f'<a href="/source-actions?ref={quote(ref)}">act</a>',
            ])
        parts.append(_table(["Title", "Captured", "Medium", "Integrity", ""], rows))
    return ("Source Integrity", "".join(parts), False)


def view_answers():
    """Answers (issue #110) — the ledger of everything answered, parity twin
    of lifehug-platform#368. Lists every answers/*.md newest-first by
    answered_date (missing dates sort last, shown as "unknown"): question
    text, category, date, and an approximate body word count. Filing here is
    synchronous (the CLI writes the file directly), so there is no
    in-flight/parked status column the way the hosted twin has — that
    explanation lives in VIEW_DESCRIPTIONS below, the view's own header
    line."""
    files = sorted(ANSWERS_DIR.glob("*.md")) if ANSWERS_DIR.exists() else []
    entries = []
    for path in files:
        try:
            content = read_text(path, errors="replace")
        except OSError as exc:
            _record_view_failure("view-answers-read", exc)
            continue
        metadata, _body = split_frontmatter(content)
        date = str(metadata.get("answered_date") or "").strip()
        question_text = str(metadata.get("question_text") or metadata.get("title") or path.stem).strip()
        category = str(metadata.get("category_name") or metadata.get("category") or "—").strip()
        word_count = len(answer_body(content).split())
        entries.append({
            "filename": path.name,
            "date": date,
            "question_text": question_text or path.stem,
            "category": category or "—",
            "word_count": word_count,
        })

    parts = ["<h1>Answers</h1>"]
    if not entries:
        parts.append(_empty(
            "No answers yet — answer a daily question and it will show up here."))
        return ("Answers", "".join(parts), False)

    dated = [e for e in entries if e["date"]]
    undated = [e for e in entries if not e["date"]]
    dated.sort(key=lambda e: e["date"], reverse=True)
    first_date = min((e["date"] for e in dated), default="unknown")
    last_date = max((e["date"] for e in dated), default="unknown")
    plural = "" if len(entries) == 1 else "s"
    parts.append(
        f'<p class="view-summary">{len(entries)} answer{plural} · '
        f"{html.escape(first_date)} → {html.escape(last_date)}</p>")

    rows = [[
        html.escape(e["question_text"]),
        html.escape(e["category"]),
        html.escape(e["date"] or "unknown"),
        str(e["word_count"]),
        f'<a href="/source-actions?ref={quote("answers/" + e["filename"])}">act</a>',
    ] for e in dated + undated]
    parts.append(_table(["Question", "Category", "Date", "Words", ""], rows))
    return ("Answers", "".join(parts), False)


def _recommendations_section_html() -> str:
    """Focus ideas lane of Review (v128/v134) — the old view_recommendations'
    body, plus a live-computed "Ready" column (issue #79). Ready-to-start is
    recomputed HERE from focus_start_gate() (live) and each rec's stored
    score against FOCUS_READY_SCORE_FLOOR — never trusted from a stored
    ready_to_start flag, which can go stale between recommendation refreshes
    and the gate's current state; this lane must never contradict its own
    policy line above it."""
    data = read_json(FOCUS_RECS_FILE, default={}) or {}
    recs = data.get("recommendations", [])
    dismissed = data.get("dismissed", [])
    pending = [r for r in recs if r.get("status") == "pending"]
    others = [r for r in recs if r.get("status") != "pending"]
    parts = [f"<h3>Pending ({len(pending)})</h3>"]
    if pending:
        gate = focus_start_gate()

        def rec_actions(r: dict) -> str:
            rid = html.escape(str(r.get("id", "")))
            return (
                f'<form class="actform act-inline" method="post" action="/actions/focus-rec">'
                f'{_token_input()}<input type="hidden" name="id" value="{rid}">'
                f'<input type="hidden" name="op" value="approve">'
                f'<button class="btn" type="submit">Approve</button></form> '
                f'<form class="actform act-inline" method="post" action="/actions/focus-rec">'
                f'{_token_input()}<input type="hidden" name="id" value="{rid}">'
                f'<input type="hidden" name="op" value="dismiss">'
                f'<button class="btn quiet" type="submit">Dismiss</button></form>')

        def _is_ready(r: dict) -> bool:
            return gate["open"] and (r.get("score", 0) or 0) >= FOCUS_READY_SCORE_FLOOR

        rows = [[
            html.escape(str(r.get("entity", "?"))),
            html.escape(str(r.get("type", "?"))),
            format(r.get("score", 0) or 0, ".1f"),
            html.escape(str(r.get("evidence_strength", "—"))),
            str(r.get("mention_count", 0)),
            html.escape(",".join(r.get("cross_categories", []))),
            (_badge("ready to start", "green") if _is_ready(r) else "—"),
            html.escape(str(r.get("reason", ""))[:240]),
            rec_actions(r),
        ] for r in sorted(pending, key=lambda r: r.get("score", 0) or 0, reverse=True)]
        parts.append(_table(["Entity", "Type", "Score", "Evidence", "Mentions", "Cats", "Ready", "Reason", "Actions"], rows))
    else:
        parts.append(_empty("No pending recommendations."))
    if others:
        parts.append(f"<h3>Acted on ({len(others)})</h3>")
        parts.append(_table(["Entity", "Status"],
                            [[html.escape(str(r.get("entity", "?"))), html.escape(str(r.get("status", "?")))] for r in others]))
    if dismissed:
        parts.append(f"<h3>Dismissed ({len(dismissed)})</h3>")
        parts.append(_table(["Entity", "Reason"],
                            [[html.escape(str(r.get("entity", "?"))), html.escape(str(r.get("dismiss_reason", "")))] for r in dismissed]))
    return "".join(parts)


def _focus_ideas_policy_line() -> str:
    """Focus ideas lane policy line (issue #79, resolved) — reflects the
    completion gate's actual state instead of a static 'planned threshold'
    note. Owner approval is unchanged either way; the gate only decides
    whether a strong pending idea may show as ready to start.

    Focus labels and the gate's reason text can originate from
    LLM/imported-source entities (approve_recommendation creates Focuses
    from recommendation entity names) — every interpolated value is
    html.escape()'d before being embedded."""
    gate = focus_start_gate()
    if gate["open"]:
        return (
            "focuses are never created without you — approving one "
            "redirects the weekly question budget; the completion gate is "
            "open, so strong pending ideas can show as ready to start "
            "(lifehug/lifehug#79, resolved)")
    n = len(gate["blocking"])
    labels = ", ".join(html.escape(str(b.get("label", ""))) for b in gate["blocking"])
    return (
        "focuses are never created without you — and starting new ones is "
        f"gated while {n} open focus{'es' if n != 1 else ''} "
        f"{'are' if n != 1 else 'is'} unfinished ({labels}) "
        "(lifehug/lifehug#79, resolved)")


def view_review():
    """Review (v128) — the system's three self-grown proposal lanes on one
    page: question candidates the classifier proposed, focus ideas grown
    from entity evidence, and entity candidates auto-detected across
    answers. Consolidates the old Question Candidates / Focus
    Recommendations / Entity Candidates views into three collapsible
    lanes — the fnd-focus idiom Foundation (v124) and Studio (v127)
    established — each carrying its own autonomy-level policy line so it's
    obvious at a glance which lane needs your judgment (question candidates,
    focus ideas) and which is pure FYI (entity candidates)."""
    stats = loop_stats()
    open_cands, pending_recs = stats["open_cands"], stats["pending_recs"]
    entity_total = sum(
        len([e for e in load_roster(t).get("entities", [])
             if not e.get("page_eligible") and not e.get("maps_to_focus")])
        for t in ENTITY_TYPES)

    parts = [
        "<h1>Review</h1>",
        f"<p>{open_cands} question candidate{'s' if open_cands != 1 else ''} waiting · "
        f"{pending_recs} focus idea{'s' if pending_recs != 1 else ''} pending · "
        f"{entity_total} entity candidate{'s' if entity_total != 1 else ''}</p>",
    ]

    # Lanes with something actionable start open: Review exists to be acted
    # on, and the hub card's CTA should land on the work, not on three
    # closed bars. The FYI entity lane always starts collapsed.
    cand_open = " open" if open_cands else ""
    rec_open = " open" if pending_recs else ""

    parts.append(
        f'<details class="fnd-focus"{cand_open}><summary>'
        '<div class="focus-head"><span class="focus-label">Question candidates</span> '
        f'{_badge(open_cands)}</div>'
        '<div class="focus-sub">auto-promote at quality ≥ '
        f'{AUTO_PROMOTE_THRESHOLD} under weekly caps — these are below the '
        'line or awaiting review</div>'
        '</summary><div class="fnd-cats">'
        + _candidates_section_html()
        + '</div></details>')

    parts.append(
        f'<details class="fnd-focus"{rec_open}><summary>'
        '<div class="focus-head"><span class="focus-label">Focus ideas</span> '
        f'{_badge(pending_recs)}</div>'
        f'<div class="focus-sub">{_focus_ideas_policy_line()}</div>'
        '</summary><div class="fnd-cats">'
        + _recommendations_section_html()
        + '</div></details>')

    parts.append(
        '<details class="fnd-focus"><summary>'
        '<div class="focus-head"><span class="focus-label">Entity candidates</span> '
        f'{_badge(entity_total)}</div>'
        '<div class="focus-sub">fully automatic — qualifying entities '
        'graduate into wiki pages at the next compile; this is a preview, '
        'no action needed</div>'
        '</summary><div class="fnd-cats">'
        + _entities_section_html()
        + '</div></details>')

    return ("Review", "".join(parts), False)


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
.tl-placeform { margin-top: 6px; }
.tl-placeform select, .tl-placeform input[type=text], .tl-placeform input:not([type]) {
  font-size: 12px; padding: 3px 6px; border: 1px solid #c8c2b8; border-radius: 5px;
  max-width: 200px; }
.tl-placeform .btn { font-size: 12px; padding: 3px 10px; }
.tl-placeform form { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
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
        import timeline_corroboration as tcorr  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        _record_view_failure("timeline-import", exc)
        return ("Timeline", f"<h1>Timeline</h1>{_empty('timeline temporarily unavailable')}", False)

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
        if period.get("corroboration"):
            # v110: connector date-evidence badge — "✉ asu ×1100 · 2010–2013".
            summary_bits.append(f"✉ {html.escape(tcorr.badge_text(period['corroboration']))}")
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
            email_badge = ""
            if event.get("corroboration"):
                # v110: matched connector records, count + span (contradiction
                # conflicts surface separately as gap cards below).
                email_badge = (f" <span class='tl-evidence'>✉ "
                               f"{html.escape(tcorr.badge_text(event['corroboration']))}</span>")
            pin = ""
            if event.get("placement") == "manual":
                unplace = (f'<form class="actform act-inline" method="post" '
                           f'action="/actions/timeline/unplace">{_token_input()}'
                           f'<input type="hidden" name="key" value="{html.escape(event["placement_key"])}">'
                           f'<button class="btn quiet" type="submit" title="remove manual placement">unpin</button></form>')
                corr = event.get("placement_correction") or ""
                assertion = (f' · <a href="/source-actions?ref={quote(corr)}">assertion</a>'
                             if corr else "")
                caught_up = (" · the loop caught up — this now places itself; the pin retires on the next weekly pass"
                             if event.get("placement_redundant") else "")
                pin = f" <span class='tl-evidence'>📌 placed by you{assertion}{caught_up} · {unplace}</span>"
            return (f"<div class='tl-dot{undated}'>{when}{html.escape(event['description'])}{anchor}{email_badge}{pin}"
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
        period_options = "".join(
            f'<option value="{html.escape(p["slug"])}">{html.escape(p["name"])}</option>'
            for p in data["periods"])
        for event in data["unplaced_events"]:
            when = f"<strong>{html.escape(event['when_hint'])}</strong> — " if event["when_hint"] else ""
            place_form = (
                f'<form class="actform act-inline" method="post" action="/actions/timeline/place">'
                f'{_token_input()}'
                f'<input type="hidden" name="source" value="{html.escape(event["source"])}">'
                f'<input type="hidden" name="description" value="{html.escape(event["description"])}">'
                f'<select name="period"><option value="">where does this belong?</option>{period_options}</select>'
                f'<input name="when_hint" placeholder="when? (your own words)" '
                f'value="{html.escape(event["when_hint"])}">'
                f'<button class="btn" type="submit">Place</button></form>')
            parts.append(f"<div class='tl-dot undated' style='margin-left:0'>{when}"
                         f"{html.escape(event['description'])}"
                         f"<div class='tl-evidence'>source: {html.escape(event['source_short'])}</div>"
                         f"<div class='tl-placeform'>{place_form}</div></div>")
        if data["unplaced_entities"]:
            chips = "".join(
                f"<span class='tl-chip'>{link(row['title'], page_rel=row['page'])}</span>"
                for row in data["unplaced_entities"])
            parts.append(f"<div class='tl-chips'>{chips}</div>")
        parts.append("</details>")

    for gap in data["global_gaps"]:
        hint = f" <span class='tl-evidence'>{html.escape(gap['hint'])}</span>" if gap.get("hint") else ""
        parts.append(f"<div class='tl-gap'>◌ {html.escape(gap['message'])}{hint}</div>")

    # Manual placements orphaned by reclassification — removable, never
    # silently misapplied.
    for stale in data.get("stale_placements", []):
        remove = (f'<form class="actform act-inline" method="post" action="/actions/timeline/unplace">'
                  f'{_token_input()}<input type="hidden" name="key" value="{html.escape(str(stale.get("key", "")))}">'
                  f'<button class="btn quiet" type="submit">remove</button></form>')
        parts.append(f"<div class='tl-gap'>📌 A placement you made no longer matches any moment "
                     f"(“{html.escape(str(stale.get('description', ''))[:100])}” → "
                     f"{html.escape(str(stale.get('period', '')))}) — the source was probably "
                     f"reclassified. {remove}</div>")

    parts.append(
        "<div class='tl-foot'>This is what I currently understand of your chronology — "
        "placements are proven by shared sources (shown in parentheses), never guessed, "
        "except the 📌 ones you placed yourself, which outrank every heuristic. "
        "See something wrong? Place it above — placing files the fact into the archive "
        "itself, so the system relearns it — use <code>lifehug.py fix</code>, or just tell "
        "the bot. Dates arrive as answers are classified — always your own time-words and "
        "landmark anchors, never inferred years.</div>")

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

    nav = ['<a href="/views/studio">← Studio</a>']
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
    text = path.read_text(errors="replace")
    body.append(f"<blockquote>{render_markdown(text)}</blockquote>")
    body.append(_artifact_actions_html(slug, number, text, is_final=(final == number)))
    return f"{title} — v{number}", "".join(body)


def _artifact_actions_html(slug: str, number: int, text: str, is_final: bool) -> str:
    """The write-action panel on a version page (v101): direct edit → vN+1,
    AI revise (job or agent-task when keyless), mark final, promote, record
    delivery. Every action shells the artifact CLI."""
    s = html.escape(slug)
    hidden = f'{_token_input()}<input type="hidden" name="slug" value="{s}">'
    ai_note = "" if _ai_route() else \
        ' <span class="muted">(keyless — will queue for agent completion)</span>'
    parts = ['<details class="art-actions"><summary>Act on this piece</summary>']
    parts.append(
        f'<h3>Edit directly</h3>'
        f'<form class="actform" method="post" action="/actions/artifact/save">{hidden}'
        f'<textarea name="content" rows="14">{html.escape(text)}</textarea>'
        f'<label>Note (optional — shows in the revision footer)</label>'
        f'<input name="note" placeholder="hand-edit: tightened the middle">'
        f'<div class="act-row"><button class="btn" type="submit">Save as v{number + 1}</button></div></form>')
    parts.append(
        f'<h3>Revise with AI{ai_note}</h3>'
        f'<form class="actform" method="post" action="/actions/artifact/revise">{hidden}'
        f'<input name="feedback" placeholder="warmer, shorter, less formal" required>'
        f'<div class="act-row"><button class="btn" type="submit">Revise</button></div></form>')
    lifecycle = []
    if not is_final:
        lifecycle.append(
            f'<form class="actform act-inline" method="post" action="/actions/artifact/final">{hidden}'
            f'<input type="hidden" name="version" value="{number}">'
            f'<button class="btn" type="submit">Mark v{number} final</button></form>')
    lifecycle.append(
        f'<form class="actform act-inline" method="post" action="/actions/artifact/promote">{hidden}'
        f'<button class="btn" type="submit">Promote to source</button></form>')
    parts.append(f'<h3>Lifecycle</h3><div class="act-row">{" ".join(lifecycle)}</div>')
    parts.append(
        f'<h3>Record delivery</h3>'
        f'<p class="muted">A letter isn\'t done until it\'s given — the reaction saves as their witness account.</p>'
        f'<form class="actform" method="post" action="/actions/artifact/delivered">{hidden}'
        f'<label>To</label><input name="to" placeholder="Mom">'
        f'<label>How it went (optional)</label><input name="note">'
        f'<label>Their reaction (optional)</label>'
        f'<textarea name="reaction" rows="3" placeholder="She read it twice and…"></textarea>'
        f'<div class="act-row"><button class="btn" type="submit">Record delivery</button></div></form>')
    parts.append("</details>")
    return "".join(parts)


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
    nav = ['<a href="/views/studio">← Studio</a>',
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


def _format_spec(format_id: str) -> dict | None:
    """One format framework spec, or None (unknown id, or specs not on disk).

    format_frameworks binds the process to a vault on its first registry call,
    so every viewer entry point routes through here and never lets a registry
    problem take a page down.
    """
    try:
        import format_frameworks  # noqa: PLC0415
        return format_frameworks.get_or_none(str(format_id))
    except Exception as exc:  # noqa: BLE001
        _record_view_failure("format-spec", exc)
        return None


def _format_label(format_id: str) -> str:
    spec = _format_spec(format_id)
    if isinstance(spec, dict) and spec.get("label"):
        return str(spec["label"])
    return str(format_id).replace("_", " ").title()


def _format_choices() -> list[tuple[str, str]]:
    """(id, "Label — summary") for every composable format, canonical order."""
    try:
        import format_frameworks  # noqa: PLC0415
        ids = list(format_frameworks.valid_formats())
    except Exception as exc:  # noqa: BLE001
        _record_view_failure("format-choices", exc)
        return []
    choices = []
    for fid in ids:
        spec = _format_spec(fid)
        if isinstance(spec, dict):
            label = str(spec.get("label") or fid)
            summary = str(spec.get("summary") or "")
            text = f"{label} — {summary}" if summary else label
        else:
            text = str(fid).replace("_", " ").title()
        choices.append((str(fid), text))
    return choices


def _studio_create_form() -> str:
    """"Start something new" (v127): the one door into a new piece.

    Collapsed by default — the Studio's first job is showing what exists — and
    posting to /actions/artifact/new, which queues the same `artifact new` CLI
    the terminal runs. The redirect can't know the slug the CLI will mint, so
    the flash names the format and subject instead of linking the piece.
    """
    options = "".join(
        f'<option value="{html.escape(fid)}">{html.escape(text)}</option>'
        for fid, text in _format_choices())
    if not options:
        options = '<option value="letter">Letter</option>'
    return (
        '<details class="fnd-focus studio-new"><summary>'
        '<div class="focus-head"><span class="focus-label">Start something new</span> '
        + _badge("create", "saturated")
        + '</div><div class="focus-sub">Pick a format and name a subject — the '
        'Studio gathers the material and opens a new piece.</div></summary>'
        '<div class="fnd-cats">'
        f'<form class="actform" method="post" action="/actions/artifact/new">{_token_input()}'
        '<label>Format</label>'
        f'<select name="format">{options}</select>'
        '<label>Subject</label>'
        '<input name="subject" placeholder="Mom">'
        '<label>Occasion (optional)</label>'
        "<input name=\"occasion\" placeholder=\"Mother's Day\">"
        '<label>Date (optional)</label>'
        '<input type="date" name="date">'
        '<label>Title (optional)</label>'
        '<input name="title" placeholder="A letter for Mom">'
        '<label>Categories (optional)</label>'
        '<input name="categories" placeholder="K,L">'
        '<p class="muted"><small>advanced: category letters from the question '
        'bank — narrows the material this piece is built from.</small></p>'
        '<div class="act-row"><button class="btn" type="submit">Start it</button></div>'
        '</form></div></details>')


def _readiness_chips(readiness: list[dict] | None) -> str:
    """"Letter · 4/5 · READY" chips for a Focus's non-book formats (v126)."""
    chips = []
    for card in readiness or []:
        tag = str(card.get("verdict", "") or "")
        chips.append(_badge(
            f'{_format_label(card.get("format", ""))} · '
            f'{card.get("filled_slots", 0)}/{card.get("total_slots", 0)} · {tag}',
            tag.lower()))
    return " ".join(chips)


def _piece_html(a: dict) -> str:
    """One piece card — the Artifacts view's per-piece rendering, plus actions.

    The card body is carried over verbatim; NEW on this surface is the v101
    write-action panel for the latest version (previously reachable only from
    the /artifact-version/ page).

    Input is a piece dict from studio._scan_pieces (byte-identical fields to
    the scan this was extracted from). Badges (format, occasion, delivered,
    promoted), the meta line with linked PDF/image sidecars, the latest text
    readable inline, the v98 revision footer (numbered version links, ★ final,
    Δ diffs), and the v101 write-action panel for the latest version.
    """
    parts = []
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
    parts.append(f"<h3>{html.escape(title)} {badges}</h3>")
    parts.append(f"<p><small>{' · '.join(meta_bits)}</small></p>")
    if a["body"]:
        rendered = render_markdown(a["body"])
        parts.append(
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
        parts.append(
            f'<p class="rev-footer"><small>Revisions: {" ".join(links)}</small></p>')
        # The same write-action panel the version page carries (v101), pointed
        # at the latest version so save/revise/final/promote/delivered are one
        # click away from the piece itself.
        latest_n = a["version_numbers"][-1]
        parts.append(_artifact_actions_html(
            a["slug"], latest_n, a["body"],
            is_final=(a["final_version"] == latest_n)))
    return "".join(parts)


def _book_chapter_table(b: dict) -> str:
    """The Book Assembly chapter table (v75), intact — moved here from the
    retired view_book so the Studio's book project card can nest it."""
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
    return _table(["Cat", "Chapter", "Answered", "Scene depth", "Draft", "Verdict",
                   "Next questions / draft"], rows)


def _book_project_card(b: dict) -> str:
    """A book project inside its Focus group: the v75 header row (verdict,
    saturation bar, manuscript rollup) with the chapter table one expand
    deeper, and the assemble button once anything is actually drafted."""
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
    parts = [
        '<div class="studio-project">',
        '<div class="focus-row"><div class="focus-head">'
        f'<span class="focus-label">📖 {html.escape(str(b.get("label", "")))}</span> {badges}</div>'
        + head_bar
        + f'<div class="focus-sub">{html.escape(str(b.get("objective", "")))} '
        f'→ {html.escape(str(b.get("deliverable", "book")))} · {ms}</div></div>',
        '<details class="art-group"><summary>'
        '<span class="art-group-title">Chapters</span>'
        f'<span class="art-group-counts">{b["chapter_count"]} chapter(s) · '
        f'{b["chapters_ready"]} ready</span></summary>'
        '<div class="art-group-body">',
        _book_chapter_table(b),
    ]
    if any(ch.get("has_draft") for ch in b["chapters"]):
        parts.append(
            '<form class="actform" method="post" action="/actions/artifact/assemble">'
            + _token_input()
            + f'<input type="hidden" name="focus" value="{html.escape(str(b.get("id", "")))}">'
            '<div class="act-row"><button class="btn" type="submit">'
            'Assemble manuscript draft</button></div></form>')
    parts.append("</div></details></div>")
    return "".join(parts)


def view_studio():
    """Studio (v127) — where material becomes things, on one page.

    Consolidates the old Book Assembly and Artifacts views into a single
    Focus-grouped surface backed by studio.compute_works(): each Focus is a
    collapsed bar (the Foundation idiom) carrying its readiness chips; expand
    it for its projects (the book, with the v75 chapter table one level
    deeper and an assemble button) and its pieces (the full Artifacts card —
    badges, inline text, revision footer, write actions). "Start something
    new" sits at the top because the answer to an empty Studio is always the
    same one verb.
    """
    try:
        import studio as studio_mod  # noqa: PLC0415
        groups = studio_mod.compute_works()
    except Exception as exc:  # noqa: BLE001
        _record_view_failure("studio", exc)
        return ("Studio", "<h1>Studio</h1>" + _studio_create_form()
                + _empty("studio view temporarily unavailable"), True)

    parts = ["<h1>Studio</h1>", _studio_create_form()]
    if not groups:
        parts.append(_empty(
            "Nothing in the studio yet — pick a format above and name a "
            "subject, and your first piece starts here."))
        return ("Studio", "".join(parts), True)

    total_projects = sum(len(g.get("projects") or []) for g in groups)
    total_pieces = sum(len(g.get("pieces") or []) for g in groups)
    summary_bits = [f"{total_projects} project(s)", f"{total_pieces} piece(s) in <code>outputs/</code>"]
    parts.append(f"<p>{' · '.join(summary_bits)}, grouped by Focus.</p>")
    if not total_projects:
        parts.append('<p class="muted">No projects yet — a Focus with a '
                     'book-class deliverable becomes a project card with a '
                     'chapter map.</p>')

    for group in groups:
        focus = group.get("focus")
        projects = group.get("projects") or []
        pieces = group.get("pieces") or []
        hint = ""
        chips = ""
        if focus:
            label = str(focus.get("label", "?"))
            head = label
            if focus.get("type") == "person":
                # Distinct given names from the pieces themselves ("Mom (Desi)").
                names = sorted({p["subject"].strip().title() for p in pieces
                                if p["subject"].strip()
                                and p["subject"].strip().lower() != label.lower()})
                if names:
                    head = f"{label} ({', '.join(names)})"
            head = html.escape(head)
            node = focus.get("wiki_node")
            if node:
                head = f'<a href="/page/{quote(str(node))}">{head}</a>'
            counts = (f"{len(projects)} project(s) · {len(pieces)} piece(s) · "
                      f"{focus.get('type', '?')} → {focus.get('deliverable', '-')} "
                      f"· categories {','.join(focus.get('categories', []))}")
            chips = _readiness_chips(group.get("readiness"))
        elif group.get("key") == "__thoughts__":
            head = "Thoughts"
            counts = f"{len(pieces)} piece(s) · essays — the author's stated positions"
        else:
            head = "Unfiled"
            counts = f"{len(pieces)} piece(s) · no matching Focus"
            hint = ("<p><small>Add <code>subject:</code> / <code>categories:</code> to "
                    "each folder's <code>meta.yaml</code> to file these under a "
                    "Focus.</small></p>")
        parts.append(
            '<details class="fnd-focus"><summary>'
            f'<div class="focus-head"><span class="focus-label">{head}</span> {chips}</div>'
            f'<div class="focus-sub">{html.escape(counts)}</div>'
            '</summary><div class="fnd-cats">')
        parts.append(hint)
        parts.extend(_book_project_card(p["book"]) for p in projects if p.get("book"))
        parts.extend(_piece_html(a) for a in pieces)
        if not projects and not pieces:
            parts.append(_empty("Nothing made for this Focus yet."))
        parts.append("</div></details>")
    return ("Studio", "".join(parts), True)


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


# ---------------------------------------------------------------------------
# Write actions (v101)
#
# The browser becomes a review-and-write studio: every mutation shells out to
# the existing lifehug.py CLI (never reimplemented), guarded by a per-process
# session token + exact loopback checks. Every browser mutation is durably
# queued; system/jobs.py's worker executes the canonical CLI outside the HTTP
# request while holding the same writer lease as Telegram and schedules.
# AI-dependent actions degrade to agent-task queues on keyless machines.
# ---------------------------------------------------------------------------

SESSION_TOKEN = secrets.token_hex(16)
_SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _f(form: dict, key: str, default: str = "") -> str:
    return (form.get(key) or [default])[0].strip()


def _ai_route() -> str | None:
    try:
        from ai_provider import provider_status  # noqa: PLC0415
        status = provider_status(probe=False)
        return status.provider if status.ready else None
    except Exception:  # noqa: BLE001
        return None


def _start_job(kind: str, payload: dict | None = None) -> dict:
    import jobs  # noqa: PLC0415
    return jobs.enqueue(kind, payload or {})


def _token_input() -> str:
    return f'<input type="hidden" name="_token" value="{SESSION_TOKEN}">'


def _outputs_ref(form: dict) -> str | None:
    slug = _f(form, "slug")
    if not _SLUG_RE.match(slug):
        return None
    return f"outputs/{slug}"


# --- action handlers: each returns (redirect_path, flash_message, job_id) ---

def act_candidate(form):
    cid, op = _f(form, "id"), _f(form, "op")
    if op == "promote":
        cat = _f(form, "category")
        if not cat:
            return ("/views/review", "✗ pick a category before promoting", None)
        job = _start_job("candidate-promote", {"candidate_id": cid, "category": cat})
        return ("/views/review", f"queued promotion {cid} → {cat}", job["id"])
    if op == "dismiss":
        job = _start_job("candidate-update", {
            "candidate_id": cid, "status": "rejected", "reason": "dismissed from viewer",
        })
        return ("/views/review", f"queued dismissal of {cid}", job["id"])
    if op == "defer":
        job = _start_job("candidate-update", {
            "candidate_id": cid, "status": "deferred", "reason": "deferred from viewer",
        })
        return ("/views/review", f"queued deferral of {cid}", job["id"])
    return ("/views/review", "✗ unknown candidate action", None)


def act_focus_rec(form):
    rid, op = _f(form, "id"), _f(form, "op")
    if op == "approve":
        # focus-approve scaffolds a category and generates starter questions
        # (AI when available) — minutes, not milliseconds: run as a job.
        job = _start_job("focus-approve", {"recommendation_id": rid})
        return ("/views/review",
                f"approving {rid} — scaffolding the Focus (starter questions may take a minute)",
                job["id"])
    if op == "dismiss":
        job = _start_job("focus-dismiss", {
            "recommendation_id": rid,
            "reason": _f(form, "reason") or "dismissed from viewer",
        })
        return ("/views/review", f"queued dismissal of {rid}", job["id"])
    return ("/views/review", "✗ unknown recommendation action", None)


def act_second_voice(form):
    job = _start_job("second-voice-ack", {"key": _f(form, "key")})
    return ("/", "queued acknowledgment — the card will step aside", job["id"])


def act_artifact_save(form):
    ref = _outputs_ref(form)
    content = (form.get("content") or [""])[0]
    if not ref or not content.strip():
        return ("/views/studio", "✗ missing artifact or empty content", None)
    note = _f(form, "note")
    job = _start_job("artifact-save", {"ref": ref, "content": content, "note": note})
    return ("/views/studio", f"queued a new version of {ref}", job["id"])


def act_artifact_revise(form):
    ref = _outputs_ref(form)
    feedback = _f(form, "feedback")
    if not ref or not feedback:
        return ("/views/studio", "✗ missing artifact or empty feedback", None)
    job = _start_job("artifact-revise", {"ref": ref, "feedback": feedback})
    return ("/views/studio", f"queued revision of {ref} — this can take a few minutes", job["id"])


def act_artifact_final(form):
    ref = _outputs_ref(form)
    if not ref:
        return ("/views/studio", "✗ bad artifact reference", None)
    job = _start_job("artifact-final", {
        "ref": ref, "version": _f(form, "version") or "latest",
    })
    return ("/views/studio", f"queued final marking for {ref}", job["id"])


def act_artifact_promote(form):
    ref = _outputs_ref(form)
    if not ref:
        return ("/views/studio", "✗ bad artifact reference", None)
    job = _start_job("artifact-promote", {"ref": ref})
    return ("/views/studio", f"queued promotion of {ref} and wiki compile", job["id"])


def act_artifact_delivered(form):
    ref = _outputs_ref(form)
    if not ref:
        return ("/views/studio", "✗ bad artifact reference", None)
    payload = {"ref": ref}
    for key in ("to", "note", "reaction"):
        val = _f(form, key)
        if val:
            payload[key] = val
    job = _start_job("artifact-delivered", payload)
    return ("/views/studio", f"queued delivery record for {ref}", job["id"])


def act_artifact_new(form):
    """"Start something new" (v127) — queue the `artifact new` CLI.

    The CLI mints the slug, so the redirect can only name what was asked for;
    the new piece appears in its Focus group once the job lands.
    """
    fmt = _f(form, "format")
    try:
        import format_frameworks  # noqa: PLC0415
        known = set(format_frameworks.valid_formats())
    except Exception as exc:  # noqa: BLE001
        # Degraded registry: let jobs.py's own valid_formats() check be the
        # authority rather than refusing every format from the viewer.
        _record_view_failure("artifact-new-formats", exc)
        known = set()
    if not fmt or (known and fmt not in known):
        return ("/views/studio", "✗ unknown format", None)
    subject = _f(form, "subject")
    categories = _f(form, "categories")
    if not subject and not categories:
        return ("/views/studio",
                "✗ name a subject (or categories) for the new piece", None)
    payload = {"format": fmt}
    for key in ("subject", "occasion", "date", "title", "categories"):
        value = _f(form, key)
        if value:
            payload[key] = value
    job = _start_job("artifact-new", payload)
    return ("/views/studio",
            f"queued: creating {fmt} for {subject or categories}", job["id"])


def act_artifact_assemble(form):
    fid = _f(form, "focus")
    if not fid:
        return ("/views/studio", "✗ missing focus", None)
    job = _start_job("artifact-assemble", {"focus": fid})
    return ("/views/studio", "queued manuscript assembly", job["id"])


def act_reflect(form):
    ref, body = _f(form, "ref"), (form.get("body") or [""])[0]
    if not ref or not body.strip():
        return ("/views/sources", "✗ missing source or empty reflection", None)
    job = _start_job("reflect-source", {"ref": ref, "body": body})
    back = f"/source-actions?ref={quote(ref)}"
    return (back, "queued reflection — it will compile alongside the original", job["id"])


def act_fix(form):
    ref = _f(form, "ref")
    back = f"/source-actions?ref={quote(ref)}"
    if not ref:
        return ("/views/sources", "✗ missing source reference", None)
    if _f(form, "mode") == "retract":
        reason = _f(form, "reason")
        if not reason:
            return (back, "✗ a retraction needs a reason", None)
        pages = [s.strip() for s in _f(form, "from_page").split(",") if s.strip()]
        job = _start_job("fix-source", {
            "ref": ref, "mode": "retract", "reason": reason, "from_pages": pages,
        })
        return (back, "queued retraction (sha-pinned, undoable via unretract)", job["id"])
    right = _f(form, "right")
    if not right:
        return (back, "✗ a correction needs the true fact (--right)", None)
    payload = {
        "ref": ref, "mode": "correct", "right": right,
        "kind": _f(form, "kind") or "factual",
    }
    wrong = _f(form, "wrong")
    if wrong:
        payload["wrong"] = wrong
    job = _start_job("fix-source", payload)
    return (back, "queued correction — it resolves at compile time", job["id"])


def act_compile(form):
    job = _start_job("compile", {"no_ai": True})
    back = _f(form, "back") or "/views/sources"
    return (back, "recompiling the wiki (30–90s)", job["id"])


def act_timeline_place(form):
    source = _f(form, "source")
    description = (form.get("description") or [""])[0].strip()
    period = _f(form, "period")
    if not (source and description and period):
        return ("/views/timeline", "✗ pick a period for the moment first", None)
    when_hint = _f(form, "when_hint")
    job = _start_job("timeline-place", {
        "source": source,
        "description": description,
        "period": period,
        "when_hint": when_hint,
        "note": _f(form, "note"),
    })
    return ("/views/timeline", "queued placement and its durable date assertion", job["id"])


def act_timeline_unplace(form):
    key = _f(form, "key")
    if not re.fullmatch(r"[0-9a-f]{12}", key):
        return ("/views/timeline", "✗ no such placement", None)
    job = _start_job("timeline-unplace", {"key": key})
    return ("/views/timeline", "queued placement removal — the filed assertion remains", job["id"])


ACTIONS = {
    "/actions/candidate": act_candidate,
    "/actions/focus-rec": act_focus_rec,
    "/actions/second-voice-ack": act_second_voice,
    "/actions/artifact/new": act_artifact_new,
    "/actions/artifact/assemble": act_artifact_assemble,
    "/actions/artifact/save": act_artifact_save,
    "/actions/artifact/revise": act_artifact_revise,
    "/actions/artifact/final": act_artifact_final,
    "/actions/artifact/promote": act_artifact_promote,
    "/actions/artifact/delivered": act_artifact_delivered,
    "/actions/reflect": act_reflect,
    "/actions/fix": act_fix,
    "/actions/compile": act_compile,
    "/actions/timeline/place": act_timeline_place,
    "/actions/timeline/unplace": act_timeline_unplace,
}


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_BIND_LOOPBACK_LITERALS = frozenset({"127.0.0.1", "::1"})


def _ip_address(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _localhost_resolves_only_loopback() -> bool:
    try:
        infos = socket.getaddrinfo("localhost", None, type=socket.SOCK_STREAM)
    except OSError:
        return False
    addresses = {info[4][0].split("%", 1)[0] for info in infos if info[4]}
    if not addresses:
        return False
    return all((ip := _ip_address(address)) is not None and ip.is_loopback
               for address in addresses)


def _validated_bind_host(host: str) -> str:
    """Return a safe bind host or raise before the viewer socket is built."""
    value = (host or "").strip()
    if value in _BIND_LOOPBACK_LITERALS:
        return value
    if _ip_address(value) is not None:
        raise ValueError("Lifehug viewer refuses non-owner bind hosts; use 127.0.0.1 or ::1")
    if value.lower() == "localhost" and _localhost_resolves_only_loopback():
        return "localhost"
    raise ValueError("Lifehug viewer refuses non-owner bind hosts; use 127.0.0.1")


def _loopback_peer(client_address) -> bool:
    try:
        host = str(client_address[0]).split("%", 1)[0]
    except (IndexError, TypeError):
        return False
    ip = _ip_address(host)
    return bool(ip and ip.is_loopback)


def _loopback_authority(value: str, expected_port: int, *, origin: bool = False) -> bool:
    """Require an exact loopback hostname and this viewer instance's port."""
    try:
        parsed = urlparse(value if origin else f"//{value}")
        if origin and parsed.scheme != "http":
            return False
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            return False
        if parsed.path != "":
            return False
        return parsed.hostname in _LOOPBACK_HOSTS and parsed.port == expected_port
    except ValueError:
        return False


def source_actions_html(ref: str) -> tuple[str, str]:
    """The Reflect / Fix form page for one source (v101). `ref` is a source
    path or source id exactly as the CLI accepts it."""
    safe = html.escape(ref)
    read_href = source_href(ref)
    toolbar = '<div class="source-toolbar"><a href="/views/sources">Source Integrity</a>'
    if read_href:
        toolbar += f'<a href="{read_href}">Read source</a>'
    toolbar += "</div>"
    body = [f"<h1>Act on a source</h1>",
            f'<p class="view-desc">Raw sources are immutable — these actions file '
            f'<em>additive</em> reflections, corrections, or retractions against '
            f'<code>{safe}</code>. They take effect at the next compile.</p>',
            toolbar]
    body.append(
        f'<h2>Reflect</h2>'
        f'<p class="muted">A later thought on this memory — how it reads now.</p>'
        f'<form method="post" action="/actions/reflect">{_token_input()}'
        f'<input type="hidden" name="ref" value="{safe}">'
        f'<textarea name="body" rows="5" placeholder="What do you see in this now?"></textarea>'
        f'<div class="act-row"><button class="btn" type="submit">File reflection</button></div></form>')
    body.append(
        f'<h2>Correct a fact</h2>'
        f'<form method="post" action="/actions/fix">{_token_input()}'
        f'<input type="hidden" name="ref" value="{safe}">'
        f'<input type="hidden" name="mode" value="correct">'
        f'<label>What it wrongly says (optional)</label>'
        f'<input name="wrong" placeholder="moved in 2006">'
        f'<label>The true fact</label>'
        f'<input name="right" placeholder="moved in 2004" required>'
        f'<label>Kind</label>'
        f'<input name="kind" value="factual">'
        f'<div class="act-row"><button class="btn" type="submit">File correction</button></div></form>')
    body.append(
        f'<h2>Retract</h2>'
        f'<p class="muted">Stops the compiler asserting this source (the raw file stays). '
        f'Scope to specific pages with a comma-separated slug list, or leave empty for all.</p>'
        f'<form method="post" action="/actions/fix">{_token_input()}'
        f'<input type="hidden" name="ref" value="{safe}">'
        f'<input type="hidden" name="mode" value="retract">'
        f'<label>Reason</label>'
        f'<input name="reason" placeholder="classifier inference, never happened" required>'
        f'<label>Only on pages (optional)</label>'
        f'<input name="from_page" placeholder="childhood, dave-and-mom">'
        f'<div class="act-row"><button class="btn" type="submit">File retraction</button></div></form>')
    body.append(
        f'<h2>Recompile</h2>'
        f'<p class="muted">Corrections and retractions apply at compile time.</p>'
        f'<form method="post" action="/actions/compile">{_token_input()}'
        f'<input type="hidden" name="back" value="/source-actions?ref={quote(ref)}">'
        f'<div class="act-row"><button class="btn" type="submit">Recompile now (no AI)</button></div></form>')
    return ("Act on source", "".join(body))


VIEWS = [
    # System overview first, with the graph right beneath it.
    ("status", "The Loop", view_status),
    ("mirror", "Mirror", view_mirror),
    ("graph", "Graph", view_graph),
    ("timeline", "Timeline", view_timeline),
    # Studio — where material becomes things (v127: absorbed Book Assembly
    # and Artifacts into one Focus-grouped making surface).
    ("studio", "Studio", view_studio),
    # Foundation: the consolidated supply-side review (v124) — absorbed the
    # separate Focuses / Coverage / Question Bank views.
    ("foundation", "Foundation", view_foundation),
    # Review: the consolidated self-grown proposal lanes (v128) — absorbed
    # Question Candidates / Focus Recommendations / Entity Candidates.
    ("review", "Review", view_review),
    ("queue", "Question Queue", view_queue),
    # The rest.
    ("sources", "Source Integrity", view_sources),
    ("answers", "Answers", view_answers),
    ("reports", "Reports", view_reports),
    ("privacy", "Privacy Preview", view_privacy_preview),
]
VIEW_MAP = {slug: fn for slug, _, fn in VIEWS}

# Old bookmarks and links keep working: the three views Foundation absorbed
# (v124), the two Studio absorbed (v127), and the three Review absorbed
# (v128) redirect permanently to their consolidated surface.
LEGACY_VIEW_REDIRECTS = {
    "focuses": "foundation",
    "coverage": "foundation",
    "question-bank": "foundation",
    "book": "studio",
    "artifacts": "studio",
    "candidates": "review",
    "recommendations": "review",
    "entities": "review",
}

# One-line explainer shown under each view's title: what the page is and what the
# data on it means. Plain text (may include simple inline HTML); injected after
# the <h1> so empty-state pages get it too.
VIEW_DESCRIPTIONS = {
    "status": "A live snapshot of the whole system — one card per moving part of the Loop: what pass you're on, how much you've answered, how many candidates and sources are waiting, and whether the weekly queue is being delivered.",
    "mirror": "What the archive has noticed about you. The weekly synthesis distills the classifier's contradictions, self-understanding insights, and stated positions into a short edition — tensions presented as coexisting truths in your own words, every claim cited. The raw signals stay browsable underneath. A place to visit and sit with, not a feed.",
    "studio": "Where material becomes things — your projects and pieces, grouped by Focus. A project (the book) shows its chapter map and readiness; expand it for the full chapter table, and assemble the drafted chapters into a manuscript when you're ready. Every piece keeps its full version history — revisions, diffs, finals, deliveries — and everything starts here: pick a format, name a subject, and the Studio gathers the material. Foundation is the material; Studio is where you work it.",
    "foundation": "The raw material behind your stories — every Focus you're building toward, how deep it runs against its target, and where the graph is thin. Expand a Focus to see its categories: the bar is answered/total and the colour your ratio — RED (0–30%), YELLOW (30–70%), GREEN (70%+) — least-covered first. Expand a category to see every question, answered (✓) and open (○). Artifacts are what you make; this is what you make them from.",
    "graph": "Your life as a graph. Each node is a wiki page (people, places, periods, themes, Focuses); size reflects how many sources mention it and edges connect subjects that share sources. Click any node to open its page.",
    "review": "What the system grew on its own, waiting for your eye. Three lanes with three autonomy levels: question candidates auto-promote past a quality bar and the rest wait here; focus ideas never become Focuses without you; entities graduate into wiki pages automatically, previewed here. Promote, approve, dismiss, or defer — or just see what the Loop noticed. Decided items keep their history below each lane.",
    "queue": "This week's planned questions — the ordered list the daily question pulls from before falling back to coverage rotation. Each row shows the question, its category, why it was chosen, and its status: answered (you've responded), delivered (sent, awaiting an answer), or queued (still waiting). Answered state is read from the question bank, so it stays accurate. The queue expires and is rebuilt weekly.",
    "sources": "The integrity ledger for every raw source (answers, stories, artifacts). Open lint findings flag metadata or manifest problems to repair; the captured-sources tables show what's tracked and whether any file has changed since it was first recorded.",
    "answers": "The ledger of everything you've answered — question, category, date, and an approximate word count, newest first, each row linking to reflect / correct / retract. Filing here is synchronous, so there's no in-flight or parked status column the way the hosted twin has — every row below already landed.",
    "timeline": "The life graph projected onto time: chrono-ordered periods as the spine, with people, places, objects, and projects lined up by shared sources (the evidence is shown), dated moments from classified answers, your own Life Chapters as a parallel band, and gaps made explicit. A validation surface — wrong placements are feedback.",
    "privacy": "Which pages' material would be eligible for each future audience build (public / friends / family), from per-page sensitivity floors. Preview only — the wiki itself is permanently owner-only, and audience surfaces will be separate, owner-reviewed builds.",
    "reports": "The full weekly and monthly maintenance reports — every step's complete output, persisted under state/reports/. The Telegram message is just the counts summary; when it flags a failure or warning, this is where the detail lives.",
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
    def send_owner_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")

    def send_simple_html(self, title: str, body: str, status: int = 200):
        payload = (
            "<!doctype html><html><head><meta charset=\"utf-8\">"
            f"<title>{html.escape(title)} · Lifehug</title></head>"
            f"<body>{body}</body></html>"
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_owner_headers()
        self.end_headers()
        self.wfile.write(payload)

    def peer_allowed(self) -> bool:
        return _loopback_peer(getattr(self, "client_address", ()))

    def host_allowed(self) -> bool:
        host = self.headers.get("Host", "")
        port = int(self.server.server_address[1])
        return _loopback_authority(host, port)

    def reject_owner_boundary(self):
        self.send_simple_html("Forbidden", "<h1>Forbidden</h1>", status=403)

    def send_html(self, title, body, status=200, active_rel=None, wide=False, no_store=False):
        flash = getattr(self, "_flash", None)
        if flash:
            job = getattr(self, "_job", None)
            pill = (f' <span class="jobpill" data-job="{html.escape(job)}">running…</span>'
                    if job else "")
            body = (f'<div class="flash">{html.escape(flash)}{pill}</div>') + body
        payload = layout(title, body, active_rel, wide)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        if no_store:
            self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.send_owner_headers()
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, data, status=200):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_owner_headers()
        self.end_headers()
        self.wfile.write(payload)

    def _post_allowed(self, form) -> bool:
        host = self.headers.get("Host", "")
        port = int(self.server.server_address[1])
        if not _loopback_authority(host, port):
            return False
        origin = self.headers.get("Origin")
        if origin and not _loopback_authority(origin, port, origin=True):
            return False
        token = self.headers.get("X-Lifehug-Token") or _f(form, "_token")
        return secrets.compare_digest(token or "", SESSION_TOKEN)

    def _source_get_allowed(self) -> bool:
        """Raw source bodies are available only to a loopback peer + Host."""
        try:
            peer = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return False
        if not peer.is_loopback:
            return False
        host = self.headers.get("Host", "")
        try:
            hostname = urlparse(f"//{host}").hostname or ""
        except ValueError:
            return False
        if hostname.lower().rstrip(".") == "localhost":
            return True
        try:
            return ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            return False

    def do_POST(self):
        if not self.peer_allowed() or not self.host_allowed():
            self.reject_owner_boundary()
            return
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        form = parse_qs(body, keep_blank_values=True)
        if not self._post_allowed(form):
            self.send_html("Forbidden", "<h1>Forbidden</h1>", status=403)
            return
        handler = ACTIONS.get(parsed.path)
        if handler is None:
            self.send_html("Not found", "<h1>Not found</h1>", status=404)
            return
        try:
            redirect, flash, job_id = handler(form)
        except Exception as exc:  # noqa: BLE001 — action failures stay typed and private
            # Exception messages can contain absolute paths, provider details, or
            # submitted text.  The public redirect and HTTP log deliberately expose
            # only a fixed operation code plus the exception class.
            operation = parsed.path.removeprefix("/actions/").replace("/", "-")
            self.log_error(
                "viewer action failed operation=%s exception_class=%s",
                operation,
                type(exc).__name__,
            )
            redirect, flash, job_id = (
                "/",
                "✗ action failed safely; nothing was queued",
                None,
            )
        params = {"flash": flash}
        if job_id:
            params["job"] = job_id
        sep = "&" if "?" in redirect else "?"
        self.send_response(303)
        self.send_header("Location", redirect + sep + urlencode(params))
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if not self.peer_allowed() or not self.host_allowed():
            self.reject_owner_boundary()
            return
        parsed = urlparse(self.path)
        q = parse_qs(parsed.query)
        self._flash = (q.get("flash") or [None])[0]
        self._job = (q.get("job") or [None])[0]

        if parsed.path.startswith("/jobs/") and parsed.path.endswith(".json"):
            import jobs  # noqa: PLC0415
            record = jobs.load_job(parsed.path[len("/jobs/"):-len(".json")])
            if record is None:
                self.send_json({"error": "not found"}, status=404)
            else:
                self.send_json(record)
            return

        if parsed.path.startswith("/source/"):
            if not self._source_get_allowed():
                self.send_html("Forbidden", "<h1>Forbidden</h1>"
                               + _empty("Raw sources are available only on this device."),
                               status=403, no_store=True)
                return
            ref = unquote(parsed.path[len("/source/"):], errors="replace")
            result = source_document_html(ref)
            if result is None:
                self.send_html("Source unavailable", "<h1>Source unavailable</h1>"
                               + _empty("Only exact regular Markdown files in approved source folders can be read."),
                               status=404, no_store=True)
                return
            self.send_html(result[0], result[1], no_store=True)
            return

        if parsed.path == "/source-actions":
            ref = (q.get("ref") or [""])[0].strip()
            if not ref:
                self.send_html("Act on source", "<h1>Act on a source</h1>"
                               + _empty("No source given — open this from a source row."))
                return
            title, body = source_actions_html(ref)
            self.send_html(title, body)
            return

        if parsed.path == "/":
            # Home is the action hub (v99). The wiki index stays reachable via
            # the sidebar's Index link (/page/wiki/index.md).
            try:
                title, body, wide = view_home()
            except Exception as exc:  # noqa: BLE001 — the front page must never 500
                self.log_error(
                    "viewer read failed operation=home exception_class=%s",
                    type(exc).__name__,
                )
                title, body, wide = ("Today",
                                     f"<h1>Today</h1>{_empty('home view temporarily unavailable')}",
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
            self.send_owner_headers()
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
            self.send_owner_headers()
            self.end_headers()
            self.wfile.write(payload)
            return

        if parsed.path.startswith("/views/"):
            slug = parsed.path[len("/views/"):].strip("/")
            legacy_target = LEGACY_VIEW_REDIRECTS.get(slug)
            if legacy_target:
                self.send_response(301)
                self.send_header("Location", f"/views/{legacy_target}")
                self.end_headers()
                return
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
                self.log_error(
                    "viewer read failed operation=view-%s exception_class=%s",
                    slug,
                    type(exc).__name__,
                )
                title, body, wide = (
                    "View error",
                    "<h1>View error</h1><p>This view is temporarily unavailable.</p>",
                    False,
                )
            self.send_html(title, body, wide=wide)
            return

        self.send_html("Not found", "<h1>Not found</h1>", status=404)


class LifehugHTTPServer(ThreadingHTTPServer):
    """Loopback-only viewer server that avoids startup-time reverse DNS.

    Python's HTTPServer.server_bind calls socket.getfqdn(host), which can block
    on macOS reverse lookups even for 127.0.0.1. The viewer does not use that
    display name, so bind directly and keep the host literal.
    """

    def server_bind(self):
        TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


class LifehugIPv6HTTPServer(LifehugHTTPServer):
    address_family = socket.AF_INET6


def main():
    parser = argparse.ArgumentParser(description="Serve the owner-only Lifehug wiki")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host; keep 127.0.0.1 for owner-only local use")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    try:
        host = _validated_bind_host(args.host)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    server_cls = LifehugIPv6HTTPServer if host == "::1" else LifehugHTTPServer
    server = server_cls((host, args.port), Handler)
    display_host = f"[{host}]" if ":" in host else host
    print(f"Lifehug wiki serving at http://{display_host}:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
