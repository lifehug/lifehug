"""v376: a focus finds its page (issue #434, graph joins). All data is synthetic.

The fixture is built from the shapes production actually writes, not hand-set
ones: a question bank shaped like the owner's (A–E arcs, an ``(Etherfuse
Story)`` project group, ``## Focuses`` people including a parenthetical
``Focus — Dad (James Edwin Taylor)``), a roadmap produced by
``rebuild_roadmap`` and ``focus_new`` (a place Focus and a relationship Focus),
and wiki pages written by the real compiler (``wiki_compile.py --no-ai``) in an
external vault. The graph is then read in that vault.

Rules: ``A_FOCUS_KNOWS_ITS_OWN_PAGE``, ``A_RELATIONSHIP_HAS_TWO_ENDS``,
``A_PRIMARY_FOCUS_IS_THE_HUB``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

from tempdirs import root_parent_tmp  # noqa: E402
import focus_pages  # noqa: E402
import portrait_targets  # noqa: E402
import serve_wiki  # noqa: E402

BANK = """# Question Bank

## A: Origins (Childhood & Family)
- [x] A1: Where were you born? *(2026-01-01)*
- [ ] A2: What did your house look like?

## B: Becoming (Growing Up & Direction)
- [ ] B1: When did you leave home?

## C: Relationships & People
- [ ] C1: Who shaped you?

## D: Etherfuse & Purpose
- [ ] D1: Why this work?

## E: Reflection & Wisdom
- [ ] E1: What would you tell your younger self?

## Project Categories

## F: The Problem (Etherfuse Story)
- [x] F1: What was broken? *(2026-01-02)*

## G: The Insight (Etherfuse Story)
- [ ] G1: What did you see first?

## Focuses

## K: Focus — Mom
- [x] K1: Tell me about your mom. *(2026-01-03)*
- [x] K2: What did your mom teach you? *(2026-01-04)*

## L: Focus — Katie
- [x] L1: How did you meet Katie? *(2026-01-05)*

## M: Focus — Dad (James Edwin Taylor)
- [ ] M1: What was your dad like?
"""

ANSWERS = {
    "A1": "I was born in Mesa. Mom kept us fed on almost nothing; childhood was moving.",
    "F1": "Money did not move across borders for the people who needed it.",
    "K1": "Mom was kind to everyone. My childhood with Mom was belonging and moving.",
    "K2": "Mom taught me that kindness is a choice. Katie says I got that from her.",
    "L1": "I met Katie in Provo. Mom liked her right away.",
}


def _answer(qid: str, body: str) -> str:
    return (
        "---\n"
        f'title: "{qid}"\n'
        'type: "prompted_answer"\n'
        f'source_id: "answer:{qid}"\n'
        f'question_id: "{qid}"\n'
        'captured_at: "2026-01-01T00:00:00Z"\n'
        'visibility: "owner_only"\n'
        "immutable: true\n"
        "schema_version: 1\n"
        f'source_path: "answers/{qid}.md"\n'
        "---\n\n"
        f"# {qid}\n\n{body}\n"
    )


def make_vault(root: Path) -> Path:
    (root / "state").mkdir(parents=True)
    (root / "answers").mkdir()
    (root / "question-bank.md").write_text(BANK, encoding="utf-8")
    (root / "profile.yaml").write_text(
        'name: "Dave"\nfull_name: "David James Taylor"\n', encoding="utf-8")
    (root / "state" / "rotation.json").write_text(json.dumps({
        "version": 1, "current_pass": 1, "pass_names": ["skeleton"],
        "last_question_id": None, "last_asked_at": None, "questions_asked": 0,
        "questions_answered": 0, "next_question_id": None, "focus_frequency": 4,
    }), encoding="utf-8")
    (root / "state" / "coverage.json").write_text(json.dumps({
        "version": 1, "last_updated": None, "categories": {},
    }), encoding="utf-8")
    for qid, body in ANSWERS.items():
        (root / "answers" / f"{qid}.md").write_text(_answer(qid, body), encoding="utf-8")
    return root


# Runs inside the external vault: the real roadmap doors, then the graph.
DRIVER = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import roadmap
roadmap.rebuild_roadmap(write=True)
roadmap.focus_new("Solothurn", "place", "standard", generate=False)
roadmap.focus_new("Grandma Betty Jo", "relationship", "basic", generate=False)
print(json.dumps(roadmap.load_roadmap()))
"""

