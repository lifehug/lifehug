"""Event identity I2c — the containment authority UPGRADE.

Controlling design: lifehug-platform `docs/design/event-identity.md` **v4.2**,
amendment §12b ruling 6, whose own sentence is already in the code:
`episode_fold_contract.CONTAINMENT_AUTHORITY_RULE_TEXT` — *"the authority flag
chooses one field — `origin` — and that field is outside the binding digest,
so flipping it re-keys nothing, rewrites no evidence and moves no file"*.

**The live defect this closes.** A vault ran `bind-episodes --apply` before its
host had the drag-out gesture, so the containment rung filed at the DEFAULT
authority and every record landed `origin: "proposed"`. Once drag was live and
the placements were reviewed, the sanctioned re-run —
`bind-episodes --apply --containment-authority applied` — did NOTHING:

* I3c's filter drops a containment row whose (telling, episode) pair already
  carries an active binding, and the rung's OWN earlier record is such a
  binding, so the row never reached a writer at all; and
* had it reached one, `file_event_identity`'s canonical-bytes create-or-keep
  would have kept the proposal, because the two authorities mint the SAME
  ``identity_id`` and therefore the same path.

The run then reported ``containment_members: 0`` — which reads as *the rung
found nothing*, the exact misreading `episode_fold_contract.containment_origin`
refuses an unknown authority in order to prevent. `episode_fold` kept
publishing the records as ``proposed_links`` (soft "possibly…" rows) because
``GROUPING_ORIGINS`` excludes ``proposed``, so a container card counting only
``containments`` showed zero members over a vault that held twenty.

**The semantics chosen, and the half that is deliberately not symmetric**
(`episode_fold_contract.CONTAINMENT_AUTHORITY_UPGRADE_RULE_TEXT`): `proposed`
→ `deterministic` moves IN PLACE — same file, same identity_id, same evidence,
the original ``created_at`` preserved, one field — and is counted as an
upgrade rather than a creation, because nothing was decided that was not
decided before. `deterministic` → `proposed` is not a move at all: it is KEPT
and counted, because a host that forgot its flag must not silently un-draw a
containment a person can already see and already drag out. Anything differing
beyond ``origin`` is not an upgrade target and ordinary create-or-keep stands.

Every negative below was run against a build with its guard removed — the
``ORIGIN_UPGRADES`` patch in :class:`TheDefectTests` is that build, run
in-process — and SEEN failing first.

Synthetic data only. The record SHAPE in :data:`FOUNDER_SHAPED_RECORD` is the
shape a real vault's proposed containments actually carry, read from a
read-only clone; every ref, name, date and quote in it is invented.
"""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import episode_binder as eb  # noqa: E402
import episode_containers as ec  # noqa: E402
import episode_fold as ef  # noqa: E402
import episode_fold_contract as efc  # noqa: E402
import event_identity as ei  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

NOW = "2026-08-31T12:00:00Z"
LATER = "2027-03-04T08:00:00Z"

BINDINGS_DIR = "state/temporal_claims/identities/bindings"


# --------------------------------------------------------------------------
# The fixture — one container and the tellings that name it
# --------------------------------------------------------------------------

ROSTERS = {
    "theme": {"type": "theme", "entities": [
        {"name": "Halcyon", "slug": "halcyon", "aliases": ["Halcyon Works"]},
    ]},
}


