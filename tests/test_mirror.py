"""Tests for the Mirror (v100): entry loading, section contract, keyless
emit/from-response roundtrip, and the viewer/home integration."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import mirror  # noqa: E402
import serve_wiki  # noqa: E402


GOOD_BODY = """## Tensions I keep circling

- You've said possessions never mattered (source: A10) and you've described
  the ache of not having what other kids had (source: A10). What do both
  truths protect?

## What I seem to know about myself

- You've written that safety came from your mother's face up close (source: A1).

## Stated positions

- position: the mantle of responsibility is meant to be worn (source: mantle).

## Sit with

- You've called the memory a feeling more than a picture (source: A11) — what
  else do you remember with your body first?
- Relationships outrank possessions (source: A10) — where does that get hard?
- The mantle is worn, not natural (source: mantle) — who taught you the weight?
"""


class MirrorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._saved = {
            (mirror, "CLASSIFICATIONS_DIR"): mirror.CLASSIFICATIONS_DIR,
            (mirror, "WIKI_DIR"): mirror.WIKI_DIR,
            (mirror, "MIRROR_RESPONSES_FILE"): mirror.MIRROR_RESPONSES_FILE,
            (serve_wiki, "CLASSIFICATIONS_DIR"): serve_wiki.CLASSIFICATIONS_DIR,
            (serve_wiki, "WIKI_DIR"): serve_wiki.WIKI_DIR,
        }
        mirror.CLASSIFICATIONS_DIR = self.tmp / "classifications"
        mirror.WIKI_DIR = self.tmp / "wiki"
        mirror.MIRROR_RESPONSES_FILE = self.tmp / "mirror_responses.json"
        serve_wiki.CLASSIFICATIONS_DIR = mirror.CLASSIFICATIONS_DIR
        serve_wiki.WIKI_DIR = mirror.WIKI_DIR

    def tearDown(self):
        for (mod, name), val in self._saved.items():
            setattr(mod, name, val)

    def _classification(self, name, **kwargs):
        d = self.tmp / "classifications"
        d.mkdir(parents=True, exist_ok=True)
        payload = {"source_path": kwargs.pop("source_path", f"answers/{name}.md"),
                   "classified_at": kwargs.pop("classified_at", "2026-07-01T00:00:00Z")}
        payload.update(kwargs)
        (d / f"{name}.json").write_text(json.dumps(payload))

    # --- entry loading ---

    def test_load_entries_kinds_and_dedupe(self):
        self._classification(
            "answers-a1",
            contradictions=["Ache and dismissal coexist.", "Ache and dismissal coexist."],
            self_understanding_insights=[
                "Core value: people over things.",
                "position: the mantle is worn, not natural.",
            ])
        self._classification(
            "answers-a2", classified_at="2026-07-05T00:00:00Z",
            contradictions=["Ache and dismissal coexist."],  # cross-file dupe
            self_understanding_insights=["POSITION: caps still count."])
        entries = mirror.load_mirror_entries()
        kinds = sorted(e["kind"] for e in entries)
        self.assertEqual(kinds, ["contradiction", "insight", "position", "position"])
        # Newest classification sorts first.
        self.assertEqual(entries[0]["classified_at"], "2026-07-05T00:00:00Z")
        # Source stems travel with each entry.
        self.assertEqual({e["source_short"] for e in entries},
                         {"answers-a1", "answers-a2"})

    def test_load_entries_empty_dir(self):
        self.assertEqual(mirror.load_mirror_entries(), [])

    # --- Mirror inbound (issue #119) ---

    def test_load_mirror_entries_includes_responses_alongside_classifications(self):
        self._classification("answers-a1", contradictions=["Ache and dismissal coexist."])
        mirror.append_mirror_responses([{
            "session_id": "conv-20260816-210400-abcdef",
            "text": "I keep circling back to this and I think it's fine now.",
            "tension_ref": "Sit with: the mantle you wear",
            "responded_at": "2026-08-16T21:04:00Z",
        }])
        entries = mirror.load_mirror_entries()
        kinds = sorted(e["kind"] for e in entries)
        self.assertEqual(kinds, ["contradiction", "response"])
        response = next(e for e in entries if e["kind"] == "response")
        self.assertEqual(response["text"], "I keep circling back to this and I think it's fine now.")
        self.assertEqual(response["source"], "conversation:conv-20260816-210400-abcdef")
        self.assertEqual(response["source_short"], "conv-20260816-210400-abcdef")
        self.assertEqual(response["classified_at"], "2026-08-16T21:04:00Z")

    def test_mirror_prompt_gains_response_block_and_never_adjudicates_instruction(self):
        mirror.append_mirror_responses([{
            "session_id": "conv-20260816-210400-abcdef",
            "text": "Still sitting with the mantle line.",
        }])
        prompt = mirror.build_mirror_prompt()
        self.assertIn("Author responses to tensions", prompt)
        self.assertIn("Still sitting with the mantle line.", prompt)
        self.assertIn("never declare the tension", prompt.lower())
        self.assertIn("the author resolves tensions, not you", prompt.lower())

    # --- section contract ---

    def test_validate_good_body(self):
        self.assertEqual(mirror.validate_mirror_body(GOOD_BODY), [])

    def test_validate_rejects_missing_section_and_extra_sit_with(self):
        errors = mirror.validate_mirror_body("## Sit with\n- a\n- b\n- c\n- d\n")
        self.assertTrue(any("missing section" in e for e in errors))
        self.assertTrue(any("max 3" in e for e in errors))

    def test_validate_rejects_frontmatter(self):
        errors = mirror.validate_mirror_body("---\ntitle: x\n---\n" + GOOD_BODY)
        self.assertTrue(any("frontmatter" in e for e in errors))

    def test_strip_fences(self):
        fenced = "```markdown\n## Hello\n```"
        self.assertEqual(mirror._strip_fences(fenced), "## Hello")

    # --- keyless roundtrip ---

    def test_emit_task_and_from_response_roundtrip(self):
        self._classification("answers-a1", contradictions=["Two truths, one porch."])
        out_dir = self.tmp / "agent_tasks" / "mirror"
        self.assertEqual(mirror.emit_task(out_dir), 0)
        manifest = json.loads((out_dir / "manifest.json").read_text())
        self.assertEqual(manifest["task"], "mirror")
        prompt = (out_dir / "mirror.prompt.md").read_text()
        self.assertIn("Two truths, one porch.", prompt)
        self.assertIn("## Sit with", prompt)

        response = out_dir / "mirror.response.md"
        response.write_text(GOOD_BODY)
        self.assertEqual(mirror.from_response(response), 0)
        page = mirror.mirror_page_path()
        self.assertTrue(page.exists())
        text = page.read_text()
        self.assertIn('title: "Mirror"', text)
        self.assertIn("type: self", text)
        self.assertIn("synthesized: true", text)
        self.assertIn("contradictions: 1", text)
        self.assertIn("## Sit with", text)

        # Freshly written edition suppresses re-emission (agent pre-completed).
        out2 = self.tmp / "agent_tasks" / "mirror2"
        self.assertEqual(mirror.emit_task(out2), 0)
        self.assertFalse((out2 / "manifest.json").exists())

    def test_from_response_rejects_contract_violation(self):
        bad = self.tmp / "bad.md"
        bad.write_text("just some prose, no sections")
        self.assertEqual(mirror.from_response(bad), 1)
        self.assertFalse(mirror.mirror_page_path().exists())

    def test_emit_task_no_material(self):
        out_dir = self.tmp / "agent_tasks" / "mirror"
        self.assertEqual(mirror.emit_task(out_dir), 0)
        self.assertFalse((out_dir / "manifest.json").exists())

    # --- viewer + home integration ---

    def test_view_mirror_empty_state(self):
        title, body, wide = serve_wiki.view_mirror()
        self.assertEqual(title, "Mirror")
        self.assertIn("mirror-compile", body)

    def test_view_mirror_renders_synthesis_and_raw_feed(self):
        self._classification("answers-a1", contradictions=["Two truths, one porch."],
                             self_understanding_insights=["position: worn, not natural."])
        mirror.write_mirror_page(GOOD_BODY)
        title, body, _ = serve_wiki.view_mirror()
        self.assertIn("Tensions I keep circling", body)
        self.assertIn("The raw signals", body)
        self.assertIn("Two truths, one porch.", body)
        self.assertIn("Stated positions", body)
        # The page's own H1 is dropped so the view doesn't render two titles.
        self.assertEqual(body.count("<h1>Mirror</h1>"), 1)

    def test_home_sit_with_prefers_mirror(self):
        self._classification("answers-a1", contradictions=["Raw pool line."])
        card = serve_wiki._hub_card_sit_with()
        self.assertIn("Raw pool line.", card["body"])  # fallback pre-synthesis
        mirror.write_mirror_page(GOOD_BODY)
        card = serve_wiki._hub_card_sit_with()
        self.assertEqual(card["title"], "From this week's Mirror")
        self.assertEqual(card["href"], "/views/mirror")
        picks = serve_wiki._sit_with_from_mirror()
        self.assertEqual(len(picks), 3)
        self.assertIn(card["body"], picks)


if __name__ == "__main__":
    unittest.main()
