"""Tests for the focus-merge contract (v169, ADR 0012).

`focus-merge` is the healing verb duplicate curation (ADR 0010, v168) left
missing: a deliberate, owner-initiated, auditable multi-file transaction
that fuses two Focuses into one. These tests pin the transaction's SAFETY
properties, which are the whole point of the verb — the step order, the
refusals, dry-run's write-nothing guarantee, the append-only audit record,
the never-renumber-question-ids doctrine, and the regression that a merged
vault stays merged across `derive_roadmap`.

Everything here is synthetic — a throwaway vault per test, never the
founder vault (AGENTS.md's boundary rule).
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))
sys.path.insert(0, str(ROOT / "tests"))

from tempdirs import root_parent_tmp  # noqa: E402

import entity_roster  # noqa: E402
import focus_curation  # noqa: E402
import focus_dupes  # noqa: E402
import focus_merge  # noqa: E402
import roadmap  # noqa: E402

BANK = """# Question Bank

## A: Origins
- [x] A1: What is your earliest memory? *(2026-01-01)*
- [ ] A2: Where were you born?

## Focuses

## K: Focus — Fear
- [x] K1: What scares you most? *(2026-02-01)*
- [ ] K2: When did you first feel afraid?

## L: Focus — The Fear
- [ ] L1: What is the fear you never name?
- [ ] L2: Who taught you to be afraid?
"""

PRIMARY = {
    "id": "my-life", "label": "My Life", "type": "life_story", "primary": True,
    "tier": "extreme", "objective": "story", "deliverable": "book",
    "categories": ["A"], "target_depth": 50, "cap": 0.4, "phase": "active",
    "wiki_node": None, "neighborhoods": [],
}


def _focus(fid: str, label: str, categories: list[str], *, target_depth: int = 20,
           wiki_node: str | None = None, neighborhoods: list[str] | None = None) -> dict:
    return {
        "id": fid, "label": label, "primary": False, "type": "theme", "tier": "standard",
        "objective": f"explore {label}", "deliverable": "essay", "categories": categories,
        "target_depth": target_depth, "cap": 0.3, "phase": "active",
        "wiki_node": wiki_node if wiki_node is not None else f"wiki/themes/{fid}.md",
        "neighborhoods": neighborhoods if neighborhoods is not None else [f"nbhd-{fid}"],
    }


class FixtureBase(unittest.TestCase):
    """Throwaway-vault plumbing, following tests/test_focus_duplicate_curation.py's
    real-path-tmp-dir + monkeypatched-module-attribute convention."""

    def setUp(self):
        self.tmp = root_parent_tmp(self, ROOT, prefix="lifehug-focus-merge-")
        self._saved = {
            (roadmap, "ROADMAP_FILE"): roadmap.ROADMAP_FILE,
            (roadmap, "QUESTIONS_FILE"): roadmap.QUESTIONS_FILE,
            (focus_merge, "ROADMAP_FILE"): focus_merge.ROADMAP_FILE,
            (focus_merge, "QUESTIONS_FILE"): focus_merge.QUESTIONS_FILE,
            (focus_merge, "WIKI_DIR"): focus_merge.WIKI_DIR,
            (focus_merge, "REPO_DIR"): focus_merge.REPO_DIR,
            (focus_merge, "FOCUS_MERGES_FILE"): focus_merge.FOCUS_MERGES_FILE,
            (focus_merge, "COMPILE_NEEDED_FILE"): focus_merge.COMPILE_NEEDED_FILE,
            (entity_roster, "ENTITY_DIR"): entity_roster.ENTITY_DIR,
            (focus_curation, "SETTLED_FILE"): focus_curation.SETTLED_FILE,
        }
        bank = self.tmp / "question-bank.md"
        bank.write_text(BANK, encoding="utf-8")
        roadmap.QUESTIONS_FILE = bank
        focus_merge.QUESTIONS_FILE = bank
        focus_merge.WIKI_DIR = self.tmp / "wiki"
        focus_merge.REPO_DIR = self.tmp
        focus_merge.FOCUS_MERGES_FILE = self.tmp / "state" / "focus_merges.json"
        focus_merge.COMPILE_NEEDED_FILE = self.tmp / "state" / ".compile-needed"
        entity_roster.ENTITY_DIR = self.tmp / "state" / "entity_rosters"
        focus_curation.SETTLED_FILE = self.tmp / "state" / "focus_curation" / "settled.json"
        self._set_roadmap([PRIMARY, _focus("fear", "Fear", ["K"]),
                           _focus("the-fear", "The Fear", ["L"], target_depth=30)])
        self._write_page("wiki/themes/fear.md", "focus", "Fear")
        self._write_page("wiki/themes/the-fear.md", "focus", "The Fear")

    def tearDown(self):
        for (mod, name), value in self._saved.items():
            setattr(mod, name, value)

    # --- fixture helpers ---------------------------------------------------

    def _set_roadmap(self, focuses: list[dict]) -> None:
        path = self.tmp / "state" / "roadmap.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": 1, "focuses": focuses}, indent=2), encoding="utf-8")
        roadmap.ROADMAP_FILE = path
        focus_merge.ROADMAP_FILE = path

    def _write_page(self, relative: str, origin: str | None, title: str) -> Path:
        path = self.tmp / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        origin_line = f"origin: {origin}\n" if origin else ""
        path.write_text(f'---\ntitle: "{title}"\ntype: theme\n{origin_line}---\n\n# {title}\n',
                        encoding="utf-8")
        return path

    def _set_roster(self, entity_type: str, entities: list[dict], **extra) -> Path:
        path = entity_roster.ENTITY_DIR / f"{entity_type}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "type": entity_type, "resolved_at": "2026-08-01T00:00:00Z",
                   "entities": entities, **extra}
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def _default_roster(self) -> Path:
        return self._set_roster("theme", [
            {"name": "Fear", "slug": "fear", "aliases": ["dread"], "qualifies": True,
             "maps_to_focus": "fear", "page_eligible": True},
            {"name": "The Fear", "slug": "the-fear", "aliases": [], "qualifies": True,
             "maps_to_focus": "the-fear", "page_eligible": True},
        ], source="ai", sampled_answer_ids=["A1"])

    def _roadmap(self) -> dict:
        return json.loads((self.tmp / "state" / "roadmap.json").read_text(encoding="utf-8"))

    def _focus_ids(self) -> list[str]:
        return [f["id"] for f in self._roadmap()["focuses"]]

    def _find(self, fid: str) -> dict | None:
        return next((f for f in self._roadmap()["focuses"] if f["id"] == fid), None)

    def _vault_fingerprint(self) -> dict[str, str]:
        return {
            p.relative_to(self.tmp).as_posix(): p.read_text(encoding="utf-8", errors="replace")
            for p in sorted(self.tmp.rglob("*")) if p.is_file()
        }


# ---------------------------------------------------------------------------
# Scope 1 — the transaction
# ---------------------------------------------------------------------------

class HappyMergeTests(FixtureBase):
    def setUp(self):
        super().setUp()
        self._default_roster()
        self.result = focus_merge.focus_merge("fear", "the-fear")

    def test_status_is_merged_and_applied(self):
        self.assertEqual(self.result["status"], "merged")
        self.assertTrue(self.result["applied"])

    def test_categories_are_unioned_in_survivor_order(self):
        # Order preserved (survivor's own first), never sorted.
        self.assertEqual(self._find("fear")["categories"], ["K", "L"])

    def test_loser_entry_is_dropped(self):
        self.assertNotIn("the-fear", self._focus_ids())
        self.assertIn("fear", self._focus_ids())

    def test_neighborhoods_are_merged(self):
        self.assertEqual(self._find("fear")["neighborhoods"], ["nbhd-fear", "nbhd-the-fear"])

    def test_survivor_user_fields_are_unchanged_without_adopt_target(self):
        survivor = self._find("fear")
        self.assertEqual(survivor["target_depth"], 20)  # NOT the loser's 30
        self.assertEqual(survivor["tier"], "standard")
        self.assertEqual(survivor["objective"], "explore Fear")
        self.assertEqual(survivor["cap"], 0.3)
        self.assertEqual(survivor["phase"], "active")

    def test_bank_header_is_annotated_with_the_provenance_comment(self):
        text = focus_merge.QUESTIONS_FILE.read_text(encoding="utf-8")
        self.assertIn("<!-- merged into fear by focus-merge ", text)
        self.assertIn('(was "Focus — The Fear")', text)

    def test_loser_header_adopts_the_survivor_header_text(self):
        text = focus_merge.QUESTIONS_FILE.read_text(encoding="utf-8")
        self.assertIn("## L: Focus — Fear\n", text)
        self.assertNotIn("## L: Focus — The Fear", text)

    def test_question_ids_are_never_renumbered(self):
        """Bank doctrine: ids only ever grow, and provenance elsewhere
        references them — a merge touches header LINES, never question lines."""
        text = focus_merge.QUESTIONS_FILE.read_text(encoding="utf-8")
        for original in ("- [x] A1:", "- [ ] A2:", "- [x] K1:", "- [ ] K2:",
                         "- [ ] L1:", "- [ ] L2:"):
            self.assertIn(original, text)
        self.assertIn("- [ ] L1: What is the fear you never name?", text)

    def test_roster_entries_repoint_to_the_survivor(self):
        roster = json.loads((entity_roster.ENTITY_DIR / "theme.json").read_text(encoding="utf-8"))
        self.assertEqual({e["name"]: e["maps_to_focus"] for e in roster["entities"]},
                         {"Fear": "fear", "The Fear": "fear"})

    def test_roster_rewrite_preserves_unrelated_payload_keys(self):
        roster = json.loads((entity_roster.ENTITY_DIR / "theme.json").read_text(encoding="utf-8"))
        self.assertEqual(roster["source"], "ai")
        self.assertEqual(roster["sampled_answer_ids"], ["A1"])

    def test_the_losers_slug_joins_the_survivors_roster_aliases(self):
        roster = json.loads((entity_roster.ENTITY_DIR / "theme.json").read_text(encoding="utf-8"))
        survivor = next(e for e in roster["entities"] if e["name"] == "Fear")
        self.assertIn("dread", survivor["aliases"])  # pre-existing alias kept
        self.assertIn("the-fear", survivor["aliases"])

    def test_curation_ledger_settles_the_loser_as_a_merge(self):
        settled = json.loads(focus_curation.SETTLED_FILE.read_text(encoding="utf-8"))
        self.assertEqual(settled["decisions"]["rec-the-fear"]["bucket"], "merge")

    def test_focus_origin_wiki_page_is_removed_and_logged(self):
        self.assertFalse((self.tmp / "wiki" / "themes" / "the-fear.md").exists())
        self.assertTrue((self.tmp / "wiki" / "themes" / "fear.md").exists())
        log = (self.tmp / "wiki" / "log.md").read_text(encoding="utf-8")
        self.assertIn("removed wiki/themes/the-fear.md", log)
        self.assertIn("merged into fear", log)

    def test_audit_record_is_written(self):
        data = json.loads(focus_merge.FOCUS_MERGES_FILE.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 1)
        self.assertEqual(len(data["merges"]), 1)
        record = data["merges"][0]
        self.assertEqual(record["survivor"], "fear")
        self.assertEqual(record["loser"], "the-fear")
        self.assertEqual(record["loser_label"], "The Fear")
        self.assertEqual(record["categories_moved"], ["L"])
        self.assertEqual(record["roster_repoints"], [{"type": "theme", "entity": "The Fear"}])
        self.assertIn("state/roadmap.json", record["files_touched"])
        self.assertIn("wiki/themes/the-fear.md", record["files_touched"])

    def test_recompile_sentinel_is_touched_and_nothing_is_compiled_inline(self):
        self.assertTrue(focus_merge.COMPILE_NEEDED_FILE.exists())

    def test_the_pair_no_longer_appears_in_the_dupes_report(self):
        report = focus_dupes.certain_focus_duplicates(roadmap.load_roadmap())
        self.assertEqual(report, [])


class AuditRecordIsAppendOnlyTests(FixtureBase):
    def test_a_second_merge_appends_rather_than_replacing(self):
        self._set_roadmap([PRIMARY, _focus("fear", "Fear", ["K"]),
                           _focus("the-fear", "The Fear", ["L"]),
                           _focus("dread", "Dread", [])])
        focus_merge.focus_merge("fear", "the-fear")
        focus_merge.focus_merge("fear", "dread")
        data = json.loads(focus_merge.FOCUS_MERGES_FILE.read_text(encoding="utf-8"))
        self.assertEqual([m["loser"] for m in data["merges"]], ["the-fear", "dread"])


class AdoptTargetTests(FixtureBase):
    def test_adopt_target_raises_target_depth_to_the_max(self):
        focus_merge.focus_merge("fear", "the-fear", adopt_target=True)
        self.assertEqual(self._find("fear")["target_depth"], 30)

    def test_adopt_target_never_lowers_the_survivors_target(self):
        self._set_roadmap([PRIMARY, _focus("fear", "Fear", ["K"], target_depth=40),
                           _focus("the-fear", "The Fear", ["L"], target_depth=5)])
        focus_merge.focus_merge("fear", "the-fear", adopt_target=True)
        self.assertEqual(self._find("fear")["target_depth"], 40)


# ---------------------------------------------------------------------------
# Dry run — prints everything, writes nothing
# ---------------------------------------------------------------------------

class DryRunTests(FixtureBase):
    def setUp(self):
        super().setUp()
        self._default_roster()

    def test_dry_run_leaves_the_vault_byte_for_byte_identical(self):
        before = self._vault_fingerprint()
        focus_merge.focus_merge("fear", "the-fear", dry_run=True)
        self.assertEqual(self._vault_fingerprint(), before)

    def test_dry_run_reports_it_applied_nothing(self):
        result = focus_merge.focus_merge("fear", "the-fear", dry_run=True)
        self.assertEqual(result["status"], "dry_run")
        self.assertFalse(result["applied"])

    def test_dry_run_prints_every_planned_step(self):
        result = focus_merge.focus_merge("fear", "the-fear", dry_run=True)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            focus_merge.print_plan(result["plan"], dry_run=True)
        printed = buffer.getvalue()
        for step in ("(b) roadmap", "(c) question bank", "(d) entity rosters",
                     "(e) curation settled ledger", "(f) wiki", "(g) audit", "(h) recompile"):
            self.assertIn(step, printed, f"dry-run plan is missing step {step}")
        # the concrete edits, not just the headings
        self.assertIn("['K'] → ['K', 'L']", printed)
        self.assertIn("## L: Focus — Fear", printed)
        self.assertIn("maps_to_focus the-fear → fear", printed)
        self.assertIn("remove wiki/themes/the-fear.md", printed)
        self.assertIn("[DRY RUN] nothing was written.", printed)

    def test_dry_run_plan_matches_what_the_real_merge_does(self):
        planned = focus_merge.focus_merge("fear", "the-fear", dry_run=True)["plan"]
        applied = focus_merge.focus_merge("fear", "the-fear")["plan"]
        self.assertEqual(planned["roadmap"], applied["roadmap"])
        self.assertEqual(planned["files_touched"], applied["files_touched"])
        self.assertEqual([e["line_after"] for e in planned["bank"]],
                         [e["line_after"] for e in applied["bank"]])


# ---------------------------------------------------------------------------
# Refusals — every one of them leaves the vault untouched
# ---------------------------------------------------------------------------

class RefusalTests(FixtureBase):
    def _assert_refused(self, survivor: str, loser: str, expected: str) -> None:
        before = self._vault_fingerprint()
        with self.assertRaises(focus_merge.FocusMergeError) as caught:
            focus_merge.focus_merge(survivor, loser)
        self.assertIn(expected, str(caught.exception))
        self.assertEqual(self._vault_fingerprint(), before,
                         "a refused merge must leave the vault byte-for-byte unchanged")

    def test_refuses_the_primary_focus_as_survivor(self):
        self._assert_refused("my-life", "fear", "cannot be a merge survivor")

    def test_refuses_the_primary_focus_as_loser(self):
        self._assert_refused("fear", "my-life", "cannot be a merge loser")

    def test_refuses_an_unknown_survivor(self):
        self._assert_refused("nope", "fear", "no such focus: 'nope'")

    def test_refuses_an_unknown_loser(self):
        self._assert_refused("fear", "nope", "no such focus: 'nope'")

    def test_refuses_a_self_merge(self):
        self._assert_refused("fear", "fear", "cannot absorb itself")

    def test_refuses_a_self_merge_that_only_differs_in_case(self):
        # "Fear" and "fear" slugify to the same id — the same ENTRY, so this
        # is a self-merge, not a duplicate pair.
        self._assert_refused("fear", "Fear", "cannot absorb itself")

    def test_a_refused_merge_writes_no_audit_record(self):
        with self.assertRaises(focus_merge.FocusMergeError):
            focus_merge.focus_merge("my-life", "fear")
        self.assertFalse(focus_merge.FOCUS_MERGES_FILE.exists())

    def test_rerunning_a_completed_merge_errors_cleanly(self):
        focus_merge.focus_merge("fear", "the-fear")
        after_first = self._vault_fingerprint()
        with self.assertRaises(focus_merge.FocusMergeError) as caught:
            focus_merge.focus_merge("fear", "the-fear")
        self.assertIn("no such focus: 'the-fear'", str(caught.exception))
        self.assertEqual(self._vault_fingerprint(), after_first,
                         "a re-run must not double-apply or corrupt the healed vault")


# ---------------------------------------------------------------------------
# Wiki — hand-authored pages are structurally untouchable
# ---------------------------------------------------------------------------

class WikiPageTests(FixtureBase):
    def test_hand_authored_page_is_left_in_place_with_a_warning(self):
        page = self._write_page("wiki/themes/the-fear.md", None, "The Fear")
        result = focus_merge.focus_merge("fear", "the-fear")
        self.assertTrue(page.exists(), "a hand-authored page must never be removed by a merge")
        self.assertEqual(result["plan"]["wiki"]["action"], "keep")
        self.assertTrue(any("hand-authored" in w for w in result["plan"]["warnings"]))
        self.assertTrue(any("origin: missing" in w for w in result["plan"]["warnings"]))

    def test_foreign_origin_page_is_left_in_place_with_a_warning(self):
        page = self._write_page("wiki/themes/the-fear.md", "mention", "The Fear")
        result = focus_merge.focus_merge("fear", "the-fear")
        self.assertTrue(page.exists())
        self.assertEqual(result["plan"]["wiki"]["action"], "keep")
        self.assertTrue(any("origin: mention" in w for w in result["plan"]["warnings"]))

    def test_a_kept_page_is_still_a_complete_merge_everywhere_else(self):
        self._write_page("wiki/themes/the-fear.md", None, "The Fear")
        focus_merge.focus_merge("fear", "the-fear")
        self.assertNotIn("the-fear", self._focus_ids())
        self.assertEqual(self._find("fear")["categories"], ["K", "L"])

    def test_missing_page_is_not_an_error(self):
        (self.tmp / "wiki" / "themes" / "the-fear.md").unlink()
        result = focus_merge.focus_merge("fear", "the-fear")
        self.assertEqual(result["plan"]["wiki"]["action"], "absent")
        self.assertEqual(result["status"], "merged")


# ---------------------------------------------------------------------------
# Rosters — the settled-ledger alias fallback
# ---------------------------------------------------------------------------

class RosterTests(FixtureBase):
    def test_loser_with_no_roster_entry_takes_the_settled_ledger_alias_path(self):
        # No roster files at all — nothing owns the survivor.
        result = focus_merge.focus_merge("fear", "the-fear")
        self.assertEqual(result["plan"]["roster_repoints"], [])
        self.assertEqual(result["plan"]["roster_aliases"], [])
        self.assertIn("the-fear", result["plan"]["ledger_aliases"])
        settled = json.loads(focus_curation.SETTLED_FILE.read_text(encoding="utf-8"))
        aliases = settled["focus_aliases"]["fear"]
        self.assertIn("the-fear", [a["alias"] for a in aliases])
        self.assertEqual(aliases[0]["focus_id"], "the-fear")

    def test_ledger_alias_path_still_settles_the_merge_decision(self):
        focus_merge.focus_merge("fear", "the-fear")
        settled = json.loads(focus_curation.SETTLED_FILE.read_text(encoding="utf-8"))
        self.assertEqual(settled["decisions"]["rec-the-fear"]["bucket"], "merge")

    def test_no_ledger_alias_when_a_survivor_roster_entry_absorbs_it(self):
        self._default_roster()
        result = focus_merge.focus_merge("fear", "the-fear")
        self.assertEqual(result["plan"]["ledger_aliases"], [])
        settled = json.loads(focus_curation.SETTLED_FILE.read_text(encoding="utf-8"))
        self.assertNotIn("focus_aliases", settled)

    def test_repoints_are_found_across_every_roster_type(self):
        self._set_roster("person", [
            {"name": "The Fear", "slug": "the-fear", "aliases": [], "qualifies": True,
             "maps_to_focus": "the-fear"},
        ])
        focus_merge.focus_merge("fear", "the-fear")
        roster = json.loads((entity_roster.ENTITY_DIR / "person.json").read_text(encoding="utf-8"))
        self.assertEqual(roster["entities"][0]["maps_to_focus"], "fear")


# ---------------------------------------------------------------------------
# The regression the whole verb rests on: a merged vault STAYS merged
# ---------------------------------------------------------------------------

class DeriveDoesNotResurrectTests(FixtureBase):
    """`derive_roadmap` runs on every `roadmap-rebuild` and on every
    `focus_new`. If it re-materialized the absorbed focus, a merge would
    silently un-merge itself — the single highest-cost failure this verb
    could have. Both orientations are pinned: the surviving id being the
    one the bank derives first is NOT something a merge can assume."""

    def _rebuild(self) -> list[str]:
        merged = roadmap.derive_roadmap(BANK, existing=roadmap.load_roadmap())
        return [f["id"] for f in merged["focuses"]]

    def test_merging_the_fear_into_fear_survives_a_rebuild(self):
        focus_merge.focus_merge("fear", "the-fear")
        ids = self._rebuild()
        self.assertNotIn("the-fear", ids)
        self.assertIn("fear", ids)

    def test_merging_fear_into_the_fear_survives_a_rebuild(self):
        # The reverse orientation: the SURVIVING id is not the one
        # derive_focuses' fold happens to pick first. Before the
        # settled-identity door in derive_roadmap, this resurrected the
        # absorbed focus on the next rebuild.
        focus_merge.focus_merge("the-fear", "fear")
        ids = self._rebuild()
        self.assertNotIn("fear", ids)
        self.assertIn("the-fear", ids)

    def test_the_rebuild_keeps_both_category_letters_on_the_survivor(self):
        focus_merge.focus_merge("the-fear", "fear")
        merged = roadmap.derive_roadmap(BANK, existing=roadmap.load_roadmap())
        survivor = next(f for f in merged["focuses"] if f["id"] == "the-fear")
        self.assertEqual(sorted(survivor["categories"]), ["K", "L"])

    def test_the_rebuild_leaves_the_dupes_report_clean(self):
        focus_merge.focus_merge("the-fear", "fear")
        rebuilt = roadmap.derive_roadmap(BANK, existing=roadmap.load_roadmap())
        self.assertEqual(focus_dupes.certain_focus_duplicates(rebuilt), [])

    def test_an_unmerged_vault_still_derives_both_focuses_independently(self):
        """The settled-identity door must not fold focuses that were never
        merged: two DIFFERENT names keep two entries."""
        self._set_roadmap([PRIMARY, _focus("fear", "Fear", ["K"]),
                           _focus("courage", "Courage", ["M"])])
        merged = roadmap.derive_roadmap(BANK, existing=roadmap.load_roadmap())
        ids = [f["id"] for f in merged["focuses"]]
        self.assertIn("fear", ids)
        self.assertIn("courage", ids)


class SettledIdentityDoorTests(unittest.TestCase):
    """Unit-level pins for roadmap._settled_key_owners / _settled_id_for —
    the derive_roadmap door ADR 0012 adds."""

    def test_owners_map_skips_the_primary_focus(self):
        owners = roadmap._settled_key_owners([
            {"id": "my-life", "label": "My Life", "primary": True},
            {"id": "the-fear", "label": "The Fear"},
        ])
        self.assertEqual(owners.get("fear"), "the-fear")
        self.assertNotIn("my-life", owners.values())

    def test_first_entry_wins_a_contested_key(self):
        owners = roadmap._settled_key_owners([
            {"id": "fear", "label": "Fear"},
            {"id": "fear-2", "label": "fear"},
        ])
        self.assertEqual(owners["fear"], "fear")

    def test_a_derived_id_already_in_the_roadmap_keeps_its_own_id(self):
        prior = {"fear": {"id": "fear"}}
        owners = {"fear": "the-fear"}
        self.assertEqual(roadmap._settled_id_for({"id": "fear", "label": "Fear"}, prior, owners), "fear")

    def test_a_new_derived_focus_adopts_the_settled_owner_id(self):
        self.assertEqual(
            roadmap._settled_id_for({"id": "fear", "label": "Fear"}, {}, {"fear": "the-fear"}),
            "the-fear")

    def test_an_uncontested_new_focus_keeps_its_own_id(self):
        self.assertEqual(
            roadmap._settled_id_for({"id": "courage", "label": "Courage"}, {}, {"fear": "the-fear"}),
            "courage")


# ---------------------------------------------------------------------------
# Scope 2 — the detection hint line
# ---------------------------------------------------------------------------

class DupesHintTests(FixtureBase):
    def test_certain_duplicates_carry_the_exact_focus_merge_command(self):
        report = focus_dupes.certain_focus_duplicates(roadmap.load_roadmap())
        self.assertEqual(len(report), 1)
        suggested = report[0]["suggested_merge"]
        self.assertEqual(suggested["survivor"], "fear")
        self.assertEqual(suggested["losers"], ["the-fear"])
        self.assertEqual(suggested["commands"], ["lifehug focus-merge fear the-fear"])

    def test_the_suggested_survivor_is_the_one_carrying_more_categories(self):
        self._set_roadmap([PRIMARY, _focus("fear", "Fear", ["K"]),
                           _focus("the-fear", "The Fear", ["L", "M"])])
        report = focus_dupes.certain_focus_duplicates(roadmap.load_roadmap())
        self.assertEqual(report[0]["suggested_merge"]["survivor"], "the-fear")

    def test_the_suggestion_is_deterministic_on_a_tie(self):
        self._set_roadmap([PRIMARY, _focus("the-fear", "The Fear", ["L"]),
                           _focus("fear", "Fear", ["K"])])
        first = focus_dupes.certain_focus_duplicates(roadmap.load_roadmap())
        second = focus_dupes.certain_focus_duplicates(roadmap.load_roadmap())
        self.assertEqual(first[0]["suggested_merge"], second[0]["suggested_merge"])
        self.assertEqual(first[0]["suggested_merge"]["survivor"], "fear")  # id order

    def test_the_printed_report_shows_the_heal_command(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            focus_dupes._print_report({
                "certain_focus_duplicates": focus_dupes.certain_focus_duplicates(roadmap.load_roadmap()),
                "near_name_pairs": [],
                "pending_idea_duplicates": [],
            })
        printed = buffer.getvalue()
        self.assertIn("heal: lifehug focus-merge fear the-fear", printed)
        self.assertIn("--dry-run", printed)

    def test_the_report_still_writes_nothing_with_the_hint(self):
        before = self._vault_fingerprint()
        focus_dupes.certain_focus_duplicates(roadmap.load_roadmap())
        self.assertEqual(self._vault_fingerprint(), before)


# ---------------------------------------------------------------------------
# Scope 1 — the job-queue envelope
# ---------------------------------------------------------------------------

class JobEnvelopeTests(unittest.TestCase):
    def setUp(self):
        import jobs
        self.jobs = jobs

    def test_focus_merge_is_a_registered_command(self):
        self.assertIn("focus-merge", self.jobs.COMMANDS)
        self.assertIn("focus-merge", self.jobs.ALLOWED_COMMANDS)

    def test_the_envelope_is_never_retried(self):
        self.assertEqual(self.jobs.COMMANDS["focus-merge"].retry_safety, "never")

    def test_a_valid_payload_builds_the_cli_invocation(self):
        (invocation,) = self.jobs.COMMANDS["focus-merge"].build(
            {"survivor": "fear", "loser": "the-fear"})
        self.assertEqual(invocation.kind, "lifehug-cli")
        self.assertEqual(invocation.arguments, ("focus-merge", "fear", "the-fear"))

    def test_adopt_target_rides_the_envelope(self):
        (invocation,) = self.jobs.COMMANDS["focus-merge"].build(
            {"survivor": "fear", "loser": "the-fear", "adopt_target": True})
        self.assertEqual(invocation.arguments, ("focus-merge", "fear", "the-fear", "--adopt-target"))

    def test_a_self_merge_payload_is_rejected(self):
        with self.assertRaises(ValueError):
            self.jobs.COMMANDS["focus-merge"].build({"survivor": "fear", "loser": "fear"})

    def test_a_path_shaped_focus_id_is_rejected(self):
        for bad in ("../etc/passwd", "fear/../x", "fear;rm -rf /", ""):
            with self.assertRaises(ValueError):
                self.jobs.COMMANDS["focus-merge"].build({"survivor": bad, "loser": "the-fear"})

    def test_an_unknown_payload_key_is_rejected(self):
        with self.assertRaises(ValueError):
            self.jobs.COMMANDS["focus-merge"].build(
                {"survivor": "fear", "loser": "the-fear", "compile": True})

    def test_the_command_takes_the_writer_lock(self):
        import lifehug
        self.assertIn("focus-merge", lifehug.DIRECT_MUTATION_COMMANDS)


# ---------------------------------------------------------------------------
# Scope 3 — the viewer's Combine affordance
# ---------------------------------------------------------------------------

class ViewerCombineTests(FixtureBase):
    def setUp(self):
        super().setUp()
        import serve_wiki
        self.serve_wiki = serve_wiki
        self._saved_load = serve_wiki.load_roadmap
        serve_wiki.load_roadmap = roadmap.load_roadmap

    def tearDown(self):
        self.serve_wiki.load_roadmap = self._saved_load
        super().tearDown()

    def test_the_lane_renders_a_combine_form_per_duplicate_pair(self):
        body = self.serve_wiki._duplicate_focuses_section_html()
        self.assertIn('action="/actions/focus-merge"', body)
        self.assertIn("Combine", body)
        self.assertIn('name="survivor"', body)
        self.assertIn('value="fear,the-fear"', body)

    def test_the_survivor_picker_is_seeded_with_the_dupes_reports_suggestion(self):
        body = self.serve_wiki._duplicate_focuses_section_html()
        self.assertIn('<option value="fear" selected>', body)

    def test_the_lane_reads_empty_once_the_pair_is_healed(self):
        focus_merge.focus_merge("fear", "the-fear")
        body = self.serve_wiki._duplicate_focuses_section_html()
        self.assertIn("No duplicate focuses", body)
        self.assertNotIn("Combine", body)

    def test_the_action_enqueues_one_merge_job_per_loser(self):
        enqueued: list[tuple[str, dict]] = []
        saved = self.serve_wiki._start_job
        self.serve_wiki._start_job = lambda kind, payload: (
            enqueued.append((kind, payload)) or {"id": "job-1"})
        try:
            path, flash, job_id = self.serve_wiki.act_focus_merge(
                {"survivor": ["fear"], "group": ["fear,the-fear"], "_token": ["t"]})
        finally:
            self.serve_wiki._start_job = saved
        self.assertEqual(path, "/views/review")
        self.assertEqual(enqueued, [("focus-merge", {"survivor": "fear", "loser": "the-fear"})])
        self.assertIn("the-fear → fear", flash)
        self.assertEqual(job_id, "job-1")

    def test_the_action_recomputes_losers_and_refuses_a_survivor_outside_the_group(self):
        called: list = []
        saved = self.serve_wiki._start_job
        self.serve_wiki._start_job = lambda kind, payload: called.append((kind, payload))
        try:
            _path, flash, job_id = self.serve_wiki.act_focus_merge(
                {"survivor": ["my-life"], "group": ["fear,the-fear"], "_token": ["t"]})
        finally:
            self.serve_wiki._start_job = saved
        self.assertEqual(called, [], "a survivor outside the rendered group must enqueue nothing")
        self.assertIn("pick which focus to keep", flash)
        self.assertIsNone(job_id)

    def test_the_action_refuses_a_single_focus_group(self):
        called: list = []
        saved = self.serve_wiki._start_job
        self.serve_wiki._start_job = lambda kind, payload: called.append((kind, payload))
        try:
            _path, flash, _job = self.serve_wiki.act_focus_merge(
                {"survivor": ["fear"], "group": ["fear"], "_token": ["t"]})
        finally:
            self.serve_wiki._start_job = saved
        self.assertEqual(called, [])
        self.assertIn("nothing to combine", flash)

    def test_the_route_is_registered(self):
        self.assertIs(self.serve_wiki.ACTIONS["/actions/focus-merge"],
                      self.serve_wiki.act_focus_merge)


class OpaqueOriginPostTests(unittest.TestCase):
    """Regression for the pre-existing viewer defect this PR had to fix
    before the Combine button could work in a browser at all.

    `send_owner_headers` sets `Referrer-Policy: no-referrer`, and Chromium
    serializes the Origin of a form-POST navigation as the literal string
    "null" under that policy. `_post_allowed` rejected it, so EVERY POST
    action in the viewer answered 403 in a Chromium-family browser —
    reproduced on clean origin/main with the untouched candidate-Promote
    button. An opaque origin now falls through to the session-token check,
    exactly as an absent Origin already did; a WRONG origin still fails."""

    def setUp(self):
        import serve_wiki
        self.serve_wiki = serve_wiki

    class _FakeServer:
        server_address = ("127.0.0.1", 8765)

    def _handler(self, headers: dict):
        serve_wiki = self.serve_wiki

        class Fake:
            _post_allowed = serve_wiki.Handler._post_allowed

            def __init__(self, hdrs):
                self.headers = hdrs
                self.server = OpaqueOriginPostTests._FakeServer()

        return Fake(headers)

    def _allowed(self, origin: str | None, *, token: str | None = None) -> bool:
        headers = {"Host": "127.0.0.1:8765"}
        if origin is not None:
            headers["Origin"] = origin
        form = {"_token": [token if token is not None else self.serve_wiki.SESSION_TOKEN]}
        return self._handler(headers)._post_allowed(form)

    def test_an_opaque_null_origin_is_accepted_with_a_valid_token(self):
        self.assertTrue(self._allowed("null"))

    def test_an_absent_origin_is_still_accepted(self):
        self.assertTrue(self._allowed(None))

    def test_a_matching_loopback_origin_is_still_accepted(self):
        self.assertTrue(self._allowed("http://127.0.0.1:8765"))

    def test_a_foreign_origin_is_still_rejected(self):
        self.assertFalse(self._allowed("http://evil.example.com"))

    def test_a_loopback_origin_on_the_wrong_port_is_still_rejected(self):
        self.assertFalse(self._allowed("http://127.0.0.1:9999"))

    def test_an_opaque_origin_without_a_valid_token_is_still_rejected(self):
        """The token, not the Origin, is the CSRF defense — an opaque origin
        buys an attacker nothing."""
        self.assertFalse(self._allowed("null", token="not-the-token"))

    def test_a_missing_origin_without_a_valid_token_is_still_rejected(self):
        self.assertFalse(self._allowed(None, token=""))


# ---------------------------------------------------------------------------
# Scope 5 — shipped-artifact bookkeeping
# ---------------------------------------------------------------------------

class ManifestTests(unittest.TestCase):
    def test_focus_merges_is_a_registered_vault_data_path(self):
        contract = json.loads((SYSTEM / "vault_contract.json").read_text(encoding="utf-8"))
        entry = contract["data_paths"]["focus_merges"]
        self.assertEqual(entry["path"], "state/focus_merges.json")
        self.assertTrue(entry["tracked"])
        self.assertFalse(entry["required"])
        self.assertEqual(entry["schema"]["supported"], [1])

    def test_focus_merges_is_vault_data_never_a_framework_file(self):
        version = json.loads((SYSTEM / "version.json").read_text(encoding="utf-8"))
        self.assertNotIn("state/focus_merges.json", version["framework_files"])

    def test_the_verb_module_is_a_framework_file(self):
        version = json.loads((SYSTEM / "version.json").read_text(encoding="utf-8"))
        self.assertIn("system/focus_merge.py", version["framework_files"])

    def test_adr_0012_exists(self):
        self.assertTrue((ROOT / "docs" / "adr" / "0012-focus-merge.md").exists())

    def test_the_walkthrough_has_a_make_target(self):
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("walkthrough-focus-merge:", makefile)
        self.assertTrue((ROOT / "tests" / "walkthrough_focus_merge.py").exists())


if __name__ == "__main__":
    unittest.main()
