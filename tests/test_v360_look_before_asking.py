"""v360 (owner, 2026-09-25) — look before asking.

The owner, on his own timeline (a scratch clone at generation 193, 38 open
`precision_gap` cards, every one a node with NO placement): *"For each of these
questions … if I ask you directly right now, I bet you could answer them, so
I'm wondering why they're not getting answered."* The resolver had never tried
27 of them. Five rules, each guarded here on a synthetic vault with the real
shapes (the real minter, the real fold, the real publication seam):

A. `resolver.LOOK_AT_EVERYTHING_THAT_CAN_BECOME_A_CARD` — a landmark entry with
   no story telling (a residence he named on a ladder) is planned from its own
   record.
B. `identity_resolution.WHAT_HE_CALLS_THEM_DECIDES_A_BARE_NAME` — *"When I talk
   about James, I'm talking about my son … I call my dad Dad and his dad
   Grandpa."* Pinned in the fold here; the resolver rungs in
   `tests/test_v357_a_full_name_outranks_a_shared_first_name.py`.
C. `resolver.A_FAMILY_MOMENT_IS_DATED_FROM_ITS_OWN_PERSON` — his son's moment is
   dated from his son's birth.
D. `temporal_publication.NEVER_ASK_WHAT_WAS_NOT_LOOKED_AT` — a date card is
   drawn only once the resolver looked and asked.
E. `resolver.AN_ESTIMATE_PLACES_AS_THE_SYSTEMS_INFERENCE` — a grounded estimate
   places, as the system's inference, and never over what he said.

Synthetic data only; NEVER references any real vault.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import chronology as chrono  # noqa: E402
import identity_resolution as ir  # noqa: E402
import landmark_projection as lp  # noqa: E402
import resolver  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import temporal_work_items as twi  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

NOW = "2026-09-01T12:00:00Z"
OWNER_BIRTH = "1981-07-11"
SON_BIRTH = "2013-05-10"
SON_REF = "person/james-everett-taylor"

#: The owner's four Jameses, in the roster's own shape (v357's fixture rows).
ROSTER = {"version": 1, "type": "person", "entities": [
    {"name": "James Taylor", "slug": "james-taylor", "relationship": "parent",
     "aliases": ["James Taylor (Dad)", "dad", "my dad", "father"]},
    {"name": "James Edwin Taylor Sr.", "slug": "james-edwin-taylor-sr",
     "relationship": "grandparent", "aliases": ["grandfather", "grandpa"]},
    {"name": "James Everett Taylor", "slug": "james-everett-taylor",
     "relationship": "child", "aliases": []},
    {"name": "Anthon James Taylor", "slug": "anthon-james-taylor",
     "relationship": "sibling", "aliases": ["AJ", "AJ Taylor", "James"]},
    {"name": "James", "slug": "james", "relationship": "sibling", "aliases": [],
     "maps_to_focus": "anthon-james-taylor"},
]}


class _CaseBlind(dict):
    def __getitem__(self, key):
        return super().__getitem__(str(key).lower())

    def get(self, key, default=None):
        return super().get(str(key).lower(), default)

    def __contains__(self, key):
        return super().__contains__(str(key).lower())


class Vault:
    """One synthetic vault: stories with real claims, a roster, a publish."""

    def __init__(self, case: unittest.TestCase) -> None:
        self.root = root_parent_tmp(case, ROOT, prefix="lookfirst-")
        (self.root / "answers").mkdir(parents=True)
        (self.root / "state" / "temporal_claims").mkdir(parents=True)
        self.n = 0

    def roster(self, snapshot: dict = ROSTER) -> None:
        folder = self.root / "state" / "entity_rosters"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "person.json").write_text(json.dumps(snapshot), "utf-8")

    def claim(self, stem: str, body: str, *, label: str, claim_type: str = "occurrence",
              subject: str = "self", value: object = None, basis: str = "explicit",
              event_kind: str = "moment", quote: str = "", event_ref: str = "") -> dict:
        """One story file (kept if it exists) plus one classifier claim on it."""
        path = self.root / "answers" / f"{stem}.md"
        if not path.exists():
            path.write_text(f"---\ntitle: {stem}\ntype: prompted_answer\n---\n\n{body}\n", "utf-8")
        self.n += 1
        node_id = event_ref or tp.derive_node_id(node_kind="event", event_kind=event_kind,
                                                 subject_refs=[subject], discriminator=f"{stem}-{label}")
        row = {
            "source_kind": "import", "claim_type": claim_type, "subject_mention": subject,
            "event_kind": event_kind, "event_ref": node_id, "event_mention": label,
            "evidence": [{"quote": quote or body[:80]}], "basis": basis, "confidence": 0.8,
            "extractor_version": "classifier-claims/rule:5",
            "source_ref": {"source_id": f"classification:answers-{stem}#{tc.digest_id('t', label)[-12:]}",
                           "revision": "sha256:" + f"{self.n:064x}", "source_path": f"answers/{stem}.md"},
        }
        if value is not None:
            row["temporal_value"] = value
        claim = tc.validate_temporal_claim(row, now=NOW)
        ts.write_receipt(self.root, {"source_ref": claim["source_ref"],
                                     "extractor_version": "classifier-claims/rule:5",
                                     "claims": [claim]}, now=NOW)
        return claim

    def owner_birth(self) -> None:
        self.claim("birth", f"I was born on {OWNER_BIRTH}.", label="my birth", claim_type="date",
                   value=chrono.parse_stated_date(OWNER_BIRTH).to_dict(), event_kind="birth")

    def son_birth(self) -> None:
        self.claim("son-birth", f"James Everett Taylor was born {SON_BIRTH}.",
                   label="James Everett Taylor's birth", claim_type="date",
                   subject="James Everett Taylor",
                   value=chrono.parse_stated_date(SON_BIRTH).to_dict(), event_kind="birth")

    def his_words(self) -> None:
        """How he refers to the other three Jameses, in his own tellings."""
        for n, text in enumerate(("My dad drove us to the lake.", "Grandpa taught me to fish.",
                                  "AJ and I built the ramps."), start=1):
            self.claim(f"words{n}", text, label=f"telling {n}")

    def publish(self) -> dict:
        return pub.publish(self.root, now=NOW)

    def nodes(self) -> dict:
        # Titles are sentence-cased since the wording change; look them up case-blind.
        return _CaseBlind({str(node["label"]).lower(): node for node in (pub.read_projection(self.root) or {})["nodes"]})

    def cards(self) -> list[dict]:
        return list((pub.read_work_items(self.root) or {})["work_items"])

    def ledger(self, rows: dict) -> None:
        resolver.save_ledger(self.root, {"version": 1, "nodes": rows})


def envelope(item: dict, answers: list[dict]) -> dict:
    return {"schema_version": 1, "model": "test-model", "items": [{
        **{k: item[k] for k in ("key", "source_path", "node_ids", "identity")},
        "include_paths": item.get("include_paths") or [],
        "text": json.dumps({"answers": answers}), "usage": {}, "truncated": False}]}


def unknown(node_id: str, **fields) -> dict:
    row = {"node_id": node_id, "answer": None, "basis": "inferred", "confidence": 0.3,
           "fact_key": "x", "citations": [], "reason": "cannot tell",
           "question": "Roughly which year was this?", "also_resolves": []}
    row.update(fields)
    return row


# --------------------------------------------------------------------------
# A — look at everything that can become a card
# --------------------------------------------------------------------------


class ALandmarkEntryIsLookedAtTests(unittest.TestCase):

    def setUp(self):
        self.vault = Vault(self)
        self.vault.owner_birth()
        (self.vault.root / "state").mkdir(exist_ok=True)
        lp.file_landmark_record(self.vault.root, "residences",
                                {"domain": "residences", "label": "Mesa, Arizona", "city": "Mesa"},
                                ordinal=1, now=NOW)
        ts.rebuild_active_index(self.vault.root)
        self.vault.publish()

    def test_the_undated_residence_entry_is_planned_from_its_own_record(self):
        node = self.vault.nodes()["Mesa, Arizona"]
        self.assertFalse(node.get("usable_placement"))
        read = resolver._Read(self.vault.root)
        self.assertIn(node["node_id"], read.by_node, "a ladder entry must be looked at")
        source, target = read.by_node[node["node_id"]]
        self.assertTrue(source.startswith("sources/landmarks/"))
        self.assertIn("the person's own ladder entry: city Mesa", target["event"]["description"])

    def test_the_old_rule_left_it_unplanned(self):
        """The defect reproduced: without the landmark-entry exception, a
        residence is never a target however long it sits carded."""
        original = resolver._is_landmark_entry_node
        resolver._is_landmark_entry_node = lambda *a, **k: False
        try:
            read = resolver._Read(self.vault.root)
        finally:
            resolver._is_landmark_entry_node = original
        self.assertNotIn(self.vault.nodes()["Mesa, Arizona"]["node_id"], read.by_node)

    def test_an_estimate_never_places_a_residence(self):
        node_id = self.vault.nodes()["Mesa, Arizona"]["node_id"]
        item = resolver.plan_items(self.vault.root, limit=5)["items"][0]
        resolver.file_envelope(self.vault.root, envelope(item, [unknown(node_id, estimate={
            "earliest": "1995", "latest": "1998", "confidence": 0.5,
            "basis": [{"kind": "residence", "text": "the Arizona years"}]})]), now=NOW)
        row = resolver.load_ledger(self.vault.root)["nodes"][node_id]
        self.assertEqual(row["estimate_not_placed"], "residence")
        self.assertFalse(self.vault.nodes()["Mesa, Arizona"].get("usable_placement"))


# --------------------------------------------------------------------------
# B + C — a bare James is his son, dated from his son's birth
# --------------------------------------------------------------------------


class BareJamesIsHisSonTests(unittest.TestCase):

    def setUp(self):
        self.vault = Vault(self)
        self.vault.roster()
        self.vault.owner_birth()
        self.vault.son_birth()
        self.ducks = self.vault.claim(
            "ducks", "James, at two, chasing ducks from the rowboat.",
            label="James's duck-chasing rowboat antics", claim_type="age", subject="James",
            value={"low": 2, "high": 2, "unit": "years"}, quote="James, at two, chasing ducks")

    def test_without_his_words_the_bare_name_still_asks(self):
        self.vault.publish()
        node = self.vault.nodes()["James's duck-chasing rowboat antics"]
        self.assertNotIn(SON_REF, node["subject_refs"])
        self.assertIsNone(node.get("best_temporal_value"))

    def test_with_his_words_it_is_his_son_at_two(self):
        self.vault.his_words()
        self.vault.publish()
        node = self.vault.nodes()["James's duck-chasing rowboat antics"]
        self.assertEqual(node["subject_refs"], [SON_REF])
        best = node["best_temporal_value"]
        self.assertEqual((best["earliest"], best["latest"], best["basis"]), ("2015-05", "2016-05", "age"))
        self.assertFalse(any(card["kind"] == "identity_uncertain" for card in self.vault.cards()))


class AFamilyMomentIsDatedFromItsOwnPersonTests(unittest.TestCase):

    def setUp(self):
        self.vault = Vault(self)
        self.vault.roster()
        self.vault.owner_birth()
        self.vault.son_birth()
        self.vault.his_words()
        self.school = self.vault.claim(
            "school", "We pulled James out of school in sixth grade.",
            label="James pulled from school", subject="James")
        self.vault.publish()
        self.node = self.vault.nodes()["James pulled from school"]

    def test_the_sons_moment_is_planned_with_his_own_birth(self):
        self.assertEqual(self.node["occurrence_subject_scope"], "other_person")
        read = resolver._Read(self.vault.root)
        _source, target = read.by_node[self.node["node_id"]]
        self.assertEqual(target["subject_birth"],
                         {"ref": SON_REF, "name": "James Everett Taylor", "birth": SON_BIRTH})

    def test_the_prompt_carries_his_tables_and_the_verifier_accepts_them(self):
        item = resolver.plan_items(self.vault.root, limit=5)["items"][0]
        self.assertIn("## The people these moments are about", item["prompt"])
        self.assertIn(f"[family:{SON_REF}]", item["prompt"])
        self.assertIn("James Everett Taylor 6th grade -> 2024-08 to 2025-06", item["prompt"])
        report = resolver.file_envelope(self.vault.root, envelope(item, [{
            "node_id": self.node["node_id"], "answer": {"earliest": "2024-08", "latest": "2025-06"},
            "basis": "derived", "confidence": 0.8, "fact_key": "sixth_grade",
            "citations": [{"doc": "story", "quote": "pulled James out of school in sixth grade"},
                          {"doc": f"family:{SON_REF}", "quote": "James Everett Taylor 6th grade -> 2024-08 to 2025-06"}],
            "reason": "sixth grade from his school years", "question": None}]), now=NOW)
        self.assertEqual(report["filed"], 1)
        best = self.vault.nodes()["James pulled from school"]["best_temporal_value"]
        self.assertEqual((best["earliest"], best["latest"]), ("2024-08", "2025-06"))

    def test_the_owners_age_table_still_never_dates_his_son(self):
        sp = resolver._Read(self.vault.root).spine
        target = {"subject": "James", "event": {"date": {"age": "11"}}, "handles": []}
        item = {"answer": {"earliest": "1992-07-11", "latest": "1993-07-10"}, "basis": "derived",
                "fact_key": "age_11", "citations": [{"doc": "spine", "quote": "11 -> 1992-07-11 to 1993-07-10"}]}
        self.assertEqual(resolver.verify(item, story="", passages={}, sp=sp, target=target)[1],
                         resolver.SUBJECT_AGE_NOT_OWNER)

    def test_a_bare_age_on_his_moment_is_arithmetic_off_his_birthday(self):
        self.vault.claim("swim", "Harvey... no, James learned to swim at 4.", label="James learns to swim",
                         claim_type="relative_order", subject="James",
                         value={"relation": "within", "anchors": ["4"]}, quote="at 4")
        self.vault.publish()
        read = resolver._Read(self.vault.root)
        _pending, deterministic = resolver._pending(read)
        labels = {target["label"]: age for _s, target, age in deterministic}
        self.assertEqual(labels.get("James learns to swim"), (4, "within"))
        resolver.file_envelope(self.vault.root, {"items": []}, now=NOW)
        best = self.vault.nodes()["James learns to swim"]["best_temporal_value"]
        self.assertEqual((best["earliest"], best["latest"]), ("2017-05-10", "2018-05-09"))

    def test_the_grade_table_follows_the_september_cutoff(self):
        self.assertEqual(resolver.grade_table("2013-05-10")[0], "kindergarten -> 2018-08 to 2019-06")
        self.assertEqual(resolver.grade_table("2013-10-01")[0], "kindergarten -> 2019-08 to 2020-06")
        self.assertIn("11th grade (junior) -> 1997-08 to 1998-06", resolver.grade_table(OWNER_BIRTH))
        self.assertIn("12th grade (senior) -> 1998-08 to 1999-06", resolver.grade_table(OWNER_BIRTH))


# --------------------------------------------------------------------------
# D — never ask what the look-first step has not tried
# --------------------------------------------------------------------------


class NeverAskWhatWasNotLookedAtTests(unittest.TestCase):

    def setUp(self):
        self.vault = Vault(self)
        self.vault.owner_birth()
        self.shop = self.vault.claim("shop", "The shop opened at some point after we moved.",
                                     label="shop opening", claim_type="relative_order",
                                     value={"relation": "after", "anchors": ["the move to Cedarport"]})
        self.node_id = self.shop["event_ref"]

    def card(self) -> dict | None:
        return next((row for row in self.vault.cards()
                     if row.get("node_ref") == self.node_id and row["kind"] == twi.PRECISION_GAP_KIND), None)

    def test_a_vault_with_no_resolver_ledger_keeps_its_cards(self):
        self.vault.publish()
        self.assertIsNotNone(self.card())

    def test_a_moment_not_yet_looked_at_has_no_card_and_is_queued(self):
        self.vault.ledger({})
        summary = self.vault.publish()
        self.assertIsNone(self.card())
        withheld = {row["node_ref"]: row["reason"] for row in summary["unlooked_date_cards"]}
        self.assertEqual(withheld[self.node_id], pub.NOT_YET_LOOKED_AT)
        # Queued: the resolver's own plan takes it.
        self.assertIn(self.node_id, resolver.plan_items(self.vault.root, limit=5)["items"][0]["node_ids"])

    def test_the_anchor_card_waits_for_the_moment_it_would_place(self):
        self.vault.ledger({})
        self.vault.publish()
        handle = twi.anchor_handle_ref("the move to Cedarport")
        self.assertFalse(any(row.get("subject_ref") == handle for row in self.vault.cards()))
        self.vault.ledger({self.node_id: {"status": "unknown", "question": "Which year did the shop open?"}})
        self.vault.publish()
        self.assertTrue(any(row.get("subject_ref") == handle for row in self.vault.cards()))

    def test_looked_at_and_asked_is_a_card_in_the_resolvers_words(self):
        self.vault.ledger({self.node_id: {"status": "unknown", "question": "Which summer did the shop open?"}})
        self.vault.publish()
        card = self.card()
        self.assertEqual((card["prompt_intent"], card["question_source"]),
                         ("Which summer did the shop open?", "resolver"))

    def test_looked_at_without_a_question_is_no_card(self):
        for status in ("unknown", "unverified", "no_answer_returned", "not_an_event"):
            with self.subTest(status):
                self.vault.ledger({self.node_id: {"status": status, "question": None}})
                summary = self.vault.publish()
                self.assertIsNone(self.card())
                self.assertEqual({r["node_ref"]: r["reason"] for r in summary["unlooked_date_cards"]}[self.node_id],
                                 pub.LOOKED_AT_WITHOUT_A_QUESTION)

    def test_a_moment_the_resolver_can_never_plan_is_no_card(self):
        """A retelling of a moment already placed (v333's
        `RESTATEMENT_IS_NOT_A_QUESTION`) is never planned by design — and so
        it is never asked either."""
        self.vault.claim("grad1", "I graduated in June 1999.", label="graduation day",
                         claim_type="date", value=chrono.parse_stated_date("1999-06").to_dict())
        again = self.vault.claim("grad2", "Graduation day was after the big game.", label="graduation day",
                                 claim_type="relative_order",
                                 value={"relation": "after", "anchors": ["the big game"]})
        self.vault.ledger({})
        summary = self.vault.publish()
        self.assertIn(again["event_ref"], resolver.restated_placed_nodes(pub.read_projection(self.vault.root)))
        self.assertNotIn(again["event_ref"], resolver._Read(self.vault.root).by_node)
        reasons = {r["node_ref"]: r["reason"] for r in summary["unlooked_date_cards"]}
        self.assertEqual(reasons[again["event_ref"]], pub.NEVER_PLANNABLE)
        self.assertFalse(any(row.get("node_ref") == again["event_ref"] for row in self.vault.cards()))

    def test_the_gate_moves_no_placement(self):
        self.vault.publish()
        without = (pub.read_projection(self.vault.root) or {})["nodes"]
        self.vault.ledger({})
        self.vault.publish()
        withheld = (pub.read_projection(self.vault.root) or {})["nodes"]
        strip = lambda nodes: sorted((n["node_id"], json.dumps(n.get("best_temporal_value"), sort_keys=True))
                                     for n in nodes)
        self.assertEqual(strip(without), strip(withheld))


# --------------------------------------------------------------------------
# E — a grounded estimate places, as the system's inference
# --------------------------------------------------------------------------


class AnEstimatePlacesTests(unittest.TestCase):

    def setUp(self):
        self.vault = Vault(self)
        self.vault.owner_birth()
        self.shop = self.vault.claim("shop", "The shop opened at some point after we moved.",
                                     label="shop opening", claim_type="relative_order",
                                     value={"relation": "after", "anchors": ["the move to Cedarport"]})
        self.node_id = self.shop["event_ref"]
        self.vault.publish()
        self.before = pub.read_projection(self.vault.root)

    def file(self, **estimate) -> dict:
        item = resolver.plan_items(self.vault.root, limit=5)["items"][0]
        return resolver.file_envelope(self.vault.root, envelope(item, [unknown(self.node_id, estimate={
            "earliest": "1996", "latest": "1998-03-17", "confidence": 0.5,
            "basis": [{"kind": "residence", "text": "the Cedarport years"}], **estimate})]), now=NOW)

    def node(self) -> dict:
        return self.vault.nodes()["shop opening"]

    def test_a_grounded_estimate_is_a_placement_at_month_grain(self):
        report = self.file()
        self.assertEqual(report["placed_by_estimate"], 1)
        node = self.node()
        self.assertTrue(node["usable_placement"])
        best = node["best_temporal_value"]
        self.assertEqual((best["earliest"], best["latest"]), ("1996", "1998-03"))
        # The system's inference, and legible as one.
        self.assertEqual(best["confidence"], "conjectural")
        claim = next(c for c in ts.fold_active_index(self.vault.root)["claims"]
                     if c["claim_id"] == resolver.load_ledger(self.vault.root)["nodes"][self.node_id]
                     ["placed_by_estimate"]["claim_id"])
        self.assertEqual((claim["basis"], claim["source_kind"]), ("inferred", "system_derived"))
        self.assertIn("the Cedarport years", claim["evidence"][0]["quote"])
        # Placed, so neither a card nor a floating window.
        self.assertFalse(any(row.get("node_ref") == self.node_id and row["kind"] == "precision_gap"
                             for row in self.vault.cards()))
        self.assertNotIn("probable_window", node)

    def test_an_ungrounded_estimate_stays_sky(self):
        report = self.file(basis=[{"kind": "story", "text": "the resolver's own reading"}])
        self.assertEqual(report["placed_by_estimate"], 0)
        self.assertFalse(self.node().get("usable_placement"))
        self.assertEqual(self.node()["probable_window"]["earliest"], "1996")

    def test_before_the_rule_an_estimate_filed_nothing(self):
        original = resolver.estimate_places
        resolver.estimate_places = lambda *a, **k: False
        try:
            self.file()
        finally:
            resolver.estimate_places = original
        self.assertFalse(self.node().get("usable_placement"))

    def test_what_he_says_places_it_and_the_estimate_is_the_rival(self):
        self.file()
        self.vault.claim("shop", "", label="shop opening", claim_type="date",
                         value=chrono.parse_stated_date("2003").to_dict(), event_ref=self.node_id,
                         quote="the shop opened in 2003")
        self.vault.publish()
        node = self.node()
        self.assertEqual((node["best_temporal_value"]["best"], node["best_temporal_value"]["basis"]),
                         ("2003", "stated"))
        self.assertEqual(node["conflict_state"], "contradicted")

    def test_a_node_he_dated_is_never_estimated_onto(self):
        self.assertFalse(resolver.estimate_places(
            {"earliest": "1996", "latest": "1998", "basis": [{"kind": "tenure", "text": "x"}]},
            {"person_dated": True}))

    def test_a_verified_answer_retires_the_estimate(self):
        self.file()
        estimate_claim = resolver.load_ledger(self.vault.root)["nodes"][self.node_id]["placed_by_estimate"]["claim_id"]
        read = resolver._Read(self.vault.root, triggers={"answers/shop.md"})
        self.assertIn(self.node_id, read.by_node, "an estimated moment stays reachable")
        item = resolver.plan_items(self.vault.root, limit=5, force=True, read=read)["items"][0]
        resolver.file_envelope(self.vault.root, envelope(item, [{
            "node_id": self.node_id, "answer": {"earliest": "1997-06", "latest": "1997-06"}, "basis": "stated",
            "confidence": 0.9, "fact_key": "shop", "reason": "x", "question": None,
            "citations": [{"doc": "story", "quote": "The shop opened at some point after we moved"}]}]),
            now=NOW, read=read, force=True)
        by_id = {c["claim_id"]: c for c in ts.fold_active_index(self.vault.root)["claims"]}
        self.assertEqual(by_id[estimate_claim]["status"], "superseded")
        self.assertEqual(self.node()["best_temporal_value"]["best"], "1997-06")

    def test_standing_estimates_place_with_no_model_call(self):
        self.vault.ledger({self.node_id: {"status": "unknown", "question": "Which year?", "label": "shop opening",
                                          "estimate": {"earliest": "1996", "latest": "1998",
                                                       "basis": [{"kind": "tenure", "text": "Tidewheel"}]}}})
        report = resolver.resolve_vault(self.vault.root, model="test-model", execute=True, limit=0,
                                        concurrency=1, only_sources={"answers/none.md"}, force=False, now=NOW)
        self.assertEqual(report["standing_estimates_placed"], 1)
        self.assertTrue(self.node()["usable_placement"])
        dry = resolver.resolve_vault(self.vault.root, model="test-model", execute=False, limit=0,
                                     concurrency=1, only_sources=None, force=False, now=NOW)
        self.assertEqual(dry["standing_estimates_placed"], 0)

    def test_the_placement_audit_is_empty(self):
        self.file()
        after = pub.read_projection(self.vault.root)
        was = {n["node_id"]: chrono.from_dict(n["best_temporal_value"])
               for n in self.before["nodes"] if n.get("best_temporal_value")}
        now = {n["node_id"]: chrono.from_dict(n["best_temporal_value"])
               for n in after["nodes"] if n.get("best_temporal_value")}
        self.assertEqual([n for n in was if n not in now or not chrono.dates_agree(was[n], now[n])], [])


# --------------------------------------------------------------------------
# A duplicate names its survivor, and an answer follows it there
# --------------------------------------------------------------------------


class ADuplicateNamesItsSurvivorTests(unittest.TestCase):
    """`resolver.A_DUPLICATE_NAMES_ITS_SURVIVOR`, through v359's
    `answer_placement.AN_ANSWER_OUTLIVES_ITS_CARD`: the card is shown, he
    answers, and before the answer is placed the resolver retires the moment as
    a restatement of another — the answer lands on the survivor."""

    def setUp(self):
        import answer_placement as ap  # noqa: PLC0415

        self.ap = ap
        self.vault = Vault(self)
        self.vault.owner_birth()
        self.survivor = self.vault.claim("shop1", "The shop opened in 1997.", label="shop opening",
                                         claim_type="date", value=chrono.parse_stated_date("1997").to_dict())
        self.retired = self.vault.claim("shop2", "The shop downtown opened after we moved.",
                                        label="the downtown shop opens", claim_type="relative_order",
                                        value={"relation": "after", "anchors": ["the move to Cedarport"]})
        self.dup, self.keep = self.retired["event_ref"], self.survivor["event_ref"]
        self.vault.publish()
        self.vault.ledger({self.dup: {"status": "unknown", "question": "Which year did the downtown shop open?",
                                      "label": "the downtown shop opens", "source_path": "answers/shop2.md"}})
        self.vault.publish()
        # v361 (`resolver.A_PLAN_IS_FILED_AGAINST_THE_LEDGER_IT_READ`): the item is
        # planned from the ledger it will be filed against.
        self.item = resolver.plan_items(self.vault.root, limit=5, force=True)["items"][0]
        self.card = next(row for row in self.vault.cards() if row.get("node_ref") == self.dup)
        # He answers the card he was shown …
        ts.promote_conversational_source(self.vault.root, "June 1997", {
            "turn_ref": "1", "speaker": "person", "channel": "web",
            "session_ref": f"conversation:cand:work_item:{self.card['work_item_id']}"})
        # … and the resolver, looking again, retires the moment as a duplicate.
        self.report = resolver.file_envelope(self.vault.root, envelope(self.item, [{
            "node_id": self.dup, "answer": None, "not_an_event": {
                "kind": "duplicate", "reason": f"restates {self.keep}", "duplicate_of": self.keep}}]),
            now=NOW, force=True)

    def test_the_verdict_names_the_survivor_as_a_field(self):
        row = resolver.load_ledger(self.vault.root)["nodes"][self.dup]
        self.assertEqual((row["status"], row["kind"], row["duplicate_of"]),
                         (resolver.NOT_AN_EVENT_STATUS, "duplicate", self.keep))
        self.assertEqual(resolver.duplicate_redirects(self.vault.root), {self.dup: self.keep})
        self.assertNotIn(self.dup, {n["node_id"] for n in pub.read_projection(self.vault.root)["nodes"]})

    def test_a_survivor_named_only_in_prose_is_still_read(self):
        verdict, _ = resolver.verify_not_an_event({"answer": None, "not_an_event": {
            "kind": "duplicate", "reason": f"the same moment as {self.keep}"}})
        self.assertEqual(verdict["duplicate_of"], self.keep)
        two, _ = resolver.verify_not_an_event({"answer": None, "not_an_event": {
            "kind": "duplicate", "reason": f"{self.keep} or node:{'0' * 24}"}})
        self.assertNotIn("duplicate_of", two)

    def test_the_answer_lands_on_the_survivor(self):
        report = self.ap.place_answers(self.vault.root, now=NOW)
        self.assertEqual(report["unplaced"], [])
        [filed] = report["filed"]
        self.assertEqual((filed["node_ref"], filed["asked_node_ref"]), (self.keep, self.dup))

    def test_without_the_redirect_the_answer_is_refused(self):
        original = self.ap.duplicate_redirects
        self.ap.duplicate_redirects = lambda root: {}
        try:
            report = self.ap.place_answers(self.vault.root, dry_run=True, now=NOW)
        finally:
            self.ap.duplicate_redirects = original
        self.assertEqual([row["refused"] for row in report["unplaced"]], [self.ap.REFUSED_NODE_NOT_DRAWN])



class ASurvivorMustBeAMomentTests(unittest.TestCase):

    def test_a_survivor_the_projection_does_not_hold_is_dropped(self):
        vault = Vault(self)
        vault.owner_birth()
        moment = vault.claim("shop", "The shop opened after we moved.", label="shop opening",
                             claim_type="relative_order",
                             value={"relation": "after", "anchors": ["the move to Cedarport"]})
        vault.publish()
        item = resolver.plan_items(vault.root, limit=5)["items"][0]
        for survivor in (f"node:{'1' * 24}", moment["event_ref"]):
            with self.subTest(survivor):
                resolver.file_envelope(vault.root, envelope(item, [{
                    "node_id": moment["event_ref"], "answer": None, "not_an_event": {
                        "kind": "duplicate", "reason": "x", "duplicate_of": survivor}}]), now=NOW, force=True)
                row = resolver.load_ledger(vault.root)["nodes"][moment["event_ref"]]
                self.assertEqual(row["kind"], "duplicate")
                self.assertNotIn("duplicate_of", row)
                self.assertEqual(resolver.duplicate_redirects(vault.root), {})


class TheRulesAreNamedTests(unittest.TestCase):

    def test_every_rule_is_a_named_sentence(self):
        for module, name in ((resolver, "LOOK_AT_EVERYTHING_THAT_CAN_BECOME_A_CARD"),
                             (resolver, "A_FAMILY_MOMENT_IS_DATED_FROM_ITS_OWN_PERSON"),
                             (resolver, "AN_ESTIMATE_PLACES_AS_THE_SYSTEMS_INFERENCE"),
                             (resolver, "AN_ESTIMATE_NEVER_PLACES_A_RESIDENCE"),
                             (resolver, "A_DUPLICATE_NAMES_ITS_SURVIVOR"),
                             (pub, "NEVER_ASK_WHAT_WAS_NOT_LOOKED_AT"),
                             (ir, "WHAT_HE_CALLS_THEM_DECIDES_A_BARE_NAME")):
            with self.subTest(name):
                self.assertGreater(len(getattr(module, name)), 60)

    def test_the_rule_version_moved_for_the_identity_change(self):
        self.assertEqual(tt.CALCULATION_RULE_VERSION, "timeline-rules:25")


if __name__ == "__main__":
    unittest.main()