def revision(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def value(text: str) -> dict:
    grain = {4: "year", 7: "month", 10: "day"}[len(text)]
    return {"best": text, "earliest": text, "latest": text, "granularity": grain,
            "basis": "stated", "confidence": "certain"}


def claim(*, source: str, **overrides) -> dict:
    if overrides.get("event_mention") and "event_ref" not in overrides:
        overrides["event_ref"] = tp.derive_node_id(
            node_kind="event", event_kind=overrides.get("event_kind") or "moment",
            subject_refs=["I"], discriminator=source,
        )
    payload = {
        "source_kind": "conversation",
        "source_ref": {"source_id": source, "revision": revision(source)},
        "evidence": [{"quote": overrides.pop("quote", "a sentence somebody said")}],
        "extractor_version": "classifier:1",
        "created_at": "2026-08-30T00:00:00Z",
        "basis": "explicit",
        "confidence": 0.9,
        "status": "active",
        "claim_type": "occurrence",
        "subject_mention": "I",
    }
    payload.update(overrides)
    return tc.validate_temporal_claim(payload)


MEMBERS = ("classification:answers-a1#aaa1", "classification:answers-a2#aaa2",
           "classification:answers-a3#aaa3")


def base_claims() -> list:
    return [
        claim(source="landmark:entry-birth", claim_type="date",
              subject_mention="birth", event_kind="birth",
              temporal_value=value("1981-07-11"), quote="I was born 11 July 1981."),
        # The container: the subject IS the thing, and `started` opens a span.
        claim(source="landmark:entry-halcyon", claim_type="date",
              subject_mention="Halcyon", event_kind="started",
              temporal_value=value("2022-05"), quote="Halcyon, May 2022 - Present"),
        # Three members: they name the entity inside a sentence and are undated.
        claim(source=MEMBERS[0], event_mention="Started Halcyon",
              event_kind="moment", quote="We started Halcyon in a garage."),
        claim(source=MEMBERS[1], event_mention="Halcyon's first hire",
              event_kind="moment", quote="Halcyon's first hire."),
        claim(source=MEMBERS[2], event_mention="Halcyon Works moved offices",
              event_kind="moment", quote="Halcyon Works moved offices."),
    ]


def seed(root: Path) -> None:
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "sources").mkdir(parents=True, exist_ok=True)
    by_source: dict = {}
    for row in base_claims():
        key = (row["source_ref"]["source_id"], row["source_ref"]["revision"],
               row["extractor_version"])
        by_source.setdefault(key, []).append(row)
    for (_id, _rev, extractor), rows in sorted(by_source.items()):
        ts.write_receipt(root, {
            "source_ref": rows[0]["source_ref"], "extractor_version": extractor,
            "created_at": "2026-08-30T00:00:00Z",
            "claims": [dict(row) for row in rows],
        })
    ts.rebuild_active_index(root)
    directory = root / "state" / "entity_rosters"
    directory.mkdir(parents=True, exist_ok=True)
    for kind, snapshot in ROSTERS.items():
        (directory / f"{kind}.json").write_text(json.dumps(snapshot), "utf-8")


def bindings_on_disk(root: Path) -> dict:
    """``{filename: parsed record}`` — what the vault actually holds."""
    found = {}
    for path in sorted((root / BINDINGS_DIR).glob("*.json")):
        found[path.name] = json.loads(path.read_text("utf-8"))
    return found


