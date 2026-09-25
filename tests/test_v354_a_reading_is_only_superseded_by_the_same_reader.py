"""v354 — an answer never retires the listener's reading of the same message.

THE INCIDENT (lifehug#409, found while verifying v353 on a fresh scratch clone
of the owner's vault, and filed rather than swallowed; the platform pin is going
to v353 and staging's daily maintenance scheduler stays PAUSED until the
placement path is trustworthy end to end).

`temporal_store._fold` step 1 grouped receipts by ``(source_id, revision)``,
elected the latest by `temporal_store.receipt_sort_key` as the group's winner,
and marked every other receipt's claims ``superseded / reextracted`` — *"a
previous interpretation of the same words"*. That rule was written for one
extractor re-running over one document and it is right for that.

v352's `answer_placement.file_answer` writes its receipt on the promoted reply
ITSELF, at that reply's own revision, which puts it in the same group as the
`general_listener` receipt already filed for that message. The answer's receipt
is newer, so it won the group and the listener's whole reading of the same words
was retired. Measured on the clone, ``place-answers`` filed 8 receipts and two
of those messages already carried a listener receipt::

    conversation:msg-99efe6688bbd9e4f752438e0  "She graduated in 2006"
      receipt:537be58a3848123630f24b32  (general_listener)  RETIRED by
      receipt:d9a21bab13bbd169561adc7e  (answer-placement)
      -> claim:36bae1eb0bbfd2120274471d, a `graduation` dated 2006 for
         "Katie Ann Merrill", which was DRAWING node:091ec8a898daa8548afaf104
         placed at 2006

    conversation:msg-c9d84f13e02d1c9547bafaa6
      -> claim:257f9e5681424bdd8539c76a, a `relative_order` after "left
         Kristen", node:3d1065f366b17440103c9a25

and the v340/v342 placement audit over the whole act was not empty:
``{"lost": ["node:091ec8a898daa8548afaf104"], "moved": [],
"drawn_at_an_alias": []}``. The owner's own timeline lost a dated moment to it.

THE RULE, `temporal_store.A_READING_IS_ONLY_SUPERSEDED_BY_THE_SAME_READER`. The
election unit is ``(source_id, revision, extractor identity)``: a receipt
supersedes another only when the SAME READER re-read the same revision of the
same document. Two extractors reading one message are two readings of it, both
legitimate, and neither retires the other — which is what
`answer_placement.EXTRACTOR_VERSION` has said in prose since v352 (*"two
readings of one message are two interpretations … a shared version would make
them one claim that overwrote itself"*) and what
`temporal_claims.CLAIM_IDENTITY_KEYS` already made true of their CLAIMS. Only
the group key was missing it.

WHO a reader is, is the NAME at the head of its extractor version
(`temporal_claims.extractor_identity` /
`temporal_claims.AN_EXTRACTORS_NAME_IS_WHO_READ_IT`); everything after the name
says WHICH VERSION of that reader did the reading. That is the honest seam, and
it is not the issue's own first suggestion: keying on the whole
``extractor_version`` would make every group a singleton, because
`temporal_claims.receipt_relative_path` already writes one receipt file per
``(source, revision, extractor_version)`` — a prompt edit, a new model or a
bumped rule version IS a new extractor version, and it is exactly the case
supersession exists for (`general_listener.PROMPT_VERSION_LENGTH`,
`timeline_evidence.CLASSIFIER_CLAIMS_RULE_VERSION`'s own ``"4" -> "5"`` note).
So the version stays out of the key and the name goes in.

The ids in part 1 are the owner's own, minted rather than copied: his reply's
bytes promote to ``sources/conversations/msg-99efe6688bbd9e4f752438e0.md`` with
the same ``content_sha256``, so the same listener claim, the same two receipt
ids and the same 2006 node fall out of content addressing. Nothing here reads
his vault. The whole file was run against v353's bytes first and fails there —
the listener's claim comes back ``superseded / reextracted`` and the audit comes
back with his node in ``lost``.
"""

