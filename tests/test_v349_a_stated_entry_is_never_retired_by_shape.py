"""v349 — a stated entry is never retired by shape.

WHERE IT WAS SEEN. Staging, 2026-09-24 19:18:10 UTC, hosted package pinned to
v347 (`48ddabdf`). The owner answered a `residences` landmark card. The hosted
`landmark-record` job filed one source —
`sources/landmarks/entry-5d5e93f00610650276f2f86a.md`, whose whole body is::

    {"address":"701 North Williams","domain":"residences","label":"701 North Williams"}

— and commit `398b85df` "Landmark: residences (Lifehug Cloud)" retired ALL 30
existing residence entries with it. `state/landmarks.json` residences went
30 -> 1; 29 `sources/corrections/temporal-*.md` were filed, each *"Supersede N
temporal claim(s) … superseded by a later residences answer
(landmarks_interaction.entry_superseded_by)"*, `correction_scope:
landmarks/residences`, 89 claims in all. The published projection went
generation 152 -> 153: nodes 1190 -> 1161, unplaced 35 -> 117, open work items
45 -> 154. Every moment those stays had PLACED by containment — "Attended
Longfellow Elementary", "Fell on a nail", "Marriage to Katie", "Job at Boeing",
"Graduation from MIT", the whole childhood-moves sequence — fell to unplaced
and minted a card.

THE DIAGNOSIS, and it is NOT the regression anybody expected. Nothing in
v343-v347 broke. Running `unreadable_fields` over the 30 real entries and the
residences row at v278, v342, v343, v345, v346, v347 and v348 returns the
IDENTICAL answer every time — `('link', 'nickname', 'ongoing', 'place_ref')`
for 23 of them, `('link', 'ongoing', 'place_ref')` for 5, and those four plus
`note` for 2 — and `entry_superseded_by` returns True for 30 of 30 at every one
of those releases. The bomb was armed on **2026-09-15**, when the owner's
place-enriched residences were filed carrying exactly the fields the writer
emits, and it was armed by **v278** (`8030d26`, "E-L2c — ladder fields,
organization roster, chain coverage/gaps/closure, the one chain chooser"):
before that commit `validate_landmark` on a rich residence emitted
`{address, city, domain, label, span}` and `unreadable_fields` returned `()`;
after it the same value emits `{…, link, nickname, ongoing, place_ref}` and
`unreadable_fields` returns four. E-L2c added five fields to the writer and
told `NON_RUNG_FIELDS` about none of them. v214's rule 3 — "a clean record
retires the collapsed aggregate" — had been reading those five as the signature
of a machine that had many entries and filed one for sixty-four releases.

The trigger on 19:18 was simply the first LEAN residences record. Rule 3 needs
the NEW record to carry no unreadable field, and every residences record filed
on 09-15 was rich. The bare answer was the first one that was not. `work` and
`partnerships` answered the same evening and were untouched for the only reason
that matters here: no `work` or `partnerships` entry in that vault carried a
descriptor, so `unreadable_fields` was `()` on both sides and rule 3 could not
fire at all.

WHY THE GUARD DID NOT CATCH IT. `tests/test_landmarks.py`'s ladder-consistency
guard (leg 4) builds its probe from a hand-written `everything` dict —
`domain, label, place, subject, birth_order, date, span, chain_complete` plus
the ladder's rungs — and E-L2c never joined it. So the guard never asked
`unreadable_fields` about `link`, `nickname`, `ongoing`, `place_ref` or `note`,
its pinned `UNREAD` set stayed at its six `(domain, field)` pairs, and CI was
green the whole time.

THE RULES (`landmarks_interaction.A_STATED_ENTRY_IS_NEVER_RETIRED_BY_SHAPE`):

1. Rule 3 may retire only a DEMONSTRABLE machine-collapsed aggregate
   (`collapsed_aggregate_fields`): a field the domain's own writer never emits,
   or a `span` the domain has no rung for whose bounds straddle a stretch —
   v214's live instance, the four children as one row. The readable set is
   DERIVED from the writer (`writer_stored_fields`, which runs
   `validate_landmark` over `_writer_probe_value`, itself built from
   `_TEXT_CAPS` / `WRITER_DESCRIPTOR_FIELDS` / the ladder) so it cannot drift
   again. And an entry with a promoted source of its own is never retired by
   shape — with one exemption that is load-bearing and was SEEN failing before
   it was written: a STRADDLING SPAN is demonstrable whoever filed it. Read
   bluntly, the provenance clause retires rule 3 itself, because since v225
   every entry in a drawn store came from a `sources/landmarks/entry-*.md` and
   v214's own four-children row had one too
   (`collapsed_by_a_straddling_span`).
2. A supersession that would retire MORE THAN ONE existing entry from a single
   substantive record is refused out loud, with a finding naming the count
   (`supersession_findings`, `SUPERSESSION_FAN_OUT_LINT`). One answer is one
   entry. A `none` is exempt: retiring the whole domain is what it means.
3. The regression itself is fixed — the five descriptors are declared in
   `WRITER_DESCRIPTOR_FIELDS`, `NON_RUNG_FIELDS` reads them, and the writer is
   held to the same declaration so an undeclared field cannot reach the store.
4. The vault repair is a package verb: `landmark-reinstate --domain <d> --since
   <ts> --apply` files ONE `retract` correction scoped to
   `temporal_store.CORRECTION_CORRECTION_SCOPE` naming the supersessions that
   stop standing (`landmark_projection.reinstate_domain`). The superseded
   corrections stay on disk; the claims go active again; the ENTRIES come back
   because `state/landmarks.json` is a drawing and its sources were never
   touched.

MEASURED on a copy of the owner's staging vault (`/private/tmp/lifehug-rig`,
head `ade14e675`, read-only original): residences drawn 3 -> 33 (the 30 plus
the three later answers `701 North Williams`, `dad's house`, `Fiegers' house`,
all kept), residence stays carrying a usable interval 0 -> 30, containment
placements (`participation_span_applied`) 31 -> 61, unplaced 51 -> 32, open work
items 76 -> 48, nodes 1203 -> 1233, one file written under
`sources/corrections/`, and a second `--apply` reporting nothing to do.

Synthetic data only; NEVER references ~/Workspace/dave.
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import landmark_projection as lp  # noqa: E402
import landmarks_interaction as li  # noqa: E402
import temporal_store as ts  # noqa: E402
import timeline  # noqa: E402

# --------------------------------------------------------------------------
# The shapes the incident actually had
# --------------------------------------------------------------------------
#
# Synthetic VALUES, the real field SHAPES: every key the owner's thirty
# residence entries carried, in the same combinations and the same counts —
# 23 with a nickname, 5 without one, 2 with a trailing note — because the
# defect was entirely a property of which KEYS were present.

#: The bare record the hosted job filed, verbatim apart from nothing.
BARE_RECORD = {
    "address": "701 North Williams",
    "domain": "residences",
    "label": "701 North Williams",
}


def _bound(best: str, *, granularity: str = "month") -> dict:
    return {"best": best, "earliest": best, "latest": best,
            "granularity": granularity, "confidence": "certain",
            "basis": "stated", "anchors": [], "provenance": []}


def residence(label: str, *, start: str, end: str | None,
              nickname: bool = True, note: str | None = None) -> dict:
    """One residence entry in the exact shape the owner's vault held.

    `address`, `city`, `domain`, `label`, `link`, `ongoing`, `place_ref` and
    `span` on every one of them; `nickname` on 25 of 30; `note` on 2. Four of
    those eight — `link`, `nickname`, `ongoing`, `place_ref` — are what
    `validate_landmark` emits and what no residences rung reads, which is the
    whole defect.
    """
    span = {"start": _bound(start)}
    if end is not None:
        span["end"] = _bound(end)
    entry = {
        "address": f"{label} Street, Cedarport, ZZ",
        "city": "Cedarport, Zetaland",
        "domain": "residences",
        "label": label,
        "link": f"https://maps.example.invalid/?q={label.replace(' ', '+')}",
        "ongoing": end is None,
        "place_ref": f"place/residence-{abs(hash(label)) % (10 ** 20):020d}",
        "span": span,
    }
    if nickname:
        entry["nickname"] = label
    if note is not None:
        entry["note"] = note
    return entry


def thirty_residences() -> list[dict]:
    """The thirty, with the real distribution of optional keys."""
    entries = []
    for index in range(30):
        label = f"Stay {index:02d}"
        entries.append(residence(
            label,
            start=f"{1962 + index}-06",
            end=None if index == 29 else f"{1963 + index}-06",
            nickname=index not in (3, 9, 14, 21, 27),
            note="the one with the green door" if index in (5, 18) else None,
        ))
    return entries


ROW = li.domain_row("residences")
CHILDREN_ROW = li.domain_row("children")

#: v214's own instance, and the only shape rule 3 was ever built for: four
#: children as ONE row whose span runs from the first birthday to the last.
COLLAPSED_CHILDREN = {
    "domain": "children",
    "who": "the kids",
    "label": "the kids",
    "span": {"start": _bound("1979", granularity="year"),
             "end": _bound("1986", granularity="year")},
}
ONE_CHILD = {"domain": "children", "who": "Jackie", "label": "Jackie",
             "year": "1979"}


# --------------------------------------------------------------------------
# Rule 3, narrowed: the incident, as a unit
# --------------------------------------------------------------------------


class TheThirtyStayTest(unittest.TestCase):
    """The reproduction, and the fix, on the real shapes."""

    def setUp(self) -> None:
        self.entries = thirty_residences()

    def test_the_writer_emits_every_field_the_thirty_carry(self) -> None:
        """The premise. If the writer did not emit these, they would not be
        the writer's problem — and rule 3 would have been right about them."""
        stored = li.writer_stored_fields(ROW)
        for field in ("address", "city", "label", "link", "nickname",
                      "ongoing", "place_ref", "span", "note"):
            with self.subTest(field=field):
                self.assertIn(field, stored)

    def test_no_stated_residence_reads_as_a_collapsed_aggregate(self) -> None:
        for entry in self.entries:
            with self.subTest(label=entry["label"]):
                self.assertEqual(li.collapsed_aggregate_fields(entry, ROW), ())

    def test_the_bare_record_retires_none_of_the_thirty(self) -> None:
        retired = [entry for entry in self.entries
                   if li.entry_superseded_by(entry, BARE_RECORD, ROW)]
        self.assertEqual(retired, [], "the whole incident, as one assertion")

    def test_supersession_reason_is_none_for_every_one_of_them(self) -> None:
        for entry in self.entries:
            with self.subTest(label=entry["label"]):
                self.assertIsNone(
                    li.supersession_reason(entry, BARE_RECORD, ROW))

    def test_the_five_descriptors_are_no_longer_unreadable(self) -> None:
        """The regression fix itself, stated as the count that used to be 4."""
        for entry in self.entries:
            with self.subTest(label=entry["label"]):
                self.assertEqual(li.unreadable_fields(entry, ROW), ())

    def test_removing_the_declaration_reproduces_the_wipe(self) -> None:
        """Seen failing first: with `WRITER_DESCRIPTOR_FIELDS` out of
        `NON_RUNG_FIELDS`, the fields go unreadable again — and rule 3's OWN
        narrowing is what still saves the entries. Two independent guards."""
        without = li.NON_RUNG_FIELDS - li.WRITER_DESCRIPTOR_FIELDS
        with mock.patch.object(li, "NON_RUNG_FIELDS", without):
            unread = li.unreadable_fields(self.entries[0], ROW)
            self.assertEqual(set(unread),
                             {"link", "nickname", "ongoing", "place_ref"})
            # …and the second guard holds anyway, because every one of those
            # four is a field the writer emits.
            self.assertEqual(
                li.collapsed_aggregate_fields(self.entries[0], ROW), ())
            self.assertFalse(
                li.entry_superseded_by(self.entries[0], BARE_RECORD, ROW))


