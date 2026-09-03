#!/usr/bin/env python3
"""Placement certainty over the calculated projection (ADR 0027, Cut 2a).

The legacy :func:`timeline.placement_score` computes *how placed this life
is* — the level, its stated/derived pair, and the per-year certainty strip —
over the legacy ``timeline_data()`` payload (``anchors``, ``event_lineup``,
``periods``, ``bands``). That arithmetic is ADR 0027's, not the payload's,
and this module runs the SAME arithmetic over the calculated projection
(:mod:`temporal_projection`) so a vault that has moved to the calculated side
still gets a real band instead of ``calculated-certainty.ts``'s
``placement: null``.

**One arithmetic, two inputs.** Every number-crunching step — the width
discipline, the inferred-placement discount, the band thresholds, the
per-year aoristic strip — is imported from :mod:`timeline` and called
unchanged: :func:`timeline._level`, :func:`timeline._years_width`,
:func:`timeline._record_width` / :func:`timeline._record_years`,
:func:`timeline.placement_score_band` and :func:`timeline._per_year_band`.
Those five are already shape-agnostic — they consume a list of ``thing``
dicts (``{kind, key, years, width, stated_years, stated_width, dated,
derived, inferred}``) and never touch ``timeline_data()``'s own dict shape —
so nothing in :mod:`timeline` had to change (ADR 0027 §7's own words: "the
level and the margin must share one arithmetic — standing rule", read here
as "the legacy score and the calculated score must share one arithmetic").
What is new here is only the ADAPTER: turning a
:class:`temporal_projection.CalculatedTimelineNode` into the same ``thing``
shape :func:`timeline._thing` builds from a legacy row.

**The field mapping** (legacy → calculated), spelled out because it is the
one thing that could silently drift:

============================  =========================================
legacy                        calculated
============================  =========================================
``anchors.birth.date``        the ``event`` node with ``event_kind ==
                               "birth"`` and ``"self"`` in
                               ``subject_refs`` (:data:`OWNER_BIRTH_EVENT_KIND`,
                               :data:`OWNER_SUBJECT_REF`) — its
                               ``best_temporal_value``. Absent → no score,
                               exactly as ADR 0027 rule 8 requires.
``event_lineup`` /
``unplaced_events`` moments   ``event`` nodes, EXCLUDING the birth node
                               itself — birth is the ruler that defines
                               ``L``, never a thing scored against it,
                               matching how legacy never scores ``anchors``
                               entries as ``event_lineup`` rows.
``periods`` (excluding
``kind == "age_frame"``)      ``period`` nodes with ``event_kind ==
                               "named_era"``. Age-frame period nodes are
                               excluded for the identical reason legacy
                               excludes them: an age frame is the
                               coordinate system, not a thing whose own
                               placement is in question.
``bands[].places[]``
(residence spans)              ``episode`` nodes (residence / job / school
                               / military / relationship participation
                               spans) — the calculated side's one broader
                               notion of "a span something happened
                               inside", not narrowed to residence alone,
                               because ADR 0027 never scored those kinds
                               apart and the calculated graph has no
                               parallel "place span vs. everything else"
                               split to preserve.
a record's basis (the
``date_derived`` flag /
``temporal_work_items.
node_claim_basis``)           ``node["basis"]`` — ``explicit`` /
                               ``calculated`` / ``inferred``
                               (:data:`temporal_claims.CLAIM_BASES`), the
                               SAME three-way vocabulary
                               ``node_claim_basis`` maps a date record's
                               chronology basis onto. ``explicit`` reads as
                               legacy's "not derived, not inferred";
                               ``calculated`` as legacy's ``date_derived``;
                               ``inferred`` as legacy's ``inferred`` (half
                               credit, :data:`timeline.INFERRED_PLACEMENT_
                               WEIGHT`) — a node's own basis is not
                               recomputed here, it is trusted, because the
                               fold already stamped it through the one
                               ``node_claim_basis`` mapping.
``unknown_years()``'s
band-span / spine-hole
fallback                      ``node["possible_temporal_value"]`` when
                               present (a containment window the fold
                               already computed — E3's ``within(frame)``,
                               an identity binder's outer range), else the
                               life span floor. The calculated graph
                               publishes this fallback directly; nothing
                               here re-derives a band span by hand.
============================  =========================================

**One deliberate, named simplification.** ADR 0027 rule 3 (§3, "stated and
derived are a pair") requires ``score_stated`` to read anything the person
did not literally state as unplaced, *including* an undated thing's
fallback interval — ``_stated_view`` nulls out every derived span so an
undated moment cannot inherit an era the cross-dating pass just dated.
Reproducing that exactly over the calculated graph would mean re-deriving,
for every node, what its ``possible_temporal_value`` would have been had
every ``calculated``/``inferred`` node upstream of it been read as
unplaced — a second, parallel fold. Instead, :func:`_thing_from_node` gives
the stated basis the life span itself as the fallback for anything that is
not ``dated and basis == "explicit"``. This can only ever be MORE
conservative than legacy's band-aware fallback (a wider interval, never a
narrower one), so it never overstates ``score_stated`` — it can understate
it on a vault where an undated thing sits inside an explicitly-dated
container and legacy's ``_band_span`` would have narrowed the stated
fallback to that container's own dates. The oracle test in
``tests/test_temporal_placement.py`` is built to avoid that one case (no
undated thing inside an explicitly-dated container) so legacy and
calculated agree exactly on the fixture; the gap is named here rather than
patched with new arithmetic (no heuristic invented to close it).

**What is NOT here.** ``next_gain`` — the margin, "one answer would place
N things" — needs ``timeline.keystones()``'s greedy plan over the legacy
anchor graph, which Cut 3 (`resolves`/`leverage` published from the
calculated projection, ADR 0027 amended) replaces with a calculated-graph
equivalent. Publishing a margin here would mean inventing a second,
un-audited greedy plan; :func:`placement_for_projection` publishes
``next_gain: None`` instead and Cut 3 fills it in over the same one
arithmetic once `resolves`/`leverage` exist on the calculated side.

Controlling contracts: ADR 0027 (the placement score), the
2026-09-03 timeline-unification decision record §4.3 and §7 Cut 2, and the
execution plan's "2a · OSS · Placement certainty over the calculated
projection".
"""