from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import answer_placement as ap  # noqa: E402
import classifier_context as cc  # noqa: E402
import era_identity as eri  # noqa: E402
import era_record as err  # noqa: E402
import general_listener as gl  # noqa: E402
import landmark_projection as lp  # noqa: E402
import landmark_reading as lr  # noqa: E402
import landmark_recorder as lrec  # noqa: E402
import resolver as rsv  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import timeline_evidence as te  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402
from test_v345_a_telling_of_a_landmark_folds_onto_it import (  # noqa: E402
    placement_audit,
)

NOW = "2026-09-25T12:00:00Z"

# --------------------------------------------------------------------------
# The owner's own message, rebuilt from what made it rather than copied
# --------------------------------------------------------------------------

#: His reply, verbatim, and the card its session named.
REPLY = "She graduated in 2006"
CAPTURED = "2026-09-22T00:45:31Z"
CARD = "work:ddbe55d2f8fabd24f2fe5880"
#: What content addressing then mints, on his vault and on this fixture alike.
SOURCE_ID = "conversation:msg-99efe6688bbd9e4f752438e0"
REVISION = "sha256:3fc09a0e90916ded2adc0aa249d7502b8d01078bfea063a13a06025f36158fa1"
SOURCE_PATH = "sources/conversations/msg-99efe6688bbd9e4f752438e0.md"

#: The listener's reading of that reply: the receipt, its one claim, and the node
#: the claim was drawing. `confidence: 0.0` and the full name are his vault's.
LISTENER_VERSION = "general_listener/schema:1/prompt:bc715c9abe4c/model:haiku-class"
LISTENER_RECEIPT = "receipt:537be58a3848123630f24b32"
LISTENER_CLAIM = "claim:36bae1eb0bbfd2120274471d"
LISTENER_HEARD = "2026-09-23T19:33:02Z"
GRADUATE = "Katie Ann Merrill"
GRADUATION_NODE = "node:091ec8a898daa8548afaf104"

#: The answer's reading of the same reply, filed against the card's own node.
ANSWER_RECEIPT = "receipt:d9a21bab13bbd169561adc7e"
ANSWER_CLAIM = "claim:39ae7f4216e1708b05250550"
CARD_NODE = "node:9b9e8612d7a9530ae7dc4b60"
CARD_LABEL = "Katie graduates esthetician school"
CARD_SUBJECT = "Katie"


def source_ref() -> dict:
    return {"source_id": SOURCE_ID, "revision": REVISION, "source_path": SOURCE_PATH}


def listener_claim() -> dict:
    """His listener's one claim about that reply — a `date`, 2006, on a name."""
    return tc.validate_temporal_claim({
        "source_kind": "conversation",
        "source_ref": source_ref(),
        "claim_type": "date",
        "subject_mention": GRADUATE,
        "event_kind": "graduation",
        "temporal_value": {
            "best": "2006", "earliest": "2006", "latest": "2006",
            "granularity": "year", "confidence": "certain", "basis": "stated",
        },
        "evidence": [{"quote": REPLY}],
        "basis": "explicit",
        "confidence": 0.0,
        "extractor_version": LISTENER_VERSION,
        "created_at": LISTENER_HEARD,
    })


def owners_card() -> dict:
    """The published work-item row his reply was an answer to, in the shape
    `answer_placement.card_for_answer` hands `file_answer`."""
    return {"work_item_id": CARD, "node_ref": CARD_NODE, "subject_ref": CARD_SUBJECT,
            "event_kind": "moment", "label": CARD_LABEL, "state": "open",
            "question": f"When did {CARD_LABEL} happen?"}


