#!/usr/bin/env python3
"""Timeline-gain question candidates — one chooser (Cut 5b, R2).

The defect this closes is `README.md` L288's own sentence: *"Timeline/Mirror
gap findings are a different lane … they never enter the bank themselves"*.
Owner ruling **R2** (2026-09-03) reverses it:

    *Landmark and timeline questions may enter the daily queue, and may
    surface as whispers, when they pass the shared value threshold.*

Not "always", and not "never". **Above the bar, under the caps.** This module
is the one door between the published Timeline projection and the question
machinery, and it is deliberately a narrow one: it reads two published blocks,
applies four refusals, and hands the survivors to the seam the keystone lane
already used.

What it reads
-------------

`temporal_publication.calculated_view`'s two graph-derived blocks, and nothing
else:

* ``landmark_opportunities`` — Cut 5a's ``lo:<24 hex>`` rows: a named gap, the
  question generated FROM that gap (*"When did you move out of the Mesa
  house?"*), its ``leverage`` / ``resolves``, its ``domain``, its
  ``ladder_rung`` and its ``sensitivity``;
* ``keystones`` — Cut 3a's ``tl:<anchor-slug>`` rows: the greedy plan over the
  residual graph, each with the same ``leverage`` / ``resolves`` arithmetic.

Both are computed by the fold from ONE dependency graph, so a candidate here
carries no number this module invented.

The entry rule, exactly
-----------------------

A row becomes a candidate when **all four** hold:

1. ``leverage >= timeline_leverage_per_story`` — THE dial, imported from
   `question_planner.DEFAULT_LANE_POLICY` and never copied (§4.6: one base
   gain quantity feeds three hosts). 6 at this pin.
2. ``sensitivity != "offer_only"`` — losses are offered, never asked, however
   they score (§4.6, and `question_planner.is_loss_discovery` refuses the
   generic opener a second time downstream).
3. The identity is not already **answered, filed or open in the bank**. The
   bank is the answer-once ledger; a checked row is an answer, wherever it was
   given.
4. The identity is not **dismissed** by the owner. A human negative persists
   across rebuilds (:func:`dismiss`, `state/timeline_candidates.json`) —
   otherwise a rebuild would re-ask something a person said no to.

And the weight it carries once it is in the bank is the keystone rule,
unchanged: ``leverage / timeline_leverage_per_story``, in exactly the currency
`DEFAULT_LANE_POLICY["objective_boost"]` is quoted in.

The caps, and why they are small
--------------------------------

* :data:`LANDMARK_MINT_CAP` **= 1**. At most one LANDMARK-opportunity question
  is minted per queue build, on top of the keystone plan's own
  `timeline_gain.KEYSTONE_CAP` (2). Deliberately conservative: R2 opened a
  door that had been bolted shut, and the acceptance criterion beside it
  (§8.2.10) is *"ordinary gaps do not flood the queue"*. One is the smallest
  number that makes the door real.
* `question_planner.GROUP_CAPS["timeline"]` still bounds the WEEK at one
  timeline question however many candidates clear the bar. Minting is not
  asking.
* `arc_planner.DEFAULT_GAP_MAX` still bounds the whispers.

Identity, and why there is only one
-----------------------------------

A candidate's ``id`` is the row's OWN published id — ``lo:`` for an
opportunity, ``tl:`` for a keystone — both content-addressed over the gap, so
a rebuild asks under the same id. That id is written into the minted bank
row's ``timeline_probe:`` provenance comment, which is what
`timeline_interaction.timeline_probe_index` reads and what the whisper matches
on: the queue entry and the whisper are one thing, by construction.

Beside it rides the substrate's ``work_item_id``, resolved against the
projection's own items wherever the graph already holds one for the same gap,
so an answer on any surface closes the item on all of them
(`question_planner.close_answered_work_items`).

What Mirror gets (lifehug-platform#573's other half)
---------------------------------------------------

Nothing, deliberately, and by a mechanism that already existed. A
contradiction is Mirror work: `temporal_timeline.SURFACES_BY_KIND` never lists
`daily_question` for it, `timeline_gain.MIRROR_OWNED_KINDS` keeps it out of
the Timeline's own gain, and Mirror's daily convergence is deferred (decision
record §2.5, lifehug-platform#663). So the Mirror half of #573 needs no hook
here: when that convergence lands, a Mirror item widens its own surfaces and
walks through the same door, scored by the same components.

Answerability is the same mechanism read the other way: a gap the fold marked
as not for the daily question stays off it, this module never widens a
published item's ``allowed_surfaces``, and better wording never buys a
surface.

Pure where it can be: every vault read is guarded and degrades to "no timeline
questions this week", which is exactly the pre-R2 behaviour.

Controlling contract: `lifehug-platform
docs/decisions/2026-09-03-timeline-unification/decision-record.md` R2 and
§4.6; execution-plan.md §5b. Issues lifehug-platform#573, #586.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

from lifehug_core import (  # noqa: E402
    QUESTIONS_FILE,
    STATE_DIR,
    now_utc,
    read_json,
    read_text,
    write_json,
)

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

#: The provenance every candidate this module mints carries, into the bank row
#: and out onto the queue entry. One word, so a week's queue is readable: this
#: question came from the timeline's own measured gain, not from a classifier
#: follow-up or a wiki harvest.
PROVENANCE = "timeline-gain"

#: Which published block a candidate came from.
SOURCE_OPPORTUNITY = "landmark_opportunity"
SOURCE_KEYSTONE = "keystone"

#: §4.6's sensitivity value that is a REFUSAL rather than a weight.
OFFER_ONLY = "offer_only"

#: MIRROR's own kinds, re-exported from `timeline_gain` so this module names
#: them without redeclaring them. Nothing here ever mints one: a contradiction
#: is Mirror work, its `allowed_surfaces` never lists `daily_question`
#: (`temporal_timeline.SURFACES_BY_KIND`), and Mirror's daily convergence is
#: deferred (decision record §2.5, lifehug-platform#663). That is the whole of
#: #573's Mirror half in this cut: no hook, by the existing mechanism.
def _mirror_owned_kinds() -> tuple:
    try:
        from timeline_gain import MIRROR_OWNED_KINDS  # noqa: PLC0415

        return tuple(MIRROR_OWNED_KINDS)
    except Exception:  # noqa: BLE001
        return ("contradiction", "identity_uncertain")


MIRROR_OWNED_KINDS = _mirror_owned_kinds()

#: At most this many LANDMARK opportunities are minted per queue build, on top
#: of the keystone plan. See the module docstring — one, conservatively.
LANDMARK_MINT_CAP = 1

#: Pass as ``landmark_cap`` to lift it. The WHISPER lane uses it: its own cap
#: is `arc_planner.DEFAULT_GAP_MAX`, and there is deliberately no second dial
#: (v200's comment, unchanged) — the mint cap is about spending a DAY.
UNCAPPED = -1

#: Where an owner's "no" lives. A tiny file rather than a field on a candidate,
#: because a candidate is DERIVED every build and a human decision must not be.
DISMISSALS_FILE = STATE_DIR / "timeline_candidates.json"
DISMISSALS_VERSION = 1

#: What answering an opportunity of each kind SETTLES about its own node —
#: `question_planner.WORK_ITEM_PLACEMENT_GAIN`'s vocabulary, keyed by the
#: opportunity kind instead of the work-item kind. A missing BOUND places the
#: stay; the fold may hold the same node as a `precision_gap` (worth 0.4,
#: "sharpen a date we have"), and that is the wrong reading of a stay with no
#: end at all. An ambiguity keeps the fold's own number.
PLACEMENT_GAIN_BY_KIND = {
    "span_open_end": 0.8,
    "span_open_start": 0.8,
    "span_missing": 0.8,
    "birth_origin": 0.8,
    "relationship_anchor": 0.8,
}

#: research.md §4, hard, and `arc_planner.BANNED_PHRASE`'s own words: a whisper
#: never opens with a calendar year. Read from the planner so the two can never
#: become two rules.
def _banned_phrase() -> str:
    try:
        from arc_planner import BANNED_PHRASE  # noqa: PLC0415

        return str(BANNED_PHRASE).lower()
    except Exception:  # noqa: BLE001
        return "what year"


# --------------------------------------------------------------------------
# The dial — read, never copied
# --------------------------------------------------------------------------


def entry_threshold(policy: object = None) -> int:
    """``timeline_leverage_per_story`` — ONE definition, the queue's own.

    `landmark_opportunities.default_threshold` reads the same key for the same
    reason: §4.6 says one base gain quantity feeds three hosts, so the
    Timeline surface, this door and the queue's weight formula are all quoting
    the same number.
    """
    from question_planner import DEFAULT_LANE_POLICY  # noqa: PLC0415

    lane = dict(DEFAULT_LANE_POLICY)
    if isinstance(policy, dict):
        lane.update(policy)
    try:
        return int(lane["timeline_leverage_per_story"])
    except (KeyError, TypeError, ValueError):
        return int(DEFAULT_LANE_POLICY["timeline_leverage_per_story"])


# --------------------------------------------------------------------------
# Reading the served view
# --------------------------------------------------------------------------


def load_view(payload: object = None, *, vault_root: object = None) -> dict:
    """The served `calculated_view` block, or ``{}`` — GUARDED.

    Three shapes are accepted because three callers hold three of them: the
    assembled `timeline.timeline_data()` payload (``["calculated"]``), a view
    block on its own, and nothing at all — in which case the vault's published
    generation is read through the ONE root definition
    (`timeline._projection_vault_root`).
    """
    if isinstance(payload, dict):
        block = payload.get("calculated")
        if isinstance(block, dict):
            return block
        if "landmark_opportunities" in payload or "keystones" in payload:
            return payload
        return {}
    try:
        import temporal_publication  # noqa: PLC0415

        if vault_root is None:
            import timeline  # noqa: PLC0415

            vault_root = timeline._projection_vault_root()  # noqa: SLF001
        return temporal_publication.calculated_view(vault_root)
    except Exception:  # noqa: BLE001 — a projection problem is "no candidates"
        return {}


def view_has_projection(view: object) -> bool:
    """Does this view carry a graph the candidates could come from?

    The legacy keystone minter is the FALLBACK for a vault with no published
    projection (Cut 7b deletes it), and this is the predicate that chooses.
    ``published`` alone is not enough: a generation that predates Cut 3a
    carries neither block and has nothing to say about gain.
    """
    row = view if isinstance(view, dict) else {}
    return bool(row.get("landmark_opportunities") or row.get("keystones"))


# --------------------------------------------------------------------------
# The dismissal ledger (a human negative persists)
# --------------------------------------------------------------------------


def load_dismissals(path: object = None) -> dict:
    store = read_json(Path(path) if path else DISMISSALS_FILE, default=None)
    if not isinstance(store, dict):
        return {"version": DISMISSALS_VERSION, "dismissed": []}
    rows = [row for row in (store.get("dismissed") or ()) if isinstance(row, dict)]
    return {"version": int(store.get("version") or DISMISSALS_VERSION),
            "dismissed": rows}


def dismissed_ids(store: object = None, *, path: object = None) -> set:
    """Every identity the owner has said no to."""
    data = store if isinstance(store, dict) else load_dismissals(path)
    return {str(row.get("id") or "").strip()
            for row in (data.get("dismissed") or ())
            if str(row.get("id") or "").strip()}


def dismiss(identity: object, *, reason: object = "", now: object = None,
            path: object = None) -> dict:
    """Record an owner's no. Idempotent; never deletes the earlier record."""
    key = str(identity or "").strip()
    if not key:
        raise ValueError("a dismissal needs an identity")
    target = Path(path) if path else DISMISSALS_FILE
    store = load_dismissals(target)
    if key not in dismissed_ids(store):
        store["dismissed"].append({
            "id": key,
            "reason": str(reason or ""),
            "dismissed_at": str(now or now_utc()),
        })
        store["version"] = DISMISSALS_VERSION
        write_json(target, store)
    return store


