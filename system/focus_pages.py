#!/usr/bin/env python3
"""Which wiki page a Focus compiles to — the ONE category→page rule.

The compiler (``wiki_compile.py``) decides where a question-bank category is
written; the roadmap's ``wiki_node`` was a second, independent guess made by
Focus type, and the two disagreed (issue #434 audit, 2026-09-29): every
``## Focuses`` category is written as a person page whatever its Focus type,
a grouped project Focus (``(Etherfuse Story)``) is written as one page per
category and never as ``projects/<tag>.md``, the primary Focus had no page at
all, and a relationship Focus had no directory. This module is the rule both
sides now read, so they cannot drift again:

* ``A_FOCUS_KNOWS_ITS_OWN_PAGE`` — a Focus resolves to the pages the compiler
  writes for its categories (:func:`focus_pages`). The stored ``wiki_node`` is
  only a fallback for a Focus with no category. A resolved page that does not
  exist on disk is *reported* (``doctor``, the graph's ``warnings``), never
  silently dropped.
* ``A_PRIMARY_FOCUS_IS_THE_HUB`` — the primary life-story Focus is the life
  hub, ``wiki/life/<slug(full_name)>.md`` (what ``plan_life_story`` writes).
* ``A_RELATIONSHIP_HAS_TWO_ENDS`` — a relationship page is the edge between
  the owner (the hub) and the person its Focus category names, written at
  ``wiki/relationships/<slug(name)>-and-<slug(person)>.md``.

Pure: no vault paths are bound here. Callers pass the parsed categories and
the owner's ``name`` / ``full_name`` from config.
"""

from __future__ import annotations

import re
from pathlib import Path

from lifehug_core import slugify

A_FOCUS_KNOWS_ITS_OWN_PAGE = "A_FOCUS_KNOWS_ITS_OWN_PAGE"
A_PRIMARY_FOCUS_IS_THE_HUB = "A_PRIMARY_FOCUS_IS_THE_HUB"
A_RELATIONSHIP_HAS_TWO_ENDS = "A_RELATIONSHIP_HAS_TWO_ENDS"

OLD_FOCUS_TERM = "Spot" "light"

#: Compiler page type → wiki subdirectory. Mirrors ``wiki_compile.TYPE_DIRS``
#: (a test holds them equal).
PAGE_DIRS = {
    "life": "life",
    "person": "people",
    "place": "places",
    "period": "periods",
    "project": "projects",
    "theme": "themes",
    "object": "objects",
    "relationship": "relationships",
    "self": "self",
    "lifes_work": "lifes_work",
}


def clean_focus_name(name: str) -> str:
    """'Focus — Mom' → 'Mom'; 'Focus — Dad (James)' → 'Dad'. The compiler's title rule."""
    for prefix in (
        "Focus — ", "Focus - ", "Focus: ", "Focus ",
        f"{OLD_FOCUS_TERM} — ", f"{OLD_FOCUS_TERM} - ",
        f"{OLD_FOCUS_TERM}: ", f"{OLD_FOCUS_TERM} ",
    ):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return re.sub(r"\s*\(.*?\)\s*$", "", name).strip()


def page_path(page_type: str, slug: str) -> str:
    """Vault-relative page path, e.g. ``wiki/people/mom.md``."""
    return f"wiki/{PAGE_DIRS[page_type]}/{slug}.md"


def focus_category_slug(category_name: str) -> str:
    """Slug of the person page a ``## Focuses`` category compiles to."""
    return slugify(clean_focus_name(category_name))


def project_category_slug(category_name: str) -> str:
    """Slug of the project page a ``## Project Categories`` category compiles to."""
    return slugify(category_name)


def arc_category_slug(category_name: str) -> str:
    """Slug of the life-arc page a main (A–E) category compiles to."""
    return slugify(category_name)


def hub_slug(author_full: str) -> str:
    """Slug of the life hub (the owner's self-portrait page)."""
    return slugify(author_full)


def relationship_slug(author: str, person: str) -> str:
    """Slug of the owner-and-person relationship page."""
    return f"{slugify(author or 'Me')}-and-{slugify(person)}"