def vault_bytes(root: Path) -> dict:
    """``{relative path: sha256}`` for EVERY file — the no-op comparison."""
    return {
        path.relative_to(root).as_posix():
        hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def fold_blocks(root: Path) -> tuple[int, int]:
    """``(containments, proposed_links)`` the drawing publishes."""
    index = ts.fold_active_index(root)
    claims = [row for row in index.get("claims") or () if isinstance(row, dict)]
    found = tt.derive_calculated_timeline(
        {"version": ts.INDEX_VERSION, "claims": claims},
        episode_records=ef.load_episode_records(root), now=NOW,
    )
    return (sum(len(node.get("containments") or ()) for node in found.nodes),
            sum(len(node.get("proposed_links") or ()) for node in found.nodes))


class VaultCase(unittest.TestCase):
    """A vault that has already run `--apply` at the DEFAULT authority — the
    state the live defect was found in."""

    authority_first = "proposed"

    def setUp(self) -> None:
        self.root = root_parent_tmp(self, ROOT, prefix="i2c-")
        seed(self.root)
        self.first = eb.bind_episodes(
            self.root, apply=True, now=NOW,
            containment_authority=self.authority_first)

    def rerun(self, authority: str, *, now: str = LATER, apply: bool = True) -> dict:
        return eb.bind_episodes(self.root, apply=apply, now=now,
                                containment_authority=authority)


# ==========================================================================
# The vault the defect was found in
# ==========================================================================


class TheProposedVaultTests(VaultCase):
    def test_the_first_run_files_proposals_the_fold_will_not_draw(self):
        filed = bindings_on_disk(self.root)
        self.assertTrue(filed)
        for record in filed.values():
            self.assertEqual(record["origin"], "proposed")
            self.assertEqual(record["relation"], "part_of")
            self.assertIn(record["rule_id"], ec.DETERMINISTIC_CONTAINMENT_RULE_IDS)
        containments, proposed = fold_blocks(self.root)
        self.assertEqual(containments, 0)
        self.assertEqual(proposed, len(filed))

    def test_proposed_is_outside_the_grouping_origins_the_fold_draws(self):
        """The one-line reason a container card counted zero members."""
        self.assertNotIn("proposed", efc.GROUPING_ORIGINS)
        self.assertEqual(efc.CONTAINMENT_ORIGIN_BY_AUTHORITY["proposed"], "proposed")
        self.assertEqual(efc.CONTAINMENT_ORIGIN_BY_AUTHORITY["applied"], "deterministic")


# ==========================================================================
# The defect, and the guard proven to fire
# ==========================================================================


class TheDefectTests(VaultCase):
    """What the sanctioned re-run did BEFORE this change — the build with the
    guard removed, run in-process by emptying the one tuple that admits the
    move. Every assertion here is the behaviour the live vault exhibited."""

    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(setattr, efc, "ORIGIN_UPGRADES", efc.ORIGIN_UPGRADES)
        efc.ORIGIN_UPGRADES = ()

    def test_the_re_run_at_applied_authority_changed_nothing(self):
        before = vault_bytes(self.root)
        second = self.rerun("applied")
        self.assertEqual(vault_bytes(self.root), before)
        self.assertEqual(second["filed"]["upgraded"], [])
        for record in bindings_on_disk(self.root).values():
            self.assertEqual(record["origin"], "proposed")

    def test_and_reported_zero_members_which_reads_as_found_nothing(self):
        second = self.rerun("applied")
        self.assertEqual(second["plan"].counts["containment_members"], 0)
        self.assertEqual(second["plan"].counts["containment_upgrades"], 0)

    def test_and_the_fold_still_published_proposed_links(self):
        self.rerun("applied")
        containments, proposed = fold_blocks(self.root)
        self.assertEqual(containments, 0)
        self.assertEqual(proposed, len(bindings_on_disk(self.root)))


# ==========================================================================
# The upgrade — in place, one field, same file
# ==========================================================================


class UpgradeTests(VaultCase):
    def test_the_re_run_upgrades_every_filed_proposal(self):
        before = bindings_on_disk(self.root)
        second = self.rerun("applied")
        self.assertEqual(sorted(second["filed"]["upgraded"]),
                         sorted(record["identity_id"] for record in before.values()))
        self.assertEqual(second["filed"]["created"], 0)
        self.assertEqual(second["plan"].counts["containment_upgrades"], len(before))

    def test_it_is_the_same_file_and_the_same_identity(self):
        """*"flipping it re-keys nothing … and moves no file"* — proven on the
        filenames and the ids, not on the promise."""
        before = bindings_on_disk(self.root)
        self.rerun("applied")
        after = bindings_on_disk(self.root)
        self.assertEqual(sorted(after), sorted(before))
        for name, record in after.items():
            self.assertEqual(record["identity_id"], before[name]["identity_id"])
            self.assertEqual(f"{BINDINGS_DIR}/{name}",
                             ei.binding_relative_path(record["origin"],
                                                      record["identity_id"]))

    def test_exactly_one_field_moved(self):
        """Evidence, rule, candidates, claim ids, status — and the CLOCK. The
        decision's own `created_at` is the bytes already on disk, never the
        re-derivation's, or "when was this decided" would become "when was it
        last re-filed"."""
        before = bindings_on_disk(self.root)
        self.rerun("applied")
        for name, record in bindings_on_disk(self.root).items():
            self.assertEqual(record["origin"], "deterministic")
            self.assertEqual(before[name]["origin"], "proposed")
            self.assertEqual(record["created_at"], before[name]["created_at"])
            self.assertNotEqual(record["created_at"], LATER)
            self.assertEqual({k: v for k, v in record.items() if k != "origin"},
                             {k: v for k, v in before[name].items() if k != "origin"})

    def test_the_fold_now_publishes_containments(self):
        filed = len(bindings_on_disk(self.root))
        self.rerun("applied")
        containments, proposed = fold_blocks(self.root)
        self.assertEqual(containments, filed)
        self.assertEqual(proposed, 0)

    def test_the_records_never_leave_state(self):
        """`bindings_dir` sends both origins to the same directory, which is
        why this is an upgrade and not a move; CERT-11's promise is that
        deleting `state/` still removes only what a rule can re-derive."""
        self.rerun("applied")
        for path in self.root.rglob("*.json"):
            if "identities/bindings" in path.as_posix():
                self.assertTrue(path.relative_to(self.root).as_posix()
                                .startswith("state/"), path)


# ==========================================================================
# Idempotency, and the direction that is NOT a move
# ==========================================================================


class IdempotencyTests(VaultCase):
    def test_a_second_applied_run_is_a_byte_identical_no_op(self):
        self.rerun("applied")
        before = vault_bytes(self.root)
        third = self.rerun("applied", now="2028-01-01T00:00:00Z")
        self.assertEqual(vault_bytes(self.root), before)
        self.assertEqual(third["filed"]["upgraded"], [])
        self.assertEqual(third["filed"]["created"], 0)
        self.assertEqual(third["filed"]["not_upgraded"], [])

    def test_a_run_back_at_proposed_keeps_the_stronger_record_and_counts_it(self):
        """The half that is deliberately not symmetric. A host that forgot its
        flag does not un-draw what a person can already see."""
        self.rerun("applied")
        before = vault_bytes(self.root)
        fourth = self.rerun("proposed", now="2029-01-01T00:00:00Z")
        self.assertEqual(vault_bytes(self.root), before)
        self.assertEqual(len(fourth["filed"]["kept_stronger"]),
                         len(bindings_on_disk(self.root)))
        self.assertEqual(fourth["plan"].counts["containment_kept_stronger"],
                         len(bindings_on_disk(self.root)))
        for record in bindings_on_disk(self.root).values():
            self.assertEqual(record["origin"], "deterministic")

    def test_the_keep_is_visible_in_the_report_not_only_in_the_counts(self):
        self.rerun("applied")
        text = "\n".join(eb.describe(self.rerun("proposed", apply=False)["plan"]))
        self.assertIn("kept at deterministic", text)
        for identity_id in {row["identity_id"]
                            for row in bindings_on_disk(self.root).values()}:
            self.assertIn(identity_id, text)

    def test_the_upgrade_is_announced_by_the_dry_run_which_writes_nothing(self):
        """The rollout gate's owner-reviewed dry run must be able to review the
        upgrade, or the only way to learn what moves is to move it."""
        before = vault_bytes(self.root)
        outcome = eb.binder_step(self.root, now=LATER,
                                 containment_authority="applied")
        self.assertEqual(vault_bytes(self.root), before)
        self.assertFalse(outcome["wrote"])
        self.assertEqual(len(outcome["containment_upgrades"]),
                         len(bindings_on_disk(self.root)))
        self.assertIn("upgrade to deterministic",
                      "\n".join(eb.describe(self.rerun("applied", apply=False)["plan"])))


# ==========================================================================
# What is NOT an upgrade target
# ==========================================================================


class NotAnUpgradeTests(VaultCase):
    def one_record(self) -> dict:
        filed = bindings_on_disk(self.root)
        name = sorted(filed)[0]
        return {"name": name, **filed[name]}

    def test_a_record_differing_in_anything_besides_origin_is_kept(self):
        """Create-or-keep is unchanged for a record that says something else:
        the difference is REPORTED, never resolved by an origin flip."""
        row = self.one_record()
        path = self.root / BINDINGS_DIR / row["name"]
        payload = json.loads(path.read_text("utf-8"))
        payload["evidence"] = dict(payload["evidence"])
        payload["evidence"]["reason"] = "something an earlier rule believed"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True,
                                   ensure_ascii=False) + "\n", "utf-8")
        before = vault_bytes(self.root)
        record, outcome = ei.refile_event_identity(self.root, **{
            **{k: v for k, v in row.items() if k not in ("name", "relative_path")},
            "origin": "deterministic", "created_at": LATER,
        })
        self.assertEqual(outcome, "kept_differs")
        self.assertEqual(record["origin"], "proposed")
        self.assertEqual(vault_bytes(self.root), before)

    def test_bytes_an_older_normalization_wrote_are_kept_not_re_normalized(self):
        """The upgrade is proved on the BYTES. A file this version would not
        write for this record is `kept_differs`, so an origin flip can never
        smuggle a re-normalization in with it."""
        row = self.one_record()
        path = self.root / BINDINGS_DIR / row["name"]
        payload = json.loads(path.read_text("utf-8"))
        # Same record, different serialization — exactly the shape a version
        # that indented differently would have left behind.
        path.write_text(json.dumps(payload, indent=4, sort_keys=True) + "\n", "utf-8")
        before = vault_bytes(self.root)
        _record, outcome = ei.refile_event_identity(self.root, **{
            **{k: v for k, v in row.items() if k not in ("name", "relative_path")},
            "origin": "deterministic", "created_at": LATER,
        })
        self.assertEqual(outcome, "kept_differs")
        self.assertEqual(vault_bytes(self.root), before)

    def test_the_plain_door_never_upgrades(self):
        """Audit A6's create-or-keep is literally untouched: the door that does
        not ask for an upgrade does not get one."""
        row = self.one_record()
        before = vault_bytes(self.root)
        record, created = ei.file_event_identity(self.root, **{
            **{k: v for k, v in row.items() if k not in ("name", "relative_path")},
            "origin": "deterministic", "created_at": LATER,
        })
        self.assertFalse(created)
        self.assertEqual(record["origin"], "proposed")
        self.assertEqual(vault_bytes(self.root), before)

    def test_a_persons_own_answer_on_the_pair_stays_filtered_and_untouched(self):
        """I3c's invariant, unchanged. A pair a person has answered `same` on
        is never re-placed by the containment rung, and the upgrade path does
        not reach it either: it is not this rung's own record wearing the other
        authority, it is somebody's decision. Nothing under `sources/` moves,
        and the vault still loads clean."""
        import identity_questions as iq  # noqa: PLC0415

        member = MEMBERS[0]
        row = next(record for record in bindings_on_disk(self.root).values()
                   if record["telling_ref"] == member)
        iq.resolve_same_event_answer(
            self.root, telling_ref=member,
            candidate_telling_ref="landmark:entry-halcyon",
            answer="same", now=NOW,
        )
        human_before = {name: digest for name, digest in vault_bytes(self.root).items()
                        if name.startswith("sources/identity/")}
        self.assertTrue(human_before, "the person's own decision is on disk")

        second = self.rerun("applied")
        self.assertNotIn(row["identity_id"], set(second["filed"]["upgraded"]))
        placed = {member["telling_ref"] for block in second["plan"].containments
                  for member in block["members"]}
        self.assertNotIn(member, placed, "the answered pair was re-placed")
        self.assertTrue(placed, "the run still places the members nobody answered")
        self.assertEqual(
            {name: digest for name, digest in vault_bytes(self.root).items()
             if name.startswith("sources/identity/")},
            human_before, "the person's decision was rewritten")
        # And the vault still loads: no resurrected `part_of` beside the `same`.
        self.assertTrue(efc.active_binding_index(
            ei.load_event_identities(self.root)))

    def test_the_fold_still_loads_clean_after_the_upgrade(self):
        """The upgrade must never write a state the fold refuses: it moves an
        origin, and `active_binding_index` refuses relations that disagree."""
        self.rerun("applied")
        index = efc.active_binding_index(ei.load_event_identities(self.root))
        self.assertTrue(index)
        eb.bind_episodes(self.root, apply=False, now=LATER,
                         containment_authority="applied")