def undismiss(identity: object, *, path: object = None) -> dict:
    """Lift a dismissal — the owner changed their mind."""
    key = str(identity or "").strip()
    target = Path(path) if path else DISMISSALS_FILE
    store = load_dismissals(target)
    kept = [row for row in store["dismissed"] if str(row.get("id") or "") != key]
    if len(kept) != len(store["dismissed"]):
        store["dismissed"] = kept
        write_json(target, store)
    return store


# --------------------------------------------------------------------------
# The bank, as the answer-once ledger
# --------------------------------------------------------------------------


def bank_candidate_ids(question_bank_text: object = None) -> set:
    """Every `lo:`/`tl:` identity the bank already holds — asked or answered.

    Read from the bank's OWN provenance comments through
    `timeline_interaction.timeline_probe_index`, so there is no second ledger
    of what has been asked. A CHECKED row counts: "answered, not deleted" is
    the whole of retire-on-answer, and an answered question is never re-asked.
    """
    text = read_text(QUESTIONS_FILE) if question_bank_text is None else str(question_bank_text)
    try:
        import timeline_interaction  # noqa: PLC0415

        index = timeline_interaction.timeline_probe_index(text)
    except Exception:  # noqa: BLE001
        return set()
    return {str(row.get("question_id") or "").strip()
            for row in index.values()
            if str(row.get("question_id") or "").strip()}