class OwnersMessage:
    """A synthetic vault holding ONE promoted reply read by TWO readers."""

    def __init__(self, test: unittest.TestCase):
        self.root = root_parent_tmp(test, ROOT, prefix="lifehug-v354-")
        for folder in ("state/temporal_claims", "sources/conversations"):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        self.ref = ts.promote_conversational_source(self.root, REPLY, {
            "session_ref": f"conversation:cand:work_item:{CARD}",
            "turn_ref": "0", "speaker": "person", "channel": "web",
            "occurred_at": CAPTURED})
        self.listener_path = ts.write_receipt(self.root, {
            "source_ref": source_ref(),
            "extractor_version": LISTENER_VERSION,
            "recorder": gl.LISTENER_EXTRACTOR,
            "created_at": LISTENER_HEARD,
            "claims": [listener_claim()],
        }, now=LISTENER_HEARD)

    def file_the_answer(self) -> dict:
        """Through the real seat, with the real reading the sweep computes."""
        reading = ap.answer_reading(REPLY, captured=CAPTURED,
                                   question=owners_card()["question"])
        return ap.file_answer(self.root, source_path=SOURCE_PATH,
                              card=owners_card(), reading=reading or ap.telling_reading(),
                              text=REPLY, now=NOW)

    def index(self) -> dict:
        return ts.fold_active_index(self.root)

    def claim(self, claim_id: str) -> dict:
        rows = [row for row in self.index()["claims"] if row["claim_id"] == claim_id]
        assert len(rows) == 1, f"{claim_id} appears {len(rows)} times"
        return rows[0]

    def drawing(self) -> object:
        return tt.derive_calculated_timeline(self.index(), now=NOW)

    def nodes(self) -> dict[str, dict]:
        return {row["node_id"]: row for row in self.drawing().nodes}


# --------------------------------------------------------------------------
# 1. The fixture is the owner's own message and his own two readings
# --------------------------------------------------------------------------

class TheFixtureIsTheOwnersOwnMessageTests(unittest.TestCase):
    """Content addressing used as the evidence it is: his reply's bytes promote
    to his source, and his two receipts and their claims fall out of it."""

    def setUp(self):
        self.vault = OwnersMessage(self)
        self.filed = self.vault.file_the_answer()

    def test_the_promoted_reply_is_his_source_at_his_revision(self):
        self.assertEqual(self.vault.ref.source_id, SOURCE_ID)
        self.assertEqual(self.vault.ref.revision, REVISION)
        self.assertEqual(self.vault.ref.source_path, SOURCE_PATH)

    def test_both_receipts_and_both_claims_are_his(self):
        receipts = {row["receipt_id"]: row for row in self.vault.index()["receipts"]}
        self.assertEqual(sorted(receipts), sorted([ANSWER_RECEIPT, LISTENER_RECEIPT]))
        self.assertEqual(listener_claim()["claim_id"], LISTENER_CLAIM)
        self.assertEqual(self.filed["claim_id"], ANSWER_CLAIM)
        self.assertEqual(self.filed["work_item_id"], CARD)
        self.assertEqual(self.filed["node_ref"], CARD_NODE)

    def test_the_answer_is_the_telling_his_vault_filed(self):
        """It carried no time his rungs could read, so it filed as a telling —
        which is what made the loss silent: one occurrence replaced a dated
        reading of the same sentence."""
        self.assertEqual(self.filed["reading"], ap.READING_TELLING)
        self.assertIsNone(ap.answer_reading(
            REPLY, captured=CAPTURED, question=owners_card()["question"]))

    def test_the_two_receipts_share_one_source_revision(self):
        """The defect's precondition, ASSERTED rather than assumed: the answer's
        receipt cites the reply itself, so it lands in the listener's group."""
        rows = {row["receipt_id"]: row for row in self.vault.index()["receipts"]}
        self.assertEqual(
            {row["source_ref"]["source_id"] for row in rows.values()}, {SOURCE_ID})
        self.assertEqual(
            {row["source_ref"]["revision"] for row in rows.values()}, {REVISION})

    def test_the_answers_receipt_is_the_newer_one(self):
        """And the other precondition: under a key without the extractor the
        answer WINS, which is why it was the listener's reading that went."""
        rows = {row["receipt_id"]: row for row in self.vault.index()["receipts"]}
        answer, listener = rows[ANSWER_RECEIPT], rows[LISTENER_RECEIPT]
        key = ts.receipt_sort_key
        self.assertGreater(
            key(ts.read_receipt(self.vault.root, answer["relative_path"])),
            key(ts.read_receipt(self.vault.root, listener["relative_path"])),
        )


# --------------------------------------------------------------------------
# 2. The reproduction, and the fix
# --------------------------------------------------------------------------

