"""v72 — Second voice (Tiers 1–3), letters, escalation, staleness, delivery."""

import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))


def load(name):
    """Load a private copy of system/<name>.py WITHOUT clobbering the shared
    sys.modules entry — other test modules bind the canonical module at import
    time, and replacing it mid-suite splits state across two module objects."""
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    orig = sys.modules.get(name)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        if orig is not None:
            sys.modules[name] = orig
        else:
            sys.modules.pop(name, None)
    return mod


core = load("lifehug_core")
ingest = load("ingest_story")
re_mod = load("research_expand")
qp = load("question_planner")
wc = load("wiki_compile")


class WitnessIngestTests(unittest.TestCase):
    def test_witness_frontmatter(self):
        import argparse
        args = argparse.Namespace(
            title="Mom's account — The Move", source="telegram",
            captured_at="2026-07-04T00:00:00Z", witness="Mom")
        fm = ingest.frontmatter(args, "sources/manual/x.md", [], "body")
        self.assertIn('type: "witness_account"', fm)
        self.assertIn('witness: "Mom"', fm)
        self.assertIn('witness_slug: "mom"', fm)

    def test_non_witness_unchanged(self):
        import argparse
        args = argparse.Namespace(
            title="A memory", source="telegram",
            captured_at="2026-07-04T00:00:00Z", witness=None)
        fm = ingest.frontmatter(args, "sources/manual/x.md", [], "body")
        self.assertIn('type: "unprompted_story"', fm)
        self.assertNotIn("witness:", fm)

    def test_witness_candidates_target_the_gap(self):
        cands = ingest.generate_witness_candidates("Mom", "The Move", "sources/manual/x.md", "now")
        self.assertEqual(len(cands), 3)
        self.assertTrue(any("differ" in c["text"] for c in cands))
        self.assertTrue(all("Mom" in c["text"] for c in cands))


class WitnessSynthesisTests(unittest.TestCase):
    def _desc(self, kind=None, witness=""):
        item = {"id": "manual:x", "source": "sources/manual/x.md", "body": "We moved in June."}
        if kind:
            item["kind"] = kind
            item["witness"] = witness
        return {
            "type": "person", "title": "Mom", "slug": "mom",
            "cited_items": [item], "supporting_items": [],
        }

    def test_witness_marked_and_instruction_present(self):
        prompt = wc.build_synthesis_prompt(self._desc("witness_account", "Mom"), [], "")
        self.assertIn("WITNESS ACCOUNT — Mom's words", prompt)
        self.assertIn("NEVER merge a witness account", prompt)
        self.assertIn("perspectives differ", prompt.lower())

    def test_no_witness_no_instruction(self):
        prompt = wc.build_synthesis_prompt(self._desc(), [], "")
        self.assertNotIn("WITNESS ACCOUNT", prompt)

    def test_task_sources_carry_witness_note(self):
        rows = wc.task_sources(self._desc("witness_account", "Mom"))
        self.assertEqual(rows[0]["witness"], "Mom")
        self.assertIn("never merge", rows[0]["note"])


