"""Owner rulings, staging 2026-09-23: "recent" is a placement; a date card only
when it changes something.

The case. Needs Placing showed *"Mid-anger hug with James"* carrying the card
*"About how long before you recorded this (a week, a month, several months) did
the mid-anger hug with James happen?"*. The source was `answers/O6.md`, a
prompted answer captured 2026-07-14 to the question *"What's a **recent**
moment that was peak James…?"*. The story has no time words; the classifier
stamped ``when_hint: recent``; the resolver produced only an ESTIMATE (probable
window 2026-01..2026-07, ledger status ``unknown``) and minted the question.

Ruling 1 — *"'Recent' with a known capture date IS a placement, not a guess."*
Ruling 2 — *"A date card is minted only when narrowing would change
something… A freestanding anecdote whose placement is already inside about a
year gets NO card: 'higher fidelity can happen later on the timeline, ideally
not at all.'"*
Ruling 3 — *"A question MAY ask for higher fidelity when that would resolve
many things."*

The case itself was reproduced on a scratch clone of the owner's vault at v332
and again with this branch overlaid; the before/after card counts and the list of
every card this gate removes are in the PR body.

Synthetic data only, shaped like the owner's vault (a prompted answer with the
frontmatter `process_answer` writes, and one classification over it). NEVER
references ~/Workspace/dave.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import chronology as chrono  # noqa: E402
import classifier_claims as cc  # noqa: E402
import cross_dating as cd  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_placement as tpl  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import temporal_work_items as twi  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

NOW = "2026-09-23T12:00:00Z"

#: The case's own dates and words, so a failure reads as the case failing.
CAPTURED = "2026-07-14T10:35:18"
CAPTURE_DAY = "2026-07-14"
SIX_MONTHS_BACK = "2026-01-14"
QUESTION = (
    "What's a **recent** moment that was peak James — something he did or "
    "said that made you think 'that's exactly who this kid is'?"
)


# --------------------------------------------------------------------------
# 1. The vocabulary (owner ruling 1's table)
# --------------------------------------------------------------------------


class RecencyVocabularyTests(unittest.TestCase):
    """One table, narrowest first, and every rung the ruling names."""

    def test_the_table_is_narrowest_first(self):
        widths = []
        for name, months, days, patterns in chrono.RECENCY_RUNGS:
            self.assertTrue(patterns, f"{name} has no patterns")
            if name == chrono.RECENCY_YEAR_START_RUNG:
                continue  # calendar-anchored, not an offset — it has no width
            widths.append(months * 31 + days)
        self.assertEqual(widths, sorted(widths),
                         "RECENCY_RUNGS must be narrowest-first: the order is "
                         "what makes 'this week' beat 'this year'")

    def test_every_rung_is_named_once(self):
        names = [name for name, _m, _d, _p in chrono.RECENCY_RUNGS]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn(chrono.DEFAULT_RECENCY_RUNG, names)
        self.assertIn(chrono.RECENCY_YEAR_START_RUNG, names)
        self.assertEqual(chrono.recency_window(chrono.DEFAULT_RECENCY_RUNG),
                         (6, 0), "a bare 'recent' is the ruling's six months")

    def test_each_rung_of_the_ruling(self):
        """The ruling's own ladder, verbatim, counted back from 2026-07-14."""
        cases = [
            # (what was said, expected earliest)
            ("yesterday", "2026-06-30"),          # 2 weeks
            ("the other day", "2026-06-30"),      # 2 weeks
            ("this week", "2026-06-30"),          # 2 weeks
            ("last week", "2026-06-14"),          # 1 month
            ("last month", "2026-05-14"),         # 2 months
            ("a few weeks ago", "2026-05-14"),    # 2 months
            ("recently", SIX_MONTHS_BACK),        # 6 months
            ("lately", SIX_MONTHS_BACK),          # 6 months
            ("these days", SIX_MONTHS_BACK),      # 6 months
            ("recent", SIX_MONTHS_BACK),          # 6 months — "a recent …"
            ("a few months ago", "2025-10-14"),   # 9 months
            ("this year", "2026-01-01"),          # 1 January of the capture year
        ]
        for said, earliest in cases:
            with self.subTest(said=said):
                record = chrono.from_recency(CAPTURE_DAY, f"It happened {said}.")
                self.assertIsNotNone(record, f"{said!r} matched no rung")
                self.assertEqual(record.earliest, earliest)
                self.assertEqual(record.latest, CAPTURE_DAY,
                                 "the window always ENDS at the capture date")

    def test_the_stronger_word_narrows_deterministically(self):
        """Two cues in one telling: the tighter rung wins, every time."""
        record = chrono.from_recency(
            CAPTURE_DAY, "It was recent — yesterday, actually.")
        self.assertEqual(record.earliest, "2026-06-30")
        self.assertEqual(chrono.recency_cue("recent", "yesterday"),
                         ("immediate", "yesterday"))

    def test_basis_is_stated_and_renders_as_placed_by_you(self):
        record = chrono.from_recency(CAPTURED, "recent")
        self.assertEqual(record.basis, "stated")
        self.assertEqual(record.granularity, "range")
        self.assertEqual(twi.node_claim_basis(record), "explicit",
                         "ruling 1: it renders as 'placed by you'")
        self.assertEqual(
            chrono.display_date(record),
            "14 January 2026–14 July 2026 — you said recent, told 2026-07-14")
        self.assertNotIn(record.provenance[0]["basis"],
                         chrono.VERBATIM_PROVENANCE_BASES,
                         "a recency clause must NOT read as calculated/inferred")

    def test_no_capture_date_changes_nothing(self):
        for captured in (None, "", "not a date", "2026-13-01", "later"):
            with self.subTest(captured=captured):
                self.assertIsNone(chrono.from_recency(captured, "recently"))

    def test_no_cue_changes_nothing(self):
        for said in ("one day", "at the kitchen table", "sixth grade", ""):
            with self.subTest(said=said):
                self.assertIsNone(chrono.from_recency(CAPTURE_DAY, said))

    def test_the_year_trap_is_closed(self):
        """A text that names a year DATES ITSELF; a recency word in it is not
        the reading. `classifier_claims._age_band_text`'s own guard, reused."""
        cases = [
            "I remember it like it was yesterday: he wrote from Korea in 1952.",
            "In recent decades the town changed; we left in 1974.",
            "A recent photograph of my grandmother from 1943.",
            "This week in 1985 we drove to Mesa.",
            "Recently I found the 1997 letters.",
        ]
        for said in cases:
            with self.subTest(said=said):
                self.assertIsNone(chrono.from_recency(CAPTURE_DAY, said))

    def test_the_year_trap_is_closed_per_text_not_per_call(self):
        """A `when_hint` of "recent" still places a story that mentions a year
        somewhere else — the veto is on the text that names the year."""
        record = chrono.from_recency(
            CAPTURE_DAY, "We bought the house in 1998.", "recent")
        self.assertIsNotNone(record)
        self.assertEqual(record.earliest, SIX_MONTHS_BACK)

    def test_a_recency_word_meaning_the_opposite_is_vetoed(self):
        """English says "like it was yesterday" about a memory, not a date."""
        cases = [
            "It feels like yesterday.",
            "I remember it as though it were yesterday.",
            "In recent years the town changed.",
            "Nothing like it in recent memory.",
            "The best game in recent history.",
            "Back in those days, these days were unimaginable.",
        ]
        for said in cases:
            with self.subTest(said=said):
                self.assertIsNone(chrono.from_recency(CAPTURE_DAY, said),
                                  "RECENCY_VETO_RES must refuse this")

    def test_the_veto_table_is_checked_before_the_rungs(self):
        self.assertTrue(chrono.RECENCY_VETO_RES)
        self.assertIsNone(chrono.recency_cue("like it was yesterday"))
        self.assertEqual(chrono.recency_cue("yesterday")[0], "immediate")

    def test_earlier_this_year_never_starts_in_the_year_before(self):
        """The phrase ASSERTS the calendar year; a 9-month offset would not."""
        record = chrono.from_recency("2026-02-01", "earlier this year")
        self.assertEqual(record.earliest, "2026-01-01")
        self.assertEqual(record.latest, "2026-02-01")
        self.assertEqual(chrono.recency_cue("earlier this year")[0],
                         chrono.RECENCY_YEAR_START_RUNG)

    def test_a_short_month_is_clamped_not_an_error(self):
        record = chrono.from_recency("2026-08-31", "recently")
        self.assertEqual(record.earliest, "2026-02-28")

    def test_span_months_is_one_arithmetic(self):
        self.assertEqual(chrono.span_months(chrono.parse_edtf("1988")), 12)
        self.assertEqual(chrono.span_months(chrono.parse_edtf("1998-06")), 1)
        self.assertEqual(chrono.span_months(chrono.from_recency(CAPTURE_DAY, "recent")), 7)
        self.assertIsNone(chrono.span_months(chrono.parse_edtf("1990/..")))
        self.assertIsNone(chrono.span_months(None))


