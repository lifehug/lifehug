"""Cut 5a — landmark opportunities and sufficiency from the calculated graph.

The defect (Codex audit F7, owner ruling R2 of 2026-09-03): `Landmarks.tsx`
reads the legacy domain rows, filters on ``status != complete`` and says "Your
landmarks are all filled in" when nine ladders are full. A checklist privileges
a domain worth nothing and hides an anchor worth everything. "Sufficient" is
supposed to mean *the remaining landmark questions no longer offer enough
expected improvement to justify a privileged surface*.

So the cases below are about a graph, not a form:

* a residence ladder that is COMPLETE and whose stay is still open at one end,
  with five events sitting inside it — one opportunity, worth 6, naming the
  house;
* a ladder whose only remaining gaps are worth 1 — no opportunity at all, and
  the domain says why it collapsed;
* a person the ladder enumerates and nobody dated — *"When did you and Katie
  first meet?"*, never *"When did this part begin?"*;
* the same question, twice, from two rebuilds — the same id, so it is never
  asked twice;
* losses, which are offered and never asked;
* a closed list the person closed;
* and the threshold, which is the QUEUE's dial and not a second number.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "system"
sys.path.insert(0, str(SYSTEM))

import episode_binder as eb  # noqa: E402
import episode_fold as ef  # noqa: E402
import landmark_opportunities as lo  # noqa: E402
import landmark_projection as lp  # noqa: E402
import landmarks_interaction as li  # noqa: E402
import question_planner as qp  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_publication as pub  # noqa: E402
import temporal_store as ts  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import timeline_gain as tg  # noqa: E402

NOW = "2026-09-01T12:00:00Z"

#: The dial's value at this pin. Spelled once so every expectation below reads
#: as "the bar", and pinned to the queue's own definition by
#: `TheThresholdIsOneDial`.
BAR = 6


def revision(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def year(text: str) -> dict:
    return {"best": text, "earliest": text, "latest": text, "granularity": "year",
            "basis": "stated", "confidence": "certain"}


# --------------------------------------------------------------------------
# A hand-written graph — the arithmetic, without a vault
# --------------------------------------------------------------------------


def stay(node_id: str, label: str, *, event_kind: str = "residence",
         best: object = None) -> dict:
    """One participation episode node, with only the fields this module reads."""
    row = {"node_id": node_id, "node_kind": "episode", "event_kind": event_kind,
           "label": label}
    if best is not None:
        row["best_temporal_value"] = best
    return row


def inside(node_id: str, episode_node_id: str) -> dict:
    """One event the containment rung put inside a stay (D2)."""
    return {"node_id": node_id, "node_kind": "event", "event_kind": "moment",
            "containments": [{"episode_node_id": episode_node_id}]}


def graph(nodes: object = (), items: object = (), ordering: object = ()) -> dict:
    """A projection-shaped mapping whose index is REALLY derived.

    `timeline_gain.dependency_index` is the same function the fold calls, so
    these cases exercise Cut 3a's arithmetic rather than a hand-typed number
    that could quietly disagree with it.
    """
    rows = list(nodes)
    return {
        "nodes": rows,
        "work_items": list(items),
        "dependency_index": tg.dependency_index(nodes=rows, ordering=list(ordering)),
    }


def anchored(label: str, node_id: str, reach: int) -> tuple[list, list]:
    """A node called ``label`` that ``reach`` other nodes depend on (D1)."""
    nodes = [{"node_id": node_id, "node_kind": "event", "label": label}]
    ordering = []
    for n in range(reach):
        nodes.append({"node_id": f"{node_id}-dep{n}", "node_kind": "event"})
        ordering.append((f"{node_id}-dep{n}", (node_id,)))
    return nodes, ordering


PERSON_ROSTER = {"version": 1, "type": "person", "entities": [
    {"name": "Katie", "slug": "katie"},
    {"name": "Nana", "slug": "nana"},
    {"name": "Ruth", "slug": "ruth"},
]}


class OpenBoundTests(unittest.TestCase):
    """R-Q1/R-Q2/R-Q3: the bound the graph is missing, in the domain's words."""

    def test_a_stay_with_no_end_asks_when_they_moved_out(self) -> None:
        nodes = [stay("node:mesa", "the Mesa house", best=year("1990") | {"best": "1990/.."})]
        nodes.extend(inside(f"node:m{n}", "node:mesa") for n in range(5))
        found = lo.landmark_opportunities(graph(nodes), {}, ())
        self.assertEqual(len(found), 1)
        row = found[0]
        self.assertEqual(row["domain"], "residences")
        self.assertEqual(row["kind"], "span_open_end")
        self.assertEqual(row["question"], "When did you move out of the Mesa house?")
        self.assertEqual(row["leverage"], BAR)
        self.assertEqual(len(row["resolves"]), 5)
        self.assertEqual(row["ladder_rung"], "span")

    def test_a_stay_with_no_start_asks_the_other_bound(self) -> None:
        nodes = [stay("node:mesa", "the Mesa house",
                      best={"best": "../1992", "earliest": None, "latest": "1992"})]
        nodes.extend(inside(f"node:m{n}", "node:mesa") for n in range(5))
        row = lo.landmark_opportunities(graph(nodes), {}, ())[0]
        self.assertEqual(row["kind"], "span_open_start")
        self.assertEqual(row["question"], "When did you move into the Mesa house?")

    def test_a_stay_with_no_interval_reuses_the_ladders_own_span_rung(self) -> None:
        """R-Q3: a rung exists and already names both bounds and the subject."""
        nodes = [stay("node:mesa", "the Mesa house")]
        nodes.extend(inside(f"node:m{n}", "node:mesa") for n in range(5))
        row = lo.landmark_opportunities(graph(nodes), {}, ())[0]
        self.assertEqual(row["kind"], "span_missing")
        self.assertEqual(row["question"],
                         li.EVENT_QUESTION_TEXTS[("residences", "span")]
                         .format(label="the Mesa house"))

    def test_a_dated_stay_owes_nothing(self) -> None:
        nodes = [stay("node:mesa", "the Mesa house",
                      best={"best": "1990/1992", "earliest": "1990", "latest": "1992"})]
        nodes.extend(inside(f"node:m{n}", "node:mesa") for n in range(5))
        self.assertEqual(lo.landmark_opportunities(graph(nodes), {}, ()), [])

    def test_a_stay_the_person_is_still_in_is_not_asked_to_end(self) -> None:
        """"When did you move out" is not a question about a house somebody
        still lives in; the fold's own `life_clip_end` says so."""
        nodes = [stay("node:now", "the house on Elm",
                      best={"best": "2019/..", "earliest": "2019", "latest": None})]
        nodes[0]["life_clip_end"] = "present"
        nodes.extend(inside(f"node:m{n}", "node:now") for n in range(5))
        self.assertEqual(lo.landmark_opportunities(graph(nodes), {}, ()), [])

    def test_each_span_domain_asks_in_its_own_verb(self) -> None:
        for event_kind, domain in lo.DOMAIN_BY_EPISODE_KIND.items():
            with self.subTest(domain=domain):
                nodes = [stay("node:x", "Northrop", event_kind=event_kind,
                              best={"best": "1990/..", "earliest": "1990",
                                    "latest": None})]
                nodes.extend(inside(f"node:m{n}", "node:x") for n in range(5))
                row = lo.landmark_opportunities(graph(nodes), {}, ())[0]
                self.assertEqual(row["domain"], domain)
                self.assertEqual(row["question"],
                                 lo.SPAN_END_TEXTS[domain].format(label="Northrop"))


