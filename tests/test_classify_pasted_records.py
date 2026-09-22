"""A pasted vital record files, place unresolved and all (v326).

On 2026-09-22 the owner pasted two FamilySearch cards (Name / Birth / Death /
Burial lines about a named grandfather) into a Timeline conversation, and a
third message correcting whose moment an earlier story was. All three were
refused by ``classify-story --classify`` with
``failure=ClassifierContextError status=context_resolution_invalid`` — no
event, no claim, the exact death dates lost to the classifier.

The code is raised when ``timeline_evidence.normalize_resolution`` rejects an
event's ``timeline_resolution`` bookkeeping: a status the context's coverage
contradicts (``incomplete`` for a complete context, which is what a model
says when the vault does not know the place), or an echoed ``candidate_ids``
that is not the validator's own recomputed event-local set. Until v326 the
CLI path never asked for salvage, and a resolution failure was not salvageable
anywhere. These tests pin the refusal and the fix.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import classifier_claims  # noqa: E402
import classifier_context as cc  # noqa: E402
import classify_story  # noqa: E402
from test_classifier_context import ContextCase, node  # noqa: E402

JAMES_RECORD = """Actually, I just looked up on an app. This is information about him and when he died.

Name • 8 Sources
James Edwin Taylor Sr

Sex • 6 Sources
Male

Birth • 6 Sources
17 October 1930
Corpus Christi, Nueces, Texas, United States

Death • 3 Sources
4 April 1996
Apple Valley, San Bernardino, California, United States

Burial • 2 Sources
Victor Valley Memorial Park, Victorville, San Bernardino, California, United States
"""

DARVIN_RECORD = """Name • 9 Sources
Darvin Burrows Beauchamp

Birth • 7 Sources
30 September 1929
Inglewood, Los Angeles, California, United States

Death • 4 Sources
2 May 1996
Redlands, San Bernardino, California, United States

Burial • 2 Sources
1996
Calimesa, Riverside, California, United States
"""

CORRECTION = (
    "That was my grandma, Betty Joe, and Grandpa Jim, not me. That was them. "
    "I never lived there. I just visited."
)


def death_event(subject: str, stated: str, place: str, resolution: dict | None) -> dict:
    return {
        "title": f"Death of {subject}",
        "description": f"{subject} died in {place.split(',')[0]}.",
        "subject": subject,
        "places": [place],
        "when_hint": None,
        "anchor": None,
        "date": {"stated": stated, "age": None, "anchor_ref": None, "relation": None},
        "source_grounding": None,
        "timeline_relation": None,
        "timeline_resolution": resolution,
    }


class PastedRecordCase(ContextCase):
    """The fixture's Cedarport stay is the one candidate the vault knows; the
    record's places (Apple Valley, Redlands, Calimesa) are not in it."""

    def setUp(self) -> None:
        super().setUp()
        self.source = self.root / "sources" / "conversations" / "msg-record.md"
        self.source.parent.mkdir(parents=True, exist_ok=True)
        self.source.write_text(JAMES_RECORD, encoding="utf-8")

    def full_response(self, snapshot: dict, events: list[dict]) -> dict:
        return {
            "_classification_snapshot": cc.snapshot_metadata(snapshot),
            "people": [{"name": "James Edwin Taylor Sr"}],
            "places": [],
            "events": events,
        }

    def classify(self, response: dict, **kwargs) -> tuple[int, dict | None, str, str]:
        classifications = self.root / "state" / "classifications"
        candidates = self.root / "state" / "question_candidates.json"
        with mock.patch.object(classify_story, "REPO_DIR", self.root), \
                mock.patch.object(classify_story, "CLASSIFICATIONS_DIR", classifications), \
                mock.patch.object(classify_story, "QUESTION_CANDIDATES_FILE", candidates), \
                mock.patch.object(classify_story, "classify_with_ai") as model, \
                redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
            rc = classify_story.classify_file(
                self.source, "synthetic-recorded", precomputed_result=response, **kwargs,
            )
            path = classify_story.classification_path(self.source)
            saved = json.loads(path.read_text()) if path.exists() else None
        model.assert_not_called()
        return rc, saved, out.getvalue(), err.getvalue()


