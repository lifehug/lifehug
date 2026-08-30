"""v264 — place co-location inference, `timeline-rules:4`.

Contract: lifehug-platform `docs/pr-specs/timeline-fix/05-one-timeline.md`
§3 and §8.3 (Timeline Fix 05, PR D). The owner's third sentence, read off his
own Timeline on 2026-08-29:

    "If something's calculated from San Diego, all the other calculated
     San Diego things should be inferred to be around that range."

The rule under test is `temporal_timeline.COLOCATION_RULE_TEXT`, and these
tests are its three cases plus the four promises that travel with it: an
inference is never NARROWER than the episode span it came from, it never
overrides something somebody stated, it is worth HALF of a stated placement
in the ADR 0027 score, and a rebuild from the same claims is byte-identical.

`tests/goldens/cert_10_place_co_location.json` is CERT-10's fixture. The
platform's `scripts/eras/certify_eras.py` owns the certification ROW; this
file proves the same numbers in the package, so the two hosts read one
fixture rather than two hand-copied expectations (ADR 0021).

Synthetic data only; NEVER references ~/Workspace/dave. On the founder's own
vault this rule yields NOTHING today — his residence landmarks are one
UNDATED entry (lifehug#293's evidence) — which is why every case here is
built on a synthetic vault and said out loud rather than measured live.
"""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))

import chronology as chrono  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import temporal_work_items as twi  # noqa: E402
import timeline as tl  # noqa: E402

CERT_10 = json.loads(
    (ROOT / "tests" / "goldens" / "cert_10_place_co_location.json").read_text("utf-8")
)

NOW = "2026-08-29T12:00:00Z"