class TheRulesStillSpeakingTest(unittest.TestCase):
    """v349 narrows rule 3 and touches neither of the spoken rules."""

    def test_a_none_still_retires_the_whole_domain(self) -> None:
        for entry in thirty_residences():
            self.assertEqual(
                li.supersession_reason(
                    entry, {"domain": "residences", "none": True}, ROW),
                li.SUPERSEDED_BY_NONE)

    def test_a_substantive_answer_still_clears_a_standing_terminal(self) -> None:
        self.assertEqual(
            li.supersession_reason({"domain": "children", "none": True},
                                   ONE_CHILD, CHILDREN_ROW),
            li.SUPERSEDED_AS_TERMINAL)

    def test_a_skip_is_still_never_an_answer(self) -> None:
        self.assertIsNone(li.supersession_reason(
            thirty_residences()[0],
            {"domain": "residences", "skipped": True}, ROW))

    def test_v214s_own_collapsed_children_row_is_still_retired(self) -> None:
        self.assertEqual(
            li.collapsed_aggregate_fields(COLLAPSED_CHILDREN, CHILDREN_ROW),
            ("span",))
        self.assertEqual(
            li.supersession_reason(COLLAPSED_CHILDREN, ONE_CHILD, CHILDREN_ROW),
            li.SUPERSEDED_AS_COLLAPSED)

    def test_one_childs_own_single_date_span_is_not_a_collapse(self) -> None:
        """The narrowing, from the other side: a `span` on `children` is only
        evidence of a collapse when its bounds actually straddle a stretch."""
        single = {"domain": "children", "who": "Bo", "label": "Bo",
                  "span": {"start": _bound("1981", granularity="year"),
                           "end": _bound("1981", granularity="year")}}
        self.assertEqual(
            li.collapsed_aggregate_fields(single, CHILDREN_ROW), ())
        self.assertIsNone(
            li.supersession_reason(single, ONE_CHILD, CHILDREN_ROW))

    def test_a_field_the_writer_never_emits_is_still_a_collapse(self) -> None:
        """Rule 3 keeps a live meaning: a shape that reached the store from
        outside the writer is exactly what it was built to retire."""
        foreign = dict(thirty_residences()[0])
        foreign["aggregate_of"] = ["stay a", "stay b", "stay c"]
        self.assertEqual(
            li.collapsed_aggregate_fields(foreign, ROW), ("aggregate_of",))
        self.assertEqual(li.supersession_reason(foreign, BARE_RECORD, ROW),
                         li.SUPERSEDED_AS_COLLAPSED)


