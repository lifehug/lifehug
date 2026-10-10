"""v402 — a refiled entry introduces nobody; an organization is never a
spouse; a cornerstone wedding or divorce belongs to its own couple.

The owner, 2026-10-10, on the Cornerstones view: *"Castle Island Ventures is a
cornerstone, which is not true. I've tried to erase this many times. Under my
cornerstone it says div. or divorced. I haven't been divorced."* The row under
Spouse read "Castle / Castle Island Ventures — married 11 Jan 2007 — div. 13
May 2025". Three causes, one test class each (the incident's numbering):

* **1a** — `entity_roster.landmark_introduction_plan` read every landmark
  entry, REFILED or not, so the daily `roster_introductions` sweep minted a
  spouse from two `partnerships` entries refiled a week earlier
  (`organization_is_not_a_partner`).
* **1b** — a `partnerships` entry named a venture fund (three capitalised
  words pass `_looks_like_a_full_name`), and another named his sister's
  husband (subject: the sister); both minted the OWNER's spouse.
* **1c** — once minted, the row was a settled identity fact every refresh
  kept; nothing ever took it back.
* **2** — `cornerstones.cornerstone_nodes` keyed EVERY wedding/divorce
  cornerstone to the owner, so his sister's divorce filled his divorced cell
  and every Spouse row's.
* **3** — a whole-message listener telling, bound to the sister's `divorced`
  episode, still held her `married` (second wedding) claim once the divorce
  claim beside it was superseded; the divorce took the wedding's date and
  counterpart.

Every test here was run against the v399 bytes and SEEN failing first.
Synthetic data only; nothing here reads a real vault.
"""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

from tempdirs import root_parent_tmp  # noqa: E402

import cornerstones as cs  # noqa: E402
import entity_roster  # noqa: E402
import event_identity as ei  # noqa: E402
import landmark_projection as lp  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_publication  # noqa: E402,F401 — bound to the real vault before any test redirects it
import temporal_store  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import timeline_views as tv  # noqa: E402

OWNER_NAMES = ("Dave", "David James Taylor")
NOW = "2026-10-10T12:00:00Z"


# --------------------------------------------------------------------------
# Landmark entries and the substrate's identity claims over them
# --------------------------------------------------------------------------


def _entry(digest: str, record: dict, *, ordinal: int) -> dict:
    return {"source_id": f"landmark:entry-{digest}", "domain": record["domain"],
            "entry_key": (record.get("who") or record.get("label") or "").casefold(),
            "ordinal": ordinal, "record": dict(record)}


def castle(digest: str = "a512fa5b", *, ordinal: int = 126) -> dict:
    """The founder's shape: a venture fund filed under `partnerships`."""
    return _entry(digest, {"domain": "partnerships", "label": "Castle Island Ventures",
                           "who": "Castle Island Ventures", "subject": "Etherfuse",
                           "date": {"best": "2025-05", "basis": "anchor"}}, ordinal=ordinal)


def robin(digest: str = "robin0001", *, ordinal: int = 7) -> dict:
    """A PERSON in the owner's own partnership (no subject: his)."""
    return _entry(digest, {"domain": "partnerships", "label": "Robin Ann Hale",
                           "who": "Robin Ann Hale",
                           "date": {"best": "2007-01-11", "basis": "stated"}}, ordinal=ordinal)


def lorin(digest: str = "96fb70fd", *, ordinal: int = 140) -> dict:
    """His SISTER's partnership: a person, but not the owner's."""
    return _entry(digest, {"domain": "partnerships", "label": "Lorin Cook", "who": "Lorin Cook",
                           "subject": "Jacque",
                           "date": {"best": "2025-05-13", "basis": "anchor"}}, ordinal=ordinal)


def identity_claim(entry: dict, *, status: str = "active") -> dict:
    digest = entry["source_id"].rpartition("-")[2]
    return {"claim_id": f"claim:{digest:0<24}"[:30], "claim_type": "identity",
            "status": status, "source_ref": {"source_id": entry["source_id"]}}


def index_over(*rows: tuple) -> dict:
    """``(entry, status)`` pairs -> an active index holding each entry's
    identity claim at that status ("superseded" = refiled or retired)."""
    return {"version": 1, "claims": [identity_claim(entry, status=status)
                                     for entry, status in rows]}


