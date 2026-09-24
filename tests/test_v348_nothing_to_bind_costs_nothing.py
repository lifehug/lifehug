"""v348 — nothing to bind costs nothing.

On the owner's vault (~2000 claims, ~1190 nodes) `bind-episodes --apply`
measured 187s wall on a fast Mac and 300-450s on the hosted 2-vCPU worker
(2026-09-24) — even immediately after a full sweep had already applied
everything and there was nothing new to file. Every timeline answer rides a
file-claims job that runs this binder, so ten answers cost ten full
derivations serialized through one vault lease.

THE RULE (`episode_binder.NOTHING_TO_BIND_COSTS_NOTHING`): a pass whose
CHEAP signature — the telling manifest's digest, the bindings store's
digest, `episode_binder.RULE_VERSION` and
`temporal_timeline.CALCULATION_RULE_VERSION` — matches the receipt the last
successful `--apply` left under `state/temporal_claims/binder_receipt.json`
does no derivation at all: no `fold_derivation`, no `plan()`. It returns
that apply's own summary with `applied: False, reason: "nothing_new"`. Any
difference — a new or changed telling, a changed binding, a moved rule
version, or no receipt at all — is the full pass, exactly as before this
release.

This suite guards three things: the digest/receipt machinery as units, the
fast path over a vault built and bound through the real verbs (fresh pass,
no-op pass, pass after one new telling — the audit invariants v340 and v342
guard must hold across all three), and the CLI wiring in `lifehug.py` that
prints `reason: "nothing_new"` rather than pretending a run applied
something it never derived.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import episode_binder as eb  # noqa: E402
import event_identity as ei  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

# Reused rather than re-derived, exactly as `test_v342...` reuses
# `test_v340...`'s own claim builder, vault writer and clock: a second
# spelling of "the shape a vault's receipts actually have" is how two tests
# come to disagree about what a vault is.
from test_v340_apply_keeps_placements import (  # noqa: E402
    NOW,
    claim,
    write_vault,
)
from test_v342_a_merged_node_keeps_its_date import (  # noqa: E402
    BIRTHDAY,
    BRITTNEY_NODE,
    brittney_claims,
    drawn,
    placed,
)

LATER = "2026-10-01T00:00:00Z"
EVEN_LATER = "2026-10-08T00:00:00Z"


# --------------------------------------------------------------------------
# A small audit, adapted from v342's own — what "nothing was lost" means
# --------------------------------------------------------------------------


def stale_aliases(projection: dict) -> list:
    """:data:`episode_fold.AN_ALIAS_NEVER_NAMES_A_NODE_THE_DRAWING_PUBLISHES`,
    over a projection: keys of ``node_aliases`` the drawing still publishes
    as a node."""
    published = drawn(projection)
    return sorted(key for key in (projection.get("node_aliases") or {}) if key in published)


def follow(node_id: str, aliases: dict) -> str:
    current, seen = node_id, {node_id}
    while current in aliases:
        nxt = aliases[current]
        if nxt in seen:
            return current
        seen.add(nxt)
        current = nxt
    return current


def lost_placements(before: dict, after: dict) -> list:
    """v340's guarantee, as an invariant: every node placed in ``before`` is,
    in ``after``, placed at the same date — or gone from the drawing and
    redirected (through ``node_aliases``, any chain) to a node placed at
    that same date. Anything else is a placement this pass cost."""
    aliases = dict(after.get("node_aliases") or {})
    after_placed = placed(after)
    after_drawn = drawn(after)
    lost = []
    for node_id, row in sorted(placed(before).items()):
        if node_id in after_placed:
            if after_placed[node_id].get("best") == row.get("best"):
                continue
            lost.append({"node_id": node_id, "why": "still drawn, date moved"})
            continue
        if node_id in after_drawn:
            lost.append({"node_id": node_id, "why": "drawn without a date"})
            continue
        target = follow(node_id, aliases)
        if target == node_id or target not in after_placed:
            lost.append({"node_id": node_id, "why": "gone, and no alias redirects it"})
            continue
        if after_placed[target].get("best") != row.get("best"):
            lost.append({"node_id": node_id, "why": "aliased at an incompatible date"})
    return lost


# --------------------------------------------------------------------------
# A vault built and bound through the real verbs only
# --------------------------------------------------------------------------


class VaultCase(unittest.TestCase):
    claims: tuple = ()
    prefix = "v348-"

    def setUp(self):
        self.root = root_parent_tmp(self, ROOT, prefix=self.prefix)
        write_vault(self.root, self.claims)
        ei.rebuild_telling_manifest(self.root)

    def publish(self, *, now: str = NOW) -> dict:
        pub.publish(self.root, roster_snapshot=(), now=now, full=True)
        return pub.read_projection(self.root) or {}

    def bind(self, *, now: str = NOW, apply: bool = True) -> dict:
        return eb.bind_episodes(self.root, apply=apply, now=now)

    def add_telling(self, new_claims: list, *, now: str = LATER) -> None:
        """The classify-story half of a real pass: a new receipt, the active
        index and the telling manifest rebuilt — never `--apply` itself."""
        by_source: dict[str, list] = {}
        for row in new_claims:
            by_source.setdefault(row["source_ref"]["source_id"], []).append(row)
        for source_id in sorted(by_source):
            batch = by_source[source_id]
            ts.write_receipt(self.root, {
                "source_ref": batch[0]["source_ref"],
                "extractor_version": batch[0]["extractor_version"],
                "created_at": batch[0]["created_at"],
                "claims": batch,
            }, now=now)
        ts.rebuild_active_index(self.root)
        ei.rebuild_telling_manifest(self.root)


class TheFastPathOverARealBindTests(VaultCase):
    """The incident's own shape, reused: two tellings of Brittney's birth
    that `plan()`'s milestone rung (`RULE_ID_MILESTONE`) really binds — the
    fixture `test_v342...` proves produces a real envelope through
    `eb.bind_episodes(apply=True)`, not a hand-built one."""

    prefix = "v348-fresh-"
    claims = brittney_claims()

    def setUp(self):
        super().setUp()
        self.outcome1 = self.bind(now=NOW)
        self.projection1 = self.publish(now=NOW)

    # -- (a) the fresh pass: full, and it actually binds something --------

    def test_the_fresh_pass_derives_and_files(self):
        self.assertFalse(self.outcome1.get("fast_path"))
        self.assertIsNone(self.outcome1.get("reason"))
        self.assertTrue(self.outcome1["applied"])
        self.assertIsNotNone(self.outcome1["plan"])
        self.assertEqual(len(self.outcome1["plan"].exact_groups), 1)
        self.assertNotIn(BRITTNEY_NODE, placed(self.projection1))
        # The merged node carries the date; the old id is redirected, not drawn.
        merged = [node_id for node_id in placed(self.projection1)
                 if placed(self.projection1)[node_id]["best"] == BIRTHDAY]
        self.assertEqual(len(merged), 1)
        self.assertNotIn(BRITTNEY_NODE, drawn(self.projection1))

    def test_the_fresh_pass_writes_a_receipt_that_matches_the_vault_now(self):
        receipt = eb.read_binder_receipt(self.root)
        self.assertIsNotNone(receipt)
        self.assertEqual(receipt["schema_version"], eb.BINDER_RECEIPT_SCHEMA_VERSION)
        self.assertEqual(receipt["rule"], "episode_binder.NOTHING_TO_BIND_COSTS_NOTHING")
        self.assertEqual(receipt["rule_version"], eb.RULE_VERSION)
        self.assertEqual(receipt["calculation_rule_version"], tt.CALCULATION_RULE_VERSION)
        self.assertTrue(eb._signature_matches(receipt, eb._cheap_pass_signature(self.root)))

    def test_the_receipts_report_is_the_summary_tail_not_the_full_narrative(self):
        """A RECEIPT stays small (rule 1: "a small binder receipt") even on a
        vault whose full `describe()` report is thousands of lines — one per
        candidate pair judged. `_compact_report_summary` is what keeps the
        two from being the same size."""
        full_report = self.outcome1["report"]
        receipt = eb.read_binder_receipt(self.root)
        compact = receipt["summary"]["report"]
        self.assertLessEqual(len(compact), len(full_report))
        self.assertIn("Summary", compact)
        self.assertEqual(eb._compact_report_summary(full_report), compact)

    # -- (b) the no-op pass: fast, and derives NOTHING ---------------------

    def test_the_second_apply_takes_the_fast_path_and_derives_nothing(self):
        # Proof, not inference: `plan()` and `read_vault_inputs` raise if the
        # fast path calls either of them.
        original_plan, original_inputs = eb.plan, eb.read_vault_inputs

        def _boom(*_a, **_k):
            raise AssertionError("the fast path derived something")

        eb.plan = _boom
        eb.read_vault_inputs = _boom
        try:
            outcome2 = self.bind(now=LATER)
        finally:
            eb.plan, eb.read_vault_inputs = original_plan, original_inputs

        self.assertTrue(outcome2.get("fast_path"))
        self.assertEqual(outcome2.get("reason"), "nothing_new")
        self.assertFalse(outcome2["applied"])
        self.assertIsNone(outcome2["plan"])
        self.assertIsNone(outcome2["filed"])
        self.assertIn("nothing to bind", "\n".join(outcome2["report"]))

    def test_the_no_op_pass_publishes_byte_identical_placements(self):
        self.bind(now=LATER)
        projection2 = self.publish(now=LATER)
        self.assertEqual(placed(projection2), placed(self.projection1))
        self.assertEqual(drawn(projection2), drawn(self.projection1))
        self.assertEqual(projection2.get("node_aliases"), self.projection1.get("node_aliases"))
        self.assertEqual(lost_placements(self.projection1, projection2), [])
        self.assertEqual(stale_aliases(projection2), [])

    def test_a_dry_run_also_takes_the_fast_path(self):
        """Rule 2 is about a PASS, not only `--apply`: a dry run after a
        matching receipt costs nothing either."""
        outcome = self.bind(now=LATER, apply=False)
        self.assertTrue(outcome.get("fast_path"))
        self.assertEqual(outcome.get("reason"), "nothing_new")
        self.assertFalse(outcome["applied"])

    def test_binder_step_survives_the_fast_path(self):
        step = eb.binder_step(self.root, now=LATER)
        self.assertFalse(step["wrote"])
        self.assertEqual(step.get("reason"), "nothing_new")
        self.assertEqual(step["questions"], [])
        self.assertIsInstance(step["counts"], dict)

    def test_deleting_the_receipt_forces_a_full_pass_again(self):
        """The receipt is a projection, never evidence — deleting it costs
        the full pass once and changes nothing else."""
        path = ts.store_path(self.root, eb.BINDER_RECEIPT_FILE)
        path.unlink()
        outcome = self.bind(now=LATER)
        self.assertFalse(outcome.get("fast_path"))
        self.assertTrue(outcome["applied"])
        # …and republishing lands on the SAME bytes: the fast path was never
        # deciding anything, only skipping the derivation of a decision
        # already on disk. `CALCULATION_RULE_VERSION` does not have to move
        # for this release, because there is nothing here for it to say.
        projection = self.publish(now=LATER)
        self.assertEqual(placed(projection), placed(self.projection1))
        self.assertEqual(projection.get("node_aliases"), self.projection1.get("node_aliases"))

    # -- (c) a pass after one new, unrelated telling: full again ----------

    def test_a_new_telling_forces_the_full_pass_and_loses_nothing(self):
        self.bind(now=LATER)  # the no-op pass, establishing that it fast-paths
        new_source = "classification:answers-b7#eeeeeeeeeeee"
        self.add_telling([
            claim(claim_type="occurrence", subject_mention="self", event_kind="moment",
                  source=new_source, event_mention="Started a new job",
                  quote="I started a new job."),
        ], now=EVEN_LATER)

        outcome3 = self.bind(now=EVEN_LATER)
        self.assertFalse(outcome3.get("fast_path"))
        self.assertIsNone(outcome3.get("reason"))
        self.assertTrue(outcome3["applied"])

        projection3 = self.publish(now=EVEN_LATER)
        self.assertEqual(lost_placements(self.projection1, projection3), [])
        self.assertEqual(stale_aliases(projection3), [])
        # The new telling's own node is drawn — the pass did real work, not
        # merely a re-confirmation of the old one.
        labels = {node.get("label") for node in projection3.get("nodes") or ()}
        self.assertIn("Started a new job", labels)

        # And a FOURTH pass, immediately after, is fast again — the new
        # telling only cost one full pass, not every pass from here on.
        original_plan = eb.plan
        eb.plan = lambda *a, **k: (_ for _ in ()).throw(AssertionError("derived again"))
        try:
            outcome4 = self.bind(now=EVEN_LATER)
        finally:
            eb.plan = original_plan
        self.assertTrue(outcome4.get("fast_path"))


# --------------------------------------------------------------------------
# A vault with nothing to bind at all — the incident's own report
# --------------------------------------------------------------------------


class NothingEverToBindTests(VaultCase):
    """The incident measured 187s on a run that filed ONE envelope over a
    vault that had already applied everything; this is the limit case where
    a run files nothing on the FIRST apply too, and the second is still
    fast."""

    prefix = "v348-empty-"
    claims = (
        claim(claim_type="occurrence", subject_mention="self", event_kind="moment",
              source="classification:answers-a1#111111111111",
              event_mention="A moment nothing else retells",
              quote="Something happened once."),
    )

    def test_first_apply_files_nothing_and_writes_a_receipt_anyway(self):
        outcome1 = self.bind(now=NOW)
        self.assertFalse(outcome1.get("fast_path"))
        filed = outcome1["filed"] or {}
        self.assertEqual(filed.get("envelopes"), [])
        self.assertEqual(filed.get("proposals"), [])
        self.assertIsNotNone(eb.read_binder_receipt(self.root))

        outcome2 = self.bind(now=LATER)
        self.assertTrue(outcome2.get("fast_path"))
        self.assertEqual(outcome2.get("reason"), "nothing_new")


# --------------------------------------------------------------------------
# The digest and receipt machinery, as units — no vault required
# --------------------------------------------------------------------------


class TellingDigestTests(unittest.TestCase):
    def test_row_and_claim_order_do_not_move_the_digest(self):
        a = {"tellings": [
            {"telling_ref": "t2", "status": "active", "claim_ids": ["c2", "c1"]},
            {"telling_ref": "t1", "status": "active", "claim_ids": []},
        ]}
        b = {"tellings": [
            {"claim_ids": ["c1", "c2"], "telling_ref": "t2", "status": "active"},
            {"telling_ref": "t1", "status": "active", "claim_ids": []},
        ]}
        self.assertEqual(eb._telling_digest(a), eb._telling_digest(b))

    def test_a_status_change_moves_the_digest(self):
        a = {"tellings": [{"telling_ref": "t1", "status": "active", "claim_ids": ["c1"]}]}
        b = {"tellings": [{"telling_ref": "t1", "status": "retired", "claim_ids": ["c1"]}]}
        self.assertNotEqual(eb._telling_digest(a), eb._telling_digest(b))

    def test_a_new_telling_moves_the_digest(self):
        a = {"tellings": [{"telling_ref": "t1", "status": "active", "claim_ids": ["c1"]}]}
        b = {"tellings": [
            {"telling_ref": "t1", "status": "active", "claim_ids": ["c1"]},
            {"telling_ref": "t2", "status": "active", "claim_ids": ["c2"]},
        ]}
        self.assertNotEqual(eb._telling_digest(a), eb._telling_digest(b))


class BindingsStoreDigestTests(unittest.TestCase):
    def setUp(self):
        self.root = root_parent_tmp(self, ROOT, prefix="v348-digest-")
        (self.root / "state" / "temporal_claims").mkdir(parents=True, exist_ok=True)

    def test_a_new_binding_file_moves_the_digest(self):
        before = eb._bindings_store_digest(self.root)
        base = ts.store_path(self.root, ei.STATE_BINDINGS_DIR)
        base.mkdir(parents=True, exist_ok=True)
        (base / "eid-test.json").write_text('{"a": 1}\n', encoding="utf-8")
        after = eb._bindings_store_digest(self.root)
        self.assertNotEqual(before, after)

    def test_a_file_outside_the_binding_directories_is_ignored(self):
        before = eb._bindings_store_digest(self.root)
        (self.root / "state" / "temporal_claims" / "unrelated.json").write_text(
            "{}", encoding="utf-8")
        after = eb._bindings_store_digest(self.root)
        self.assertEqual(before, after)


class LandmarkSourcesDigestTests(unittest.TestCase):
    """`go-dig-import --apply`, measured on the rig against the owner's own
    vault (2026-09-24), files `sources/landmarks/entry-*.md` and
    `state/landmarks.json` WITHOUT touching a claim, a binding, the active
    index or the telling manifest — so a signature without this digest would
    have fast-pathed straight past it."""

    def setUp(self):
        self.root = root_parent_tmp(self, ROOT, prefix="v348-landmark-")
        (self.root / "sources" / "landmarks").mkdir(parents=True, exist_ok=True)

    def test_a_new_landmark_entry_moves_the_digest(self):
        before = eb._landmark_sources_digest(self.root)
        (self.root / "sources" / "landmarks" / "entry-aaaaaaaaaaaaaaaa.md").write_text(
            "---\ntype: landmark_source\n---\n{}\n", encoding="utf-8")
        after = eb._landmark_sources_digest(self.root)
        self.assertNotEqual(before, after)

    def test_an_edited_landmark_entry_moves_the_digest(self):
        path = self.root / "sources" / "landmarks" / "entry-aaaaaaaaaaaaaaaa.md"
        path.write_text("---\ntype: landmark_source\n---\n{\"dates\": \"2020\"}\n",
                        encoding="utf-8")
        before = eb._landmark_sources_digest(self.root)
        path.write_text("---\ntype: landmark_source\n---\n{\"dates\": \"2021\"}\n",
                        encoding="utf-8")
        after = eb._landmark_sources_digest(self.root)
        self.assertNotEqual(before, after)

    def test_no_landmarks_directory_is_a_stable_empty_digest(self):
        empty_root = root_parent_tmp(self, ROOT, prefix="v348-nolandmark-")
        self.assertEqual(eb._landmark_sources_digest(empty_root),
                         eb._landmark_sources_digest(empty_root))


class ARealLandmarkImportForcesAFullPassTests(VaultCase):
    """The bug this suite exists to have caught: a landmark import that adds
    no claim and no binding must still force the next pass to be full, or
    the fast path silently drops v345's own promise
    (`A_TELLING_OF_A_LANDMARK_FOLDS_ONTO_IT`)."""

    prefix = "v348-landmark-vault-"
    claims = brittney_claims()

    def test_a_landmark_file_alone_breaks_the_fast_path(self):
        self.bind(now=NOW)
        signature_before = eb._cheap_pass_signature(self.root)
        self.assertTrue(eb._signature_matches(
            eb.read_binder_receipt(self.root), signature_before))

        landmarks_dir = self.root / "sources" / "landmarks"
        landmarks_dir.mkdir(parents=True, exist_ok=True)
        (landmarks_dir / "entry-bbbbbbbbbbbbbbbb.md").write_text(
            "---\ntype: landmark_source\n---\n{\"new\": true}\n", encoding="utf-8")

        signature_after = eb._cheap_pass_signature(self.root)
        self.assertNotEqual(signature_before["landmark_digest"],
                            signature_after["landmark_digest"])
        self.assertFalse(eb._signature_matches(
            eb.read_binder_receipt(self.root), signature_after))

        outcome = self.bind(now=LATER)
        self.assertFalse(outcome.get("fast_path"))


class SignatureMatchTests(unittest.TestCase):
    def base(self) -> dict:
        return {"telling_digest": "a", "bindings_digest": "b", "rule_version": "v1",
               "calculation_rule_version": "c1", "framework_version": 1}

    def test_a_missing_receipt_or_signature_never_matches(self):
        sig = self.base()
        self.assertFalse(eb._signature_matches(None, sig))
        self.assertFalse(eb._signature_matches(dict(sig, schema_version=1), None))
        self.assertFalse(eb._signature_matches(None, None))

    def test_an_identical_signature_matches(self):
        sig = self.base()
        receipt = dict(sig, schema_version=eb.BINDER_RECEIPT_SCHEMA_VERSION)
        self.assertTrue(eb._signature_matches(receipt, sig))

    def test_any_signature_field_moving_breaks_the_match(self):
        sig = self.base()
        for key in eb.BINDER_RECEIPT_SIGNATURE_FIELDS:
            receipt = dict(sig, schema_version=eb.BINDER_RECEIPT_SCHEMA_VERSION)
            receipt[key] = "something-else"
            self.assertFalse(eb._signature_matches(receipt, sig), key)

    def test_a_receipt_schema_version_mismatch_breaks_the_match(self):
        sig = self.base()
        receipt = dict(sig, schema_version=eb.BINDER_RECEIPT_SCHEMA_VERSION + 1)
        self.assertFalse(eb._signature_matches(receipt, sig))


class ReceiptRoundTripTests(unittest.TestCase):
    def test_write_then_read_back(self):
        root = root_parent_tmp(self, ROOT, prefix="v348-round-")
        (root / "state" / "temporal_claims").mkdir(parents=True, exist_ok=True)
        receipt = {"schema_version": eb.BINDER_RECEIPT_SCHEMA_VERSION,
                  "rule": "episode_binder.NOTHING_TO_BIND_COSTS_NOTHING",
                  "telling_digest": "x", "bindings_digest": "y",
                  "rule_version": eb.RULE_VERSION,
                  "calculation_rule_version": tt.CALCULATION_RULE_VERSION,
                  "framework_version": 999, "vault_head": None,
                  "summary": {"report": ["a"], "counts": {}, "filed": {}, "frames": 0,
                             "entities": 0, "question_contexts": 0}}
        eb.write_binder_receipt(root, receipt)
        self.assertEqual(eb.read_binder_receipt(root), receipt)

    def test_a_vault_that_never_applied_reads_no_receipt(self):
        root = root_parent_tmp(self, ROOT, prefix="v348-none-")
        (root / "state" / "temporal_claims").mkdir(parents=True, exist_ok=True)
        self.assertIsNone(eb.read_binder_receipt(root))

    def test_a_vault_with_no_telling_manifest_has_no_cheap_signature(self):
        root = root_parent_tmp(self, ROOT, prefix="v348-nomanifest-")
        (root / "state" / "temporal_claims").mkdir(parents=True, exist_ok=True)
        self.assertIsNone(eb._cheap_pass_signature(root))


# --------------------------------------------------------------------------
# The CLI wiring (`lifehug.py`), with the binder itself mocked at the seam
# --------------------------------------------------------------------------


class CmdBindEpisodesNothingNewTests(unittest.TestCase):
    """`lifehug.cmd_bind_episodes` never touches `REPO_DIR` once
    `episode_binder.bind_episodes` is mocked at the module boundary — the
    CLI wiring is what is under test, not the binder itself."""

    def setUp(self):
        import lifehug  # noqa: PLC0415

        self.lifehug = lifehug
        self.original = eb.bind_episodes

    def tearDown(self):
        eb.bind_episodes = self.original

    def fast_outcome(self) -> dict:
        return {
            "plan": None,
            "report": [
                "Event identity — the binder (rv, rung R1)",
                ("nothing to bind: no new telling or binding since the last apply "
                 "(episode_binder.NOTHING_TO_BIND_COSTS_NOTHING)"),
            ],
            "applied": False, "reason": "nothing_new", "filed": None,
            "frames": 3, "entities": 2, "question_contexts": 1,
            "last_summary": {"counts": {"tellings": 5},
                             "filed": {"envelopes": ["eop:1"], "created": 1}},
            "fast_path": True,
        }

    def args(self, *, as_json: bool) -> argparse.Namespace:
        return argparse.Namespace(apply=True, dry_run=False, json=as_json,
                                  question_cap=None, containment_authority=None)

    def test_human_output_reports_nothing_new_and_skips_the_filed_block(self):
        eb.bind_episodes = lambda *a, **k: self.fast_outcome()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.lifehug.cmd_bind_episodes(self.args(as_json=False))
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("nothing to bind", out)
        self.assertNotIn("✓ filed", out)

    def test_json_output_reports_applied_false_reason_nothing_new(self):
        eb.bind_episodes = lambda *a, **k: self.fast_outcome()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.lifehug.cmd_bind_episodes(self.args(as_json=True))
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["applied"])
        self.assertEqual(payload["reason"], "nothing_new")
        self.assertIsNone(payload["filed"])
        self.assertEqual(payload["last_filed"], {"envelopes": ["eop:1"], "created": 1})

    def test_a_real_full_outcome_is_unaffected_by_the_new_branch(self):
        """The ordinary path (a real bind) still prints exactly as before —
        the new branch is additive, never a rewrite of what worked."""
        import episode_binder as real_eb  # noqa: PLC0415

        plan = real_eb.plan([], question_cap=real_eb.GLOBAL_QUESTION_CAP)
        eb.bind_episodes = lambda *a, **k: {
            "plan": plan, "report": real_eb.describe(plan, applied=True),
            "applied": True, "reason": None,
            "filed": {"envelopes": [], "proposals": [], "created": 0,
                     "upgraded": [], "kept_stronger": [], "not_upgraded": []},
            "frames": 0, "entities": 0, "question_contexts": 0, "fast_path": False,
        }
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.lifehug.cmd_bind_episodes(self.args(as_json=False))
        self.assertEqual(rc, 0)
        self.assertIn("✓ filed 0 envelope(s), 0 proposal(s); 0 new record group(s)", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
