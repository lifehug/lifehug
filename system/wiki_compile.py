#!/usr/bin/env python3
"""Compile Lifehug answers into the private Lifehug wiki."""

from __future__ import annotations

import argparse
import re
from datetime import date, datetime
from pathlib import Path

from lifehug_core import (
    ANSWERS_DIR,
    MANUAL_SOURCES_DIR,
    QUESTIONS_FILE,
    REPO_DIR,
    WIKI_DIR,
    answer_body,
    answer_id_from_filename,
    load_config,
    parse_categories,
    parse_questions,
    slugify,
    write_text,
)
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


def compile_spotlights(categories, questions, answers, manual_sources, dry_run=False):
    written = []
    for cat_id, info in sorted(categories.items()):
        if info.get("group") != "spotlight":
            continue
        title = clean_spotlight_name(info["name"])
        slug = slugify(title)
        answer_items = [answers[q["id"]] for q in questions if q["category"] == cat_id and q["id"] in answers]
        source_items = matching_sources(manual_sources, [title])
        sources = [a["source"] for a in answer_items] + [s["source"] for s in source_items]
        body = [
            frontmatter(title, "person", sources),
            "",
            f"# {title}",
            "",
            f"> A Lifehug spotlight compiled from {len(answer_items)} answered prompts. "
            f"This page is owner-only and cites its source answers.",
            "",
            "## What We Know",
        ]
        if answer_items:
            body.extend(cited_blocks(answer_items))
        else:
            body.append("No answered source material yet.")
        if source_items:
            body.extend(["", "## Supporting Story Sources"])
            body.extend(cited_blocks(source_items))
        body.extend(["", "## Open Questions"])
        body.extend(unanswered_questions(questions, cat_id) or ["No open questions currently tracked."])
        body.extend(["", "## Related Pages"])
        body.append("- [[family]] — many person spotlights connect through family and formative relationships")
        path = TYPE_DIRS["person"] / f"{slug}.md"
        if write_page(path, "\n".join(body), dry_run):
            written.append(path)
    return written


def compile_projects(categories, questions, answers, manual_sources, dry_run=False):
    written = []
    for cat_id, info in sorted(categories.items()):
        if info.get("group") != "project":
            continue
        title = info["name"]
        slug = slugify(title)
        answer_items = [answers[q["id"]] for q in questions if q["category"] == cat_id and q["id"] in answers]
        source_items = matching_sources(manual_sources, [title, title.replace("The ", "")])
        sources = [a["source"] for a in answer_items] + [s["source"] for s in source_items]
        body = [
            frontmatter(title, "project", sources),
            "",
            f"# {title}",
            "",
            f"> A project thread compiled from category {cat_id} and {len(answer_items)} answered prompts.",
            "",
            "## What We Know",
        ]
        body.extend(cited_blocks(answer_items) or ["No answered source material yet."])
        if source_items:
            body.extend(["", "## Supporting Story Sources"])
            body.extend(cited_blocks(source_items))
        body.extend(["", "## Open Questions"])
        body.extend(unanswered_questions(questions, cat_id) or ["No open questions currently tracked."])
        body.extend(["", "## Related Pages"])
        body.append("- [[themes]] — project stories often connect back to recurring life themes")
        path = TYPE_DIRS["project"] / f"{slug}.md"
        if write_page(path, "\n".join(body), dry_run):
            written.append(path)
    return written


def compile_themes(answers, manual_sources, dry_run=False):
    written = []
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
        body = [
            frontmatter(title, "theme", sources),
            "",
            f"# {title}",
            "",
            f"> A recurring Lifehug theme found across {len(hits)} source answers.",
            "",
            "## Source Signals",
        ]
        body.extend(cited_blocks(hits, limit=12))
        body.extend([
            "",
            "## Open Questions",
            f"- Where does {title.lower()} first appear in the author's life?",
            f"- How has {title.lower()} changed across different periods, relationships, and projects?",
            "",
            "## Related Pages",
            "- [[people]] — themes are often carried through relationships",
            "- [[periods]] — themes often change shape across seasons of life",
        ])
        path = TYPE_DIRS["theme"] / f"{theme}.md"
        if write_page(path, "\n".join(body), dry_run):
            written.append(path)
    return written


def compile_relationships(categories, questions, answers, author, dry_run=False):
    """Build a relationship (dyadic) node per spotlight person: the bond between
    the author and that person. Populates the graph edges in wiki/relationships/
    (previously never written) so cross-entity synthesis is possible later."""
    written = []
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
        body = [
            frontmatter(title, "relationship", sources, related=[person_slug]),
            "",
            f"# {title}",
            "",
            f"> The relationship between {author} and {person}, synthesized from "
            f"{len(answer_items)} answered prompts. Owner-only; cites its sources.",
            "",
            "## What We Know",
        ]
        body.extend(cited_blocks(answer_items, limit=10))
        body.extend([
            "",
            "## Open Questions (dyadic)",
            f"- What does {author} most want {person} to understand?",
            f"- How does {author} think {person} sees them — and is it accurate?",
            f"- What has gone unsaid between {author} and {person}?",
            "",
            "## Related Pages",
            f"- [[{person_slug}]] — the person profile this relationship centers on",
        ])
        path = TYPE_DIRS["relationship"] / f"{slug}.md"
        if write_page(path, "\n".join(body), dry_run):
            written.append(path)
    return written


def compile_self(questions, answers, dry_run=False):
    """Build a self-knowledge surface from answers belonging to self-type
    Focuses (created via `focus-add --type self`). No self Focus → nothing to
    compile yet; the page appears once self-knowledge questions are answered."""
    written = []
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
        body = [
            frontmatter(title, "self", sources),
            "",
            f"# {title}",
            "",
            f"> A self-knowledge surface synthesized from {len(answer_items)} answers — "
            f"patterns, values, fears, and contradictions in the author's own words.",
            "",
            "## What We Know",
        ]
        body.extend(cited_blocks(answer_items, limit=12))
        body.extend([
            "",
            "## Related Pages",
            "- [[themes]] — self-knowledge surfaces recurring themes",
            "- [[people]] — how the author sees themselves shapes their relationships",
        ])
        path = TYPE_DIRS["self"] / f"{slug}.md"
        if write_page(path, "\n".join(body), dry_run):
            written.append(path)
    return written


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


def main():
    parser = argparse.ArgumentParser(description="Compile Lifehug answers into the private wiki")
    parser.add_argument("--dry-run", action="store_true")
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

    written = []
    written.extend(compile_spotlights(categories, questions, answers, manual_sources, args.dry_run))
    written.extend(compile_projects(categories, questions, answers, manual_sources, args.dry_run))
    written.extend(compile_themes(answers, manual_sources, args.dry_run))
    written.extend(compile_relationships(categories, questions, answers, author, args.dry_run))
    written.extend(compile_self(questions, answers, args.dry_run))
    update_index(written, args.dry_run)

    print(f"✓ Wiki compile complete: {len(written)} page updates")


if __name__ == "__main__":
    main()
