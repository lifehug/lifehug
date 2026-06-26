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
    MANUAL_SOURCES_DIR,
    QUESTIONS_FILE,
    REPO_DIR,
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
    write_json,
    write_text,
)
from research_expand import DEFAULT_MODEL, call_ai, parse_ai_json
from roadmap import load_roadmap

TYPE_DIRS = {
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
CACHE_VERSION = "v1"
SYNTH_CACHE_FILE = STATE_DIR / "wiki_synthesis_cache.json"
# Drop-zone for keyless desktop synthesis: when the skill runs through Claude
# Code, the agent writes each page's prose here (state/synthesis/<slug>.md) and
# the next compile consumes it into the cache. No API key / gateway needed.
SYNTH_DIR = STATE_DIR / "synthesis"

MAX_RELATED = 12  # total related links per page
MAX_SHARED = 8    # shared-source links added per page


def clean_spotlight_name(name: str) -> str:
    for prefix in ("Spotlight — ", "Spotlight - ", "Spotlight: ", "Spotlight "):
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
        }
    return answers


def strip_frontmatter(text: str) -> str:
    return re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, count=1, flags=re.DOTALL).strip()


def frontmatter_value(text: str, key: str, default: str = "") -> str:
    match = re.search(rf"^{re.escape(key)}:\s*[\"']?(.+?)[\"']?\s*$", text, re.MULTILINE)
    return match.group(1).strip().strip('"').strip("'") if match else default