# --------------------------------------------------------------------------
# Rule 2: one answer is one entry
# --------------------------------------------------------------------------


class FanOutRefusalTest(unittest.TestCase):

    def _foreign(self, count: int) -> list[dict]:
        rows = []
        for entry in thirty_residences()[:count]:
            row = dict(entry)
            row["aggregate_of"] = ["a", "b"]
            rows.append(row)
        return rows

    def test_one_collapsed_entry_is_not_a_fan_out(self) -> None:
        self.assertEqual(
            li.supersession_findings(self._foreign(1), BARE_RECORD, ROW), [])

    def test_two_would_be_refused_out_loud_with_the_count(self) -> None:
        findings = li.supersession_findings(self._foreign(2), BARE_RECORD, ROW)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["lint"], li.SUPERSESSION_FAN_OUT_LINT)
        self.assertEqual(findings[0]["count"], 2)
        self.assertIn("2", findings[0]["detail"])
        self.assertIn("residences", findings[0]["detail"])

    def test_the_incidents_own_count_appears_in_the_finding(self) -> None:
        findings = li.supersession_findings(self._foreign(30), BARE_RECORD, ROW)
        self.assertEqual(findings[0]["count"], 30)
        self.assertIn("30", findings[0]["detail"])
        self.assertEqual(len(findings[0]["entry_keys"]), 30)

    def test_a_none_is_exempt_because_the_fan_out_is_the_point(self) -> None:
        self.assertEqual(
            li.supersession_findings(thirty_residences(),
                                     {"domain": "residences", "none": True},
                                     ROW),
            [])

    def test_a_stated_entry_never_reaches_the_count_at_all(self) -> None:
        """The two rules are independent: the thirty are safe under rule 1, so
        rule 2 has nothing to refuse."""
        self.assertEqual(
            li.supersession_findings(thirty_residences(), BARE_RECORD, ROW), [])