class BirthOriginTests(unittest.TestCase):
    """R-Q4: the coordinate system. Nothing else in the graph reaches as far."""

    def test_no_birthday_is_an_opportunity_under_the_origin_anchor(self) -> None:
        nodes, ordering = anchored("", tg.origin_anchor("self"), BAR)
        row = lo.landmark_opportunities(graph(nodes, ordering=ordering), {}, ())[0]
        self.assertEqual(row["domain"], "birth")
        self.assertEqual(row["kind"], "birth_origin")
        self.assertEqual(row["question"], li.RUNG_TEXTS[("birth", "year")])
        self.assertEqual(row["subject"], tg.origin_anchor("self"))
        self.assertEqual(row["leverage"], BAR + 1)

    def test_a_filed_birthday_owes_nothing(self) -> None:
        nodes, ordering = anchored("", tg.origin_anchor("self"), BAR)
        state = {"birth": [{"domain": "birth", "year": "1970", "month": "03",
                            "day": "02"}]}
        self.assertEqual(
            lo.landmark_opportunities(graph(nodes, ordering=ordering), state, ()), [])


class AmbiguousEpisodeTests(unittest.TestCase):
    """R-Q6: the fold already wrote the sentence; this reuses it."""

    def item(self, kind: str, prompt: str) -> dict:
        return {"work_item_id": "work:abc", "kind": kind, "state": "open",
                "allowed_surfaces": ["timeline", "whisper", "daily_question"],
                "node_ref": "node:zoo", "subject_ref": "the zoo trip",
                "requested_field": "date", "prompt_intent": prompt,
                "resolves": [f"node:d{n}" for n in range(BAR)], "leverage": BAR + 1}

    def test_the_items_own_sentence_is_the_question(self) -> None:
        prompt = "Which time in Phoenix was that — 1988-1990 or 1996-1999?"
        found = lo.landmark_opportunities(
            graph(items=[self.item("place_ambiguous", prompt)]), {}, ())
        self.assertEqual(len(found), 1)
        row = found[0]
        self.assertEqual(row["domain"], "residences")
        self.assertEqual(row["kind"], "ambiguous_episode")
        self.assertEqual(row["question"], prompt)
        self.assertIsNone(row["ladder_rung"])
        self.assertEqual(row["leverage"], BAR + 1)
        self.assertEqual(row["work_item_id"], "work:abc")

    def test_an_organization_ambiguity_finds_the_domain_it_names(self) -> None:
        prompt = "Which time at Roosevelt High was that — 1984-1986 or 1988-1990?"
        state = {"schools": [{"domain": "schools", "label": "Roosevelt High"}]}
        row = lo.landmark_opportunities(
            graph(items=[self.item("tenure_ambiguous", prompt)]), state, ())[0]
        self.assertEqual(row["domain"], "schools")

    def test_an_organization_ambiguity_falls_back_to_work(self) -> None:
        prompt = "Which time at the Boatworks was that — 1991-1992 or 1997-1999?"
        row = lo.landmark_opportunities(
            graph(items=[self.item("tenure_ambiguous", prompt)]), {}, ())[0]
        self.assertEqual(row["domain"], "work")