def bank_work_item_ids(question_bank_text: object = None) -> set:
    """Every substrate identity the bank already holds — asked or answered.

    The second half of "asked once, answered once": a row minted under a `tl:`
    keystone id and a row minted under an `lo:` opportunity id can be the SAME
    gap, and what proves it is the ``work_item:`` marker they both carry. A
    candidate whose substrate identity is already in the bank is refused here
    for the same reason `question_planner.queue_candidates` refuses it later —
    one question, however many names it has.
    """
    text = read_text(QUESTIONS_FILE) if question_bank_text is None else str(question_bank_text)
    try:
        from question_planner import bank_work_items  # noqa: PLC0415

        return set(bank_work_items(text))
    except Exception:  # noqa: BLE001
        return set()


# --------------------------------------------------------------------------
# The candidates
# --------------------------------------------------------------------------


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _opportunity_candidate(row: dict) -> dict | None:
    question = _text(row.get("question"))
    anchor = _text(row.get("subject"))
    identity = _text(row.get("id"))
    if not question or not anchor or not identity:
        return None
    return {
        "id": identity,
        "provenance": PROVENANCE,
        "source": SOURCE_OPPORTUNITY,
        "kind": _text(row.get("kind")),
        "question": question,
        "anchor": anchor,
        "label": _text(row.get("label")),
        "domain": _text(row.get("domain")),
        "ladder_rung": row.get("ladder_rung"),
        "leverage": int(row.get("leverage") or 0),
        "resolves": [r for r in (row.get("resolves") or ()) if isinstance(r, str)],
        "sensitivity": _text(row.get("sensitivity")) or "ordinary",
        "work_item_id": _text(row.get("work_item_id")),
    }


