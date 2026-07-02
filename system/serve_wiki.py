#!/usr/bin/env python3
"""Owner-only local Lifehug wiki viewer."""

from __future__ import annotations

import argparse
import html
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from lifehug_core import (
    COVERAGE_FILE,
    FOCUS_RECS_FILE,
    QUESTION_CANDIDATES_FILE,
    QUESTION_QUEUE_FILE,
    QUESTIONS_FILE,
    ROTATION_FILE,
    SOURCE_LINT_FINDINGS_FILE,
    SOURCE_MANIFEST_FILE,
    WIKI_DIR,
    load_config,
    parse_categories,
    parse_questions,
    read_json,
    slugify,
)
from entity_roster import ENTITY_TYPES, load_roster
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
        return (
            f'<div class="sidebar-group" data-group="{html.escape(gtype)}">'
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


def menu_html() -> str:
    """The hamburger dropdown: one link per registered view. Adding a view to
    VIEWS automatically adds it here and at /views/<slug>."""
    links = "".join(
        f'<a class="menu-item" href="/views/{slug}">{html.escape(label)}</a>'
        for slug, label, _ in VIEWS
    )
    return (
        '<div class="menu-wrap">'
        '<button class="menu-btn" id="menuBtn" aria-label="Views menu" onclick="toggleMenu(event)">'
        '<span></span><span></span><span></span></button>'
        f'<div class="menu-dropdown" id="menuDropdown"><div class="menu-title">Views</div>{links}</div>'
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
    body {{ margin: 0; font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #202124; background: #fbfaf7; }}
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
    .qb-cat {{ margin-bottom: 18px; }}
    .qb-list {{ list-style: none; padding-left: 0; }}
    .qb-list li {{ padding: 3px 0; }}
    .qb-list .q-done {{ color: #6b5d49; }}
    .qb-list .q-mark {{ display: inline-block; width: 16px; }}
    .qb-list .q-id {{ font-weight: 650; color: #7c4f1d; margin-right: 4px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; margin: 8px 0 24px; }}
    .card {{ background: #fff; border: 1px solid #e5dfd5; border-radius: 10px; padding: 14px 16px; }}
    .card-val {{ font-size: 26px; font-weight: 700; color: #3f3428; }}
    .card-lbl {{ font-size: 13px; color: #6b5d49; }}
    .card .sub {{ font-size: 12px; color: #9a8c75; margin-top: 2px; }}
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
            '<div class="qb-cat">' + _h2(head) + _bar(ratio, f"{answered}/{total}")
            + '<ul class="qb-list">' + "".join(lis) + "</ul></div>"
        )
    return ("Question Bank", "".join(parts), False)


def view_candidates():
    cands = (read_json(QUESTION_CANDIDATES_FILE, default={}) or {}).get("candidates", [])
    if not cands:
        return ("Candidates", "<h1>Question Candidates</h1>" + _empty("No candidates yet."), False)
    by_status: dict[str, list[dict]] = {}
    for c in cands:
        by_status.setdefault(c.get("status", "candidate"), []).append(c)
    parts = ["<h1>Question Candidates</h1>"]
    for status in sorted(by_status):
        group = by_status[status]
        parts.append(_h2(f"{status} ({len(group)})"))
        rows = []
        for c in group:
            score = (c.get("quality") or {}).get("score")
            rows.append([
                html.escape(str(c.get("text", ""))[:300]),
                format(c.get("priority", 0) or 0, ".2f"),
                (format(score, ".2f") if isinstance(score, (int, float)) else "—"),
                html.escape(str(c.get("target_category") or "—")),
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


def view_status():
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
    q_delivered = sum(1 for q in q_items if q.get("status") == "delivered" or q.get("delivered_at"))

    names = rot.get("pass_names") or []
    cur = rot.get("current_pass")
    pass_name = names[cur - 1] if isinstance(cur, int) and 1 <= cur <= len(names) else ""

    def card(label, value, sub=""):
        s = f'<div class="sub">{html.escape(sub)}</div>' if sub else ""
        return (f'<div class="card"><div class="card-val">{html.escape(str(value))}</div>'
                f'<div class="card-lbl">{html.escape(label)}</div>{s}</div>')

    cards = [
        card("Pass", (f"{cur} · {pass_name}" if pass_name else cur) if cur else "—"),
        card("Questions asked", rot.get("questions_asked", 0)),
        card("Answered", f"{answered}/{total}", f"{_pct(answered / total if total else 0)} coverage"),
        card("Green categories", greens),
        card("Open candidates", open_cands),
        card("Sources captured", len(manifest)),
        card("Open lint findings", lint.get("open_count", len([f for f in lint.get("findings", []) if f.get("status", "open") == "open"]))),
        card("Pending focus recs", pending_recs),
        card("Queue delivered", f"{q_delivered}/{len(q_items)}", "expires " + str(queue.get("expires_at", "—"))),
    ]
    grid = '<div class="cards">' + "".join(cards) + "</div>"
    breakdown = ""
    if cand_by_status:
        chips = " ".join(_badge(f"{k}: {v}") for k, v in sorted(cand_by_status.items()))
        breakdown = _h2("Candidate pipeline") + f"<p>{chips}</p>"
    links = '<p class="muted">Detail views: ' + " · ".join(
        f'<a href="/views/{slug}">{html.escape(label)}</a>' for slug, label, _ in VIEWS if slug != "status"
    ) + "</p>"
    return ("The Loop", "<h1>The Loop — System Status</h1>" + grid + breakdown + links, False)


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


VIEWS = [
    ("status", "The Loop", view_status),
    ("focuses", "Focuses", view_focuses),
    ("coverage", "Coverage", view_coverage),
    ("graph", "Graph", view_graph),
    ("question-bank", "Question Bank", view_question_bank),
    ("candidates", "Question Candidates", view_candidates),
    ("entities", "Entity Candidates", view_entities),
    ("queue", "Question Queue", view_queue),
    ("sources", "Source Integrity", view_sources),
    ("recommendations", "Focus Recommendations", view_recommendations),
]
VIEW_MAP = {slug: fn for slug, _, fn in VIEWS}

# One-line explainer shown under each view's title: what the page is and what the
# data on it means. Plain text (may include simple inline HTML); injected after
# the <h1> so empty-state pages get it too.
VIEW_DESCRIPTIONS = {
    "status": "A live snapshot of the whole system — one card per moving part of the Loop: what pass you're on, how much you've answered, how many candidates and sources are waiting, and whether the weekly queue is being delivered.",
    "focuses": "Everything you're deliberately building toward — people, themes, or books. Each bar shows how full a Focus is against its target (answered / target), its tier, and whether it's early, developing, ready to draft, or saturated.",
    "coverage": "How much of each question category you've answered. The bar and colour show your ratio — RED (0–30%), YELLOW (30–70%), GREEN (70%+). Categories are sorted least-covered first, so the top of the list is where the story still needs you.",
    "graph": "Your life as a graph. Each node is a wiki page (people, places, periods, themes, Focuses); size reflects how many sources mention it and edges connect subjects that share sources. Click any node to open its page.",
    "question-bank": "The full master list of questions by category — answered (✓) and still open (○). This is the raw pool the daily question and the weekly planner draw from; it only ever grows.",
    "candidates": "Follow-up questions the weekly classifier proposed from your answers and stories, grouped by review status. These are <em>not</em> daily questions yet — they wait here until promoted into the question bank.",
    "entities": "People, places, periods, objects, and themes auto-detected across your answers that have <em>not</em> yet graduated into wiki pages. Once one graduates it drops off this list and appears in the wiki itself. Qualifies = it meets the bar to become a page.",
    "queue": "This week's planned questions — the ordered list the daily question pulls from before falling back to coverage rotation. Each row shows the question, its category, why it was chosen, and its status: answered (you've responded), delivered (sent, awaiting an answer), or queued (still waiting). Answered state is read from the question bank, so it stays accurate. The queue expires and is rebuilt weekly.",
    "sources": "The integrity ledger for every raw source (answers, stories, artifacts). Open lint findings flag metadata or manifest problems to repair; the captured-sources tables show what's tracked and whether any file has changed since it was first recorded.",
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