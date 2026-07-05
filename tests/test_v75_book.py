"""Tests for v75 book assembly (system/book.py).

Covers the compute path (chapter readiness math, five-slot depth aggregation,
book-project filtering) and the CLI entry points at a smoke level, using the
real repository state so the test doubles as a live sanity check for Dave.
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SYSTEM = _REPO / "system"
if str(_SYSTEM) not in sys.path:
    sys.path.insert(0, str(_SYSTEM))

import book  # noqa: E402


def test_compute_books_returns_only_book_deliverables():
    """Focuses whose deliverable is a letter/tweet/etc. must NOT surface here.

    A book map contaminated with letter Focuses stops being a manuscript view.
    """
    books = book.compute_books()
    for b in books:
        assert str(b["deliverable"]).lower() in book.BOOK_DELIVERABLES, (
            f"non-book Focus leaked into book map: {b['label']} ({b['deliverable']})"
        )


def test_compute_books_primary_focus_leads():
    """The author's own life story is the primary Focus and must sort first.

    If a project Focus (e.g. Etherfuse) ever leads the book list, the primary
    weighting from v36 has regressed.
    """
    books = book.compute_books()
    if len(books) < 2:
        return  # nothing to compare
    # If any book is primary, it must be the first one.
    if any(b.get("primary") for b in books):
        assert books[0].get("primary"), "primary book must sort first"


def test_chapter_saturation_and_verdict_bounds():
    """Saturation stays in [0, 1] and verdicts come from the fixed vocabulary."""
    valid_verdicts = {"EARLY", "DEVELOPING", "READY", "SATURATED"}
    for b in book.compute_books():
        for ch in b["chapters"]:
            assert 0.0 <= ch["saturation"] <= 1.0
            assert 0.0 <= ch["scene_slot_ratio"] <= 1.0
            assert ch["verdict"] in valid_verdicts


def test_ready_flag_matches_verdict():
    """ready_to_draft is derived; it must equal verdict in {READY,SATURATED}."""
    for b in book.compute_books():
        for ch in b["chapters"]:
            expected = ch["verdict"] in ("READY", "SATURATED")
            assert ch["ready_to_draft"] is expected


def test_gap_questions_are_unanswered_and_capped():
    """Gap questions are the priority-ranked UNANSWERED tail (capped 5)."""
    for b in book.compute_books():
        for ch in b["chapters"]:
            assert len(ch["gap_questions"]) <= 5
            # Every listed gap must NOT have been an answered question.
            answered_short = ch["answered"]
            total = ch["total"]
            unanswered_available = total - answered_short
            # A gap list longer than the unanswered pool would be a bug.
            assert len(ch["gap_questions"]) <= max(unanswered_available, 0)


def test_five_slot_depth_bounded_by_answers():
    """scene_slots_total == answers * len(FIVE_SLOTS) (no double-counting)."""
    expected_per_answer = len(book.FIVE_SLOTS)
    for b in book.compute_books():
        for ch in b["chapters"]:
            assert ch["scene_slots_total"] == ch["answered"] * expected_per_answer
            assert 0 <= ch["scene_slots_filled"] <= ch["scene_slots_total"]


def test_find_chapter_by_category_id_and_slug():
    """Look-up must accept both the raw category letter ('A') and the slug."""
    books = book.compute_books()
    if not books:
        return
    b = books[0]
    if not b["chapters"]:
        return
    ch = b["chapters"][0]
    by_id = book.find_chapter(str(b["id"]), ch["category_id"])
    by_slug = book.find_chapter(str(b["id"]), ch["slug"])
    assert by_id is not None
    assert by_slug is not None
    assert by_id[1]["category_id"] == ch["category_id"]
    assert by_slug[1]["category_id"] == ch["category_id"]


def test_print_book_status_smoke():
    """CLI entry point must run and emit the book banner (or empty message)."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = book.print_book_status()
    assert rc == 0
    out = buf.getvalue()
    # Either a banner (real repo) or the empty explanation (fresh install).
    assert "Book Assembly" in out or "No book-project Focuses yet." in out


def test_print_book_chapter_bad_ref_returns_1():
    """A missing book/chapter combo must report failure without crashing."""
    rc = book.print_book_chapter("does-not-exist", "Z")
    assert rc == 1


# ---- v76 phase 2 additions ------------------------------------------------


def test_book_carries_manuscript_rollup():
    """Phase 2: every book has drafted_words/manuscript_target/ratio fields."""
    for b in book.compute_books():
        assert "drafted_words" in b
        assert "manuscript_target" in b
        assert "manuscript_ratio" in b
        assert b["drafted_words"] >= 0
        assert b["manuscript_target"] >= 0
        assert 0.0 <= b["manuscript_ratio"] <= 100.0  # ratio can exceed 1 if drafts go long