from __future__ import annotations

import sys
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import temporal_projection as tp  # noqa: E402
import temporal_work_items as twi  # noqa: E402
import timeline as tl  # noqa: E402

#: The owner's own subject ref (`temporal_work_items.OWNER_SUBJECT_REF`),
#: spelled again here under the name this module's readers will look for.
OWNER_SUBJECT_REF = twi.OWNER_SUBJECT_REF

#: The event kind that marks the owner's own birth node
#: (`temporal_work_items.BIRTH_ORIGIN_EVENT_KIND`) — the calculated graph's
#: one analog of legacy's `anchors.birth`.
OWNER_BIRTH_EVENT_KIND = twi.BIRTH_ORIGIN_EVENT_KIND

__all__ = ["placement_for_projection", "OWNER_SUBJECT_REF", "OWNER_BIRTH_EVENT_KIND"]


def _life_span(projection: dict) -> tuple[int, int] | None:
    """`(birth_year, current_year)` from the projection's own birth node.

    `timeline.life_span` is reused unchanged — it only ever needed a
    resolvable date record, never the legacy payload shape. `None` when no
    owner birth node exists or it carries no resolvable date, matching ADR
    0027 rule 8 exactly: no birth landmark, no score.
    """
    for node in projection.get("nodes") or ():
        if not isinstance(node, dict):
            continue
        if node.get("node_kind") != "event":
            continue
        if node.get("event_kind") != OWNER_BIRTH_EVENT_KIND:
            continue
        subjects = node.get("subject_refs") or ()
        if OWNER_SUBJECT_REF not in subjects:
            continue
        record = node.get("best_temporal_value")
        if record is None:
            continue
        life = tl.life_span(birth_date=record)
        if life is not None:
            return life
    return None


def _is_scored_node(node: dict) -> bool:
    """Is this node one of the THINGS the score counts — see the mapping
    table in the module docstring. Age frames (the ruler) and the owner's
    own birth node (the anchor `L` is measured from) are excluded for the
    same reason legacy excludes age-frame periods and never scores its own
    `anchors.birth` entry as an `event_lineup` row."""
    node_kind = node.get("node_kind")
    event_kind = node.get("event_kind")
    if node_kind == "period":
        return event_kind == tp.NAMED_ERA_EVENT_KIND
    if node_kind == "event":
        return event_kind != OWNER_BIRTH_EVENT_KIND
    if node_kind == "episode":
        return True
    return False