class TheListenersReadingSurvivesTheAnswerTests(unittest.TestCase):
    """What v353 measured, as an assertion: the claim, its node and its date."""

    def setUp(self):
        self.vault = OwnersMessage(self)
        self.before = self.vault.drawing()
        self.filed = self.vault.file_the_answer()
        self.after = self.vault.drawing()

    def test_the_listeners_claim_is_still_active_and_unmarked(self):
        row = self.vault.claim(LISTENER_CLAIM)
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["status_marks"], [])
        self.assertIn(LISTENER_CLAIM, self.vault.index()["active_claim_ids"])

    def test_no_claim_in_the_vault_is_retired_as_reextracted(self):
        counts = self.vault.index()["counts"]
        self.assertEqual(counts["superseded"], 0)
        self.assertEqual(counts["active"], 2)
        self.assertEqual(
            [mark for row in self.vault.index()["claims"]
             for mark in row["status_marks"]], [])

    def test_both_readings_are_elected(self):
        index = self.vault.index()
        self.assertEqual(index["counts"]["receipts"], 2)
        self.assertEqual(index["counts"]["selected_receipts"], 2)
        self.assertTrue(all(row["selected"] for row in index["receipts"]))

    def test_one_source_revision_read_twice_is_two_readings_and_one_source(self):
        index = self.vault.index()
        self.assertEqual(index["counts"]["sources"], 1)
        self.assertEqual(index["counts"]["readings"], 2)
        self.assertEqual(
            [(row["source_id"], row["revision"], row["extractor_identity"])
             for row in index["sources"]],
            [(SOURCE_ID, REVISION, ap.EXTRACTOR_NAME),
             (SOURCE_ID, REVISION, gl.LISTENER_EXTRACTOR)],
        )

    def test_his_2006_graduation_keeps_its_node_and_its_placement(self):
        node = self.vault.nodes()[GRADUATION_NODE]
        self.assertEqual(node["label"], GRADUATE)
        self.assertEqual(node["event_kind"], "graduation")
        self.assertEqual(node["best_temporal_value"]["best"], "2006")
        self.assertEqual(node["input_claim_refs"], [LISTENER_CLAIM])

    def test_the_answer_draws_its_own_card_node_beside_it(self):
        """Neither reading is at the other's expense: the answer's telling lands
        on the card's node and the listener's date stays on its own."""
        nodes = self.vault.nodes()
        self.assertEqual(nodes[CARD_NODE]["input_claim_refs"], [ANSWER_CLAIM])
        self.assertIn(GRADUATION_NODE, nodes)

    def test_the_placement_audit_over_the_filing_is_empty(self):
        self.assertEqual(placement_audit(self.before, self.after),
                         {"lost": [], "moved": [], "drawn_at_an_alias": []})

    def test_the_old_election_key_would_have_retired_it(self):
        """The defect as arithmetic, so this file states what it is fixing: group
        the same two receipts by ``(source_id, revision)`` alone and there is ONE
        winner, and it is not the listener's."""
        index = self.vault.index()
        groups: dict[tuple[str, str], list[dict]] = {}
        for row in index["receipts"]:
            key = (row["source_ref"]["source_id"], row["source_ref"]["revision"])
            groups.setdefault(key, []).append(row)
        self.assertEqual(len(groups), 1)
        ordered = sorted(
            next(iter(groups.values())),
            key=lambda row: (row["created_at"], row["extractor_version"],
                             row["receipt_id"]))
        self.assertEqual(ordered[-1]["receipt_id"], ANSWER_RECEIPT)
        self.assertEqual(ordered[0]["receipt_id"], LISTENER_RECEIPT)
        # And with the extractor in the key, the same receipts are two groups of
        # one, each electing itself.
        self.assertEqual(len(index["sources"]), 2)
        self.assertEqual([row["receipt_ids"] for row in index["sources"]],
                         [[ANSWER_RECEIPT], [LISTENER_RECEIPT]])

    def test_filing_the_answer_again_writes_nothing_and_changes_nothing(self):
        before = ts.active_index_bytes(self.vault.index())
        again = self.vault.file_the_answer()
        self.assertEqual(again["claim_id"], self.filed["claim_id"])
        self.assertEqual(again["receipt_path"], self.filed["receipt_path"])
        ts.forget_fold_inputs(self.vault.root)
        self.assertEqual(ts.active_index_bytes(self.vault.index()), before)


# --------------------------------------------------------------------------
# 3. The general case: every reader pair, not `answer_placement`'s
# --------------------------------------------------------------------------