def _keystone_candidate(row: dict) -> dict | None:
    question = _text(row.get("question"))
    anchor = _text(row.get("anchor"))
    identity = _text(row.get("id"))
    if not question or not anchor or not identity:
        return None
    return {
        "id": identity,
        "provenance": PROVENANCE,
        "source": SOURCE_KEYSTONE,
        "kind": "keystone",
        "question": question,
        "anchor": anchor,
        "label": _text(row.get("label")) or anchor,
        "domain": "",
        "ladder_rung": None,
        "leverage": int(row.get("leverage") or 0),
        "resolves": [r for r in (row.get("resolves") or ()) if isinstance(r, str)],
        "sensitivity": "ordinary",
        "work_item_id": _text(row.get("work_item_id")),
    }


def candidates_from_view(view: object, *, policy: object = None,
                         question_bank_text: object = None,
                         dismissed: object = None,
                         landmark_cap: object = None) -> list[dict]:
    """The rows that pass the entry rule, opportunities first.

    Order is load-bearing twice. An OPPORTUNITY outranks a keystone about the
    same anchor because its question was generated from the named gap — *"When
    did you move out of the Mesa house?"* rather than the fold's own *"Do you
    know the year for the Mesa house?"* — and the two are the same question, so
    only one may be asked. Within each block the order is
    ``(-leverage, id)``, which is total, so a rebuild produces the same list.
    """
    row = view if isinstance(view, dict) else {}
    bar = entry_threshold(policy)
    refused = dismissed_ids() if dismissed is None else {str(d) for d in dismissed}
    known = bank_candidate_ids(question_bank_text)
    known_items = bank_work_item_ids(question_bank_text)
    if landmark_cap is None:
        cap = LANDMARK_MINT_CAP
    elif int(landmark_cap) < 0:
        cap = None
    else:
        cap = int(landmark_cap)

    opportunities = [_opportunity_candidate(r)
                     for r in (row.get("landmark_opportunities") or ())
                     if isinstance(r, dict)]
    keystones = [_keystone_candidate(r) for r in (row.get("keystones") or ())
                 if isinstance(r, dict)]

    def admitted(rows: list) -> list:
        out = []
        for candidate in rows:
            if candidate is None:
                continue
            if candidate["leverage"] < bar:
                continue                      # below_threshold
            if candidate["sensitivity"] == OFFER_ONLY:
                continue                      # offer_only, §4.6
            if candidate["id"] in refused:
                continue                      # dismissed_by_owner
            if candidate["id"] in known:
                continue                      # already_asked / already_answered
            if candidate["work_item_id"] and candidate["work_item_id"] in known_items:
                continue                      # the same gap, under its other name
            out.append(candidate)
        out.sort(key=lambda c: (-c["leverage"], c["id"]))
        return out

    chosen: list[dict] = []
    seen_anchors: set = set()

    for candidate in (admitted(opportunities) if cap is None
                      else admitted(opportunities)[:cap]):
        chosen.append(candidate)
        seen_anchors.add(candidate["anchor"])
        if candidate["work_item_id"]:
            seen_anchors.add(candidate["work_item_id"])
    for candidate in admitted(keystones):
        if candidate["anchor"] in seen_anchors or (
                candidate["work_item_id"] and candidate["work_item_id"] in seen_anchors):
            continue
        chosen.append(candidate)
    return chosen


