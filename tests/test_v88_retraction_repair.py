"""v88 — retractions bind to content, not to an id forever (the N10 case).

A retraction filed against a mis-filed source must stop applying when the
target's payload is replaced by a genuine one under the same id. Also covers
the explicit unretract escape hatch, and the Charlee page fixes: witness
accounts attach by witness_slug, and a new Focus gets a first-name alias
derived from its title before the roster knows the person.
"""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


wc = load("wiki_compile")
si = load("source_integrity")


def _item(qid="N10", sha="sha-genuine"):
    return {"id": qid, "source": f"answers/{qid}.md", "body": "iron man",
            "content_sha256": sha, "sensitivity": "family"}


def _retraction(sha_pin="", voided=False):
    return {"id": "retraction:y", "source": "sources/corrections/y.md",
            "kind": "source_retraction", "retracts": "answer:N10",
            "retracts_path": "answers/N10.md", "retracts_sha256": sha_pin,
            "voided": voided, "suppress_on": [], "corrects": "",
            "corrects_path": "", "body": "reason"}


class ShaPinnedRetractionTests(unittest.TestCase):
    def _retracted(self, item, retraction):
        with mock.patch.object(wc, "_RETRACTIONS", [retraction]):
            return wc._is_retracted(item, "charlee-joy-taylor")

    def test_pinned_retraction_ignores_replaced_content(self):
        # The retraction was filed against the mis-filed letter; the genuine
        # answer later replaced it under the same id.
        self.assertFalse(self._retracted(_item(sha="sha-genuine"),
                                         _retraction(sha_pin="sha-misfiled-letter")))

    def test_pinned_retraction_suppresses_matching_content(self):
        self.assertTrue(self._retracted(_item(sha="sha-misfiled-letter"),
                                        _retraction(sha_pin="sha-misfiled-letter")))

    def test_legacy_unpinned_retraction_still_applies(self):
        self.assertTrue(self._retracted(_item(), _retraction(sha_pin="")))

    def test_voided_retraction_never_applies(self):
        self.assertFalse(self._retracted(_item(sha="sha-misfiled-letter"),
                                         _retraction(sha_pin="sha-misfiled-letter", voided=True)))


class UnretractTests(unittest.TestCase):
    def _write_retraction(self, tmp, voided_line=""):
        path = tmp / "retraction.md"
        path.write_text(
            "---\n"
            'title: "Retraction for N10"\n'
            'type: "source_retraction"\n'
            'source_id: "retraction:retraction"\n'
            'retracts: "answer:N10"\n'
            f"{voided_line}"
            "---\n\n# Retraction for N10\n\nwrong reason\n",
            encoding="utf-8")
        return path

    def test_unretract_voids_the_record(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        path = self._write_retraction(tmp)
        with mock.patch.object(si, "register_source", lambda p: {}):
            si.unretract(path, "targeted the mis-filed letter")
        text = path.read_text(encoding="utf-8")
        self.assertIn("voided: true", text)
        self.assertIn("voided_reason:", text)
        self.assertIn("wrong reason", text)  # original payload preserved

    def test_unretract_rejects_non_retractions(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        path = tmp / "story.md"
        path.write_text('---\ntype: "unprompted_story"\n---\n\nbody\n', encoding="utf-8")
        with self.assertRaises(ValueError):
            si.unretract(path, "nope")

    def test_unretract_rejects_double_void(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        path = self._write_retraction(tmp, "voided: true\n")
        with self.assertRaises(ValueError):
            si.unretract(path, "again")


class NewRetractionPinsShaTests(unittest.TestCase):
    def test_create_linked_source_records_target_sha(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        target = tmp / "N10.md"
        target.write_text('---\ntype: "prompted_answer"\nsource_id: "answer:N10"\n---\n\n# Q\n\niron man\n',
                          encoding="utf-8")
        with mock.patch.object(si, "CORRECTION_SOURCES_DIR", tmp / "corrections"), \
                mock.patch.object(si, "resolve_source_target", lambda v: target), \
                mock.patch.object(si, "register_source", lambda p: {}):
            path = si.create_linked_source(
                "answers/N10.md", "misfiled", source_type="source_retraction",
                title=None, source_medium="manual")
        text = path.read_text(encoding="utf-8")
        self.assertIn("retracts_sha256:", text)
        expected = si.source_record(target)["content_sha256"]
        self.assertIn(expected, text)


class AnswerBodyDividerTests(unittest.TestCase):
    """v89: the --- divider before a generated follow-up section must not
    swallow the answer text (N10's Iron Man moment compiled as its
    follow-up list)."""

    def test_body_before_followup_divider_is_kept(self):
        import lifehug_core
        content = ("---\ntype: \"prompted_answer\"\n---\n\n"
                   "# Question N10: What does she say?\n\n"
                   "one time Charlee said that I'm like Iron Man\n\n---\n\n"
                   "## Follow-up Questions Generated\n- N10b: \"iron-man\"\n")
        body = lifehug_core.answer_body(content)
        self.assertIn("Iron Man", body)
        self.assertNotIn("Follow-up", body)


class CharleePageFixTests(unittest.TestCase):
    def test_first_name_alias_from_focus_title(self):
        self.assertEqual(wc._first_name_alias("Charlee Joy Taylor"), "Charlee")
        self.assertEqual(wc._first_name_alias("The Problem"), "")
        self.assertEqual(wc._first_name_alias("Etherfuse"), "")
        self.assertEqual(wc._first_name_alias("My 20s"), "")

    def test_witness_items_attach_by_slug(self):
        manual = {
            "manual:letter": {"id": "manual:letter", "source": "sources/manual/letter.md",
                              "kind": "witness_account", "witness": "Charlee",
                              "witness_slug": "charlee-joy-taylor", "body": "Happy Fathers day Dad"},
            "manual:other": {"id": "manual:other", "source": "sources/manual/other.md",
                             "kind": "unprompted_story", "witness_slug": "", "body": "x"},
        }
        manual["manual:letter"]["witness_slug"] = "charlee"  # first-name slug, the common case
        names = ["Charlee Joy Taylor", "Charlee"]
        hits = wc._witness_items(manual, names)
        self.assertEqual([h["id"] for h in hits], ["manual:letter"])
        self.assertEqual(wc._witness_items(manual, ["Someone Else"]), [])


if __name__ == "__main__":
    unittest.main()
