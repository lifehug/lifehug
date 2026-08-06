#!/usr/bin/env python3
"""Lifehug book assembly (v75 phase 1 + v76 phase 2).

Turns the Focus + question-bank model into a chapter-shaped view of the memoir,
so the flagship deliverable has a path to existence. Every book-project Focus
(deliverable in {book, chapter, memoir}) becomes a book; each of its question
categories becomes a chapter with:

  - answered count / total  (raw completeness)
  - answered %              (the readiness bar you can see)
  - avg five-slot depth     (McAdams scene coverage from state/classifications)
  - readiness verdict       (EARLY / DEVELOPING / READY / SATURATED)
  - top gap questions       (highest-priority unanswered questions in the chapter)
  - a manuscript hook       (the wiki life-arc page that already synthesizes it)
  - draft word count        (v76: scanned from outputs/, matched to this chapter)

Zero AI calls on the compute path. All read-only inspection over live state.

v76 adds phase 2:
  - manuscript rollup: outputs/ chapter drafts get counted; each chapter/book
    reports drafted words vs. a target (target = category question count * 350)
  - milestone offer tracking (state/book_offers.json): remembers which
    (book, chapter) pairs have already been offered so process_answer only
    fires the offer once per crossing
  - gap-question boost: nearly-ready chapters expose their top gap ids so the
    planner can prioritise them in the weekly queue (see question_planner)
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

_SYSTEM_DIR = Path(__file__).resolve().parent
if str(_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_DIR))

from lifehug_core import (
    BOOK_OFFERS_FILE,
    CLASSIFICATIONS_DIR,
    OUTPUTS_DIR,
    QUESTIONS_FILE,
    WIKI_DIR,
    now_utc,
    parse_categories,
    parse_questions,
    read_json,
    slugify,
    write_json,
)
from roadmap import load_roadmap, rebuild_roadmap


# Deliverables that produce a book (as opposed to a letter, tweet, etc.).
BOOK_DELIVERABLES = {"book", "chapter", "memoir", "manuscript"}

# Readiness thresholds keyed to the same verdict vocabulary as progress.py, so
# "READY" here means the same thing "READY" means on the Focuses view.
READY = 0.70
DEVELOPING = 0.40

# The five-slot scene probe (McAdams via v70/research.md). A "deep" answer for
# a memoir chapter fills all five; we count what fraction we have.
# NAMES MUST MATCH the classifier's scene_slots schema in classify_story.py —
# a mismatch reads as permanently-empty slots (caught by the contract test in
# tests/test_v75_book.py).
FIVE_SLOTS = ("what_happened", "when_and_where", "who_was_there",
              "thought_and_felt", "what_it_says_about_me")

# Phase 2: word-count target per chapter is coarse on purpose. We anchor it to
# the number of questions in the chapter (~350 words per answer's worth of
# material is typical literary-nonfiction density). It's a compass, not a
# ruler — chapters that don't need this many words shouldn't be padded.
WORDS_PER_QUESTION_TARGET = 350

# Persisted memory of which chapter milestones have been announced so the
# process_answer hook can fire an offer exactly once per crossing.
def _verdict(saturation: float, saturated: bool = False) -> tuple[str, str]:
    if saturated:
        return "SATURATED", "well-known — maintenance"
    if saturation >= READY:
        return "READY", "ready to draft"
    if saturation >= DEVELOPING:
        return "DEVELOPING", "building material"
    return "EARLY", "needs more answers"


def _load_scene_slots() -> dict[str, dict[str, bool]]:
    """Return {question_id: {slot: bool}}.

    Classifier stamps `scene_slots` per source (a source is one answer file
    like answers/D9.md), so we key by answer stem which is also the question
    id. Missing files, missing slots, and pre-v70 classifications all read as
    all-empty — never crashes, never lies about depth.
    """
    out: dict[str, dict[str, bool]] = {}
    if not CLASSIFICATIONS_DIR.exists():
        return out
    for path in sorted(CLASSIFICATIONS_DIR.glob("*.json")):
        data = read_json(path, default={}) or {}
        # source_path looks like "answers/D9.md" — stem is the question id.
        src = str(data.get("source_path", "")).strip()
        if not src.startswith("answers/") or not src.endswith(".md"):
            continue
        qid = Path(src).stem
        slots = data.get("scene_slots", {}) or {}
        if not isinstance(slots, dict):
            continue
        out[qid] = {slot: bool(slots.get(slot)) for slot in FIVE_SLOTS}
    return out


def _life_arc_page(category_id: str, category_name: str) -> str | None:
    """Best-effort link to the wiki life-story arc page for this chapter.

    The v34 life pages live at wiki/life/<arc-slug>.md — Origins, Becoming,
    Relationships & People, Etherfuse & Purpose, Reflection & Wisdom, etc.
    We match on the category NAME slug (already the label the wiki uses),
    which keeps this stable if a category's letter code ever changes.
    """
    if not category_name:
        return None
    stem = slugify(category_name)
    for cand in (WIKI_DIR / "life" / f"{stem}.md",
                 WIKI_DIR / "projects" / f"{stem}.md"):
        try:
            if cand.exists():
                return cand.relative_to(WIKI_DIR.parent).as_posix()
        except (OSError, ValueError):
            continue
    return None


def _priority(q: dict) -> float:
    """Sort key for gap questions: use stored priority when present, otherwise
    fall back to a stable, string-comparable id so output is deterministic."""
    try:
        return float(q.get("priority", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Phase 2: manuscript rollup — count words in outputs/ chapter drafts
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[\w'’-]+", re.UNICODE)


def _count_words(text: str) -> int:
    """Loose but stable word count — tokens of word chars, apostrophes, hyphens.

    Frontmatter isn't stripped here (the caller passes in the body only). The
    goal is a compass number, not typographic accuracy.
    """
    if not text:
        return 0
    return sum(1 for _ in _WORD_RE.finditer(text))


def _latest_version(out_dir: Path) -> Path | None:
    """Return the highest-numbered vN.md in an outputs/ artifact dir, or None.

    The artifact workflow saves versions as v1.md, v2.md, …; we score the
    latest so revisions replace their predecessors instead of being summed.
    """
    if not out_dir.is_dir():
        return None
    best_n = -1
    best_path: Path | None = None
    for path in out_dir.glob("v*.md"):
        m = re.match(r"^v(\d+)\.md$", path.name)
        if not m:
            continue
        n = int(m.group(1))
        if n > best_n:
            best_n = n
            best_path = path
    return best_path


def _read_artifact_meta(out_dir: Path) -> dict | None:
    """Best-effort meta.yaml parse. Returns None on missing / unreadable files.

    Only the fields we need (format, categories, subject) are pulled out; we
    tolerate the flat format compose.py writes and never crash on surprise.
    """
    meta_path = out_dir / "meta.yaml"
    if not meta_path.exists():
        return None
    meta: dict = {"categories": []}
    for raw in meta_path.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip("'\"")
        if key == "categories" and val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            meta["categories"] = [x.strip().upper() for x in inner.split(",") if x.strip()]
        elif key in ("format", "subject", "title"):
            meta[key] = val
    return meta


def _load_drafts_by_category() -> dict[str, list[tuple[str, int]]]:
    """Scan outputs/ for chapter-format drafts and bucket them by category.

    Returns {category_letter: [(artifact_slug, word_count), …]}. A draft
    contributes to every category listed in its meta.yaml (a chapter that
    weaves Origins + Becoming counts toward both). Only the LATEST version of
    each artifact is counted, so revisions never inflate the total.
    """
    out: dict[str, list[tuple[str, int]]] = {}
    if not OUTPUTS_DIR.exists():
        return out
    for artifact_dir in sorted(OUTPUTS_DIR.iterdir()):
        if not artifact_dir.is_dir():
            continue
        meta = _read_artifact_meta(artifact_dir)
        if not meta:
            continue
        # Only chapter-format drafts count toward the manuscript; letters,
        # tweets, and posts have their own progress model.
        fmt = str(meta.get("format", "")).lower().strip()
        if fmt not in ("chapter", "book", "memoir", "manuscript"):
            continue
        cats = meta.get("categories") or []
        if not cats:
            continue
        latest = _latest_version(artifact_dir)
        if latest is None:
            continue
        try:
            body = latest.read_text(errors="replace")
        except OSError:
            continue
        words = _count_words(body)
        if words <= 0:
            continue
        for cat in cats:
            out.setdefault(str(cat).upper(), []).append((artifact_dir.name, words))
    return out


def compute_chapter(category_id: str,
                    category_name: str,
                    questions_in_cat: list[dict],
                    scene_slots: dict[str, dict[str, bool]],
                    drafts_by_cat: dict[str, list[tuple[str, int]]] | None = None,
                    max_gap_questions: int = 5) -> dict:
    total = len(questions_in_cat)
    answered_qs = [q for q in questions_in_cat if q.get("answered")]
    unanswered_qs = [q for q in questions_in_cat if not q.get("answered")]
    answered = len(answered_qs)

    # Answered ratio — the readiness spine. Empty chapters read as EARLY, not
    # ready-by-vacuous-truth.
    saturation = (answered / total) if total else 0.0

    # Five-slot depth across the answers we DO have. Averaged over answers, not
    # over slots — an unanswered question can't fill slots.
    scene_total = 0
    scene_filled = 0
    for q in answered_qs:
        qid = q.get("id", "")
        # Absent classifications mean "not scored yet" — count as five empty
        # slots so the number honestly reflects what the system knows.
        slots = scene_slots.get(qid, {slot: False for slot in FIVE_SLOTS})
        for slot in FIVE_SLOTS:
            scene_total += 1
            if slots.get(slot):
                scene_filled += 1
    scene_ratio = (scene_filled / scene_total) if scene_total else 0.0

    tag, label = _verdict(saturation)

    # Top gap questions, sorted by priority (desc), then id (asc) for stability.
    gaps = sorted(unanswered_qs,
                  key=lambda q: (-_priority(q), str(q.get("id", ""))))[:max_gap_questions]

    # Phase 2: manuscript progress — sum words from every chapter-format
    # draft that lists this category. Target scales with the number of
    # questions in the chapter (WORDS_PER_QUESTION_TARGET); zero-question
    # chapters skip the target so we never divide by zero.
    drafts_by_cat = drafts_by_cat if drafts_by_cat is not None else _load_drafts_by_category()
    drafts_here = drafts_by_cat.get(category_id, [])
    drafted_words = sum(w for _, w in drafts_here)
    manuscript_target = total * WORDS_PER_QUESTION_TARGET
    manuscript_ratio = (drafted_words / manuscript_target) if manuscript_target else 0.0

    return {
        "category_id": category_id,
        "category_name": category_name,
        "slug": slugify(category_name or f"chapter-{category_id}"),
        "total": total,
        "answered": answered,
        "saturation": saturation,
        "scene_slot_ratio": scene_ratio,
        "scene_slots_filled": scene_filled,
        "scene_slots_total": scene_total,
        "verdict": tag,
        "verdict_label": label,
        "ready_to_draft": tag in ("READY", "SATURATED"),
        "gap_questions": [
            {"id": q.get("id"), "text": q.get("text", "")} for q in gaps
        ],
        "manuscript_hook": _life_arc_page(category_id, category_name),
        # Phase 2 fields
        "drafts": [{"artifact": name, "words": w} for name, w in drafts_here],
        "drafted_words": drafted_words,
        "manuscript_target": manuscript_target,
        "manuscript_ratio": manuscript_ratio,
        "has_draft": bool(drafts_here),
    }


def compute_book(focus: dict,
                 questions: list[dict],
                 categories: dict[str, dict],
                 scene_slots: dict[str, dict[str, bool]],
                 drafts_by_cat: dict[str, list[tuple[str, int]]] | None = None) -> dict:
    """Turn one book-project Focus into a book with a chapter list."""
    cat_ids: list[str] = list(focus.get("categories", []) or [])
    drafts_by_cat = drafts_by_cat if drafts_by_cat is not None else _load_drafts_by_category()
    chapters = []
    total_q = total_a = 0
    total_drafted = 0
    total_target = 0
    drafted_chapter_count = 0
    for cid in cat_ids:
        cat_name = categories.get(cid, {}).get("name", "") or f"Category {cid}"
        qs_in_cat = [q for q in questions if str(q.get("category", "")) == cid]
        ch = compute_chapter(cid, cat_name, qs_in_cat, scene_slots, drafts_by_cat=drafts_by_cat)
        chapters.append(ch)
        total_q += ch["total"]
        total_a += ch["answered"]
        total_drafted += ch["drafted_words"]
        total_target += ch["manuscript_target"]
        if ch["has_draft"]:
            drafted_chapter_count += 1

    saturation = (total_a / total_q) if total_q else 0.0
    tag, label = _verdict(saturation)
    ready_chapters = sum(1 for c in chapters if c["ready_to_draft"])
    manuscript_ratio = (total_drafted / total_target) if total_target else 0.0

    return {
        "id": focus.get("id"),
        "label": focus.get("label"),
        "objective": focus.get("objective", ""),
        "deliverable": focus.get("deliverable", "book"),
        "primary": bool(focus.get("primary")),
        "categories": cat_ids,
        "chapters": chapters,
        "chapter_count": len(chapters),
        "chapters_ready": ready_chapters,
        "chapters_drafted": drafted_chapter_count,
        "total_questions": total_q,
        "answered_questions": total_a,
        "saturation": saturation,
        "verdict": tag,
        "verdict_label": label,
        # Phase 2: manuscript rollup
        "drafted_words": total_drafted,
        "manuscript_target": total_target,
        "manuscript_ratio": manuscript_ratio,
    }


def compute_books() -> list[dict]:
    """All book-project Focuses, each with its full chapter breakdown.

    Books are ordered: primary Focus first (the author's own life story), then
    others by descending target_depth so the biggest projects lead. Non-book
    deliverables are skipped — letters and tweets don't need a chapter map.
    """
    roadmap = load_roadmap()
    if not roadmap.get("focuses"):
        try:
            roadmap = rebuild_roadmap(write=False)
        except Exception:
            roadmap = {"focuses": []}

    if not QUESTIONS_FILE.exists():
        return []

    md = QUESTIONS_FILE.read_text(encoding="utf-8")
    questions = parse_questions(md)
    categories = parse_categories(md)
    scene_slots = _load_scene_slots()
    # Phase 2: scan outputs/ once, share the result across every chapter so a
    # book map with 10 chapters still only walks the filesystem once.
    drafts_by_cat = _load_drafts_by_category()

    books = []
    for focus in roadmap.get("focuses", []):
        deliverable = str(focus.get("deliverable", "")).lower().strip()
        if deliverable not in BOOK_DELIVERABLES:
            continue
        if not focus.get("categories"):
            # A zombie focus can't be a book — no chapters to hang on.
            continue
        books.append(compute_book(focus, questions, categories, scene_slots,
                                  drafts_by_cat=drafts_by_cat))

    books.sort(key=lambda b: (
        0 if b["primary"] else 1,
        -int(b.get("total_questions") or 0),
        str(b.get("label", "")),
    ))
    return books


# ---------------------------------------------------------------------------
# Phase 2: milestone offers (chapter-just-went-READY → one-time Telegram nudge)
# ---------------------------------------------------------------------------


def _load_offers_state() -> dict:
    """Track which (book, chapter) pairs the offer hook has already announced.

    Shape: {"offered": {"<book_id>:<chapter_cat_id>": "<ISO ts>"}, "version": 1}
    Missing / malformed on disk → a clean empty state, never a crash.
    """
    data = read_json(BOOK_OFFERS_FILE, default={}) or {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("version", 1)
    offered = data.get("offered")
    if not isinstance(offered, dict):
        offered = {}
    data["offered"] = offered
    return data


def _offer_key(book_id: str, chapter_cat_id: str) -> str:
    return f"{book_id}:{chapter_cat_id}"


def _mark_offered(book_id: str, chapter_cat_id: str) -> None:
    """Persist that we announced this chapter so we don't spam on the next answer."""
    state = _load_offers_state()
    state["offered"][_offer_key(book_id, chapter_cat_id)] = now_utc()
    write_json(BOOK_OFFERS_FILE, state)


def already_offered(book_id: str, chapter_cat_id: str) -> bool:
    return _offer_key(book_id, chapter_cat_id) in _load_offers_state()["offered"]


def newly_ready_chapters(books: list[dict] | None = None) -> list[tuple[dict, dict]]:
    """Chapters that are READY (or SATURATED) and haven't been offered yet.

    Returns (book, chapter) tuples. The process_answer hook calls this after
    saving an answer; the first crossing wins, subsequent no-ops are silent.
    """
    books = books if books is not None else compute_books()
    out: list[tuple[dict, dict]] = []
    for b in books:
        for ch in b["chapters"]:
            if not ch["ready_to_draft"]:
                continue
            # Chapters that already have a draft don't need to be re-offered —
            # the point of the offer is the transition, not maintenance.
            if ch.get("has_draft"):
                continue
            if already_offered(str(b.get("id", "")), ch["category_id"]):
                continue
            out.append((b, ch))
    return out


def format_chapter_offer(book: dict, chapter: dict) -> str:
    """The one-line-plus-command Telegram message body for a chapter offer.

    Keep it short: the point is "want to draft this?", not a report. The exact
    artifact command is included so Dave can copy-paste it, or a future button
    handler can capture it verbatim.
    """
    label = book.get("label", "(untitled book)")
    cat = chapter["category_id"]
    name = chapter["category_name"]
    ratio = chapter["saturation"]
    cmd = (f'python3 system/lifehug.py artifact new --format chapter '
           f'--subject "{name}" --categories {cat}')
    return (
        f"📖 Book milestone — chapter READY\n"
        f"{label} → [{cat}] {name}\n"
        f"{chapter['answered']}/{chapter['total']} answered ({ratio:.0%})\n\n"
        f"Want to draft it? Reply with the chapter letter, or run:\n{cmd}"
    )


def send_ready_offers(books: list[dict] | None = None, dry_run: bool = False) -> list[dict]:
    """Fire one-time Telegram offers for chapters that just went READY.

    Returns a list of {book, chapter, sent} rows so the caller can log what
    happened. `dry_run=True` computes the list without sending or marking, so
    the offer surface is exercisable in tests and CLI previews.
    """
    from lifehug_core import send_telegram  # noqa: PLC0415

    rows: list[dict] = []
    for book, chapter in newly_ready_chapters(books):
        sent = False
        if not dry_run:
            sent = send_telegram(format_chapter_offer(book, chapter))
            if sent:
                _mark_offered(str(book.get("id", "")), chapter["category_id"])
        rows.append({
            "book_id": book.get("id"),
            "book_label": book.get("label"),
            "chapter_id": chapter["category_id"],
            "chapter_name": chapter["category_name"],
            "sent": sent,
            "dry_run": dry_run,
        })
    return rows


# ---------------------------------------------------------------------------
# Phase 2: gap-question boost — exposes near-ready chapters' top gaps so the
# planner can prioritise them in the weekly queue.
# ---------------------------------------------------------------------------

# A "nearly-ready" chapter is one whose answered ratio sits in the top slice
# below READY; that's where an extra push actually matters. Chapters way below
# the threshold don't get the boost — filling one gap doesn't move them.
NEARLY_READY_MIN = 0.50


def gap_question_ids(max_per_chapter: int = 2,
                     books: list[dict] | None = None) -> list[str]:
    """Top-priority unanswered question ids from chapters that could tip READY.

    Order: nearly-ready chapters (closer to READY first), then a couple of gaps
    per chapter. The planner takes this as a boost list — asked BEFORE random
    coverage picks, capped so it can't crowd out the rest of the mix.
    """
    books = books if books is not None else compute_books()
    scored: list[tuple[float, str]] = []
    for b in books:
        for ch in b["chapters"]:
            if ch["ready_to_draft"]:
                continue  # already there, no boost needed
            if ch["saturation"] < NEARLY_READY_MIN:
                continue  # too far away for one gap to matter
            # Chapters closer to READY score higher (rank by 1 - distance).
            distance = max(READY - ch["saturation"], 0.0)
            for gap in ch["gap_questions"][:max_per_chapter]:
                qid = gap.get("id")
                if qid:
                    scored.append((distance, str(qid)))
    scored.sort(key=lambda pair: (pair[0], pair[1]))
    return [qid for _, qid in scored]


def find_book(book_id: str) -> dict | None:
    for book in compute_books():
        if str(book.get("id")) == book_id or slugify(str(book.get("label", ""))) == slugify(book_id):
            return book
    return None


def find_chapter(book_id: str, chapter_ref: str) -> tuple[dict, dict] | None:
    """Look up (book, chapter) by book id/slug and chapter category id or slug."""
    book = find_book(book_id)
    if not book:
        return None
    target = str(chapter_ref).strip()
    target_slug = slugify(target)
    for chapter in book["chapters"]:
        if (chapter["category_id"] == target
                or chapter["slug"] == target_slug):
            return book, chapter
    return None


# ---------------------------------------------------------------------------
# CLI helpers (called from lifehug.py wrappers)
# ---------------------------------------------------------------------------


def _bar_text(ratio: float, width: int = 16) -> str:
    r = max(0.0, min(1.0, float(ratio)))
    filled = int(round(r * width))
    return "█" * filled + "·" * (width - filled)


def print_book_status() -> int:
    """`lifehug.py book-status` — one line per chapter, one heading per book.

    The point isn't to be exhaustive; it's to show the manuscript at a glance
    so you know which chapter to sit with today. Exits 0 even when there are
    no book Focuses (empty message, not an error)."""
    books = compute_books()
    if not books:
        print("No book-project Focuses yet. A Focus with deliverable=book "
              "produces a chapter list; add one with `lifehug.py focus-new`.")
        return 0

    print("Lifehug — Book Assembly\n")
    for book in books:
        head = book["label"] or "(untitled)"
        tag = book["verdict"]
        # Phase 2: manuscript rollup on the header line so you see draft
        # progress alongside answer progress. Zero-draft books show "—".
        drafted = book["drafted_words"]
        target = book["manuscript_target"]
        ms = (f"{drafted:,}/{target:,} words drafted"
              if drafted else "no drafts yet")
        print(f"  📖 {head}  [{tag}]  "
              f"{book['answered_questions']}/{book['total_questions']} "
              f"across {book['chapter_count']} chapters "
              f"({book['chapters_ready']} ready)  ·  {ms}")
        if book.get("objective"):
            print(f"     {book['objective']}")
        print()
        for ch in book["chapters"]:
            bar = _bar_text(ch["saturation"])
            depth = ""
            if ch["scene_slots_total"]:
                depth = f"  · scenes {ch['scene_slot_ratio']:.0%}"
            draft_note = ""
            if ch["has_draft"]:
                draft_note = f"  · 📄 {ch['drafted_words']:,} words"
            print(f"     [{ch['category_id']}] {ch['category_name'][:28]:28}"
                  f"  {bar}  {ch['answered']:3}/{ch['total']:<3}"
                  f"  {ch['verdict']:11}{depth}{draft_note}")
        print()

    return 0


def print_book_offers(dry_run: bool = True) -> int:
    """`lifehug.py book-offers [--send]` — preview or fire chapter-ready offers.

    Preview mode (default) never touches Telegram and never marks anything as
    offered. `--send` actually fires and persists so the same chapter isn't
    announced twice. Prints a single-line status per chapter so the CLI is
    scannable at a glance.
    """
    rows = send_ready_offers(dry_run=dry_run)
    if not rows:
        print("No new chapter-ready offers.")
        return 0
    header = "Preview (nothing sent):" if dry_run else "Offers fired:"
    print(header)
    for row in rows:
        state = "sent ✓" if row.get("sent") else ("[preview]" if dry_run else "send failed")
        print(f"  {state}  {row['book_label']} → [{row['chapter_id']}] {row['chapter_name']}")
    return 0


def print_book_chapter(book_id: str, chapter_ref: str) -> int:
    """`lifehug.py book-chapter <book> <chapter>` — the depth view.

    Lists the next unanswered gap questions so the author knows exactly what
    to sit down and record to move the chapter from DEVELOPING to READY."""
    hit = find_chapter(book_id, chapter_ref)
    if not hit:
        print(f"No chapter matching book={book_id!r} chapter={chapter_ref!r}",
              file=sys.stderr)
        return 1
    book, ch = hit
    print(f"📖 {book['label']}  →  Chapter [{ch['category_id']}] {ch['category_name']}\n")
    bar = _bar_text(ch["saturation"])
    print(f"  {bar}  {ch['answered']}/{ch['total']} answered "
          f"({ch['saturation']:.0%})  [{ch['verdict']} — {ch['verdict_label']}]")
    if ch["scene_slots_total"]:
        print(f"  Scene depth (McAdams 5-slot): "
              f"{ch['scene_slots_filled']}/{ch['scene_slots_total']} slots filled "
              f"across {ch['answered']} answers ({ch['scene_slot_ratio']:.0%})")
    if ch.get("manuscript_hook"):
        print(f"  Synthesis so far: {ch['manuscript_hook']}")
    if ch["gap_questions"]:
        print("\n  Top gap questions to move this chapter forward:")
        for gap in ch["gap_questions"]:
            print(f"    - [{gap['id']}] {gap['text']}")
    elif ch["ready_to_draft"]:
        print("\n  This chapter is ready to draft.")
        print(f"    python3 system/lifehug.py artifact new --format chapter "
              f"--subject \"{ch['category_name']}\" "
              f"--categories {ch['category_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(print_book_status())