# --------------------------------------------------------------------------
# 2. A synthetic vault, shaped like the case
# --------------------------------------------------------------------------


def _vault(case: unittest.TestCase) -> Path:
    root = root_parent_tmp(case, ROOT, prefix="recency-")
    (root / "state" / "classifications").mkdir(parents=True, exist_ok=True)
    (root / "answers").mkdir(parents=True, exist_ok=True)
    return root


def _answer(root: Path, qid: str, *, body: str, question: str = QUESTION,
            captured: str | None = CAPTURED) -> str:
    """A prompted answer with the frontmatter `process_answer` writes."""
    relative = f"answers/{qid}.md"
    lines = [
        "---",
        f'title: "Question {qid}: {question}"',
        'type: "prompted_answer"',
        f'question_id: "{qid}"',
    ]
    if question:
        lines.append(f'question_text: "{question}"')
    if captured:
        lines.append(f'captured_at: "{captured}"')
        lines.append(f'answered_date: "{captured[:10]}"')
    lines += ['source_path: "%s"' % relative, "---", "", body, ""]
    (root / relative).write_text("\n".join(lines), encoding="utf-8")
    return relative


def _classification(root: Path, stem: str, source_path: str, *events: dict) -> None:
    payload = {
        "source_path": source_path,
        "source_type": "prompted_answer",
        "people": [], "places": [], "time_periods": [], "themes": [],
        "events": list(events),
    }
    (root / "state" / "classifications" / f"{stem}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")


