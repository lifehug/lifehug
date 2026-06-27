#!/usr/bin/env python3
"""Shared Lifehug parsing and state helpers."""

from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
REPO_DIR = SYSTEM_DIR.parent
QUESTIONS_FILE = SYSTEM_DIR / "question-bank.md"
ROTATION_FILE = SYSTEM_DIR / "rotation.json"
COVERAGE_FILE = SYSTEM_DIR / "coverage.json"
CONFIG_FILE = REPO_DIR / "config.yaml"
README_FILE = REPO_DIR / "README.md"
ANSWERS_DIR = REPO_DIR / "answers"
OUTPUTS_DIR = REPO_DIR / "outputs"
TEMPLATES_DIR = REPO_DIR / "templates"
STATE_DIR = REPO_DIR / "state"
WIKI_DIR = REPO_DIR / "wiki"
SOURCES_DIR = REPO_DIR / "sources"
MANUAL_SOURCES_DIR = SOURCES_DIR / "manual"
IMPORT_SOURCES_DIR = SOURCES_DIR / "imports"
CORRECTION_SOURCES_DIR = SOURCES_DIR / "corrections"
QUESTION_CANDIDATES_FILE = STATE_DIR / "question_candidates.json"
QUESTION_QUEUE_FILE = STATE_DIR / "question_queue.json"
PLANNER_STATE_FILE = STATE_DIR / "planner_state.json"
SOURCE_MANIFEST_FILE = STATE_DIR / "source_manifest.json"
SOURCE_LINT_FINDINGS_FILE = STATE_DIR / "source_lint_findings.json"
MISSION_FILE = SYSTEM_DIR / "mission.md"
CLASSIFICATIONS_DIR = STATE_DIR / "classifications"
NEIGHBORHOODS_FILE = STATE_DIR / "neighborhoods.json"
FOCUS_RECS_FILE = STATE_DIR / "focus_recommendations.json"
LEGACY_FOCUS_RECS_FILE = STATE_DIR / ("spot" "light_recommendations.json")
CONNECTORS_DIR = SYSTEM_DIR / "connectors"

QUESTION_ID_RE = r"[A-Z]\d+[a-z]*"
QUESTION_LINE_RE = re.compile(
    rf"^- \[([ xX])\] ({QUESTION_ID_RE}): (.+?)(?:\s+\*\(.+\)\*)?\s*$",
    re.MULTILINE,
)
CATEGORY_HEADER_RE = re.compile(r"^## ([A-Z]): (.+?)(?:\s*\(.*\))?\s*$")

STORY_FUNCTIONS = (
    "foundation",
    "scene",
    "tension",
    "turning_point",
    "relationship",
    "meaning",
    "contradiction",
    "output_gap",
    # self-knowledge arc (WNRS / 36-Questions / IFS style)
    "self_image",
    "value",
    "fear",
    "perception_by_others",
    "growth_edge",
    # relational / dyadic arc
    "who_they_are",
    "shared_history",
    "what_i_see_in_them",
    "what_i_want_them_to_know",
    "how_they_see_me",
)


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path, default=None):
    try:
        with path.open() as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent) as f:
        json.dump(data, f, indent=2)
        f.write("\n")
        tmp = Path(f.name)
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent) as f:
        f.write(text)
        tmp = Path(f.name)
    tmp.replace(path)


def load_config(path: Path = CONFIG_FILE) -> dict[str, str]:
    """Load the simple top-level scalar subset of config.yaml used by scripts."""
    config: dict[str, str] = {}
    if not path.exists():
        return config
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        if not key.strip() or val.strip().startswith("|"):
            continue
        config[key.strip()] = val.split("#", 1)[0].strip().strip('"').strip("'")
    return config


def normalize_group(group: str | None) -> str:
    """Normalize old category group names to the current vocabulary."""
    if group == "spot" "light":
        return "focus"
    return group or "main"


def category_group(cat_id: str, section_group: str | None = None) -> str:
    section_group = normalize_group(section_group)
    if section_group in {"main", "project", "focus"}:
        return section_group
    if cat_id >= "K":
        return "focus"
    if cat_id >= "F":
        return "project"
    return "main"


def parse_categories(md_text: str) -> dict[str, dict[str, str]]:
    """Discover categories and their metadata from question-bank.md."""
    categories: dict[str, dict[str, str]] = {}
    group = "main"
    for line in md_text.splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("## focus") or stripped.startswith("## " + ("spot" "light")):
            group = "focus"
            continue
        if stripped.startswith("## project"):
            group = "project"
            continue

        match = CATEGORY_HEADER_RE.match(line)
        if match:
            cat_id = match.group(1)
            name = match.group(2).strip()
            categories[cat_id] = {"name": name, "group": category_group(cat_id, group)}
    return categories


