"""v387 — a conversation can teach identity: the identity listener.

Identity-unification design §4.1.4 (lifehug-platform#987), decisions D3/D4,
promises P4/P5. Synthetic names only; the owner's cases appear by SHAPE.
NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import general_listener as gl
import landmark_recorder as lr
import person_resolution as pr


def _roster(*extra: dict) -> dict:
    return {"version": 1, "type": "person", "entities": [
        {"name": "Rosalind Vane", "slug": "rosalind-vane", "aliases": ["Roz"],
         "relationship": "spouse"},
        {"name": "Edwin Marsh", "slug": "edwin-marsh", "aliases": ["Dad"],
         "relationship": "parent"},
        {"name": "Pip Marsh", "slug": "pip-marsh", "relationship": "child"},
        {"name": "Wren Marsh", "slug": "wren-marsh", "relationship": "child"},
        {"name": "Tilly Hart", "slug": "tilly-hart"},
        # A placeholder role row and a fold pointer: never candidates.
        {"name": "Son", "slug": "son", "relationship": "child"},
        {"name": "Rozzy", "slug": "rozzy", "maps_to_focus": "rosalind-vane"},
        *extra,
    ]}


def _listen(answer: str, raws: list[str], roster: dict):
    seen: list[str] = []

    def call(prompt: str, model: str) -> str:
        seen.append(prompt)
        return raws[min(len(seen), len(raws)) - 1]

    return lr.listen_to_answer(answer=answer, call=call, person_roster=roster), seen


def _identity(**record) -> str:
    return json.dumps({"landmarks": [], "people": [], "claims": [],
                       "identity_assertions": [], "person_identity": [record]})


EMPTY = json.dumps({"landmarks": [], "people": [], "claims": [],
                    "identity_assertions": [], "person_identity": []})


class PrescreenTests(unittest.TestCase):
    """`may_contain_identity` — table-driven, both polarities."""

    CASES = (
        ("Rosalind Ann Quill is my wife, the Roz I talk about.", True, "name_is_relation"),
        ("My wife Roz and I drove up.", True, "relation_name"),
        ("Tilly, my sister, came too.", True, "relation_name"),
        ("Grandma Betty Lou, also known as BL, raised us.", True, "also_known_as"),
        ("Wren goes by Birdie now.", True, "also_known_as"),
        ("We called her Dot.", True, "also_known_as"),
        ("Mrs. Hart, née Quill, taught piano.", True, "also_known_as"),
        ("Tilly was my best friend.", True, "is_my"),
        ("this is @rosalind-vane", True, "handle"),
        ("Same as @edwin-marsh.", True, "handle"),
        ("@pip-marsh is the one I meant", True, "handle"),
        # Negatives — the load-bearing half.
        ("Mom was my rock.", False, None),
        ("She is my wife.", False, None),
        ("My dad took us fishing.", False, None),
        ("We went to the store on Tuesday.", False, None),
        ("I love my wife.", False, None),
        ("email me at me@example.com", False, None),
    )

    def test_the_table(self):
        for text, fires, reason in self.CASES:
            with self.subTest(text=text):
                verdict = gl.may_contain_identity(text)
                self.assertEqual(verdict.fired, fires)
                if reason:
                    self.assertIn(reason, verdict.reasons)

    def test_a_relation_word_never_reaches_a_name_in_another_clause(self):
        self.assertFalse(gl.may_contain_identity("I miss my wife. Tilly called.").fired)

    def test_the_relation_words_are_derived_not_retyped(self):
        import identity_resolution as ir
        for word in ir.RELATIONSHIP_MENTION_WORDS:
            self.assertIn(word, gl._REL_WORDS)

    def test_the_host_gate_is_datable_or_identity(self):
        self.assertTrue(gl.should_listen("Rosalind Ann Quill is my wife."))
        self.assertTrue(gl.should_listen("We moved in 1974."))
        self.assertFalse(gl.should_listen("Nice weather today."))


class IdentityListenerTests(unittest.TestCase):

    def test_identity_listener_alias(self):
        """P4: "X is my wife" with exactly one spouse files alias X on her."""
        outcome, seen = _listen(
            "Rosalind Ann Quill is my wife.",
            [_identity(name="Rosalind Ann Quill", relationship="wife",
                       evidence="Rosalind Ann Quill is my wife")], _roster())
        self.assertEqual(outcome.status, lr.STATUS_RECORDED)
        self.assertEqual(len(seen), 1)
        (record,) = outcome.person_identity
        self.assertEqual(record["resolution"], gl.IDENTITY_RESOLVED)
        self.assertEqual(record["alias_of"], "person/rosalind-vane")
        self.assertEqual(record["basis"], pr.BASIS_STATEMENT)
        self.assertEqual(gl.identity_invocations(outcome.person_identity), [[
            "entity-verdict", "person", "rosalind-vane", "clear",
            "--alias", "Rosalind Ann Quill"]])
        # ...and the known people were SHOWN to the listener.
        self.assertIn("Rosalind Vane @rosalind-vane — also: Roz · spouse", seen[0])

    def test_identity_listener_alias_contested(self):
        """P4: two known spouses ⇒ ambiguous, both claimants, nothing filed."""
        roster = _roster({"name": "Gale Stone", "slug": "gale-stone",
                          "relationship": "spouse"})
        outcome, _ = _listen(
            "Rosalind Ann Quill is my wife.",
            [_identity(name="Rosalind Ann Quill", relationship="wife")], roster)
        (record,) = outcome.person_identity
        self.assertEqual(record["resolution"], gl.IDENTITY_AMBIGUOUS)
        self.assertIsNone(record["alias_of"])
        self.assertEqual(sorted(record["candidates"]),
                         ["person/gale-stone", "person/rosalind-vane"])
        self.assertEqual(gl.identity_invocations(outcome.person_identity), [])
        self.assertEqual(gl.acknowledgement_line(record), "")

    def test_identity_listener_never_mints(self):
        """P5 / D3: a name the roster does not know mints nothing."""
        roster = _roster()
        roster["entities"] = [e for e in roster["entities"]
                              if e.get("relationship") != "parent"]
        outcome, _ = _listen(
            "Arlo Finch is my dad.",
            [_identity(name="Arlo Finch", relationship="dad")], roster)
        (record,) = outcome.person_identity
        self.assertEqual(record["resolution"], gl.UNKNOWN_PERSON)
        argvs = gl.identity_invocations(outcome.person_identity)
        self.assertEqual(argvs, [])
        self.assertTrue(all("--ensure" not in argv for argv in argvs))

    def test_a_set_valued_word_never_resolves_alone(self):
        """"my son" with two children is a question, never a pick."""
        outcome, _ = _listen(
            "Birdie is my daughter.",
            [_identity(name="Birdie", relationship="daughter")], _roster())
        (record,) = outcome.person_identity
        self.assertEqual(record["resolution"], gl.IDENTITY_AMBIGUOUS)
        self.assertEqual(gl.identity_invocations(outcome.person_identity), [])

    def test_a_named_child_resolves_and_files(self):
        outcome, _ = _listen(
            "Wren goes by Birdie now.",
            [_identity(name="Birdie", refers_to="Wren Marsh")], _roster())
        self.assertEqual(gl.identity_invocations(outcome.person_identity), [[
            "entity-verdict", "person", "wren-marsh", "clear", "--alias", "Birdie"]])

    def test_relationship_is_filed_only_when_the_record_has_none(self):
        outcome, _ = _listen(
            "Tilly Hart, my sister, also goes by Tee.",
            [_identity(name="Tee", refers_to="Tilly Hart", relationship="sister")],
            _roster())
        self.assertEqual(gl.identity_invocations(outcome.person_identity), [[
            "entity-verdict", "person", "tilly-hart", "clear", "--alias", "Tee",
            "--relationship", "sibling"]])
        outcome, _ = _listen(
            "Roz, my wife, also goes by Rozie.",
            [_identity(name="Rozie", refers_to="Roz", relationship="wife")],
            _roster())
        self.assertNotIn("--relationship",
                         gl.identity_invocations(outcome.person_identity)[0])

    def test_mention_and_relationship_that_disagree_are_ambiguous(self):
        outcome, _ = _listen(
            "Pip Marsh is my wife.",
            [_identity(name="Pippa", refers_to="Pip Marsh", relationship="wife")],
            _roster())
        (record,) = outcome.person_identity
        self.assertEqual(record["resolution"], gl.IDENTITY_AMBIGUOUS)

    def test_a_name_already_borne_by_someone_else_is_contested(self):
        outcome, _ = _listen(
            "Roz is my sister Tilly too.",
            [_identity(name="Roz", refers_to="Tilly Hart")], _roster())
        (record,) = outcome.person_identity
        self.assertEqual(record["resolution"], gl.IDENTITY_AMBIGUOUS)
        self.assertEqual(sorted(record["candidates"]),
                         ["person/rosalind-vane", "person/tilly-hart"])

    def test_the_family_only_guard_does_not_depend_on_the_leaf(self):
        """D3: a non-family relationship word drops by name, and that drop is
        a DECISION — it clears the backstop, one attempt."""
        outcome, seen = _listen(
            "Tilly was my best friend.",
            [_identity(name="Tilly", refers_to="Tilly Hart", relationship="friend")],
            _roster())
        self.assertEqual(outcome.person_identity, ())
        self.assertIn(gl.DROPPED_IDENTITY_NOT_FAMILY, outcome.findings)
        self.assertEqual(len(seen), 1)
        self.assertEqual(outcome.lint_ids, ())

    def test_the_model_may_not_emit_a_ref(self):
        record, finding = gl.validate_person_identity(
            {"name": "Roz", "alias_of": "person/rosalind-vane"},
            person_roster=_roster())
        self.assertIsNone(record)
        self.assertEqual(finding, gl.DROPPED_IDENTITY_MALFORMED)


class HandleTests(unittest.TestCase):
    """§4.1.4b: an `@handle` is an explicit reference, exact, never guessed."""

    def test_a_handle_files_on_its_record(self):
        outcome, _ = _listen(
            "Rosalind Ann Quill — this is @rosalind-vane",
            [_identity(name="Rosalind Ann Quill", refers_to="@rosalind-vane")],
            _roster())
        (record,) = outcome.person_identity
        self.assertEqual(record["basis"], pr.BASIS_HANDLE)
        self.assertEqual(record["alias_of"], "person/rosalind-vane")
        self.assertEqual(gl.identity_invocations(outcome.person_identity), [[
            "entity-verdict", "person", "rosalind-vane", "clear",
            "--alias", "Rosalind Ann Quill"]])

    def test_an_unknown_handle_is_recorded_never_guessed(self):
        outcome, _ = _listen(
            "Rosalind Ann Quill — this is @rosalind",
            [_identity(name="Rosalind Ann Quill", refers_to="@rosalind")],
            _roster())
        (record,) = outcome.person_identity
        self.assertEqual(record["resolution"], gl.UNKNOWN_HANDLE)
        self.assertEqual(record["handle"], "rosalind")
        self.assertEqual(gl.identity_invocations(outcome.person_identity), [])


class BackstopTests(unittest.TestCase):

    def test_a_name_lesson_heard_as_nothing_retries_once_then_withholds(self):
        outcome, seen = _listen("Rosalind Ann Quill is my wife.", [EMPTY, EMPTY],
                                _roster())
        self.assertEqual(outcome.status, lr.STATUS_WITHHELD)
        self.assertEqual(len(seen), 2)
        self.assertEqual(outcome.lint_ids, (gl.IDENTITY_HEARD_NOTHING_LINT,))
        self.assertIn("You recorded no `person_identity`", seen[1])

    def test_the_retry_recovers(self):
        outcome, seen = _listen(
            "Rosalind Ann Quill is my wife.",
            [EMPTY, _identity(name="Rosalind Ann Quill", relationship="wife")],
            _roster())
        self.assertEqual(outcome.status, lr.STATUS_RECORDED)
        self.assertEqual(len(seen), 2)
        self.assertEqual(len(outcome.person_identity), 1)

    def test_a_restatement_of_a_known_name_is_not_a_miss(self):
        outcome, seen = _listen("My wife Roz and I drove up.", [EMPTY], _roster())
        self.assertEqual(outcome.status, lr.STATUS_NOTHING)
        self.assertEqual(len(seen), 1)

    def test_other_facts_heard_never_withhold_for_a_missed_identity(self):
        dated = json.dumps({"landmarks": [], "people": [], "claims": [{
            "claim_type": "date", "subject_mention": "we",
            "event_kind": "move", "temporal_value": "1974",
            "evidence": "we moved in 1974"}], "identity_assertions": [],
            "person_identity": []})
        outcome, seen = _listen(
            "Arlo Finch is my dad, and we moved in 1974.", [dated, dated],
            _roster())
        self.assertEqual(outcome.status, lr.STATUS_RECORDED)
        self.assertEqual(len(seen), 2)
        self.assertEqual(outcome.lint_ids, (gl.IDENTITY_HEARD_NOTHING_LINT,))
        self.assertEqual(len(outcome.claims), 1)


class AcknowledgementTests(unittest.TestCase):
    """D4: the reply may acknowledge only a filed, resolved record."""

    def test_only_a_resolved_record_is_acknowledged(self):
        record, _ = gl.validate_person_identity(
            {"name": "Rosalind Ann Quill", "relationship": "wife"},
            person_roster=_roster())
        self.assertEqual(gl.acknowledgement_line(record),
                         "Got it — Rosalind Ann Quill is Rosalind Vane.")
        unknown, _ = gl.validate_person_identity(
            {"name": "Arlo Finch", "relationship": "uncle"}, person_roster=_roster())
        self.assertIsNone(unknown)  # uncle is not a family seat: dropped
        self.assertEqual(gl.acknowledgement_line({"resolution": "ambiguous"}), "")

    def test_the_purpose_is_its_own_name(self):
        self.assertEqual(gl.IDENTITY_RECORD_PURPOSE, "identity_record")
        self.assertNotEqual(gl.IDENTITY_RECORD_PURPOSE, gl.DATE_RECORD_PURPOSE)

    def test_the_leaf_teaches_the_fifth_list(self):
        prompt = gl.build_listener_prompt(answer="x", person_roster=_roster())
        self.assertIn('"person_identity": []', prompt)
        self.assertIn("PEOPLE YOU ALREADY KNOW", prompt)
        self.assertNotIn("{known_people}", prompt)
        self.assertNotIn("Rozzy", prompt)  # a fold pointer is not a person
        self.assertNotIn("- Son", prompt)  # a placeholder row is not a person


if __name__ == "__main__":
    unittest.main()
