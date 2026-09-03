#!/usr/bin/env python3
"""ONE gain for every Timeline-owned repair item (Cut 3a, ADR 0027).

The legacy projection has ranked its unknowns by ``resolves`` and
``leverage = 1 + len(resolves)`` since v208 (`timeline.row_leverage`), and the
★ keystone is a greedy plan over the residual of that same graph
(`timeline.keystones`, v198/v204). The calculated projection had neither: its
work items carried ``combined_score``, computed elsewhere, on a different
scale, so Needs Placing had two incomparable numbers and a category order on
top of them.

**This module is a PORT, not a new metric.** Same arithmetic, same
self-inclusive ``1 +``, same greedy-over-the-residual plan, same
``KEYSTONE_CAP``, same ``tl:<anchor-slug>`` identity — over the calculated
dependency graph instead of the legacy one. No precision weighting and no
uncertainty-reduction estimate: the decision record (2026-09-03, §7 Cut 3;
review §2.5) rules those a later tier, to be built only if v1 is measured
insufficient.

It is pure: plain dicts in, plain dicts out, no I/O, no clock, no model. The
fold hands it the graph it already has; a test hands it a hand-written one.

The five dependency rules
-------------------------

An edge means *"this node's interval would change if that anchor were
answered"*, and each one is read off something the projection already
publishes or the fold already computed:

* **D1 ordering anchor.** Every resolved ordering edge — a ``before`` /
  ``after`` / ``between`` / ``within`` relative claim, or a durable
  ``OrderingConstraint`` (a drag) — makes its subject depend on each anchor
  node. This is the calculated twin of an era bounding the moments placed in
  it.
* **D2 episode containment.** A node whose published ``containments`` cite an
  episode depends on that episode's bounds: a stay that nobody has dated
  leaves every event inside it holding a window and no value.
* **D3 birth origin.** Every node the fold could not place because an age
  statement had no birthday to count from (``age_without_birth_anchor``)
  depends on the origin anchor ``origin:<owner>``. The origin is the
  coordinate system; nothing else in the graph reaches as far.
* **D4 unresolved anchor handle.** A node whose relative claim named an anchor
  the substrate cannot resolve (*"the summer after we moved"*) depends on that
  handle, keyed by the same unresolved subject ref the handle's own work item
  is minted under.
* **D5 the universe.** Only a node that would actually GAIN counts: the
  unplaced nodes, plus every node a Timeline-owned item is already asking
  about (a coarse date narrows). An item never resolves itself.

Deliberately **not** a rule: an era or frame MEMBERSHIP. ADR 0030 and the eras
design are explicit that *an era's members are coverage, never bounds* — a
membership is a receipt. Dating an era bounds its members through D1's
``within`` edge, which is a claim somebody made, and through nothing else.

What it publishes
-----------------

* per Timeline-owned work item: ``resolves`` (node ids, sorted, never its own)
  and ``leverage`` (``1 + len(resolves)``, so a lone undated event is exactly
  ``1``);
* ``keystones``: the greedy plan, at most :data:`KEYSTONE_CAP` rows, each
  ``{"id": "tl:<anchor-slug>", ...}``;
* ``dependency_index``: the graph the two above were computed from, so the
  numbers are checkable rather than asserted.

Mirror-owned kinds (``contradiction``, ``identity_uncertain``) are left
completely alone, ``combined_score`` included: they are not Timeline rows and
ranking them by reach would be answering a different question.

Controlling contract: `lifehug-platform
docs/decisions/2026-09-03-timeline-unification/execution-plan.md` §3a.
"""

from __future__ import annotations

import sys
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import temporal_work_items as twi  # noqa: E402
import timeline_interaction as ti  # noqa: E402

#: How many stars a plan may hold. The legacy twin is `timeline.KEYSTONE_CAP`
#: and the two are pinned equal by `tests/test_timeline_gain.py` — spelled here
#: rather than imported because `timeline` imports the publication, which
#: imports the fold, which imports this module.
KEYSTONE_CAP = 2

#: The kinds Mirror owns. They keep `combined_score` and get no `leverage`:
#: "which of these two readings is right" is not a question about reach.
MIRROR_OWNED_KINDS = ("contradiction", "identity_uncertain")

#: The surface that makes an item a Timeline row.
TIMELINE_SURFACE = "timeline"

#: The anchor-ref namespace for the birth origin. Every other anchor ref in the
#: index is a node id or an unresolved subject ref, both of which are already
#: unique; the origin is not a node until somebody says when it was.
ORIGIN_PREFIX = "origin:"

#: What a missing `interaction_cost` costs at the tie-break. Legacy uses 99 for
#: a probe with no stated cost, for the same reason: an unknown cost loses.
UNKNOWN_COST = 1.0