class SufficiencyTests(unittest.TestCase):
    """R2: a domain leaves the privileged surface on VALUE, not on completion."""

    def low_value(self) -> dict:
        nodes = [stay("node:mesa", "the Mesa house",
                      best={"best": "1990/..", "earliest": "1990", "latest": None})]
        nodes.extend(inside(f"node:m{n}", "node:mesa") for n in range(2))
        return graph(nodes)

    def test_a_ladder_whose_only_gaps_are_low_value_offers_nothing(self) -> None:
        found, verdicts = lo.surface(self.low_value(), {}, ())
        self.assertEqual(found, [])
        self.assertTrue(verdicts["residences"]["sufficient"])
        self.assertEqual(verdicts["residences"]["reason"], lo.REASON_BELOW_THRESHOLD)
        self.assertEqual(verdicts["residences"]["best_leverage"], 3)

    def test_the_same_gap_above_the_bar_is_offered(self) -> None:
        """The bar is a bar, not a category: one number decides both ways."""
        found, verdicts = lo.surface(self.low_value(), {}, (), threshold=3)
        self.assertEqual(len(found), 1)
        self.assertFalse(verdicts["residences"]["sufficient"])
        self.assertEqual(verdicts["residences"]["reason"], lo.REASON_OPEN)

    def test_every_domain_gets_a_verdict_and_a_reason(self) -> None:
        verdicts = lo.landmark_sufficiency(graph(), {}, ())
        self.assertEqual(sorted(verdicts),
                         sorted(row["domain"] for row in li.load_questions()))
        for domain, row in verdicts.items():
            with self.subTest(domain=domain):
                self.assertIn(row["reason"], lo.SUFFICIENCY_REASONS)
                self.assertIsInstance(row["sufficient"], bool)
                self.assertGreaterEqual(row["best_leverage"], 0)

    def test_a_sufficient_domain_publishes_nothing_and_an_open_one_publishes(self) -> None:
        """The invariant the two answers are computed together to keep."""
        nodes = [stay("node:mesa", "the Mesa house",
                      best={"best": "1990/..", "earliest": "1990", "latest": None})]
        nodes.extend(inside(f"node:m{n}", "node:mesa") for n in range(5))
        found, verdicts = lo.surface(graph(nodes), {}, ())
        offered = {row["domain"] for row in found}
        for domain, row in verdicts.items():
            with self.subTest(domain=domain):
                self.assertEqual(row["sufficient"], domain not in offered)