#: Every extractor identity that files receipts into this vault, in the spelling
#: its own module files it in. Read from the modules rather than typed out, so a
#: rename cannot leave this table quietly wrong.
READERS = {
    "general_listener": gl.claim_extractor_version(
        gl.claim_extractor(gl.LISTENER_EXTRACTOR, leaf="a listener leaf",
                           model="haiku-class")),
    "landmark_recorder": gl.claim_extractor_version(
        gl.claim_extractor(lrec.RECORDER_EXTRACTOR, leaf="a recorder leaf",
                           model="sonnet-class")),
    "landmark_reading": gl.claim_extractor_version(
        gl.claim_extractor(lr.READING_EXTRACTOR, leaf="a reading leaf",
                           model="sonnet-class")),
    "answer-placement": ap.EXTRACTOR_VERSION,
    "classifier-claims": te.CLASSIFIER_CLAIMS_EXTRACTOR,
    "story-classifier": cc.EXTRACTOR_VERSION,
    "resolver": rsv.EXTRACTOR_VERSION,
    "era_record": err.ERA_RECORD_EXTRACTOR,
    "era_identity": eri.IDENTITY_EXTRACTOR,
    "landmark-record": lp.LIVE_EXTRACTOR,
    "legacy-entry-import": lp.LEGACY_EXTRACTOR,
    "unbound": gl.UNBOUND_EXTRACTOR,
}


class WhoReadItTests(unittest.TestCase):
    """`temporal_claims.extractor_identity` over every spelling on disk."""

    def test_every_filer_in_the_vault_reads_back_as_itself(self):
        self.assertEqual(
            {name: tc.extractor_identity(version)
             for name, version in sorted(READERS.items())},
            {name: name for name in READERS},
        )

    def test_no_two_filers_share_an_identity(self):
        self.assertEqual(len(set(READERS.values())), len(READERS))
        self.assertEqual(
            len({tc.extractor_identity(v) for v in READERS.values()}), len(READERS))

    def test_a_version_bump_is_the_same_reader_in_both_spellings(self):
        """The two spellings a version takes in this vault: ``name/rule:N``
        (`timeline_evidence.CLASSIFIER_CLAIMS_RULE_VERSION`) and the older
        ``name:N`` (`classifier_context.EXTRACTOR_VERSION`)."""
        self.assertEqual(tc.extractor_identity("classifier-claims/rule:4"),
                         tc.extractor_identity("classifier-claims/rule:5"))
        self.assertEqual(tc.extractor_identity("story-classifier:2"),
                         tc.extractor_identity("story-classifier:3"))
        self.assertEqual(
            tc.extractor_identity(gl.claim_extractor_version(gl.claim_extractor(
                gl.LISTENER_EXTRACTOR, leaf="yesterday's leaf", model="haiku-class"))),
            tc.extractor_identity(gl.claim_extractor_version(gl.claim_extractor(
                gl.LISTENER_EXTRACTOR, leaf="today's leaf", model="opus-class"))),
        )

    def test_a_version_with_no_name_is_refused_by_name(self):
        with self.assertRaises(tc.ExtractionReceiptError) as caught:
            tc.extractor_identity("   ")
        self.assertEqual(caught.exception.code, "extractor_version_required")

    def test_the_law_is_written_down_where_the_fold_can_cite_it(self):
        self.assertIn("same reader",
                      ts.A_READING_IS_ONLY_SUPERSEDED_BY_THE_SAME_READER)
        self.assertIn("extractor version", tc.AN_EXTRACTORS_NAME_IS_WHO_READ_IT)