def read_manual_sources() -> dict[str, dict]:
    sources = {}
    if not MANUAL_SOURCES_DIR.exists():
        return sources
    for path in sorted(MANUAL_SOURCES_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        title = frontmatter_value(text, "title", path.stem.replace("-", " ").title())
        body = strip_frontmatter(text)
        body = re.sub(r"^# .+?\n+", "", body, count=1).strip()
        source_id = f"source:{path.stem}"
        sources[source_id] = {
            "id": source_id,
            "path": path,
            "source": rel(path),
            "title": title,
            "body": body,
            "kind": "manual_source",
        }
    return sources


def frontmatter(title: str, page_type: str, sources: list[str], related: list[str] | None = None) -> str:
    today = date.today().isoformat()
    related = related or []
    lines = [
        "---",
        f'title: "{title}"',
        f"type: {page_type}",
        "status: active",
        "visibility: owner_only",
        "sensitivity: personal",
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


def cited_blocks(items: list[dict], limit: int = 8) -> list[str]:
    blocks = []
    for item in items[:limit]:
        body = re.sub(r"\s+", " ", item["body"]).strip()
        if len(body) > 420:
            body = body[:420].rsplit(" ", 1)[0] + "..."
        blocks.append(f"- **{item['id']}**: {body} [{item['source']}]")
    return blocks


def matching_sources(sources: dict[str, dict], terms: list[str]) -> list[dict]:
    clean_terms = [term.lower() for term in terms if term and len(term.strip()) >= 3]
    matches = []
    for source in sources.values():
        haystack = f"{source.get('title', '')} {source.get('body', '')}".lower()
        if any(term in haystack for term in clean_terms):
            matches.append(source)
    return matches


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
                seed_related=None):
    return {
        "type": page_type,
        "title": title,
        "slug": slug,
        "path": TYPE_DIRS[page_type] / f"{slug}.md",
        "sources": sources,
        "cited_items": cited_items,
        "supporting_items": supporting_items,
        "summary": summary,
        "open_questions": open_questions,
        "open_questions_header": open_questions_header,
        "seed_related": seed_related or [],
    }


def plan_spotlights(categories, questions, answers, manual_sources):
    descs = []
    for cat_id, info in sorted(categories.items()):
        if info.get("group") != "spotlight":
            continue
        title = clean_spotlight_name(info["name"])
        slug = slugify(title)
        answer_items = [answers[q["id"]] for q in questions if q["category"] == cat_id and q["id"] in answers]
        source_items = matching_sources(manual_sources, [title])
        sources = [a["source"] for a in answer_items] + [s["source"] for s in source_items]
        descs.append(_descriptor(
            "person", title, slug, sources, answer_items, source_items,
            summary=f"A Lifehug spotlight compiled from {len(answer_items)} answered prompts. "
                    f"Owner-only; cites its source answers.",
            open_questions=unanswered_questions(questions, cat_id),
        ))
    return descs


def plan_projects(categories, questions, answers, manual_sources):
    descs = []
    for cat_id, info in sorted(categories.items()):
        if info.get("group") != "project":
            continue
        title = info["name"]
        slug = slugify(title)
        answer_items = [answers[q["id"]] for q in questions if q["category"] == cat_id and q["id"] in answers]
        source_items = matching_sources(manual_sources, [title, title.replace("The ", "")])
        sources = [a["source"] for a in answer_items] + [s["source"] for s in source_items]
        descs.append(_descriptor(
            "project", title, slug, sources, answer_items, source_items,
            summary=f"A project thread compiled from category {cat_id} and {len(answer_items)} answered prompts.",
            open_questions=unanswered_questions(questions, cat_id),
        ))
    return descs


def plan_themes(answers, manual_sources):
    descs = []
    for theme, keywords in sorted(THEME_KEYWORDS.items()):
        hits = []
        for item in list(answers.values()) + list(manual_sources.values()):
            haystack = item["body"].lower()
            if any(keyword in haystack for keyword in keywords):
                hits.append(item)
        if not hits:
            continue
        title = theme.replace("-", " ").title()
        sources = [a["source"] for a in hits]
        descs.append(_descriptor(
            "theme", title, theme, sources, hits, [],
            summary=f"A recurring Lifehug theme found across {len(hits)} source answers.",
            open_questions=[
                f"- Where does {title.lower()} first appear in the author's life?",
                f"- How has {title.lower()} changed across different periods, relationships, and projects?",
            ],
        ))
    return descs


def plan_relationships(categories, questions, answers, author):
    descs = []
    author = author or "Me"
    author_slug = slugify(author)
    for cat_id, info in sorted(categories.items()):
        if info.get("group") != "spotlight":
            continue
        person = clean_spotlight_name(info["name"])
        person_slug = slugify(person)
        answer_items = [answers[q["id"]] for q in questions if q["category"] == cat_id and q["id"] in answers]
        if not answer_items:
            continue
        title = f"{author} & {person}"
        slug = f"{author_slug}-and-{person_slug}"
        sources = [a["source"] for a in answer_items]
        descs.append(_descriptor(
            "relationship", title, slug, sources, answer_items, [],
            summary=f"The relationship between {author} and {person}, synthesized from "
                    f"{len(answer_items)} answered prompts. Owner-only; cites its sources.",
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
        body = re.sub(r"\s+", " ", item["body"]).strip()
        if len(body) > cap:
            body = body[:cap].rsplit(" ", 1)[0] + "..."
        out.append({"id": item["id"], "source": item["source"], "body": body})
    return out


def build_synthesis_prompt(desc: dict, roster: list[dict], mission: str) -> str:
    src_lines = []
    for item in (desc["cited_items"] + desc["supporting_items"])[:14]:
        body = re.sub(r"\s+", " ", item["body"]).strip()
        if len(body) > 1500:
            body = body[:1500].rsplit(" ", 1)[0] + "..."
        src_lines.append(f"[{item['id']}] ({item['source']}): {body}")
    roster_lines = [f"- {r['slug']} — {r['title']} ({r['type']})" for r in roster]
    return f"""You are compiling a private, owner-only life-story wiki. Write the entry for one page.

PAGE TITLE: {desc['title']}
PAGE TYPE: {desc['type']}

MISSION / VOICE CONTEXT (for tone only):
{mission.strip()}

SOURCE MATERIAL — the ONLY facts you may use. Do not invent names, dates, events,
or feelings that are not present below:
{chr(10).join(src_lines) or '(no source material yet)'}

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
    body = [
        frontmatter(desc["title"], desc["type"], desc["sources"], related),
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
    sections = []
    for page_type, directory in TYPE_DIRS.items():
        title = page_type.title() + "s"
        sections.append(f"## {title}")
        pages = sorted(p for p in directory.glob("*.md") if p.name != ".gitkeep")
        if pages:
            for page in pages:
                label = page.stem.replace("-", " ").title()
                sections.append(f"- [{label}]({rel(page)})")
        else:
            sections.append("")
        sections.append("")
    text = "# Lifehug Wiki Index\n\n" + "\n".join(sections).rstrip() + "\n"
    write_page(WIKI_DIR / "index.md", text, dry_run)

    if written_pages and not dry_run:
        log = WIKI_DIR / "log.md"
        existing = log.read_text(encoding="utf-8") if log.exists() else "# Lifehug Wiki Compile Log\n"
        stamp = datetime.now().isoformat(timespec="seconds")
        additions = "\n".join(f"- {stamp}: updated {rel(p)}" for p in written_pages)
        write_text(log, existing.rstrip() + "\n" + additions + "\n")


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
    author = load_config().get("name", "Me")

    # 1. plan
    descs = []
    descs += plan_spotlights(categories, questions, answers, manual_sources)
    descs += plan_projects(categories, questions, answers, manual_sources)
    descs += plan_themes(answers, manual_sources)
    descs += plan_relationships(categories, questions, answers, author)
    descs += plan_self(questions, answers)

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
    for d in descs:
        text = render_page(d, synths[d["slug"]], final_related[d["slug"]], backlinks[d["slug"]], slug_title)
        if write_page(d["path"], text, args.dry_run):
            written.append(d["path"])
    update_index(written, args.dry_run)

    if not args.dry_run:
        write_json(SYNTH_CACHE_FILE, cache)

    print(f"✓ Wiki compile complete: {len(written)} page updates")


if __name__ == "__main__":
    main()