def _thing_from_node(node: dict, life: tuple[int, int]) -> dict:
    """One calculated node, as the `thing` shape `timeline._level` and
    `timeline._per_year_band` already consume — the adapter half of the
    field mapping table above."""
    record = node.get("best_temporal_value")
    dated = record is not None
    basis = str(node.get("basis") or "inferred")
    inferred = dated and basis == "inferred"
    # `calculated` is legacy's `date_derived`; `inferred` also counts as
    # derived for the stated/derived split, exactly as legacy's
    # `derived = derived or inferred` does.
    derived = dated and basis in ("calculated", "inferred")
    if dated:
        years = tl._record_years(record) or [life[0], life[1]]  # noqa: SLF001
        width = tl._record_width(record, life)  # noqa: SLF001
    else:
        possible = node.get("possible_temporal_value")
        if possible is not None:
            years = tl._record_years(possible) or [life[0], life[1]]  # noqa: SLF001
        else:
            years = [life[0], life[1]]
        width = tl._years_width(years)  # noqa: SLF001
    if dated and basis == "explicit":
        stated_years, stated_width = years, width
    else:
        # The named simplification (module docstring): anything not
        # explicitly stated floors to the life span on the stated basis,
        # never to a containment the fold may have derived.
        stated_years = [life[0], life[1]]
        stated_width = tl._years_width(stated_years)  # noqa: SLF001
    return {
        "kind": node.get("node_kind"),
        "key": node.get("node_id"),
        "years": years,
        "width": width,
        "stated_years": stated_years,
        "stated_width": stated_width,
        "dated": dated,
        "derived": derived,
        "inferred": inferred,
    }


def placement_for_projection(projection: dict) -> dict | None:
    """The placement-score payload (ADR 0027), computed over a published or
    in-memory calculated projection instead of the legacy payload.

    Same return shape `timeline.placement_score` publishes — `score`,
    `score_formula_version`, `score_stated`, `band`, `stated_fraction`,
    `derived_fraction`, `inferred_fraction`, `life_span_years`, `things`,
    `per_year_band`, `caveat_floor` — with `next_gain` published as `None`
    (see the module docstring's "What is NOT here").

    `None` when there is no birth node to measure `L` from, or when the
    projection holds no scoreable thing at all — the same two refusals
    `timeline.placement_score` makes, for the same reason.
    """
    if not isinstance(projection, dict):
        return None
    life = _life_span(projection)
    if life is None:
        return None
    things = [
        _thing_from_node(node, life)
        for node in (projection.get("nodes") or ())
        if isinstance(node, dict) and _is_scored_node(node)
    ]
    if not things:
        return None
    score = tl._level(things, life)  # noqa: SLF001
    dated = [thing for thing in things if thing["dated"]]
    derived = sum(1 for thing in dated if thing["derived"])
    inferred = sum(1 for thing in dated if thing["inferred"])
    stated = len(dated) - derived
    return {
        "score": score,
        "score_formula_version": tl.PLACEMENT_SCORE_FORMULA_VERSION,
        "score_stated": tl._level(things, life, key="stated_width"),  # noqa: SLF001
        "band": tl.placement_score_band(score),
        "stated_fraction": (round(stated / len(dated), tl.PLACEMENT_ROUNDING)
                            if dated else 0.0),
        "derived_fraction": (round(derived / len(dated), tl.PLACEMENT_ROUNDING)
                             if dated else 0.0),
        "inferred_fraction": (round(inferred / len(dated), tl.PLACEMENT_ROUNDING)
                              if dated else 0.0),
        "life_span_years": int(max(life[1] - life[0], 1)),
        "things": len(things),
        "per_year_band": tl._per_year_band(things, life),  # noqa: SLF001
        "caveat_floor": True,
        # Cut 3 scope (`resolves`/`leverage` from the calculated graph) —
        # see the module docstring's "What is NOT here".
        "next_gain": None,
    }
