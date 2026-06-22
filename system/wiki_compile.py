#!/usr/bin/env python3
"""Compile Lifehug answers into the private Lifehug wiki."""

from __future__ import annotations

import argparse
import re
from datetime import date, datetime
from pathlib import Path

from lifehug_core import (
    ANSWERS_DIR,
    QUESTIONS_FILE,
    REPO_DIR,
    WIKI_DIR,
    answer_body,
    answer_id_from_filename,
    parse_categories,
    parse_questions,
    slugify,
    write_text,
)

TYPE_DIRS = {
    "person": WIKI_DIR / "people",
    "place": WIKI_DIR / "places",
    "period": WIKI_DIR / "periods",
    "project": WIKI_DIR / "projects",
    "theme": WIKI_DIR / "themes",
    "object": WIKI_DIR / "objects",
    "relationship": WIKI_DIR / "relationships",
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


def cited_answer_blocks(answer_items: list[dict], limit: int = 8) -> list[str]:
    blocks = []
    for answer in answer_items[:limit]:
        body = re.sub(r"\s+", " ", answer["body"]).strip()
        if len(body) > 420:
            body = body[:420].rsplit(" ", 1)[0] + "..."
        blocks.append(f"- **{answer['id']}**: {body} [{answer['source']}]")
    return blocks


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


def compile_spotlights(categories, questions, answers, dry_run=False):
    written = []
    for cat_id, info in sorted(categories.items()):
        if info.get("group") != "spotlight":
            continue
        title = clean_spotlight_name(info["name"])
        slug = slugify(title)
        answer_items = [answers[q["id"]] for q in questions if q["category"] == cat_id and q["id"] in answers]
        sources = [a["source"] for a in answer_items]
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
            body.extend(cited_answer_blocks(answer_items))
        else:
            body.append("No answered source material yet.")
        body.extend(["", "## Open Questions"])
        body.extend(unanswered_questions(questions, cat_id) or ["No open questions currently tracked."])
        body.extend(["", "## Related Pages"])
        body.append("- [[family]] — many person spotlights connect through family and formative relationships")
        path = TYPE_DIRS["person"] / f"{slug}.md"
        if write_page(path, "\n".join(body), dry_run):
            written.append(path)
    return written


def compile_projects(categories, questions, answers, dry_run=False):
    written = []
    for cat_id, info in sorted(categories.items()):
        if info.get("group") != "project":
            continue
        title = info["name"]
        slug = slugify(title)
        answer_items = [answers[q["id"]] for q in questions if q["category"] == cat_id and q["id"] in answers]
        sources = [a["source"] for a in answer_items]
        body = [
            frontmatter(title, "project", sources),
            "",
            f"# {title}",
            "",
            f"> A project thread compiled from category {cat_id} and {len(answer_items)} answered prompts.",
            "",
            "## What We Know",
        ]
        body.extend(cited_answer_blocks(answer_items) or ["No answered source material yet."])
        body.extend(["", "## Open Questions"])
        body.extend(unanswered_questions(questions, cat_id) or ["No open questions currently tracked."])
        body.extend(["", "## Related Pages"])
        body.append("- [[themes]] — project stories often connect back to recurring life themes")
        path = TYPE_DIRS["project"] / f"{slug}.md"
        if write_page(path, "\n".join(body), dry_run):
            written.append(path)
    return written


def compile_themes(answers, dry_run=False):
    written = []
    for theme, keywords in sorted(THEME_KEYWORDS.items()):
        hits = []
        for answer in answers.values():
            haystack = answer["body"].lower()
            if any(keyword in haystack for keyword in keywords):
                hits.append(answer)
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
        body.extend(cited_answer_blocks(hits, limit=12))
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

    written = []
    written.extend(compile_spotlights(categories, questions, answers, args.dry_run))
    written.extend(compile_projects(categories, questions, answers, args.dry_run))
    written.extend(compile_themes(answers, args.dry_run))
    update_index(written, args.dry_run)

    print(f"✓ Wiki compile complete: {len(written)} page updates")


if __name__ == "__main__":
    main()
