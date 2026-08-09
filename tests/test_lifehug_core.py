import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import lifehug_core


class CoreParsingTests(unittest.TestCase):
    def test_parse_generated_question_ids(self):
        md = """## A: Origins
- [x] A1: First question *(2026-01-01)*
- [ ] A14a: Follow-up question
- [x] G5c: Project follow-up *(pass-2)*
"""
        questions = lifehug_core.parse_questions(md)
        self.assertEqual([q["id"] for q in questions], ["A1", "A14a", "G5c"])
        self.assertEqual(sum(1 for q in questions if q["answered"]), 2)

    def test_coverage_includes_generated_ids(self):
        md = """## A: Origins
- [x] A1: First
- [ ] A1a: Follow-up
"""
        questions = lifehug_core.parse_questions(md)
        categories = lifehug_core.parse_categories(md)
        coverage = lifehug_core.compute_coverage(questions, categories)
        self.assertEqual(coverage["categories"]["A"]["total"], 2)
        self.assertEqual(coverage["categories"]["A"]["answered"], 1)

    def test_answer_body_skips_yaml_frontmatter(self):
        content = """---
title: "Question A1"
source_id: "answer:A1"
---

# Question A1: First

The answer body.
"""
        self.assertEqual(lifehug_core.answer_body(content), "# Question A1: First\n\nThe answer body.")

    def test_answer_body_handles_legacy_answer_with_added_frontmatter(self):
        content = """---
title: "Question A1"
source_id: "answer:A1"
---

# Question A1: First
**Category:** A (Origins) | **Pass:** 1
**Asked:** 2026-01-01 | **Answered:** 2026-01-02
**Source:** voice

---

Legacy answer body.
"""
        self.assertEqual(lifehug_core.answer_body(content), "Legacy answer body.")

    def test_answer_body_keeps_addenda_before_generated_followups(self):
        content = """---
title: "Question A1"
source_id: "answer:A1"
---

# Question A1: First

The first telling.

## Additional Answer 2

**Answered:** 2026-08-08
**Source:** voice
**Captured:** 2026-08-08T12:00:00

The second telling.

---

## Follow-up Questions Generated
- A1a: "What changed?"
"""
        body = lifehug_core.answer_body(content)
        self.assertIn("The first telling.", body)
        self.assertIn("The second telling.", body)
        self.assertNotIn("Follow-up Questions Generated", body)

    def test_learning_failure_log_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "learning_failures.jsonl"
            lifehug_core.record_learning_failure(
                "process_answer",
                "quality_scoring",
                RuntimeError("scorer unavailable"),
                context={"question_id": "A1"},
                exit_code=7,
                path=path,
            )

            rows = lifehug_core.read_learning_failures(path=path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["component"], "process_answer")
            self.assertEqual(rows[0]["operation"], "quality_scoring")
            self.assertEqual(rows[0]["exit_code"], 7)
            self.assertIn("A1", json.dumps(rows[0]["context"]))
            self.assertIn("process_answer/quality_scoring", lifehug_core.format_learning_failure(rows[0]))


class ProcessAnswerTests(unittest.TestCase):
    def test_next_followup_id_uses_letter_suffixes(self):
        spec = importlib.util.spec_from_file_location("process_answer", SYSTEM / "process_answer.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        md = """## B: Becoming
- [x] B9: Base
- [ ] B9a: First follow-up
- [ ] B9b: Second follow-up
"""
        self.assertEqual(mod.next_followup_id(md, "B9"), "B9c")


if __name__ == "__main__":
    unittest.main()