def _text(value: object) -> str:
    return str(value or "").strip()


def origin_anchor(owner: object) -> str:
    """``origin:self`` — the birth origin's anchor ref."""
    return f"{ORIGIN_PREFIX}{_text(owner)}"


def is_timeline_owned(item: object) -> bool:
    """Is this a Timeline repair row (§3a scope)?

    ``timeline`` in ``allowed_surfaces`` and a kind Mirror does not own. The
    surface list is the mechanism §2.4 already uses to route work, so this asks
    the published field rather than re-deciding per kind.
    """
    if not isinstance(item, dict):
        return False
    if _text(item.get("kind")) in MIRROR_OWNED_KINDS:
        return False
    surfaces = item.get("allowed_surfaces") or ()
    if isinstance(surfaces, (str, bytes)):
        surfaces = [surfaces]
    return TIMELINE_SURFACE in {_text(s) for s in surfaces}


def anchor_ref(item: object) -> str:
    """The anchor key this item would SUPPLY — the legacy `unknown_anchor` job.

    A row is ranked by what ANSWERING IT places, so it is looked up under the
    anchor it becomes, never under an anchor it merely belongs to (ADR 0027,
    issue #216).

    * a node-shaped item → its ``node_ref``;
    * the birth-origin item → :func:`origin_anchor` of its subject;
    * an unresolved-handle item → its own ``subject_ref``.

    ``""`` when the item becomes no anchor, which yields ``leverage: 1`` —
    answering it still places itself.
    """
    if not isinstance(item, dict):
        return ""
    node_ref = _text(item.get("node_ref"))
    if node_ref:
        return node_ref
    subject = _text(item.get("subject_ref"))
    if not subject:
        return ""
    if _text(item.get("requested_field")) == twi.REQUESTED_FIELD_BIRTH_DATE:
        return origin_anchor(subject)
    return subject


def gain_universe(*, nodes: object = (), items: object = (),
                  unplaced: object = ()) -> set[str]:
    """D5 — the node ids that could still GAIN from an answer.

    Two populations, and both are already computed elsewhere rather than
    re-derived here: the fold's own ``diagnostics["unplaced"]``, and the node
    every Timeline-owned item is about (a `precision_gap`'s node is placed and
    still narrows). ``nodes`` is accepted so a caller can restrict the universe
    to node ids the projection actually holds.
    """
    known = {
        _text(row.get("node_id"))
        for row in (nodes or ())
        if isinstance(row, dict) and _text(row.get("node_id"))
    }
    live = {_text(node_id) for node_id in (unplaced or ()) if _text(node_id)}
    for item in items or ():
        if not is_timeline_owned(item):
            continue
        node_ref = _text(item.get("node_ref"))
        if node_ref:
            live.add(node_ref)
    return (live & known) if known else live


def dependency_index(
    *,
    nodes: object = (),
    ordering: object = (),
    anchors: object = None,
    universe: object = None,
) -> dict[str, list[str]]:
    """``{anchor_ref: [node ids]}`` — what answering one anchor would place.

    ``ordering`` is D1 as ``(subject_node_id, (anchor_node_id, ...))`` pairs —
    the fold's resolved edges, handed over as plain data so this module never
    reaches into the fold's private edge type. ``anchors`` is D3 and D4, which
    only the fold can key (``{anchor_ref: [node ids]}``): a handle and an
    origin are anchors with no node of their own.

    D2 is read here, off the nodes themselves, because ``containments`` is a
    published field and a caller should not have to unpack it twice.

    Every dependent is filtered to ``universe`` (D5), exactly as legacy filters
    its resolve sets to the live unknown keys: an anchor that would place
    something already placed has not earned the number.
    """
    live = None if universe is None else {_text(key) for key in universe}
    index: dict[str, set[str]] = {}

    def add(anchor: object, node_id: object) -> None:
        key, dependent = _text(anchor), _text(node_id)
        if not key or not dependent or key == dependent:
            return
        if live is not None and dependent not in live:
            return
        index.setdefault(key, set()).add(dependent)

    for subject, anchor_ids in ordering or ():
        for anchor in anchor_ids or ():
            add(anchor, subject)

    for row in nodes or ():
        if not isinstance(row, dict):
            continue
        node_id = _text(row.get("node_id"))
        for link in row.get("containments") or ():
            if isinstance(link, dict):
                add(link.get("episode_node_id"), node_id)

    for anchor, dependents in (anchors or {}).items():
        for node_id in dependents or ():
            add(anchor, node_id)

    return {key: sorted(value) for key, value in sorted(index.items())}