def parse_questions(md_text: str) -> list[dict[str, object]]:
    """Parse question-bank.md into question records.

    Supports base IDs (`A14`) and generated follow-up IDs (`A14a`, `G5c`).
    """
    questions: list[dict[str, object]] = []
    for match in QUESTION_LINE_RE.finditer(md_text):
        qid = match.group(2)
        questions.append({
            "id": qid,
            "category": qid[0],
            "text": match.group(3).strip(),
            "answered": match.group(1).lower() == "x",
        })
    return questions


def question_by_id(questions: list[dict[str, object]], question_id: str):
    wanted = question_id.strip()
    return next((q for q in questions if q["id"] == wanted), None)


def compute_coverage(
    questions: list[dict[str, object]],
    categories: dict[str, dict[str, str]],
) -> dict:
    coverage = {
        "version": 1,
        "last_updated": datetime.now().isoformat(),
        "categories": {},
    }
    known_cats = sorted(set(categories) | {str(q["category"]) for q in questions})
    for cat_id in known_cats:
        cat_qs = [q for q in questions if q["category"] == cat_id]
        total = len(cat_qs)
        answered = sum(1 for q in cat_qs if q["answered"])
        ratio = answered / total if total else 0
        if ratio >= 0.7:
            status = "green"
        elif ratio >= 0.3:
            status = "yellow"
        else:
            status = "red"
        coverage["categories"][cat_id] = {
            "total": total,
            "answered": answered,
            "status": status,
        }
    return coverage


def rebuild_coverage() -> dict:
    md_text = QUESTIONS_FILE.read_text()
    questions = parse_questions(md_text)
    categories = parse_categories(md_text)
    coverage = compute_coverage(questions, categories)
    write_json(COVERAGE_FILE, coverage)
    return coverage


def mark_answered_in_bank(question_id: str, answered_date: str | None = None) -> bool:
    md = QUESTIONS_FILE.read_text()
    date_text = answered_date or datetime.now().date().isoformat()
    qid = re.escape(question_id)
    pattern = re.compile(
        rf"^(- \[) \] ({qid}: .+?)(?:\s+\*\(.+\)\*)?\s*$",
        re.MULTILINE,
    )
    new_md, count = pattern.subn(rf"\1x] \2 *({date_text})*", md, count=1)
    if count:
        write_text(QUESTIONS_FILE, new_md)
        return True
    return False


def answer_id_from_filename(path: Path) -> str | None:
    match = re.match(rf"^({QUESTION_ID_RE})", path.stem)
    return match.group(1) if match else None


def split_frontmatter(content: str) -> tuple[dict[str, object], str]:
    """Return simple YAML-ish frontmatter and body.

    Lifehug only emits scalar JSON-compatible values in frontmatter, so this
    intentionally stays small instead of depending on a YAML parser.
    """
    if not content.startswith("---\n"):
        return {}, content
    lines = content.splitlines()
    end_index = None
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = idx
            break
    if end_index is None:
        return {}, content

    metadata: dict[str, object] = {}
    for raw in lines[1:end_index]:
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if not value:
            metadata[key] = ""
            continue
        try:
            metadata[key] = json.loads(value)
        except json.JSONDecodeError:
            metadata[key] = value.strip('"').strip("'")

    body = "\n".join(lines[end_index + 1:])
    if body.startswith("\n"):
        body = body[1:]
    if content.endswith("\n"):
        body += "\n"
    return metadata, body


def answer_body(content: str) -> str:
    _metadata, frontmatter_body = split_frontmatter(content)
    target = frontmatter_body if frontmatter_body != content else content
    body_match = re.search(r"---\n+(.*?)(?:\n+---|\Z)", target, re.DOTALL)
    if body_match:
        return body_match.group(1).strip()
    return target.strip()


def status_emoji(answered: int, total: int) -> str:
    if total == 0:
        return "⚪"
    ratio = answered / total
    if ratio >= 0.7:
        return "🟢"
    if ratio >= 0.3:
        return "🟡"
    return "🔴"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return slug.strip("-") or "untitled"


def load_mission() -> str:
    """Load mission.md content for AI prompt injection."""
    if MISSION_FILE.exists():
        return MISSION_FILE.read_text(encoding="utf-8")
    return ""