class RelationshipTests(unittest.TestCase):
    """R-Q4: the person, by name, and the event the domain actually dates."""

    def katie(self, entry: object = None, reach: int = BAR):
        nodes, ordering = anchored("Katie", "node:katie", reach)
        state = {"partnerships": [entry if entry is not None
                                  else {"domain": "partnerships", "label": "katie",
                                        "happened": True}]}
        return graph(nodes, ordering=ordering), state

    def test_an_unresolved_relationship_asks_when_they_first_met(self) -> None:
        projection, state = self.katie()
        found = lo.landmark_opportunities(projection, state, PERSON_ROSTER)
        self.assertEqual(len(found), 1)
        row = found[0]
        self.assertEqual(row["domain"], "partnerships")
        self.assertEqual(row["kind"], "relationship_anchor")
        self.assertEqual(row["question"], "When did you and Katie first meet?")
        self.assertEqual(row["event"], "first_met")
        self.assertEqual(row["ladder_rung"], "year")
        self.assertEqual(row["subject"], "node:katie")
        self.assertEqual(row["leverage"], BAR + 1)

    def test_the_name_is_the_rosters(self) -> None:
        """The entry says "katie"; everyone else says Katie."""
        projection, state = self.katie()
        without = lo.landmark_opportunities(projection, state, ())[0]
        self.assertEqual(without["question"], "When did you and katie first meet?")

    def test_a_dated_relationship_is_not_an_opportunity(self) -> None:
        projection, state = self.katie(
            {"domain": "partnerships", "label": "katie", "happened": True,
             "date": {"best": "1998", "earliest": "1998", "latest": "1998",
                      "granularity": "year", "basis": "stated",
                      "confidence": "certain"}})
        self.assertEqual(lo.landmark_opportunities(projection, state, PERSON_ROSTER), [])

    def test_a_question_never_asks_about_nobody(self) -> None:
        """An entry with no name yet has no anchor and no sentence: that rung
        is the ladder's business, and it is what keeps "When did this part
        begin?" unrepresentable here."""
        projection, _ = self.katie()
        state = {"partnerships": [{"domain": "partnerships", "happened": True}]}
        for row in lo.candidates(projection, state, PERSON_ROSTER):
            with self.subTest(row=row["id"]):
                self.assertTrue(row["label"] or row["domain"] == "birth")


class LossesAreOfferOnlyTests(unittest.TestCase):
    """§4.6: losses stay offer-only. Sensitivity never moves the gain."""

    def nana(self):
        nodes, ordering = anchored("Nana", "node:nana", BAR)
        state = {"losses": [{"domain": "losses", "label": "nana", "happened": True}]}
        return graph(nodes, ordering=ordering), state

    def test_losses_never_produce_an_unprompted_opportunity(self) -> None:
        projection, state = self.nana()
        found, verdicts = lo.surface(projection, state, PERSON_ROSTER)
        self.assertEqual([row for row in found if row["domain"] == "losses"], [])
        self.assertTrue(verdicts["losses"]["sufficient"])
        self.assertEqual(verdicts["losses"]["reason"], lo.REASON_OFFER_ONLY)

    def test_the_leverage_is_still_measured_and_still_published(self) -> None:
        """Sensitivity changes whether it may be surfaced, never what it is
        worth — so the withheld number is on the record."""
        projection, state = self.nana()
        verdicts = lo.landmark_sufficiency(projection, state, PERSON_ROSTER)
        self.assertEqual(verdicts["losses"]["best_leverage"], BAR + 1)

    def test_a_raised_subject_is_offered_and_says_it_is_an_offer(self) -> None:
        projection, state = self.nana()
        found, verdicts = lo.surface(projection, state, PERSON_ROSTER,
                                     raised=("losses",))
        row = next(r for r in found if r["domain"] == "losses")
        self.assertEqual(row["question"], "Roughly when did you lose Nana?")
        self.assertEqual(row["sensitivity"], lo.SENSITIVITY_OFFER_ONLY)
        self.assertFalse(verdicts["losses"]["sufficient"])

    def test_only_the_sensitive_domain_carries_the_flag(self) -> None:
        nodes, ordering = anchored("Katie", "node:katie", BAR)
        state = {"partnerships": [{"domain": "partnerships", "label": "katie",
                                   "happened": True}]}
        row = lo.landmark_opportunities(graph(nodes, ordering=ordering), state,
                                        PERSON_ROSTER)[0]
        self.assertEqual(row["sensitivity"], lo.SENSITIVITY_ORDINARY)