def item_gain(item: object, index: object) -> tuple[list[str], int]:
    """ONE item's ``(resolves, leverage)`` — `timeline.row_leverage`'s twin.

    Identical arithmetic: the anchor's resolve set minus the item's own node,
    and ``1 + len(resolves)``. Self-inclusive, so a row that places nothing but
    itself is exactly ``1`` and no Timeline row is ever ``0``.
    """
    anchor = anchor_ref(item)
    resolved = set((index or {}).get(anchor) or ()) if anchor else set()
    resolved.discard(_text((item or {}).get("node_ref")))
    resolves = sorted(resolved)
    return resolves, 1 + len(resolves)


def apply_gain(items: object, index: object) -> list[dict]:
    """Stamp ``resolves``/``leverage`` on every Timeline-owned row.

    Returns new dicts; the Mirror-owned rows come back untouched, ``scores``
    and ``combined_score`` included. Order is preserved — ranking is the host's
    job (ADR 0027: the package supplies honest per-row numbers and does no
    ranking), and the keystone plan below is the one exception, because a plan
    is not an ordering.
    """
    stamped: list[dict] = []
    for item in items or ():
        if not isinstance(item, dict) or not is_timeline_owned(item):
            stamped.append(dict(item) if isinstance(item, dict) else item)
            continue
        resolves, leverage = item_gain(item, index)
        stamped.append({**item, "resolves": resolves, "leverage": leverage})
    return stamped


def _scored_items(items: object, index: object) -> list[dict]:
    """Every Timeline-owned item that would place something else, scored.

    Freshly built on every call so the greedy loop can stamp ``gain`` on its
    picks without mutating anything shared — the legacy `_scored_anchors`
    contract, kept.
    """
    scored = []
    for item in items or ():
        if not isinstance(item, dict) or not is_timeline_owned(item):
            continue
        anchor = anchor_ref(item)
        if not anchor:
            continue
        resolves, leverage = item_gain(item, index)
        if not resolves:
            continue
        row = {
            "id": ti.keystone_question_id(anchor),
            "anchor": anchor,
            "work_item_id": _text(item.get("work_item_id")),
            "leverage": leverage,
            "resolves": resolves,
            "cost": _cost(item),
        }
        node_ref = _text(item.get("node_ref"))
        if node_ref:
            row["node_ref"] = node_ref
        question = _text(item.get("prompt_intent"))
        if question:
            row["question"] = question
        scored.append(row)
    return scored


def _cost(item: dict) -> float:
    """The tie-break cost: cheaper wins, an unstated cost loses."""
    try:
        return float(item.get("interaction_cost"))
    except (TypeError, ValueError):
        return UNKNOWN_COST


def keystones(items: object, index: object, n: int = KEYSTONE_CAP) -> list[dict]:
    """The greedy plan over the RESIDUAL graph — `timeline.keystones`'s twin.

    ```
    S ← ∅
    for i in 1..n:
        aᵢ    ← argmax_a |R(a) minus S|   # marginal gain, not leverage
        gainᵢ ← |R(aᵢ) minus S|
        S     ← S ∪ R(aᵢ)
    ```

    Ordering independently by leverage double-counts: on real vault data one
    star's resolve set was a strict SUBSET of the other's, so the second star
    bought nothing (`system/research/go-deep.md` §8.2/§8.3, via v198). An item
    whose marginal gain is zero is never starred, however large its leverage,
    and a plan that runs out of gain stops short of the cap rather than filling
    it with a question that places nothing new.

    Ties break by interaction cost, then by the anchor ref, so two rebuilds
    over one graph pick the same star.

    Each row keeps ``leverage`` — the total reach, the number the person is
    shown — and gains ``gain``, the marginal contribution that earned its
    place. The host stars ``keystones[0]``.
    """
    remaining = _scored_items(items, index)
    plan: list[dict] = []
    covered: set[str] = set()
    for _ in range(max(int(n), 0)):
        best: dict | None = None
        best_key: tuple | None = None
        best_marginal: set[str] = set()
        for row in remaining:
            marginal = set(row["resolves"]) - covered
            if not marginal:
                continue
            key = (-len(marginal), row["cost"], row["anchor"])
            if best_key is None or key < best_key:
                best, best_key, best_marginal = row, key, marginal
        if best is None:
            break  # nothing left adds anything — a shorter plan is the honest one
        plan.append({**{k: v for k, v in best.items() if k != "cost"},
                     "gain": len(best_marginal)})
        covered |= best_marginal
        remaining = [row for row in remaining if row is not best]
    return plan


__all__ = [
    "KEYSTONE_CAP",
    "MIRROR_OWNED_KINDS",
    "ORIGIN_PREFIX",
    "TIMELINE_SURFACE",
    "anchor_ref",
    "apply_gain",
    "dependency_index",
    "gain_universe",
    "is_timeline_owned",
    "item_gain",
    "keystones",
    "origin_anchor",
]
