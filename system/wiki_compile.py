#!/usr/bin/env python3
"""Compile Lifehug answers into the private Lifehug wiki.

Pipeline: plan → synthesize → cross-link → write.

1. plan       — gather every page that will exist as a descriptor (no writes).
2. synthesize — turn each page's cited sources into flowing prose + content-
                derived related links via an LLM (OpenClaw-first, Anthropic
                fallback). Falls back to the deterministic excerpt list when no
                LLM is available, and caches results so re-compiles are cheap.
3. cross-link — derive backlinks (reverse of related) and shared-source "see
                also" edges so the wiki is a navigable graph, not a flat list.
4. write      — render frontmatter + narrative + sources + related + backlinks
                + open questions, then refresh the index.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from lifehug_core import (
    ANSWERS_DIR,
    QUESTIONS_FILE,
    REPO_DIR,
    SOURCES_DIR,
    STATE_DIR,
    WIKI_DIR,
    answer_body,
    answer_id_from_filename,
    load_config,
    load_mission,
    parse_categories,
    parse_questions,
    read_json,
    slugify,
    split_frontmatter,
    write_json,
    write_text,
)
from research_expand import DEFAULT_MODEL, call_ai, parse_ai_json
from entity_roster import load_roster
from roadmap import load_roadmap

# `Entity Type` is the code/frontmatter routing term. Most values are graph
# node types. `relationship` stays here for compatibility, but it writes a
# Relationship Edge page rather than a node page.
TYPE_DIRS = {
    "life": WIKI_DIR / "life",
    "person": WIKI_DIR / "people",
    "place": WIKI_DIR / "places",
    "period": WIKI_DIR / "periods",
    "project": WIKI_DIR / "projects",
    "theme": WIKI_DIR / "themes",
    "object": WIKI_DIR / "objects",
    "relationship": WIKI_DIR / "relationships",
    "self": WIKI_DIR / "self",
    "lifes_work": WIKI_DIR / "lifes_work",
}

# Friendly index section headings per entity type (mirrors serve_wiki._GROUP_LABELS).
# Naive `type.title() + "s"` mangles these ("Persons", "Selfs", "Lifes_Works").
SECTION_LABELS = {
    "person": "People",
    "place": "Places",
    "period": "Periods",
    "project": "Projects",
    "theme": "Themes",
    "object": "Objects",
    "relationship": "Relationships",
    "self": "Self",
    "lifes_work": "Life's Work",
}

THEME_KEYWORDS = {
    "agency": ["agency", "control", "choice", "independent", "untethered"],
    "belonging": ["belong", "friend", "included", "circle", "home"],
    "faith": ["mormon", "mission", "church", "faith", "god"],
    "family": ["mom", "dad", "parents", "family", "kids", "children", "wife", "brother"],
    "financial-instability": ["money", "poor", "poverty", "bankrupt", "runway", "hungry", "lunch money"],
    "grief": ["died", "death", "grief", "loss", "passed away"],
    "hunger": ["hungry", "hunger", "driven", "insatiable"],
    "urgency": ["urgency", "urgent", "emergency", "runway", "panic"],
}

# Bump to invalidate cached syntheses when the prompt/contract changes.
# v3: the privacy-phase-0 honesty unlock — pages re-synthesize under the
# explicit owner-only contract (no sanitizing; the tier system protects
# sensitive material downstream, not the synthesis).
CACHE_VERSION = "v3"
SYNTH_CACHE_FILE = STATE_DIR / "wiki_synthesis_cache.json"
# Drop-zone for keyless desktop synthesis: when the skill runs through Claude
# Code, the agent writes each page's prose here (state/synthesis/<slug>.md) and
# the next compile consumes it into the cache. No API key / gateway needed.
SYNTH_DIR = STATE_DIR / "synthesis"

MAX_RELATED = 12  # total related links per page
MAX_SHARED = 8    # shared-source links added per page
OLD_FOCUS_TERM = "Spot" "light"


def clean_focus_name(name: str) -> str:
    for prefix in (
        "Focus — ", "Focus - ", "Focus: ", "Focus ",
        f"{OLD_FOCUS_TERM} — ", f"{OLD_FOCUS_TERM} - ",
        f"{OLD_FOCUS_TERM}: ", f"{OLD_FOCUS_TERM} ",
    ):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return re.sub(r"\s*\(.*?\)\s*$", "", name).strip()


def rel(path: Path) -> str:
    return path.relative_to(REPO_DIR).as_posix()


def read_answers() -> dict[str, dict]:
    answers = {}
    if not ANSWERS_DIR.exists():
        return answers
    for path in sorted(ANSWERS_DIR.glob("*.md")):
        qid = answer_id_from_filename(path)
        if not qid:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        answers[qid] = {
            "id": qid,
            "path": path,
            "source": rel(path),
            "body": answer_body(text),
            "sensitivity": frontmatter_value(text, "sensitivity", "private"),
            "content_sha256": frontmatter_value(text, "content_sha256", ""),
        }
    return answers


def strip_frontmatter(text: str) -> str:
    _metadata, body = split_frontmatter(text)
    return body.strip()


def frontmatter_value(text: str, key: str, default: str = "") -> str:
    match = re.search(rf"^{re.escape(key)}:\s*[\"']?(.+?)[\"']?\s*$", text, re.MULTILINE)
    return match.group(1).strip().strip('"').strip("'") if match else default


def page_is_synthesized(existing_text: str) -> bool:
    """Whether an already-written page holds synthesized prose (vs an excerpt
    fallback). Prefers the explicit `synthesized:` frontmatter marker; for legacy
    pages written before the marker existed, infers from layout — a fallback page
    carries the `## What We Know` header, a synthesized page does not."""
    marker = frontmatter_value(existing_text, "synthesized")
    if marker == "true":
        return True
    if marker == "false":
        return False
    return "## What We Know" not in existing_text  # legacy page: infer from layout


def should_preserve_existing(existing_text: str, new_synthesized: bool) -> bool:
    """True when re-rendering would downgrade an already-synthesized page to an
    excerpt fallback. Guards every compile path on a keyless machine: a synthesized
    page is never clobbered by a fallback render — its last good prose is preserved
    until a real synthesis runs (compile machine, or the /compile skill writes a draft)."""
    if new_synthesized:
        return False
    return page_is_synthesized(existing_text)


def read_manual_sources() -> dict[str, dict]:
    sources = {}
    if not SOURCES_DIR.exists():
        return sources
    for path in sorted(p for p in SOURCES_DIR.rglob("*.md") if p.name != ".gitkeep"):
        text = path.read_text(encoding="utf-8", errors="replace")
        metadata, raw_body = split_frontmatter(text)
        title = frontmatter_value(text, "title", path.stem.replace("-", " ").title())
        body = raw_body.strip() if raw_body != text else strip_frontmatter(text)
        body = re.sub(r"^# .+?\n+", "", body, count=1).strip()
        source_id = frontmatter_value(text, "source_id", f"source:{path.stem}")
        kind = frontmatter_value(text, "type", "manual_source")
        generated_from = metadata.get("generated_from", [])
        if not isinstance(generated_from, list):
            generated_from = []
        sources[source_id] = {
            "id": source_id,
            "path": path,
            "source": rel(path),
            "title": title,
            "body": body,
            "kind": kind,
            "witness": frontmatter_value(text, "witness", ""),
            "witness_slug": frontmatter_value(text, "witness_slug", ""),
            "content_sha256": frontmatter_value(text, "content_sha256", ""),
            "sensitivity": frontmatter_value(text, "sensitivity", "private"),
            "corrects": str(metadata.get("corrects", "") or ""),
            "retracts": str(metadata.get("retracts", "") or ""),
            "retracts_path": str(metadata.get("retracts_path", "") or ""),
            "retracts_sha256": str(metadata.get("retracts_sha256", "") or ""),
            "voided": bool(metadata.get("voided", False)),
            "corrects_path": str(metadata.get("corrects_path", "") or ""),
            "suppress_on": metadata.get("suppress_on", []) if isinstance(metadata.get("suppress_on"), list) else [],
            "source_trust": str(metadata.get("source_trust", "")),
            "authority": str(metadata.get("authority", "")),
            "generated_from": [str(item) for item in generated_from],
        }
    return sources


# ---------------------------------------------------------------------------
# Correction & retraction resolution (v74, issue #24).
#
# Corrections are ADDITIVE sources that OVERRIDE the original claim at compile
# time: the correction text is appended to its target's body under an
# authoritative marker, so every downstream consumer (synthesis prompts,
# keyless task packs, excerpt fallbacks) sees the fix — and the changed body
# re-keys the synthesis cache, forcing an honest re-render.
#
# Retractions tell the compiler to STOP ASSERTING a source: globally, or only
# on specific page slugs (the mis-attribution case — a source that belongs on
# one person's pages but was wrongly pulled onto another's). Raw files are
# never touched; history stays auditable.
# ---------------------------------------------------------------------------

# Set by main() from the corrections layer; module-level so _descriptor (the
# single choke point that knows each page's slug) can apply scoped retractions.
_RETRACTIONS: list[dict] = []


def split_correction_layer(manual_sources: dict) -> tuple[dict, list[dict], list[dict]]:
    """Split corrections/retractions out of the narrative source pool.
    Returns (narrative_sources, corrections, retractions). Reflections stay
    narrative — they are the author's later perspective, quotable as material;
    corrections/retractions are compiler directives, not story."""
    narrative: dict = {}
    corrections: list[dict] = []
    retractions: list[dict] = []
    for source_id, item in manual_sources.items():
        if item.get("kind") == "source_correction":
            corrections.append(item)
        elif item.get("kind") == "source_retraction":
            retractions.append(item)
        else:
            narrative[source_id] = item
    return narrative, corrections, retractions


CORRECTION_MARKER = "[LATER CORRECTION — authoritative]"


def apply_corrections(answers: dict, manual_sources: dict, corrections: list[dict]) -> int:
    """Append each correction to its target's body under the authoritative
    marker. Matching is by source_id or path. Returns count applied."""
    applied = 0
    by_id: dict[str, dict] = {}
    for qid, item in answers.items():
        by_id[f"answer:{qid}"] = item
        by_id[item.get("source", "")] = item
    for source_id, item in manual_sources.items():
        by_id[source_id] = item
        by_id[item.get("source", "")] = item
    for correction in corrections:
        target = by_id.get(correction.get("corrects", "")) or by_id.get(correction.get("corrects_path", ""))
        if not target:
            continue
        target["body"] = (f"{target.get('body', '')}\n\n{CORRECTION_MARKER} "
                          f"{correction.get('body', '').strip()}")
        target["corrected"] = True
        applied += 1
    return applied


def _is_retracted(item: dict, slug: str) -> bool:
    item_ids = {str(item.get("id", "")), f"answer:{item.get('id', '')}", str(item.get("source", ""))}
    for retraction in _RETRACTIONS:
        if retraction.get("voided"):
            continue  # explicitly un-retracted (lifehug.py unretract)
        if not ({retraction.get("retracts", ""), retraction.get("retracts_path", "")} & item_ids):
            continue
        # Sha-pinned retraction (v88): it retracts the CONTENT it was filed
        # against, not the id forever. If the target's payload has since been
        # replaced (mis-filed source swapped for a genuine one under the same
        # id), the retraction no longer applies.
        pinned = retraction.get("retracts_sha256", "")
        current = str(item.get("content_sha256", "") or "")
        if pinned and current and pinned != current:
            continue
        scope = retraction.get("suppress_on") or []
        if not scope or slug in scope:
            return True
    return False


def frontmatter(title: str, page_type: str, sources: list[str], related: list[str] | None = None,
                synthesized: bool = True, origin: str = "focus", section: str = "",
                chrono: int | None = None, sensitivity: str = "private") -> str:
    today = date.today().isoformat()
    related = related or []
    lines = [
        "---",
        f'title: "{title}"',
        f"type: {page_type}",
        "status: active",
        "visibility: owner_only",
        # The most-closed level among this page's sources: which future
        # audience BUILD could include (a re-rendered form of) this page.
        # Metadata only — never enforcement; the wiki itself stays owner-only.
        f"sensitivity: {sensitivity}",
        f"origin: {origin}",
        f"synthesized: {'true' if synthesized else 'false'}",
    ]
    if chrono is not None:
        # Chronological rank (1 = earliest in life); periods sort by this in the index.
        lines.append(f"chrono: {chrono}")
    if section:
        lines.append(f'section: "{section}"')
    lines += [
        f"created: {today}",
        f"last_updated: {today}",
        "sources:",
    ]
    for source in sources:
        lines.append(f'  - "{source}"')
    lines.append(f"sources_count: {len(sources)}")
    lines.append("related:")
    for item in related:
        lines.append(f'  - "[[{item}]]"')
    lines.append("---")
    return "\n".join(lines)


def display_body(text: str) -> str:
    """Normalize old category labels for generated wiki display only."""
    return re.sub(rf"\b{OLD_FOCUS_TERM}\b", "Focus", text)


def is_derived_source(item: dict) -> bool:
    """Derived/artifact sources support synthesis but are not primary proof."""
    kind = str(item.get("kind", ""))
    trust = str(item.get("source_trust", ""))
    return kind in {"authored_artifact", "artifact_context", "artifact_source"} or trust in {
        "authored_expression",
        "derived_context",
        "derived",
    }


def cited_blocks(items: list[dict], limit: int = 8) -> list[str]:
    blocks = []
    for item in items[:limit]:
        body = re.sub(r"\s+", " ", display_body(item["body"])).strip()
        if len(body) > 420:
            body = body[:420].rsplit(" ", 1)[0] + "..."
        label = ""
        if is_derived_source(item):
            label = f" ({item.get('source_trust') or item.get('kind')})"
        blocks.append(f"- **{item['id']}**{label}: {body} [{item['source']}]")
    return blocks


def matching_sources(sources: dict[str, dict], terms: list[str]) -> list[dict]:
    clean_terms = [term.lower() for term in terms if term and len(term.strip()) >= 3]
    matches = []
    for source in sources.values():
        haystack = f"{source.get('title', '')} {source.get('body', '')}".lower()
        if any(term in haystack for term in clean_terms):
            matches.append(source)
    return matches


def split_primary_supporting(items: list[dict]) -> tuple[list[dict], list[dict]]:
    primary, supporting = [], []
    for item in items:
        if is_derived_source(item):
            supporting.append(item)
        else:
            primary.append(item)
    return primary, supporting


def unanswered_questions(questions: list[dict], category: str, limit: int = 8) -> list[str]:
    rows = []
    for q in questions:
        if q["category"] == category and not q["answered"]:
            rows.append(f"- {q['id']}: {q['text']}")
        if len(rows) >= limit:
            break
    return rows


def write_page(path: Path, text: str, dry_run: bool) -> bool:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing.strip() == text.strip():
        return False
    if dry_run:
        print(f"would write {rel(path)}")
        return True
    write_text(path, text if text.endswith("\n") else text + "\n")
    return True


# ---------------------------------------------------------------------------
# Plan pass — build page descriptors (no writes)
# ---------------------------------------------------------------------------


def _descriptor(page_type, title, slug, sources, cited_items, supporting_items,
                summary, open_questions, open_questions_header="Open Questions",
                seed_related=None, origin="focus", section="", chrono=None):
    if _RETRACTIONS:
        cited_items = [i for i in cited_items if not _is_retracted(i, slug)]
        supporting_items = [i for i in supporting_items if not _is_retracted(i, slug)]
        kept = {i["source"] for i in cited_items + supporting_items}
        sources = [s for s in sources if s in kept]
    return {
        "type": page_type,
        "title": title,
        "slug": slug,
        "path": TYPE_DIRS[page_type] / f"{slug}.md",
        "sources": sources,
        "cited_items": cited_items,
        "supporting_items": supporting_items,
        "summary": summary,
        "chrono": chrono,
        "open_questions": open_questions,
        "open_questions_header": open_questions_header,
        "seed_related": seed_related or [],
        "origin": origin,
        "section": section,
    }


def project_label(qualifier: str) -> str:
    """Sidebar sub-group label for a project category's '(...)' qualifier:
    '(Etherfuse Story)' -> 'Etherfuse'. Drops a trailing ' Story' if present."""
    if not qualifier:
        return ""
    return re.sub(r"\s+story$", "", qualifier.strip(), flags=re.IGNORECASE).strip()


def _mention_regex(names):
    """Word-boundary, case-insensitive matcher for a person's name + aliases.
    Names shorter than 2 chars are skipped to avoid noisy substring hits;
    2-char names (initials like AJ, JT) are allowed — word boundaries keep them
    from matching inside other words."""
    parts = sorted({n.strip() for n in names if n and len(n.strip()) >= 2}, key=len, reverse=True)
    if not parts:
        return None
    return re.compile(r"\b(" + "|".join(re.escape(p) for p in parts) + r")\b", re.IGNORECASE)


def scan_mentions(names, answers, manual_sources):
    """Return (answer_items, manual_items) whose body mentions any of `names`,
    ordered by salience (how many times the person is mentioned) so the most
    relevant sources survive the downstream source cap — not alphabetical order,
    which would, e.g., drop a Focus person's death from a later category."""
    rx = _mention_regex(names)
    if rx is None:
        return [], []

    def ranked(items):
        scored = []
        for it in items:
            hits = len(rx.findall(it.get("body") or ""))
            if hits:
                scored.append((hits, it))
        # Most-mentioned first; stable tie-break on source for determinism.
        scored.sort(key=lambda t: (-t[0], t[1].get("source", "")))
        return [it for _, it in scored]

    return ranked(answers.values()), ranked(manual_sources.values())