def _event(title: str, description: str, *, when_hint: str | None = None,
           **extra: object) -> dict:
    row: dict = {
        "title": title, "description": description,
        "when_hint": when_hint, "anchor": None,
        "date": {"stated": None, "age": None, "anchor_ref": None, "relation": None},
    }
    row.update(extra)
    return row


def _run(root: Path) -> dict:
    return cc.migrate_classifier_moments(
        root, classifications_dir=root / "state" / "classifications",
        dry_run=False, publish=False, now=NOW)


def _fold(root: Path) -> tt.CalculatedTimeline:
    return tt.derive_calculated_timeline(ts.fold_active_index(root), now=NOW)


def _hug_case(case: unittest.TestCase, *, when_hint: str | None = "recent",
              question: str = QUESTION,
              captured: str | None = CAPTURED) -> tuple[Path, dict]:
    """The owner's own case: `answers/O6.md` and the mid-anger hug."""
    root = _vault(case)
    relative = _answer(
        root, "O6", question=question, captured=captured,
        body=("James was furious about the wrong cup. Then he stopped, looked "
              "at me and said: give me a hug."))
    _classification(root, "answers-o6", relative,
                    _event("Mid-anger hug with James",
                           "James asked for a hug in the middle of being "
                           "furious.", when_hint=when_hint))
    return root, _run(root)