class ManyReadersOneDocumentTests(unittest.TestCase):
    """The law over a whole vault, for pairs that have nothing to do with
    `answer_placement` — the general case the fix is made of."""

    def setUp(self):
        self.root = root_parent_tmp(self, ROOT, prefix="lifehug-v354-readers-")
        for folder in ("state/temporal_claims", "sources/conversations"):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        self.ref = ts.promote_conversational_source(
            self.root, "Rosa and I married in 1978, the year I left Brindle.",
            {"session_ref": "s1", "turn_ref": "t1"})

    def file(self, version: str, *, event_kind: str, best: str,
             created_at: str) -> Path:
        row = tc.validate_temporal_claim({
            "source_kind": "conversation",
            "source_ref": self.ref.to_dict(),
            "claim_type": "date",
            "subject_mention": "Rosa",
            "event_kind": event_kind,
            "temporal_value": {
                "best": best, "earliest": best, "latest": best,
                "granularity": "year", "confidence": "certain", "basis": "stated",
            },
            "evidence": [{"quote": "we married in 1978"}],
            "basis": "explicit",
            "confidence": 0.9,
            "extractor_version": version,
            "created_at": created_at,
        })
        return ts.write_receipt(self.root, {
            "source_ref": self.ref.to_dict(), "extractor_version": version,
            "created_at": created_at, "claims": [row],
        }, now=created_at)

    def index(self) -> dict:
        return ts.fold_active_index(self.root)

    def test_three_readers_of_one_revision_all_keep_their_reading(self):
        self.file(READERS["general_listener"], event_kind="married",
                  best="1978", created_at="2026-08-20T10:00:00Z")
        self.file(READERS["landmark_recorder"], event_kind="moved",
                  best="1978", created_at="2026-08-21T10:00:00Z")
        self.file(READERS["classifier-claims"], event_kind="moment",
                  best="1978", created_at="2026-08-22T10:00:00Z")
        counts = self.index()["counts"]
        self.assertEqual(counts["receipts"], 3)
        self.assertEqual(counts["selected_receipts"], 3)
        self.assertEqual(counts["active"], 3)
        self.assertEqual(counts["superseded"], 0)
        self.assertEqual(counts["sources"], 1)
        self.assertEqual(counts["readings"], 3)

    def test_the_landmark_rule_and_the_legacy_import_are_two_readers(self):
        """`landmark_projection`'s own pair: the SAME deterministic rule under
        two names, so the fold can tell an imported record from one filed after
        the flip. Two names are two readers, and the flip is gated on
        `landmark_projection.already_substrate_backed` rather than on one of
        them retiring the other."""
        self.file(READERS["legacy-entry-import"], event_kind="married",
                  best="1978", created_at="2026-08-20T10:00:00Z")
        self.file(READERS["landmark-record"], event_kind="married",
                  best="1978", created_at="2026-08-21T10:00:00Z")
        counts = self.index()["counts"]
        self.assertEqual(counts["active"], 2)
        self.assertEqual(counts["superseded"], 0)

    def test_one_reader_at_two_versions_still_elects_a_winner(self):
        """The rule supersession exists for, unchanged: a prompt edit is a later
        interpretation of the same words by the same reader."""
        yesterday = gl.claim_extractor_version(gl.claim_extractor(
            gl.LISTENER_EXTRACTOR, leaf="yesterday's leaf", model="haiku-class"))
        today = gl.claim_extractor_version(gl.claim_extractor(
            gl.LISTENER_EXTRACTOR, leaf="today's leaf", model="haiku-class"))
        self.file(yesterday, event_kind="married", best="1977",
                  created_at="2026-08-20T10:00:00Z")
        self.file(today, event_kind="married", best="1978",
                  created_at="2026-08-26T10:00:00Z")
        index = self.index()
        self.assertEqual(index["counts"]["active"], 1)
        self.assertEqual(index["counts"]["superseded"], 1)
        self.assertEqual(index["counts"]["readings"], 1)
        stale = next(row for row in index["claims"]
                     if row["status"] == "superseded")
        self.assertEqual([mark["reason"] for mark in stale["status_marks"]],
                         ["reextracted"])
        self.assertEqual(stale["temporal_value"]["best"], "1977")
        active = ts.active_claims(index)[0]
        self.assertEqual(active["temporal_value"]["best"], "1978")

    def test_a_rule_version_bump_in_the_colon_spelling_still_elects(self):
        self.file("story-classifier:2", event_kind="married", best="1977",
                  created_at="2026-08-20T10:00:00Z")
        self.file("story-classifier:3", event_kind="married", best="1978",
                  created_at="2026-08-26T10:00:00Z")
        counts = self.index()["counts"]
        self.assertEqual((counts["active"], counts["superseded"]), (1, 1))

    def test_the_fold_stays_a_function_of_the_receipts_on_disk(self):
        """Wave B's exit gate, with two readers in the vault: delete the index,
        rebuild it, get the same bytes."""
        self.file(READERS["general_listener"], event_kind="married",
                  best="1978", created_at="2026-08-20T10:00:00Z")
        self.file(READERS["answer-placement"], event_kind="moment",
                  best="1978", created_at="2026-08-26T10:00:00Z")
        path = ts.write_active_index(self.root, self.index())
        original = path.read_bytes()
        path.unlink()
        ts.forget_fold_inputs(self.root)
        self.assertEqual(
            ts.active_index_bytes(ts.rebuild_active_index(self.root)),
            original.decode("utf-8"))