_ALIAS_STOPWORDS = {"the", "my", "our", "a", "an"}


def _first_name_alias(title: str) -> str:
    """'Charlee Joy Taylor' -> 'Charlee': a brand-new Focus has no roster
    aliases until the monthly refresh, so derive the obvious one from the
    title itself. Determiners and short tokens are skipped."""
    first = title.split()[0] if title.split() else ""
    if len(first) >= 3 and first.lower() not in _ALIAS_STOPWORDS and first != title:
        return first
    return ""


def _witness_items(manual_sources, names):
    """Witness accounts FROM a person are source material for that person's
    page by definition (v88) — attach by witness_slug, never by name-mention
    luck (a letter from Charlee may never say 'Charlee'). The witness slug is
    usually the first name ('charlee'), so match it against every known name
    for the page ('Charlee Joy Taylor', aliases, the first-name alias)."""
    slugs = {slugify(n) for n in names if n}
    return [s for s in manual_sources.values()
            if s.get("kind") == "witness_account"
            and s.get("witness_slug") and s.get("witness_slug") in slugs]


def _focus_slugs(categories):
    return {
        slugify(clean_focus_name(info["name"]))
        for info in categories.values()
        if info.get("group") == "focus"
    }


def _focus_alias_map(person_roster, focus_slugs=None):
    """focus_slug -> alias names, from canonical person entities mapped to a Focus."""
    alias_map = defaultdict(set)
    valid = set(focus_slugs or [])
    for p in (person_roster or {}).get("entities", []):
        mf = p.get("maps_to_focus")
        if not mf:
            continue
        focus_slug = slugify(clean_focus_name(str(mf)))
        if valid and focus_slug not in valid:
            continue
        alias_map[focus_slug].add(p.get("name", ""))
        for a in p.get("aliases", []):
            alias_map[focus_slug].add(a)
    return alias_map


