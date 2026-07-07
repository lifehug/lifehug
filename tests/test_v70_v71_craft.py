"""v70 (question craft) + v71 (time & self): why→what lint, deferral,
rumination detector, period arc, perennials, wiki harvest, timeline."""

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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
qc = load("question_candidates")
qprof = load("quality_profile")
re_mod = load("research_expand")
cls = load("classify_story")


def iso_days_ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace("+00:00", "Z")


class WhyWhatLintTests(unittest.TestCase):
    def test_self_directed_why_flagged(self):
        q = qc.check_quality("Why do you always feel like an outsider at these events?")
        self.assertIn("self_directed_why", q["flags"])

    def test_why_about_events_and_others_clean(self):
        for text in (
            "Why did the family leave Mesa when it did?",
            "Why do you think your dad made that choice?",
        ):
            self.assertNotIn("self_directed_why", qc.check_quality(text)["flags"], text)


class DeferralTests(unittest.TestCase):
    def test_classifier_defer_flag_sets_defer_until(self):
        store = {"candidates": []}
        recs = cls.build_candidates(
            [{"text": "A deep question about the fresh loss you described last week?",
              "story_function": "tension", "priority": 0.8, "defer": True}],
            Path("answers/Z1.md"), store, iso_days_ago(0))
        self.assertEqual(len(recs), 1)
        self.assertIn("defer_until", recs[0])
        age = qc._candidate_age_days({"created_at": recs[0]["defer_until"]})
        self.assertLess(age, 0)  # in the future

    def test_deferred_candidates_exempt_from_expiry(self):
        data = {"candidates": [{
            "id": "deferred-fresh", "status": "candidate",
            "created_at": iso_days_ago(60),
            "defer_until": iso_days_ago(-30),  # 30 days in the future
            "text": "q",
        }]}
        expired = qc.expire_stale_candidates(data)
        self.assertEqual(expired, [])
        self.assertEqual(data["candidates"][0]["status"], "candidate")


class RuminationTests(unittest.TestCase):
    def _sig(self, insight, negative, i_rate):
        return {"insight_rate": insight, "negative_rate": negative, "i_rate": i_rate}

    def test_brooding_signature_flags_category(self):
        scores = [{"category": "E", "signals": self._sig(0.02, 0.03, 0.10)} for _ in range(3)]
        self.assertEqual(qprof.detect_rumination(scores), ["E"])

    def test_rising_insight_is_processing_not_brooding(self):
        scores = [
            {"category": "E", "signals": self._sig(0.01, 0.03, 0.10)},
            {"category": "E", "signals": self._sig(0.02, 0.03, 0.10)},
            {"category": "E", "signals": self._sig(0.05, 0.03, 0.10)},
        ]
        self.assertEqual(qprof.detect_rumination(scores), [])

    def test_positive_material_never_flags(self):
        scores = [{"category": "A", "signals": self._sig(0.0, 0.001, 0.10)} for _ in range(3)]
        self.assertEqual(qprof.detect_rumination(scores), [])

    def test_insufficient_window_never_flags(self):
        scores = [{"category": "E", "signals": self._sig(0.0, 0.05, 0.2)}] * 2
        self.assertEqual(qprof.detect_rumination(scores), [])

    def test_signals_include_processing_rates(self):
        sig = qprof.extract_signals("I realized I was afraid because I understood my fear.")
        self.assertGreater(sig["insight_rate"], 0)
        self.assertGreater(sig["negative_rate"], 0)
        self.assertGreater(sig["i_rate"], 0)


