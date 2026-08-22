"""Tests for the entity-identity-context contract (v190).

Play graduates an entity in the background and opens the conversation that
establishes WHO or WHAT it is (platform ADR 0020 + review-loop/57; ADR 0022
amended). The properties these tests pin, layer by layer:

  - `entity_candidate` — the pure Play-path surface: the type-aware opener,
    the transcript-derived stage, the duplicate list (which reuses the
    ROSTER's own matchers and adds none), offer-worthiness, the closed
    validator for the additive `entity_setup` field, and the seven
    `entity_setup_gates.*` lints.
  - `conversation_delivery` — the structural layer of `entity_setup`: absent
    or malformed always degrades to None, and the appendix is byte-identical
    when no caller asks for the field.
  - `entity_verdict` — graduation AND identity in ONE idempotent call, plus
    the `--maps-to` precedence rule.
  - `entity_roster` — the identity facts survive a refresh, exactly as
    `keywords` and `owner_verdict` already do.
  - `recommend_focuses` — the one entity -> focus hand-off seam, which
    appends a row and creates no Focus.

Everything here is synthetic — a throwaway roster/state per test, never the
founder vault (AGENTS.md's boundary rule).
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

from tempdirs import root_parent_tmp  # noqa: E402

import conversation_delivery  # noqa: E402
import entity_candidate  # noqa: E402
import entity_roster  # noqa: E402
import entity_verdict  # noqa: E402
import focus_candidate  # noqa: E402
import jobs  # noqa: E402
import lifehug  # noqa: E402
import recommend_focuses  # noqa: E402

ASIDE = (
    "I've added **Synthetic Ada** as a person in your story — tell me if "
    "that's the wrong name or the wrong person."
)


# ---------------------------------------------------------------------------
# The pure Play-path surface (Design §A.4, §C)
# ---------------------------------------------------------------------------


class OpeningQuestionTests(unittest.TestCase):
    def test_opening_question_is_type_aware_and_one_line(self):
        for entity_type in entity_roster.ENTITY_TYPES:
            with self.subTest(entity_type=entity_type):
                line = entity_candidate.opening_question("Synthetic Ada", entity_type)
                self.assertIn("Synthetic Ada", line)
                self.assertEqual(line.count("?"), 1)
                self.assertNotIn("\n", line)
        self.assertEqual(
            entity_candidate.opening_question("Synthetic Ada", "person"),
            "Tell me about Synthetic Ada — who are they to you?",
        )

    def test_unknown_or_blank_type_falls_back_to_the_generic_line(self):
        for entity_type in (None, "", "spaceship"):
            with self.subTest(entity_type=entity_type):
                self.assertEqual(
                    entity_candidate.opening_question("Synthetic Ada", entity_type),
                    "Tell me about Synthetic Ada — what should I know about it?",
                )

    def test_a_blank_name_is_a_caller_bug_not_a_degradation(self):
        for name in ("", "   ", None):
            with self.subTest(name=name):
                with self.assertRaises(entity_candidate.EntityCandidateError):
                    entity_candidate.opening_question(name, "person")


class EntityStageTests(unittest.TestCase):
    def test_stage_is_derived_from_the_transcript_alone(self):
        self.assertEqual(
            entity_candidate.entity_stage_for_session({"turns": []}), "establish"
        )
        self.assertEqual(
            entity_candidate.entity_stage_for_session(
                {"turns": [{"role": "user", "text": "hi"}]}
            ),
            "establish",
        )
        self.assertEqual(
            entity_candidate.entity_stage_for_session(
                {"turns": [{"role": "user"}, {"role": "lifehug"}]}
            ),
            "settled",
        )

    def test_a_missing_turns_key_is_establish_not_an_error(self):
        self.assertEqual(entity_candidate.entity_stage_for_session({}), "establish")

    def test_stage_matches_the_focus_lane_twin(self):
        # Recurring-defect doctrine: the two lanes derive the same stage the
        # same way. A divergence here means someone forked the derivation.
        for session in (
            {"turns": []},
            {"turns": [{"role": "user"}]},
            {"turns": [{"role": "lifehug"}]},
        ):
            with self.subTest(session=session):
                self.assertEqual(
                    entity_candidate.entity_stage_for_session(session),
                    focus_candidate.focus_stage_for_session(session),
                )


def _roster(*entities: dict) -> dict:
    return {"version": 1, "type": "person", "entities": list(entities)}


def _entry(name: str, **extra: object) -> dict:
    entry = {
        "name": name,
        "slug": entity_roster.slugify(name),
        "aliases": [],
        "qualifies": True,
        "maps_to_focus": None,
        "score": 1.0,
        "unique_answers": 1,
        "page_eligible": False,
    }
    entry.update(extra)
    return entry


class PossibleDuplicatesTests(unittest.TestCase):
    def test_alias_match_is_found_through_the_rosters_own_keys(self):
        roster = _roster(
            _entry("Synthetic Jim Reynolds", aliases=["Synthetic Jim"]),
            _entry("Synthetic Harbor"),
        )
        self.assertEqual(
            entity_candidate.possible_duplicates("person", "Synthetic Jim", roster),
            ["Synthetic Jim Reynolds"],
        )

    def test_near_name_token_subset_is_found_through_focus_dupes(self):
        roster = _roster(_entry("Synthetic Jim Reynolds"), _entry("Synthetic Harbor"))
        self.assertEqual(
            entity_candidate.possible_duplicates("person", "Synthetic Jim", roster),
            ["Synthetic Jim Reynolds"],
        )

    def test_the_subject_own_row_and_never_vetoed_rows_are_excluded(self):
        roster = _roster(
            _entry("Synthetic Jim"),
            _entry("Synthetic Jim Reynolds", owner_verdict="never"),
        )
        self.assertEqual(
            entity_candidate.possible_duplicates("person", "Synthetic Jim", roster), []
        )

    def test_an_unrelated_roster_yields_nothing(self):
        roster = _roster(_entry("Synthetic Harbor"), _entry("Synthetic Cabin"))
        self.assertEqual(
            entity_candidate.possible_duplicates("person", "Synthetic Ada", roster), []
        )

    def test_blank_name_and_empty_roster_are_empty_not_errors(self):
        self.assertEqual(entity_candidate.possible_duplicates("person", "", _roster()), [])
        self.assertEqual(entity_candidate.possible_duplicates("person", "Ada", {}), [])
        self.assertEqual(
            entity_candidate.possible_duplicates("person", "Ada", {"entities": None}), []
        )

    def test_the_list_is_capped_so_the_leaf_stays_bounded(self):
        roster = _roster(
            *[
                _entry(f"Synthetic Jim {index}", aliases=["Synthetic Jim"])
                for index in range(entity_candidate.MAX_POSSIBLE_DUPLICATES + 3)
            ]
        )
        self.assertEqual(
            len(entity_candidate.possible_duplicates("person", "Synthetic Jim", roster)),
            entity_candidate.MAX_POSSIBLE_DUPLICATES,
        )

    def test_it_delegates_to_the_rosters_matcher_rather_than_owning_one(self):
        # The recurring-defect pin: patch the ROSTER's key function and the
        # result changes. A second, private matcher inside entity_candidate
        # would make this test pass with the wrong answer.
        roster = _roster(_entry("Synthetic Harbor"))
        original = entity_roster._entity_keys  # noqa: SLF001
        entity_roster._entity_keys = lambda entry: {"same"}  # noqa: SLF001
        try:
            self.assertEqual(
                entity_candidate.possible_duplicates("person", "Synthetic Ada", roster),
                ["Synthetic Harbor"],
            )
        finally:
            entity_roster._entity_keys = original  # noqa: SLF001


class OfferWorthyTests(unittest.TestCase):
    def test_offer_worthy_types_are_the_focus_recommendation_types(self):
        # Owner ruling 4's list, read from the ONE module that can express a
        # recommendation of a given type rather than re-typed.
        worthy = {
            entity_type
            for entity_type in entity_roster.ENTITY_TYPES
            if entity_candidate.is_offer_worthy(entity_type, {})
        }
        self.assertEqual(worthy, set(recommend_focuses.FOCUS_RECOMMENDATION_TYPES))
        self.assertEqual(worthy, {"person", "place", "period", "theme"})
        self.assertFalse(entity_candidate.is_offer_worthy("object", {}))

    def test_a_vetoed_or_already_mapped_entity_is_not_offer_worthy(self):
        self.assertFalse(
            entity_candidate.is_offer_worthy("person", {"owner_verdict": "never"})
        )
        self.assertFalse(
            entity_candidate.is_offer_worthy("person", {"maps_to_focus": "katie"})
        )
        self.assertTrue(entity_candidate.is_offer_worthy("person", {"maps_to_focus": None}))

    def test_a_missing_entry_is_offer_worthy_on_type_alone(self):
        self.assertTrue(entity_candidate.is_offer_worthy("person"))
        self.assertTrue(entity_candidate.is_offer_worthy("person", None))


# ---------------------------------------------------------------------------
# validate_entity_setup — the closed layer (Design §B.2)
# ---------------------------------------------------------------------------


class ValidateEntitySetupTests(unittest.TestCase):
    def test_a_full_valid_object_round_trips(self):
        value = {
            "aliases": ["Jo", "Ada Mae"],
            "relationship": "parent",
            "living": False,
            "type": "person",
            "maps_to": "synthetic-jim-reynolds",
            "start_focus": True,
        }
        self.assertEqual(
            entity_candidate.validate_entity_setup(
                value, roster_slugs=["synthetic-jim-reynolds"]
            ),
            value,
        )

    def test_unknown_type_and_relationship_are_dropped_exactly(self):
        for value, expected in (
            ({"type": "spaceship", "living": True}, {"living": True}),
            ({"type": "Person", "living": True}, {"living": True}),
            ({"relationship": "grandmother-in-law"}, None),
            ({"relationship": "Parent"}, None),
            ({"relationship": "parent"}, {"relationship": "parent"}),
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    entity_candidate.validate_entity_setup(value), expected
                )

    def test_maps_to_must_exist_in_the_callers_roster(self):
        self.assertIsNone(
            entity_candidate.validate_entity_setup({"maps_to": "who-dis"}, roster_slugs=[])
        )
        self.assertEqual(
            entity_candidate.validate_entity_setup(
                {"maps_to": " known "}, roster_slugs=["known"]
            ),
            {"maps_to": "known"},
        )

    def test_living_and_start_focus_must_be_real_bools(self):
        for value in ({"living": 1}, {"living": "yes"}, {"start_focus": 1},
                      {"start_focus": "true"}, {"living": None}):
            with self.subTest(value=value):
                self.assertIsNone(entity_candidate.validate_entity_setup(value))

    def test_aliases_are_trimmed_deduped_and_capped(self):
        value = {
            "aliases": ["  Jo  ", "jo", "", 7, "Jo Ann", "x" * 200],
        }
        self.assertEqual(
            entity_candidate.validate_entity_setup(value),
            {"aliases": ["Jo", "Jo Ann"]},
        )
        many = {"aliases": [f"Name {i}" for i in range(50)]}
        self.assertEqual(
            len(entity_candidate.validate_entity_setup(many)["aliases"]),
            entity_candidate.MAX_ENTITY_ALIASES,
        )
        self.assertIsNone(entity_candidate.validate_entity_setup({"aliases": []}))
        self.assertIsNone(entity_candidate.validate_entity_setup({"aliases": "Jo"}))

    def test_an_invalid_key_drops_only_itself(self):
        self.assertEqual(
            entity_candidate.validate_entity_setup(
                {"aliases": ["Jo"], "type": "spaceship"}
            ),
            {"aliases": ["Jo"]},
        )

    def test_non_objects_and_unknown_keys_degrade_to_none(self):
        for value in (None, "Jo", [], 7, {}, {"nickname": "Jo"},
                      {"aliases": ["Jo"], "nickname": "Jo"}):
            with self.subTest(value=value):
                self.assertIsNone(entity_candidate.validate_entity_setup(value))

    def test_entity_setup_keys_match_the_structural_layer(self):
        # The two key sets are deliberately duplicated (importing across the
        # delivery engine would cycle); this is the pin that keeps them equal.
        self.assertEqual(
            entity_candidate.ENTITY_SETUP_KEYS,
            conversation_delivery._ENTITY_SETUP_KEYS,  # noqa: SLF001
        )

    def test_relationships_are_the_focus_lanes_list_not_a_second_copy(self):
        for relationship in focus_candidate.FOCUS_RELATIONSHIPS:
            with self.subTest(relationship=relationship):
                self.assertEqual(
                    entity_candidate.validate_entity_setup(
                        {"relationship": relationship}
                    ),
                    {"relationship": relationship},
                )


# ---------------------------------------------------------------------------
# The lints (Design §D)
# ---------------------------------------------------------------------------


class EntitySetupLintTests(unittest.TestCase):
    def _ids(self, text: str, **kwargs) -> set[str]:
        kwargs.setdefault("stage", "establish")
        return {
            finding["lint"]
            for finding in entity_candidate.lint_entity_setup_reply(text, **kwargs)
        }

    def test_aside_single_sentence(self):
        good = f"That mill ran her life. {ASIDE} Is she your mother?"
        self.assertNotIn("entity_setup.aside_single_sentence", self._ids(good))
        self.assertIn(
            "entity_setup.aside_single_sentence",
            self._ids("That mill ran her life. Is she your mother?"),
        )
        self.assertIn(
            "entity_setup.aside_single_sentence", self._ids(f"{ASIDE} {ASIDE}")
        )

    def test_aside_not_a_question(self):
        asked = (
            "I've added **Synthetic Ada** as a person in your story — is that "
            "the wrong name or the wrong person?"
        )
        self.assertIn("entity_setup.aside_not_a_question", self._ids(asked))
        self.assertNotIn("entity_setup.aside_not_a_question", self._ids(ASIDE))

    def test_aside_never_repeated_on_a_settled_turn(self):
        self.assertIn(
            "entity_setup.aside_never_repeated", self._ids(ASIDE, stage="settled")
        )
        self.assertNotIn(
            "entity_setup.aside_never_repeated",
            self._ids("What did she come home smelling like?", stage="settled"),
        )

    def test_one_identity_question(self):
        self.assertNotIn(
            "entity_setup.one_identity_question",
            self._ids(f"{ASIDE} Is she your mother?"),
        )
        self.assertIn(
            "entity_setup.one_identity_question",
            self._ids(f"{ASIDE} Is she your mother? Is she living?"),
        )

    def test_settled_silence_only_when_the_user_did_not_signal(self):
        text = "Is this the same as the page you already have?"
        self.assertIn(
            "entity_setup.settled_silence", self._ids(text, stage="settled")
        )
        self.assertNotIn(
            "entity_setup.settled_silence",
            self._ids(text, stage="settled", user_signaled=True),
        )
        self.assertNotIn(
            "entity_setup.settled_silence",
            self._ids("Tell me about the mill.", stage="settled"),
        )

    def test_offer_at_most_once(self):
        offer = "If she's someone you want to build out, say so and I'll start a focus."
        self.assertIn(
            "entity_setup.offer_at_most_once",
            self._ids(f"{ASIDE} {offer}", offered_before=True),
        )
        self.assertNotIn(
            "entity_setup.offer_at_most_once",
            self._ids(f"{ASIDE} {offer}", offered_before=False),
        )

    def test_recording_a_yes_is_not_a_second_offer(self):
        # The lint locates the OFFER shape (a conditional), not every mention
        # of a focus — otherwise receiving a yes would be unlintable.
        self.assertNotIn(
            "entity_setup.offer_at_most_once",
            self._ids("Jo, then — that's how she'd have wanted it.",
                      stage="settled", offered_before=True, user_signaled=True),
        )

    def test_no_mechanism_talk(self):
        for text in (
            f"{ASIDE} I'll create a page for her.",
            f"{ASIDE} She'll get a wiki page shortly.",
            f"{ASIDE} I've started a focus on her.",
            f"{ASIDE} The system will take it from here.",
        ):
            with self.subTest(text=text):
                self.assertIn("entity_setup.no_mechanism_talk", self._ids(text))
        self.assertNotIn("entity_setup.no_mechanism_talk", self._ids(ASIDE))

    def test_graduation_is_not_a_mechanism_phrase(self):
        # "when did you graduate?" is an ordinary life-story question; making
        # it a lint would be a false positive the conversation pays for.
        self.assertNotIn(
            "entity_setup.no_mechanism_talk",
            self._ids("When did she graduate?", stage="settled"),
        )

    def test_an_unknown_stage_fails_toward_the_strictest_rule(self):
        self.assertIn(
            "entity_setup.aside_never_repeated", self._ids(ASIDE, stage="whatever")
        )

    def test_findings_share_the_inherited_lint_shape(self):
        findings = entity_candidate.lint_entity_setup_reply(
            "Nothing here.", stage="establish"
        )
        self.assertTrue(findings)
        for finding in findings:
            self.assertEqual(set(finding), {"lint", "detail", "span"})
            self.assertIsInstance(finding["detail"], str)
            self.assertEqual(len(finding["span"]), 2)

    def test_a_clean_establish_reply_produces_no_findings(self):
        self.assertEqual(
            self._ids(f"That mill ran her life. {ASIDE} Is she your mother?"), set()
        )


# ---------------------------------------------------------------------------
# The leaf and the standalone research prompt (Design §A.2, §A.3)
# ---------------------------------------------------------------------------


class LeafAndPromptTests(unittest.TestCase):
    def test_leaf_is_stage_keyed_and_placeholder_bearing(self):
        leaf = (
            ROOT / "interactions/entity_candidate/prompt/turn-instructions.md"
        ).read_text(encoding="utf-8")
        for placeholder in (
            "{entity_stage}", "{entity_name}", "{entity_type}", "{possible_duplicates}"
        ):
            self.assertIn(placeholder, leaf)
        for stage in sorted(entity_candidate.VALID_ENTITY_STAGES):
            self.assertIn(f"`{stage}`", leaf)
        self.assertIn("entity_setup", leaf)
        self.assertIn("in your story", leaf)
        self.assertIn("start a focus", leaf)
        # The research output object no longer lives in the leaf (§A.3).
        self.assertNotIn("evidence_spans", leaf)
        self.assertNotIn("dimension_evidence", leaf)

    def test_research_output_contract_survives_the_leaf_move(self):
        block = entity_candidate._research_output_contract_block()  # noqa: SLF001
        for key in (
            "reply", "action", "next_gap", "evidence_spans", "dimension_evidence",
            "seed_questions", "confirmation_span",
        ):
            self.assertIn(f'"{key}"', block)
        for dimension in entity_candidate.ENTITY_DIMENSIONS:
            self.assertIn(dimension, block)

    def test_readme_no_longer_claims_play_is_read_only(self):
        readme = (
            ROOT / "interactions/entity_candidate/README.md"
        ).read_text(encoding="utf-8")
        self.assertNotIn("Play is read-only", readme)
        self.assertIn("Play graduates", readme)


# ---------------------------------------------------------------------------
# conversation_delivery — the structural layer (Design §B.1)
# ---------------------------------------------------------------------------


def _shape(**kwargs) -> conversation_delivery.TurnShape:
    defaults = {
        "position": "middle",
        "question_allowed": True,
        "user_turns": 1,
        "target_exchanges": 4,
    }
    return conversation_delivery.TurnShape(**{**defaults, **kwargs})


class EntitySetupStructuralTests(unittest.TestCase):
    def _raw(self, **extra) -> str:
        return json.dumps({"message": "A plain reply.", **extra})

    def test_output_contract_block_byte_identical_without_entity_stage(self):
        for question_allowed in (True, False):
            with self.subTest(question_allowed=question_allowed):
                shape = _shape(question_allowed=question_allowed)
                self.assertIsNone(shape.entity_stage)
                block = conversation_delivery._output_contract_block(shape)  # noqa: SLF001
                self.assertNotIn("entity_setup", block)

    def test_entity_setup_line_and_note_present_when_staged(self):
        for stage in sorted(entity_candidate.VALID_ENTITY_STAGES):
            with self.subTest(stage=stage):
                block = conversation_delivery._output_contract_block(  # noqa: SLF001
                    _shape(entity_stage=stage)
                )
                self.assertIn('"entity_setup": {"aliases"', block)
                self.assertIn('"entity_setup" is null on every turn except one', block)

    def test_all_three_additive_fields_coexist_in_a_stable_order(self):
        block = conversation_delivery._output_contract_block(  # noqa: SLF001
            _shape(placement_stage="assert", focus_stage="establish",
                   entity_stage="establish")
        )
        self.assertLess(block.index('"placement"'), block.index('"focus_setup"'))
        self.assertLess(block.index('"focus_setup"'), block.index('"entity_setup"'))
        self.assertLess(block.index('"entity_setup"'), block.index('"rolling_summary"'))

    def test_entity_setup_absent_is_none(self):
        self.assertIsNone(
            conversation_delivery.parse_turn_output(self._raw())["entity_setup"]
        )
        self.assertIsNone(
            conversation_delivery.parse_turn_output(self._raw(entity_setup=None))[
                "entity_setup"
            ]
        )

    def test_entity_setup_malformed_degrades_never_raises(self):
        for value in (
            "Jo", [], 7, {}, {"nickname": "Jo"}, {"relationship": "   "},
            {"relationship": "x" * 501}, {"living": 1}, {"start_focus": "yes"},
            {"aliases": "Jo"}, {"aliases": [""]}, {"aliases": [7]},
        ):
            with self.subTest(value=value):
                self.assertIsNone(
                    conversation_delivery.parse_turn_output(
                        self._raw(entity_setup=value)
                    )["entity_setup"]
                )

    def test_entity_setup_partial_object_survives(self):
        parsed = conversation_delivery.parse_turn_output(
            self._raw(entity_setup={"start_focus": True})
        )
        self.assertEqual(parsed["entity_setup"], {"start_focus": True})

    def test_entity_setup_trims_and_drops_only_the_bad_key(self):
        parsed = conversation_delivery.parse_turn_output(
            self._raw(entity_setup={"relationship": "  parent  ", "living": "no"})
        )
        self.assertEqual(parsed["entity_setup"], {"relationship": "parent"})

    def test_the_structural_layer_owns_no_vocabulary(self):
        # An off-vocabulary relationship survives the structural layer and is
        # the CLOSED layer's job to reject — the same split placement and
        # focus_setup use.
        parsed = conversation_delivery.parse_turn_output(
            self._raw(entity_setup={"relationship": "grandmother-in-law"})
        )
        self.assertEqual(parsed["entity_setup"], {"relationship": "grandmother-in-law"})
        self.assertIsNone(entity_candidate.validate_entity_setup(parsed["entity_setup"]))

    def test_a_runaway_alias_list_is_bounded(self):
        parsed = conversation_delivery.parse_turn_output(
            self._raw(entity_setup={"aliases": [f"Name {i}" for i in range(200)]})
        )
        self.assertEqual(
            len(parsed["entity_setup"]["aliases"]),
            conversation_delivery._ENTITY_SETUP_MAX_ALIASES,  # noqa: SLF001
        )


# ---------------------------------------------------------------------------
# entity-verdict: graduation AND identity in one call (Design §E)
# ---------------------------------------------------------------------------


class EntityVerdictIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-entity-identity-")
        self._saved_dir = entity_roster.ENTITY_DIR
        entity_roster.ENTITY_DIR = self.tmp / "state" / "entity_rosters"
        entity_verdict.roster_file = entity_roster.roster_file
        self._saved_focus_map = entity_verdict._focus_map  # noqa: SLF001
        entity_verdict._focus_map = lambda: {"katie": "Katie"}  # noqa: SLF001

    def tearDown(self):
        entity_roster.ENTITY_DIR = self._saved_dir
        entity_verdict._focus_map = self._saved_focus_map  # noqa: SLF001

    def _seed(self, *entities: dict) -> None:
        entity_roster.write_roster("person", list(entities))

    def _on_disk(self, slug: str) -> dict:
        return next(
            entity
            for entity in entity_roster.load_roster("person")["entities"]
            if entity["slug"] == slug
        )

    def test_a_three_argument_call_is_unchanged(self):
        self._seed(_entry("Synthetic Ada"))
        entity = entity_verdict.apply_verdict("person", "synthetic-ada", "graduate")
        self.assertEqual(entity["owner_verdict"], "graduate")
        self.assertTrue(entity["page_eligible"])
        self.assertNotIn("relationship", entity)
        self.assertNotIn("living", entity)

    def test_aliases_union_dedupe_and_never_shadow_the_canonical_name(self):
        self._seed(_entry("Synthetic Ada", aliases=["Ada Mae"]))
        entity_verdict.apply_verdict(
            "person", "synthetic-ada", "graduate",
            aliases=["  Jo  ", "ada mae", "Synthetic Ada", "Jo"],
        )
        self.assertEqual(self._on_disk("synthetic-ada")["aliases"], ["Ada Mae", "Jo"])

    def test_relationship_and_living_are_stored_on_the_entry(self):
        self._seed(_entry("Synthetic Ada"))
        entity_verdict.apply_verdict(
            "person", "synthetic-ada", "graduate",
            relationship="parent", living=False,
        )
        entity = self._on_disk("synthetic-ada")
        self.assertEqual(entity["relationship"], "parent")
        self.assertIs(entity["living"], False)

    def test_an_off_vocabulary_relationship_is_refused_before_any_write(self):
        self._seed(_entry("Synthetic Ada"))
        before = entity_roster.roster_file("person").read_bytes()
        with self.assertRaises(entity_verdict.EntityVerdictError):
            entity_verdict.apply_verdict(
                "person", "synthetic-ada", "graduate", relationship="grandmother-in-law"
            )
        self.assertEqual(entity_roster.roster_file("person").read_bytes(), before)

    def test_a_non_bool_living_is_refused(self):
        self._seed(_entry("Synthetic Ada"))
        with self.assertRaises(entity_verdict.EntityVerdictError):
            entity_verdict.apply_verdict(
                "person", "synthetic-ada", "graduate", living="yes"
            )

    def test_too_many_or_too_long_aliases_are_refused(self):
        self._seed(_entry("Synthetic Ada"))
        with self.assertRaises(entity_verdict.EntityVerdictError):
            entity_verdict.apply_verdict(
                "person", "synthetic-ada", "graduate",
                aliases=[f"Name {i}" for i in range(entity_candidate.MAX_ENTITY_ALIASES + 1)],
            )
        with self.assertRaises(entity_verdict.EntityVerdictError):
            entity_verdict.apply_verdict(
                "person", "synthetic-ada", "graduate", aliases=["x" * 200]
            )

    def test_maps_to_an_entity_folds_the_loser_into_the_survivor(self):
        self._seed(
            _entry("Synthetic Jim", aliases=["Jimmy"]),
            _entry("Synthetic Jim Reynolds"),
        )
        entity = entity_verdict.apply_verdict(
            "person", "synthetic-jim", "graduate", maps_to="synthetic-jim-reynolds"
        )
        self.assertEqual(entity["maps_to_focus"], "synthetic-jim-reynolds")
        self.assertFalse(entity["page_eligible"])
        # maps-to WINS: the graduation is skipped, not recorded.
        self.assertNotIn("owner_verdict", entity)
        survivor = self._on_disk("synthetic-jim-reynolds")
        self.assertIn("Synthetic Jim", survivor["aliases"])
        self.assertIn("Jimmy", survivor["aliases"])

    def test_maps_to_a_focus_slug_is_accepted(self):
        self._seed(_entry("Synthetic Wife"))
        entity = entity_verdict.apply_verdict(
            "person", "synthetic-wife", "clear", maps_to="katie"
        )
        self.assertEqual(entity["maps_to_focus"], "katie")
        self.assertFalse(entity["page_eligible"])

    def test_an_unknown_or_self_maps_to_is_refused_with_the_roster_untouched(self):
        self._seed(_entry("Synthetic Jim"))
        before = entity_roster.roster_file("person").read_bytes()
        for target in ("who-dis", "synthetic-jim", ""):
            with self.subTest(target=target):
                with self.assertRaises(entity_verdict.EntityVerdictError):
                    entity_verdict.apply_verdict(
                        "person", "synthetic-jim", "graduate", maps_to=target
                    )
        self.assertEqual(entity_roster.roster_file("person").read_bytes(), before)

    def test_graduate_on_a_mapped_entity_still_raises_without_maps_to(self):
        # The pre-v190 refusal is untouched: only an explicit --maps-to in the
        # same call opts into the "maps-to wins" precedence.
        self._seed(_entry("Synthetic Wife", maps_to_focus="katie"))
        with self.assertRaises(entity_verdict.EntityVerdictError):
            entity_verdict.apply_verdict("person", "synthetic-wife", "graduate")

    def test_maps_to_still_carries_the_identity_facts(self):
        self._seed(_entry("Synthetic Jim"), _entry("Synthetic Jim Reynolds"))
        entity = entity_verdict.apply_verdict(
            "person", "synthetic-jim", "graduate",
            aliases=["Jimmy"], relationship="friend", living=True,
            maps_to="synthetic-jim-reynolds",
        )
        self.assertEqual(entity["relationship"], "friend")
        self.assertIs(entity["living"], True)
        self.assertEqual(entity["maps_to_focus"], "synthetic-jim-reynolds")

    def test_never_still_applies_alongside_a_mapping(self):
        self._seed(_entry("Synthetic Jim"), _entry("Synthetic Jim Reynolds"))
        entity = entity_verdict.apply_verdict(
            "person", "synthetic-jim", "never", maps_to="synthetic-jim-reynolds"
        )
        self.assertEqual(entity["owner_verdict"], "never")
        self.assertFalse(entity["page_eligible"])

    def test_the_whole_call_is_idempotent(self):
        self._seed(_entry("Synthetic Ada"))
        kwargs = {"aliases": ["Jo"], "relationship": "parent", "living": False}
        entity_verdict.apply_verdict("person", "synthetic-ada", "graduate", **kwargs)
        first = entity_roster.roster_file("person").read_bytes()
        entity_verdict.apply_verdict("person", "synthetic-ada", "graduate", **kwargs)
        self.assertEqual(entity_roster.roster_file("person").read_bytes(), first)

    def test_cli_applies_identity_and_reports_the_maps_to_precedence(self):
        self._seed(_entry("Synthetic Jim"), _entry("Synthetic Jim Reynolds"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = entity_verdict.main([
                "person", "synthetic-jim", "graduate",
                "--alias", "Jimmy", "--relationship", "friend", "--not-living",
                "--maps-to", "synthetic-jim-reynolds",
            ])
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("mapped to synthetic-jim-reynolds", text)
        self.assertIn("graduate superseded by --maps-to", text)
        self.assertIn("relationship: friend", text)
        self.assertIn("living: no", text)

    def test_cli_json_output_carries_the_record(self):
        self._seed(_entry("Synthetic Ada"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = entity_verdict.main([
                "person", "synthetic-ada", "graduate", "--alias", "Jo", "--json",
            ])
        self.assertEqual(code, 0)
        record = json.loads(out.getvalue())
        self.assertEqual(record["aliases"], ["Jo"])
        self.assertEqual(record["owner_verdict"], "graduate")


class VerdictWrapperAndQueueTests(unittest.TestCase):
    def test_wrapper_threads_every_identity_flag(self):
        parser = lifehug.build_parser()
        args = parser.parse_args([
            "entity-verdict", "person", "ada", "graduate",
            "--alias", "Jo", "--alias", "Ada Mae",
            "--relationship", "parent", "--not-living",
            "--maps-to", "jim-reynolds",
        ])
        self.assertEqual(args.alias, ["Jo", "Ada Mae"])
        self.assertEqual(args.relationship, "parent")
        self.assertIs(args.living, False)
        self.assertEqual(args.maps_to, "jim-reynolds")

    def test_living_and_not_living_are_mutually_exclusive(self):
        parser = lifehug.build_parser()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            parser.parse_args([
                "entity-verdict", "person", "ada", "graduate", "--living", "--not-living",
            ])

    def test_queue_builder_shapes_the_identity_argv(self):
        invocations = jobs._build_entity_verdict({  # noqa: SLF001
            "type": "person", "slug": "ada", "verdict": "graduate",
            "aliases": ["Jo"], "relationship": "parent", "living": False,
            "maps_to": "jim-reynolds",
        })
        self.assertEqual(
            invocations[0].arguments,
            ("entity-verdict", "person", "ada", "graduate", "--alias", "Jo",
             "--relationship", "parent", "--not-living", "--maps-to", "jim-reynolds"),
        )

    def test_queue_builder_still_accepts_the_pre_v190_payload(self):
        invocations = jobs._build_entity_verdict(  # noqa: SLF001
            {"type": "person", "slug": "ada", "verdict": "graduate"}
        )
        self.assertEqual(
            invocations[0].arguments, ("entity-verdict", "person", "ada", "graduate")
        )

    def test_queue_builder_rejects_bad_identity_payloads(self):
        base = {"type": "person", "slug": "ada", "verdict": "graduate"}
        for bad in (
            {"aliases": "Jo"}, {"aliases": [""]}, {"aliases": [7]},
            {"aliases": ["x" * 200]}, {"living": "yes"}, {"maps_to": "not a slug!"},
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    jobs._build_entity_verdict({**base, **bad})  # noqa: SLF001


# ---------------------------------------------------------------------------
# entity_roster: the identity facts survive a refresh (Design §E)
# ---------------------------------------------------------------------------


class RosterCarryForwardTests(unittest.TestCase):
    def test_normalize_keeps_a_validated_relationship_and_living(self):
        raw = [{"name": "Ada", "aliases": [], "qualifies": True, "maps_to_focus": None,
                "relationship": "  parent  ", "living": False}]
        entry = entity_roster.normalize("person", raw, [], {}, 8.0, 2)[0]
        self.assertEqual(entry["relationship"], "parent")
        self.assertIs(entry["living"], False)

    def test_normalize_drops_shape_invalid_identity_values(self):
        raw = [{"name": "Ada", "aliases": [], "qualifies": True, "maps_to_focus": None,
                "relationship": "   ", "living": 1}]
        entry = entity_roster.normalize("person", raw, [], {}, 8.0, 2)[0]
        self.assertNotIn("relationship", entry)
        self.assertNotIn("living", entry)

    def test_previous_identity_facts_carry_onto_the_folded_slot(self):
        previous = {"entities": [
            _entry("Ada", relationship="parent", living=False),
        ]}
        raw = [{"name": "Ada", "aliases": [], "qualifies": True, "maps_to_focus": None}]
        folded, _ = entity_roster.apply_previous_decisions(raw, previous)
        self.assertEqual(folded[0]["relationship"], "parent")
        self.assertIs(folded[0]["living"], False)

    def test_a_fresh_value_wins_over_the_carried_one(self):
        previous = {"entities": [_entry("Ada", relationship="parent")]}
        raw = [{"name": "Ada", "aliases": [], "qualifies": True,
                "maps_to_focus": None, "relationship": "mentor"}]
        folded, _ = entity_roster.apply_previous_decisions(raw, previous)
        self.assertEqual(folded[0]["relationship"], "mentor")

    def test_identity_facts_survive_an_empty_refresh(self):
        previous = {"entities": [_entry("Ada", living=True)]}
        folded, forced = entity_roster.apply_previous_decisions([], previous)
        self.assertEqual([e["name"] for e in folded], ["Ada"])
        self.assertEqual(forced, 1)

    def test_identity_facts_survive_a_refresh_that_omits_the_entity(self):
        previous = {"entities": [_entry("Ada", relationship="parent")]}
        raw = [{"name": "Harbor", "aliases": [], "qualifies": True, "maps_to_focus": None}]
        folded, _ = entity_roster.apply_previous_decisions(raw, previous)
        self.assertIn("Ada", [e["name"] for e in folded])

    def test_an_entity_with_no_settled_fact_is_still_dropped(self):
        previous = {"entities": [_entry("Ada")]}
        folded, forced = entity_roster.apply_previous_decisions([], previous)
        self.assertEqual(folded, [])
        self.assertEqual(forced, 0)

    def test_the_settled_identity_predicate_is_explicit(self):
        self.assertTrue(entity_roster._has_settled_identity(  # noqa: SLF001
            {"owner_verdict": "never"}))
        self.assertTrue(entity_roster._has_settled_identity(  # noqa: SLF001
            {"relationship": "parent"}))
        self.assertTrue(entity_roster._has_settled_identity({"living": False}))  # noqa: SLF001
        self.assertFalse(entity_roster._has_settled_identity({}))  # noqa: SLF001
        # A merge's durability lives on the survivor's aliases, not here.
        self.assertFalse(entity_roster._has_settled_identity(  # noqa: SLF001
            {"maps_to_focus": "katie"}))


# ---------------------------------------------------------------------------
# The hand-off seam: one row, no focus (Design §F)
# ---------------------------------------------------------------------------


class RecommendationForEntityTests(unittest.TestCase):
    def test_the_row_carries_exactly_the_recommendation_keys(self):
        row = recommend_focuses.recommendation_for_entity(
            {"name": "Synthetic Ada", "type": "person", "score": 4.5,
             "unique_answers": 3},
            now="2026-08-22T00:00:00Z",
        )
        self.assertEqual(
            set(row), set(recommend_focuses.RECOMMENDATION_ROW_KEYS)
        )
        self.assertEqual(row["id"], "rec-synthetic-ada")
        self.assertEqual(row["status"], "pending")
        self.assertFalse(row["ready_to_start"])
        self.assertEqual(
            row["reason"], recommend_focuses.ENTITY_ONBOARDING_REASON
        )
        self.assertEqual(row["reason"], "owner asked during entity onboarding")

    def test_recommendation_row_keys_match_the_recommend_literal(self):
        # Recurring-defect doctrine: the row shape has ONE authority. This
        # reads `recommend()`'s own dict literal out of the AST, so a key
        # added to one and not the other fails the build.
        tree = ast.parse((SYSTEM / "recommend_focuses.py").read_text(encoding="utf-8"))
        function = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "recommend"
        )
        literal = next(
            node.value for node in ast.walk(function)
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "rec"
            and isinstance(node.value, ast.Dict)
        )
        keys = {key.value for key in literal.keys}
        self.assertEqual(keys, set(recommend_focuses.RECOMMENDATION_ROW_KEYS))

    def test_an_unrecommendable_type_or_a_nameless_entry_raises(self):
        with self.assertRaises(ValueError):
            recommend_focuses.recommendation_for_entity(
                {"name": "The Cone", "type": "object"}
            )
        with self.assertRaises(ValueError):
            recommend_focuses.recommendation_for_entity({"name": "", "type": "person"})
        with self.assertRaises(ValueError):
            recommend_focuses.recommendation_for_entity({"name": "Ada"})


class AppendEntityRecommendationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-entity-handoff-")
        self._saved_dir = entity_roster.ENTITY_DIR
        entity_roster.ENTITY_DIR = self.tmp / "state" / "entity_rosters"
        self.recs = self.tmp / "state" / "focus_recommendations.json"
        self.recs.parent.mkdir(parents=True, exist_ok=True)
        self._saved_recs = recommend_focuses.FOCUS_RECS_FILE
        self._saved_legacy = recommend_focuses.LEGACY_FOCUS_RECS_FILE
        recommend_focuses.FOCUS_RECS_FILE = self.recs
        recommend_focuses.LEGACY_FOCUS_RECS_FILE = self.tmp / "state" / "legacy.json"
        entity_roster.write_roster("person", [_entry("Synthetic Ada")])

    def tearDown(self):
        entity_roster.ENTITY_DIR = self._saved_dir
        recommend_focuses.FOCUS_RECS_FILE = self._saved_recs
        recommend_focuses.LEGACY_FOCUS_RECS_FILE = self._saved_legacy

    def test_it_appends_one_pending_row(self):
        result = recommend_focuses.append_entity_recommendation("person", "synthetic-ada")
        self.assertTrue(result["created"])
        stored = json.loads(self.recs.read_text(encoding="utf-8"))
        self.assertEqual(len(stored["recommendations"]), 1)
        self.assertEqual(stored["recommendations"][0]["id"], "rec-synthetic-ada")
        self.assertEqual(stored["recommendations"][0]["status"], "pending")

    def test_a_second_call_writes_nothing_at_all(self):
        recommend_focuses.append_entity_recommendation("person", "synthetic-ada")
        before = self.recs.read_bytes()
        result = recommend_focuses.append_entity_recommendation("person", "synthetic-ada")
        self.assertFalse(result["created"])
        self.assertEqual(self.recs.read_bytes(), before)

    def test_it_creates_no_focus(self):
        called: list[object] = []
        import roadmap

        saved = roadmap.focus_new
        roadmap.focus_new = lambda *a, **k: called.append((a, k))
        try:
            recommend_focuses.append_entity_recommendation("person", "synthetic-ada")
        finally:
            roadmap.focus_new = saved
        self.assertEqual(called, [])

    def test_an_unknown_type_or_slug_raises(self):
        with self.assertRaises(ValueError):
            recommend_focuses.append_entity_recommendation("alien", "synthetic-ada")
        with self.assertRaises(ValueError):
            recommend_focuses.append_entity_recommendation("person", "who-dis")


class HandOffWrapperAndQueueTests(unittest.TestCase):
    def test_the_verb_is_a_direct_mutation_command(self):
        self.assertIn("focus-recommend-from-entity", lifehug.DIRECT_MUTATION_COMMANDS)
        self.assertNotIn("focus-recommend-from-entity", lifehug.READ_ONLY_COMMANDS)

    def test_the_wrapper_parses_and_shapes_the_call(self):
        parser = lifehug.build_parser()
        args = parser.parse_args(["focus-recommend-from-entity", "person", "ada"])
        self.assertEqual((args.type, args.slug), ("person", "ada"))

    def test_it_is_a_registered_queue_command(self):
        self.assertIn("focus-recommend-from-entity", jobs.COMMANDS)
        invocations = jobs._build_focus_recommend_from_entity(  # noqa: SLF001
            {"type": "person", "slug": "ada"}
        )
        self.assertEqual(
            invocations[0].arguments, ("focus-recommend-from-entity", "person", "ada")
        )

    def test_the_queue_builder_rejects_bad_payloads(self):
        for bad in (
            {"type": "alien", "slug": "ada"},
            {"type": "person", "slug": "not a slug!"},
            {"type": "person", "slug": "ada", "extra": 1},
            {"type": "person"},
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    jobs._build_focus_recommend_from_entity(bad)  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