def plan_focuses(categories, questions, answers, manual_sources, person_roster=None):
    descs = []
    alias_map = _focus_alias_map(person_roster, _focus_slugs(categories))
    for cat_id, info in sorted(categories.items()):
        if info.get("group") != "focus":
            continue
        title = clean_focus_name(info["name"])
        slug = slugify(title)
        answer_items = [answers[q["id"]] for q in questions if q["category"] == cat_id and q["id"] in answers]
        source_items = matching_sources(manual_sources, [title])

        # Mention enrichment: pull answers/sources that mention this person by
        # name or any roster alias, even when filed under other categories. This
        # is what fills, e.g., an empty Dad Focus from his many cross-category
        # mentions. Focus *behavior* is unchanged — only the page's sources widen.
        names = [title] + sorted(n for n in alias_map.get(slug, set()) if n)
        first_alias = _first_name_alias(title)
        if first_alias and first_alias not in names:
            names.append(first_alias)
        a_hits, m_hits = scan_mentions(names, answers, manual_sources)
        # Retraction filter runs BEFORE the summary counts (v88) — the page
        # banner must not claim prompts the compiler refuses to assert.
        answer_items = [i for i in answer_items if not _is_retracted(i, slug)]
        cited_srcs = {a["source"] for a in answer_items}
        extra_answers = [it for it in a_hits if it["source"] not in cited_srcs
                         and not _is_retracted(it, slug)]
        cited_items = answer_items + extra_answers
        src_srcs = {s["source"] for s in source_items}
        supporting_items = source_items + [it for it in m_hits if it["source"] not in src_srcs]
        for wit in _witness_items(manual_sources, names):
            if wit["source"] not in {s["source"] for s in supporting_items}:
                supporting_items.append(wit)
        supporting_items = [i for i in supporting_items if not _is_retracted(i, slug)]
        sources = [x["source"] for x in cited_items] + [x["source"] for x in supporting_items]

        if answer_items and extra_answers:
            summary = (f"A Lifehug Focus from {len(answer_items)} answered prompts "
                       f"(+{len(extra_answers)} mentions across the story). Owner-only.")
        elif answer_items:
            summary = (f"A Lifehug Focus compiled from {len(answer_items)} answered prompts. "
                       f"Owner-only; cites its source answers.")
        elif extra_answers:
            summary = (f"A Lifehug Focus — no dedicated answers yet; compiled from "
                       f"{len(extra_answers)} mentions across the story. Owner-only.")
        else:
            summary = ("A Lifehug Focus with no source material yet. Owner-only.")

        descs.append(_descriptor(
            "person", title, slug, sources, cited_items, supporting_items,
            summary=summary,
            open_questions=unanswered_questions(questions, cat_id),
        ))
    return descs