class RecencyPlacementTests(unittest.TestCase):
    """Ruling 1, end to end over the case that produced it."""

    def test_the_case_is_placed_as_a_stated_range(self):
        root, report = _hug_case(self)
        self.assertEqual(report["claims_by_type"].get("date"), 1)
        self.assertEqual(report["claims_by_type"].get(tc.OCCURRENCE_CLAIM_TYPE), 0,
                         "the mid-anger hug is no longer an undated occurrence")
        self.assertEqual(report["dated"], 1)
        self.assertEqual(report["undated"], 0)

        nodes = [n for n in _fold(root).nodes if n.get("node_kind") == "event"]
        self.assertEqual(len(nodes), 1)
        node = nodes[0]
        best = node["best_temporal_value"]
        self.assertEqual(best["earliest"], SIX_MONTHS_BACK)
        self.assertEqual(best["latest"], CAPTURE_DAY)
        self.assertEqual(best["basis"], "stated")
        self.assertEqual(node["basis"], "explicit",
                         "ruling 1: 'placed by you', never date_derived")
        self.assertTrue(tpl.has_usable_placement(node))

    def test_the_cue_may_be_in_the_question_instead_of_the_story(self):
        """`answers/O6.md`'s own shape: no time words anywhere but the question."""
        root, report = _hug_case(self, when_hint="one day")
        self.assertEqual(report["claims_by_type"].get("date"), 1)
        node = [n for n in _fold(root).nodes if n.get("node_kind") == "event"][0]
        self.assertEqual(node["best_temporal_value"]["earliest"], SIX_MONTHS_BACK)

    def test_the_cue_may_be_in_the_story_instead_of_the_question(self):
        root, report = _hug_case(self, when_hint="last week",
                                 question="Tell me about James.")
        self.assertEqual(report["claims_by_type"].get("date"), 1)
        node = [n for n in _fold(root).nodes if n.get("node_kind") == "event"][0]
        self.assertEqual(node["best_temporal_value"]["earliest"], "2026-06-14",
                         "the story's own stronger word wins")

    def test_no_capture_date_leaves_it_exactly_as_it_was(self):
        root, report = _hug_case(self, captured=None)
        self.assertEqual(report["claims_by_type"].get(tc.OCCURRENCE_CLAIM_TYPE), 1)
        self.assertEqual(report["undated"], 1)
        node = [n for n in _fold(root).nodes if n.get("node_kind") == "event"][0]
        self.assertIsNone(node["best_temporal_value"])
        self.assertFalse(tpl.has_usable_placement(node))

    def test_no_cue_leaves_it_exactly_as_it_was(self):
        root, report = _hug_case(self, when_hint="one day",
                                 question="Tell me about James.")
        self.assertEqual(report["claims_by_type"].get(tc.OCCURRENCE_CLAIM_TYPE), 1)
        node = [n for n in _fold(root).nodes if n.get("node_kind") == "event"][0]
        self.assertIsNone(node["best_temporal_value"])

    def test_a_date_the_person_stated_still_wins(self):
        """Ruling 1 sits BELOW the three rungs the person spelled out."""
        reading = cc.temporal_reading(
            _event("x", "y", when_hint="recent",
                   date={"stated": "1998-06", "age": None,
                         "anchor_ref": None, "relation": None}),
            {"captured": CAPTURED, "question_text": QUESTION})
        self.assertEqual(reading["claim_type"], "date")
        self.assertEqual(reading["temporal_value"]["best"], "1998-06")

    def test_the_resolver_does_not_re_ask_a_placed_moment(self):
        """A node with a stated range is not pending, and mints no card."""
        root, _report = _hug_case(self)
        result = _fold(root)
        node = [n for n in result.nodes if n.get("node_kind") == "event"][0]
        self.assertEqual(
            [item for item in result.work_items
             if item.get("node_ref") == node["node_id"]
             and item.get("kind") == twi.PRECISION_GAP_KIND],
            [], "a placed moment is not a precision gap")
        self.assertNotIn(node["node_id"],
                         (result.diagnostics or {}).get("unplaced") or ())

    def test_a_stale_estimate_is_not_drawn_over_a_real_placement(self):
        """An estimate is *never a placement*, so it never rides beside one."""
        payloads = {
            pub.PROJECTION_FILE: {
                "nodes": [
                    {"node_id": "node:placed",
                     "best_temporal_value": {"earliest": SIX_MONTHS_BACK,
                                             "latest": CAPTURE_DAY,
                                             "granularity": "range",
                                             "basis": "stated"}},
                    {"node_id": "node:unplaced", "best_temporal_value": None},
                ],
                "work_items": [],
            },
        }
        estimates = {
            "node:placed": {"earliest": "2026-01", "latest": "2026-07",
                            "basis": [], "source": "resolver"},
            "node:unplaced": {"earliest": "2026-01", "latest": "2026-07",
                              "basis": [], "source": "resolver"},
        }
        pub._with_resolver_estimates(payloads, estimates)  # noqa: SLF001
        drawn = {row["node_id"]: row.get("probable_window")
                 for row in payloads[pub.PROJECTION_FILE]["nodes"]}
        self.assertIsNone(drawn["node:placed"])
        self.assertIsNotNone(drawn["node:unplaced"])

    def test_capture_context_reads_the_answer_frontmatter(self):
        root = _vault(self)
        relative = _answer(root, "O6", body="A story.")
        found = cc.capture_context(root, relative)
        self.assertEqual(found["captured"], CAPTURED)
        self.assertEqual(found["question_text"], QUESTION)

    def test_capture_context_degrades_rather_than_raising(self):
        root = _vault(self)
        self.assertEqual(cc.capture_context(root, "answers/missing.md"), {})
        (root / "answers" / "bare.md").write_text("no frontmatter", encoding="utf-8")
        self.assertEqual(cc.capture_context(root, "answers/bare.md"), {})

    def test_the_capture_key_ladder_prefers_the_most_precise(self):
        self.assertEqual(cc.CAPTURE_DATE_KEYS[0], "captured_at")
        root = _vault(self)
        (root / "answers" / "old.md").write_text(
            '---\ntitle: "A7 — anything?"\nanswered_date: "2026-04-20"\n---\n\nx\n',
            encoding="utf-8")
        found = cc.capture_context(root, "answers/old.md")
        self.assertEqual(found["captured"], "2026-04-20")
        self.assertEqual(found["question_text"], "A7 — anything?",
                         "an answer written before `question_text` existed "
                         "carries the question in its title")