# ==========================================================================
# The record shape a real vault carries
# ==========================================================================


#: The SHAPE of a proposed containment as one is actually filed — every key,
#: in the order a filed record holds them. Content invented; shape read from a
#: read-only clone of a vault that hit the live defect.
FOUNDER_SHAPED_RECORD = {
    "candidates": ["episode:5f85ce8a80b267a55e9feb3a"],
    "claim_ids_at_bind": [],
    "created_at": "2026-08-31T07:51:52Z",
    "episode_id": "episode:5f85ce8a80b267a55e9feb3a",
    "evidence": {
        "entities": ["theme/halcyon"],
        "episode_quote": "Halcyon",
        "reason": ("shares theme/halcyon with Halcyon (after May 2022, "
                   "open-ended), and is undated, so the span cannot be "
                   "contradicted"),
        "signals": ["entity"],
        "span": "after May 2022",
        "telling_quote": "Tidewheel became Halcyon",
    },
    "operation_id": None,
    "origin": "proposed",
    "record_type": "event_identity",
    "relation": "part_of",
    "rule_id": "entity_span",
    "rule_version": "event-identity:1",
    "schema_version": 1,
    "source_ref": None,
    "status": "active",
    "supersedes": None,
    "telling_aliases": [],
    "telling_ref": "classification:sources-manual-2026-08-24-a-garage#ba8a0d9c2f76",
}


class RealShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = root_parent_tmp(self, ROOT, prefix="i2c-shape-")
        (self.root / "state").mkdir(parents=True, exist_ok=True)
        (self.root / "sources").mkdir(parents=True, exist_ok=True)
        payload = {k: v for k, v in FOUNDER_SHAPED_RECORD.items()
                   if k != "identity_id"}
        self.record, created = ei.file_event_identity(self.root, **payload)
        self.assertTrue(created)
        self.path = self.root / self.record["relative_path"]

    def test_the_shape_a_real_vault_holds_is_a_valid_proposed_containment(self):
        self.assertEqual(self.record["origin"], "proposed")
        self.assertEqual(self.record["relation"], "part_of")
        self.assertEqual(self.record["rule_id"], efc.RULE_ID_ENTITY_SPAN)
        self.assertTrue(self.path.is_file())

    def test_it_upgrades_in_place_to_a_record_the_write_door_admits(self):
        """C2's origin gate admits `deterministic` `part_of` for exactly the
        two evidence-grade rule ids, and `entity_span` is one of them — so the
        upgraded record is not merely written, it is VALID."""
        before = json.loads(self.path.read_text("utf-8"))
        record, outcome = ei.refile_event_identity(self.root, **{
            **{k: v for k, v in FOUNDER_SHAPED_RECORD.items()
               if k != "identity_id"},
            "origin": "deterministic", "created_at": LATER,
        })
        self.assertEqual(outcome, "upgraded")
        self.assertEqual(record["identity_id"], self.record["identity_id"])
        after = json.loads(self.path.read_text("utf-8"))
        self.assertEqual(after["origin"], "deterministic")
        self.assertEqual(after["created_at"], before["created_at"])
        self.assertEqual({k: v for k, v in after.items() if k != "origin"},
                         {k: v for k, v in before.items() if k != "origin"})
        self.assertIsNotNone(ei.read_event_identity(
            self.root, record["relative_path"]))
        self.assertIn(after["origin"], efc.GROUPING_ORIGINS)


