"""CERT-10 — episode containment through the ONE rung (E-L2a).

Controlling design: lifehug-platform `docs/design/timeline-eras.md` v2.1 §4.1
and acceptance rows 5, 6 and 24; OSS ADR 0030's participation-episode
addendum. This file REPLACES `tests/test_place_co_location.py`, whose cases
these are.

The owner's sentence the retired rule was written for is unchanged:

    "If something's calculated from San Diego, all the other calculated
     San Diego things should be inferred to be around that range."

What changed is who answers it, and how honestly. `place_co_location` gave a
member the stay's span as its BEST value; the containment rung files a
`part_of` record and the fold renders the stay's span as a POSSIBLE OUTER
RANGE. Same fact, said as what it is — and one definition of "an undated thing
during a dated stay" instead of two.

What also changed is the construction, and that is the point. Every case here
runs through the REAL path: the recorder's own writer
(`landmark_projection.file_landmark_record`, which is what `landmark-record`
and the hosts' `landmark_invocations` call), the promoted source, the receipt,
the active index, `bind-episodes --apply` and the fold. The retired file built
`claim_type="range"`, `event_kind="residence"` claims by hand and said at its
own line 24 that on a real vault the rule "yields NOTHING today" — which was
true, and was the defect (design §0.2 M1), not a property of the fixture.

`tests/goldens/cert_10_place_containment.json` is the fixture. The platform's
`scripts/eras/certify_eras.py` owns the certification ROW; this file proves the
same numbers in the package, so the two hosts read one fixture (ADR 0021).

Synthetic data only; NEVER references ~/Workspace/dave.
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

import chronology as chrono  # noqa: E402
import conversation_lints as cl  # noqa: E402
import episode_binder as eb  # noqa: E402
import episode_fold as ef  # noqa: E402
import episode_fold_contract as efc  # noqa: E402
import landmark_projection as lp  # noqa: E402
import question_planner as qp  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import timeline as tl  # noqa: E402
import timeline_interaction as ti  # noqa: E402
from tempdirs import root_parent_tmp  # noqa: E402

CERT_10 = json.loads(
    (ROOT / "tests" / "goldens" / "cert_10_place_containment.json").read_text("utf-8")
)

NOW = "2026-09-01T12:00:00Z"


def revision(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def year(text: str) -> dict:
    return {"best": text, "earliest": text, "latest": text, "granularity": "year",
            "basis": "stated", "confidence": "certain"}


def moment_claim(row: dict, *, temporal_value: object = None) -> dict:
    """One classifier moment, shaped exactly as `classifier_claims` files it —
    including the per-moment ``event_ref``, without which every moment groups
    into ONE node (that module says so in its own docstring)."""
    payload = {
        "source_kind": "conversation",
        "source_ref": {"source_id": row["source"], "revision": revision(row["source"])},
        "evidence": [{"quote": row["quote"]}],
        "extractor_version": "classifier:1",
        "created_at": "2026-08-30T00:00:00Z",
        "basis": "explicit",
        "confidence": 0.9,
        "status": "active",
        "claim_type": "occurrence",
        "subject_mention": "I",
        "event_mention": row["mention"],
        "event_kind": "moment",
        "event_ref": tp.derive_node_id(
            node_kind="event", event_kind="moment",
            subject_refs=["I"], discriminator=row["source"],
        ),
    }
    if temporal_value is not None:
        payload["claim_type"] = "date"
        payload["temporal_value"] = temporal_value
    return tc.validate_temporal_claim(payload)


class CertCase(unittest.TestCase):
    """One CERT-10 case, built and folded through the real path."""

    CASE = ""
    ROSTER: object = None
    EXTRA_MOMENTS: tuple = ()

    def setUp(self) -> None:
        self.case = CERT_10["cases"][self.CASE]
        self.expected = self.case["expected"]
        self.root = root_parent_tmp(self, ROOT, prefix="cert10-")
        (self.root / "state").mkdir(parents=True, exist_ok=True)
        (self.root / "sources").mkdir(parents=True, exist_ok=True)
        roster = self.ROSTER if self.ROSTER is not None else CERT_10["place_roster"]
        rosters = self.root / "state" / "entity_rosters"
        rosters.mkdir(parents=True, exist_ok=True)
        (rosters / f"{roster['type']}.json").write_text(json.dumps(roster), "utf-8")

        lp.file_landmark_record(
            self.root, "birth",
            {"domain": "birth", "label": "birth",
             "date": {"best": CERT_10["owner_birth"], "earliest": CERT_10["owner_birth"],
                      "latest": CERT_10["owner_birth"], "granularity": "day",
                      "basis": "stated", "confidence": "certain"}},
            ordinal=1, now=NOW,
        )
        for ordinal, stay in enumerate(self.case["stays"], start=2):
            entry = {k: v for k, v in stay.items() if k not in ("domain", "span")}
            entry["span"] = {"start": year(stay["span"]["start"]),
                             "end": year(stay["span"]["end"])}
            lp.file_landmark_record(self.root, stay["domain"], entry,
                                    ordinal=ordinal, now=NOW)
        for row in (*self.case["moments"], *self.EXTRA_MOMENTS):
            claim = moment_claim(row, temporal_value=row.get("temporal_value"))
            ts.write_receipt(self.root, {
                "source_ref": claim["source_ref"],
                "extractor_version": "classifier:1",
                "created_at": "2026-08-30T00:00:00Z",
                "claims": [claim],
            })
        ts.rebuild_active_index(self.root)
        self.binder = eb.bind_episodes(
            self.root, apply=True, now=NOW, containment_authority="applied")
        self.result = self.fold()

    def fold(self):
        return tt.derive_calculated_timeline(
            ts.fold_active_index(self.root),
            episode_records=ef.load_episode_records(self.root),
            landmark_entries=lp.load_landmark_sources(self.root),
            now=NOW,
        )

    # -- readers ---------------------------------------------------------

    def moment_nodes(self) -> list[dict]:
        return [row for row in self.result.nodes if row.get("event_kind") == "moment"]

    def residence_nodes(self) -> list[dict]:
        return [row for row in self.result.nodes if row.get("event_kind") == "residence"]

    def windowed(self) -> list[dict]:
        return [row for row in self.moment_nodes()
                if row.get("possible_temporal_value")]

    def items_of_kind(self, kind: str) -> list[dict]:
        return [row for row in self.result.work_items if row.get("kind") == kind]


class TheRuleIsWrittenDown(unittest.TestCase):
    """The rule text lives as a constant, and the retirement says so too."""

    def test_the_rule_version_tracks_the_current_rules(self):
        self.assertEqual(tt.CALCULATION_RULE_VERSION, "timeline-rules:5")
        self.assertEqual(tt.CALCULATION_RULE_VERSION,
                         CERT_10["calculation_rule_version"])

    def test_the_retired_rule_is_gone_and_says_where_it_went(self):
        """The epitaph is the test: a reader who greps for the old rule finds
        the two homes its two jobs moved to, not a silent absence."""
        self.assertFalse(hasattr(tt, "COLOCATION_RULE_ID"))
        self.assertFalse(hasattr(tt, "COLOCATION_EPISODE_KINDS"))
        for phrase in ("containment rung", "possible outer range",
                       "place_ambiguous", "tenure_ambiguous"):
            self.assertIn(phrase, tt.COLOCATION_RETIRED)

    def test_the_containment_rule_text_says_all_three_cases(self):
        import episode_containers as ec  # noqa: PLC0415

        for phrase in ("EXACTLY ONE", "place_ambiguous", "tenure_ambiguous"):
            self.assertIn(phrase, ec.CONTAINMENT_UNIQUENESS_RULE_TEXT)
        for phrase in ("never narrower", "never overrides"):
            self.assertIn(phrase, efc.CONTAINMENT_RULE_TEXT)

    def test_both_ambiguity_kinds_are_declared_work_item_kinds(self):
        self.assertIn("place_ambiguous", tp.WORK_ITEM_KINDS)
        self.assertIn("tenure_ambiguous", tp.WORK_ITEM_KINDS)


class OneDatedEpisode(CertCase):
    """CERT-10 case 1: three moments naming one dated residence."""

    CASE = "one_dated_episode"

    def test_the_stay_is_one_residence_episode(self):
        self.assertEqual(len(self.residence_nodes()),
                         self.expected["residence_episodes"])

    def test_every_member_gets_the_stay_as_its_window(self):
        windowed = self.windowed()
        self.assertEqual(len(windowed), self.expected["contained_nodes"])
        for row in windowed:
            value = row["possible_temporal_value"]
            self.assertEqual(value["earliest"], self.expected["window"]["earliest"])
            self.assertEqual(value["latest"], self.expected["window"]["latest"])
            self.assertEqual(value["basis"], self.expected["node_basis"])
            self.assertIsNone(row.get("best_temporal_value"))

    def test_the_row_says_how_it_knows(self):
        row = self.windowed()[0]
        provenance = row["possible_temporal_value"]["provenance"]
        entry = next(e for e in provenance
                     if e.get("rule") == efc.CONTAINMENT_RULE_ID)
        self.assertEqual(entry["claim"], self.expected["provenance_claim"])
        self.assertTrue(
            entry["source"].startswith(self.expected["provenance_source_prefix"]))
        self.assertEqual(entry["basis"], "inferred")

    def test_the_sentence_a_person_reads_is_not_attributed_to_them(self):
        row = self.windowed()[0]
        rendered = chrono.display_date(
            chrono.from_dict(row["possible_temporal_value"]))
        self.assertNotIn("you said", rendered)
        self.assertIn(self.expected["provenance_claim"], rendered)

    def test_the_window_is_never_narrower_than_the_stay(self):
        span = chrono.from_dict(
            self.residence_nodes()[0]["best_temporal_value"])
        for row in self.windowed():
            value = chrono.from_dict(row["possible_temporal_value"])
            self.assertLessEqual(
                chrono._ordinal(value.earliest, end=False),  # noqa: SLF001
                chrono._ordinal(span.earliest, end=False),  # noqa: SLF001
            )
            self.assertGreaterEqual(
                chrono._ordinal(value.latest, end=True),  # noqa: SLF001
                chrono._ordinal(span.latest, end=True),  # noqa: SLF001
            )

    def test_a_window_does_not_silence_the_question(self):
        """§7.1 / H6: render-placeable is not date-resolved. A window is a
        bound, not an answer, and every member still owes its own date."""
        nodes = {row["node_id"] for row in self.moment_nodes()}
        asked = {row.get("node_ref") for row in self.result.work_items}
        self.assertTrue(nodes <= asked, f"unasked: {sorted(nodes - asked)}")

    def test_the_rung_that_filed_it_is_named(self):
        by_rule = self.binder["plan"].counts["containment_by_rule"]
        self.assertEqual(by_rule[self.expected["rule_id"]],
                         self.expected["contained_nodes"])

    def test_no_ambiguity_item_is_minted(self):
        self.assertEqual(self.items_of_kind("place_ambiguous"), [])

    def test_two_rebuilds_are_identical(self):
        """Deterministic, no model call."""
        first = tt.structural_signature(self.result)
        second = tt.structural_signature(self.fold())
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(second, sort_keys=True))


class TwoEpisodesAtTheSamePlace(CertCase):
    """CERT-10 case 2: moved away and came back — no containment, one item."""

    CASE = "two_episodes_same_place"

    def test_two_stays_at_one_place_are_two_episodes(self):
        self.assertEqual(len(self.residence_nodes()),
                         self.expected["residence_episodes"])

    def test_nothing_is_placed(self):
        self.assertEqual(len(self.windowed()), self.expected["contained_nodes"])
        self.assertEqual(
            self.binder["plan"].counts["containment_by_rule"]["entity_span"], 0)

    def test_the_rung_says_why_it_refused(self):
        refused = self.binder["plan"].containment_ambiguities
        self.assertEqual(len(refused), 1)
        self.assertEqual(refused[0]["entity"], "place/san-diego")
        self.assertEqual(refused[0]["kind"], self.expected["work_item_kind"])

    def test_one_place_ambiguous_item_is_minted_and_names_the_place(self):
        items = self.items_of_kind(self.expected["work_item_kind"])
        self.assertEqual(len(items), self.expected["place_ambiguous_items"])
        self.assertIn("San Diego", items[0]["prompt_intent"] or "")
        self.assertIn("timeline", items[0]["allowed_surfaces"])

    def test_the_question_is_a_sentence_a_person_would_say(self):
        """D3's deterministic backstop applies to this kind too — a lint
        finding would have minted `prompt_intent: None` and a withheld
        reason."""
        item = self.items_of_kind(self.expected["work_item_kind"])[0]
        self.assertEqual(cl.lint_question(item["prompt_intent"]), [])
        self.assertIsNone(item.get("withheld_reason"))
        self.assertEqual(item["prompt_intent"], self.expected["prompt_intent"])

    def test_the_item_is_openable(self):
        """An item no host can open is invisible work (ADR 0021)."""
        for kind in ("place_ambiguous", "tenure_ambiguous"):
            self.assertIn(kind, ti.WORK_ITEM_KINDS)
            self.assertIn(kind, ti.WORK_ITEM_PROBES)
            self.assertIn(kind, qp.WORK_ITEM_PLACEMENT_GAIN)


class NoEpisodeAtAll(CertCase):
    """CERT-10 case 3: zero matching stays leaves the moment alone."""

    CASE = "no_episode"

    def test_the_moment_is_unchanged(self):
        self.assertEqual(len(self.windowed()), self.expected["contained_nodes"])
        self.assertEqual(len(self.items_of_kind("place_ambiguous")),
                         self.expected["place_ambiguous_items"])


class ThePlaceRosterFoldsAliases(CertCase):
    """The roster is what makes "SD" and "San Diego" one place.

    The rung's entity signal resolves a mention THROUGH the roster
    (`episode_containers.resolve_entity_set`), so an alias reaches the stay and
    a word no roster knows reaches nothing. That is the whole difference a
    roster makes, and it is the same difference the retired rule tested.
    """

    CASE = "no_episode"

    def setUp(self) -> None:
        self.__class__.EXTRA_MOMENTS = ()
        super().setUp()

    def _fold_with(self, roster: dict, mention: str) -> list[dict]:
        root = root_parent_tmp(self, ROOT, prefix="cert10-alias-")
        (root / "state").mkdir(parents=True, exist_ok=True)
        (root / "sources").mkdir(parents=True, exist_ok=True)
        rosters = root / "state" / "entity_rosters"
        rosters.mkdir(parents=True, exist_ok=True)
        (rosters / f"{roster['type']}.json").write_text(json.dumps(roster), "utf-8")
        lp.file_landmark_record(
            root, "residences",
            {"label": "San Diego", "city": "San Diego",
             "span": {"start": year("1988"), "end": year("1990")}},
            ordinal=1, now=NOW,
        )
        claim = moment_claim({"source": "classification:answers-sd#sd",
                              "mention": mention,
                              "quote": "we went to the zoo"})
        ts.write_receipt(root, {
            "source_ref": claim["source_ref"], "extractor_version": "classifier:1",
            "created_at": "2026-08-30T00:00:00Z", "claims": [claim],
        })
        ts.rebuild_active_index(root)
        eb.bind_episodes(root, apply=True, now=NOW, containment_authority="applied")
        found = tt.derive_calculated_timeline(
            ts.fold_active_index(root),
            episode_records=ef.load_episode_records(root),
            landmark_entries=lp.load_landmark_sources(root),
            now=NOW,
        )
        return [row for row in found.nodes
                if row.get("event_kind") == "moment"
                and row.get("possible_temporal_value")]

    def test_an_alias_reaches_the_stay(self):
        self.assertTrue(
            self._fold_with(CERT_10["place_roster"], "The coast house zoo trip"))

    def test_a_word_no_roster_knows_reaches_nothing(self):
        self.assertFalse(
            self._fold_with(CERT_10["place_roster"], "The Northgate zoo trip"),
            "a mention nothing recognizes placed a story",
        )

    def test_a_two_letter_alias_is_below_the_name_floor(self):
        """`episode_containers.ENTITY_KEY_MIN_CHARS` — a one-token key this
        short is not a name, and the retired rule had no such floor. "SD" is
        in the roster and still resolves nothing, which is the floor doing its
        job rather than the alias failing to."""
        self.assertIn("SD", CERT_10["place_roster"]["entities"][0]["aliases"])
        self.assertFalse(self._fold_with(CERT_10["place_roster"], "The SD zoo trip"))


class ContainmentNeverOverridesAStatement(CertCase):
    """The promise that makes the rung safe to run on every rebuild."""

    CASE = "one_dated_episode"
    EXTRA_MOMENTS = ()

    def setUp(self) -> None:
        self.__class__.EXTRA_MOMENTS = ({
            "source": "classification:answers-zoo-dated#zoo-dated",
            "mention": "The San Diego picnic",
            "quote": "the picnic was the summer of 1989",
            "temporal_value": {"best": "1989-07", "earliest": "1989-07",
                               "latest": "1989-07", "granularity": "month",
                               "basis": "stated", "confidence": "certain"},
        },)
        super().setUp()

    def test_a_stated_date_keeps_its_own_value_and_gets_no_window(self):
        stated = [row for row in self.moment_nodes()
                  if row.get("best_temporal_value")
                  and row["best_temporal_value"].get("earliest") == "1989-07"]
        self.assertTrue(stated, "the stated moment lost its own date")
        for row in stated:
            self.assertIsNone(
                row.get("possible_temporal_value"),
                "a containment was written over something somebody said",
            )


class OnlyTheOwnersOwnEpisodesDate(unittest.TestCase):
    """eras §5: a relative's history never rides onto the owner's axis on a
    stated relationship alone. An episode that is not the owner's is not
    evidence about where the OWNER was."""

    def _group(self, **overrides) -> dict:
        base = {"node_id": "ep:x", "node_kind": "episode", "event_kind": "job",
                "subject": "person/uncle-ray", "resolved": True, "claims": []}
        base.update(overrides)
        return base

    def test_a_job_the_owner_did_not_hold_is_not_on_the_axis(self):
        group = self._group(claims=[{
            "claim_id": "claim:x",
            "subject_resolution": {"reason": "ambiguous_candidates"},
        }])
        self.assertFalse(tt._episode_on_owner_axis(  # noqa: SLF001
            group, is_place_subject=False, best=None,
            entry_index={}, owner="self", birth=None,
        ))

    def test_a_place_subject_episode_is_always_on_the_axis(self):
        self.assertTrue(tt._episode_on_owner_axis(  # noqa: SLF001
            self._group(event_kind="residence", subject="place/san-diego"),
            is_place_subject=True, best=None,
            entry_index={}, owner="self", birth=None,
        ))

    def test_the_owners_own_narration_is_on_the_axis(self):
        self.assertTrue(tt._episode_on_owner_axis(  # noqa: SLF001
            self._group(subject="the shop", resolved=False),
            is_place_subject=False, best=None,
            entry_index={}, owner="self", birth=None,
        ))


class TheScoreCountsInferredAtHalf(unittest.TestCase):
    """ADR 0027: `w = 0.5` of an explicit placement, and the arithmetic is
    written into the score module rather than asserted in a PR body."""

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
        doc = (tl.placement_score.__doc__ or "").replace(" ", "")
        self.assertIn("(L+w", doc)
        self.assertIn("INFERRED_PLACEMENT_WEIGHT", doc)

    def test_an_inferred_placement_earns_half_the_credit(self):
        stated = tl.placement_score(self._data("stated"))
        inferred = tl.placement_score(self._data("order"))
        self.assertIsNotNone(stated)
        self.assertIsNotNone(inferred)
        self.assertEqual(inferred["score_formula_version"],
                         tl.PLACEMENT_SCORE_FORMULA_VERSION)
        self.assertAlmostEqual(inferred["score"], stated["score"] / 2.0, places=3)
        self.assertEqual(inferred["score_stated"], 0.0)
        self.assertGreater(float(stated["life_span_years"]), 0.0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
