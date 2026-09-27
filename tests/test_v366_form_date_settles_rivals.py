"""v366 (owner, 2026-09-27): a date saved on the person form SETTLES its rivals.

"I've tried to edit the Harvey birthday many times and it seems to say it's
filed but doesn't work." His Born of 2021-10-11 filed, and the Cornerstones
grid kept its ⚠ because the roster's "2020" reading came from a source the
form never retired. And the ruling: the row's pencil opens the form, and
saving a date there IS the settlement
(`landmark_edit.A_FORM_DATE_SETTLES_ITS_RIVALS`).

Every record is synthetic; nothing here reads a real vault.
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import landmark_edit as le  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import test_v360_edit_forms as forms  # noqa: E402

HARVEY_FORM = {"mode": "save", "person_ref": "person/harvey", "name": "Harvey",
               "category": "child", "relation_word": "Son", "born": "2021-10-11"}


def seeded(*, family_reading: str, children: list[dict] | None = None) -> tuple[dict, dict]:
    """The roster says Harvey was born ``family_reading`` (a ``family``
    landmark entry, the shape the owner's roster import filed), and his
    ``children`` entry says 2021-10-11."""
    roster = copy.deepcopy(forms.ROSTER)
    roster["entities"].append({"name": "Harvey", "slug": "harvey", "relationship": "child",
                               "source": "landmark:family", "born": forms.when(family_reading)})
    seed = copy.deepcopy(forms.SEED)
    seed["family"].append({"domain": "family", "label": "Harvey", "who": "Harvey",
                           "relation": "child", "date": forms.when(family_reading)})
    seed["children"] = children if children is not None else [
        {"domain": "children", "label": "Harvey Rex Taylor", "who": "Harvey Rex Taylor",
         "date": forms.when("2021-10-11")}]
    return roster, seed


class _Vault(forms.FormVault):
    FAMILY_READING = "2020"
    CHILDREN: list[dict] | None = None

    def setUp(self) -> None:
        roster, seed = seeded(family_reading=self.FAMILY_READING, children=self.CHILDREN)
        with mock.patch.object(forms, "ROSTER", roster), mock.patch.object(forms, "SEED", seed):
            super().setUp()
        pub.publish(self.vault, now=forms.NOW, full=True)

    def harvey(self) -> dict:
        view = self.projection().get("cornerstones_view") or {}
        return next(p for g in view.get("groups") or () for p in g["people"]
                    if p["person_ref"] == "person/harvey")

    def cards(self) -> list[dict]:
        return [w for w in self.projection().get("work_items") or ()
                if w.get("kind") == "contradiction" and "Harvey" in str(w.get("prompt_intent"))]


class HarveysBirthdayTests(_Vault):
    """His case: the roster says 2020, the landmark says 2021-10-11, he saves
    2021-10-11."""

    def test_saving_his_date_leaves_one_value_and_no_card(self) -> None:
        result = le.edit_person(self.vault, HARVEY_FORM)
        born = self.harvey()["born"]
        self.assertEqual((born["value"], born["status"]), ("2021-10-11", "exact"))
        self.assertIsNone(born["play"])
        self.assertEqual(self.cards(), [])
        self.assertTrue(result["settled_claims"])
        self.assertEqual(self.roster()["harvey"]["born"]["best"], "2021-10-11")

    def test_the_rival_is_superseded_not_deleted(self) -> None:
        result = le.edit_person(self.vault, HARVEY_FORM)
        index = ts.fold_active_index(self.vault)
        rows = {row["claim_id"]: row for row in index["claims"]}
        for claim_id in result["settled_claims"]:
            self.assertEqual(rows[claim_id]["status"], "superseded")
            self.assertEqual(rows[claim_id]["temporal_value"]["best"], "2020")
        # The source the 2020 reading came from is still on disk.
        self.assertTrue(any("Harvey" in p.read_text() and "2020" in p.read_text()
                            for p in self.sources()))

    def test_undo_reinstates_the_rival(self) -> None:
        result = le.edit_person(self.vault, HARVEY_FORM)
        le.edit_person(self.vault, {"mode": "undo", "corrections": result["corrections"]})
        active = {row["claim_id"] for row in ts.active_claims(ts.fold_active_index(self.vault))}
        self.assertTrue(set(result["settled_claims"]) <= active)

    def test_the_same_save_again_settles_nothing_more(self) -> None:
        le.edit_person(self.vault, HARVEY_FORM)
        again = le.edit_person(self.vault, HARVEY_FORM)
        self.assertNotIn("settled_claims", again)
        self.assertEqual(self.cards(), [])


class AnOpenCardTests(_Vault):
    """The live shape: both readings already on ONE node, the ⚠ already shown."""

    CHILDREN = [{"domain": "children", "label": "Harvey", "who": "Harvey",
                 "date": forms.when("2021-10-11")}]

    def test_the_card_that_was_open_closes(self) -> None:
        self.assertEqual(self.harvey()["born"]["status"], "disagreement")
        self.assertTrue(self.cards())
        le.edit_person(self.vault, HARVEY_FORM)
        self.assertEqual(self.harvey()["born"]["status"], "exact")
        self.assertEqual(self.cards(), [])


class AnAgreeingReadingTests(_Vault):
    """A coarser reading that fits ("2021") is evidence, never a rival."""

    FAMILY_READING = "2021"

    def test_an_agreeing_reading_is_kept(self) -> None:
        result = le.edit_person(self.vault, HARVEY_FORM)
        self.assertNotIn("settled_claims", result)
        self.assertEqual(self.harvey()["born"]["value"], "2021-10-11")
        self.assertEqual(self.cards(), [])


class TheRuleTests(unittest.TestCase):

    def test_the_rule_is_named(self) -> None:
        self.assertIn("settles", le.A_FORM_DATE_SETTLES_ITS_RIVALS)
        self.assertIn("A_FORM_DATE_SETTLES_ITS_RIVALS", le.__all__)


if __name__ == "__main__":
    unittest.main()