def _row(name: str, **extra) -> dict:
    out = {"name": name, "slug": entity_roster.slugify(name), "aliases": [],
           "qualifies": False, "score": 0.0, "unique_answers": 0, "page_eligible": False,
           "focus": None, "folded_into": None}
    out.update(extra)
    return out


def katie() -> dict:
    return _row("Katie Taylor", aliases=["wife", "my wife", "Katie Ann Merrill", "Katie"],
                relationship="spouse", source="landmark:family")


def minted(name: str, **extra) -> dict:
    """A row the landmark introducer minted (its door: `landmark:family`)."""
    return _row(name, relationship="spouse", source="landmark:family", **extra)


class _DailyStep(unittest.TestCase):
    """`entity-roster --ensure-introduced` — the hosted daily
    `roster_introductions` step — over a throwaway vault."""

    def setUp(self) -> None:
        import lifehug_core  # noqa: PLC0415

        self.root = root_parent_tmp(self, ROOT, prefix="lifehug-v402-introduce-")
        (self.root / "system").mkdir(parents=True, exist_ok=True)
        (self.root / "state" / "entity_rosters").mkdir(parents=True, exist_ok=True)
        (self.root / "profile.yaml").write_text("name: Dave\n", encoding="utf-8")
        self.path = self.root / "state" / "entity_rosters" / "person.json"
        for module, name, value in ((lifehug_core, "REPO_DIR", self.root),
                                    (entity_roster, "ENTITY_DIR", self.path.parent)):
            saved = getattr(module, name)
            setattr(module, name, value)
            self.addCleanup(setattr, module, name, saved)

    def seed(self, rows) -> None:
        self.path.write_text(json.dumps({"version": 1, "type": "person", "entities": rows}),
                             encoding="utf-8")

    def run_step(self, entries, index, *, dry_run: bool = False) -> dict:
        with mock.patch.object(lp, "load_landmark_sources", return_value=list(entries)), \
                mock.patch.object(temporal_store, "read_active_index", return_value=index), \
                mock.patch.object(entity_roster, "recount_stats", return_value={}):
            result = entity_roster.ensure_introduced_relatives(dry_run=dry_run)
        result["roster"] = json.loads(self.path.read_text(encoding="utf-8"))
        return result

    def slugs(self, result) -> set:
        return {row["slug"] for row in result["roster"]["entities"]}


# --------------------------------------------------------------------------
# 1a — a withdrawn (refiled / retired) entry introduces nobody
# --------------------------------------------------------------------------


class AWithdrawnEntryIntroducesNobody(_DailyStep):

    def test_the_projection_and_the_introducer_read_one_definition(self):
        index = index_over((robin(), "superseded"), (castle(), "active"))
        self.assertEqual(lp.withdrawn_source_ids(index), {robin()["source_id"]})
        self.assertEqual([e["source_id"] for e in
                          lp.standing_landmark_sources([robin(), castle()], index)],
                         [castle()["source_id"]])
        # An entry the substrate holds no claim for was never withdrawn.
        self.assertEqual(lp.withdrawn_source_ids({"claims": []}), frozenset())

    def test_a_refiled_partnership_mints_no_spouse(self):
        self.seed([katie()])
        result = self.run_step([robin()], index_over((robin(), "superseded")))
        self.assertNotIn("robin-ann-hale", self.slugs(result))
        self.assertEqual(result["filed"], 0)

    def test_the_same_entry_standing_still_mints_its_spouse(self):
        self.seed([])
        result = self.run_step([robin()], index_over((robin(), "active")))
        self.assertIn("robin-ann-hale", self.slugs(result))


# --------------------------------------------------------------------------
# 1b — a spouse is a PERSON in the owner's OWN partnership
# --------------------------------------------------------------------------


class ASpouseIsAPersonInTheOwnersOwnPartnership(unittest.TestCase):

    def test_an_organization_is_never_a_spouse(self):
        plan = entity_roster.landmark_introduction_plan([castle()], roster={"entities": []})
        self.assertEqual(plan["mint"], [])
        self.assertEqual(entity_roster.introduction_refusal(castle()),
                         lp.ORGANIZATION_IS_NOT_A_PARTNER)

    def test_his_sisters_husband_is_not_his_spouse(self):
        plan = entity_roster.landmark_introduction_plan([lorin()], roster={"entities": []})
        self.assertEqual(plan["mint"], [])
        self.assertEqual(entity_roster.introduction_refusal(lorin(), owner_names=OWNER_NAMES),
                         entity_roster.INTRODUCER_NOT_HIS_PARTNERSHIP)

    def test_his_own_partner_is_still_his_spouse(self):
        mine = _entry("dave0001", {"domain": "partnerships", "who": "Robin Ann Hale",
                                   "label": "Robin Ann Hale", "subject": "David James Taylor"},
                      ordinal=3)
        for entry in (robin(), mine):
            plan = entity_roster.landmark_introduction_plan([entry], roster={"entities": []},
                                                            owner_names=OWNER_NAMES)
            self.assertEqual([(r["slug"], r["relationship"]) for r in plan["mint"]],
                             [("robin-ann-hale", "spouse")])


