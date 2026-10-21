"""v426 (ADR 0047) — the owner is one record.

The owner, 2026-10-20: "looks like the system doesn't connect that Dave and
David James Taylor are both me." Every fixture here is SYNTHETIC — the SHAPE
of the founder vault's roster (a row named by the profile ``name`` carrying the
full name and a wrong owner-possessive alias, a placeholder ``Kids`` query,
``version, type, resolved_at, entities, source, relation_queries,
retired_rows``) with invented relatives. Nothing is read from a real vault.
"""

from __future__ import annotations

import copy
import io
import json
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import classifier_context  # noqa: E402
import cornerstones  # noqa: E402
import entity_roster  # noqa: E402
import entity_verdict  # noqa: E402
import focus_pages  # noqa: E402
import identity_resolution as ir  # noqa: E402
import lifehug_core  # noqa: E402
import owner_identity as oi  # noqa: E402
import person_resolution  # noqa: E402
import recommend_focuses  # noqa: E402
import roadmap  # noqa: E402
import roster_relations as rr  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_work_items as twi  # noqa: E402

PROFILE = {"name": "Dave", "full_name": "David James Taylor"}
NAMES = ("Dave", "David James Taylor")
CONTEXT = oi.OwnerContext(NAMES, "my-life")


def person(name, slug, *, aliases=(), **extra) -> dict:
    row = {"name": name, "slug": slug, "aliases": list(aliases), "qualifies": True,
           "focus": None, "folded_into": None, "score": 0.0, "unique_answers": 0,
           "page_eligible": False}
    row.update(extra)
    return row


def founder_shaped() -> dict:
    """The founder vault's roster SHAPE, synthetic relatives."""
    return {
        "version": 1, "type": "person", "resolved_at": "2026-10-01T05:00:00Z",
        "entities": [
            person("Dave", "dave", aliases=["David Taylor", "David James Taylor", "Dave's kids"],
                   score=31.5, unique_answers=108, page_eligible=True),
            person("Wren Taylor", "wren-taylor", aliases=["Wren"], relationship="child",
                   score=9.0, unique_answers=12, page_eligible=True),
            person("Ilse Marrow", "ilse-marrow", relationship="spouse", focus="ilse"),
        ],
        "source": "ai",
        "relation_queries": [{"word": "kids", "relationship": "child", "cardinality": None,
                              "mentions": 4, "aliases": ["the kids"], "reattributed": [],
                              "stripped_from": [], "former_rows": []}],
        "retired_rows": [],
    }


def dump(payload) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)