class ClosedListTests(unittest.TestCase):
    """A finishable domain keeps its finishable semantics — and only those."""

    def ruth(self, *, finished: bool):
        nodes, ordering = anchored("Ruth", "node:ruth", BAR)
        entry = {"domain": "family", "label": "ruth", "relation": "sibling"}
        if finished:
            entry["chain_complete"] = True
        return graph(nodes, ordering=ordering), {"family": [entry]}

    def test_an_open_list_still_owes_the_rung(self) -> None:
        projection, state = self.ruth(finished=False)
        row = lo.landmark_opportunities(projection, state, PERSON_ROSTER)[0]
        self.assertEqual(row["question"], "What year was Ruth born?")

    def test_a_declared_finished_list_is_sufficient_with_rungs_unfilled(self) -> None:
        projection, state = self.ruth(finished=True)
        found, verdicts = lo.surface(projection, state, PERSON_ROSTER)
        self.assertEqual([row for row in found if row["domain"] == "family"], [])
        self.assertTrue(verdicts["family"]["sufficient"])
        self.assertEqual(verdicts["family"]["reason"], lo.REASON_LIST_FINISHED)
        self.assertEqual(verdicts["family"]["best_leverage"], BAR + 1)

    def test_a_none_terminal_finishes_the_domain(self) -> None:
        """"I never served" is a finished answer, not a partial one."""
        verdicts = lo.landmark_sufficiency(
            graph(), {"military": [{"domain": "military", "none": True}]}, ())
        self.assertTrue(verdicts["military"]["sufficient"])

    def test_closing_a_list_never_silences_the_graph(self) -> None:
        """Declared closure closes a LIST, not a graph: "that's all the
        houses" is not an answer to "when did you move out of the Mesa
        house?" — audit F7's newly high-value anchor."""
        nodes = [stay("node:mesa", "the Mesa house",
                      best={"best": "1990/..", "earliest": "1990", "latest": None})]
        nodes.extend(inside(f"node:m{n}", "node:mesa") for n in range(5))
        state = {"residences": [{"domain": "residences", "label": "the Mesa house",
                                 "city": "the Mesa house",
                                 "address": "1220 E Palo Verde",
                                 "chain_complete": True,
                                 "span": {"start": year("1990")}}]}
        found, verdicts = lo.surface(graph(nodes), state, ())
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["question"],
                         "When did you move out of the Mesa house?")
        self.assertFalse(verdicts["residences"]["sufficient"])
        self.assertEqual(verdicts["residences"]["reason"], lo.REASON_OPEN)


class IdentityTests(unittest.TestCase):
    """An answered question never comes back, and a rebuild asks under the
    same id — which is what "never nagged again" is made of."""

    def test_the_id_is_a_function_of_the_gap_and_nothing_else(self) -> None:
        first = lo.opportunity_id(domain="residences", kind="span_open_end",
                                  subject="node:mesa")
        second = lo.opportunity_id(domain="residences", kind="span_open_end",
                                   subject="node:mesa")
        self.assertEqual(first, second)
        self.assertTrue(first.startswith(lo.OPPORTUNITY_ID_PREFIX + ":"))
        self.assertNotEqual(first, lo.opportunity_id(
            domain="residences", kind="span_open_start", subject="node:mesa"))

    def test_the_wording_and_the_leverage_do_not_move_the_id(self) -> None:
        nodes = [stay("node:mesa", "the Mesa house",
                      best={"best": "1990/..", "earliest": "1990", "latest": None})]
        few = list(nodes) + [inside(f"node:m{n}", "node:mesa") for n in range(5)]
        many = list(nodes) + [inside(f"node:m{n}", "node:mesa") for n in range(9)]
        first = lo.landmark_opportunities(graph(few), {}, ())[0]
        second = lo.landmark_opportunities(graph(many), {}, ())[0]
        self.assertNotEqual(first["leverage"], second["leverage"])
        self.assertEqual(first["id"], second["id"])

    def test_a_filed_answer_removes_the_opportunity_rather_than_renaming_it(self) -> None:
        nodes = [stay("node:mesa", "the Mesa house",
                      best={"best": "1990/..", "earliest": "1990", "latest": None})]
        nodes.extend(inside(f"node:m{n}", "node:mesa") for n in range(5))
        before = lo.landmark_opportunities(graph(nodes), {}, ())
        self.assertEqual(len(before), 1)
        answered = [dict(row) for row in nodes]
        answered[0]["best_temporal_value"] = {"best": "1990/1992",
                                              "earliest": "1990", "latest": "1992"}
        self.assertEqual(lo.landmark_opportunities(graph(answered), {}, ()), [])