def test_chapter_carries_draft_fields():
    """Phase 2: every chapter has drafts/has_draft/drafted_words fields."""
    for b in book.compute_books():
        for ch in b["chapters"]:
            assert "drafts" in ch and isinstance(ch["drafts"], list)
            assert "has_draft" in ch
            assert "drafted_words" in ch
            # If a chapter has drafts, has_draft must be True.
            assert ch["has_draft"] is bool(ch["drafts"])
            # Drafted words never negative.
            assert ch["drafted_words"] >= 0
            # Total drafted words match the sum of individual drafts.
            assert ch["drafted_words"] == sum(d.get("words", 0) for d in ch["drafts"])


def test_gap_question_ids_returns_priorities_for_near_ready():
    """gap_question_ids surfaces top gaps from chapters near READY only.

    Chapters below NEARLY_READY_MIN mustn't leak in; chapters at/above READY
    mustn't leak in either (they don't need the boost).
    """
    ids = book.gap_question_ids(max_per_chapter=2)
    # Every id must belong to a near-ready but not-yet-ready chapter.
    for b in book.compute_books():
        for ch in b["chapters"]:
            chapter_qids = {g["id"] for g in ch["gap_questions"]}
            for qid in chapter_qids & set(ids):
                assert not ch["ready_to_draft"], \
                    f"already-ready chapter leaked into gap boost: {qid}"
                assert ch["saturation"] >= book.NEARLY_READY_MIN, \
                    f"far-from-ready chapter leaked into gap boost: {qid}"


def test_send_ready_offers_dry_run_never_marks():
    """dry_run=True must never write to state/book_offers.json."""
    before = book._load_offers_state()["offered"].copy()
    book.send_ready_offers(dry_run=True)
    after = book._load_offers_state()["offered"]
    assert before == after, "dry_run must not mutate offer state"


def test_newly_ready_excludes_already_offered_and_drafted():
    """A chapter that's been offered OR has a draft doesn't surface again."""
    # Two independent exclusions; every chapter that IS returned must satisfy
    # both "ready_to_draft" AND "no draft yet" AND "never offered".
    for b, ch in book.newly_ready_chapters():
        assert ch["ready_to_draft"]
        assert not ch["has_draft"], \
            f"drafted chapter re-offered: {b['label']} [{ch['category_id']}]"
        assert not book.already_offered(str(b.get("id", "")), ch["category_id"]), \
            f"already-offered chapter re-offered: {b['label']} [{ch['category_id']}]"


def test_format_chapter_offer_contains_command():
    """The offer message includes the exact artifact command."""
    fake_book = {"id": "my-life", "label": "David James Taylor"}
    fake_chapter = {
        "category_id": "A", "category_name": "Origins",
        "saturation": 0.72, "answered": 33, "total": 46,
    }
    msg = book.format_chapter_offer(fake_book, fake_chapter)
    assert "chapter" in msg.lower()
    assert "lifehug.py artifact new" in msg
    assert "--format chapter" in msg
    assert "--categories A" in msg
    assert "Origins" in msg


def test_offer_key_and_marking_roundtrip():
    """Mark an offer, confirm the guard says it's been offered, then restore.

    Redirects book.BOOK_OFFERS_FILE to a temp file so the real state stays
    clean, restores it in a try/finally so a failure here can't stick a
    fictional offer into Dave's live state.
    """
    import tempfile
    from pathlib import Path as _P
    original = book.BOOK_OFFERS_FILE
    with tempfile.TemporaryDirectory() as tmp:
        book.BOOK_OFFERS_FILE = _P(tmp) / "book_offers.json"
        try:
            assert not book.already_offered("my-life", "Z")
            book._mark_offered("my-life", "Z")
            assert book.already_offered("my-life", "Z")
        finally:
            book.BOOK_OFFERS_FILE = original


if __name__ == "__main__":
    # Manual smoke run: python3 tests/test_v75_book.py
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)


def test_five_slots_match_classifier_schema_contract():
    """book.FIVE_SLOTS must name the exact keys the classifier emits — a
    mismatch silently reads as empty slots forever (the v76 audit found
    when_where/meaning_for_self drift). Pin against the prompt schema."""
    import book
    prompt_src = (_REPO / "system" / "classify_story.py").read_text(encoding="utf-8")
    for slot in book.FIVE_SLOTS:
        assert f'"{slot}"' in prompt_src, f"book slot {slot!r} not in classifier schema"
