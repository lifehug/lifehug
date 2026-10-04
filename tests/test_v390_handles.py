"""v390 (ADR 0043, "Handles") — `@katie` is the record, typeable in any conversation.

lifehug-platform `docs/design/identity.md` §3.1 / §4.1.4b / D9, promise P14.
Every fixture is SYNTHETIC: invented people, an invented state and cities, two
names for one pair of shorts. Nothing is copied from any real vault.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import entity_roster  # noqa: E402
import entity_verdict  # noqa: E402
import general_listener as gl  # noqa: E402
import identity_handles as ih  # noqa: E402
import identity_resolution as ir  # noqa: E402
import jobs  # noqa: E402
import landmark_recorder as lr  # noqa: E402
import person_resolution as pr  # noqa: E402
from test_v389_compile_by_record import mara_vault  # noqa: E402


def row(name, slug, **extra):
    base = {"name": name, "slug": slug, "aliases": [], "qualifies": True, "score": 0.0,
            "unique_answers": 0, "page_eligible": False}
    base.update(extra)
    return base


def rosters() -> dict:
    return {
        "person": {"version": 1, "type": "person", "entities": [
            row("Mara Quill", "mara-quill", relationship="spouse", aliases=["Mara"]),
            row("Walter Pell", "walter-pell", relationship="parent", aliases=["Dad"]),
            row("Otto Lane Pell", "otto-lane-pell", relationship="child"),
        ]},
        "place": {"version": 1, "type": "place", "entities": [
            row("California", "california", place_kind="region", aliases=["CA"]),
            row("Yucaipa", "yucaipa", place_kind="city"),
            row("Orchard Cove", "orchard-cove", place_kind="city"),
        ]},
        "object": {"version": 1, "type": "object", "entities": [
            row("Orange Shorts", "orange-shorts"),
            row("One pair of clothes", "one-pair-of-clothes"),
            # Shares its slug with the place above: a token naming two types.
            row("Yucaipa trophy", "yucaipa"),
        ]},
        "theme": {"version": 1, "type": "theme", "entities": [
            row("Summers at the lake", "summers-at-the-lake"),
        ]},
        "period": {"version": 1, "type": "period", "entities": [
            row("The lake years", "the-lake-years"),
        ]},
    }


def disk(case: unittest.TestCase, data: dict) -> Path:
    tmp = Path(case.enterContext(tempfile.TemporaryDirectory()))
    patcher = mock.patch.object(entity_roster, "ENTITY_DIR", tmp)
    patcher.start()
    case.addCleanup(patcher.stop)
    for kind, roster in data.items():
        (tmp / f"{kind}.json").write_text(json.dumps(roster), encoding="utf-8")
    return tmp


def run_verdict(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = entity_verdict.main(argv[1:])  # argv[0] is the verb name
    return code, out.getvalue(), err.getvalue()


def load(kind: str) -> dict:
    return entity_roster.load_roster(kind)


def by_slug(roster: dict, slug: str) -> dict:
    return next(r for r in roster["entities"] if r["slug"] == slug)


# --------------------------------------------------------------------------
# the grammar
# --------------------------------------------------------------------------


class GrammarTable(unittest.TestCase):

    CASES = [
        ("this is @mara-quill", ["@mara-quill"]),
        ("@mara-quill is here", ["@mara-quill"]),
        ("Ask @mara-quill.", ["@mara-quill"]),                 # sentence end
        ("(@mara-quill) said so", ["@mara-quill"]),
        ("@mara-quill's house", ["@mara-quill"]),             # possessive
        ("with @a1 and @b-2, then @c", ["@a1", "@b-2", "@c"]),
        ("“@mara-quill”", ["@mara-quill"]),
        ("@Mara-Quill", ["@Mara-Quill"]),                     # case-insensitive token
        # excluded: inside an email, a URL, a host, or not a handle at all
        ("write me@example.com", []),
        ("https://example.com/@mara-quill", []),
        ("see example.com/@mara", []),
        ("@mara.example.com", []),
        ("a@b", []),
        ("@", []),
        ("@-bad", []),
        ("@@mara", []),
        ("price @ 5pm", []),
    ]

    def test_the_grammar_table(self):
        for text, expected in self.CASES:
            with self.subTest(text=text):
                self.assertEqual([s.raw for s in ir.parse_handles(text)], expected)

    def test_a_span_points_at_the_token(self):
        text = "Yes, this is @mara-quill."
        span = ir.parse_handles(text)[0]
        self.assertEqual(text[span.span[0]:span.span[1]], "@mara-quill")
        self.assertEqual((span.ref, span.reason), (None, "unresolved"))

    def test_length_is_bounded_to_64_characters(self):
        ok = "a" * 64
        self.assertEqual(len(ir.parse_handles(f"@{ok}")), 1)
        self.assertEqual(ir.parse_handles(f"@{'a' * 65}"), [])

    def test_handle_re_is_exported_and_shared(self):
        self.assertIs(ir.HANDLE_RE, ih.HANDLE_RE)
        self.assertIs(pr.HANDLE_RE, ih.HANDLE_RE)


class Resolution(unittest.TestCase):

    def test_slug_resolution_goes_person_first_across_all_types(self):
        spans = ir.parse_handles("@mara-quill @orange-shorts @summers-at-the-lake "
                                 "@the-lake-years @nobody", rosters())
        self.assertEqual([s.ref for s in spans],
                         ["person/mara-quill", "object/orange-shorts",
                          "theme/summers-at-the-lake", "period/the-lake-years", None])
        self.assertEqual(spans[-1].reason, "unknown_handle")

    def test_a_token_matching_two_types_is_ambiguous_and_names_both(self):
        span = ir.parse_handles("@yucaipa", rosters())[0]
        self.assertIsNone(span.ref)
        self.assertEqual(span.reason, "ambiguous_handle")
        self.assertEqual(set(span.candidates), {"place/yucaipa", "object/yucaipa"})

    def test_a_short_handle_on_any_type_wins_over_a_slug(self):
        data = rosters()
        by_slug(data["place"], "orchard-cove")["aliases"] = ["cove"]
        by_slug(data["place"], "orchard-cove")["alias_meta"] = {
            "cove": {"handle": True, "exclusive": True}}
        found = ir.resolve_handle("cove", data)
        self.assertEqual((found.kind, found.ref, found.reason),
                         ("resolved", "place/orchard-cove", "handle_alias"))
        # An alias that is NOT flagged a handle is not one.
        self.assertEqual(ir.resolve_handle("ca", data).kind, "unknown")

    def test_a_fold_pointer_never_answers(self):
        data = rosters()
        data["person"]["entities"].append(row("Mari", "mari", folded_into="mara-quill"))
        self.assertEqual(ir.resolve_handle("mari", data).kind, "unknown")

    def test_person_resolution_delegates_to_the_one_grammar(self):
        data = rosters()
        by_slug(data["person"], "mara-quill")["aliases"] = ["Mara", "mq"]
        by_slug(data["person"], "mara-quill")["alias_meta"] = {"mq": {"handle": True}}
        self.assertEqual(pr.parse_handles("this is @MQ, and @mara-quill"), ("mq", "mara-quill"))
        found = pr.resolve_handle("@mq", data["person"])
        self.assertEqual((found.kind, found.ref, found.basis), ("resolved", "person/mara-quill", "handle"))
        # A handle that names a place is not a person.
        self.assertEqual(pr.resolve_handle("california", data["person"]).reason, "unknown_handle")


# --------------------------------------------------------------------------
# P14 — statements by handle
# --------------------------------------------------------------------------


class HandleStatements(unittest.TestCase):

    def test_handle_statements_by_name(self):
        """The three shapes, each resolved with no model call."""
        data = rosters()
        # (a) "this is @h" — the subject comes from the host.
        alias = ih.handle_statements("This is @mara-quill.", data, subject="Mara Ann Voss")
        self.assertEqual([(s.kind, s.resolution, s.basis) for s in alias],
                         [("alias", "resolved", "handle")])
        self.assertEqual(list(alias[0].argv), ["entity-verdict", "person", "mara-quill",
                                               "clear", "--alias", "Mara Ann Voss"])
        # (a') "X is @h" — the subject is in the sentence.
        said = ih.handle_statements("Kit is @mara-quill, my wife.", data)
        self.assertEqual(list(said[0].argv)[-2:], ["--alias", "Kit"])
        # The determiner is not part of the name; a pointer before it is the subject.
        said = ih.handle_statements("I told her this is @mara-quill", data, subject="Mar")
        self.assertEqual(list(said[0].argv)[-2:], ["--alias", "Mar"])
        # (b) "same as @h": an object that is already a record folds INTO it.
        fold = ih.handle_statements("These are the same as @orange-shorts.", data,
                                    subject_ref="object/one-pair-of-clothes")
        self.assertEqual((fold[0].kind, fold[0].resolution), ("fold", "resolved"))
        self.assertEqual(list(fold[0].argv), ["entity-verdict", "object", "one-pair-of-clothes",
                                              "clear", "--fold-into", "orange-shorts"])
        named = ih.handle_statements("The one pair of clothes is the same as @orange-shorts", data)
        self.assertEqual(list(named[0].argv)[:3], ["entity-verdict", "object", "one-pair-of-clothes"])
        # ... a name that is not yet a record becomes an alias; a person only ever aliases.
        spelling = ih.handle_statements("The tangerine ones are the same as @orange-shorts", data)
        self.assertEqual((spelling[0].kind, list(spelling[0].argv)[-2:]),
                         ("alias", ["--alias", "tangerine ones"]))
        person = ih.handle_statements("Rosie is the same person as @mara-quill", data)
        self.assertEqual((person[0].kind, person[0].type), ("alias", "person"))
        # (c) "@a is in @b" — containment, places only.
        place = ih.handle_statements("@orchard-cove is in @california.", data)
        self.assertEqual((place[0].kind, place[0].resolution), ("located_in", "resolved"))
        self.assertEqual(list(place[0].argv), ["entity-verdict", "place", "orchard-cove",
                                               "clear", "--located-in", "california"])
        wrong = ih.handle_statements("@orange-shorts is in @california", data)
        self.assertEqual((wrong[0].resolution, wrong[0].reason),
                         ("unsupported", "containment_needs_two_places"))
        self.assertEqual(wrong[0].argv, ())

    def test_an_unknown_handle_files_nothing(self):
        data = rosters()
        for text in ("this is @nobody", "same as @nobody", "@nobody is in @california",
                     "@orchard-cove is in @nowhere"):
            with self.subTest(text=text):
                found = ih.handle_statements(text, data, subject="Zed")
                self.assertEqual(found[0].resolution, "unknown_handle")
                self.assertEqual(found[0].reason, "unknown_handle")
                self.assertEqual(found[0].argv, ())
                self.assertEqual(ih.statement_invocations(found), [])

    def test_a_cross_type_token_is_ambiguous_naming_both_and_files_nothing(self):
        found = ih.handle_statements("this is @yucaipa", rosters(), subject="Yuca")
        self.assertEqual(found[0].resolution, "ambiguous")
        self.assertEqual(set(found[0].candidates), {"place/yucaipa", "object/yucaipa"})
        self.assertEqual(ih.statement_invocations(found), [])

    def test_no_subject_and_role_words_file_nothing(self):
        data = rosters()
        no_subject = ih.handle_statements("this is @mara-quill", data)
        self.assertEqual((no_subject[0].resolution, no_subject[0].reason),
                         ("unknown_subject", "no_subject"))
        role = ih.handle_statements("My wife is @mara-quill", data)
        self.assertEqual(role[0].reason, "role_word_is_not_a_name")
        self.assertEqual(role[0].argv, ())
        # Periods nest and are the Eras program's: nothing is filed from here.
        period = ih.handle_statements("Summer is @the-lake-years", data)
        self.assertEqual(period[0].reason, "handle_type_unsupported")

    def test_a_name_somebody_else_holds_is_a_collision_never_a_re_point(self):
        data = rosters()
        by_slug(data["person"], "walter-pell")["aliases"].append("Wally")
        found = ih.handle_statements("Wally is @mara-quill", data)
        self.assertEqual(found[0].resolution, "ambiguous")
        self.assertEqual(found[0].candidates, ("person/mara-quill", "person/walter-pell"))
        self.assertEqual(found[0].argv, ())

    def test_a_name_the_record_already_answers_to_is_a_noop(self):
        found = ih.handle_statements("Mara is @mara-quill", rosters())
        self.assertEqual((found[0].resolution, found[0].reason), ("noop", "already_known"))
        self.assertEqual(found[0].argv, ())

    def test_a_shared_first_name_is_never_already_known(self):
        """The I-1 guard: 'Mara Ann Voss' shares 'Mara' with a record; that is
        not a restatement, it is the lesson."""
        found = ih.handle_statements("Mara Ann Voss is @mara-quill", rosters())
        self.assertEqual(found[0].resolution, "resolved")
        self.assertEqual(list(found[0].argv)[-2:], ["--alias", "Mara Ann Voss"])
        # ... and the listener's restatement check agrees.
        self.assertFalse(gl._identity_term_consumed("Mara Ann Voss", rosters()["person"]))

    def test_nothing_is_ever_ensured_and_every_record_says_so(self):
        found = ih.handle_statements(
            "Kit is @mara-quill. @orchard-cove is in @california. "
            "The tangerine ones are the same as @orange-shorts.", rosters())
        self.assertEqual(len(found), 3)
        self.assertTrue(all(s.basis == "handle" for s in found))
        argvs = ih.statement_invocations(found)
        self.assertEqual(len(argvs), 3)
        self.assertTrue(all("--ensure" not in argv for argv in argvs))
        self.assertTrue(all(s.to_dict()["basis"] == "handle" for s in found))

    def test_the_statements_actually_file_through_the_one_writer(self):
        disk(self, rosters())
        statements = ih.handle_statements(
            "Kit is @mara-quill. @orchard-cove is in @california. "
            "These are the same as @orange-shorts.", rosters(),
            subject_ref="object/one-pair-of-clothes")
        for argv in ih.statement_invocations(statements):
            code, _out, err = run_verdict(argv)
            self.assertEqual(code, 0, err)
        self.assertIn("Kit", by_slug(load("person"), "mara-quill")["aliases"])
        self.assertEqual(by_slug(load("place"), "orchard-cove")["located_in"], "place/california")
        folded = by_slug(load("object"), "one-pair-of-clothes")
        self.assertEqual(ir.folded_into_of(folded), "orange-shorts")
        # A fold is a pointer, never a deletion — and the survivor keeps both names.
        self.assertIn("One pair of clothes", by_slug(load("object"), "orange-shorts")["aliases"])

    def test_the_listener_carries_the_statements_without_a_model(self):
        calls: list[str] = []

        def failing(prompt: str, model: str) -> str:
            calls.append(prompt)
            raise RuntimeError("provider down")

        data = rosters()
        outcome = lr.listen_to_answer(
            answer="This is @mara-quill. Oh, and this is @nobody.", call=failing,
            person_roster=data["person"], entity_rosters=data,
            handle_subject="Mara Ann Voss")
        self.assertEqual([s["resolution"] for s in outcome.handle_statements],
                         ["resolved", "unknown_handle"])
        self.assertEqual(gl.handle_statement_invocations(outcome.handle_statements),
                         [["entity-verdict", "person", "mara-quill", "clear",
                           "--alias", "Mara Ann Voss"]])
        self.assertTrue(all(s["basis"] == "handle" for s in outcome.handle_statements))

    def test_a_message_with_no_handle_adds_nothing(self):
        outcome = lr.listen_to_answer(answer="Nothing to hear here.", call=lambda p, m: "{}")
        self.assertEqual(outcome.handle_statements, ())


# --------------------------------------------------------------------------
# setting, refusing and clearing a handle
# --------------------------------------------------------------------------


class SettingHandles(unittest.TestCase):

    def setUp(self):
        self.tmp = disk(self, rosters())

    def snapshot(self) -> dict:
        return {p.name: p.read_bytes() for p in sorted(self.tmp.glob("*.json"))}

    def test_a_handle_is_unique_across_types_and_nothing_is_written_on_refusal(self):
        code, out, _err = run_verdict(["ev", "person", "mara-quill", "clear", "--handle", "mq"])
        self.assertEqual(code, 0)
        mara = by_slug(load("person"), "mara-quill")
        view = ir.record_view(mara, load("person"))
        self.assertEqual((view["handle"], view["short_handle"]), ("@mara-quill", "@mq"))
        self.assertEqual(view["display_name"], "Mara Quill")
        before = self.snapshot()
        refusals = {
            "yucaipa": "slug of a place (and an object)",
            "california": "name of a place",
            "ca": "alias of a place",
            "orange-shorts": "slug of an object",
            "walter-pell": "slug of another person",
            "dad": "alias of another person",
            "summers-at-the-lake": "slug of a theme",
            "the-lake-years": "slug of a period",
            "mq": "handle another record holds",
        }
        for handle, why in refusals.items():
            with self.subTest(handle=handle, why=why):
                target = ("person", "otto-lane-pell")
                code, out, _err = run_verdict(["ev", *target, "clear", "--handle", handle])
                self.assertEqual(code, entity_verdict.EXIT_IDENTITY_UNCERTAIN)
                refusal = json.loads(out)
                self.assertEqual(refusal["reason"], "identity_uncertain")
                self.assertTrue(refusal["handle"])
                self.assertGreaterEqual(len(refusal["candidates"]), 2)  # the claimant is named
                self.assertEqual(self.snapshot(), before)

    def test_the_claimant_is_named(self):
        code, out, _err = run_verdict(["ev", "object", "orange-shorts", "clear", "--handle", "yucaipa"])
        self.assertEqual(code, entity_verdict.EXIT_IDENTITY_UNCERTAIN)
        named = {c["ref"] for c in json.loads(out)["claimed_as"]}
        self.assertEqual(named, {"place/yucaipa", "object/yucaipa"})

    def test_a_record_may_hold_its_own_name_as_its_handle(self):
        code, _out, err = run_verdict(["ev", "person", "mara-quill", "clear", "--handle", "mara"])
        self.assertEqual(code, 0, err)

    def test_the_charset_is_refused_with_no_write(self):
        before = self.snapshot()
        for bad in ("two words", "-lead", "trail-", "bang!", "a" * 65, "", "@", "é"):
            with self.subTest(handle=bad):
                code, _out, err = run_verdict(["ev", "person", "mara-quill", "clear", f"--handle={bad}"])
                self.assertEqual(code, 1)
                self.assertIn("invalid handle", err)
                self.assertEqual(self.snapshot(), before)
        # An @ and capitals are normalised, not refused.
        code, _out, _err = run_verdict(["ev", "person", "mara-quill", "clear", "--handle", "@MQ"])
        self.assertEqual(code, 0)
        self.assertEqual(ir.handle_of(by_slug(load("person"), "mara-quill")), "mq")

    def test_a_new_handle_replaces_the_old_one(self):
        run_verdict(["ev", "person", "mara-quill", "clear", "--handle", "mq"])
        run_verdict(["ev", "person", "mara-quill", "clear", "--handle", "marie"])
        mara = by_slug(load("person"), "mara-quill")
        self.assertEqual(ir.handle_of(mara), "marie")
        self.assertEqual(ir.resolve_handle("mq", {"person": load("person")}).kind, "unknown")
        self.assertEqual(ir.resolve_handle("marie", {"person": load("person")}).ref,
                         "person/mara-quill")

    def test_clear_handle(self):
        run_verdict(["ev", "person", "mara-quill", "clear", "--handle", "mq"])
        code, out, err = run_verdict(["ev", "person", "mara-quill", "clear", "--clear-handle"])
        self.assertEqual(code, 0, err)
        self.assertIn("handle: @mara-quill", out)
        mara = by_slug(load("person"), "mara-quill")
        view = ir.record_view(mara, load("person"))
        self.assertEqual((view["handle"], view["short_handle"]), ("@mara-quill", ""))
        self.assertEqual(ir.handle_of(mara), "")
        # The slug handle still resolves; the cleared one does not; the name it was is kept.
        rost = {"person": load("person")}
        self.assertEqual(ir.resolve_handle("mara-quill", rost).ref, "person/mara-quill")
        self.assertEqual(ir.resolve_handle("mq", rost).kind, "unknown")
        self.assertIn("mq", mara["aliases"])
        # Cleared handles are free again for anybody.
        # (The alias string "mq" stays on Mara as a name, so it is not free to
        # become another record's handle: a name is held until it is retracted.)
        code, _out, _err = run_verdict(["ev", "person", "otto-lane-pell", "clear", "--handle", "mq"])
        self.assertEqual(code, entity_verdict.EXIT_IDENTITY_UNCERTAIN)
        # Clearing nothing is a clean no-op, and the two flags are different acts.
        self.assertEqual(run_verdict(["ev", "person", "walter-pell", "clear", "--clear-handle"])[0], 0)
        with self.assertRaises(entity_verdict.EntityVerdictError):
            entity_verdict.apply_verdict("person", "walter-pell", "clear",
                                         handle="wally", clear_handle=True)

    def test_the_job_payload_speaks_clear_handle(self):
        self.assertIn("--clear-handle", jobs_args({"clear_handle": True}))
        self.assertNotIn("--clear-handle", jobs_args({}))
        with self.assertRaises(ValueError):
            jobs_args({"clear_handle": True, "handle": "x"})
        with self.assertRaises(ValueError):
            jobs_args({"clear_handle": False})


def jobs_args(extra: dict) -> tuple[str, ...]:
    (invocation,) = jobs._build_entity_verdict(
        {"type": "person", "slug": "mara-quill", "verdict": "clear", **extra})
    return invocation.arguments


# --------------------------------------------------------------------------
# display
# --------------------------------------------------------------------------


class Display(unittest.TestCase):

    def test_the_people_block_carries_handles(self):
        data = rosters()["person"]
        by_slug(data, "mara-quill")["aliases"] = ["Mara", "mq"]
        by_slug(data, "mara-quill")["alias_meta"] = {"mq": {"handle": True, "exclusive": True}}
        block = pr.render_known_people(data)
        lines = block.splitlines()
        self.assertTrue(lines[0].startswith("- Mara Quill @mq"))        # short handle wins
        self.assertTrue(any(l.startswith("- Walter Pell @walter-pell") for l in lines))
        # The listener's prompt shows the same block.
        prompt = gl.build_listener_prompt(answer="x", person_roster=data)
        self.assertIn("- Mara Quill @mq", prompt)
        self.assertIn("@handle", prompt)

    def test_the_viewer_header_shows_the_handle_beside_the_name(self):
        vault = mara_vault(self)
        roster = vault.root / "state/entity_rosters/person.json"
        data = json.loads(roster.read_text())
        mara = data["entities"][0]
        mara["aliases"].append("mq")
        mara["alias_meta"] = {"mq": {"handle": True, "exclusive": True}}
        roster.write_text(json.dumps(data))
        vault.compile()
        text = vault.page("people/mara-quill.md")
        self.assertIn('short_handle: "@mq"', text)
        header = vault.serve(f"print(sw.identity_header_html({text!r}))")
        self.assertIn("Mara Quill", header)
        self.assertIn("@mara-quill @mq", header)
        # The display name is unchanged: the handle is a separate field.
        view = ir.record_view(mara, {"entities": data["entities"]})
        self.assertEqual(view["display_name"], "Mara Quill")


if __name__ == "__main__":
    unittest.main()