GRAPH = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import serve_wiki
print(json.dumps({"graph": serve_wiki.graph_data(), "joins": serve_wiki.graph_focus_joins()}))
"""


class RealShapedVaultTests(unittest.TestCase):
    """One compiled external vault, shared by the assertions below."""

    @classmethod
    def setUpClass(cls):
        cls._holder = unittest.TestCase()
        cls.tmp = root_parent_tmp(cls._holder, ROOT, prefix="lifehug-v376-")
        cls.vault = make_vault(cls.tmp / "vault")
        env = dict(os.environ, LIFEHUG_VAULT_ROOT=str(cls.vault))

        def run(args: list[str]) -> str:
            proc = subprocess.run(args, capture_output=True, text=True, env=env, cwd=str(cls.tmp))
            if proc.returncode != 0:
                raise AssertionError(f"{args[:3]} failed:\n{proc.stdout}\n{proc.stderr}")
            return proc.stdout

        out = run([sys.executable, "-c", DRIVER, str(SYSTEM)])
        cls.roadmap = json.loads(out.strip().splitlines()[-1])
        run([sys.executable, str(SYSTEM / "wiki_compile.py"), "--no-ai"])
        out = run([sys.executable, "-c", GRAPH, str(SYSTEM)])
        payload = json.loads(out.strip().splitlines()[-1])
        cls.graph, cls.joins = payload["graph"], payload["joins"]
        cls.doctor = run([sys.executable, "-c",
                          "import sys; sys.path.insert(0, sys.argv[1]); import lifehug; "
                          "lifehug.graph_portrait_checks()", str(SYSTEM)])

    @classmethod
    def tearDownClass(cls):
        cls._holder.doCleanups()

    def focus(self, fid: str) -> dict:
        return next(f for f in self.roadmap["focuses"] if f["id"] == fid)

    def test_roadmap_wiki_node_is_the_page_the_compiler_writes(self):
        # A_PRIMARY_FOCUS_IS_THE_HUB: the primary focus is the life hub.
        self.assertEqual(self.focus("my-life")["wiki_node"], "wiki/life/david-james-taylor.md")
        # A grouped project focus is one page per category, never projects/<tag>.md.
        self.assertEqual(self.focus("etherfuse")["wiki_node"], "wiki/projects/the-problem.md")
        # Every ## Focuses category compiles to a person page, whatever the type.
        self.assertEqual(self.focus("solothurn")["wiki_node"], "wiki/people/solothurn.md")
        self.assertEqual(self.focus("dad")["wiki_node"], "wiki/people/dad.md")
        # A relationship focus is its edge page.
        self.assertEqual(self.focus("grandma-betty-jo")["wiki_node"],
                         "wiki/relationships/dave-and-grandma-betty-jo.md")

    def test_every_focus_resolves_or_is_reported(self):
        rows = {r["focus_id"]: r for r in self.joins["joins"]}
        self.assertIsNone(self.joins["error"])
        self.assertEqual(rows["my-life"]["pages"], ["wiki/life/david-james-taylor.md"])
        self.assertEqual(rows["my-life"]["rule"], focus_pages.A_PRIMARY_FOCUS_IS_THE_HUB)
        self.assertEqual(rows["etherfuse"]["pages"],
                         ["wiki/projects/the-problem.md", "wiki/projects/the-insight.md"])
        for fid in ("mom", "katie", "dad", "solothurn"):
            self.assertTrue(rows[fid]["pages"], fid)
            self.assertFalse(rows[fid]["missing"], fid)
        for row in rows.values():
            for page in row["pages"]:
                self.assertTrue((self.vault / page).is_file(), page)
        # The relationship focus has no answers yet, so no edge page: reported.
        self.assertEqual(rows["grandma-betty-jo"]["missing_relationships"],
                         ["wiki/relationships/dave-and-grandma-betty-jo.md"])
        self.assertIn("focus 'Grandma Betty Jo': page wiki/relationships/dave-and-grandma-betty-jo.md "
                      "does not exist", self.graph["warnings"])
        self.assertIn("warn: graph focus pages", self.doctor)
        self.assertIn("dave-and-grandma-betty-jo.md", self.doctor)

    def test_relationship_edges_join_the_owner_and_the_person(self):
        # The compiled page has the audited shape: a multi-item related: list
        # whose second item is not the other end (it is a theme or a page).
        fm = serve_wiki._frontmatter_block(
            (self.vault / "wiki/relationships/dave-and-mom.md").read_text(encoding="utf-8"))
        related = serve_wiki._fm_list(fm, "related")
        self.assertGreater(len(related), 2)
        self.assertEqual(related[0], "mom")
        self.assertNotIn(related[1], {"david-james-taylor", "dave"})
        rels = {e["page"]: e for e in self.graph["edges"] if e.get("kind") == "relationship"}
        hub = "wiki/life/david-james-taylor.md"
        self.assertEqual({rels["wiki/relationships/dave-and-mom.md"]["source"],
                          rels["wiki/relationships/dave-and-mom.md"]["target"]},
                         {hub, "wiki/people/mom.md"})
        self.assertEqual({rels["wiki/relationships/dave-and-katie.md"]["source"],
                          rels["wiki/relationships/dave-and-katie.md"]["target"]},
                         {hub, "wiki/people/katie.md"})
        # told reaches the edge through the Mom focus: 2 answered of target 20.
        self.assertGreater(rels["wiki/relationships/dave-and-mom.md"]["told"], 0)

    def test_focus_pages_carry_their_focus(self):
        # v378: every entity has a target ring; a Focus page also names its Focus.
        # v380 (A_FOCUS_WEARS_GOLD): ``focus`` is the active-Focus flag, the name
        # moved to ``focus_label``.
        by_id = {n["id"]: n for n in self.graph["nodes"]}
        self.assertEqual(by_id["wiki/life/david-james-taylor.md"]["focus_label"], "David James Taylor")
        self.assertIs(by_id["wiki/life/david-james-taylor.md"]["focus"], True)
        for page in ("wiki/projects/the-problem.md", "wiki/projects/the-insight.md"):
            self.assertEqual(by_id[page]["focus_label"], "Etherfuse")
            self.assertGreater(by_id[page]["target"], 0)

    def test_zero_credit_draws_at_the_minimum(self):
        # Radius is radius_min + span * sqrt(told / value_max): told 0 is the minimum.
        self.assertEqual(self.graph["style"]["radius_min"], portrait_targets.RADIUS_MIN)
        self.assertTrue(any(n["told"] == 0 for n in self.graph["nodes"]))

    def test_doctor_prints_effective_portrait_values_and_origin(self):
        self.assertIn(f"drawing.radius_min = {portrait_targets.RADIUS_MIN} <- framework "
                      "system/portrait_targets.json", self.doctor)


class RelationshipEndsTests(unittest.TestCase):
    """The owner's "Dave & Mom" page lists mom, then a theme and a period."""

    def setUp(self):
        self.slug_to_id = {
            "mom": "wiki/people/mom.md", "dave": "wiki/people/dave.md",
            "childhood": "wiki/periods/childhood.md", "belonging": "wiki/themes/belonging.md",
            "grandma-betty-jo": "wiki/people/grandma-betty-jo.md",
        }
        self.label_to_id = {"mom": "wiki/people/mom.md", "dave": "wiki/people/dave.md"}
        self.hub = "wiki/life/david-james-taylor.md"

    def ends(self, title, related):
        return serve_wiki._relationship_ends(
            title, related, self.slug_to_id, self.label_to_id, self.hub,
            "wiki/relationships/x.md", ("Dave", "David James Taylor", "david-james-taylor"))

    def test_title_first_and_the_owner_is_the_hub(self):
        related = ["mom", "childhood", "belonging", "grandma-betty-jo"]
        self.assertEqual(set(self.ends("Dave & Mom", related)), {self.hub, "wiki/people/mom.md"})

    def test_related_is_only_a_fallback(self):
        # An end the title cannot resolve falls back to related:, then the hub.
        self.assertEqual(set(self.ends("Dave & Someone New", ["mom"])),
                         {self.hub, "wiki/people/mom.md"})
        # One unresolvable name and nothing to fall back on: only the hub, no edge.
        self.assertIsNone(self.ends("Someone New", []))