# --------------------------------------------------------------------------
# 4. The whole act, through the real verb and the real publish
# --------------------------------------------------------------------------

#: A classification of the same conversation, which is where the CARD comes
#: from on his vault. Its revision is a seed: a document this fixture does not
#: have.
TOLD = "classification:answers-c31#4f1a9c2d7b30"
TOLD_REVISION = "sha256:" + hashlib.sha256(
    b"the classification his vault holds for the esthetician school",
).hexdigest()
SCHOOL_NODE = tp.derive_node_id(
    node_kind="event", event_kind="moment", subject_refs=[CARD_SUBJECT])


def school_telling() -> dict:
    """The undated occurrence that mints the card — *something happened to
    Katie and nobody said when*."""
    return tc.validate_temporal_claim({
        "source_kind": "conversation",
        "source_ref": {"source_id": TOLD, "revision": TOLD_REVISION},
        "claim_type": tc.OCCURRENCE_CLAIM_TYPE,
        "subject_mention": CARD_SUBJECT,
        "event_kind": "moment",
        "event_mention": CARD_LABEL,
        "event_ref": SCHOOL_NODE,
        "evidence": [{"quote": "Katie went through esthetician school"}],
        "basis": "explicit",
        "confidence": 0.9,
        "extractor_version": te.CLASSIFIER_CLAIMS_EXTRACTOR,
        "created_at": "2026-09-01T00:00:00Z",
    })


