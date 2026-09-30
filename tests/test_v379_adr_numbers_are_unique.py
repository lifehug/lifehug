"""v379: ADR numbers are unique (docs only). All data is synthetic.

ADR 0039 named two rulings: v375's re-key ADR
(``docs/adr/0039-a-re-key-is-not-a-change-to-a-life.md``, merged first, keeps
0039) and v378's ring-is-a-target ADR (``docs/adr/0039-the-ring-is-a-target.md``,
merged later), both ratified the same day. Nothing checked that a file's
4-digit prefix was actually distinct before it landed on disk, so the
collision shipped in v378 and was only caught by inspection; this fixes the
duplicate (the ring ADR is renumbered to 0040) and adds the regression test
CI should have had from the start — that every ``docs/adr/`` file (besides
the numberless ``TEMPLATE.md``) carries a distinct 4-digit prefix, and that
prefix is the leading four characters of its filename.
"""

from __future__ import annotations

import re
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADR_DIR = ROOT / "docs" / "adr"

NUMBERED_ADR = re.compile(r"^(\d{4})-[a-z0-9-]+\.md$")


class TestAdrNumbersAreUnique(unittest.TestCase):
    def test_every_adr_file_has_a_four_digit_prefix(self) -> None:
        for path in sorted(ADR_DIR.glob("*.md")):
            if path.name == "TEMPLATE.md":
                continue
            self.assertRegex(
                path.name,
                NUMBERED_ADR,
                f"{path.name} does not match NNNN-slug.md",
            )

    def test_adr_prefixes_are_distinct(self) -> None:
        prefixes = []
        for path in sorted(ADR_DIR.glob("*.md")):
            if path.name == "TEMPLATE.md":
                continue
            match = NUMBERED_ADR.match(path.name)
            self.assertIsNotNone(match, f"{path.name} does not match NNNN-slug.md")
            prefixes.append(match.group(1))

        counts = Counter(prefixes)
        duplicates = {number: count for number, count in counts.items() if count > 1}
        self.assertEqual(
            duplicates,
            {},
            f"docs/adr/ has duplicate ADR numbers: {duplicates} "
            "(ADR 0039 named two ADRs before v379 fixed it — see "
            "docs/adr/0040-the-ring-is-a-target.md)",
        )

    def test_the_v378_v379_split_is_resolved(self) -> None:
        rekey = ADR_DIR / "0039-a-re-key-is-not-a-change-to-a-life.md"
        ring = ADR_DIR / "0040-the-ring-is-a-target.md"
        stale_ring_number = ADR_DIR / "0039-the-ring-is-a-target.md"

        self.assertTrue(rekey.exists(), rekey)
        self.assertTrue(ring.exists(), ring)
        self.assertFalse(stale_ring_number.exists(), stale_ring_number)

        self.assertIn("# ADR 0039:", rekey.read_text(encoding="utf-8"))
        self.assertIn("# ADR 0040:", ring.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