def whisper_gaps(view: object, *, policy: object = None,
                 question_bank_text: object = None,
                 dismissed: object = None) -> list[dict]:
    """The same candidates, shaped as `arc_planner` gap rows.

    The whisper and the queue entry are ONE thing (#586): same id, same
    question, same leverage. Two rules are applied here and nowhere else,
    because they are about the whisper surface rather than about the item:

    * a question containing `arc_planner.BANNED_PHRASE` never becomes a
      whisper (research.md §4 — landmark anchors, never a calendar year). The
      ladder is allowed to ask a sibling's birth year outright as the DAY's
      question; a conversational aside is not.
    * the landmark cap does not apply — `arc_planner.DEFAULT_GAP_MAX` is the
      whisper lane's own cap and there is deliberately no second dial.
    """
    banned = _banned_phrase()
    rows = candidates_from_view(view, policy=policy,
                                question_bank_text=question_bank_text,
                                dismissed=dismissed, landmark_cap=UNCAPPED)
    gaps = []
    for candidate in rows:
        if banned and banned in candidate["question"].lower():
            continue
        gaps.append({
            "kind": PROVENANCE,
            "period": None,
            "message": candidate["label"] or candidate["question"],
            "hint": "the gap the graph named; any precision places it",
            "leverage": candidate["leverage"],
            "unknown_key": candidate["anchor"],
            "anchor": candidate["anchor"],
            "anchors": [],
            "question_id": candidate["id"],
            "probe": {"text": candidate["question"], "step": ""},
            "provenance": PROVENANCE,
            "label": candidate["label"] or candidate["question"],
            "work_item_id": candidate["work_item_id"],
            "domain": candidate["domain"],
        })
    return gaps