class TheThresholdIsOneDial(unittest.TestCase):
    """§4.6: one base quantity, one bar, three hosts."""

    def test_the_default_threshold_is_the_queues_own_dial(self) -> None:
        self.assertEqual(lo.default_threshold(),
                         qp.DEFAULT_LANE_POLICY[lo.THRESHOLD_DIAL])
        self.assertEqual(lo.default_threshold(), BAR)

    def test_the_dial_has_exactly_one_definition(self) -> None:
        """Read, never copied: this module names the dial and asks for it."""
        source = (SYSTEM / "landmark_opportunities.py").read_text(encoding="utf-8")
        self.assertIn("from question_planner import DEFAULT_LANE_POLICY", source)
        self.assertNotIn("DEFAULT_LANE_POLICY = ", source)
        self.assertNotIn(f'"{lo.THRESHOLD_DIAL}":', source)

    def test_the_leverage_is_cut_3as_arithmetic_and_not_a_second_metric(self) -> None:
        index = {"node:mesa": ["node:a", "node:b"]}
        self.assertEqual(lo.gain_for("node:mesa", index),
                         tg.item_gain({"node_ref": "node:mesa"}, index))

    def test_a_bad_threshold_is_refused_rather_than_guessed(self) -> None:
        with self.assertRaises(lo.LandmarkOpportunityError) as caught:
            lo.landmark_sufficiency(graph(), {}, (), threshold="soon")
        self.assertEqual(caught.exception.code, "threshold_not_a_number")


# --------------------------------------------------------------------------
# The whole path — a vault, the fold, the publication, the rebuild
# --------------------------------------------------------------------------


class MesaVault(unittest.TestCase):
    """A COMPLETE residence ladder (the person even said the list was
    finished) whose one stay never got an end, with five things inside it.

    This is audit F7's own sentence as a fixture: the legacy surface would
    have said "all filled in".
    """

    MOMENTS = 5

    def setUp(self) -> None:
        self.vault = Path(tempfile.mkdtemp(prefix="lifehug-landmark-opps-"))
        self.addCleanup(shutil.rmtree, self.vault, ignore_errors=True)
        (self.vault / "state").mkdir(parents=True, exist_ok=True)
        (self.vault / "sources").mkdir(parents=True, exist_ok=True)
        rosters = self.vault / "state" / "entity_rosters"
        rosters.mkdir(parents=True, exist_ok=True)
        self.roster = {"version": 1, "type": "place", "entities": [
            {"name": "the Mesa house", "slug": "the-mesa-house", "aliases": ["Mesa"]},
        ]}
        (rosters / "place.json").write_text(json.dumps(self.roster), encoding="utf-8")

        lp.file_landmark_record(
            self.vault, "birth",
            {"domain": "birth", "label": "birth",
             "date": {"best": "1970-03-02", "earliest": "1970-03-02",
                      "latest": "1970-03-02", "granularity": "day",
                      "basis": "stated", "confidence": "certain"}},
            ordinal=1, now=NOW,
        )
        lp.file_landmark_record(
            self.vault, "residences",
            {"domain": "residences", "label": "the Mesa house",
             "city": "the Mesa house", "address": "1220 E Palo Verde",
             "chain_complete": True, "span": {"start": year("1990")}},
            ordinal=2, now=NOW,
        )
        for n in range(self.MOMENTS):
            source = f"classification:answers-m{n}#m{n}"
            claim = tc.validate_temporal_claim({
                "source_kind": "conversation",
                "source_ref": {"source_id": source, "revision": revision(source)},
                "evidence": [{"quote": f"a thing in the Mesa house, {n}"}],
                "extractor_version": "classifier:1",
                "created_at": "2026-08-30T00:00:00Z",
                "basis": "explicit", "confidence": 0.9, "status": "active",
                "claim_type": "occurrence", "subject_mention": "I",
                "event_mention": f"The Mesa thing {n}", "event_kind": "moment",
                "event_ref": tp.derive_node_id(node_kind="event", event_kind="moment",
                                               subject_refs=["I"], discriminator=source),
            })
            ts.write_receipt(self.vault, {
                "source_ref": claim["source_ref"],
                "extractor_version": "classifier:1",
                "created_at": "2026-08-30T00:00:00Z", "claims": [claim],
            })
        ts.rebuild_active_index(self.vault)
        eb.bind_episodes(self.vault, apply=True, now=NOW,
                         containment_authority="applied")
        self.result = self.fold()

    def fold(self, generation: int = 1):
        return tt.derive_calculated_timeline(
            ts.fold_active_index(self.vault),
            episode_records=ef.load_episode_records(self.vault),
            landmark_entries=lp.load_landmark_sources(self.vault),
            roster_snapshot=self.roster,
            projection_generation=generation, now=NOW,
        )

    def publish(self):
        return pub.publish(self.vault, roster_snapshot=self.roster, now=NOW)