def author_names(config: dict) -> tuple[str, str]:
    """(name, full_name) as the compiler reads them."""
    author = (config or {}).get("name") or "Me"
    full = (config or {}).get("full_name") or author
    return str(author), str(full)


def hub_page(author_full: str) -> str:
    return page_path("life", hub_slug(author_full))


def category_page(cat_id: str, categories: dict, author: str) -> dict | None:
    """The page(s) one bank category compiles to.

    Returns ``{"page": path, "relationship": path|None, "person": title|None}``
    or ``None`` for a category the compiler does not give a page (timeline).
    """
    info = categories.get(cat_id)
    if not info:
        return None
    group = info.get("group")
    name = info.get("name", "")
    if group == "focus":
        person = clean_focus_name(name)
        return {
            "page": page_path("person", slugify(person)),
            "relationship": page_path("relationship", relationship_slug(author, person)),
            "person": person,
        }
    if group == "project":
        return {"page": page_path("project", project_category_slug(name)),
                "relationship": None, "person": None}
    if group == "main":
        return {"page": page_path("life", arc_category_slug(name)),
                "relationship": None, "person": None}
    return None


def focus_pages(focus: dict, categories: dict, author: str, author_full: str) -> dict:
    """Resolve one roadmap Focus to the pages the compiler writes for it.

    ``pages`` are the node pages the Focus's target applies to (a grouped
    project Focus has one per category). ``relationships`` are the edge pages
    its ``## Focuses`` categories compile to. ``rule`` names how it resolved.
    Existence is not checked here — see :func:`resolve_roadmap`.
    """
    if focus.get("primary"):
        return {"pages": [hub_page(author_full)], "relationships": [],
                "rule": A_PRIMARY_FOCUS_IS_THE_HUB}
    pages: list[str] = []
    rels: list[str] = []
    ftype = focus.get("type")
    if ftype == "self":
        # plan_self writes self Focuses from the roadmap, not from the bank group.
        pages.append(page_path("self", slugify(focus.get("label") or focus.get("id") or "self")))
    for cat_id in sorted(str(c) for c in focus.get("categories") or []):
        hit = category_page(cat_id, categories, author)
        if hit is None:
            continue
        if ftype != "self" and hit["page"] not in pages:
            pages.append(hit["page"])
        if hit["relationship"] and hit["relationship"] not in rels:
            rels.append(hit["relationship"])
    if ftype == "relationship" and rels:
        # A relationship Focus's own page is the edge, not the person page.
        return {"pages": [], "relationships": rels, "rule": A_RELATIONSHIP_HAS_TWO_ENDS}
    if pages or rels:
        return {"pages": pages, "relationships": rels, "rule": A_FOCUS_KNOWS_ITS_OWN_PAGE}
    node = focus.get("wiki_node")
    if node:
        return {"pages": [str(node)], "relationships": [], "rule": "wiki_node"}
    return {"pages": [], "relationships": [], "rule": "none"}


def primary_page(focus: dict, categories: dict, author: str, author_full: str) -> str | None:
    """The single page a Focus's ``wiki_node`` should hold (first resolved page)."""
    hit = focus_pages(focus, categories, author, author_full)
    return (hit["pages"] or hit["relationships"] or [None])[0]


def resolve_roadmap(focuses: list[dict], categories: dict, author: str,
                    author_full: str, vault_root: Path) -> list[dict]:
    """Every Focus, its resolved pages, and which of them are missing on disk."""
    out = []
    for focus in focuses or []:
        hit = focus_pages(focus, categories, author, author_full)
        present = [p for p in hit["pages"] if (vault_root / p).is_file()]
        missing = [p for p in hit["pages"] if p not in present]
        rel_present = [p for p in hit["relationships"] if (vault_root / p).is_file()]
        out.append({
            "focus_id": focus.get("id"),
            "label": focus.get("label") or focus.get("id"),
            "rule": hit["rule"],
            "pages": present,
            "missing": missing,
            "relationships": rel_present,
            # A relationship Focus with no written edge page is missing too.
            "missing_relationships": (
                [p for p in hit["relationships"] if p not in rel_present]
                if focus.get("type") == "relationship" else []),
        })
    return out