def revision(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def claim(**overrides) -> dict:
    source = overrides.pop("source", "src-1")
    payload = {
        "source_kind": "conversation",
        "source_ref": {"source_id": source, "revision": revision(source)},
        "evidence": [{"quote": overrides.pop("quote", "a sentence from the story")}],
        "extractor_version": "classifier:1",
        "created_at": "2026-08-29T00:00:00Z",
        "basis": "explicit",
        "confidence": 0.9,
        "status": "active",
    }
    payload.update(overrides)
    return tc.validate_temporal_claim(payload)


def birth_claim() -> dict:
    return claim(
        claim_type="date",
        subject_mention="I",
        event_kind="birth",
        source="s-birth",
        quote="I was born on 11 July 1981",
        temporal_value={
            "best": CERT_10["owner_birth"], "earliest": CERT_10["owner_birth"],
            "latest": CERT_10["owner_birth"], "granularity": "day",
            "basis": "stated", "confidence": "certain",
        },
    )


def episode_claim(row: dict) -> dict:
    return claim(
        claim_type="range",
        subject_mention=row["place"],
        event_kind=row["event_kind"],
        event_ref=row["event_ref"],
        source=f"s-{row['event_ref']}",
        quote=f"we lived in {row['place']}",
        temporal_value=row["temporal_value"],
    )


def moment_claim(row: dict) -> dict:
    """One migrated classifier moment, shaped exactly as `classifier_claims`
    files it — including the per-moment ``event_ref``, without which every
    moment of the owner's groups into ONE node (that module says so in its own
    docstring, and a fixture that skipped it would test the wrong thing)."""
    return claim(
        claim_type="occurrence",
        subject_mention="I",
        event_kind="moment",
        event_ref=tp.derive_node_id(
            node_kind="event", event_kind="moment",
            subject_refs=["I"], discriminator=row["source"],
        ),
        source=row["source"],
        quote=row["quote"],
        place_mentions=row["place_mentions"],
    )


def case_claims(name: str) -> list[dict]:
    case = CERT_10["cases"][name]
    rows = [birth_claim()]
    rows.extend(episode_claim(row) for row in case["episodes"])
    rows.extend(moment_claim(row) for row in case["moments"])
    return rows


def derive(claims, **kwargs):
    kwargs.setdefault("now", NOW)
    index = {"version": ts.INDEX_VERSION, "claims": [dict(row) for row in claims]}
    return tt.derive_calculated_timeline(index, **kwargs)


def moment_nodes(result) -> list[dict]:
    return [row for row in result.nodes if row.get("event_kind") == "moment"]


def items_of_kind(result, kind: str) -> list[dict]:
    return [row for row in result.work_items if row.get("kind") == kind]


class TheRuleIsWrittenDown(unittest.TestCase):
    """§8.3 asks for the rule text as a constant, and for the version to move."""

    def test_the_rule_version_moves_to_four(self):
        self.assertEqual(tt.CALCULATION_RULE_VERSION, "timeline-rules:4")
        self.assertEqual(
            tt.CALCULATION_RULE_VERSION, CERT_10["calculation_rule_version"]
        )

    def test_the_rule_text_says_all_three_cases(self):
        text = tt.COLOCATION_RULE_TEXT
        for phrase in ("exactly ONE", "never narrower", "inferred", "place_ambiguous"):
            self.assertIn(phrase, text)
        self.assertEqual(tt.COLOCATION_RULE_ID, "place_co_location")

    def test_place_ambiguous_is_a_declared_work_item_kind(self):
        self.assertIn("place_ambiguous", tp.WORK_ITEM_KINDS)


class OneDatedEpisode(unittest.TestCase):
    """CERT-10 case 1: three co-located moments, one dated residence."""

    def setUp(self):
        self.expected = CERT_10["cases"]["one_dated_episode"]["expected"]
        self.result = derive(case_claims("one_dated_episode"))

    def test_every_co_located_moment_is_inferred_into_the_span(self):
        placed = [row for row in moment_nodes(self.result)
                  if row.get("best_temporal_value")]
        self.assertEqual(len(placed), self.expected["inferred_nodes"])
        for row in placed:
            value = row["best_temporal_value"]
            self.assertEqual(
                value["earliest"],
                self.expected["inferred_best_temporal_value"]["earliest"],
            )
            self.assertEqual(
                value["latest"],
                self.expected["inferred_best_temporal_value"]["latest"],
            )
            self.assertEqual(row["basis"], self.expected["node_basis"])

    def test_the_row_says_how_it_knows(self):
        row = next(r for r in moment_nodes(self.result) if r.get("best_temporal_value"))
        provenance = row["best_temporal_value"]["provenance"]
        entry = next(e for e in provenance if e.get("rule") == tt.COLOCATION_RULE_ID)
        self.assertEqual(entry["claim"], self.expected["provenance_claim"])
        self.assertEqual(entry["source"], self.expected["provenance_source"])
        self.assertEqual(entry["basis"], "inferred")

    def test_the_sentence_a_person_reads_is_not_attributed_to_them(self):
        row = next(r for r in moment_nodes(self.result) if r.get("best_temporal_value"))
        rendered = chrono.display_date(row["best_temporal_value"])
        self.assertNotIn("you said", rendered)
        self.assertIn(self.expected["provenance_claim"], rendered)

    def test_the_inference_is_never_narrower_than_the_episode_span(self):
        episode = CERT_10["cases"]["one_dated_episode"]["episodes"][0]
        span = chrono.from_dict(episode["temporal_value"])
        for row in moment_nodes(self.result):
            value = chrono.from_dict(row["best_temporal_value"])
            if value is None:
                continue
            self.assertLessEqual(
                chrono._ordinal(value.earliest, end=False),  # noqa: SLF001
                chrono._ordinal(span.earliest, end=False),  # noqa: SLF001
            )
            self.assertGreaterEqual(
                chrono._ordinal(value.latest, end=True),  # noqa: SLF001
                chrono._ordinal(span.latest, end=True),  # noqa: SLF001
            )

    def test_an_inference_does_not_silence_the_question(self):
        """The moment still needs its own date; the inference is a bound, not
        an answer. `_wants_precision` would otherwise read a year-granularity
        span as "already precise enough" and the ▸ would vanish."""
        nodes = {row["node_id"] for row in moment_nodes(self.result)}
        asked = {row.get("node_ref") for row in self.result.work_items}
        self.assertTrue(nodes <= asked, f"unasked: {sorted(nodes - asked)}")

    def test_no_ambiguity_item_is_minted(self):
        self.assertEqual(items_of_kind(self.result, "place_ambiguous"), [])


class TwoEpisodesAtTheSamePlace(unittest.TestCase):
    """CERT-10 case 2: moved away and back — no inference, one work item."""

    def setUp(self):
        self.expected = CERT_10["cases"]["two_episodes_same_place"]["expected"]
        self.result = derive(case_claims("two_episodes_same_place"))

    def test_nothing_is_inferred(self):
        placed = [row for row in moment_nodes(self.result)
                  if row.get("best_temporal_value")]
        self.assertEqual(len(placed), self.expected["inferred_nodes"])

    def test_one_place_ambiguous_item_is_minted_and_names_the_place(self):
        items = items_of_kind(self.result, "place_ambiguous")
        self.assertEqual(len(items), self.expected["place_ambiguous_items"])
        self.assertIn("San Diego", items[0]["prompt_intent"] or "")
        self.assertIn("timeline", items[0]["allowed_surfaces"])

    def test_the_question_is_a_sentence_a_person_would_say(self):
        """D3's deterministic backstop applies to this kind too — a lint
        finding would have minted `prompt_intent: None` and a withheld
        reason, and the assertion above would have caught it, but the lint
        itself is the promise worth pinning."""
        import conversation_lints as cl  # noqa: PLC0415

        item = items_of_kind(self.result, "place_ambiguous")[0]
        self.assertEqual(cl.lint_question(item["prompt_intent"]), [])
        self.assertIsNone(item.get("withheld_reason"))
        self.assertIn("1988–1990", item["prompt_intent"])
        self.assertIn("1996–1999", item["prompt_intent"])

    def test_the_item_is_openable(self):
        """An item no host can open is invisible work (ADR 0021)."""
        import timeline_interaction as ti  # noqa: PLC0415

        self.assertIn("place_ambiguous", ti.WORK_ITEM_KINDS)
        self.assertIn("place_ambiguous", ti.WORK_ITEM_PROBES)
        import question_planner as qp  # noqa: PLC0415

        self.assertIn("place_ambiguous", qp.WORK_ITEM_PLACEMENT_GAIN)


class NoEpisodeAtAll(unittest.TestCase):
    """CERT-10 case 3: zero matching episodes leaves the moment alone."""

    def test_the_moment_is_unchanged(self):
        expected = CERT_10["cases"]["no_episode"]["expected"]
        result = derive(case_claims("no_episode"))
        placed = [row for row in moment_nodes(result) if row.get("best_temporal_value")]
        self.assertEqual(len(placed), expected["inferred_nodes"])
        self.assertEqual(len(items_of_kind(result, "place_ambiguous")),
                         expected["place_ambiguous_items"])


class InferenceNeverOverridesAStatement(unittest.TestCase):
    """The promise that makes the rule safe to run on every rebuild."""

    def test_a_stated_date_survives_a_co_located_residence(self):
        rows = case_claims("one_dated_episode")
        rows.append(claim(
            claim_type="date",
            subject_mention="I",
            event_kind="moment",
            event_ref=tp.derive_node_id(
                node_kind="event", event_kind="moment",
                subject_refs=["I"], discriminator="s-zoo",
            ),
            source="s-zoo-dated",
            quote="the zoo was the summer of 1989",
            temporal_value={"best": "1989-07", "earliest": "1989-07",
                            "latest": "1989-07", "granularity": "month",
                            "basis": "stated", "confidence": "certain"},
        ))
        result = derive(rows)
        stated = [row for row in moment_nodes(result)
                  if row.get("basis") == "explicit"]
        self.assertTrue(stated, "the stated moment lost its own date")
        for row in stated:
            self.assertEqual(row["best_temporal_value"]["earliest"], "1989-07")
            self.assertFalse([
                entry for entry in row["best_temporal_value"]["provenance"]
                if entry.get("rule") == tt.COLOCATION_RULE_ID
            ], "an inference was written over something somebody said")


class ByteStability(unittest.TestCase):
    """Deterministic, no model call: rebuild twice, identical bytes."""

    def test_two_rebuilds_are_identical(self):
        rows = case_claims("one_dated_episode")
        first = tt.structural_signature(derive(rows))
        second = tt.structural_signature(derive(list(reversed(rows))))
        self.assertEqual(
            json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True)
        )