class SecondVoiceOfferTests(unittest.TestCase):
    QUESTIONS = [
        {"id": "K9", "category": "K", "text": "What did your mom's kitchen smell like on Sundays?", "answered": False},
        {"id": "K10", "category": "K", "text": "Answered one", "answered": True},
    ]

    def setUp(self):
        self._orig = (qp.SECOND_VOICE_OFFERS_FILE, qp.load_question_state, qp.resolve_roadmap,
                      sys.modules["lifehug_core"].load_config)
        self.tmp = tempfile.TemporaryDirectory()
        qp.SECOND_VOICE_OFFERS_FILE = Path(self.tmp.name) / "offers.json"
        qp.load_question_state = lambda: (self.QUESTIONS, {"K": {"group": "focus"}}, {"categories": {}})
        qp.resolve_roadmap = lambda *a, **k: {"focuses": [
            {"id": "mom", "label": "Mom", "type": "person", "categories": ["K"]}]}
        sys.modules["lifehug_core"].load_config = lambda *a, **k: {"second_voice_offers_per_month": 2}

    def tearDown(self):
        (qp.SECOND_VOICE_OFFERS_FILE, qp.load_question_state, qp.resolve_roadmap,
         sys.modules["lifehug_core"].load_config) = self._orig
        self.tmp.cleanup()

    def test_offer_is_second_person_bank_question(self):
        offer = qp.pick_second_voice_offer()
        self.assertIsNotNone(offer)
        self.assertIn("ask Mom", offer)
        self.assertIn("No rush", offer)
        # Bank questions are second-person (askable of the person) — the offer
        # must come from the parent interview bank, not the author-lens category.
        from research_expand import INTERVIEW_BANKS
        self.assertTrue(any(q in offer for q in INTERVIEW_BANKS["parent"]))

    def test_offers_never_repeat_a_question(self):
        sys.modules["lifehug_core"].load_config = lambda *a, **k: {"second_voice_offers_per_month": 99}
        seen = set()
        while True:
            offer = qp.pick_second_voice_offer()
            if offer is None:
                break
            self.assertNotIn(offer, seen)
            seen.add(offer)
        from research_expand import INTERVIEW_BANKS
        self.assertEqual(len(seen), len(INTERVIEW_BANKS["parent"]))  # pool exhausts, never loops

    def test_monthly_cap_enforced(self):
        sys.modules["lifehug_core"].load_config = lambda *a, **k: {"second_voice_offers_per_month": 0}
        self.assertIsNone(qp.pick_second_voice_offer())

    def test_deceased_person_never_offered(self):
        qp.resolve_roadmap = lambda *a, **k: {"focuses": [
            {"id": "mom", "label": "Mom", "type": "person", "categories": ["K"], "living": False}]}
        self.assertIsNone(qp.pick_second_voice_offer())

    def test_relationship_inference(self):
        self.assertEqual(qp._relationship_for({"label": "Mom"}), "parent")
        self.assertEqual(qp._relationship_for({"label": "Charlee Joy Taylor",
                                               "relationship": "child"}), "child")
        self.assertEqual(qp._relationship_for({"label": "Trevor"}), "friend")

    def test_cap_counts_this_month(self):
        now = datetime(2026, 7, 15, tzinfo=timezone.utc)
        core.write_json(qp.SECOND_VOICE_OFFERS_FILE, {"version": 1, "offered": [
            {"question_id": "X1", "month": "2026-07"},
            {"question_id": "X2", "month": "2026-07"},
        ]})
        self.assertIsNone(qp.pick_second_voice_offer(now=now))
        # Last month's offers don't count against this month.
        core.write_json(qp.SECOND_VOICE_OFFERS_FILE, {"version": 1, "offered": [
            {"question_id": "X1", "month": "2026-06"},
            {"question_id": "X2", "month": "2026-06"},
        ]})
        self.assertIsNotNone(qp.pick_second_voice_offer(now=now))


class InterviewPackTests(unittest.TestCase):
    def test_pack_contains_bank_and_ingest_instructions(self):
        pack = re_mod.build_interview_pack("Mom", "parent")
        self.assertIn("Interview pack — Mom (parent)", pack)
        self.assertIn("day I was born", pack)
        self.assertIn('ingest-story --witness "Mom"', pack)
        self.assertIn("skip the rest", pack)  # not a checklist

    def test_all_relationship_banks_are_substantial(self):
        for rel, bank in re_mod.INTERVIEW_BANKS.items():
            self.assertGreaterEqual(len(bank), 5, rel)
            for q in bank:
                self.assertNotIn(q.split()[0].lower(), ("did", "do", "are", "is"), q)  # no yes/no openers


class EscalationTests(unittest.TestCase):
    def _rows(self, answered_count):
        questions = [
            {"id": f"K{i}", "category": "K", "text": "Tell me about who they are as a person",
             "answered": i <= answered_count} for i in range(1, 4)
        ]
        questions.append({"id": "K9", "category": "K",
                          "text": "How do you think they see you — and is it accurate, how they see you?",
                          "answered": False})
        findex = {"cat_to_focus": {"K": "mom"},
                  "info": {"mom": {"weight": 1.0, "type": "person", "fill": {}, "cap_fraction": 0.3}}}
        return qp.enriched_pending_questions(questions, {"K": {"group": "focus"}},
                                             {"categories": {}}, [], findex)

    def test_late_arc_held_until_earned(self):
        rows = self._rows(answered_count=0)
        late = next(r for r in rows if r["id"] == "K9")
        self.assertTrue(late["escalation_hold"])

    def test_late_arc_released_after_two_answers(self):
        rows = self._rows(answered_count=2)
        late = next(r for r in rows if r["id"] == "K9")
        self.assertFalse(late["escalation_hold"])


class FormatTests(unittest.TestCase):
    def test_new_formats_registered_with_templates(self):
        compose = load("compose")
        for fmt in ("unsent_letter", "legacy_letter"):
            self.assertIn(fmt, compose.VALID_FORMATS)
            self.assertTrue((ROOT / "templates" / f"{fmt}.md").exists(), fmt)

    def test_unsent_letter_template_is_owner_only_by_design(self):
        text = (ROOT / "templates" / "unsent_letter.md").read_text(encoding="utf-8")
        self.assertIn("NEVER be sent", text)
        self.assertIn("hello again", text)
        self.assertIn("Never suggest sharing", text)

    def test_legacy_letter_has_five_movements(self):
        text = (ROOT / "templates" / "legacy_letter.md").read_text(encoding="utf-8")
        for movement in ("Values", "Lessons", "Gratitude", "Hopes", "Forgiveness"):
            self.assertIn(movement, text)


if __name__ == "__main__":
    unittest.main()