# --------------------------------------------------------------------------
# Candidates -> work items (the seam the keystone lane already used)
# --------------------------------------------------------------------------


def _published_index(items: object) -> tuple[dict, dict]:
    by_id: dict = {}
    by_ref: dict = {}
    for item in items or ():
        if not isinstance(item, dict):
            continue
        identity = _text(item.get("work_item_id"))
        if identity:
            by_id.setdefault(identity, item)
        for key in ("node_ref", "event_ref", "subject_ref"):
            ref = _text(item.get(key))
            if ref:
                by_ref.setdefault(ref, item)
    return by_id, by_ref


def as_candidate(row: object) -> dict | None:
    """One PUBLISHED row or one candidate record -> a candidate record.

    Tolerant on purpose: the fold hands over `landmark_opportunities` and
    `keystones` in their published shapes, :func:`candidates_from_view` hands
    over records, and a host debugging one holds whichever it has. Read the
    shape, not the type.
    """
    if not isinstance(row, dict):
        return None
    if row.get("provenance") == PROVENANCE and row.get("anchor"):
        return dict(row)
    if row.get("subject"):
        return _opportunity_candidate(row)
    if row.get("anchor"):
        return _keystone_candidate(row)
    return None


def _keystone_payload(candidate: dict) -> dict:
    """The keystone-shaped row `mint_work_item_question` mints from.

    ``question_id`` is the candidate's OWN id, which is how a `lo:` opportunity
    reaches the bank under its own identity through the one row minter
    (`timeline_interaction.mint_keystone_question`) rather than a second one.
    """
    return {
        "anchor": candidate["anchor"],
        "question_id": candidate["id"],
        "label": candidate["label"] or candidate["anchor"],
        "leverage": int(candidate["leverage"]),
        "probe": {"text": candidate["question"], "step": ""},
        "unknown_keys": list(candidate["resolves"]),
        "anchors": [],
        "provenance": PROVENANCE,
    }


