"""v93 — classify_stem must never exceed the 255-byte filename limit.

A retraction slug embeds the full question text; one real 262-char stem made
classification_path unwritable (keyed path) and emit_prompts crash (keyless
path). Found while verifying v92 on live data.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))


def load(name):
    spec = importlib.util.spec_from_file_location(name, SYSTEM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


cs = load("classify_story")


class StemCapTests(unittest.TestCase):
    def test_short_stem_is_byte_identical_to_historical_value(self):
        # Existing classification files are keyed by the uncapped stem —
        # anything at or under the cap must not change.
        path = cs.REPO_DIR / "answers" / "A1.md"
        self.assertEqual(cs.classify_stem(path), "answers-a1")

    def test_long_stem_is_capped_under_filename_limit(self):
        long_name = "retraction-for-question-" + "-".join(["word"] * 60) + ".md"
        path = cs.REPO_DIR / "sources" / "corrections" / long_name
        stem = cs.classify_stem(path)
        self.assertLessEqual(len(stem), cs.MAX_STEM_LEN + 13)  # cap + "-" + 12-char hash
        self.assertLess(len(stem) + len(".response.json"), 255)

    def test_long_stem_is_stable_and_unique(self):
        base = "sources/corrections/" + "x" * 300
        a = cs.classify_stem(cs.REPO_DIR / (base + "a.md"))
        a2 = cs.classify_stem(cs.REPO_DIR / (base + "a.md"))
        b = cs.classify_stem(cs.REPO_DIR / (base + "b.md"))
        self.assertEqual(a, a2)          # deterministic
        self.assertNotEqual(a, b)        # same truncated prefix, distinct hash

    def test_derived_paths_stay_writable(self):
        long_name = "retraction-" + "q" * 300 + ".md"
        path = cs.REPO_DIR / "sources" / "corrections" / long_name
        clf = cs.classification_path(path)
        self.assertLess(len(clf.name), 255)


if __name__ == "__main__":
    unittest.main()
