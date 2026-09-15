"""Synthetic, offline regressions for #335/#336 through the actual recorder."""

from __future__ import annotations

import copy
import unittest

import entity_roster
import episode_binder as eb
import identity_resolution as ir
import landmark_offer as lo
import roster_relations as rr
import temporal_store as ts
from test_landmark_offer import NOW, OfferVaultCase, ScriptedCall, read_dates, read_unit, reading
from test_place_containment import moment_claim, year


def house(nickname="Moonstone", address="14 Willow Lane", start="1990", end="1992",
          *, place_ref=None):
    dates = f"Dates: {start} - {end}" if start else "We stayed here."
    text = (f"{dates}\nNickname: {nickname}\nCity: Riverbend\nAddress: {address}\n"
            "Link: https://example.invalid/home")
    names = {"nickname": nickname, "city": "Riverbend", "address": address,
             "link": "https://example.invalid/home"}
    if place_ref:
        names["place_ref"] = place_ref
    unit = read_unit("u1", "residences", nickname, dates,
                     record={"city": "Riverbend", "label": nickname}, names=names,
                     dates=read_dates(start, end) if start else None)
    unit["name_evidence"] = {key: {"quote": value, "occurrence": 1}
                             for key, value in names.items() if key != "place_ref"}
    return text, reading(units=[unit])


class AttributeCoverageTests(unittest.TestCase):
    def propose(self, text, completion):
        return lo.propose(text, call=ScriptedCall(reading=completion), generation=32,
                          landmarks={}, roster=[], write=False, now=NOW)

    def leftovers(self, proposal):
        return "\n".join(row["text"] for key in ("stories", "unrecognized")
                         for row in proposal[key])

    def test_separate_fields_are_owned_and_fully_covered(self):
        text, completion = house()
        proposal = self.propose(text, completion)
        self.assertEqual(self.leftovers(proposal), "")
        evidence = proposal["units"][0]["name_evidence"]
        self.assertEqual(set(evidence), {"nickname", "city", "address", "link"})
        for row in evidence.values():
            self.assertEqual(text[row["offset"]:row["offset"] + row["length"]], row["text"])
        self.assertEqual(lo.lint_offer_proposal(proposal), [])

    def test_value_evidence_never_hides_trailing_prose(self):
        text, completion = house()
        text = text.replace("Nickname: Moonstone", "Nickname: Moonstone; an unrelated memory remains")
        proposal = self.propose(text, completion)
        self.assertIn("an unrelated memory remains", self.leftovers(proposal))
        self.assertNotIn("Nickname: Moonstone", self.leftovers(proposal))
        self.assertEqual(lo.lint_offer_proposal(proposal), [])

    def test_overbroad_proposed_evidence_quote_is_rejected(self):
        text, completion = house()
        overbroad = "Nickname: Moonstone; an unrelated memory remains"
        text = text.replace("Nickname: Moonstone", overbroad)
        completion["units"][0]["name_evidence"]["nickname"]["quote"] = overbroad
        proposal = self.propose(text, completion)
        self.assertNotIn("nickname", proposal["units"][0]["name_evidence"])
        self.assertIn(overbroad, self.leftovers(proposal))

    def test_repeated_values_need_an_explicit_occurrence(self):
        text, completion = house()
        text += "\nMoonstone was also the name of a painting."
        completion["units"][0]["name_evidence"]["nickname"].pop("occurrence")
        proposal = self.propose(text, completion)
        self.assertIn("Nickname: Moonstone", self.leftovers(proposal))
        completion["units"][0]["name_evidence"]["nickname"]["occurrence"] = 1
        proposal = self.propose(text, completion)
        self.assertNotIn("Nickname: Moonstone", self.leftovers(proposal))
        self.assertIn("Moonstone was also the name of a painting", self.leftovers(proposal))

    def test_separate_unit_occurrences_are_not_global_value_coverage(self):
        first, completion = house()
        second, other = house("Suncrest", "28 Ash Lane", "2000", "2002")
        second_unit = other["units"][0]
        second_unit["ref"] = "u2"
        for field in ("city", "link"):
            second_unit["name_evidence"][field]["occurrence"] = 2
        completion["units"].append(second_unit)
        proposal = self.propose(first + "\n" + second, completion)
        self.assertEqual(self.leftovers(proposal), "")
        offsets = [u["name_evidence"]["city"]["offset"] for u in proposal["units"]]
        self.assertEqual(len(set(offsets)), 2)
        second_unit["name_evidence"]["city"]["occurrence"] = 1
        proposal = self.propose(first + "\n" + second, completion)
        self.assertTrue(all("city" not in u["name_evidence"] for u in proposal["units"]))
        self.assertIn("City: Riverbend", self.leftovers(proposal))

    def test_normalized_nickname_covers_only_retained_name(self):
        text, completion = house("Moonstone (rented)")
        completion["units"][0]["name_evidence"]["nickname"]["quote"] = "Moonstone"
        proposal = self.propose(text, completion)
        self.assertEqual(proposal["units"][0]["record"]["nickname"], "Moonstone")
        self.assertIn("(rented)", self.leftovers(proposal))
        self.assertEqual(proposal["units"][0]["name_evidence"]["nickname"]["text"], "Moonstone")

    def test_rejected_or_truncated_link_cannot_hide_dropped_text(self):
        for value in ("http://example.invalid/home", "https://example.invalid/" + "a" * 510):
            with self.subTest(value=value[:30]):
                text, completion = house()
                text = text.replace("https://example.invalid/home", value)
                unit = completion["units"][0]
                unit["names"]["link"] = value
                unit["name_evidence"]["link"]["quote"] = value
                proposal = self.propose(text, completion)
                self.assertNotIn("link", proposal["units"][0]["name_evidence"])
                self.assertIn(value, self.leftovers(proposal))

    def test_legacy_reading_is_accepted_without_guessed_coverage(self):
        text, completion = house()
        completion["units"][0].pop("name_evidence")
        proposal = self.propose(text, completion)
        self.assertEqual(proposal["units"][0]["name_evidence"], {})
        self.assertIn("Nickname: Moonstone", self.leftovers(proposal))