def work_items(candidates: object, *, published: object = (),
               now: object = None) -> list[dict]:
    """Candidates -> validated work items, carrying BOTH identities.

    A candidate whose gap the projection ALREADY holds an item for reuses that
    item — same ``work_item_id``, same claim refs — and only overrides what the
    opportunity knows better: the wording, the placement gain, and the `lo:`
    identity it will be asked under. That is the whole of "one question, one
    identity, every surface": an answer on the Timeline row closes the queue
    entry, because they were never two items.

    A candidate with no such item is adapted through
    `question_planner.work_item_from_keystone`, the same door v196's keystones
    have always used.
    """
    try:
        import question_planner as qp  # noqa: PLC0415
        import temporal_projection  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return []
    by_id, by_ref = _published_index(published)
    stamp = str(now or now_utc())
    rows: list[dict] = []
    for row in candidates or ():
        candidate = as_candidate(row)
        if candidate is None:
            continue
        base = by_id.get(candidate.get("work_item_id") or "") or by_ref.get(
            candidate.get("anchor") or "")
        item = None
        if isinstance(base, dict):
            payload = dict(base)
            payload["state"] = "open"
            payload["prompt_intent"] = candidate["question"]
            # ANSWERABILITY, and it is the substrate's call, not this module's
            # (§4.6's host-specific safeguards; §2.4's own mechanism). The base
            # item's `allowed_surfaces` is deliberately left ALONE: a gap the
            # fold marked as not for the daily question — a witness-supplied
            # fact, a Mirror-owned contradiction, a loss opener — stays off it,
            # and `question_planner.queue_candidates` refuses it by name
            # (`surface_not_allowed`). Better wording never buys a surface.
            payload.setdefault("created_at", stamp)
            try:
                item = temporal_projection.validate_temporal_work_item(payload, now=stamp)
            except Exception:  # noqa: BLE001 — one bad row never hides the rest
                item = None
        if item is None:
            item = qp.work_item_from_keystone(
                {**_keystone_payload(candidate),
                 "anchor_kind": ("birth" if candidate.get("kind") == "birth_origin"
                                 else None)},
                now=stamp,
            )
        if not isinstance(item, dict):
            continue
        item["keystone"] = _keystone_payload(candidate)
        item["downstream_reach"] = int(candidate["leverage"])
        if int(candidate["leverage"]) > 0:
            # §4.6, one base gain quantity: this item is being asked BECAUSE of
            # the leverage Cut 3a measured for the gap, so the reach component
            # is that number normalized against the one dial. A base row's own
            # `system_value` was normalized for a different question about the
            # same node (a precision gap on a stay that has no bound at all)
            # and would otherwise be scored beside a reach that contradicts it.
            item.pop("system_value", None)
        item["resolves"] = list(candidate["resolves"])
        item["provenance"] = PROVENANCE
        item["timeline_candidate_id"] = candidate["id"]
        item["timeline_candidate_source"] = candidate["source"]
        if candidate.get("domain"):
            item["landmark_domain"] = candidate["domain"]
        if candidate.get("ladder_rung"):
            item["ladder_rung"] = candidate["ladder_rung"]
        gain = PLACEMENT_GAIN_BY_KIND.get(str(candidate.get("kind") or ""))
        if gain is not None:
            item["placement_gain"] = gain
        if candidate["sensitivity"] == OFFER_ONLY:
            item["offer_only"] = True
        rows.append(item)
    return rows


def from_view(view: object = None, *, payload: object = None, policy: object = None,
              question_bank_text: object = None, now: object = None) -> list[dict]:
    """The whole path in one call: served view -> queue-ready work items."""
    block = view if isinstance(view, dict) else load_view(payload)
    if not view_has_projection(block):
        return []
    rows = candidates_from_view(block, policy=policy,
                                question_bank_text=question_bank_text)
    return work_items(rows, published=block.get("work_items") or (), now=now)


# --------------------------------------------------------------------------
# Retire on answer
# --------------------------------------------------------------------------


def _match_key(value: object) -> str:
    try:
        from temporal_claims import normalized_mention_key  # noqa: PLC0415

        return normalized_mention_key(value)
    except Exception:  # noqa: BLE001
        return _text(value).lower()


def identities_for_landmark(domain: object, record: object, *,
                            view: object = None) -> list[str]:
    """Which published identities a filed landmark answers.

    Matched on the OPPORTUNITY's own published fields — its ``domain`` and the
    subject it names — against the record that was just filed, because the
    projection at this moment still holds the opportunity (the republish that
    removes it has not run yet). A ``none`` terminal, which names no subject,
    answers every open opportunity in its domain: that is what "there were
    none" means.

    Keystones ride along: a keystone whose anchor is the matched
    opportunity's subject is the same gap under the fold's own name.
    """
    block = view if isinstance(view, dict) else load_view()
    row = record if isinstance(record, dict) else {}
    key = _text(domain)
    if not key:
        return []
    wanted = {_match_key(row.get(field))
              for field in ("label", "city", "name", "what", "who", "subject", "place")
              if _match_key(row.get(field))}
    terminal = bool(row.get("none"))
    matched: list[str] = []
    anchors: set = set()
    for opportunity in block.get("landmark_opportunities") or ():
        if not isinstance(opportunity, dict) or _text(opportunity.get("domain")) != key:
            continue
        label = _match_key(opportunity.get("label"))
        if not terminal and wanted and label and label not in wanted:
            continue
        identity = _text(opportunity.get("id"))
        if identity:
            matched.append(identity)
            anchors.add(_text(opportunity.get("subject")))
    for keystone in block.get("keystones") or ():
        if not isinstance(keystone, dict):
            continue
        if _text(keystone.get("anchor")) in anchors:
            identity = _text(keystone.get("id"))
            if identity:
                matched.append(identity)
    return matched