# --------------------------------------------------------------------------
# 3. The stakes gate (owner ruling 2)
# --------------------------------------------------------------------------


def _card(event_kind: str = "moment", **extra: object) -> dict:
    row = {"kind": twi.PRECISION_GAP_KIND, "work_item_id": "work:deadbeef",
           "node_ref": "node:anecdote", "event_kind": event_kind}
    row.update(extra)
    return row


class StakesGateTests(unittest.TestCase):
    """*"A date card is minted only when narrowing would change something."*"""

    def test_a_freestanding_anecdote_inside_a_year_gets_no_card(self):
        self.assertFalse(twi.date_card_changes_something(_card(), window=7))
        self.assertEqual(twi.no_date_card_reason(_card(), window=7),
                         twi.NO_STAKES_INSIDE_A_YEAR)

    def test_a_window_wider_than_about_a_year_keeps_its_card(self):
        self.assertTrue(twi.date_card_changes_something(_card(), window=13))
        self.assertTrue(twi.date_card_changes_something(_card(), window=36))
        self.assertEqual(twi.PRECISION_STAKES_WINDOW_MONTHS, 12)

    def test_a_single_calendar_year_is_inside_about_a_year(self):
        self.assertFalse(twi.date_card_changes_something(_card(), window=12))

    def test_an_unplaced_moment_keeps_its_card(self):
        """No window at all is not 'inside a year'."""
        for window in (None, "", "not a number"):
            with self.subTest(window=window):
                self.assertTrue(twi.date_card_changes_something(_card(), window=window))

    def test_a_life_event_always_keeps_its_card(self):
        for kind in ("birth", "death", "married", "move", "residence", "job",
                     "school", "graduation", "military", "child_born",
                     "started", "ended"):
            with self.subTest(kind=kind):
                self.assertTrue(
                    twi.date_card_changes_something(_card(kind), window=1),
                    f"{kind} is a real life event and keeps its card")

    def test_the_life_event_vocabulary_is_the_folds_own(self):
        """Reused, never re-typed (ruling 2's own instruction)."""
        for kind in tc.EVENT_KINDS:
            self.assertIn(kind, twi.LIFE_EVENT_KINDS)
        self.assertIn("residence", twi.LIFE_EVENT_KINDS)
        self.assertNotIn(cc.MOMENT_EVENT_KIND, twi.LIFE_EVENT_KINDS,
                         "a freestanding anecdote arrives as `moment`, and "
                         "that exclusion is the whole gate")

    def test_leverage_keeps_the_card(self):
        self.assertTrue(twi.date_card_changes_something(
            _card(resolves=["node:other"]), window=7))

    def test_an_ordering_constraint_keeps_the_card(self):
        self.assertTrue(twi.date_card_changes_something(_card(), window=7, orders=True))

    def test_a_contradiction_keeps_the_card(self):
        self.assertTrue(twi.date_card_changes_something(
            _card(), window=7, contradicted=True))

    def test_a_frame_boundary_keeps_the_card(self):
        self.assertTrue(twi.date_card_changes_something(
            _card(), window=7, straddles_frame=True))

    def test_the_gate_speaks_for_one_kind_only(self):
        for kind in ("missing_anchor", "contradiction", "place_ambiguous",
                     "identity_uncertain", "residence_overlap"):
            with self.subTest(kind=kind):
                self.assertTrue(twi.date_card_changes_something(
                    _card(kind="x") | {"kind": kind}, window=1))

    def test_a_decade_edge_is_a_frame_boundary(self):
        straddle = tt._straddles_a_frame  # noqa: SLF001
        self.assertTrue(straddle(chrono.parse_edtf("1989/1990"), ()))
        self.assertFalse(straddle(chrono.parse_edtf("1991/1992"), ()))
        self.assertFalse(straddle(None, ()))

    def test_an_age_frame_edge_is_a_frame_boundary(self):
        frames = cd.age_frames("1981-07-11", as_of="2026-09-23")
        self.assertTrue(frames)
        straddle = tt._straddles_a_frame  # noqa: SLF001
        # Thirteen is the childhood/teens edge (`AGE_FRAME_FIXED_BANDS`), so an
        # interval sitting across the owner's thirteenth year touches two.
        self.assertTrue(straddle(chrono.parse_edtf("1994-01/1994-12"), frames))