class ReadingRevisionTests(OfferVaultCase):
    def test_same_generation_upgrade_keeps_old_document_and_receipt(self):
        text, completion = house()
        legacy = lo.propose(text, self.root, call=ScriptedCall(reading=completion),
                            generation=32, now=NOW, write=False)
        legacy.pop("reading_revision")
        legacy["proposal_id"] = f"{lo.PROPOSAL_ID_PREFIX}:" + lo._digest({
            "text": ts.normalize_payload(text), "generation": 32})
        for unit in legacy["units"]:
            unit.pop("name_evidence")
        lo._save_proposal(self.root, legacy)
        legacy_path = lo.proposal_path(self.root, legacy["proposal_id"])
        legacy_bytes = legacy_path.read_bytes()
        receipt = lo.apply(legacy["proposal_id"], [legacy["units"][0]["unit_id"]], self.root, now=NOW)
        receipt_path = lo.offer_receipt_path(self.root, receipt["receipt_id"])
        receipt_bytes = receipt_path.read_bytes()
        current = lo.propose(text, self.root, call=ScriptedCall(reading=completion),
                             generation=32, now=NOW)
        self.assertNotEqual(current["proposal_id"], legacy["proposal_id"])
        self.assertEqual(lo.proposal_reading_rank(legacy), (32, 1))
        self.assertEqual(lo.proposal_reading_rank(current), (32, 2))
        self.assertFalse(lo.is_current_proposal(legacy, text))
        self.assertTrue(lo.is_current_proposal(current, text, generation=32))
        self.assertEqual(legacy_path.read_bytes(), legacy_bytes)
        self.assertEqual(lo.read_proposal(self.root, current["proposal_id"]), current)
        before = entity_roster.load_roster("place")
        self.assertEqual(lo.apply(legacy["proposal_id"], receipt["unit_ids"], self.root), receipt)
        self.assertEqual(receipt_path.read_bytes(), receipt_bytes)
        self.assertEqual(entity_roster.load_roster("place"), before)
        self.assertNotEqual(receipt["filed"][0]["place_ref"], "place/riverbend")

    def test_current_match_and_request_namespace_are_package_authority(self):
        text, completion = house()
        proposal = lo.propose(text, self.root, call=ScriptedCall(reading=completion),
                             generation=32, now=NOW)
        self.assertTrue(lo.is_current_proposal(proposal, text))
        self.assertFalse(lo.is_current_proposal(proposal, text + " changed"))
        self.assertFalse(lo.is_current_proposal(proposal, text, generation=33))
        for field, value in (("reading_revision", 1), ("reading_revision", "2"),
                             ("vault_generation", True), ("state", "failed"),
                             ("proposal_id", "landmark-proposal:invalid")):
            self.assertFalse(lo.is_current_proposal({**proposal, field: value}, text))
        self.assertEqual(lo.proposal_reading_rank({"vault_generation": 32, "reading_revision": "2"}), (-1, -1))
        original = lo.PROPOSAL_READING_REVISION
        try:
            first = lo.reading_request_key(text)
            lo.PROPOSAL_READING_REVISION += 1
            self.assertNotEqual(lo.reading_request_key(text), first)
            self.assertFalse(lo.is_current_proposal(proposal, text))
        finally:
            lo.PROPOSAL_READING_REVISION = original