class _TmpRoster(unittest.TestCase):
    """A tmp roster dir and the bound owner profile/roadmap patched."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lifehug-v426-", dir=str(ROOT / "tests")))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        roadmap_file = self.tmp / "roadmap.json"
        roadmap_file.write_text(json.dumps({"version": 1, "focuses": [
            {"id": "my-life", "primary": True, "type": "life_story", "label": "David James Taylor"},
            {"id": "ilse", "type": "person", "label": "Ilse"},
        ]}), encoding="utf-8")
        for target, attr, value in (
            (entity_roster, "ENTITY_DIR", self.tmp),
            (lifehug_core, "ROADMAP_FILE", roadmap_file),
        ):
            patcher = mock.patch.object(target, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(oi, "bound_owner_profile", lambda: dict(PROFILE))
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, payload) -> Path:
        path = self.tmp / "person.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path


# --------------------------------------------------------------------------
# The one definition
# --------------------------------------------------------------------------


class OneDefinition(unittest.TestCase):

    def test_temporal_publication_reexports_the_same_functions(self):
        for name in ("owner_profile", "owner_names_from_profile", "owner_name_variants",
                     "owner_identity_inputs", "OWNER_NAME_PROFILE_KEYS"):
            with self.subTest(name=name):
                self.assertIs(getattr(pub, name), getattr(oi, name))

    def test_self_is_the_word_every_seat_already_uses(self):
        self.assertEqual(oi.SELF_RELATIONSHIP, cornerstones.SELF)
        self.assertEqual(oi.SELF_RELATIONSHIP, twi.OWNER_SUBJECT_REF)
        self.assertEqual(classifier_context.OWNER_SUBJECT_REF, twi.OWNER_SUBJECT_REF)

    def test_author_names_and_the_hub(self):
        self.assertEqual(focus_pages.author_names(PROFILE), ("Dave", "David James Taylor"))
        self.assertEqual(focus_pages.author_names({}), ("Me", "Me"))
        self.assertEqual(oi.owner_slug(PROFILE), "dave")
        self.assertEqual(oi.hub_page(PROFILE), "wiki/life/david-james-taylor.md")
        self.assertEqual(oi.primary_focus_id({"focuses": [{"id": "x"}, {"id": "my-life",
                                                                         "primary": True}]}),
                         "my-life")


class OwnerRow(unittest.TestCase):

    def test_a_self_row_is_found_first(self):
        roster = {"entities": [person("Dave", "dave"),
                               person("Davey", "davey", relationship="self")]}
        finding = oi.find_owner_row(roster, NAMES)
        self.assertEqual((finding.note, finding.row["slug"]), (oi.FOUND_SELF, "davey"))
        self.assertTrue(oi.is_owner_row(finding.row))

    def test_a_name_only_row_is_found_by_the_profile_names(self):
        roster = founder_shaped()
        finding = oi.find_owner_row(roster, NAMES)
        self.assertEqual((finding.note, finding.row["slug"]), (oi.FOUND_NAME, "dave"))
        self.assertEqual(oi.owner_ref(roster, NAMES), "person/dave")
        self.assertFalse(oi.is_owner_row(finding.row))

    def test_two_rows_is_ambiguous_and_names_nobody(self):
        roster = {"entities": [person("Dave", "dave"),
                               person("David James Taylor", "david-james-taylor")]}
        finding = oi.find_owner_row(roster, NAMES)
        self.assertIsNone(finding.row)
        self.assertEqual(finding.note, oi.FOUND_AMBIGUOUS)
        self.assertEqual(finding.candidates, ("dave", "david-james-taylor"))
        self.assertIsNone(oi.owner_row(roster, NAMES))
        two_selves = {"entities": [person("A", "a", relationship="self"),
                                   person("B", "b", relationship="self")]}
        self.assertEqual(oi.find_owner_row(two_selves, NAMES).note, oi.FOUND_AMBIGUOUS)

    def test_no_names_and_no_self_row_is_none(self):
        self.assertEqual(oi.find_owner_row(founder_shaped(), ()).note, oi.FOUND_NONE)

    def test_a_folded_row_is_never_the_owner(self):
        row = person("Dave", "dave", relationship="self", folded_into="other")
        self.assertFalse(oi.is_owner_row(row))


class OwnerMention(unittest.TestCase):

    def test_every_owner_form(self):
        for text in ("Dave", "David James Taylor", "David Taylor", "Dave Taylor",
                     "Dave (narrator)", "David Taylor (author)", "Dave (the narrator)",
                     "Dave (me)", "the narrator", "the author", "me", "Self"):
            with self.subTest(text=text):
                self.assertTrue(oi.is_owner_mention(text, NAMES))

    def test_a_relative_with_his_surname_is_not_him(self):
        for text in ("Wren Taylor", "Anna Taylor", "David", "Taylor", "Dave's kids",
                     "Wren (narrator)", "Davey Jones", ""):
            with self.subTest(text=text):
                self.assertFalse(oi.is_owner_mention(text, NAMES))

    def test_without_profile_names_only_the_owner_words(self):
        self.assertFalse(oi.is_owner_mention("Dave", ()))
        self.assertTrue(oi.is_owner_mention("the narrator", ()))

    def test_owner_possessives(self):
        self.assertTrue(oi.is_owner_possessive("Dave's kids", NAMES))
        self.assertTrue(oi.is_owner_possessive("David James Taylor’s mom", NAMES))
        self.assertFalse(oi.is_owner_possessive("Wren's kids", NAMES))
        self.assertFalse(oi.is_owner_possessive("Dave", NAMES))


# --------------------------------------------------------------------------
# D6 — the converter's owner step (acceptance 5)
# --------------------------------------------------------------------------


class ConverterOwnerStep(unittest.TestCase):

    def test_marks_the_row_and_is_byte_stable(self):
        once, report = rr.convert_legacy_roster(founder_shaped(), owner=CONTEXT)
        dave = next(e for e in once["entities"] if e["slug"] == "dave")
        self.assertEqual(dave["relationship"], "self")
        self.assertEqual(dave["focus"], "my-life")
        self.assertIs(dave["page_eligible"], False)
        self.assertEqual(dave["aliases"], ["David Taylor", "David James Taylor"])
        self.assertEqual(report["owner"]["slug"], "dave")
        self.assertEqual(report["owner"]["changes"]["aliases_dropped"], ["Dave's kids"])
        kids = next(q for q in once["relation_queries"] if q["relationship"] == "child")
        self.assertIn("Dave's kids", kids["aliases"])
        # Everything else the payload carries is kept.
        for key in ("version", "type", "resolved_at", "source", "retired_rows"):
            self.assertEqual(once[key], founder_shaped()[key])
        twice, report2 = rr.convert_legacy_roster(once, owner=CONTEXT)
        self.assertEqual(dump(once), dump(twice))
        self.assertFalse(report2["changed"])
        self.assertEqual(report2["owner"]["changes"], {})

    def test_no_roadmap_leaves_focus_alone(self):
        converted, _ = rr.convert_legacy_roster(founder_shaped(),
                                                owner=oi.OwnerContext(NAMES, ""))
        dave = next(e for e in converted["entities"] if e["slug"] == "dave")
        self.assertEqual(dave["relationship"], "self")
        self.assertIsNone(dave["focus"])
        self.assertIs(dave["page_eligible"], False)

    def test_no_owner_context_is_the_v386_converter(self):
        converted, report = rr.convert_legacy_roster(founder_shaped())
        self.assertNotIn("owner", report)
        dave = next(e for e in converted["entities"] if e["slug"] == "dave")
        self.assertNotIn("relationship", dave)

    def test_an_ambiguous_owner_is_left_alone(self):
        roster = founder_shaped()
        roster["entities"].append(person("David James Taylor", "david-james-taylor"))
        roster["entities"][0]["aliases"] = ["David Taylor"]
        converted, report = rr.convert_legacy_roster(roster, owner=CONTEXT)
        self.assertEqual(report["owner"]["found"], oi.FOUND_AMBIGUOUS)
        self.assertFalse(any(e.get("relationship") == "self" for e in converted["entities"]))


class DavesKidsRegression(unittest.TestCase):
    """The v386 converter put "Dave's kids" onto the owner's row: the owner
    possessive resolved to the owner. A possessive names somebody OF its
    possessor — it stays on its relation query."""

    def roster(self) -> dict:
        return {"version": 1, "type": "person", "entities": [
            person("Dave", "dave", aliases=["David Taylor", "David James Taylor"]),
            person("Wren Taylor", "wren-taylor", relationship="child"),
            person("Kids", "kids", qualifies=False, unique_answers=3,
                   aliases=["Dave's kids", "the kids"]),
        ]}

    def test_never_reattributed_without_the_profile(self):
        converted, report = rr.convert_legacy_roster(self.roster())
        dave = next(e for e in converted["entities"] if e["slug"] == "dave")
        self.assertNotIn("Dave's kids", dave["aliases"])
        self.assertFalse(report["reattributed"])
        query = next(q for q in converted["relation_queries"] if q["word"] == "kids")
        self.assertIn("Dave's kids", query["aliases"])

    def test_never_reattributed_with_the_profile(self):
        converted, _ = rr.convert_legacy_roster(self.roster(), owner=CONTEXT)
        dave = next(e for e in converted["entities"] if e["slug"] == "dave")
        self.assertNotIn("Dave's kids", dave["aliases"])
        self.assertEqual(dave["relationship"], "self")


# --------------------------------------------------------------------------
# D3 — minting never makes a stranger of the owner (acceptance 2)
# --------------------------------------------------------------------------


class Minting(unittest.TestCase):

    RAW = [{"name": "Dave", "qualifies": True}, {"name": "David Taylor", "qualifies": True},
           {"name": "David James Taylor", "qualifies": True},
           {"name": "Dave (narrator)", "qualifies": True},
           {"name": "Wren Taylor", "qualifies": True}]

    def owners(self, rows):
        return [e for e in rows if e.get("relationship") == "self"
                or oi.is_owner_mention(e["name"], NAMES)]

    def test_four_spellings_are_one_self_row(self):
        rows = entity_roster.normalize("person", copy.deepcopy(self.RAW), [], {}, 0.0, 0,
                                       owner=CONTEXT)
        owners = self.owners(rows)
        self.assertEqual(len(owners), 1)
        dave = owners[0]
        self.assertEqual((dave["name"], dave["slug"], dave["relationship"]),
                         ("Dave", "dave", "self"))
        self.assertEqual(sorted(dave["aliases"]), ["David James Taylor", "David Taylor"])
        self.assertIs(dave["page_eligible"], False)
        self.assertEqual(dave["focus"], "my-life")
        self.assertIn("wren-taylor", {e["slug"] for e in rows})
        self.assertEqual(len(rows), 2)

    def test_mints_one_row_named_the_profile_name(self):
        raw = [r for r in copy.deepcopy(self.RAW) if r["name"] != "Dave"]
        rows = entity_roster.normalize("person", raw, [], {}, 0.0, 0, owner=CONTEXT)
        owners = self.owners(rows)
        self.assertEqual(len(owners), 1)
        self.assertEqual(owners[0]["slug"], "dave")
        self.assertEqual(owners[0]["relationship"], "self")

    def test_the_deterministic_path_too(self):
        candidates = [{"entity": name, "score": 9.0, "unique_answers": 5, "evidence": []}
                      for name in ("Dave", "David Taylor", "Dave (narrator)", "Wren Taylor")]
        with mock.patch.object(entity_roster, "_owner_context", lambda *_a, **_k: CONTEXT):
            rows = entity_roster.deterministic("person", candidates, {}, 0.0, 0)
        self.assertEqual(len(self.owners(rows)), 1)
        self.assertEqual(len(rows), 2)

    def test_a_previous_self_row_survives_a_refresh_that_retypes_it(self):
        previous = {"entities": [person("Dave", "dave", relationship="self",
                                        aliases=["David Taylor"])]}
        raw, _ = entity_roster.apply_previous_decisions(
            [{"name": "David Taylor", "relationship": "friend", "qualifies": True}], previous)
        self.assertEqual(raw[0]["relationship"], "self")

    def test_without_a_profile_nothing_changes(self):
        rows = entity_roster.normalize("person", copy.deepcopy(self.RAW), [], {}, 0.0, 0,
                                       owner=oi.OwnerContext())
        self.assertEqual(len(rows), 5)

    def test_the_prompt_names_the_author(self):
        prompt = entity_roster.build_prompt("person", [], {}, owner=CONTEXT)
        self.assertIn('The AUTHOR is "Dave", "David James Taylor"', prompt)
        self.assertNotIn("AUTHOR", entity_roster.build_prompt("person", [], {},
                                                              owner=oi.OwnerContext()))


class FirstNameAliasesSkipTheOwner(_TmpRoster):

    def test_the_self_row_takes_no_first_name_alias(self):
        self.write({"version": 1, "type": "person", "entities": [
            person("David James Taylor", "david-james-taylor", relationship="self"),
            person("Wren Taylor", "wren-taylor", relationship="child"),
        ]})
        with redirect_stdout(io.StringIO()):
            result = entity_roster.first_name_aliases(dry_run=True)
        self.assertEqual([row["slug"] for row in result["added"]], ["wren-taylor"])


# --------------------------------------------------------------------------
# D3 — verdicts refuse to make a stranger of the owner
# --------------------------------------------------------------------------


class VerdictRefusals(_TmpRoster):

    def setUp(self):
        super().setUp()
        self.path = self.write(founder_shaped())
        # Persist the converted shape so a refusal is checked byte-for-byte.
        entity_roster.repair_owner_identity(apply=True)
        self.before = self.path.read_bytes()

    def refused(self, call):
        with self.assertRaises(entity_verdict.EntityIsOwner) as ctx:
            call()
        self.assertEqual(self.path.read_bytes(), self.before)
        return ctx.exception

    def test_each_act_is_refused_with_one_reason(self):
        acts = {
            "relationship": lambda: entity_verdict.apply_verdict(
                "person", "dave", "clear", relationship="friend"),
            "focus": lambda: entity_verdict.apply_verdict("person", "dave", "clear", focus="ilse"),
            "graduate": lambda: entity_verdict.apply_verdict("person", "dave", "graduate"),
            "never": lambda: entity_verdict.apply_verdict("person", "dave", "never"),
            "fold loser": lambda: entity_verdict.apply_verdict(
                "person", "dave", "clear", fold_into="wren-taylor"),
            "retire": lambda: entity_verdict.retire_row("person", "dave", receipt={"why": "x"}),
        }
        for act, call in acts.items():
            with self.subTest(act=act):
                exc = self.refused(call)
                self.assertEqual(exc.reason, oi.ENTITY_IS_OWNER)
                self.assertEqual(exc.reason, "ENTITY_IS_OWNER")

    def test_the_cli_exits_one_and_writes_nothing(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            code = entity_verdict.main(["person", "dave", "graduate"])
        self.assertEqual(code, 1)
        self.assertIn("ENTITY_IS_OWNER", err.getvalue())
        self.assertEqual(self.path.read_bytes(), self.before)

    def test_folding_another_row_into_the_owner_is_allowed(self):
        data = json.loads(self.before)
        data["entities"].append(person("Me", "me-row"))
        self.path.write_text(json.dumps(data), encoding="utf-8")
        entity_verdict.apply_verdict("person", "me-row", "clear", fold_into="dave")
        after = json.loads(self.path.read_text(encoding="utf-8"))
        dave = next(e for e in after["entities"] if e["slug"] == "dave")
        self.assertIn("Me", dave["aliases"])
        self.assertEqual(dave["relationship"], "self")

    def test_an_alias_on_the_owner_is_allowed_and_keeps_no_person_page(self):
        entity_verdict.apply_verdict("person", "dave", "clear", aliases=["DJT"])
        dave = next(e for e in json.loads(self.path.read_text())["entities"]
                    if e["slug"] == "dave")
        self.assertIn("DJT", dave["aliases"])
        self.assertIs(dave["page_eligible"], False)

    def test_attach_focus_refuses_a_person_focus(self):
        exc = self.refused(lambda: entity_verdict.attach_focus("dave", "ilse"))
        self.assertEqual(exc.reason, "THE_OWNER_IS_NOT_A_PERSON_FOCUS")
        # The primary Focus he already has is a no-op, never a refusal.
        self.assertEqual(entity_verdict.attach_focus("dave", "my-life")["focus"], "my-life")


class FocusNewRefusal(_TmpRoster):

    def setUp(self):
        super().setUp()
        self.write(founder_shaped())
        self.qbank = self.tmp / "question-bank.md"
        self.qbank.write_text("## A: Origins\n- [x] A1: Earliest? *(2026-01-01)*\n",
                              encoding="utf-8")
        for target, attr in ((roadmap, "QUESTIONS_FILE"), (lifehug_core, "QUESTIONS_FILE"),
                             (entity_roster, "QUESTIONS_FILE")):
            patcher = mock.patch.object(target, attr, self.qbank)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(roadmap, "ROADMAP_FILE", lifehug_core.ROADMAP_FILE)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_person_slug_and_label_are_refused(self):
        before = self.qbank.read_bytes()
        for kwargs in ({"label": "Dave", "person_slug": "dave"},
                       {"label": "David Taylor"},
                       {"label": "Dave (narrator)"}):
            with self.subTest(**kwargs):
                with self.assertRaises(roadmap.OwnerIsNotAPersonFocusError) as ctx:
                    roadmap.focus_new(kwargs.pop("label"), "person", "basic", generate=False,
                                      **kwargs)
                self.assertEqual(ctx.exception.reason, "THE_OWNER_IS_NOT_A_PERSON_FOCUS")
        self.assertEqual(self.qbank.read_bytes(), before)


class RecommendationsCoverTheOwner(_TmpRoster):

    def test_the_owner_is_covered_without_a_page(self):
        self.write(founder_shaped())
        with mock.patch.object(entity_roster, "QUESTIONS_FILE", self.tmp / "none.md"):
            people = recommend_focuses._identity_people()
        resolved = recommend_focuses._resolved_person("David James Taylor", people)
        self.assertTrue(resolved["is_owner"])
        self.assertTrue(recommend_focuses._person_is_covered(resolved, set()))
        wren = recommend_focuses._resolved_person("Wren Taylor", people)
        self.assertFalse(recommend_focuses._person_is_covered(wren, set()))

    def test_an_unrostered_owner_detection_is_never_recommended(self):
        names = recommend_focuses._owner_names()
        self.assertEqual(names, NAMES)
        self.assertTrue(recommend_focuses._is_owner_detection("Dave (narrator)", names))
        self.assertFalse(recommend_focuses._is_owner_detection("Wren Taylor", names))


# --------------------------------------------------------------------------
# D3 — the classifier's two seats
# --------------------------------------------------------------------------


class ClassifierSeats(unittest.TestCase):

    def roster(self) -> dict:
        converted, _ = rr.convert_legacy_roster(founder_shaped(), owner=CONTEXT)
        return converted

    def test_an_owner_subject_is_self_never_person_owner(self):
        rosters = {"person": ir.roster_index(self.roster(), entity_type="person")}
        refs, unresolved, ambiguities = classifier_context._resolved_subject_refs(
            ["Dave", "David James Taylor", "Dave (narrator)", "Wren Taylor"],
            rosters=rosters, owner_names=NAMES)
        self.assertEqual(refs, ["person/wren-taylor", "self"])
        self.assertNotIn("person/dave", refs)
        self.assertEqual((unresolved, ambiguities), ([], []))
        # Without the owner's names the roster match stands (pre-v426 shape).
        refs, _, _ = classifier_context._resolved_subject_refs(["Dave"], rosters=rosters)
        self.assertEqual(refs, ["person/dave"])

    def test_known_people_lists_the_owner_as_you(self):
        block = person_resolution.render_known_people(self.roster())
        first = block.splitlines()[0]
        self.assertEqual(first, "- Dave (you, the author) — also: David Taylor, David James Taylor")
        self.assertEqual(sum("Dave" in line.split(" — ")[0] for line in block.splitlines()), 1)


# --------------------------------------------------------------------------
# D6 — the verb (acceptance 5)
# --------------------------------------------------------------------------


class OwnerIdentityVerb(_TmpRoster):

    def run_verb(self, *argv) -> str:
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(oi.main(list(argv)), 0)
        return out.getvalue()

    def test_report_apply_and_idempotent(self):
        path = self.write(founder_shaped())
        original = path.read_bytes()
        report = json.loads(self.run_verb("--json"))
        self.assertEqual(path.read_bytes(), original)  # a report writes nothing
        self.assertEqual(report["profile_names"], list(NAMES))
        self.assertEqual((report["found"], report["slug"]), ("name", "dave"))
        self.assertEqual(report["changes"]["relationship"], {"was": None, "now": "self"})
        self.assertEqual(report["changes"]["focus"], {"was": None, "now": "my-life"})
        self.assertEqual(report["changes"]["page_eligible"], {"was": True, "now": False})
        self.assertEqual(report["changes"]["aliases_dropped"], ["Dave's kids"])
        self.assertFalse(report["applied"])
        self.assertIn("would change", self.run_verb())

        applied = json.loads(self.run_verb("--apply", "--json"))
        self.assertTrue(applied["applied"])
        once = path.read_bytes()
        again = json.loads(self.run_verb("--apply", "--json"))
        self.assertFalse(again["changed"])
        self.assertFalse(again["applied"])
        self.assertEqual(again["changes"], {})
        self.assertEqual(path.read_bytes(), once)
        self.assertIn("nothing to do", self.run_verb("--apply"))
        payload = json.loads(once)
        self.assertEqual(payload["resolved_at"], "2026-10-01T05:00:00Z")
        self.assertEqual(payload["retired_rows"], [])

    def test_entity_roster_convert_identity_runs_the_owner_step(self):
        path = self.write(founder_shaped())
        with mock.patch.object(entity_roster, "QUESTIONS_FILE", self.tmp / "none.md"):
            entity_roster.convert_identity(focus_map={})
        dave = next(e for e in json.loads(path.read_text())["entities"] if e["slug"] == "dave")
        self.assertEqual(dave["relationship"], "self")

    def test_no_roster_is_nothing_to_do(self):
        self.assertIn("nothing to do", self.run_verb())

    def test_the_verb_is_wired(self):
        import lifehug  # noqa: PLC0415

        self.assertIn("owner-identity", lifehug.DIRECT_MUTATION_COMMANDS)
        args = lifehug.build_parser().parse_args(["owner-identity", "--apply", "--json"])
        self.assertIs(args.func, lifehug.cmd_owner_identity)


# --------------------------------------------------------------------------
# The guard — no second reading of the profile names
# --------------------------------------------------------------------------


class NoInlineProfileNameReads(unittest.TestCase):
    """The known readers of the owner's profile spellings read them through
    `owner_identity` (or `focus_pages.author_names`, which does). v427 (O2)
    rewired `serve_wiki` and `wiki_compile` and added them here."""

    READERS = ("focus_pages.py", "roadmap.py", "mirror.py", "lifehug.py",
               "serve_wiki.py", "wiki_compile.py")
    INLINE = re.compile(
        r"""(?:cfg|config|profile|load_config\(\))\s*(?:\.get\(\s*|\[\s*)["'](?:name|full_name)["']""")

    def test_no_reader_spells_the_owner_itself(self):
        for name in self.READERS:
            text = (ROOT / "system" / name).read_text(encoding="utf-8")
            with self.subTest(module=name):
                self.assertEqual(self.INLINE.findall(text), [])

    def test_the_readers_ask_owner_identity(self):
        for name in ("focus_pages.py", "roadmap.py", "mirror.py", "serve_wiki.py",
                     "wiki_compile.py"):
            text = (ROOT / "system" / name).read_text(encoding="utf-8")
            with self.subTest(module=name):
                self.assertIn("owner_identity", text)

    def test_the_definition_does_read_them(self):
        text = (ROOT / "system" / "owner_identity.py").read_text(encoding="utf-8")
        self.assertIn('OWNER_NAME_PROFILE_KEYS = ("name", "full_name")', text)


if __name__ == "__main__":
    unittest.main()