_ENTITY_NOUN = {"person": "person", "place": "place", "period": "period", "object": "object"}
# Minimum REAL mentions (answers that actually name the entity) for a page. Places
# and periods need "a few"; people are already score-gated in the roster; a
# symbolic object can graduate on a single resonant mention.
_ENTITY_MIN_MENTIONS = {"person": 1, "place": 2, "period": 2, "object": 1}
RELATIONSHIP_MIN_MENTION_ANSWERS = 2


def plan_entities(entity_type, answers, manual_sources, roster, taken_slugs):
    """Auto pages for page-eligible ENTITIES of a type (person/place/period/object)
    that aren't already Focuses — graduated purely from mentions across the corpus.
    Generalizes the old person-only path to every entity type (the life graph
    builds itself). `taken_slugs` accumulates so we never double-build a slug."""
    descs = []
    noun = _ENTITY_NOUN.get(entity_type, entity_type)
    entities = (roster or {}).get("entities") or []
    for ent in entities:
        if not ent.get("page_eligible"):
            continue
        slug = ent.get("slug") or slugify(ent.get("name", ""))
        if not slug or slug in taken_slugs:
            continue  # a Focus owns it, or already emitted
        names = [ent.get("name", "")] + ent.get("aliases", [])
        a_hits, m_hits = scan_mentions(names, answers, manual_sources)
        if entity_type == "person":
            hit_srcs = {s["source"] for s in m_hits}
            m_hits = m_hits + [w for w in _witness_items(manual_sources, names)
                               if w["source"] not in hit_srcs]
        if len(a_hits) < _ENTITY_MIN_MENTIONS.get(entity_type, 1) and not m_hits:
            continue  # needs a few real mentions to be worth a page
        primary, supporting = split_primary_supporting(m_hits)
        cited_items = a_hits + primary
        sources = [x["source"] for x in cited_items + supporting]
        taken_slugs.add(slug)
        name = ent.get("name", slug)
        # Periods carry an AI-assigned chronological rank so the index can order
        # them earliest→latest (Childhood before My 40s) instead of alphabetically.
        chrono = ent.get("chrono") if entity_type == "period" else None
        descs.append(_descriptor(
            entity_type, name, slug, sources, cited_items, supporting,
            summary=f"A {noun} in the author's life, compiled automatically from "
                    f"{len(cited_items)} mentions across the story. Owner-only.",
            open_questions=[
                f"- What did {name} mean in the author's life?",
                f"- Which moments make {name} matter to the story?",
            ],
            origin="mention",
            chrono=chrono if isinstance(chrono, int) else None,
        ))
    return descs


def plan_projects(categories, questions, answers, manual_sources):
    descs = []
    for cat_id, info in sorted(categories.items()):
        if info.get("group") != "project":
            continue
        title = info["name"]
        slug = slugify(title)
        project = project_label(info.get("qualifier", ""))
        answer_items = [answers[q["id"]] for q in questions if q["category"] == cat_id and q["id"] in answers]
        source_items = matching_sources(manual_sources, [title, title.replace("The ", "")])
        sources = [a["source"] for a in answer_items] + [s["source"] for s in source_items]
        summary = (f"A project thread compiled from category {cat_id} and {len(answer_items)} answered prompts.")
        if project:
            summary = (f"Part of the {project} story — category {cat_id}, "
                       f"{len(answer_items)} answered prompts.")
        descs.append(_descriptor(
            "project", title, slug, sources, answer_items, source_items,
            summary=summary,
            open_questions=unanswered_questions(questions, cat_id),
            section=project,
        ))
    return descs


def theme_keyword_map(theme_roster=None):
    """Static THEME_KEYWORDS overlaid by page-eligible theme-roster entries (v97).

    The static dict stays as the bootstrap for fresh/keyless installs and its
    8 legacy pages keep their slugs. A roster entry wins on collision (its
    curated keywords replace the static row) and can add NEW themes (e.g.
    parenting) that graduate like any other roster entity. Roster-added themes
    are origin: mention so orphan cleanup applies when they leave the roster;
    static themes stay origin: focus (never auto-removed)."""
    merged = {}
    for slug, words in THEME_KEYWORDS.items():
        merged[slug] = {"title": slug.replace("-", " ").title(),
                        "keywords": list(words), "origin": "focus"}
    for ent in (theme_roster or {}).get("entities") or []:
        if not ent.get("page_eligible") or ent.get("maps_to_focus"):
            continue
        slug = ent.get("slug") or slugify(ent.get("name", ""))
        if not slug:
            continue
        name = (ent.get("name") or "").strip() or slug.replace("-", " ").title()
        keywords = [str(k).strip().lower() for k in (ent.get("keywords") or [])
                    if str(k).strip()]
        if not keywords:
            keywords = [name.lower()]
        merged[slug] = {"title": name.title() if name.islower() else name,
                        "keywords": keywords,
                        "origin": "focus" if slug in THEME_KEYWORDS else "mention"}
    return merged


def plan_themes(answers, manual_sources, theme_roster=None, author_slug=None):
    descs = []
    for theme, spec in sorted(theme_keyword_map(theme_roster).items()):
        keywords = spec["keywords"]
        answer_hits = []
        manual_hits = []
        for item in answers.values():
            haystack = item["body"].lower()
            if any(keyword in haystack for keyword in keywords):
                answer_hits.append(item)
        for item in manual_sources.values():
            haystack = item["body"].lower()
            if any(keyword in haystack for keyword in keywords):
                manual_hits.append(item)
        primary_sources, supporting_sources = split_primary_supporting(manual_hits)
        hits = answer_hits + primary_sources
        if not hits and not supporting_sources:
            continue
        title = spec["title"]
        sources = [a["source"] for a in hits + supporting_sources]
        descs.append(_descriptor(
            "theme", title, theme, sources, hits, supporting_sources,
            summary=f"A recurring Lifehug theme found across {len(hits)} source answers.",
            open_questions=[
                f"- Where does {title.lower()} first appear in the author's life?",
                f"- How has {title.lower()} changed across different periods, relationships, and projects?",
            ],
            # Themes are dimensions of the author: link each theme page to the
            # author hub so it's reachable from Self (reciprocal backlink).
            seed_related=[author_slug] if author_slug else None,
            origin=spec["origin"],
        ))
    return descs


def plan_relationships(categories, questions, answers, manual_sources, author, person_roster=None):
    descs = []
    author = author or "Me"
    author_slug = slugify(author)
    alias_map = _focus_alias_map(person_roster, _focus_slugs(categories))
    for cat_id, info in sorted(categories.items()):
        if info.get("group") != "focus":
            continue
        person = clean_focus_name(info["name"])
        person_slug = slugify(person)
        answer_items = [answers[q["id"]] for q in questions if q["category"] == cat_id and q["id"] in answers]

        # Relationships are dyadic edges, not generic node pages. They should
        # be able to graduate from the same mention-enriched evidence as Focus
        # person pages, but only when there is enough actual source material to
        # say something useful about the bond.
        names = [person] + sorted(n for n in alias_map.get(person_slug, set()) if n)
        a_hits, _m_hits = scan_mentions(names, answers, manual_sources)
        cited_srcs = {a["source"] for a in answer_items}
        extra_answers = [it for it in a_hits if it["source"] not in cited_srcs]
        if not answer_items and len(extra_answers) < RELATIONSHIP_MIN_MENTION_ANSWERS:
            continue

        title = f"{author} & {person}"
        slug = f"{author_slug}-and-{person_slug}"
        supporting_items = []
        if answer_items:
            supporting_items.extend(extra_answers)
        source_items = matching_sources(manual_sources, names)
        primary_sources, supporting_sources = split_primary_supporting(source_items)
        if answer_items:
            supporting_items.extend(primary_sources + supporting_sources)
            cited_items = answer_items
        else:
            cited_items = extra_answers + primary_sources
            supporting_items.extend(supporting_sources)
        sources = [a["source"] for a in cited_items] + [s["source"] for s in supporting_items]
        if answer_items and extra_answers:
            summary = (f"The relationship between {author} and {person}, synthesized from "
                       f"{len(answer_items)} dedicated answered prompts plus "
                       f"{len(extra_answers)} mentions across the story. Owner-only; cites its sources.")
        elif answer_items:
            summary = (f"The relationship between {author} and {person}, synthesized from "
                       f"{len(answer_items)} answered prompts. Owner-only; cites its sources.")
        else:
            summary = (f"The relationship between {author} and {person} — no dedicated Focus answers yet; "
                       f"compiled from {len(extra_answers)} mentions across the story. Owner-only; cites its sources.")
        descs.append(_descriptor(
            "relationship", title, slug, sources, cited_items, supporting_items,
            summary=summary,
            open_questions=[
                f"- What does {author} most want {person} to understand?",
                f"- How does {author} think {person} sees them — and is it accurate?",
                f"- What has gone unsaid between {author} and {person}?",
            ],
            open_questions_header="Open Questions (dyadic)",
            seed_related=[person_slug],
        ))
    return descs