# --------------------------------------------------------------------------
# The writer and the guard cannot drift apart again
# --------------------------------------------------------------------------


class WriterDerivationTest(unittest.TestCase):

    def setUp(self) -> None:
        self.rows = list(li.load_questions())

    def test_every_field_the_writer_stores_is_readable_or_declared_slack(self) -> None:
        """The ladder-consistency guard's leg 4, now asked with the writer's
        OWN answer instead of a hand-written probe."""
        for row in self.rows:
            stored = li.writer_stored_fields(row)
            unread = set(li.unreadable_fields(dict.fromkeys(stored, "x"), row))
            self.assertTrue(
                unread <= set(li.DOMAIN_AGNOSTIC_FIELDS),
                f"{row['domain']}: {sorted(unread - set(li.DOMAIN_AGNOSTIC_FIELDS))} "
                f"stored by the writer and readable by nothing",
            )

    def test_the_pinned_domain_agnostic_slack_is_unchanged(self) -> None:
        """The exact six pairs `tests/test_landmarks.py` has always pinned —
        reproduced from the DERIVED probe, which is the proof that the two
        probes now agree."""
        unread = set()
        for row in self.rows:
            stored = dict.fromkeys(li.writer_stored_fields(row), "x")
            for field in li.unreadable_fields(stored, row):
                unread.add((row["domain"], field))
        self.assertEqual(unread, {
            ("birth", "label"), ("birth", "span"), ("family", "span"),
            ("partnerships", "span"), ("children", "span"),
            ("losses", "span"),
        })

    def test_the_descriptors_are_exactly_what_the_writer_emits(self) -> None:
        stored = li.writer_stored_fields(ROW)
        self.assertTrue(li.WRITER_DESCRIPTOR_FIELDS <= stored)

    def test_non_rung_fields_is_derived_not_repeated(self) -> None:
        """`place`, `subject` and `birth_order` used to be a hand list beside
        `_TEXT_CAPS`; they are now read off it."""
        self.assertTrue({"place", "subject", "birth_order"} <= li.NON_RUNG_FIELDS)
        for field in li.IDENTITY_FIELDS:
            self.assertNotIn(field, li.NON_RUNG_FIELDS)

    def test_an_undeclared_descriptor_cannot_reach_the_store(self) -> None:
        """The drift guard: a field the writer gains without joining
        `WRITER_DESCRIPTOR_FIELDS` is dropped at validation rather than filed
        into a store that has no sentence for it."""
        record = li.validate_landmark({
            "domain": "residences", "city": "Cedarport", "label": "Stay",
            "ongoing": True, "span": {"start": "1984"},
        })
        self.assertIn("ongoing", record)
        smuggled = dict(record)
        smuggled["curb_appeal"] = "high"
        with mock.patch.object(li, "validate_landmark", return_value=smuggled):
            li._WRITER_STORED_FIELDS.clear()
            self.addCleanup(li._WRITER_STORED_FIELDS.clear)
            self.assertIn("curb_appeal", li.writer_stored_fields(ROW))
        li._WRITER_STORED_FIELDS.clear()
        self.assertNotIn("curb_appeal", li.writer_stored_fields(ROW))