class TheFoldPublishesTheOpportunity(MesaVault):
    def test_the_legacy_ladder_calls_this_domain_complete(self) -> None:
        """The premise: the checklist has nothing left to say."""
        state = lp.project_landmark_entries(
            ts.fold_active_index(self.vault),
            sources=lp.load_landmark_sources(self.vault))["domains"]
        row = li.domain_row("residences")
        self.assertEqual(li.status_for_domain(state["residences"], row), "complete")
        self.assertIsNone(li.next_rung(state["residences"], row))

    def test_the_graph_still_owes_one_question_and_names_the_house(self) -> None:
        found = list(self.result.landmark_opportunities)
        self.assertEqual(len(found), 1)
        row = found[0]
        self.assertEqual(row["domain"], "residences")
        self.assertEqual(row["kind"], "span_open_end")
        self.assertEqual(row["question"], "When did you move out of the Mesa house?")
        self.assertEqual(row["leverage"], self.MOMENTS + 1)
        self.assertEqual(len(row["resolves"]), self.MOMENTS)

    def test_the_leverage_is_the_same_number_the_needs_placing_row_carries(self) -> None:
        """§4.6's one base quantity, proved on one generation rather than
        asserted: the opportunity and the Timeline row share an anchor."""
        row = self.result.landmark_opportunities[0]
        self.assertEqual(sorted(self.result.dependency_index[row["subject"]]),
                         row["resolves"])

    def test_every_id_it_names_is_a_node_the_projection_holds(self) -> None:
        known = {node["node_id"] for node in self.result.nodes}
        for row in self.result.landmark_opportunities:
            for node_id in row["resolves"]:
                with self.subTest(node=node_id):
                    self.assertIn(node_id, known)

    def test_the_other_eight_domains_collapse(self) -> None:
        verdicts = self.result.landmark_sufficiency
        open_domains = [d for d, row in verdicts.items() if not row["sufficient"]]
        self.assertEqual(open_domains, ["residences"])
        self.assertEqual(verdicts["losses"]["reason"], lo.REASON_OFFER_ONLY)
        self.assertEqual(verdicts["birth"]["reason"], lo.REASON_NOTHING_REMAINING)