def plan_self(questions, answers):
    descs = []
    roadmap = load_roadmap()
    self_focuses = [f for f in roadmap.get("focuses", []) if f.get("type") == "self"]
    for focus in self_focuses:
        cats = set(focus.get("categories", []))
        answer_items = [answers[q["id"]] for q in questions
                        if str(q["category"]) in cats and q["id"] in answers]
        if not answer_items:
            continue
        title = focus.get("label", "Self")
        slug = slugify(title)
        sources = [a["source"] for a in answer_items]
        descs.append(_descriptor(
            "self", title, slug, sources, answer_items, [],
            summary=f"A self-knowledge surface synthesized from {len(answer_items)} answers — "
                    f"patterns, values, fears, and contradictions in the author's own words.",
            open_questions=[],
        ))
    return descs


def plan_life_story(categories, questions, answers, manual_sources, author_full):
    """The person at the center: a self-portrait hub plus one page per life-story
    arc (the A–E 'main' categories). This finally surfaces the author's own life
    story — the core of the program — which no other pass renders."""
    per_cat = []
    for cid, info in sorted(categories.items()):
        if info.get("group") != "main":
            continue
        items = [answers[q["id"]] for q in questions if q["category"] == cid and q["id"] in answers]
        per_cat.append((cid, info, items))
    if not per_cat:
        return []

    descs = []
    # One page per arc (skip arcs with no answers yet).
    for cid, info, items in per_cat:
        if not items:
            continue
        title = info["name"]
        descs.append(_descriptor(
            "life", title, slugify(title), [a["source"] for a in items], items, [],
            summary=f"A chapter of {author_full}'s life story — {title}, "
                    f"from {len(items)} answered prompts.",
            open_questions=unanswered_questions(questions, cid),
            origin="arc",
        ))

    # Hub: a self-portrait synthesized across all arcs. Interleave answers across
    # categories so the synthesis cap sees a spread (Origins…Reflection), not just A.
    hub_items = []
    maxlen = max((len(items) for _, _, items in per_cat), default=0)
    for i in range(maxlen):
        for _, _, items in per_cat:
            if i < len(items):
                hub_items.append(items[i])
    if hub_items:
        descs.insert(0, _descriptor(
            "life", author_full, slugify(author_full),
            [a["source"] for a in hub_items], hub_items, [],
            summary=f"{author_full} — a self-portrait synthesized from the life story so far: "
                    f"who they are, what they value, what they fear, and who they're becoming.",
            open_questions=[],
            origin="hub",
            section="",
        ))
    return descs


# ---------------------------------------------------------------------------
# Synthesis pass — prose + content-derived related (LLM, cached, offline fallback)
# ---------------------------------------------------------------------------


def cache_key(desc: dict) -> str:
    h = hashlib.sha256()
    parts = [CACHE_VERSION, desc["type"], desc["title"], "|".join(sorted(desc["sources"]))]
    for item in desc["cited_items"] + desc["supporting_items"]:
        parts.append(item["id"])
        parts.append(item["body"])
    h.update("\x1f".join(parts).encode("utf-8"))
    return h.hexdigest()


WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def extract_related_from_text(text: str) -> list[str]:
    """Pull related page slugs from [[wikilinks]] embedded in prose."""
    seen, out = set(), []
    for label in WIKILINK_RE.findall(text):
        slug = slugify(label)
        if slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out


def parse_agent_narrative(text: str) -> tuple[str, list[str]]:
    """Parse an agent-written narrative file.

    An optional first non-empty line `Related: a, b, c` names related slugs
    explicitly; otherwise related is inferred from [[wikilinks]] in the prose.
    Returns (narrative_markdown, related_slugs).
    """
    lines = text.splitlines()
    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    related: list[str] | None = None
    if idx < len(lines):
        m = re.match(r"(?i)^related:\s*(.*)$", lines[idx].strip())
        if m:
            related = [slugify(s) for s in re.split(r"[,/]", m.group(1)) if s.strip()]
            lines = lines[idx + 1:]
    narrative = "\n".join(lines).strip()
    if related is None:
        related = extract_related_from_text(narrative)
    return narrative, related


def task_sources(desc: dict, limit: int = 14, cap: int = 1500) -> list[dict]:
    """Trimmed source material for an agent synthesis task."""
    out = []
    for item in (desc["cited_items"] + desc["supporting_items"])[:limit]:
        body = re.sub(r"\s+", " ", display_body(item["body"])).strip()
        if len(body) > cap:
            body = body[:cap].rsplit(" ", 1)[0] + "..."
        row = {"id": item["id"], "source": item["source"], "body": body}
        if item.get("kind") == "witness_account":
            row["witness"] = item.get("witness") or "another person"
            row["note"] = "second voice — attribute by name, never merge with the author's account"
        out.append(row)
    return out