# --------------------------------------------------------------------------
# The vault repair
# --------------------------------------------------------------------------


SEED = {
    "residences": [
        residence("Millgate", start="1984-06", end="1990-06"),
        residence("Cedar Row", start="1990-06", end="1996-06"),
        residence("Harbour", start="1996-06", end=None),
    ],
    "schools": [
        {"domain": "schools", "label": "Brindle Grammar",
         "name": "Brindle Grammar", "place": "Cedarport"},
    ],
}


class VaultTestCase(unittest.TestCase):
    """A throwaway vault per test, outside the repo and never ~/Workspace/dave."""

    def setUp(self) -> None:
        self.vault = Path(tempfile.mkdtemp(prefix="lifehug-v349-"))
        self.addCleanup(shutil.rmtree, self.vault, ignore_errors=True)
        self.store = self.vault / "state" / "landmarks.json"
        self.store.parent.mkdir(parents=True, exist_ok=True)
        patch = mock.patch.object(timeline, "LANDMARKS_STORE", self.store)
        patch.start()
        self.addCleanup(patch.stop)
        # `_projection_vault_root` DERIVES the root from the store's path, so
        # the line above is normally enough. It is pinned as well because the
        # CLI test drives `lifehug.cmd_*`, and a module-level vault binding
        # another test left pointing at the checkout would make this suite
        # publish into the repo — which is exactly what happened while this
        # file was being written: `state/landmarks.json` and
        # `state/temporal_claims/` appeared in the worktree and
        # `tests/test_queue_convergence.py` started reading them and failing.
        # `_assert_checkout_clean` below is the standing guard.
        root = mock.patch.object(timeline, "_projection_vault_root",
                                 lambda: self.vault)
        root.start()
        self.addCleanup(root.stop)
        self.addCleanup(self._assert_checkout_clean)
        self.store.write_text(
            json.dumps({"version": 1, "domains": copy.deepcopy(SEED)},
                       indent=2) + "\n", encoding="utf-8")
        timeline.flip_landmarks_if_needed()

    def _assert_checkout_clean(self) -> None:
        """No test in this file may write the repo it is running from."""
        for stray in (ROOT / "state" / "landmarks.json",
                      ROOT / "state" / "temporal_claims"):
            if stray.exists():
                raise AssertionError(
                    f"{stray} was written by a test — the vault binding "
                    f"escaped to the checkout")

    def labels(self, domain: str = "residences") -> list[str]:
        return [entry.get("label")
                for entry in (timeline.load_landmarks().get(domain) or ())]