class PageRuleParityTests(unittest.TestCase):
    def test_page_dirs_match_the_compiler(self):
        import wiki_compile

        self.assertEqual(
            {k: v.name for k, v in wiki_compile.TYPE_DIRS.items()}, focus_pages.PAGE_DIRS)

    def test_relationship_focus_type_has_a_directory(self):
        import roadmap

        self.assertEqual(roadmap.TYPE_TO_WIKI_DIR["relationship"], "relationships")


class RoadmapFailureIsLoggedTests(unittest.TestCase):
    def test_a_broken_roadmap_is_a_warning_not_silence(self):
        with mock.patch.object(serve_wiki, "load_roadmap", side_effect=ValueError("bad json")), \
                self.assertLogs("lifehug.graph", level="WARNING") as logs:
            joined = serve_wiki.graph_focus_joins()
        self.assertIn("roadmap unreadable", joined["error"])
        self.assertTrue(any("no focus draws a ring" in line for line in logs.output))


class PortraitOverrideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v376-cfg-")

    def test_a_valid_override_wins_and_says_so(self):
        (self.tmp / "portrait_targets.json").write_text(
            json.dumps({"drawing": {"radius_min": 6}}), encoding="utf-8")
        cfg = portrait_targets.load(self.tmp)
        self.assertEqual(cfg.errors, [])
        self.assertEqual(cfg.get("drawing.radius_min"), 6)
        rows = {k: o for k, _v, o in portrait_targets.effective_rows(cfg)}
        self.assertEqual(rows["drawing.radius_min"], portrait_targets.OVERRIDE_ORIGIN)
        self.assertEqual(rows["drawing.radius_span"], portrait_targets.FRAMEWORK_ORIGIN)

    def test_an_invalid_override_is_rejected_whole(self):
        (self.tmp / "portrait_targets.json").write_text(json.dumps({
            "drawing": {"radius_min": 6, "radius_span": "big"},
            "credit": {"split": "half"}, "nonsense": 1,
        }), encoding="utf-8")
        cfg = portrait_targets.load(self.tmp)
        self.assertEqual(cfg.get("drawing.radius_min"), portrait_targets.RADIUS_MIN)
        joined = " ".join(cfg.errors)
        self.assertIn("drawing.radius_span", joined)
        self.assertIn("credit.split", joined)
        self.assertIn("nonsense", joined)


if __name__ == "__main__":
    unittest.main()