def build_synthesis_prompt(desc: dict, roster: list[dict], mission: str) -> str:
    src_lines = []
    has_witness = False
    has_corrected = False
    for item in (desc["cited_items"] + desc["supporting_items"])[:14]:
        if item.get("corrected"):
            has_corrected = True
        body = re.sub(r"\s+", " ", display_body(item["body"])).strip()
        if len(body) > 1500:
            body = body[:1500].rsplit(" ", 1)[0] + "..."
        if item.get("kind") == "witness_account":
            has_witness = True
            witness = item.get("witness") or "another person"
            src_lines.append(f"[{item['id']}] (WITNESS ACCOUNT — {witness}'s words, not the author's) ({item['source']}): {body}")
        else:
            src_lines.append(f"[{item['id']}] ({item['source']}): {body}")
    roster_lines = [f"- {r['slug']} — {r['title']} ({r['type']})" for r in roster]
    if desc["type"] == "life" and desc.get("origin") == "hub":
        lens = ("This page is an honest self-portrait of the author. From the source "
                "material, synthesize who they are: their core values, what drives and "
                "what scares them, the contradictions between how they act and how they "
                "see themselves, and who they are becoming. Write in third person, warm "
                "but unflinching. This is the heart of the wiki — understanding this person.")
    elif desc["type"] == "life":
        lens = ("This page is one chapter of the author's life story. Synthesize the "
                "narrative and what it reveals about who they became.")
    elif desc["type"] in ("place", "period", "object"):
        lens = (f"This page is a {desc['type']} in the author's life. Synthesize what it "
                f"was and — most importantly — what it meant to them and what it stands for "
                f"in their story.")
    else:
        lens = ""
    return f"""You are compiling a private, owner-only life-story wiki. Write the entry for one page.
{lens}

PRIVACY CONTRACT — READ FIRST: this wiki is the author's PERMANENTLY PRIVATE
mirror. It is never published, never shared, and raw sources never leave the
repo; anything ever shown to anyone else is generated later as a separate,
owner-reviewed build. Therefore: be honest and unflinching. Do NOT sanitize,
soften, or omit difficult material — the affair, the crisis, the doubt, the
repair — when the sources hold it. A marriage page that hides the near-ending
and the rebuilding is a worse page, not a safer one; the rebuilding is usually
the point. Sensitive material BELONGS here; the tier system protects it
downstream, not you.


PAGE TITLE: {desc['title']}
PAGE TYPE: {desc['type']}

MISSION / VOICE CONTEXT (for tone only):
{mission.strip()}

SOURCE MATERIAL — the ONLY facts you may use. Do not invent names, dates, events,
or feelings that are not present below:
{chr(10).join(src_lines) or '(no source material yet)'}

Artifact/context sources marked `authored_expression`, `derived_context`, or
similar are the author's later expression or a working context pack. Use them
as attributed support, not as independent proof of every underlying event.
{f'''
Text under "{CORRECTION_MARKER}" is the author's LATER, AUTHORITATIVE fix to
the source above it: the correction overrides the original claim. Use the
corrected fact; never assert the corrected-away version, and don't narrate
the correction process itself unless the page is about that change.
''' if has_corrected else ''}
{'''
WITNESS ACCOUNTS are a second voice: another person's words about shared
events. NEVER merge a witness account into the author's account or present it
as the author's memory. Attribute it by name ("Mom remembers it as...").
When the two accounts disagree, PRESERVE BOTH tellings side by side —
"perspectives differ" is data about the relationship, never an error to
resolve or average away.
''' if has_witness else ''}
OTHER WIKI PAGES — choose related pages ONLY from this list, referencing them by slug:
{chr(10).join(roster_lines) or '(none yet)'}

Write a synthesized, encyclopedia-style entry about this {desc['type']} as flowing
markdown prose (2-4 short paragraphs). Be faithful to the source material above and
never fabricate. You may use ## subheadings if helpful. Do NOT restate the page title
as a top heading, and do NOT include a sources list, related-pages list, or backlinks
in your prose — those are added automatically.

Then pick the slugs of the other pages most genuinely related to this one (0-8), drawn
only from the list above.

Respond with ONLY a JSON object, no prose around it:
{{"narrative": "<markdown prose>", "related": ["slug1", "slug2"]}}"""


def fallback_synthesis(desc: dict) -> dict:
    """Deterministic excerpt rendering used when no LLM is available."""
    lines = cited_blocks(desc["cited_items"]) or ["No answered source material yet."]
    return {"narrative": "\n".join(lines), "related": [], "synthesized": False}


def synthesize(desc, roster, model, cache, mission, use_ai, dry_run):
    key = cache_key(desc)
    if key in cache:
        cached = cache[key]
        return {"narrative": cached["narrative"], "related": cached.get("related", []), "synthesized": True}
    # Keyless desktop path: prose written by the agent (via the /compile skill).
    # Takes precedence over call_ai so Claude Code can synthesize without a key.
    agent_file = SYNTH_DIR / f"{desc['slug']}.md"
    if agent_file.exists():
        raw = agent_file.read_text(encoding="utf-8", errors="replace").strip()
        if raw:
            narrative, related = parse_agent_narrative(raw)
            if not dry_run:
                cache[key] = {"narrative": narrative, "related": related}
                agent_file.unlink()  # consumed into the cache
            return {"narrative": narrative, "related": related, "synthesized": True}
    if not use_ai or dry_run:
        return fallback_synthesis(desc)
    try:
        prompt = build_synthesis_prompt(desc, roster, mission)
        raw = call_ai(prompt, model)
        data = parse_ai_json(raw)
        narrative = str(data.get("narrative", "")).strip()
        if not narrative:
            raise ValueError("empty narrative")
        related = [s for s in data.get("related", []) if isinstance(s, str)]
        cache[key] = {"narrative": narrative, "related": related}
        return {"narrative": narrative, "related": related, "synthesized": True}
    except Exception as exc:  # noqa: BLE001 — any LLM/parse failure → safe fallback
        print(f"  ⚠ synthesis failed for {desc['slug']} ({exc}); using excerpt fallback")
        return fallback_synthesis(desc)


# ---------------------------------------------------------------------------
# Cross-link pass — derive related + backlinks from the page graph
# ---------------------------------------------------------------------------


def compute_crosslinks(descs, synths):
    existing = {d["slug"] for d in descs}

    # Shared-source edges: pages citing the same answer/source file are related.
    source_to_slugs = defaultdict(set)
    for d in descs:
        for src in d["sources"]:
            source_to_slugs[src].add(d["slug"])
    shared = defaultdict(Counter)
    for slugs in source_to_slugs.values():
        for a in sorted(slugs):
            for b in sorted(slugs):
                if a != b:
                    shared[a][b] += 1

    final_related = {}
    for d in descs:
        slug = d["slug"]
        related: list[str] = []
        # 1) LLM-chosen + explicit seed edges (kept in order, deduped, must exist).
        for cand in synths[slug]["related"] + d["seed_related"]:
            if cand in existing and cand != slug and cand not in related:
                related.append(cand)
        # 2) shared-source edges, strongest first; ties broken by slug so the
        #    output is stable across runs (set iteration order is not).
        ranked = sorted(shared[slug].items(), key=lambda kv: (-kv[1], kv[0]))
        added = 0
        for cand, _count in ranked:
            if added >= MAX_SHARED or len(related) >= MAX_RELATED:
                break
            if cand != slug and cand not in related:
                related.append(cand)
                added += 1
        final_related[slug] = related[:MAX_RELATED]

    # Backlinks: who points at me (excluding edges already shown under related).
    backlinks = {}
    for d in descs:
        slug = d["slug"]
        bl = sorted(
            other for other in existing
            if slug in final_related.get(other, []) and other not in final_related[slug]
        )
        backlinks[slug] = bl

    return final_related, backlinks


# ---------------------------------------------------------------------------
# Write pass
# ---------------------------------------------------------------------------


def render_page(desc, synth, related, backlinks, slug_title):
    from lifehug_core import sensitivity_floor  # noqa: PLC0415
    floor = sensitivity_floor(
        item.get("sensitivity", "private")
        for item in desc["cited_items"] + desc["supporting_items"])
    body = [
        frontmatter(desc["title"], desc["type"], desc["sources"], related,
                    synthesized=bool(synth["synthesized"]), origin=desc.get("origin", "focus"),
                    section=desc.get("section", ""), chrono=desc.get("chrono"),
                    sensitivity=floor),
        "",
        f"# {desc['title']}",
        "",
        f"> {desc['summary']}",
        "",
    ]
    if synth["synthesized"]:
        body.append(synth["narrative"])
        body.extend(["", "## Sources"])
        body.extend(cited_blocks(desc["cited_items"]) or ["No answered source material yet."])
    else:
        body.append("## What We Know")
        body.extend(cited_blocks(desc["cited_items"]) or ["No answered source material yet."])
    if desc["supporting_items"]:
        body.extend(["", "## Supporting Story Sources"])
        body.extend(cited_blocks(desc["supporting_items"]))

    body.extend(["", "## Related Pages"])
    if related:
        body.extend(f"- [[{s}]] — {slug_title.get(s, s)}" for s in related)
    else:
        body.append("No related pages identified yet.")

    if backlinks:
        body.extend(["", "## Backlinks"])
        body.extend(f"- [[{s}]] — {slug_title.get(s, s)}" for s in backlinks)

    body.extend(["", f"## {desc['open_questions_header']}"])
    body.extend(desc["open_questions"] or ["No open questions currently tracked."])
    return "\n".join(body)