class StatedEntryKeepsStandingTest(VaultTestCase):
    """Rule 1's last clause, at the seat that can see the provenance."""

    def test_an_entry_with_a_source_of_its_own_is_never_retired_by_shape(self) -> None:
        sources = lp.load_landmark_sources(self.vault)
        self.assertTrue(lp.entry_source_ids(
            sources, domain="residences", entry_key="millgate"))
        findings: list = []
        timeline.save_landmark("residences", dict(BARE_RECORD), findings=findings)
        self.assertEqual(sorted(self.labels()),
                         ["701 North Williams", "Cedar Row", "Harbour", "Millgate"])
        self.assertEqual(findings, [], "nothing was even proposed for retirement")

    def test_the_guard_fires_when_the_shape_rule_would_have(self) -> None:
        """A foreign field on a stated entry: rule 3 wants it, provenance wins,
        and the refusal says so by name."""
        with mock.patch.object(
            li, "collapsed_aggregate_fields",
            side_effect=lambda entry, row: (
                ("aggregate_of",)
                if isinstance(entry, dict) and entry.get("label") == "Millgate"
                else ()),
        ):
            findings: list = []
            timeline.save_landmark("residences", dict(BARE_RECORD),
                                   findings=findings)
        self.assertIn("Millgate", self.labels())
        self.assertEqual([f["lint"] for f in findings],
                         [li.SUPERSESSION_STATED_LINT])
        self.assertIn("millgate", findings[0]["detail"])

    def test_a_fan_out_retires_nothing_and_still_files_the_answer(self) -> None:
        with mock.patch.object(
            li, "collapsed_aggregate_fields",
            side_effect=lambda entry, row: (
                ("aggregate_of",)
                if isinstance(entry, dict) and entry.get("label") in
                ("Millgate", "Cedar Row") else ()),
        ):
            findings: list = []
            timeline.save_landmark("residences", dict(BARE_RECORD),
                                   findings=findings)
        self.assertEqual(sorted(self.labels()),
                         ["701 North Williams", "Cedar Row", "Harbour", "Millgate"])
        self.assertEqual([f["lint"] for f in findings],
                         [li.SUPERSESSION_FAN_OUT_LINT])
        self.assertEqual(findings[0]["count"], 2)

    def test_a_straddling_span_is_retired_despite_its_own_source(self) -> None:
        """The exemption v214 needs, and the reason the provenance clause
        cannot be read bluntly: after the flip EVERY entry has a source, so a
        blanket veto would retire rule 3 itself and leave the founder's four
        children as one row forever. `tests/test_landmarks.py::ManyRecordsTests
        ::test_four_children_file_as_four_entries_and_retire_the_aggregate` is
        the same statement from the other end, and it was SEEN failing when
        this guard was first written without the exemption."""
        timeline.save_landmark("children", {
            "domain": "children", "label": "our four",
            "span": {"start": _bound("1979", granularity="year"),
                     "end": _bound("1990", granularity="year")}})
        self.assertEqual(self.labels("children"), ["our four"])
        # It HAS a promoted source of its own, like every drawn entry does.
        self.assertTrue(lp.entry_source_ids(
            lp.load_landmark_sources(self.vault),
            domain="children", entry_key="our four"))
        self.assertTrue(li.collapsed_by_a_straddling_span(
            {"domain": "children", "label": "our four",
             "span": {"start": _bound("1979", granularity="year"),
                      "end": _bound("1990", granularity="year")}},
            CHILDREN_ROW))
        findings: list = []
        timeline.save_landmark("children", dict(ONE_CHILD), findings=findings)
        self.assertEqual(self.labels("children"), ["Jackie"])
        self.assertEqual(findings, [])

    def test_a_foreign_field_is_only_suggestive_so_provenance_wins(self) -> None:
        """The other side of the same line: not a straddling span, so the
        entry's own source settles it."""
        self.assertFalse(li.collapsed_by_a_straddling_span(
            {"domain": "residences", "label": "Millgate",
             "aggregate_of": ["a", "b"]}, ROW))

    def test_a_none_still_clears_the_domain_through_the_writer(self) -> None:
        timeline.save_landmark("residences", {"domain": "residences", "none": True})
        self.assertEqual(
            [label for label in self.labels() if label], [])