class UnfamiliarPlaceTests(PastedRecordCase):
    """James: the model reads an unknown place as an incomplete search."""

    def response(self, snapshot=None):
        snap = snapshot or self.snapshot()
        return self.full_response(snap, [death_event(
            "James Edwin Taylor Sr", "4 April 1996",
            "Apple Valley, San Bernardino, California, United States",
            {"status": "incomplete", "candidate_ids": [],
             "reason": "The supplied context does not know Apple Valley."},
        )])

    def test_the_refusal_is_reproduced_strictly(self):
        snapshot = self.snapshot()
        self.assertTrue(cc._event_context(snapshot, deepcopy(self.response(snapshot)["events"][0]))["complete"])
        with self.assertRaises(cc.ClassifierContextError) as raised:
            cc.validate_response(self.response(snapshot), snapshot, JAMES_RECORD)
        self.assertIs(raised.exception.code, cc.ContextFailureCode.RESOLUTION_INVALID)
        self.assertEqual(
            classify_story.failure_metadata("classify-schema", raised.exception, provider="ai"),
            "provider=ai operation=classify-schema failure=ClassifierContextError "
            "status=context_resolution_invalid",
        )

    def test_salvage_files_the_event_with_the_place_kept_as_text(self):
        snapshot = self.snapshot()
        downgrades: list = []
        out = cc.validate_response(
            self.response(snapshot), snapshot, JAMES_RECORD, salvage=True, downgrades=downgrades,
        )
        event = out["events"][0]
        self.assertEqual(event["places"], ["Apple Valley, San Bernardino, California, United States"])
        self.assertEqual(event["date"]["stated"], "4 April 1996")
        self.assertIsNone(event["timeline_relation"])
        self.assertEqual(event["timeline_resolution"]["status"], "missing_evidence")
        self.assertEqual(event["timeline_resolution"]["candidate_ids"], [])
        self.assertIn("[validator downgrade: resolution_incomplete_false]",
                      event["timeline_resolution"]["reason"])
        self.assertIn("does not know Apple Valley", event["timeline_resolution"]["reason"])
        self.assertEqual(downgrades, [{
            "event_key": event["event_key"], "field": "timeline_resolution",
            "code": "resolution_incomplete_false",
        }])

    def test_the_cli_files_the_record_and_its_date_claim(self):
        """The whole path the owner ran: ``classify-story --classify`` on the
        promoted message, ending in a stored reading whose death event yields a
        stated-date claim for the exact day the record gave."""
        rc, saved, out, err = self.classify(self.response())
        self.assertEqual(rc, 0, err)
        self.assertEqual(err, "")
        self.assertEqual(len(saved["events"]), 1)
        event = saved["events"][0]
        self.assertEqual(event["subject"], "James Edwin Taylor Sr")
        self.assertEqual(event["places"], ["Apple Valley, San Bernardino, California, United States"])
        self.assertEqual(saved["validation_downgrades"][0]["code"], "resolution_incomplete_false")
        self.assertIn("kept    : 1 event(s) filed without the model's link or proof "
                      "(validator downgrades: resolution_incomplete_false)", out)
        claims = classifier_claims.event_claims(
            stem="msg-record", event=event, revision="sha256:" + "a" * 64,
            source_path=saved["source_path"],
        )
        stated = [claim for claim in claims if claim.get("claim_type") == "date"]
        self.assertEqual(len(stated), 1, claims)
        claim = stated[0]
        self.assertEqual(claim["temporal_value"]["best"], "1996-04-04")
        self.assertEqual(claim["temporal_value"]["basis"], "stated")
        self.assertEqual(claim["subject_mention"], "James Edwin Taylor Sr")
        self.assertEqual(claim["event_mention"], "Death of James Edwin Taylor Sr")
        # The place travels as the words the record used; nothing resolved it.
        self.assertEqual(claim["place_mentions"],
                         ["Apple Valley, San Bernardino, California, United States"])
        self.assertEqual(claim["timeline_resolution_status"], "missing_evidence")

    def test_the_strict_verdict_is_still_available(self):
        rc, saved, out, err = self.classify(self.response(), salvage=False)
        self.assertEqual(rc, 1)
        self.assertIsNone(saved)
        self.assertIn("status=context_resolution_invalid", err)