# --------------------------------------------------------------------------
# 1c — the same daily pass retires a row it introduced, reversibly
# --------------------------------------------------------------------------


class ARowRetiresWithTheEntriesThatIntroducedIt(_DailyStep):

    def founders_roster(self) -> list:
        return [katie(), minted("Castle Island Ventures", aliases=["Castle"]),
                minted("Lorin Cook", aliases=["Lorin"], score=7.0)]

    def founders_entries(self) -> list:
        return [castle("a512fa5b", ordinal=126), castle("94b40f96", ordinal=127), lorin()]

    def founders_index(self) -> dict:
        entries = self.founders_entries()
        return index_over((entries[0], "superseded"), (entries[1], "superseded"),
                          (entries[2], "active"))

    def test_the_castle_row_retires_and_a_second_run_changes_nothing(self):
        self.seed(self.founders_roster())
        first = self.run_step(self.founders_entries(), self.founders_index())
        self.assertEqual(self.slugs(first), {"katie-taylor"})
        self.assertEqual([r["slug"] for r in first["retired"]],
                         ["castle-island-ventures", "lorin-cook"])
        ledger = {row["slug"]: row for row in first["roster"]["retired_rows"]}
        # Never removed: the whole row is kept, with the receipt that says why.
        self.assertEqual(ledger["castle-island-ventures"]["row"]["aliases"], ["Castle"])
        receipt = ledger["castle-island-ventures"]["receipt"]
        self.assertEqual(receipt["reason"], entity_roster.RETIRE_REASON)
        self.assertEqual({r["why"] for r in receipt["introduced_by"]},
                         {entity_roster.INTRODUCER_WITHDRAWN})
        self.assertEqual(ledger["lorin-cook"]["receipt"]["introduced_by"][0]["why"],
                         entity_roster.INTRODUCER_NOT_HIS_PARTNERSHIP)
        before = self.path.read_bytes()
        again = self.run_step(self.founders_entries(), self.founders_index())
        self.assertEqual(again["retired"], [])
        self.assertEqual(self.path.read_bytes(), before, "idempotent: byte-identical")

    def test_a_dry_run_reports_and_writes_nothing(self):
        self.seed(self.founders_roster())
        before = self.path.read_bytes()
        result = self.run_step(self.founders_entries(), self.founders_index(), dry_run=True)
        self.assertEqual(len(result["retired"]), 2)
        self.assertEqual(self.path.read_bytes(), before)

    def test_a_future_refile_retires_the_row_on_the_next_ordinary_pass(self):
        self.seed([])
        standing = index_over((robin(), "active"))
        self.run_step([robin()], standing)
        self.assertIn("robin-ann-hale", self.slugs(self.run_step([robin()], standing)))
        # The refile lands (its identity claim is superseded); the next
        # ordinary daily pass — no special verb — retires the row.
        refiled = index_over((robin(), "superseded"))
        result = self.run_step([robin()], refiled)
        self.assertNotIn("robin-ann-hale", self.slugs(result))
        self.assertEqual([r["slug"] for r in result["retired"]], ["robin-ann-hale"])
        # Reversible: the entry stands again (an undo) and the SAME row returns.
        back = self.run_step([robin()], standing)
        self.assertIn("robin-ann-hale", self.slugs(back))
        self.assertEqual(back["restored"], ["robin-ann-hale"])
        self.assertNotIn("retired_rows", back["roster"])

    def test_a_row_something_else_answers_to_is_never_retired(self):
        rows = [minted("Castle Island Ventures", unique_answers=3),
                minted("Lorin Cook", relation_word="Lorin")]
        self.seed(rows)
        result = self.run_step(self.founders_entries(), self.founders_index())
        self.assertEqual(result["retired"], [])
        self.assertEqual(self.slugs(result), {"castle-island-ventures", "lorin-cook"})

    def test_a_row_another_door_minted_is_never_retired_by_this_rule(self):
        self.seed([_row("Castle Island Ventures", relationship="spouse")])
        result = self.run_step(self.founders_entries(), self.founders_index())
        self.assertEqual(result["retired"], [])

    def test_a_refresh_keeps_the_ledger(self):
        self.seed(self.founders_roster())
        self.run_step(self.founders_entries(), self.founders_index())
        entity_roster.write_roster("person", [katie()])
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual([row["slug"] for row in payload["retired_rows"]],
                         ["castle-island-ventures", "lorin-cook"])