def update_index(written_pages: list[Path], dry_run=False):
    cfg = load_config()
    author_full = cfg.get("full_name") or cfg.get("name") or "Me"

    def label(page: Path) -> str:
        title = frontmatter_value(page.read_text(encoding="utf-8", errors="replace"), "title")
        return title or page.stem.replace("-", " ").title()

    def chrono_key(page: Path) -> tuple:
        """Sort key for periods: by chrono rank (1 = earliest), pages without a
        rank sort last, alphabetical within ties. Earliest life stage on top."""
        raw = frontmatter_value(page.read_text(encoding="utf-8", errors="replace"), "chrono")
        try:
            rank = int(raw)
        except (TypeError, ValueError):
            rank = 10**6
        return (rank, page.stem)

    sections = []

    # Featured first: the person and their life story (the heart of the wiki).
    life_pages = sorted(p for p in TYPE_DIRS["life"].glob("*.md") if p.name != ".gitkeep")
    hub = next((p for p in life_pages if p.stem == slugify(author_full)), None)
    arcs = [p for p in life_pages if p is not hub]
    if hub or arcs:
        sections.append(f"_Understanding {author_full} — the life story so far._")
        sections.append("")
        if hub:
            sections.append(f"- **[{author_full} — who I am]({rel(hub)})**")
        for page in arcs:
            sections.append(f"- [{label(page)}]({rel(page)})")
        sections.append("")

    for page_type, directory in TYPE_DIRS.items():
        if page_type == "life":
            continue  # already featured above
        page_glob = [p for p in directory.glob("*.md") if p.name != ".gitkeep"]
        if not page_glob:
            continue  # skip entity types with no pages — no orphan headers
        # Periods read chronologically (earliest life stage on top); everything
        # else is alphabetical.
        pages = sorted(page_glob, key=chrono_key) if page_type == "period" else sorted(page_glob)
        sections.append(f"## {SECTION_LABELS.get(page_type, page_type.title() + 's')}")
        for page in pages:
            sections.append(f"- [{label(page)}]({rel(page)})")
        sections.append("")
    text = f"# {author_full}\n\n" + "\n".join(sections).rstrip() + "\n"
    write_page(WIKI_DIR / "index.md", text, dry_run)

    if written_pages and not dry_run:
        log = WIKI_DIR / "log.md"
        existing = log.read_text(encoding="utf-8") if log.exists() else "# Lifehug Compile Log\n"
        stamp = datetime.now().isoformat(timespec="seconds")
        additions = "\n".join(f"- {stamp}: updated {rel(p)}" for p in written_pages)
        write_text(log, existing.rstrip() + "\n" + additions + "\n")


def compile_timeline(dry_run: bool = False) -> bool:
    """Compile wiki/timeline.md as the committed, phone-readable EXPORT of the
    viewer's Timeline view (v102). Everything derives from
    timeline.timeline_data() — periods as headers with their placed events
    (the owner's manual 📌 placements honored), then the explicit unplaced
    bucket — so the export can never contradict the curated view. Dating is
    by the author's own words and landmark anchors; absolute years are
    deliberately NOT inferred (they telescope). Skipped when no events exist."""
    import timeline as tl_mod  # noqa: PLC0415
    import timeline_corroboration as tcorr  # noqa: PLC0415

    # Honor this module's (possibly monkeypatched) roots for the call.
    saved = (tl_mod.CLASSIFICATIONS_DIR, tl_mod.STATE_DIR, tl_mod.WIKI_DIR,
             tl_mod.PLACEMENTS_FILE)
    tl_mod.CLASSIFICATIONS_DIR = STATE_DIR / "classifications"
    tl_mod.STATE_DIR = STATE_DIR
    tl_mod.WIKI_DIR = WIKI_DIR
    tl_mod.PLACEMENTS_FILE = STATE_DIR / "timeline_placements.json"
    try:
        data = tl_mod.timeline_data()
    finally:
        (tl_mod.CLASSIFICATIONS_DIR, tl_mod.STATE_DIR, tl_mod.WIKI_DIR,
         tl_mod.PLACEMENTS_FILE) = saved

    total = data["counts"]["events_placed"] + data["counts"]["events_unplaced"]
    if not total:
        return False

    def event_line(e: dict) -> str:
        when = e["when_hint"] or "(undated)"
        anchor_part = f" · anchor: {e['anchor']}" if e["anchor"] else ""
        pin = " · 📌 placed by you" if e.get("placement") == "manual" else ""
        badge = (f" · ✉ {tcorr.badge_text(e['corroboration'])}"
                 if e.get("corroboration") else "")
        return f"- **{when}** — {e['description']}{anchor_part}{pin}{badge}  \n  _source: {e['source']}_"

    lines = [
        "---",
        'title: "Timeline"',
        "type: meta",
        "visibility: owner_only",
        "---",
        "",
        "# Timeline",
        "",
        "Generated export of the viewer's Timeline view (/views/timeline).",
        "Datable moments from classified sources, placed into periods by shared",
        "sources, the author's own time words, and the owner's manual placements",
        "(📌). Absolute years are deliberately NOT inferred (they telescope).",
        "",
    ]
    for period in data["periods"]:
        events = data["event_lineup"].get(period["slug"], [])
        if not events:
            continue
        header = f"## {period['name']}"
        if period.get("corroboration"):
            # v110: same connector-evidence badge as the viewer's period row.
            header += f" — ✉ {tcorr.badge_text(period['corroboration'])}"
        lines.append(header)
        lines.append("")
        lines.extend(event_line(e) for e in events)
        lines.append("")
    if data["unplaced_events"]:
        lines.append("## Unplaced")
        lines.append("")
        lines.extend(event_line(e) for e in data["unplaced_events"])
        lines.append("")
    write_page(WIKI_DIR / "timeline.md", "\n".join(lines), dry_run)
    return True


# Entity types whose mention-graduated pages are cleaned up when their entity
# leaves the roster. Focus/hand-authored pages are never candidates.
_MENTION_CLEANUP_TYPES = ("person", "place", "period", "object", "theme")