class CandidateEchoTests(PastedRecordCase):
    """Darvin: the burial names Calimesa, the vault has a Calimesa stay, and
    the model's echoed candidate list is not the validator's own."""

    def setUp(self) -> None:
        super().setUp()
        self.write_projection([node("node:calimesa", "1994/1999", "claim:calimesa") | {
            "label": "Calimesa stay", "subject_refs": ["place/calimesa", "self"],
            "legacy_refs": ["calimesa"], "episode_id": "episode:calimesa",
        }])
        self.source.write_text(DARVIN_RECORD, encoding="utf-8")

    def burial(self, resolution: dict) -> dict:
        return {
            "title": "Burial of Darvin Burrows Beauchamp",
            "description": "Darvin Burrows Beauchamp was buried in Calimesa.",
            "subject": "Darvin Burrows Beauchamp",
            "places": ["Calimesa, Riverside, California, United States"],
            "when_hint": None, "anchor": None,
            "date": {"stated": "1996", "age": None, "anchor_ref": None, "relation": None},
            "source_grounding": None, "timeline_relation": None,
            "timeline_resolution": resolution,
        }

    def test_an_empty_echo_against_a_matched_stay_is_refused_strictly_and_completed_under_salvage(self):
        snapshot = self.snapshot()
        events = [
            death_event("Darvin Burrows Beauchamp", "2 May 1996",
                        "Redlands, San Bernardino, California, United States",
                        {"status": "missing_evidence", "candidate_ids": [],
                         "reason": "No supplied candidate covers Redlands."}),
            self.burial({"status": "missing_evidence", "candidate_ids": [],
                         "reason": "The stay is the owner's, not Darvin's."}),
        ]
        context = cc._event_context(snapshot, deepcopy(events[1]))
        self.assertEqual(context["candidate_ids"], ["node:calimesa"])
        with self.assertRaises(cc.ClassifierContextError) as raised:
            cc.validate_response(self.full_response(snapshot, deepcopy(events)), snapshot, DARVIN_RECORD)
        self.assertIs(raised.exception.code, cc.ContextFailureCode.RESOLUTION_INVALID)

        rc, saved, out, err = self.classify(self.full_response(snapshot, deepcopy(events)))
        self.assertEqual(rc, 0, err)
        death, burial = saved["events"]
        self.assertEqual(death["date"]["stated"], "2 May 1996")
        self.assertEqual(death["timeline_resolution"]["candidate_ids"], [])
        self.assertIsNone(burial["timeline_relation"])
        self.assertEqual(burial["timeline_resolution"]["status"], "missing_evidence")
        self.assertEqual(burial["timeline_resolution"]["candidate_ids"], ["node:calimesa"])
        self.assertEqual(burial["places"], ["Calimesa, Riverside, California, United States"])
        self.assertEqual(
            [row["code"] for row in saved["validation_downgrades"]],
            ["resolution_candidates_completed"],
        )

    def test_a_verified_link_survives_its_own_bookkeeping(self):
        """A relation that passed every check is not thrown away because the
        reason ran long: the link is kept and reported as linked."""
        self.source.write_text(
            DARVIN_RECORD + "\nWe buried him while we lived in Calimesa.\n", encoding="utf-8",
        )
        snapshot = self.snapshot()
        event = self.burial({
            "status": "linked", "candidate_ids": ["node:calimesa"], "reason": "x" * 400,
        })
        event["timeline_relation"] = {
            "relation": "within", "candidate_id": "node:calimesa",
            "entity_refs": ["place/calimesa"],
            "evidence": {"quote": "while we lived in Calimesa"},
        }
        story = self.source.read_text()
        with self.assertRaises(cc.ClassifierContextError) as raised:
            cc.validate_response(self.full_response(snapshot, [deepcopy(event)]), snapshot, story)
        self.assertIs(raised.exception.code, cc.ContextFailureCode.RESOLUTION_INVALID)
        downgrades: list = []
        out = cc.validate_response(
            self.full_response(snapshot, [deepcopy(event)]), snapshot, story,
            salvage=True, downgrades=downgrades,
        )
        kept = out["events"][0]
        self.assertEqual(kept["timeline_relation"]["candidate_id"], "node:calimesa")
        self.assertEqual(kept["timeline_resolution"]["status"], "linked")
        self.assertLessEqual(len(kept["timeline_resolution"]["reason"]), 300)
        self.assertEqual(downgrades[0]["code"], "resolution_reason_invalid")

    def test_a_valid_non_link_status_is_preserved(self):
        snapshot = self.snapshot()
        event = self.burial({
            "status": "not_temporal", "candidate_ids": ["node:calimesa"],
            "reason": "A burial place line, not a moment.", "extra": True,
        })
        out = cc.validate_response(
            self.full_response(snapshot, [event]), snapshot, DARVIN_RECORD, salvage=True,
        )
        self.assertEqual(out["events"][0]["timeline_resolution"]["status"], "not_temporal")

    def test_a_truncated_context_still_reads_incomplete(self):
        snapshot = self.snapshot()
        snapshot["context_truncated"] = True
        event = self.burial({
            "status": "missing_evidence", "candidate_ids": ["node:calimesa"], "reason": "Nothing fits.",
        })
        out = cc.validate_response(
            self.full_response(snapshot, [event]), snapshot, DARVIN_RECORD, salvage=True,
        )
        self.assertEqual(out["events"][0]["timeline_resolution"]["status"], "incomplete")