# --------------------------------------------------------------------------
# 2 — a cornerstone wedding or divorce belongs to its own couple
# --------------------------------------------------------------------------


def _node(node_id, kind, label, subjects, best):
    return {"node_id": node_id, "event_kind": kind, "node_kind": "event", "label": label,
            "subject_refs": list(subjects), "conflict_state": "none",
            "best_temporal_value": ({"best": best, "earliest": best, "latest": best,
                                     "granularity": "day" if len(best) == 10 else "year",
                                     "basis": "stated", "confidence": "certain"}
                                    if best else None)}


class AWeddingOrDivorceBelongsToItsOwnCouple(unittest.TestCase):
    """The founder's shape: his wedding, his sister's divorce, and a roster
    that (wrongly, until 1c retires it) says her husband is a spouse."""

    def setUp(self):
        self.roster = {"entities": [
            katie(),
            minted("Lorin Cook", aliases=["Lorin"]),
            _row("Jacque Cooke", relationship="sibling", aliases=["Jacque"]),
        ]}
        self.relations = cs.Relations(self.roster, (), owner_names=OWNER_NAMES)
        self.nodes = [
            _node("node:wedding", "married", "Married Katie Ann Merrill",
                  ["author", "narrator", "self"], "2007-01-11"),
            _node("node:sister-divorce", "divorced",
                  "Jacque Cooke's prior marriage as Jacque Fergusen",
                  ["Jacque Cooke", "person/lorin-cook"], "2024"),
        ]

    def view(self):
        view = tv.cornerstones_view(self.nodes, self.relations, roster=self.roster,
                                    owner_name="David James Taylor")
        rows = {r["person_ref"]: r for g in view["groups"] for r in g["people"]}
        return view, rows

    def test_his_sisters_divorce_is_not_his_cornerstone(self):
        held = cs.cornerstone_nodes(self.nodes, self.relations)
        self.assertNotIn(("divorce", cs.SELF), held)
        self.assertIn(("wedding", cs.SELF), held)
        status, _milestone, _whose = cs.node_status(self.nodes[1], self.relations)
        self.assertEqual(status, cs.OUTSIDE_THE_SET)

    def test_his_divorced_cell_and_every_spouse_row_stay_empty(self):
        _view, rows = self.view()
        self.assertIsNone(rows["self"]["divorced"])
        self.assertIsNone(rows["person/katie-taylor"]["divorced"])
        self.assertIsNone(rows["person/lorin-cook"]["divorced"])
        self.assertEqual(rows["self"]["married"]["value"], "2007-01-11")

    def test_a_spouse_row_shows_only_its_own_couples_wedding(self):
        _view, rows = self.view()
        self.assertEqual(rows["person/katie-taylor"]["married"]["value"], "2007-01-11")
        self.assertIsNone(rows["person/lorin-cook"]["married"]["value"])

    def test_her_divorce_shows_in_others_as_hers(self):
        view, _rows = self.view()
        others = {(o["person_ref"], o["milestone"]): o for o in view["others"]}
        self.assertEqual(others[("person/jacque-cooke", "divorce")]["value"], "2024")

    def test_his_own_reception_naming_his_mother_is_still_his(self):
        relations = cs.Relations({"entities": [
            katie(), _row("Desiree Taylor", relationship="parent")]}, (),
            owner_names=OWNER_NAMES)
        node = _node("node:reception", "married", "Wedding reception",
                     ["self", "person/desiree-taylor"], "2007-01-11")
        self.assertEqual(cs.owners_couple(node, relations), (True, "person/katie-taylor"))


# --------------------------------------------------------------------------
# 3 — a wedding claim never dates a divorce episode
# --------------------------------------------------------------------------