class ReinstateRoundTripTest(VaultTestCase):
    """The repair verb, against a wipe this test performs itself."""

    def wipe(self) -> list[str]:
        """Retire all three residences the way the incident did."""
        for key in ("millgate", "cedar row", "harbour"):
            lp.retire_entry(self.vault, domain="residences", entry_key=key,
                            reason=("superseded by a later residences answer "
                                    "(landmarks_interaction.entry_superseded_by)"))
        timeline.redraw_landmarks()
        return self.labels()

    def test_the_wipe_and_the_repair(self) -> None:
        self.assertEqual(len(self.labels()), 3)
        self.assertEqual(self.wipe(), [])

        plan = lp.reinstate_domain(self.vault, domain="residences")
        self.assertEqual(len(plan["corrections"]), 3)
        self.assertFalse(plan["applied"])
        self.assertIsNone(plan["filed"])
        self.assertEqual(self.labels(), [], "a plan writes nothing")

        summary = lp.reinstate_domain(self.vault, domain="residences", apply=True)
        self.assertTrue(summary["applied"])
        timeline.redraw_landmarks()
        self.assertEqual(sorted(self.labels()),
                         ["Cedar Row", "Harbour", "Millgate"])

    def test_the_entries_come_back_from_their_own_sources(self) -> None:
        """Nothing writes an entry — the invariant the flip established."""
        before = {row["source_id"]: row["record"]
                  for row in lp.load_landmark_sources(self.vault)}
        self.wipe()
        lp.reinstate_domain(self.vault, domain="residences", apply=True)
        timeline.redraw_landmarks()
        after = {row["source_id"]: row["record"]
                 for row in lp.load_landmark_sources(self.vault)}
        self.assertEqual(before, after,
                         "the repair touched no landmark source at all")

    def test_it_is_idempotent(self) -> None:
        self.wipe()
        first = lp.reinstate_domain(self.vault, domain="residences", apply=True)
        again = lp.reinstate_domain(self.vault, domain="residences", apply=True)
        self.assertEqual(again["corrections"], [])
        self.assertFalse(again["applied"])
        third = lp.reinstate_domain(self.vault, domain="residences", apply=True)
        self.assertEqual(third["corrections"], [])
        self.assertEqual(len(first["corrections"]), 3)

    def test_nothing_is_deleted_and_the_supersessions_remain(self) -> None:
        self.wipe()
        retired = lp.domain_supersessions(self.vault, domain="residences")
        lp.reinstate_domain(self.vault, domain="residences", apply=True)
        for row in retired:
            with self.subTest(row["correction_id"]):
                self.assertTrue((self.vault / row["relative_path"]).is_file())

    def test_it_writes_only_corrections_and_state(self) -> None:
        self.wipe()
        before = {path.relative_to(self.vault)
                  for path in self.vault.rglob("*") if path.is_file()}
        lp.reinstate_domain(self.vault, domain="residences", apply=True)
        timeline.redraw_landmarks()
        after = {path.relative_to(self.vault)
                 for path in self.vault.rglob("*") if path.is_file()}
        for path in after - before:
            with self.subTest(str(path)):
                self.assertTrue(
                    str(path).startswith("sources/corrections/")
                    or str(path).startswith("state/"),
                    f"{path} is neither a correction nor state",
                )

    def test_the_window_keeps_the_repair_surgical(self) -> None:
        """A legitimate supersession outside the window is left standing.

        The window is the difference between repairing an incident and undoing
        every correction a person ever made to a domain.
        """
        lp.retire_entry(self.vault, domain="residences", entry_key="millgate",
                        reason="that was my cousin's house, not mine",
                        occurred_at="2026-01-02T00:00:00Z")
        lp.retire_entry(self.vault, domain="residences", entry_key="harbour",
                        reason=("superseded by a later residences answer "
                                "(landmarks_interaction.entry_superseded_by)"),
                        occurred_at="2026-09-24T19:18:00Z")
        timeline.redraw_landmarks()
        self.assertEqual(self.labels(), ["Cedar Row"])

        inside = lp.domain_supersessions(self.vault, domain="residences",
                                         since="2026-09-24T19:17:00Z")
        self.assertEqual([row["created_at"] for row in inside],
                         ["2026-09-24T19:18:00Z"])

        lp.reinstate_domain(self.vault, domain="residences",
                            since="2026-09-24T19:17:00Z", apply=True)
        timeline.redraw_landmarks()
        self.assertEqual(sorted(self.labels()), ["Cedar Row", "Harbour"],
                         "the January correction the person meant still stands")

        self.assertEqual(
            lp.domain_supersessions(self.vault, domain="residences",
                                    since="2099-01-01T00:00:00Z"), [])

    def test_another_domains_supersession_is_untouched(self) -> None:
        lp.retire_entry(self.vault, domain="schools",
                        entry_key="brindle grammar", reason="wrong person")
        self.wipe()
        lp.reinstate_domain(self.vault, domain="residences", apply=True)
        timeline.redraw_landmarks()
        self.assertEqual(self.labels("schools"), [])
        self.assertEqual(len(self.labels()), 3)

    def test_a_reinstated_domain_can_be_superseded_again_by_a_new_record(self) -> None:
        """Reinstatement is not a permanent shield: a NEW supersession, whose
        own reason says why, still stands."""
        self.wipe()
        lp.reinstate_domain(self.vault, domain="residences", apply=True)
        timeline.redraw_landmarks()
        lp.retire_entry(self.vault, domain="residences", entry_key="millgate",
                        reason="that was my cousin's house, not mine")
        timeline.redraw_landmarks()
        self.assertEqual(sorted(self.labels()), ["Cedar Row", "Harbour"])