class TheScoreCountsInferredAtHalf(unittest.TestCase):
    """ADR 0027, §8.3: `w = 0.5` of an explicit placement, and the arithmetic
    is written into the score module rather than asserted in a PR body."""

    LIFE = 40

    def _data(self, basis: str) -> dict:
        return {
            "anchors": {"birth": {"date": {"best": "1981-07-11",
                                           "earliest": "1981-07-11",
                                           "latest": "1981-07-11",
                                           "granularity": "day",
                                           "basis": "stated",
                                           "confidence": "certain"}}},
            "periods": [],
            "bands": [],
            "unplaced_events": [],
            "event_lineup": {"childhood": [{
                "slug": "zoo", "title": "the zoo",
                "date": {"best": "1988/1990", "earliest": "1988", "latest": "1990",
                         "granularity": "year", "basis": basis,
                         "confidence": "inferred" if basis == "order" else "certain"},
            }]},
        }

    def test_the_weight_is_one_half(self):
        self.assertEqual(tl.INFERRED_PLACEMENT_WEIGHT, 0.5)
        self.assertEqual(tl.PLACEMENT_SCORE_FORMULA_VERSION,
                         CERT_10["placement_score"]["score_formula_version"])

    def test_the_arithmetic_is_in_the_docstring(self):
        """§8.3 asks for the arithmetic in the score module, not in a PR body."""
        doc = (tl.placement_score.__doc__ or "").replace(" ", "")
        self.assertIn("(L+w", doc)
        self.assertIn("timeline-rules:4", doc)
        self.assertIn("INFERRED_PLACEMENT_WEIGHT", doc)

    def test_an_inferred_placement_earns_half_the_credit(self):
        stated = tl.placement_score(self._data("stated"))
        inferred = tl.placement_score(self._data("order"))
        self.assertIsNotNone(stated)
        self.assertIsNotNone(inferred)
        self.assertEqual(inferred["score_formula_version"],
                         tl.PLACEMENT_SCORE_FORMULA_VERSION)
        life = float(stated["life_span_years"])
        # credit = (L - w)/L for one thing; half of it when inferred.
        self.assertAlmostEqual(inferred["score"], stated["score"] / 2.0, places=3)
        # An inference is not something anybody stated, so the stated basis
        # reads it as unplaced and `score_stated` is zero.
        self.assertEqual(inferred["score_stated"], 0.0)
        self.assertGreater(life, 0.0)


if __name__ == "__main__":
    unittest.main()