class PeriodArcTests(unittest.TestCase):
    def test_time_period_arc_registered(self):
        arc = re_mod.arc_for("time_period")
        self.assertIs(arc, re_mod.PERIOD_ARC)
        functions = [fn for fn, _ in arc]
        self.assertIn("tension", functions)      # the Bridges transition slot
        self.assertEqual(len(arc), 6)

    def test_life_chapter_mode_in_prompt(self):
        prompt = re_mod.build_expansion_prompt(
            topic="My 20s", topic_type="time_period", target_output="chapter",
            mission="", source_content="", relevant_answers=[],
            question_bank_categories="")
        self.assertIn("LIFE-CHAPTER MODE", prompt)
        self.assertIn("NEVER ask 'what year was that?'", prompt)
        self.assertIn("neutral-zone", prompt)

    def test_craft_rules_in_prompt(self):
        prompt = re_mod.build_expansion_prompt(
            topic="Yucaipa", topic_type="place", target_output="chapter",
            mission="", source_content="", relevant_answers=[],
            question_bank_categories="")
        self.assertIn("Two-sentence rule", prompt)
        self.assertIn("typical-day reconstruction", prompt)
        self.assertIn("forgiveness/blessing", prompt)

    def test_gab_themes_present(self):
        self.assertIn("health_and_body", re_mod.THEME_KEYWORDS)
        self.assertIn("death_and_mortality", re_mod.THEME_KEYWORDS)


class PerennialTests(unittest.TestCase):
    BANK = (
        "# Bank\n\n"
        "## E: Reflection & Wisdom\n"
        "- [x] E3: How do you define success today? *(2025-06-01)*\n"
        "- [ ] E4: What do you want to be remembered for?\n"
    )
    ANSWER = (
        "---\n"
        'title: "Question E3"\n'
        'answered_date: "{date}"\n'
        "---\n\n"
        "# Question E3: How do you define success today?\n\n"
        "Success means my kids feel safe and I built something real.\n"
    )

    def _setup(self, tmp, answered_days_ago):
        bank = Path(tmp) / "question-bank.md"
        bank.write_text(self.BANK, encoding="utf-8")
        answers = Path(tmp) / "answers"
        answers.mkdir()
        answered = (datetime.now(timezone.utc) - timedelta(days=answered_days_ago)).date().isoformat()
        (answers / "E3.md").write_text(self.ANSWER.format(date=answered), encoding="utf-8")
        perennials = Path(tmp) / "perennials.json"
        live_core = sys.modules["lifehug_core"]  # call-time import target
        self._live_core = live_core
        self._orig = (qc.QUESTIONS_FILE, qc.PERENNIALS_FILE, live_core.ANSWERS_DIR)
        qc.QUESTIONS_FILE = bank
        qc.PERENNIALS_FILE = perennials
        live_core.ANSWERS_DIR = answers
        return bank

    def _teardown(self):
        qc.QUESTIONS_FILE, qc.PERENNIALS_FILE, self._live_core.ANSWERS_DIR = self._orig

    def test_due_perennial_generates_reask_with_excerpt(self):
        with tempfile.TemporaryDirectory() as tmp:
            bank = self._setup(tmp, answered_days_ago=400)
            try:
                qc.add_perennial("E3")
                created = qc.generate_due_perennials()
                self.assertEqual(len(created), 1)
                new_id, source = created[0]
                self.assertEqual(source, "E3")
                text = bank.read_text(encoding="utf-8")
                self.assertIn(f"- [ ] {new_id}:", text)
                self.assertIn("you answered this", text)
                self.assertIn("kids feel safe", text)      # last year's excerpt attached
                self.assertIn("here it is again: How do you define success today?", text)
                # Second run must not double-generate while the re-ask is unanswered
                self.assertEqual(qc.generate_due_perennials(), [])
            finally:
                self._teardown()

    def test_recent_answer_not_due(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._setup(tmp, answered_days_ago=100)
            try:
                qc.add_perennial("E3")
                self.assertEqual(qc.generate_due_perennials(), [])
            finally:
                self._teardown()


class WikiHarvestTests(unittest.TestCase):
    PAGE = (
        "---\ntitle: \"Dad\"\ntype: person\n---\n\n# Dad\n\nBody.\n\n"
        "## Open Questions\n"
        "- What did Dad mean in the author's life?\n"                          # boilerplate → skipped
        "- What would Dave have asked his father in the truck if he'd known it was the last long drive?\n"
        "\n## Sources\n- x\n"
    )

    def test_harvest_skips_boilerplate_keeps_real(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "wiki" / "people").mkdir(parents=True)
            (root / "wiki" / "people" / "dad.md").write_text(self.PAGE, encoding="utf-8")
            bank = root / "bank.md"
            bank.write_text("## A: Origins\n- [ ] A1: What's your earliest memory?\n", encoding="utf-8")
            live_core = sys.modules["lifehug_core"]  # call-time import target
            orig = (live_core.REPO_DIR, qc.QUESTIONS_FILE)
            live_core.REPO_DIR = root
            qc.QUESTIONS_FILE = bank
            try:
                harvested = qc.harvest_wiki_questions(dry_run=True)
            finally:
                live_core.REPO_DIR, qc.QUESTIONS_FILE = orig
            self.assertEqual(len(harvested), 1)
            self.assertTrue(harvested[0].startswith("cand-wiki-dad-"))


class TimelineTests(unittest.TestCase):
    def test_timeline_compiles_from_events(self):
        wc = load("wiki_compile")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state" / "classifications"
            state.mkdir(parents=True)
            (state / "answers-a4.json").write_text(json.dumps({
                "source_path": "answers/A4.md",
                "events": [{"description": "Moved the young family to Seattle",
                            "when_hint": "when James had just been born",
                            "anchor": "James's birth"}],
            }), encoding="utf-8")
            wiki = root / "wiki"
            wiki.mkdir()
            orig = (wc.STATE_DIR, wc.WIKI_DIR)
            wc.STATE_DIR = root / "state"
            wc.WIKI_DIR = wiki
            try:
                self.assertTrue(wc.compile_timeline())
            finally:
                wc.STATE_DIR, wc.WIKI_DIR = orig
            text = (wiki / "timeline.md").read_text(encoding="utf-8")
            self.assertIn("Moved the young family to Seattle", text)
            self.assertIn("when James had just been born", text)
            self.assertIn("anchor: James's birth", text)

    def test_no_events_no_page(self):
        wc = load("wiki_compile")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "state").mkdir()
            orig = wc.STATE_DIR
            wc.STATE_DIR = root / "state"
            try:
                self.assertFalse(wc.compile_timeline())
            finally:
                wc.STATE_DIR = orig