class TheOpportunitySurvivesARebuild(MesaVault):
    def test_two_folds_of_one_substrate_ask_under_the_same_id(self) -> None:
        first = [row["id"] for row in self.result.landmark_opportunities]
        second = [row["id"] for row in self.fold(generation=2).landmark_opportunities]
        self.assertEqual(first, second)
        self.assertTrue(first)

    def test_both_keys_ride_the_rebuild_signature(self) -> None:
        signature = tt.structural_signature(self.result)
        self.assertIn("landmark_opportunities", signature)
        self.assertIn("landmark_sufficiency", signature)
        self.assertEqual(signature, tt.structural_signature(self.fold()))

    def test_a_full_rebuild_reproduces_the_published_opportunity(self) -> None:
        self.publish()
        before = pub.rebuild_signature(pub.read_projection(self.vault))
        (self.vault / "state" / "temporal" / "active-index.json").unlink(missing_ok=True)
        report = pub.verify(self.vault, roster_snapshot=self.roster, now=NOW)
        self.assertTrue(report["identical"], report.get("differences"))
        after = pub.rebuild_signature(pub.read_projection(self.vault))
        self.assertEqual(after["landmark_opportunities"],
                         before["landmark_opportunities"])
        self.assertEqual(after["landmark_sufficiency"], before["landmark_sufficiency"])

    def test_answering_it_retires_it_and_mints_nothing_in_its_place(self) -> None:
        """The question does not come back under a new id; it stops existing."""
        was = self.result.landmark_opportunities[0]["id"]
        lp.file_landmark_record(
            self.vault, "residences",
            {"domain": "residences", "label": "the Mesa house",
             "city": "the Mesa house", "address": "1220 E Palo Verde",
             "span": {"start": year("1990"), "end": year("1992")}},
            ordinal=3, now=NOW,
        )
        ts.rebuild_active_index(self.vault)
        eb.bind_episodes(self.vault, apply=True, now=NOW,
                         containment_authority="applied")
        after = self.fold(generation=2)
        self.assertNotIn(was, [row["id"] for row in after.landmark_opportunities])
        self.assertEqual(
            [row for row in after.landmark_opportunities
             if row["domain"] == "residences" and row["kind"].startswith("span")],
            [],
        )


class ThePageIsServedTheOpportunity(MesaVault):
    def test_both_keys_are_served_by_calculated_view(self) -> None:
        self.publish()
        view = pub.calculated_view(self.vault)
        self.assertIn("landmark_opportunities", pub.view_block_keys())
        self.assertIn("landmark_sufficiency", pub.view_block_keys())
        self.assertEqual(len(view["landmark_opportunities"]), 1)
        self.assertEqual(view["landmark_opportunities"][0]["question"],
                         "When did you move out of the Mesa house?")
        self.assertFalse(view["landmark_sufficiency"]["residences"]["sufficient"])

    def test_every_published_key_is_still_served_or_excused(self) -> None:
        """The O-E1b guard's own rule, on the two new keys."""
        self.publish()
        payload = pub.read_projection(self.vault)
        self.assertIn("landmark_opportunities", payload)
        self.assertIn("landmark_sufficiency", payload)
        self.assertEqual(set(payload) - set(pub.published_block_keys()), set())

    def test_a_projection_published_before_this_cut_reads_as_no_measurement(self) -> None:
        """Tolerant by construction, like every additive key before it."""
        self.publish()
        path = pub.projection_path(self.vault)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.pop("landmark_opportunities", None)
        payload.pop("landmark_sufficiency", None)
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        view = pub.calculated_view(self.vault)
        self.assertEqual(view["landmark_opportunities"], ())
        self.assertEqual(view["landmark_sufficiency"], {})

    def test_an_empty_vault_publishes_no_opportunities_and_no_surface(self) -> None:
        vault = Path(tempfile.mkdtemp(prefix="lifehug-landmark-opps-empty-"))
        self.addCleanup(shutil.rmtree, vault, ignore_errors=True)
        pub.publish(vault, now=NOW)
        view = pub.calculated_view(vault)
        self.assertEqual(view["landmark_opportunities"], ())
        self.assertTrue(all(row["sufficient"]
                            for row in view["landmark_sufficiency"].values()))


class TheModuleIsShipped(unittest.TestCase):
    def test_the_new_module_is_a_framework_file(self) -> None:
        version = json.loads((SYSTEM / "version.json").read_text(encoding="utf-8"))
        self.assertIn("system/landmark_opportunities.py", version["framework_files"])

    def test_the_adr_exists_and_cites_the_decision_record(self) -> None:
        adr = ROOT / "docs" / "adr" / "0032-landmark-sufficiency.md"
        text = adr.read_text(encoding="utf-8")
        self.assertIn("2026-09-03-timeline-unification", text)
        for heading in ("## Context", "## Decision", "## Consequences"):
            self.assertIn(heading, text)

    def test_the_legacy_landmark_rows_are_untouched(self) -> None:
        """Cut 7b retires them; 5a does not."""
        import timeline as tl  # noqa: PLC0415

        self.assertTrue(callable(tl.landmark_rows_for))
        self.assertTrue(callable(li.landmark_rows))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