class ReinstatementIsAStatementTest(VaultTestCase):
    """The correction machine's third kind of target."""

    def test_the_scope_is_its_own(self) -> None:
        self.assertEqual(ts.CORRECTION_CORRECTION_SCOPE, "temporal_correction")
        self.assertNotEqual(ts.CORRECTION_CORRECTION_SCOPE,
                            ts.CONSTRAINT_CORRECTION_SCOPE)

    def test_a_reinstatement_names_a_correction_not_a_claim(self) -> None:
        with self.assertRaises(ts.TemporalStoreError) as caught:
            ts.reinstate_corrections(self.vault, ["claim:abc"], reason="no")
        self.assertEqual(caught.exception.code,
                         "reinstate_target_not_a_correction")

    def test_an_empty_reinstatement_is_refused(self) -> None:
        with self.assertRaises(ts.TemporalStoreError) as caught:
            ts.reinstate_corrections(self.vault, [], reason="no")
        self.assertEqual(caught.exception.code,
                         "correction_claim_ids_required")

    def test_reinstated_correction_ids_reads_back_what_was_written(self) -> None:
        lp.retire_entry(self.vault, domain="residences", entry_key="millgate",
                        reason="a wipe")
        rows = lp.domain_supersessions(self.vault, domain="residences")
        self.assertEqual(ts.reinstated_correction_ids(self.vault), ())
        ts.reinstate_corrections(self.vault,
                                 [row["correction_id"] for row in rows],
                                 reason="it was never retired by anything said")
        self.assertEqual(ts.reinstated_correction_ids(self.vault),
                         tuple(sorted(row["correction_id"] for row in rows)))

    def test_the_fold_is_independent_of_discovery_order(self) -> None:
        """Reinstatement is resolved as a SET, so the index is a function of
        the corrections on disk and not of the order they were read in."""
        lp.retire_entry(self.vault, domain="residences", entry_key="millgate",
                        reason="a wipe")
        rows = lp.domain_supersessions(self.vault, domain="residences")
        ts.reinstate_corrections(self.vault,
                                 [row["correction_id"] for row in rows],
                                 reason="reinstated")
        first = ts.fold_active_index(self.vault, full=True)
        real = ts.load_temporal_corrections

        def reversed_order(root):
            return list(reversed(real(root)))

        with mock.patch.object(ts, "load_temporal_corrections", reversed_order):
            second = ts.fold_active_index(self.vault, full=True)
        self.assertEqual(first["active_claim_ids"], second["active_claim_ids"])

    def test_a_reinstatement_target_is_never_an_unresolved_claim(self) -> None:
        lp.retire_entry(self.vault, domain="residences", entry_key="millgate",
                        reason="a wipe")
        rows = lp.domain_supersessions(self.vault, domain="residences")
        ts.reinstate_corrections(self.vault,
                                 [row["correction_id"] for row in rows],
                                 reason="reinstated")
        index = ts.fold_active_index(self.vault, full=True)
        for target in index["unresolved_correction_targets"]:
            self.assertFalse(target.startswith("temporal_correction:"))

    def test_a_retraction_of_a_claim_is_still_a_retraction(self) -> None:
        """The new scope changes nothing for an ordinary correction."""
        index = ts.fold_active_index(self.vault)
        claim_id = ts.active_claims(index)[0]["claim_id"]
        ts.retract_claims(self.vault, [claim_id], reason="never happened")
        after = ts.fold_active_index(self.vault, full=True)
        self.assertNotIn(claim_id, after["active_claim_ids"])


# --------------------------------------------------------------------------
# The verb, and the manifest
# --------------------------------------------------------------------------


class VerbTest(VaultTestCase):

    def test_the_cli_reinstates_and_prints_what_it_did(self) -> None:
        import argparse
        import contextlib
        import io

        import lifehug

        for key in ("millgate", "cedar row", "harbour"):
            lp.retire_entry(self.vault, domain="residences", entry_key=key,
                            reason="a wipe")
        timeline.redraw_landmarks()
        args = argparse.Namespace(domain="residences", since="", until="",
                                  reason="", apply=True, json=False)
        buffer = io.StringIO()
        with mock.patch.object(lifehug, "REPO_DIR", self.vault), \
                contextlib.redirect_stdout(buffer):
            code = lifehug.cmd_landmark_reinstate(args)
        self.assertEqual(code, 0)
        printed = buffer.getvalue()
        self.assertIn("reinstated 3 residences supersession(s)", printed)
        self.assertIn("entries drawn: 3", printed)
        self.assertEqual(sorted(self.labels()),
                         ["Cedar Row", "Harbour", "Millgate"])

    def test_a_bare_run_writes_nothing(self) -> None:
        import argparse
        import contextlib
        import io

        import lifehug

        lp.retire_entry(self.vault, domain="residences", entry_key="millgate",
                        reason="a wipe")
        timeline.redraw_landmarks()
        before = {path.relative_to(self.vault)
                  for path in self.vault.rglob("*") if path.is_file()}
        args = argparse.Namespace(domain="residences", since="", until="",
                                  reason="", apply=False, json=False)
        with mock.patch.object(lifehug, "REPO_DIR", self.vault), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(lifehug.cmd_landmark_reinstate(args), 0)
        after = {path.relative_to(self.vault)
                 for path in self.vault.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_the_verb_is_classified_as_a_vault_mutator(self) -> None:
        import lifehug

        self.assertIn("landmark-reinstate", lifehug.DIRECT_MUTATION_COMMANDS)
        self.assertNotIn("landmark-reinstate", lifehug.READ_ONLY_COMMANDS)


class ManifestTests(unittest.TestCase):

    def test_the_new_files_ship_in_framework_files(self) -> None:
        manifest = json.loads(
            (ROOT / "system" / "version.json").read_text(encoding="utf-8"))
        for name in (
            "system/landmarks_interaction.py",
            "system/landmark_projection.py",
            "system/temporal_store.py",
            "system/timeline.py",
            "tests/test_v349_a_stated_entry_is_never_retired_by_shape.py",
        ):
            with self.subTest(name):
                self.assertIn(name, manifest["framework_files"])

    def test_the_release_is_v349_or_later(self) -> None:
        """v350 loosened the equality this pinned. The assertion is that the
        release this file guards has SHIPPED, not that nothing has shipped
        since — an equality here makes every later bump fail a test about a
        landmark rule, which is not what it is for."""
        manifest = json.loads(
            (ROOT / "system" / "version.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(manifest["version"], 349)


if __name__ == "__main__":
    unittest.main()