def retire_identities(identities: object, *, question_bank_text: object = None,
                      answered_date: object = None) -> list[str]:
    """Check off the bank rows carrying these identities. Answered, not deleted.

    Returns the bank ids that changed. Pure when ``question_bank_text`` is
    injected (nothing is written), exactly as `question_planner`'s minting seam
    is, so a test never touches the checkout's own bank.
    """
    wanted = {str(i).strip() for i in (identities or ()) if str(i).strip()}
    if not wanted:
        return []
    text = read_text(QUESTIONS_FILE) if question_bank_text is None else str(question_bank_text)
    try:
        import timeline_interaction  # noqa: PLC0415

        index = timeline_interaction.timeline_probe_index(text)
    except Exception:  # noqa: BLE001
        return []
    retired = [bank_id for bank_id, row in index.items()
               if _text(row.get("question_id")) in wanted and not row.get("answered")]
    if not retired or question_bank_text is not None:
        return retired
    try:
        from lifehug_core import mark_answered_in_bank  # noqa: PLC0415

        for bank_id in retired:
            mark_answered_in_bank(bank_id, str(answered_date) if answered_date else None)
    except Exception:  # noqa: BLE001 — a bank problem never breaks a landmark write
        return []
    return retired


def retire_for_landmark(domain: object, record: object, *, view: object = None,
                        question_bank_text: object = None,
                        answered_date: object = None) -> list[str]:
    """The seam `timeline.save_landmark` calls — GUARDED, best effort.

    A landmark filed through the recorder, through `landmark-record`, through
    Add Landmark's apply (Cut 6a) or as a ``none`` all reach the ONE writer,
    so hooking the writer is the whole of decision-record §5.4's *"the filed
    landmark retires the matching open question from the queue"*.
    """
    try:
        identities = identities_for_landmark(domain, record, view=view)
        return retire_identities(identities, question_bank_text=question_bank_text,
                                 answered_date=answered_date)
    except Exception:  # noqa: BLE001
        return []


# --------------------------------------------------------------------------
# CLI — small on purpose: inspect what would be minted, and record an owner no
# --------------------------------------------------------------------------


def _print_candidates(rows: list[dict]) -> None:
    if not rows:
        print("no timeline-gain candidates above the threshold")
        return
    for row in rows:
        print(f"- {row['id']} [{row['source']}] leverage {row['leverage']}"
              f"{' · ' + row['domain'] if row['domain'] else ''}\n  {row['question']}")


def main(argv: object = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true",
                        help="show the candidates this vault would mint")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dismiss", metavar="ID",
                        help="record an owner's no for a lo:/tl: identity")
    parser.add_argument("--undismiss", metavar="ID")
    parser.add_argument("--reason", default="")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.dismiss:
        dismiss(args.dismiss, reason=args.reason)
        print(f"✓ dismissed {args.dismiss}")
        return 0
    if args.undismiss:
        undismiss(args.undismiss)
        print(f"✓ un-dismissed {args.undismiss}")
        return 0

    rows = candidates_from_view(load_view())
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True))
    else:
        _print_candidates(rows)
    return 0


__all__ = [
    "DISMISSALS_FILE",
    "MIRROR_OWNED_KINDS",
    "LANDMARK_MINT_CAP",
    "OFFER_ONLY",
    "PLACEMENT_GAIN_BY_KIND",
    "PROVENANCE",
    "SOURCE_KEYSTONE",
    "SOURCE_OPPORTUNITY",
    "bank_candidate_ids",
    "candidates_from_view",
    "dismiss",
    "dismissed_ids",
    "entry_threshold",
    "from_view",
    "identities_for_landmark",
    "load_dismissals",
    "load_view",
    "retire_for_landmark",
    "retire_identities",
    "undismiss",
    "view_has_projection",
    "whisper_gaps",
    "work_items",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