class TheWholeActKeepsEveryPlacementTests(unittest.TestCase):
    """`place-answers` + `publish` over a vault where the answered message was
    already read by the listener — the act the audit was not empty for.

    Self-contained, so the card is minted by the REAL minter
    (`temporal_publication.publish`) and answered through the real sweep
    (`answer_placement.place_answers`). The reply's session names THIS vault's
    card, so the promoted bytes — and therefore the ids — are the fixture's own.
    """

    def setUp(self):
        self.root = root_parent_tmp(self, ROOT, prefix="lifehug-v354-act-")
        for folder in ("state/temporal_claims", "sources/conversations"):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        told = school_telling()
        ts.write_receipt(self.root, {
            "source_ref": told["source_ref"],
            "extractor_version": told["extractor_version"],
            "created_at": told["created_at"], "claims": [told],
        }, now=told["created_at"])
        self.publish()
        self.card = self.open_card()
        # His reply, promoted with the session that names THIS card, and read by
        # the listener exactly as his vault read it.
        self.ref = ts.promote_conversational_source(self.root, REPLY, {
            "session_ref": f"conversation:cand:work_item:{self.card['work_item_id']}",
            "turn_ref": "0", "speaker": "person", "channel": "web",
            "occurred_at": CAPTURED})
        heard = tc.validate_temporal_claim({
            **listener_claim(), "claim_id": None,
            "source_ref": self.ref.to_dict(),
        })
        ts.write_receipt(self.root, {
            "source_ref": self.ref.to_dict(),
            "extractor_version": LISTENER_VERSION,
            "recorder": gl.LISTENER_EXTRACTOR,
            "created_at": LISTENER_HEARD, "claims": [heard],
        }, now=LISTENER_HEARD)
        self.heard = heard["claim_id"]
        self.publish()
        self.before = pub.read_projection(self.root) or {}
        self.report = ap.place_answers(self.root, now=NOW)
        self.publish()
        self.after = pub.read_projection(self.root) or {}

    def publish(self) -> None:
        ts.rebuild_active_index(self.root)
        pub.publish(self.root, now=NOW)

    def open_card(self) -> dict:
        rows = [row for row in (pub.read_work_items(self.root) or {}).get(
            "work_items") or () if CARD_LABEL in (row.get("prompt_intent") or "")]
        assert len(rows) == 1, f"{CARD_LABEL!r} carries {len(rows)} cards"
        return rows[0]

    class Proj:
        """A published projection in the shape `placement_audit` reads."""

        def __init__(self, payload: dict):
            self.nodes = payload.get("nodes") or []
            self.node_aliases = payload.get("node_aliases") or {}

    def test_the_answer_filed_as_a_telling_of_the_cards_node(self):
        self.assertEqual(self.report["answers"], 1)
        self.assertEqual(self.report["tellings"], 1)
        self.assertEqual(self.report["errors"], [])
        self.assertEqual(sum(self.report["refused"].values()), 0)
        self.assertEqual([row["node_ref"] for row in self.report["filed"]],
                         [SCHOOL_NODE])

    def test_the_listeners_reading_of_that_reply_is_untouched(self):
        rows = {row["claim_id"]: row
                for row in ts.fold_active_index(self.root)["claims"]}
        self.assertEqual(rows[self.heard]["status"], "active")
        self.assertEqual(rows[self.heard]["status_marks"], [])
        self.assertEqual(
            ts.fold_active_index(self.root)["counts"]["superseded"], 0)

    def test_the_placement_audit_over_the_whole_act_is_empty(self):
        """v340/v342's invariant over two whole publications — the one thing
        v353 could not get to zero on the owner's vault."""
        self.assertEqual(
            placement_audit(self.Proj(self.before), self.Proj(self.after)),
            {"lost": [], "moved": [], "drawn_at_an_alias": []},
        )

    def test_the_graduation_node_is_still_drawn_and_still_at_2006(self):
        nodes = {row["node_id"]: row for row in self.after.get("nodes") or ()}
        self.assertIn(GRADUATION_NODE, nodes)
        self.assertEqual(nodes[GRADUATION_NODE]["best_temporal_value"]["best"],
                         "2006")
        self.assertEqual(nodes[GRADUATION_NODE]["input_claim_refs"], [self.heard])

    def test_no_node_that_was_drawn_before_the_answer_is_gone_after_it(self):
        was = {row["node_id"] for row in self.before.get("nodes") or ()}
        now = {row["node_id"] for row in self.after.get("nodes") or ()}
        self.assertEqual(sorted(was - now), [])

    def test_the_sweep_is_idempotent_over_the_same_vault(self):
        again = ap.place_answers(self.root, now=NOW)
        self.assertEqual(again["errors"], [])
        self.assertEqual([row["claim_id"] for row in again["filed"]],
                         [row["claim_id"] for row in self.report["filed"]])
        ts.forget_fold_inputs(self.root)
        self.assertEqual(
            ts.fold_active_index(self.root)["counts"]["superseded"], 0)


# --------------------------------------------------------------------------
# 5. What does NOT move
# --------------------------------------------------------------------------

class NothingDerivedMovesForThisTests(unittest.TestCase):
    """The election lives in the substrate's fold, not in the arithmetic that
    draws a timeline over it."""

    def test_the_calculation_rule_version_does_not_move(self):
        """`temporal_timeline.CALCULATION_RULE_VERSION` describes what the same
        claims CALCULATE to. v354 changes which claims are ACTIVE, and only on a
        source revision two readers have both read; the arithmetic over an
        active set is untouched, and the fold is re-run in full on every publish
        so no vault carries a stale index across this change. PROVED rather than
        argued: two fresh clones of the owner's vault at one head, one per
        framework, publish byte-identical `calculated-timeline.json` and
        `work-items.json` (generation 188, 1265 nodes, 69 work items)."""
        self.assertEqual(tt.CALCULATION_RULE_VERSION, "timeline-rules:18")

    def test_the_index_schema_is_additive(self):
        """``extractor_identity`` on a source row and ``readings`` in the counts
        are new FIELDS. Nothing an older reader looked at moved, which is the
        substrate's own compatibility rule (`temporal_claims` rule 3)."""
        self.assertEqual(ts.INDEX_VERSION, 1)
        self.assertEqual(tc.SCHEMA_VERSION, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