class BareCorrectionTests(PastedRecordCase):
    """'That was my grandma and Grandpa Jim, not me': no schema refusal, and
    nothing is filed as the owner's moment."""

    def setUp(self) -> None:
        super().setUp()
        self.source.write_text(CORRECTION, encoding="utf-8")

    def test_no_events_files_quietly_and_leaves_the_question_open(self):
        snapshot = self.snapshot()
        response = self.full_response(snapshot, [])
        response["people"] = [{"name": "Betty Joe"}, {"name": "Grandpa Jim"}]
        rc, saved, out, err = self.classify(response)
        self.assertEqual(rc, 0, err)
        self.assertEqual(err, "")
        self.assertEqual(saved["events"], [])
        self.assertEqual(saved["validation_downgrades"], [])
        self.assertNotIn("kept    :", out)
        self.assertEqual([row["name"] for row in saved["people"]], ["Betty Joe", "Grandpa Jim"])

    def test_a_rescoped_moment_with_bad_bookkeeping_files_as_theirs(self):
        """If the model does read a moment out of the correction, the words
        carry the subject (timeline-rules:9 reads 'my grandma' as somebody
        else) and a resolution the coverage rule contradicts no longer loses it."""
        snapshot = self.snapshot()
        event = {
            "title": "Grandparents' home",
            "description": "My grandma Betty Joe and Grandpa Jim lived there; I only visited.",
            "subject": "my grandma, Betty Joe, and Grandpa Jim",
            "places": [], "when_hint": None, "anchor": None,
            "date": None, "source_grounding": None, "timeline_relation": None,
            "timeline_resolution": {"status": "incomplete", "candidate_ids": [],
                                    "reason": "The place is not named."},
        }
        with self.assertRaises(cc.ClassifierContextError):
            cc.validate_response(self.full_response(snapshot, [deepcopy(event)]), snapshot, CORRECTION)
        rc, saved, out, err = self.classify(self.full_response(snapshot, [event]))
        self.assertEqual(rc, 0, err)
        self.assertEqual(saved["events"][0]["subject"], "my grandma, Betty Joe, and Grandpa Jim")
        self.assertEqual(saved["events"][0]["timeline_resolution"]["status"], "missing_evidence")
        # "lived there" reaches the fixture's stay by role, so the empty echo is
        # completed first and the contradicted status rebuilt second.
        self.assertEqual(
            [row["code"] for row in saved["validation_downgrades"]],
            ["resolution_candidates_completed", "resolution_incomplete_false"],
        )

    def test_structural_failures_still_refuse_on_the_cli(self):
        snapshot = self.snapshot()
        response = self.full_response(snapshot, [])
        response["_classification_snapshot"]["context_digest"] = "sha256:" + "0" * 64
        rc, saved, out, err = self.classify(response)
        self.assertEqual(rc, 1)
        self.assertIsNone(saved)
        self.assertIn("status=context_snapshot_mismatch", err)


class PromptGuidanceTests(PastedRecordCase):
    def test_the_prompt_names_unfamiliar_places_records_and_corrections(self):
        prompt = classify_story.build_prompt(
            self.source, {}, JAMES_RECORD, context_snapshot=self.snapshot(),
        )
        text = " ".join(prompt.split())
        for rule in (
            "A place the supplied context does not know is still the event's place",
            "an unfamiliar place never makes a complete context `incomplete`",
            "A pasted record about a named person (Name / Birth / Death / Burial lines)",
            "A message that only corrects WHOSE an already-told moment was",
        ):
            self.assertIn(rule, text)
        self.assertEqual(cc.PROMPT_VERSION, "contextual-timeline:3")


if __name__ == "__main__":
    unittest.main()