# ==========================================================================
# The vocabulary
# ==========================================================================


class VocabularyTests(unittest.TestCase):
    def test_the_admitted_move_has_one_home(self):
        import re

        pattern = re.compile(r"^ORIGIN_UPGRADES\s*=", re.MULTILINE)
        owners = [path.name for path in (ROOT / "system").glob("*.py")
                  if pattern.search(path.read_text("utf-8"))]
        self.assertEqual(owners, ["episode_fold_contract.py"])

    def test_origin_move_names_all_four_cases(self):
        self.assertEqual(efc.origin_move("proposed", "deterministic"), "upgrade")
        self.assertEqual(efc.origin_move("deterministic", "proposed"), "downgrade")
        self.assertEqual(efc.origin_move("proposed", "proposed"), "same")
        self.assertEqual(efc.origin_move("stated", "deterministic"), "unrelated")
        self.assertEqual(efc.origin_move("confirmed", "proposed"), "unrelated")

    def test_only_the_one_move_is_admitted(self):
        """A widening here is a design decision, not a patch: every other pair
        of origins either says nothing changed or is a person's decision being
        overwritten by a rule."""
        self.assertEqual(efc.ORIGIN_UPGRADES, (("proposed", "deterministic"),))
        for left in efc.ORIGINS:
            for right in efc.ORIGINS:
                if (left, right) != ("proposed", "deterministic"):
                    self.assertNotEqual(efc.origin_move(left, right), "upgrade")

    def test_the_rule_text_says_both_halves(self):
        text = efc.CONTAINMENT_AUTHORITY_UPGRADE_RULE_TEXT
        self.assertIn("IN PLACE", text)
        self.assertIn("KEEPS", text)
        self.assertIn("created_at", text)

    def test_every_outcome_the_writer_returns_is_enumerated(self):
        self.assertEqual(set(efc.BINDING_FILING_OUTCOMES),
                         {"created", "upgraded", "kept", "kept_stronger",
                          "kept_differs"})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