class StakelessCardsAtPublicationTests(unittest.TestCase):
    """The seam where the resolver's own window is finally known."""

    def _payloads(self, *, event_kind: str = "moment",
                  window: tuple[str, str] = ("2026-01", "2026-07"),
                  **item_extra: object) -> dict:
        item = {"kind": twi.PRECISION_GAP_KIND, "work_item_id": "work:one",
                "node_ref": "node:anecdote", "event_kind": event_kind,
                "probable_window": {"earliest": window[0], "latest": window[1],
                                    "basis": [], "source": "resolver"}}
        item.update(item_extra)
        node = {"node_id": "node:anecdote", "label": "Mid-anger hug with James",
                "best_temporal_value": None, "conflict_state": "none",
                "input_constraint_refs": []}
        return {
            pub.PROJECTION_FILE: {"nodes": [node], "memberships": [],
                                  "work_items": [dict(item)],
                                  "counts": {"work_items": 1}},
            pub.WORK_ITEMS_FILE: {"work_items": [dict(item)],
                                  "counts": {"work_items": 1}},
        }

    def test_the_owners_own_card_comes_off(self):
        payloads = self._payloads()
        dropped = pub._without_stakeless_date_cards(payloads)  # noqa: SLF001
        self.assertEqual(len(dropped), 1,
                         "ONE row per card, not one per published file — "
                         "counting it twice makes `_summary` under-report")
        self.assertEqual(dropped[0]["label"], "Mid-anger hug with James")
        self.assertEqual(dropped[0]["window"], "2026-01..2026-07")
        self.assertEqual(dropped[0]["months"], 7)
        self.assertEqual(dropped[0]["reason"], twi.NO_STAKES_INSIDE_A_YEAR)
        for payload in payloads.values():
            self.assertEqual(payload["work_items"], [])
            self.assertEqual(payload["counts"]["work_items"], 0)

    def test_a_wide_window_keeps_its_card(self):
        payloads = self._payloads(window=("2019", "2021"))
        self.assertEqual(pub._without_stakeless_date_cards(payloads), [])  # noqa: SLF001
        self.assertEqual(len(payloads[pub.WORK_ITEMS_FILE]["work_items"]), 1)

    def test_a_window_wider_than_five_years_is_asked_only_when_hot(self):
        """v360 follow-up (owner, 2026-09-25)
        (`temporal_publication.A_WIDE_ESTIMATE_IS_ASKED_ONLY_WHEN_HOT`): until
        then 2019–2026 kept its card for being wide. Wider than about five
        years it is asked only when the moment is hot."""
        payloads = self._payloads(window=("2019", "2026"))
        dropped = pub._without_stakeless_date_cards(payloads)  # noqa: SLF001
        self.assertEqual([row["reason"] for row in dropped],
                         [pub.A_WIDE_ESTIMATE_IS_ASKED_ONLY_WHEN_HOT])
        hot = self._payloads(window=("2019", "2026"), resolves=["node:other"])
        self.assertEqual(pub._without_stakeless_date_cards(hot), [])  # noqa: SLF001

    def test_a_life_event_keeps_its_card(self):
        payloads = self._payloads(event_kind="married")
        self.assertEqual(pub._without_stakeless_date_cards(payloads), [])  # noqa: SLF001

    def test_leverage_keeps_its_card(self):
        payloads = self._payloads(resolves=["node:other", "node:third"])
        self.assertEqual(pub._without_stakeless_date_cards(payloads), [])  # noqa: SLF001

    def test_a_contradicted_node_keeps_its_card(self):
        payloads = self._payloads()
        for payload in payloads.values():
            for node in payload.get("nodes") or ():
                node["conflict_state"] = "contradicted"
        self.assertEqual(pub._without_stakeless_date_cards(payloads), [])  # noqa: SLF001

    def test_an_ordered_node_keeps_its_card(self):
        payloads = self._payloads()
        for node in payloads[pub.PROJECTION_FILE]["nodes"]:
            node["input_constraint_refs"] = ["constraint:one"]
        self.assertEqual(pub._without_stakeless_date_cards(payloads), [])  # noqa: SLF001

    def test_a_decade_straddling_window_keeps_its_card(self):
        payloads = self._payloads(window=("1989-06", "1990-03"))
        self.assertEqual(pub._without_stakeless_date_cards(payloads), [])  # noqa: SLF001

    def test_an_overlapping_frame_membership_keeps_its_card(self):
        payloads = self._payloads()
        payloads[pub.PROJECTION_FILE]["memberships"] = [
            {"member": "node:anecdote", "era": "age:self:teens",
             "relation": "overlaps"},
        ]
        self.assertEqual(pub._without_stakeless_date_cards(payloads), [])  # noqa: SLF001

    def test_the_summary_count_matches_the_published_file(self):
        """`_summary`'s `work_items` is `len(result.work_items) - len(dropped)`,
        so a per-payload row count would make it disagree with the file."""
        payloads = self._payloads()
        dropped = pub._without_stakeless_date_cards(payloads)  # noqa: SLF001
        published = len(payloads[pub.WORK_ITEMS_FILE]["work_items"])
        self.assertEqual(1 - len(dropped), published)

    def test_a_card_with_no_window_is_left_alone(self):
        payloads = self._payloads()
        for payload in payloads.values():
            for row in payload["work_items"]:
                row.pop("probable_window")
        self.assertEqual(pub._without_stakeless_date_cards(payloads), [])  # noqa: SLF001
        self.assertEqual(len(payloads[pub.WORK_ITEMS_FILE]["work_items"]), 1)


# --------------------------------------------------------------------------
# 4. Fidelity, and who may ask for it (owner ruling 3)
# --------------------------------------------------------------------------


class FidelityWordingTests(unittest.TestCase):
    def test_the_resolver_asks_for_the_least_fidelity_that_settles_it(self):
        import resolver  # noqa: PLC0415

        self.assertIn("least fidelity", resolver.PROMPT.lower())
        self.assertIn("also_resolves", resolver.PROMPT)
        self.assertIn("A moment that stands alone gets the plain question",
                      resolver.PROMPT)

    def test_the_folds_own_finer_targets_are_all_leverage_by_construction(self):
        """Ruling 3, as the fold already built it: every kind asking finer than
        a year is a kind other placements are read against."""
        for kind, target in tt.PRECISION_TARGETS.items():
            with self.subTest(kind=kind):
                self.assertNotEqual(target, tt.DEFAULT_PRECISION_TARGET)
                self.assertIn(kind, twi.LIFE_EVENT_KINDS)

    def test_the_coarse_sentence_names_the_fidelity_it_needs(self):
        asked = tt.compose_question("precision_gap_coarse", "married",
                                    who="you", what="the wedding",
                                    target="day", is_owner=True)
        self.assertIn("day", asked)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
