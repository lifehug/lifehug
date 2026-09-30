"""v378: the ring is a target (issue #434). All data is synthetic.

Real-shaped fixture (see ``test_v376_a_focus_finds_its_page``): an owner-shaped
bank, a roadmap from ``rebuild_roadmap`` + ``focus_new``, pages written by the
real compiler. On top of it, classified conversation and manual sources: one
that the classifier tagged with Mom as a subject, one that only names her in
passing (the classifier did not tag her), and one bulk import with no
classification at all. The graph is read in that vault, before and after.

Rules: the relevance gate (a non-answer source earns credit only for the
entities its current classification tags), told = credit at 1/n, target =
table weight x tier x the type's calibration scale, gap = max(0, 1 -
told/target), one radius scale for fill and ring.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

from tempdirs import root_parent_tmp  # noqa: E402
import portrait_targets  # noqa: E402
import serve_wiki  # noqa: E402
from test_v376_a_focus_finds_its_page import DRIVER, GRAPH, make_vault  # noqa: E402

CONVERSATION = "sources/conversations/msg-000000000000000000000001.md"
PASSING = "sources/manual/2026-01-10-passing.md"
BULK = "sources/gmail/2012-01-01-bulk.md"


def _source(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ntitle: \"{path.stem}\"\ntype: \"manual_source\"\n---\n\n{body}\n",
                    encoding="utf-8")


def _classification(vault: Path, source: str, **tags) -> None:
    data = {"version": 1, "source_path": source, "people": [], "places": [],
            "time_periods": [], "themes": [], "projects": []}
    data.update(tags)
    out = vault / "state" / "classifications" / (source.replace("/", "-")[:-3] + ".json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data), encoding="utf-8")


class TargetModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._holder = unittest.TestCase()
        cls.tmp = root_parent_tmp(cls._holder, ROOT, prefix="lifehug-v378-")
        cls.vault = make_vault(cls.tmp / "vault")
        env = dict(os.environ, LIFEHUG_VAULT_ROOT=str(cls.vault))

        def run(args: list[str]) -> str:
            proc = subprocess.run(args, capture_output=True, text=True, env=env, cwd=str(cls.tmp))
            if proc.returncode != 0:
                raise AssertionError(f"{args[:3]} failed:\n{proc.stdout}\n{proc.stderr}")
            return proc.stdout

        def graph() -> dict:
            out = run([sys.executable, "-c", GRAPH, str(SYSTEM)])
            return json.loads(out.strip().splitlines()[-1])["graph"]

        cls.sh = staticmethod(run)
        cls.graph_fn = staticmethod(graph)
        run([sys.executable, "-c", DRIVER, str(SYSTEM)])
        run([sys.executable, str(SYSTEM / "wiki_compile.py"), "--no-ai"])
        # The classifier's reading of the answers: who each one is about.
        _classification(cls.vault, "answers/K1.md",
                        people=[{"name": "Mom", "relationship": "mother", "mention_count": 3}])
        _classification(cls.vault, "answers/L1.md",
                        people=[{"name": "Katie", "relationship": "wife", "mention_count": 2}])
        cls.before = graph()
        _source(cls.vault / CONVERSATION, "Talked about Mom's garden and her kindness.")
        _classification(cls.vault, CONVERSATION,
                        people=[{"name": "Mom", "relationship": "mother", "mention_count": 2}])
        _source(cls.vault / PASSING, "Drove past the old school; Mom used to say it was haunted.")
        _classification(cls.vault, PASSING, places=[{"name": "Mesa", "type": "city"}])
        _source(cls.vault / BULK, "Mom Mom Mom — a newsletter with her name in it.")
        # The owner's per-entity override: a roadmap focus field.
        roadmap_file = cls.vault / "state" / "roadmap.json"
        roadmap = json.loads(roadmap_file.read_text(encoding="utf-8"))
        for focus in roadmap["focuses"]:
            if focus["id"] == "katie":
                focus["portrait_weight"] = 0.9
        roadmap_file.write_text(json.dumps(roadmap), encoding="utf-8")
        cls.after = graph()
        cls.doctor = run([sys.executable, "-c",
                          "import sys; sys.path.insert(0, sys.argv[1]); import lifehug; "
                          "lifehug.graph_portrait_checks()", str(SYSTEM)])

    @classmethod
    def tearDownClass(cls):
        cls._holder.doCleanups()

    @staticmethod
    def node(graph: dict, page: str) -> dict:
        return next(n for n in graph["nodes"] if n["id"] == page)

    def test_every_entity_has_a_target_and_a_gap(self):
        for n in self.after["nodes"]:
            self.assertGreater(n["target"], 0, n["id"])
            self.assertEqual(n["told"], n["credit"])
            self.assertGreaterEqual(n["gap"], 0)
            self.assertLessEqual(n["gap"], 1)

    def test_relevance_gate_counts_only_a_tagged_source(self):
        mom_before = self.node(self.before, "wiki/people/mom.md")["told"]
        mom_after = self.node(self.after, "wiki/people/mom.md")["told"]
        # The tagged conversation is Mom's alone: +1. The passing mention and
        # the unclassified bulk import add nothing.
        self.assertAlmostEqual(mom_after - mom_before, 1.0, places=3)

    def test_kinds_come_from_the_classifier_relation(self):
        self.assertEqual(self.node(self.after, "wiki/people/mom.md")["kind"], "parent")
        self.assertEqual(self.node(self.after, "wiki/people/katie.md")["kind"], "spouse")
        self.assertEqual(self.node(self.after, "wiki/life/david-james-taylor.md")["kind"], "hub")

    def test_weight_times_tier_and_calibration(self):
        mom = self.node(self.after, "wiki/people/mom.md")
        self.assertEqual(mom["weight"], portrait_targets.WEIGHT_PARENT)
        self.assertEqual(mom["tier"], "basic")  # tier_for_size: 2 questions
        scale = self.after["calibration"]["person"]["scale"]
        self.assertAlmostEqual(mom["target"],
                               portrait_targets.WEIGHT_PARENT * portrait_targets.TIER_BASIC * scale,
                               places=2)
        # Calibration: the best-told person (not the owner) sits on its target.
        people = [n for n in self.after["nodes"]
                  if n["type"] == "people" and n["kind"] != "owner" and n["told"] > 0]
        best = max(people, key=lambda n: n["told"] / n["target"])
        self.assertAlmostEqual(best["told"], best["target"], places=2)
        self.assertEqual(best["gap"], 0)

    def test_portrait_weight_on_a_focus_replaces_the_table_weight(self):
        self.assertEqual(self.node(self.before, "wiki/people/katie.md")["weight"], 1.0)
        self.assertEqual(self.node(self.after, "wiki/people/katie.md")["weight"], 0.9)

    def test_relationship_edges_carry_told_goal_and_gap(self):
        rels = {e["page"]: e for e in self.after["edges"] if e.get("kind") == "relationship"}
        mom = rels["wiki/relationships/dave-and-mom.md"]
        self.assertEqual(mom["relation"], "parent")
        self.assertGreater(mom["told"], 0)
        self.assertGreater(mom["goal"], 0)
        self.assertAlmostEqual(mom["gap"], max(0.0, 1 - mom["told"] / mom["goal"]), places=2)

    def test_style_is_one_scale_from_the_config(self):
        style = self.after["style"]
        self.assertEqual(style["radius_min"], portrait_targets.RADIUS_MIN)
        self.assertEqual(style["value_max"],
                         round(max(max(n["told"], n["target"]) for n in self.after["nodes"]), 3))
        body = serve_wiki.view_graph()[1]
        self.assertIn("function radius(v)", body)
        self.assertIn("n.ringR = radius(n.target)", body)
        self.assertNotIn("percentile", body)

    def test_doctor_lists_the_largest_gaps_by_type(self):
        self.assertIn("graph portrait gaps (largest 10 per type", self.doctor)
        self.assertIn("  people:", self.doctor)
        self.assertIn("targets.person.parent = 1.0 <- framework", self.doctor)


class OverrideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-v378-cfg-")

    def write(self, data: dict) -> portrait_targets.PortraitConfig:
        (self.tmp / "portrait_targets.json").write_text(json.dumps(data), encoding="utf-8")
        return portrait_targets.load(self.tmp)

    def test_a_vault_changes_a_weight_and_adds_a_kind(self):
        cfg = self.write({"targets": {"person": {"parent": 1.2, "aunt": 0.4}},
                          "calibration": {"quantile": 0.9}})
        self.assertEqual(cfg.errors, [])
        self.assertEqual(portrait_targets.table_weight(cfg, "person", "parent"), 1.2)
        self.assertEqual(portrait_targets.table_weight(cfg, "person", "aunt"), 0.4)
        rows = dict((k, o) for k, _v, o in portrait_targets.effective_rows(cfg))
        self.assertEqual(rows["targets.person.aunt"], portrait_targets.OVERRIDE_ORIGIN)

    def test_bad_values_reject_the_whole_override(self):
        cfg = self.write({"targets": {"person": {"parent": -1}},
                          "calibration": {"quantile": 1.5},
                          "kinds": {"age_frame_pattern": "(unclosed"},
                          "credit": {"classified_rule": "maybe"}})
        joined = " ".join(cfg.errors)
        for key in ("targets.person.parent", "calibration.quantile",
                    "kinds.age_frame_pattern", "credit.classified_rule"):
            self.assertIn(key, joined)
        self.assertEqual(portrait_targets.table_weight(cfg, "person", "parent"),
                         portrait_targets.WEIGHT_PARENT)


class CalibrationTests(unittest.TestCase):
    def cfg(self):
        return portrait_targets.load(None)

    def test_a_thin_type_borrows_the_median_scale(self):
        rows = [
            {"type": "person", "kind": "parent", "credit": 4.0, "base": 1.0},
            {"type": "person", "kind": "sibling", "credit": 2.0, "base": 0.8},
            {"type": "place", "kind": "city", "credit": 3.0, "base": 0.6},
            {"type": "place", "kind": "residence", "credit": 1.0, "base": 1.0},
            {"type": "self", "kind": "self", "credit": 0.0, "base": 1.0},
        ]
        cal = portrait_targets.apply_targets(rows, self.cfg())
        self.assertEqual(cal["person"], {"scale": 4.0, "source": "own"})
        self.assertEqual(cal["place"], {"scale": 5.0, "source": "own"})
        self.assertEqual(cal["self"]["source"], "borrowed")
        self.assertEqual(rows[0]["gap"], 0.0)
        self.assertAlmostEqual(rows[1]["gap"], 1 - 2.0 / 3.2)
        self.assertEqual(rows[4]["gap"], 1.0)

    def test_the_owner_page_is_not_calibrated_on(self):
        rows = [
            {"type": "person", "kind": "owner", "credit": 100.0, "base": 1.0},
            {"type": "person", "kind": "parent", "credit": 4.0, "base": 1.0},
            {"type": "person", "kind": "child", "credit": 2.0, "base": 1.0},
        ]
        cal = portrait_targets.apply_targets(rows, self.cfg())
        self.assertEqual(cal["person"]["scale"], 4.0)

    def test_relevance_gate_reads_tags_not_names(self):
        cfg = self.cfg()
        names = portrait_targets.tag_names({
            "people": [{"name": "Mom", "mention_count": 2}],
            "places": [{"name": "Mesa, Arizona (Tippett house)"}],
            "themes": ["family"], "time_periods": [{"era": "College"}],
            "projects": [{"name": "Etherfuse"}],
        }, cfg)
        self.assertEqual(names, ["Mom", "Mesa, Arizona (Tippett house)", "family", "College", "Etherfuse"])
        self.assertEqual(portrait_targets.name_variants("Mesa, Arizona (Tippett house)"),
                         ["Mesa, Arizona (Tippett house)", "Mesa, Arizona", "Mesa"])


if __name__ == "__main__":
    unittest.main()
