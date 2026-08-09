#!/usr/bin/env python3
"""Lifehug Studio compute (v127).

The shared, zero-AI compute behind the future Studio view: what has already
been made (outputs/ pieces), what's being made (book-project manuscripts),
and how ready each Focus is to make more — all in one pass, grouped by the
same Focus primitive the roadmap plans by.

Two things live here:

  - ``compute_works`` — a pure read. Scans outputs/ into "piece" dicts (the
    same shape the Artifacts wiki view renders), pulls in book.compute_books()
    projects, and groups both by Focus (roadmap order), with trailing
    "__thoughts__" (subjectless essays) and "__unfiled__" (metadata orphans)
    groups — same grouping rules as serve_wiki.view_artifacts.

  - ``assemble_book`` — the one mutation here: turns a book-project Focus's
    drafted chapters into a single concrete manuscript artifact under
    outputs/, versioned like any other artifact.

Porting note: the outputs/ scan below is a deliberate PORT of the logic
inlined in serve_wiki.view_artifacts (not an import). serve_wiki.py is a
heavy owner-only HTTP-viewer module (argparse, http.server, its whole view
registry); importing it here just to reuse a handful of small formatting
helpers would drag all of that in as a side effect of merely computing
Studio data. The meta.yaml regex-scrape and focus-resolution rules are kept
byte-identical to serve_wiki's so the Artifacts view and Studio agree on
what a "piece" is.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_SYSTEM_DIR = Path(__file__).resolve().parent
if str(_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_DIR))

import artifact
import book
from lifehug_core import (
    OUTPUTS_DIR,
    QUESTIONS_FILE,
    now_utc,
    parse_questions,
    read_json,
    slugify,
)
from roadmap import load_roadmap, rebuild_roadmap

# format_readiness lands with PR2 (issue #126). Guard the import so this
# module keeps working — with empty readiness lists — if it isn't present
# yet (e.g. this branch built ahead of that merge).
try:
    import format_readiness
except ImportError:  # pragma: no cover - exercised once PR2 lands
    format_readiness = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Ported from serve_wiki.view_artifacts — piece scan (see module docstring).
# ---------------------------------------------------------------------------

ARTIFACT_ASSET_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
}

_WORD_RE = re.compile(r"[\w'’-]+")


def _count_words(text: str) -> int:
    return len(_WORD_RE.findall(text)) if text else 0


def _version_numbers(art_dir: Path) -> list[int]:
    numbers = []
    for path in art_dir.glob("v*.md"):
        m = re.match(r"^v(\d+)$", path.stem)
        if m:
            numbers.append(int(m.group(1)))
    return sorted(numbers)


def _version_meta(art_dir: Path) -> tuple[dict, int | None]:
    """{version_number: entry} from artifact.json versions[], plus final_version."""
    data = read_json(art_dir / "artifact.json", default={}) or {}
    meta: dict[int, dict] = {}
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


def _scan_pieces(focuses: list[dict]) -> list[dict]:
    """Scan outputs/ into piece dicts, resolved against Focus categories/labels.

    Kept behaviorally identical to serve_wiki.view_artifacts's inline scan:
    same meta.yaml regex-scrape, same "categories -> focus, subject as
    fallback" resolution, same fields.
    """
    cat_to_focus = {c: f for f in focuses for c in f.get("categories", [])}
    label_to_focus = {str(f.get("label", "")).lower(): f for f in focuses}

    pieces: list[dict] = []
    if not OUTPUTS_DIR.exists():
        return pieces
    for art_dir in sorted(OUTPUTS_DIR.iterdir()):
        if not art_dir.is_dir():
            continue
        meta_path = art_dir / "meta.yaml"
        fmt = subject = created = occasion = ""
        categories: list[str] = []
        if meta_path.exists():
            head = meta_path.read_text(errors="replace")

            def _field(key, _head=head):
                m = re.search(rf"^{key}:\s*(.+)$", _head, re.MULTILINE)
                return m.group(1).strip().strip("'\"") if m else ""

            fmt, subject, created, occasion = (
                _field(k) for k in ("format", "subject", "created", "occasion"))
            m = re.search(r"^categories:\s*\[(.*?)\]", head, re.MULTILINE)
            if m:
                categories = [c.strip().strip("'\"") for c in m.group(1).split(",") if c.strip()]
        versions = sorted(art_dir.glob("v*.md"),
                          key=lambda q: int(re.match(r"v(\d+)", q.stem).group(1))
                          if re.match(r"v(\d+)", q.stem) else 0)
        if not versions and not meta_path.exists():
            continue
        latest = versions[-1] if versions else None
        body = latest.read_text(errors="replace") if latest else ""
        art_json = read_json(art_dir / "artifact.json", default={}) or {}
        occasion = occasion or str(art_json.get("occasion") or "")
        focus = next((cat_to_focus[c] for c in categories if c in cat_to_focus), None)
        if focus is None and subject:
            focus = label_to_focus.get(subject.lower())
        version_meta, final_version = _version_meta(art_dir)
        pieces.append({
            "slug": art_dir.name, "fmt": fmt, "subject": subject,
            "created": created, "occasion": occasion, "focus": focus,
            "n_versions": len(versions),
            "version_numbers": _version_numbers(art_dir),
            "version_meta": version_meta, "final_version": final_version,
            "words": _count_words(body),
            "delivered": bool(art_json.get("delivered_at")),
            "promoted": bool(art_json.get("promoted_sources")),
            "latest_name": latest.name if latest else "", "body": body,
            "assets": sorted(p.name for p in art_dir.iterdir()
                             if p.is_file() and p.suffix.lower() in ARTIFACT_ASSET_TYPES),
        })
    return pieces


def _load_roadmap_focuses() -> list[dict]:
    roadmap_data = load_roadmap()
    if not roadmap_data.get("focuses"):
        try:
            roadmap_data = rebuild_roadmap(write=False)
        except Exception:
            roadmap_data = {"focuses": []}
    return roadmap_data.get("focuses", [])


def _load_questions_default() -> list[dict]:
    if not QUESTIONS_FILE.exists():
        return []
    return parse_questions(QUESTIONS_FILE.read_text(encoding="utf-8"))


def _readiness_for(focus: dict, questions: list[dict]) -> list:
    if format_readiness is None:
        return []
    return format_readiness.readiness_for_focus(focus, questions)


def compute_works(questions: list[dict] | None = None) -> list[dict]:
    """The Studio compute: outputs/ pieces + book projects, grouped by Focus.

    Returns a list of group dicts in roadmap order, each:
        {"focus": <focus dict or None>, "projects": [...], "pieces": [...],
         "readiness": [...]}
    Trailing special groups (no "focus" key value, disambiguated by "key")
    are "__thoughts__" (essay pieces without a Focus) and "__unfiled__"
    (everything else without a Focus) — appended in that order, mirroring
    serve_wiki.view_artifacts's grouping rule.

    Pieces within every group are sorted by (created, slug) descending, same
    as the Artifacts wiki view.
    """
    focuses = _load_roadmap_focuses()
    if questions is None:
        questions = _load_questions_default()

    pieces = _scan_pieces(focuses)

    books = book.compute_books()
    projects_by_focus: dict[str, list[dict]] = {}
    for b in books:
        fid = b.get("id")
        if not fid:
            continue
        projects_by_focus.setdefault(str(fid), []).append({
            "kind": "project", "format": "book", "focus_id": str(fid), "book": b,
        })

    piece_groups: dict[str, list[dict]] = {}
    for piece in pieces:
        if piece["focus"]:
            key = str(piece["focus"]["id"])
        elif piece["fmt"] == "essay":
            key = "__thoughts__"
        else:
            key = "__unfiled__"
        piece_groups.setdefault(key, []).append(piece)

    def _sorted_pieces(items: list[dict]) -> list[dict]:
        return sorted(items, key=lambda a: (a["created"], a["slug"]), reverse=True)

    groups: list[dict] = []
    for focus in focuses:
        fid = str(focus.get("id"))
        items = piece_groups.get(fid, [])
        projects = projects_by_focus.get(fid, [])
        if not items and not projects:
            continue
        groups.append({
            "focus": focus,
            "projects": projects,
            "pieces": _sorted_pieces(items),
            "readiness": _readiness_for(focus, questions),
        })

    for special_key in ("__thoughts__", "__unfiled__"):
        items = piece_groups.get(special_key)
        if not items:
            continue
        groups.append({
            "focus": None,
            "key": special_key,
            "projects": [],
            "pieces": _sorted_pieces(items),
            "readiness": [],
        })

    return groups


# ---------------------------------------------------------------------------
# assemble_book — book Focus -> concrete manuscript artifact
# ---------------------------------------------------------------------------


def _find_book(focus_id: str) -> dict | None:
    for b in book.compute_books():
        if str(b.get("id")) == str(focus_id):
            return b
    return None


def _chapter_draft_bodies(category_id: str, drafts_by_cat: dict) -> list[str]:
    """Read every chapter-format draft's LATEST body for one category.

    A chapter that weaves more than one draft artifact into it (rare, but
    book._load_drafts_by_category allows it) gets every draft's body, in the
    same stable order _load_drafts_by_category returns them, joined with a
    blank line — never picked-and-dropped.
    """
    bodies = []
    for slug, _words in drafts_by_cat.get(category_id, []):
        draft_dir = book.OUTPUTS_DIR / slug
        latest = book._latest_version(draft_dir)  # noqa: SLF001 - shared scan helper
        if latest is None:
            continue
        try:
            bodies.append(latest.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return bodies


def _slug_for_focus_book(focus_id: str) -> str:
    """Stable slug for a focus's assembled manuscript — same focus, same
    outputs/ artifact, every time (re-assembly is a new version, not a new
    piece).

    Keyed on the focus ID, not its label: labels can be renamed (which would
    orphan the manuscript and reset its version chain) and two focuses'
    labels can slugify identically (which would collide into one artifact).
    """
    return slugify(f"{focus_id} book")


def assemble_book(focus_id: str, force: bool = False) -> dict:
    """Compose a book-project Focus's drafted chapters into one manuscript.

    Raises ValueError if `focus_id` doesn't name a book-deliverable Focus, or
    if that Focus has no drafted chapters yet (nothing to assemble). Chapters
    without a draft get a `_(not yet drafted)_` placeholder so the manuscript
    always shows its own gaps.

    Without `force`, a re-assemble whose composed manuscript is byte-identical
    to the latest saved version is a no-op (returns the existing version info
    rather than writing a redundant version); `force=True` always writes a new
    version.
    """
    target = _find_book(focus_id)
    if target is None:
        raise ValueError(f"no book-deliverable focus found for id {focus_id!r}")
    if not any(ch.get("has_draft") for ch in target["chapters"]):
        raise ValueError(
            f"focus {focus_id!r} has no drafted chapters yet — nothing to assemble"
        )

    drafts_by_cat = book._load_drafts_by_category()  # noqa: SLF001 - shared scan helper

    lines = [f"# {target['label']}"]
    chapters_included = 0
    chapters_placeholder = 0
    for ch in target["chapters"]:
        lines += ["", "", f"## {ch['category_name']}", ""]
        bodies = _chapter_draft_bodies(ch["category_id"], drafts_by_cat) if ch.get("has_draft") else []
        if bodies:
            lines.append("\n\n".join(bodies))
            chapters_included += 1
        else:
            lines.append("_(not yet drafted)_")
            chapters_placeholder += 1
    manuscript = "\n".join(lines).rstrip() + "\n"

    slug = _slug_for_focus_book(focus_id)
    out_dir = artifact.OUTPUTS_DIR / slug

    if artifact.artifact_path(out_dir).exists():
        meta = artifact.load_artifact(out_dir)
        # Adopt ONLY this focus's own manuscript. An unrelated user artifact
        # that happens to sit at the derived slug must never be written into:
        # appending the manuscript to it corrupts the user's piece, and if
        # that piece carries categories + a chapter-class format, the
        # manuscript body gets re-counted as chapter-draft material — the
        # exact runaway self-inclusion the empty-categories rule prevents.
        if (meta.get("artifact_id") != slug
                or meta.get("format") != "book"
                or meta.get("categories")):
            raise ValueError(
                f"outputs/{slug} exists but is not this focus's assembled "
                "manuscript (different artifact_id/format/categories) — "
                "refusing to write into it; move or rename that artifact"
            )
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
        created = now_utc()
        meta = {
            "version": 1,
            "artifact_id": slug,
            "title": f"{target['label']} — Manuscript",
            "format": "book",
            "subject": target["label"],
            "occasion": "",
            "occasion_date": "",
            "audience": "",
            "privacy": "owner_only",
            # No context pack: the manuscript IS the composed material, not a
            # generation task, so context.md is never built or referenced for
            # anything but this recorded (unused) path.
            #
            # Deliberately NOT `target["categories"]`: book._load_drafts_by_category
            # treats any outputs/ artifact with format in {chapter, book, memoir,
            # manuscript} AND a non-empty categories list as chapter-draft
            # material. Tagging the assembled manuscript with the focus's full
            # category list would make it re-count itself as "the chapter
            # draft" for every one of its own chapters on the next assemble
            # (runaway self-inclusion), and would permanently inflate
            # book-status's drafted-words/has_draft numbers with the whole
            # manuscript's body. Leaving categories empty excludes it from
            # that scan entirely; Focus resolution for this piece falls
            # through to the subject-label match instead (see
            # studio._scan_pieces / serve_wiki.view_artifacts), which works
            # because `subject` above is set to the focus label.
            "categories": [],
            "created_at": created,
            "updated_at": created,
            "context_path": artifact.rel(out_dir / artifact.CONTEXT_FILE),
            "context_sources": [],
            "versions": [],
            "promoted_sources": [],
        }
        artifact.save_artifact(out_dir, meta)
        artifact.write_compose_meta(out_dir, meta)

    existing_latest = artifact.latest_version_file(out_dir)
    if not force and existing_latest is not None:
        try:
            current_body = existing_latest.read_text(encoding="utf-8", errors="replace")
        except OSError:
            current_body = None
        # save_version always appends its own trailing "\n" to whatever it's
        # given (artifact.py:save_version), so the stored file never equals
        # our freshly-composed `manuscript` byte-for-byte even when nothing
        # changed — compare with trailing newlines normalized away.
        if current_body is not None and current_body.rstrip("\n") == manuscript.rstrip("\n"):
            return {
                "slug": slug,
                "path": artifact.rel(existing_latest),
                "version": int(existing_latest.stem[1:]),
                "chapters_included": chapters_included,
                "chapters_placeholder": chapters_placeholder,
                "words": _count_words(manuscript),
            }

    version = artifact.save_version(out_dir, meta, manuscript, model="assemble",
                                    feedback="", final=False)
    return {
        "slug": slug,
        "path": artifact.rel(out_dir / f"v{version}.md"),
        "version": version,
        "chapters_included": chapters_included,
        "chapters_placeholder": chapters_placeholder,
        "words": _count_words(manuscript),
    }