class ClassifierSchemaTests(unittest.TestCase):
    def test_prompt_carries_craft_rules_and_new_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "story.md"
            src.write_text("body", encoding="utf-8")
            prompt = cls.build_prompt(src, {"title": "t", "type": "unprompted_story"}, "Story text.")
        for needle in ("Two-sentence rule", "scene_slots", "situation_vs_story",
                       "events", "defer", "never mentioned to anyone",
                       "what_it_says_about_me"):
            self.assertIn(needle, prompt)

    def test_classification_record_carries_new_fields(self):
        record = cls.build_classification(
            Path("answers/A1.md"), {}, {
                "scene_slots": {"what_happened": True},
                "situation_vs_story": "balanced",
                "events": [{"description": "d", "when_hint": None, "anchor": None}],
            }, "model", "now", [])
        self.assertEqual(record["scene_slots"], {"what_happened": True})
        self.assertEqual(record["situation_vs_story"], "balanced")
        self.assertEqual(len(record["events"]), 1)


class ArtifactVoiceTests(unittest.TestCase):
    def test_voice_preservation_in_artifact_prompt(self):
        art = load("artifact")
        prompt = art.build_prompt(
            {"title": "t", "format": "letter", "subject": "Mom"}, "CONTEXT")
        self.assertIn("VOICE PRESERVATION", prompt)
        self.assertIn("never rewritten", prompt)
        self.assertIn("COMPOSE, don't summarize", prompt)


if __name__ == "__main__":
    unittest.main()