def _claim(**overrides) -> dict:
    source = overrides.pop("source")
    payload = {
        "source_kind": "conversation",
        "source_ref": {"source_id": source,
                       "revision": "sha256:" + hashlib.sha256(source.encode()).hexdigest()},
        "evidence": [{"quote": overrides.pop("quote")}],
        "extractor_version": "general_listener:1",
        "created_at": "2026-09-23T00:00:00Z",
        "basis": "explicit", "confidence": 0.9, "status": "active",
    }
    payload.update(overrides)
    return tc.validate_temporal_claim(payload)


def _dated(best: str) -> dict:
    return {"best": best, "earliest": best, "latest": best,
            "granularity": "day" if len(best) == 10 else "year",
            "basis": "stated", "confidence": "certain"}


class AWeddingNeverDatesADivorce(unittest.TestCase):
    """The founder's reply about his sister — "Jacque married Brett around
    1998 … She divorced him around 2024 … She married Lorin Cook May 13th
    2025" — filed by the listener as ONE whole-message telling, bound (R2) to
    the `divorced` episode his earlier telling made; the divorce-from-Brett
    claim beside the wedding was later superseded by the owner's own 🗑."""

    def setUp(self):
        self.divorce_ref = "classification:sources-manual-jacque#prior-marriage"
        self.message_ref = "conversation:msg-jacque"
        self.claims = [
            _claim(source=self.divorce_ref, claim_type="occurrence", event_kind="divorced",
                   subject_mention="Jacque Cooke",
                   event_mention="Jacque Cooke's prior marriage as Jacque Fergusen",
                   quote="Jacque Cooke's prior marriage as Jacque Fergusen"),
            _claim(source=self.message_ref, claim_type="date", event_kind="married",
                   subject_mention="Lorin Cook", temporal_value=_dated("2025-05-13"),
                   quote="She Married Lorin Cook May 13th 2025 or around then"),
        ]
        members = (self.divorce_ref, self.message_ref)
        operation_id = ei.operation_digest(
            authority="deterministic", op="create", rule_version=ei.IDENTITY_RULE_VERSION,
            member_refs=members)
        self.episode_id = ei.episode_id_for(operation_id)
        bindings = [{"telling_ref": ref, "episode_id": self.episode_id, "relation": "same",
                     "origin": "deterministic", "rule_id": "R2",
                     "operation_id": operation_id, "created_at": NOW} for ref in members]
        operation = {"authority": "deterministic", "op": "create",
                     "episode_id": self.episode_id, "members": list(members),
                     "creates_binding_ids": [ei.validate_event_identity(b)["identity_id"]
                                             for b in bindings],
                     "canonical_event_kind": "divorced", "created_at": NOW}
        self.records = {"operations": [ei.validate_episode_operation(operation)],
                        "bindings": [ei.validate_event_identity(b) for b in bindings]}

    def derive(self):
        index = {"version": temporal_store.INDEX_VERSION,
                 "claims": [dict(row) for row in self.claims]}
        return tt.derive_calculated_timeline(index, now=NOW, episode_records=self.records)

    def test_the_divorce_keeps_neither_the_wedding_date_nor_its_counterpart(self):
        result = self.derive()
        divorce = next(n for n in result.nodes if n.get("episode_id") == self.episode_id)
        self.assertEqual(divorce["event_kind"], "divorced")
        self.assertNotEqual((divorce.get("best_temporal_value") or {}).get("best"), "2025-05-13")
        self.assertFalse(any("lorin" in str(s).casefold() for s in divorce["subject_refs"]))
        self.assertNotIn(self.claims[1]["claim_id"], divorce["input_claim_refs"])

    def test_the_wedding_stays_its_own_fact_on_its_own_day(self):
        result = self.derive()
        weddings = [n for n in result.nodes if n.get("event_kind") == "married"]
        self.assertEqual(len(weddings), 1)
        self.assertEqual(weddings[0]["best_temporal_value"]["best"], "2025-05-13")
        self.assertIn(self.claims[1]["claim_id"], weddings[0]["input_claim_refs"])

    def test_the_rule_reads_transitions_only(self):
        import episode_fold as ef  # noqa: PLC0415

        self.assertTrue(ef.another_transition("married", "divorced"))
        self.assertFalse(ef.another_transition("divorced", "divorced"))
        self.assertFalse(ef.another_transition("moment", "divorced"))
        self.assertFalse(ef.another_transition("married", "job"))


if __name__ == "__main__":
    unittest.main()
