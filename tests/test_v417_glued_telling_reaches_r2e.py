"""v417 (owner's vault at v415): a glued resolver telling reaches R2e.

After the v415 bindings his father's graduation was one folded row, and
"Dad graduated, got San Diego job" (1987/1988, subject "narrator's family",
a resolver telling) still stood apart — and its telling appeared nowhere in
the dry run. The resolver files every reading of one node under one
``resolver:<hex>`` source; once the node had been re-keyed, that telling held
readings naming the OLD node id and the NEW one, so v414's "a telling of
several events" guard read one event under two ids as two events and R2e
never saw it. A telling is several events when its claims tell several
things, not when one thing has had two ids.

Also: the dry run says which tellings the binder skipped, and why.

Synthetic data only (the Hale family); NEVER references any real vault.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import chronology as chrono  # noqa: E402
import episode_binder as eb  # noqa: E402
import episode_containers as ec  # noqa: E402
import temporal_claims as tc  # noqa: E402

import test_v414_narrator_is_not_the_newborn as v414  # noqa: E402

NOW = "2026-10-10T12:00:00Z"
OLD_NODE = "node:e94007e68e96708a52c51676"
NEW_NODE = "node:34f272c08bf1a2b3c4d5e6f7"
RESOLVER = "resolver:e94007e68e96708a52c51676"

#: His father, known to the roster by name only: "Dad" is three letters, too
#: short to be an index key, and nobody filed "father" as an alias.
ROSTER = {"version": 1, "type": "person", "entities": [
    {"name": "Walter Hale", "slug": "walter-hale", "relationship": "parent",
     "aliases": ["Walter", "dad"]},
]}


def resolver_reading(event_ref: str, revision: str, when: str = "1987/1988") -> dict:
    """One resolver reading of the glued node, filed under its own source."""
    record = chrono.parse_stated_date(when).to_dict()
    record.update(basis="anchor", confidence="inferred")
    return tc.validate_temporal_claim({
        "source_kind": "system_derived", "claim_type": "date",
        "subject_mention": "narrator's family", "event_kind": "moment",
        "event_ref": event_ref, "event_mention": "Dad graduated, got San Diego job",
        "temporal_value": record, "evidence": [{"quote": "the San Diego job years"}],
        "basis": "inferred", "confidence": 0.5, "extractor_version": "resolver/rule:3",
        "source_ref": {"source_id": RESOLVER, "revision": "sha256:" + revision * 64,
                       "source_path": "answers/q7.md"},
    }, now=NOW)


def vault_claims() -> list:
    return [
        v414._gclaim("a", "Dad's graduation", subject="Dad", kind="moment", when="1987"),
        v414._gclaim("b", "Dad graduated", subject="Dad", kind="graduation", when="1987"),
        # The same node read twice by the resolver, before and after its re-key.
        resolver_reading(OLD_NODE, "1"),
        resolver_reading(NEW_NODE, "2"),
    ]


def index() -> ec.EntityIndex:
    return ec.entity_index({"person": ROSTER})


class TheGluedResolverTellingReachesR2eTests(unittest.TestCase):

    def setUp(self):
        self.views = eb.telling_views(vault_claims(), entity_index=index())

    def test_one_event_under_two_ids_is_one_event(self):
        view = self.views[RESOLVER]
        self.assertEqual(view.node_refs, frozenset({OLD_NODE, NEW_NODE}))
        self.assertFalse(eb.tells_several_events(view))

    def test_it_is_read_by_its_graduation_clause(self):
        readings = eb.graduation_readings(self.views, index())
        self.assertIn(RESOLVER, readings)
        subject, reading = readings[RESOLVER]
        self.assertTrue(reading.glued)
        self.assertEqual(subject, readings[v414._gref("a")][0])

    def test_it_folds_into_the_1987_row_without_lending_its_year(self):
        links = eb.graduation_links(self.views, index=index())
        members = {ref for link in links for ref in link.members}
        self.assertEqual(members, {v414._gref("a"), v414._gref("b"), RESOLVER})
        self.assertTrue(all(link.key.endswith(":1987") for link in links))
        result = eb.plan(vault_claims(), entity_index=index(), now=NOW)
        groups = [g for g in result.exact_groups if eb.RULE_ID_GRADUATION in g["rule_ids"]]
        self.assertEqual(len(groups), 1)
        self.assertIn(RESOLVER, groups[0]["members"])

    def test_a_whole_message_of_several_events_is_still_never_bound(self):
        whole = "conversation:msg-0f0f0f0f"
        claims = [*vault_claims(),
                  v414._gclaim("w1", "Brittney born", subject="Brittney", kind="birth",
                               when="1987-12-17", source_id=whole),
                  v414._gclaim("w3", "Dad graduated", subject="Dad", kind="graduation",
                               when="1987", source_id=whole)]
        views = eb.telling_views(claims, entity_index=index())
        self.assertTrue(eb.tells_several_events(views[whole]))
        self.assertNotIn(whole, eb.graduation_readings(views, index()))


class TheFoldedRowKeepsItsCleanTitleTests(unittest.TestCase):

    def test_bound_it_never_titles_the_row_nor_moves_its_year(self):
        import temporal_store as ts  # noqa: PLC0415
        import temporal_timeline as tt  # noqa: PLC0415

        claims = vault_claims()
        result = eb.plan(claims, entity_index=index(), now=NOW)
        envelope = next(row for row in result.exact_envelopes
                        if RESOLVER in row["operation"]["members"])
        drawn = tt.derive_calculated_timeline(
            {"version": ts.INDEX_VERSION, "claims": claims},
            episode_records={"operations": [envelope["operation"]],
                             "bindings": envelope["bindings"]},
            roster_snapshot=ROSTER, now=NOW)
        rows = [n for n in drawn.nodes if "graduat" in str(n.get("label")).lower()]
        self.assertEqual(len(rows), 1, [n["label"] for n in rows])
        self.assertNotIn("job", rows[0]["label"].lower())
        self.assertEqual(rows[0]["best_temporal_value"]["earliest"][:4], "1987")
        self.assertEqual(rows[0]["best_temporal_value"]["latest"][:4], "1987")


class TheDryRunSaysWhatItSkippedTests(unittest.TestCase):

    def test_one_line_per_skipped_telling_with_its_reason(self):
        whole = "conversation:msg-0f0f0f0f"
        claims = [*vault_claims(),
                  v414._gclaim("w1", "Brittney born", subject="Brittney", kind="birth",
                               when="1987-12-17", source_id=whole),
                  v414._gclaim("w3", "Dad graduated", subject="Dad", kind="graduation",
                               when="1987", source_id=whole),
                  v414._gclaim("own", "Graduation from ASU", subject="self",
                               kind="graduation", when="2013")]
        result = eb.plan(claims, entity_index=index(), now=NOW)
        skipped = {row["telling_ref"]: row for row in result.skipped}
        self.assertEqual(skipped[whole]["rung"], eb.RULE_ID_GRADUATION)
        self.assertIn("several events", skipped[whole]["reason"])
        self.assertIn("owner", skipped[v414._gref("own")]["reason"])
        self.assertNotIn(RESOLVER, skipped)
        lines = [line for line in eb.describe(result) if "skipped" in line and whole in line]
        self.assertEqual(len(lines), 1, lines)


if __name__ == "__main__":
    unittest.main()