def cleanup_orphan_entity_pages(planned_slugs: set[str], dry_run: bool = False) -> list[Path]:
    """Remove mention-origin entity pages whose entity left the roster.

    When the monthly roster refresh drops, merges, or remaps an entity, its old
    compiled page would otherwise linger forever (and stay in the index, which
    globs directories). Guard rails:
      - a type is skipped entirely when its roster file is missing/empty (fresh
        install, keyless machine, failed refresh — never delete on no signal);
      - only pages with frontmatter `origin: mention` are candidates — focus and
        hand-authored pages are structurally untouchable;
      - a page is kept if its slug was planned this compile OR belongs to a
        still page-eligible, unmapped roster entity (it may just have missed
        the mention threshold this run). Entities demoted or mapped to a Focus
        deliberately lose their standalone page.
    Pages are compiled artifacts in a git repo — deletion is recoverable.
    """
    removed: list[Path] = []
    for entity_type in _MENTION_CLEANUP_TYPES:
        roster_entities = (load_roster(entity_type) or {}).get("entities") or []
        if not roster_entities:
            continue  # no roster signal → never delete
        keep_slugs = set(planned_slugs)
        for ent in roster_entities:
            if ent.get("page_eligible") and not ent.get("maps_to_focus"):
                slug = ent.get("slug") or slugify(ent.get("name", ""))
                if slug:
                    keep_slugs.add(slug)
        directory = TYPE_DIRS[entity_type]
        if not directory.exists():
            continue
        for page in sorted(directory.glob("*.md")):
            if page.name == ".gitkeep" or page.stem in keep_slugs:
                continue
            text = page.read_text(encoding="utf-8", errors="replace")
            if frontmatter_value(text, "origin") != "mention":
                continue  # never touch focus/hand-authored pages
            if dry_run:
                print(f"  ✗ would remove orphan {rel(page)} — no longer in the {entity_type} roster")
            else:
                page.unlink()
                print(f"  ✗ removed orphan {rel(page)} — no longer in the {entity_type} roster")
            removed.append(page)
    if removed and not dry_run:
        log = WIKI_DIR / "log.md"
        existing = log.read_text(encoding="utf-8") if log.exists() else "# Lifehug Compile Log\n"
        stamp = datetime.now().isoformat(timespec="seconds")
        additions = "\n".join(f"- {stamp}: removed {rel(p)} (left the roster)" for p in removed)
        write_text(log, existing.rstrip() + "\n" + additions + "\n")
    return removed


def get_model(args) -> str:
    if getattr(args, "model", None):
        return args.model
    return load_config().get("wiki_model", DEFAULT_MODEL)


def main():
    parser = argparse.ArgumentParser(description="Compile Lifehug answers into the private wiki")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-ai", action="store_true", help="Skip LLM synthesis; use deterministic excerpts only")
    parser.add_argument("--model", help="Override the synthesis model")
    parser.add_argument("--emit-tasks", metavar="PATH",
                        help="Write per-page synthesis tasks to PATH and exit (keyless agent path; "
                             "no model call). The agent writes each task's prose, then re-run compile.")
    args = parser.parse_args()

    WIKI_DIR.mkdir(exist_ok=True)
    for directory in TYPE_DIRS.values():
        directory.mkdir(parents=True, exist_ok=True)

    md_text = QUESTIONS_FILE.read_text()
    questions = parse_questions(md_text)
    categories = parse_categories(md_text)
    answers = read_answers()
    manual_sources = read_manual_sources()
    # Correction/retraction resolution: corrections override their targets'
    # claims; retractions drop targets from pages (scoped or global).
    global _RETRACTIONS
    manual_sources, _corrections, _RETRACTIONS = split_correction_layer(manual_sources)
    _n_corrected = apply_corrections(answers, manual_sources, _corrections)
    if _n_corrected or _RETRACTIONS:
        print(f"  ⚖ corrections applied: {_n_corrected}; retractions active: {len(_RETRACTIONS)}")
    cfg = load_config()
    author = cfg.get("name", "Me")
    author_full = cfg.get("full_name") or author
    person_roster = load_roster("person")
    focus_slugs = {slugify(clean_focus_name(info["name"]))
                   for info in categories.values() if info.get("group") == "focus"}

    # 1. plan — the person's own life story leads.
    descs = []
    descs += plan_life_story(categories, questions, answers, manual_sources, author_full)
    descs += plan_focuses(categories, questions, answers, manual_sources, person_roster)
    descs += plan_projects(categories, questions, answers, manual_sources)
    descs += plan_themes(answers, manual_sources, load_roster("theme"), slugify(author_full))
    descs += plan_relationships(categories, questions, answers, manual_sources, author, person_roster)
    descs += plan_self(questions, answers)

    # Entity/node graduation: build out every node of the life graph from mentions —
    # people, then places, periods, and symbolic objects. taken_slugs accumulates
    # so a slug is never double-built across types.
    taken_slugs = set(focus_slugs) | {d["slug"] for d in descs}
    for entity_type in ("person", "place", "period", "object"):
        descs += plan_entities(entity_type, answers, manual_sources,
                               load_roster(entity_type), taken_slugs)

    slug_title = {d["slug"]: d["title"] for d in descs}
    roster = [{"slug": d["slug"], "title": d["title"], "type": d["type"]} for d in descs]

    # 2. synthesize
    use_ai = not args.no_ai
    model = get_model(args)
    mission = load_mission()
    cache = read_json(SYNTH_CACHE_FILE, {}) or {}

    # Keyless agent path: emit synthesis tasks for any page not already cached
    # or drafted, then exit. The agent fills each task's narrative_path; the
    # next compile consumes those drafts. No model call here.
    if args.emit_tasks:
        SYNTH_DIR.mkdir(parents=True, exist_ok=True)
        tasks = []
        for d in descs:
            if cache_key(d) in cache or (SYNTH_DIR / f"{d['slug']}.md").exists():
                continue
            others = [r for r in roster if r["slug"] != d["slug"]]
            tasks.append({
                "slug": d["slug"],
                "type": d["type"],
                "title": d["title"],
                "narrative_path": str(SYNTH_DIR / f"{d['slug']}.md"),
                "instructions": (
                    "This wiki is the author's PERMANENTLY PRIVATE mirror — never "
                    "published; audience surfaces are separate owner-reviewed builds. "
                    "Be honest and unflinching: do not sanitize or omit difficult "
                    "material the sources hold. Witness accounts are another "
                    "person's words — attribute by name, never merge."),
                "sources": task_sources(d),
                "related_candidates": others,
            })
        Path(args.emit_tasks).write_text(
            json.dumps(tasks, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"✓ Emitted {len(tasks)} synthesis task(s) to {args.emit_tasks}")
        if tasks:
            print("  Write each task's prose to its narrative_path, then run: "
                  "python3 system/lifehug.py compile")
        return

    synths = {}
    for d in descs:
        others = [r for r in roster if r["slug"] != d["slug"]]
        synths[d["slug"]] = synthesize(d, others, model, cache, mission, use_ai, args.dry_run)

    # 3. cross-link
    final_related, backlinks = compute_crosslinks(descs, synths)

    # 4. write
    written = []
    preserved = 0
    for d in descs:
        # Non-destructive guard: never downgrade an already-synthesized page to a
        # raw excerpt fallback (e.g. on a keyless machine with no cache/draft).
        # Keep the last good prose; the page refreshes when a real synthesis is
        # available (compile machine, or the /compile skill writes a draft).
        if d["path"].exists() and should_preserve_existing(
                d["path"].read_text(encoding="utf-8", errors="replace"),
                synths[d["slug"]]["synthesized"]):
            preserved += 1
            print(f"  ↻ preserved {d['slug']} (no key/draft to refresh)")
            continue
        text = render_page(d, synths[d["slug"]], final_related[d["slug"]], backlinks[d["slug"]], slug_title)
        if write_page(d["path"], text, args.dry_run):
            written.append(d["path"])
    removed = cleanup_orphan_entity_pages(taken_slugs, args.dry_run)
    compile_timeline(args.dry_run)
    update_index(written, args.dry_run)

    if not args.dry_run:
        write_json(SYNTH_CACHE_FILE, cache)

    suffix = f" ({preserved} preserved)" if preserved else ""
    if removed:
        suffix += f", {len(removed)} orphan(s) removed"
    print(f"✓ Wiki compile complete: {len(written)} page updates{suffix}")


if __name__ == "__main__":
    main()