class HouseIdentityTests(OfferVaultCase):
    def file_house(self, *args, **kwargs):
        text, completion = house(*args, **kwargs)
        proposal = self.propose(text, ScriptedCall(reading=completion))
        return lo.apply(proposal["proposal_id"], [u["unit_id"] for u in proposal["units"]], self.root, now=NOW)

    def resolve(self, nickname):
        return ir.resolve_mention(nickname, roster=entity_roster.load_roster("place"),
                                  evidence_ref="synthetic:future-story", now=NOW)

    def story(self, nickname, *, date=None, suffix="undated"):
        body = f"We painted the kitchen at {nickname}"
        claim = moment_claim({"source": f"classification:synthetic-{nickname}-{suffix}#painting",
                              "quote": body, "mention": body},
                             temporal_value=year(date) if date else None)
        ts.write_receipt(self.root, {"source_ref": claim["source_ref"],
                                    "extractor_version": "classifier:1", "created_at": NOW,
                                    "claims": [claim]})
        ts.rebuild_active_index(self.root)

    def bind(self):
        return eb.bind_episodes(self.root, apply=True, now=NOW,
                                containment_authority="applied")["plan"]

    def test_two_same_city_houses_resolve_and_bind_undated_stories_separately(self):
        first = self.file_house()
        second = self.file_house("Suncrest", "28 Ash Lane", "2000", "2002")
        refs = [r["filed"][0]["place_ref"] for r in (first, second)]
        self.assertEqual(len(set(refs)), 2)
        for nickname, ref in zip(("Moonstone", "Suncrest"), refs):
            resolution = self.resolve(nickname)
            self.assertEqual(resolution.resolution, "same")
            self.assertEqual(resolution.resolved_ref, ref)
            self.story(nickname)
        plan = self.bind()
        self.assertEqual(len(plan.containers), 2)
        self.assertEqual(len(plan.containments), 2)
        self.assertEqual(plan.containment_ambiguities, [])

    def test_same_house_separate_stays_needs_date_for_stay_not_house(self):
        first = self.file_house()
        second = self.file_house(start="2000", end="2002")
        ref = first["filed"][0]["place_ref"]
        self.assertEqual(second["filed"][0]["place_ref"], ref)
        self.assertEqual(len(self.entries("residences")), 2)
        self.assertEqual(self.resolve("Moonstone").resolved_ref, ref)
        self.story("Moonstone")
        self.story("Moonstone", date="1991", suffix="early")
        self.story("Moonstone", date="2001", suffix="late")
        plan = self.bind()
        self.assertEqual(len(plan.containers), 2)
        self.assertEqual(len(plan.containments), 2)
        self.assertEqual(len(plan.containment_ambiguities), 1)
        self.assertEqual(plan.containment_ambiguities[0]["kind"], "place_ambiguous")
        self.assertEqual(plan.containment_ambiguities[0]["entity"], ref)

    def test_city_ref_does_not_suppress_address_but_individual_ref_is_preserved(self):
        entity_roster.write_roster("place", [{"name": "Riverbend", "slug": "riverbend", "aliases": []}])
        first = self.file_house(place_ref="place/riverbend")
        ref = first["filed"][0]["place_ref"]
        self.assertNotEqual(ref, "place/riverbend")
        second = self.file_house("Renamed House", "An explicitly corrected address", "2000", "2002", place_ref=ref)
        self.assertEqual(second["filed"][0]["place_ref"], ref)

    def test_undated_house_does_not_fabricate_a_stay_date(self):
        receipt = self.file_house(start=None, end=None)
        self.assertEqual(self.resolve("Moonstone").resolved_ref, receipt["filed"][0]["place_ref"])
        entry = self.entries("residences")[0]
        self.assertNotIn("span", entry)
        self.assertNotIn("date", entry)

    def test_colliding_houses_persist_refusal_and_resolver_ambiguity(self):
        first = self.file_house()
        second = self.file_house("Moonstone", "28 Ash Lane", "2000", "2002")
        alias = second["filed_names"][0]["alias"]
        self.assertFalse(alias["applied"])
        self.assertEqual(alias["reason"], rr.IDENTITY_UNCERTAIN_KIND)
        self.assertEqual({c["ref"] for c in alias["candidates"]},
                         {r["filed"][0]["place_ref"] for r in (first, second)})
        self.assertEqual(self.resolve("Moonstone").resolution, "uncertain")
        self.assertEqual(lo.read_offer_receipt(self.root, second["receipt_id"]), second)
        lo.retract(second["receipt_id"], self.root, now=NOW)
        self.assertEqual(self.resolve("Moonstone").resolved_ref, first["filed"][0]["place_ref"])

    def test_legacy_city_alias_is_not_reassigned_or_reported_as_success(self):
        city = {"name": "Riverbend", "slug": "riverbend", "aliases": ["Moonstone"]}
        entity_roster.write_roster("place", [city])
        receipt = self.file_house(place_ref="place/riverbend")
        alias = receipt["filed_names"][0]["alias"]
        self.assertFalse(alias["applied"])
        self.assertEqual(alias["reason"], "identity_uncertain")
        self.assertEqual(self.resolve("Moonstone").resolution, "uncertain")
        self.assertEqual(rr.find_by_ref("place", entity_roster.load_roster("place"), "place/riverbend"), city)
        lo.retract(receipt["receipt_id"], self.root, now=NOW)
        self.assertEqual(self.resolve("Moonstone").resolved_ref, "place/riverbend")

    def test_retracting_one_stay_preserves_alias_until_last_owner(self):
        first = self.file_house()
        second = self.file_house(start="2000", end="2002")
        lo.retract(first["receipt_id"], self.root, now=NOW)
        self.assertEqual(self.resolve("Moonstone").resolved_ref, second["filed"][0]["place_ref"])
        self.assertEqual(len(self.entries("residences")), 1)
        before = copy.deepcopy(entity_roster.load_roster("place"))
        self.assertEqual(lo.apply(first["proposal_id"], first["unit_ids"], self.root), first)
        self.assertEqual(entity_roster.load_roster("place"), before)
        lo.retract(second["receipt_id"], self.root, now=NOW)
        self.assertIsNone(self.resolve("Moonstone").resolved_ref)
        self.assertEqual(self.entries("residences"), [])

    def test_refresh_preserves_houses_alias_owners_and_city_hierarchy(self):
        city = {"name": "Riverbend", "slug": "riverbend", "aliases": ["Moonstone"]}
        entity_roster.write_roster("place", [city])
        first = self.file_house()
        second = self.file_house("Suncrest", "28 Ash Lane", "2000", "2002")
        original = entity_roster.load_roster("place")
        stable_fields = ("name", "slug", "aliases", *rr.PLACE_IDENTITY_FIELDS)
        expected = [{k: e[k] for k in stable_fields if k in e} for e in original["entities"]]
        outputs = [[], [{"name": "Moonstone", "aliases": ["Riverbend", "Suncrest"], "qualifies": True}],
                   [{"name": e["name"], "aliases": ["Moonstone", "Suncrest", "Riverbend"],
                     "slug": "wrong-house", "place_kind": "city", "qualifies": True}
                    for e in reversed(original["entities"])]]
        for raw in outputs:
            with self.subTest(raw=raw):
                folded, _ = entity_roster.apply_previous_decisions(raw, original)
                normalized = entity_roster.normalize("place", folded, [], {}, 0, 0)
                entity_roster.write_roster("place", normalized)
                actual = [{k: e[k] for k in stable_fields if k in e}
                          for e in entity_roster.load_roster("place")["entities"]]
                self.assertEqual(sorted(actual, key=lambda e: e["slug"]),
                                 sorted(expected, key=lambda e: e["slug"]))
                self.assertEqual(self.resolve("Moonstone").resolution, "uncertain")
                self.assertEqual(self.resolve("Suncrest").resolved_ref, second["filed"][0]["place_ref"])
        repeated = self.file_house("Suncrest", "28 Ash Lane", "2010", "2012")
        self.assertEqual(repeated["filed"][0]["place_ref"], second["filed"][0]["place_ref"])
        lo.retract(second["receipt_id"], self.root, now=NOW)
        self.assertEqual(self.resolve("Suncrest").resolved_ref, repeated["filed"][0]["place_ref"])
        self.assertNotEqual(first["filed"][0]["place_ref"], "place/riverbend")


if __name__ == "__main__":
    unittest.main()
