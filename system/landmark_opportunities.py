#!/usr/bin/env python3
"""Landmark opportunities and sufficiency from the CALCULATED graph (Cut 5a).

The defect this closes is the Codex audit's **F7**. `Landmarks.tsx` reads the
legacy domain rows, filters on ``status != complete``, and says *"Your
landmarks are all filled in"* the moment nine ladders are full. That is a
checklist, not a measurement: it privileges a domain whose remaining questions
are worth nothing, and it hides a newly high-value anchor behind a ladder that
looks finished. Owner ruling **R2** (2026-09-03) replaces completion with
sufficiency:

    *A landmark domain leaves the privileged surface when its remaining
    questions have low marginal placement value, not when every field is
    filled.*

So this module answers two questions from the projection the fold already
publishes, and neither of them is "is the ladder full":

1. **What are the concrete gaps the graph can name?** A residence, job or
   school stay whose interval is open or missing; the birth origin; a person
   the ladder enumerates with no dated anchor; an episode the containment rung
   found ambiguous. Each is an *opportunity*: a subject, a leverage, the node
   ids it would place, and a question generated from the actual gap.
2. **Which domains still deserve a privileged surface?** A domain whose best
   remaining opportunity does not clear the shared value threshold is
   ``sufficient``: it publishes no opportunities and the surface may collapse.

**Nothing here is a reminder, a nag, or a count.** A sufficient domain is
silent; an answered question never regenerates (the identity is
content-addressed over the gap, and a filled gap is not a gap); losses are
offer-only and never produce an unprompted opportunity.

One base quantity, three hosts (decision record §4.6)
------------------------------------------------------

The leverage on an opportunity is **not a new metric**. It is
`timeline_gain.item_gain` — Cut 3a's ``resolves`` / ``leverage = 1 +
len(resolves)`` — read off the SAME ``dependency_index`` the Needs Placing
rows are ranked by, for the anchor the opportunity would supply. The threshold
is the queue's own dial, `question_planner.DEFAULT_LANE_POLICY`'s
:data:`THRESHOLD_DIAL`, read through :func:`default_threshold` so the Timeline
surface and the daily queue cannot drift apart. There is one definition of the
number and one definition of the bar.

The six question-generation rules
--------------------------------

An opportunity's question is generated from the gap, never from a template
about nothing — the F7 sentence is *"never 'When did this part begin?'"*:

* **R-Q1 open end.** A participation episode with a start and no end asks the
  bound it is missing, in the domain's own words: *"When did you move out of
  the Mesa house?"* (:data:`SPAN_END_TEXTS`).
* **R-Q2 open start.** The mirror image (:data:`SPAN_START_TEXTS`).
* **R-Q3 no interval at all.** The ladder's OWN ``span`` rung, verbatim from
  `landmarks_interaction.EVENT_QUESTION_TEXTS`, because a rung exists and it
  already names both bounds and the subject.
* **R-Q4 no birth origin.** The birth ladder's own rung, because a birthday
  is the one question whose subject is the person being asked. The anchor is
  `timeline_gain.origin_anchor`, so the leverage is exactly the reach the
  fold's D3 rule measured: nothing else in the graph reaches as far.
* **R-Q5 a person with no dated anchor.** `landmarks_interaction.
  event_questions` for the first event the domain dates that the entry has
  not answered — *"When did you and Katie first meet?"*, *"What year was
  {label} born?"*, *"Roughly when did you lose {label}?"*. The name is the
  ROSTER's display name when the roster knows the person, so the question
  calls them what everyone else calls them.
* **R-Q6 an ambiguous episode.** The work item's own ``prompt_intent``, which
  `temporal_timeline.compose_place_ambiguity_question` already wrote naming
  the place and both stays (*"which time in Phoenix — 1988–1990 or
  1996–1999?"*). Reused, never re-composed.

Deliberately NOT opportunity kinds
----------------------------------

* **A bound that exists but is coarse.** "About 1990" is a `precision_gap`,
  which the fold already mints as a Timeline-owned work item carrying Cut 3a's
  leverage. Minting a second identity for it here would be the *one question
  asked twice* defect the substrate exists to prevent (ADR 0030, D2). A
  landmark opportunity is about a bound that is MISSING.
* **A chain gap** — a stretch of years no residence, job or school covers. It
  is `chain_gap`, another Timeline-owned kind with its own identity and its
  own composed question (E-L2c), ranked beside everything else by Cut 3a. A
  chain the person closed *for now* is skipped by ROUTINE prompting only
  (`landmarks_interaction.chain_is_closed`), and the gaps stay drawn — which
  is why closure records are not read here either.
* **A rung whose answer would be a name.** See below.

**An opportunity always names its subject.** A rung whose answer would BE the
name (``who``, ``city``, ``what``) is deliberately not an opportunity: it has
no anchor in the graph, so it has no measurable leverage, and asking it is the
ladder's business rather than the timeline's. That boundary is what keeps
"When did this part begin?" unrepresentable here.

Pure: plain data in, plain data out. No vault, no clock, no model. The fold
hands it the projection it has just computed; a test hands it a hand-written
one.

Controlling contract: `lifehug-platform
docs/decisions/2026-09-03-timeline-unification/decision-record.md` R2, §4.4,
§4.6 and §7 Cut 5; execution-plan.md §5a. ADR 0032.
"""

from __future__ import annotations

import sys
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import identity_resolution as ident  # noqa: E402
import landmark_projection as lp  # noqa: E402
import landmarks_interaction as li  # noqa: E402
import temporal_work_items as twi  # noqa: E402
import timeline_gain as tg  # noqa: E402
from temporal_claims import (  # noqa: E402
    TemporalContractError,
    collapsed_text,
    digest_id,
    normalized_mention_key,
)

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

#: The id namespace. ``lo:<24 hex>`` over the canonical JSON of the GAP —
#: domain, kind, subject, event — through the substrate's one id derivation
#: (`temporal_claims.digest_id`, the same function behind `node:` and
#: `work:`), for the same reason the keystone's ``tl:`` slug is derived from
#: its anchor: a rebuild must produce the same id, and an id must not move
#: when the leverage or the wording moves.
OPPORTUNITY_ID_PREFIX = "lo"

#: THE DIAL, by name. It lives in `question_planner.DEFAULT_LANE_POLICY` and
#: it is the queue's exchange rate — *how many timeline unknowns one answer
#: must place to be worth one ordinary story answer* (v196, value 6). §4.6
#: says one base gain quantity feeds three hosts, so the Timeline surface
#: reads the queue's number rather than declaring a second one.
#: :func:`default_threshold` is the only reader; `tests/
#: test_landmark_opportunities.py` pins the two to one definition.
THRESHOLD_DIAL = "timeline_leverage_per_story"

#: What kind of gap an opportunity is. Each is something the GRAPH can name,
#: which is what makes the question specific.
OPPORTUNITY_KINDS = (
    "span_open_end",       # a stay with a start and no end
    "span_open_start",     # a stay with an end and no start
    "span_missing",        # a stay with no interval at all
    "birth_origin",        # no birthday; the coordinate system is missing
    "relationship_anchor",  # a person the ladder enumerates with no date
    "ambiguous_episode",   # two stays, and nobody knows which one
)

#: The kinds the DEPENDENCY GRAPH names by itself — a bound, an origin, an
#: ambiguity — as opposed to :data:`LADDER_KINDS`, which the specificity
#: ladder names. The split is load-bearing exactly once, in
#: :func:`sufficiency`: declaring a list finished closes a LIST, never a
#: graph. See that function.
GRAPH_KINDS = ("span_open_end", "span_open_start", "span_missing",
               "birth_origin", "ambiguous_episode")

#: The kinds the ladder names: a subject it enumerates whose date nobody gave.
LADDER_KINDS = ("relationship_anchor",)

#: Sensitivity, which never changes structural gain and only changes whether
#: and how a question may be surfaced (§4.6). ``offer_only`` is the losses
#: rule: never unprompted, shown only when the person raises the subject.
SENSITIVITY_OFFER_ONLY = "offer_only"
SENSITIVITY_ORDINARY = "ordinary"

#: Why a domain is (or is not) sufficient. A reason is published so the
#: collapse of a surface is checkable rather than mysterious.
REASON_OPEN = "open_opportunity"           # not sufficient: something clears the bar
REASON_BELOW_THRESHOLD = "below_threshold"  # the best remaining gap is not worth a surface
REASON_NOTHING_REMAINING = "nothing_remaining"  # the graph names no gap at all
REASON_LIST_FINISHED = "list_declared_finished"  # a closed list the person closed
REASON_OFFER_ONLY = "offer_only"           # sensitive, and the subject was not raised

SUFFICIENCY_REASONS = (
    REASON_OPEN,
    REASON_BELOW_THRESHOLD,
    REASON_NOTHING_REMAINING,
    REASON_LIST_FINISHED,
    REASON_OFFER_ONLY,
)

#: ``episode event kind -> landmark domain``, INVERTED from
#: `landmark_projection.PARTICIPATION_EPISODE_KINDS` rather than written out a
#: second time (ADR 0021: one definition, many readers). A fifth span domain
#: therefore lands here for free.
DOMAIN_BY_EPISODE_KIND = {
    kind: domain for domain, kind in lp.PARTICIPATION_EPISODE_KINDS.items()
}

#: R-Q1. The missing END of a stay, in the domain's own verb. These are not in
#: `landmarks_interaction.RUNG_TEXTS` because the ladder has no rung for half a
#: span: its ``span`` rung asks for both bounds at once, and asking a person
#: who already told us they moved in in 1990 "when did you move in and when did
#: you leave" is asking for something they have already given.
SPAN_END_TEXTS = {
    "residences": "When did you move out of {label}?",
    "work": "When did you leave {label}?",
    "schools": "When did you finish at {label}?",
    "military": "When did you come out of the {label}?",
}

#: R-Q2. The mirror image: the stay is closed at the far end and open at the
#: near one.
SPAN_START_TEXTS = {
    "residences": "When did you move into {label}?",
    "work": "When did you start at {label}?",
    "schools": "When did you start at {label}?",
    "military": "When did you go into the {label}?",
}

#: The two ambiguity kinds the containment rung mints, and the domain each one
#: is a question about. `place_ambiguous` is a PLACE, which is residences;
#: `tenure_ambiguous` is an organization, which the fold's own comment says is
#: work or schools — :func:`_ambiguity_domain` separates those two by asking
#: which domain's filed entries the item's sentence actually names, and falls
#: back to ``work``.
AMBIGUITY_KINDS = ("place_ambiguous", "tenure_ambiguous")

#: The rungs whose answer IS the subject's name. They are never opportunities:
#: see the module docstring. Derived per domain by
#: `landmarks_interaction.identity_rung`, so this tuple is only the two
#: openers that are not identity rungs and still name nobody.
NON_SUBJECT_RUNGS = ("happened",)


class LandmarkOpportunityError(TemporalContractError):
    """A refusal from this module."""


# --------------------------------------------------------------------------
# The dial
# --------------------------------------------------------------------------


def default_threshold() -> int:
    """The queue's own :data:`THRESHOLD_DIAL`, read from ONE definition.

    Imported lazily and by name: `question_planner` reaches back into the
    temporal substrate for its own work-item scoring, so a module-level import
    here would be a cycle — and reading the number rather than copying it is
    the whole point of §4.6's *one base gain quantity*.
    """
    from question_planner import DEFAULT_LANE_POLICY  # noqa: PLC0415

    return int(DEFAULT_LANE_POLICY[THRESHOLD_DIAL])


def _threshold(value: object) -> int:
    if value is None:
        return default_threshold()
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise LandmarkOpportunityError(
            "threshold_not_a_number", f"threshold must be a number, got {value!r}"
        ) from exc


# --------------------------------------------------------------------------
# Reading what the fold handed over
# --------------------------------------------------------------------------


def _projection_parts(projection: object) -> tuple[list, list, dict]:
    """``(nodes, work_items, dependency_index)`` from anything shaped like one.

    A `temporal_timeline.CalculatedTimeline`, its ``to_dict()``, the published
    projection payload, and `temporal_publication.calculated_view`'s block all
    carry these three under the same names, so this reads the names rather
    than the type — the tolerant-by-construction discipline the rest of the
    package publishes with.
    """
    row = projection.to_dict() if hasattr(projection, "to_dict") else projection
    if not isinstance(row, dict):
        return [], [], {}
    nodes = [n for n in (row.get("nodes") or ()) if isinstance(n, dict)]
    items = [i for i in (row.get("work_items") or ()) if isinstance(i, dict)]
    index = row.get("dependency_index")
    index = dict(index) if isinstance(index, dict) else {}
    return nodes, items, index


def _domains_state(landmarks_state: object) -> dict:
    """``{domain: [entry, ...]}`` from the ladder store or its file shape.

    Accepts ``timeline.load_landmarks()``' mapping, or
    `landmark_projection.project_landmark_entries`' whole
    ``{"version", "domains"}`` file, because the fold holds the second and a
    host holds the first and they are the same fact.
    """
    row = landmarks_state if isinstance(landmarks_state, dict) else {}
    if isinstance(row.get("domains"), dict):
        row = row["domains"]
    return {
        str(domain): [e for e in (entries or ()) if isinstance(e, dict)]
        for domain, entries in row.items()
        if isinstance(entries, (list, tuple))
    }


def _roster_names(roster: object) -> dict:
    """``{normalized mention key: display name}`` over every roster handed in.

    Accepts one snapshot, a sequence of snapshots (`lifehug` passes a list), a
    built `identity_resolution.RosterIndex`, or a bare ``{ref: name}`` map.
    Degrades to ``{}``: a roster problem is *no roster*, never a broken
    projection.
    """
    snapshots: list = []
    if isinstance(roster, ident.RosterIndex) or isinstance(roster, dict):
        snapshots = [roster]
    elif roster:
        snapshots = [row for row in roster if row]
    names: dict = {}
    for snapshot in snapshots:
        if isinstance(snapshot, dict) and "entities" not in snapshot:
            # A bare `{ref: name}` map — what `_roster_names` in the fold
            # produces and what a test finds cheapest to write.
            for ref, name in snapshot.items():
                key = normalized_mention_key(name) or normalized_mention_key(ref)
                if key:
                    names.setdefault(key, collapsed_text(name) or collapsed_text(ref))
            continue
        try:
            index = ident.roster_index(snapshot)
        except TemporalContractError:
            continue
        for table in (index.by_name_key, index.by_alias_key):
            for key, refs in table.items():
                for ref in refs or ():
                    display = index.name_of(ref)
                    if key and display:
                        names.setdefault(key, display)
    return names


def _display_name(label: object, names: dict) -> str:
    """The roster's name for this label, or the label as the person wrote it."""
    text = collapsed_text(label)
    if not text:
        return ""
    return names.get(normalized_mention_key(text), text)


# --------------------------------------------------------------------------
# The gain — REUSED from Cut 3a, never recomputed
# --------------------------------------------------------------------------


def gain_for(anchor: object, index: object) -> tuple[list, int]:
    """``(resolves, leverage)`` for the anchor this opportunity would supply.

    Literally `timeline_gain.item_gain` over a one-field item, so the number
    on a landmark opportunity and the number on the Needs Placing row that
    shares its anchor are the same arithmetic over the same graph. Self
    inclusive: an anchor that places nothing else is exactly ``1``.
    """
    return tg.item_gain({"node_ref": collapsed_text(anchor)}, index)


def opportunity_id(*, domain: object, kind: object, subject: object,
                   event: object = None) -> str:
    """``lo:<24 hex>`` over the GAP — stable across rebuilds by construction.

    The payload is deliberately only what makes this gap this gap. Leverage,
    wording, ladder rung and the projection generation are all out: a
    republished projection that reworded a question must not retire and re-mint
    the person's open question, and a gap whose leverage grew is the same gap.
    """
    return digest_id(OPPORTUNITY_ID_PREFIX, {
        "domain": collapsed_text(domain),
        "kind": collapsed_text(kind),
        "subject": collapsed_text(subject),
        "event": collapsed_text(event) or None,
    })


# --------------------------------------------------------------------------
# The ladder, read per entry
# --------------------------------------------------------------------------


def _rows_by_domain(framework_root: object = None) -> dict:
    return {row["domain"]: row for row in li.load_questions(framework_root)}


def _entry_next_rung(entry: dict, row: dict) -> str | None:
    """The next rung THIS entry is missing, or ``None`` when it has reached
    ``complete_at``.

    `landmarks_interaction.next_rung` walks a whole domain and then falls
    through to the closure question; an opportunity is about one subject, so
    this asks the ladder about one entry and stops at the target rung.
    """
    ladder = list(row.get("ladder") or ())
    if not ladder:
        return None
    target = row.get("complete_at")
    target_index = ladder.index(target) if target in ladder else len(ladder) - 1
    reached = li.rung_reached(entry, row)
    index = ladder.index(reached) if reached in ladder else -1
    if index >= target_index:
        return None
    return ladder[index + 1]


def _entry_label(entry: dict, row: dict, names: dict) -> str:
    """What this entry's subject is CALLED — the roster's word where it has one."""
    named = li.identity_named(entry, row) or entry.get("label") or entry.get("name")
    return _display_name(named, names)


def _has_any_date(entry: dict) -> bool:
    """Does this entry carry a date of any grain, under any of its spellings?

    `landmark_projection` writes the reconciled winner to ``date`` or
    ``span`` (and its losers to the ``*_alternates`` keys), and the recorder
    may write a per-event key straight from the domain's own
    ``date_semantics``. All of them mean the same thing here: somebody has
    already anchored this subject.
    """
    for key in ("date", "span", li.DATE_ALTERNATES_KEY, li.SPAN_ALTERNATES_KEY):
        if entry.get(key):
            return True
    return any(entry.get(event) for event in li.DATE_SEMANTICS)


def _list_declared_finished(entries: list, row: dict) -> bool:
    """Has the person said this list is finished?

    `status_for_domain`'s own closure test, read on its own: an explicit
    ``chain_complete``, or the none terminal (*"I never served"* finishes the
    military domain the way one tour does).
    """
    return any(entry.get("chain_complete") or li.is_none_entry(entry, row)
               for entry in entries)


def _domain_is_closable(row: dict) -> bool:
    """A closed list: one the person declares finished, or one that accepts a
    ``none`` terminal. Both keep their finishable semantics under R2."""
    return bool(li.requires_declared_closure(row) or li.domain_accepts_none(row))


# --------------------------------------------------------------------------
# The four families of candidate (R-Q1..R-Q6)
# --------------------------------------------------------------------------


def _episode_interval(node: dict) -> object:
    """The stay's own interval record, or ``None``.

    A participation episode's interval is its ``best_temporal_value`` (built by
    `episode_containers.span_from_claims`, which spells an unfinished stay
    ``1990/..``). ``definition_span`` is read too, because an age frame and any
    later span-shaped node carry theirs there.
    """
    value = node.get("best_temporal_value")
    if isinstance(value, dict):
        return value
    span = node.get("definition_span")
    if isinstance(span, dict):
        start = span.get("start") if isinstance(span.get("start"), dict) else None
        end = span.get("end") if isinstance(span.get("end"), dict) else None
        if start is None and end is None:
            return None
        return {
            "best": None,
            "earliest": (start or {}).get("earliest"),
            "latest": (end or {}).get("latest"),
        }
    return None


def _open_bound(node: dict) -> str | None:
    """Which bound of this stay is open: ``"end"``, ``"start"``, ``"both"``, or
    ``None`` when the person has given both.

    ``life_clip_end: "present"`` is the one exemption and it is not a guess:
    the fold stamps it on a clip that runs to today, and *"when did you move
    out"* is not a question about a house somebody still lives in.
    """
    if collapsed_text(node.get("life_clip_end")) == "present":
        return None
    value = _episode_interval(node)
    if value is None:
        return "both"
    best = collapsed_text(value.get("best"))
    has_start = bool(collapsed_text(value.get("earliest"))) and not best.startswith("../")
    has_end = bool(collapsed_text(value.get("latest"))) and not best.endswith("/..")
    if has_start and has_end:
        return None
    if has_start:
        return "end"
    if has_end:
        return "start"
    return "both"


def _span_candidates(nodes: list, index: dict, rows: dict, names: dict) -> list:
    """R-Q1/R-Q2/R-Q3 — every participation episode with a bound the graph wants.

    Driven off the NODES, not off the ladder, and that is the whole of F7's
    first half: a residence ladder can be complete (`span` reached, because
    the entry carries a span) while the stay it drew is open at one end and
    five events are sitting inside it holding a window.
    """
    found = []
    for node in nodes:
        event_kind = collapsed_text(node.get("event_kind"))
        domain = DOMAIN_BY_EPISODE_KIND.get(event_kind)
        row = rows.get(domain)
        if row is None:
            continue
        node_id = collapsed_text(node.get("node_id"))
        if not node_id:
            continue
        label = _display_name(node.get("label"), names)
        if not label:
            # An opportunity always names its subject; an unlabelled stay has
            # nothing to put in the sentence.
            continue
        bound = _open_bound(node)
        if bound is None:
            continue
        if bound == "end":
            kind, text = "span_open_end", SPAN_END_TEXTS.get(domain)
        elif bound == "start":
            kind, text = "span_open_start", SPAN_START_TEXTS.get(domain)
        else:
            kind = "span_missing"
            text = li.EVENT_QUESTION_TEXTS.get((domain, "span"))
        if not text:
            continue
        resolves, leverage = gain_for(node_id, index)
        found.append(_opportunity(
            domain=domain, kind=kind, subject=node_id, subject_kind="episode",
            label=label, question=text.format(label=label), ladder_rung="span",
            row=row, resolves=resolves, leverage=leverage,
        ))
    return found


def _birth_candidate(state: dict, index: dict, rows: dict, owner: str) -> list:
    """R-Q4 — no birthday, so no age statement lands anywhere.

    The anchor is `timeline_gain.origin_anchor` — the one anchor ref with no
    node of its own — so the leverage here is exactly the reach the fold's D3
    rule already measured for the birth-origin work item.
    """
    row = rows.get("birth")
    if row is None:
        return []
    entries = state.get("birth") or []
    if entries and all(_entry_next_rung(entry, row) is None for entry in entries):
        return []
    ladder = list(row.get("ladder") or ())
    rung = ladder[0] if ladder else "year"
    if entries:
        rung = _entry_next_rung(entries[0], row) or rung
    text = li.RUNG_TEXTS.get(("birth", rung))
    if not text:
        return []
    anchor = tg.origin_anchor(owner)
    resolves, leverage = gain_for(anchor, index)
    return [_opportunity(
        domain="birth", kind="birth_origin", subject=anchor, subject_kind="origin",
        label="", question=text.format(label="you"), ladder_rung=rung,
        row=row, resolves=resolves, leverage=leverage,
    )]


def _person_candidates(state: dict, nodes: list, items: list, index: dict,
                       rows: dict, names: dict) -> list:
    """R-Q5 — a person the ladder enumerates whose anchor nobody has dated.

    The subject is the entry's own name, resolved through the roster, and the
    question is the domain's own event question for the first event it dates
    that this entry has not answered. That is why it reads *"When did you and
    Katie first meet?"* rather than *"When did this part begin?"*: the domain
    declares three distinct events and the ladder already has a sentence for
    each one (`landmarks_interaction.event_questions`, v219).
    """
    found = []
    for domain in sorted(state):
        row = rows.get(domain)
        if row is None or domain in lp.PARTICIPATION_EPISODE_KINDS:
            continue
        if not li.enumerates_subjects(row):
            continue
        for entry in state[domain]:
            if li.is_none_entry(entry, row):
                continue
            rung = _entry_next_rung(entry, row)
            if rung is None or rung in NON_SUBJECT_RUNGS or rung == li.identity_rung(row):
                continue
            if _has_any_date(entry):
                # The anchor EXISTS; what is left is grain, and grain places
                # nothing new — the graph already has a coordinate for this
                # person. `month` after `year` is the ladder's business, and
                # minting it here would ask "when did you and Katie first
                # meet?" of somebody who has already said.
                continue
            label = _entry_label(entry, row, names)
            if not label:
                continue
            questions = li.event_questions(row, label)
            if not questions:
                continue
            event = questions[0]["event"]
            anchor = _person_anchor(label, entry, nodes, items, names)
            resolves, leverage = gain_for(anchor, index)
            found.append(_opportunity(
                domain=domain, kind="relationship_anchor", subject=anchor,
                subject_kind="person", label=label,
                question=questions[0]["text"], ladder_rung=rung, row=row,
                resolves=resolves, leverage=leverage, event=event,
            ))
    return found


def _person_anchor(label: str, entry: dict, nodes: list, items: list,
                   names: dict) -> str:
    """The anchor ref the graph knows this person by.

    Looked up rather than invented, in the order the graph actually keys
    things: the node whose label is this person, then the Timeline work item
    already asking about them (whose ``anchor_ref`` is Cut 3a's own key), then
    the entry's key as a last resort so an unknown person still has a stable
    identity to be asked under.
    """
    key = normalized_mention_key(label)
    for node in nodes:
        if normalized_mention_key(node.get("label")) == key:
            node_id = collapsed_text(node.get("node_id"))
            if node_id:
                return node_id
    for item in items:
        if not tg.is_timeline_owned(item):
            continue
        if normalized_mention_key(item.get("subject_ref")) == key:
            anchor = tg.anchor_ref(item)
            if anchor:
                return anchor
    return f"landmark:{normalized_mention_key(label).replace(' ', '-')}"


def _ambiguity_candidates(items: list, state: dict, index: dict,
                          rows: dict) -> list:
    """R-Q6 — two stays, and the containment rung could not choose.

    The question is the item's OWN ``prompt_intent``: the fold composed it with
    both stays' spans in it, chronologically, exactly because a person
    answering *"which time in Phoenix — 1988–1990 or 1996–1999?"* is scanning
    a life. Re-composing it here would be a second sentence for one fact.
    """
    found = []
    for item in items:
        kind = collapsed_text(item.get("kind"))
        if kind not in AMBIGUITY_KINDS or not tg.is_timeline_owned(item):
            continue
        question = collapsed_text(item.get("prompt_intent"))
        node_ref = collapsed_text(item.get("node_ref"))
        if not question or not node_ref:
            continue
        domain = _ambiguity_domain(kind, question, state, rows)
        row = rows.get(domain)
        if row is None:
            continue
        resolves = [r for r in (item.get("resolves") or ()) if isinstance(r, str)]
        leverage = item.get("leverage")
        if leverage is None:
            resolves, leverage = gain_for(node_ref, index)
        found.append(_opportunity(
            domain=domain, kind="ambiguous_episode", subject=node_ref,
            subject_kind="node", label=collapsed_text(item.get("subject_ref")),
            question=question, ladder_rung=None, row=row,
            resolves=list(resolves), leverage=int(leverage),
            work_item_id=collapsed_text(item.get("work_item_id")),
        ))
    return found


def _ambiguity_domain(kind: str, question: str, state: dict, rows: dict) -> str:
    """Which landmark domain an ambiguity is a question about.

    A place is residences. An organization is work or schools, and the fold's
    item does not say which — so this asks which domain's FILED entries the
    sentence actually names, and falls back to ``work``, which is the commoner
    of the two and the one the fold's own comment names first.
    """
    if kind == "place_ambiguous":
        return "residences"
    haystack = normalized_mention_key(question)
    for domain in ("schools", "work"):
        row = rows.get(domain)
        if row is None:
            continue
        for entry in state.get(domain) or ():
            label = normalized_mention_key(li.identity_named(entry, row)
                                           or entry.get("label"))
            if label and label in haystack:
                return domain
    return "work"


def _opportunity(*, domain, kind, subject, subject_kind, label, question,
                 ladder_rung, row, resolves, leverage, event=None,
                 work_item_id="") -> dict:
    payload = {
        "id": opportunity_id(domain=domain, kind=kind, subject=subject, event=event),
        "domain": domain,
        "kind": kind,
        "subject": subject,
        "subject_kind": subject_kind,
        "label": label,
        "question": question,
        "ladder_rung": ladder_rung,
        "leverage": int(leverage),
        "resolves": list(resolves),
        "sensitivity": (SENSITIVITY_OFFER_ONLY if row.get("sensitive")
                        else SENSITIVITY_ORDINARY),
        "order": int(row.get("order") or 99),
    }
    if event:
        payload["event"] = event
    if work_item_id:
        payload["work_item_id"] = work_item_id
    return payload


# --------------------------------------------------------------------------
# The two published answers
# --------------------------------------------------------------------------


def candidates(projection: object, landmarks_state: object, roster: object = (),
               *, owner: object = twi.OWNER_SUBJECT_REF,
               framework_root: object = None) -> list[dict]:
    """Every gap the graph can name, BEFORE sufficiency and sensitivity.

    Exposed because sufficiency is a statement about the candidates — a
    domain's ``best_leverage`` is the best candidate it had, including the one
    that was then withheld — and because a caller debugging a collapsed
    surface needs to see what was measured.
    """
    nodes, items, index = _projection_parts(projection)
    state = _domains_state(landmarks_state)
    rows = _rows_by_domain(framework_root)
    names = _roster_names(roster)
    found: list[dict] = []
    found.extend(_span_candidates(nodes, index, rows, names))
    found.extend(_birth_candidate(state, index, rows, collapsed_text(owner)))
    found.extend(_person_candidates(state, nodes, items, index, rows, names))
    found.extend(_ambiguity_candidates(items, state, index, rows))
    found.sort(key=lambda row: (-row["leverage"], row["order"], row["id"]))
    return found


def sufficiency(rows: object, state: object = None, *, threshold: object = None,
                raised: object = (), framework_root: object = None) -> dict:
    """``{domain: {sufficient, best_leverage, reason}}`` over ALL nine domains.

    THE RULE (R2). A domain is **sufficient** when nothing it holds is worth a
    privileged surface, and the branches say which kind of nothing it is:

    1. A **sensitive** domain nobody has raised — ``offer_only``. Losses are
       offered, never asked (§4.6), and that is not a judgement about their
       leverage, which is published beside it either way.
    2. A domain the graph names **no gap** in — ``nothing_remaining``. There
       is nothing to be privileged about.
    3. A **closed list the person declared finished** — ``list_declared_
       finished``. Family and children keep their finishable semantics: *"that
       is everyone"* finishes the list even with rungs unfilled.

       **Declared closure closes a LIST, not a graph.** It never silences an
       opportunity the DEPENDENCY GRAPH named (:data:`GRAPH_KINDS`) that
       clears the threshold: a residence chain somebody closed can still hold
       a stay five events are waiting on, and *"that's all the houses"* is not
       an answer to *"when did you move out of the Mesa house?"*. That is
       precisely audit F7's *"a newly high-value anchor appears with a
       specific question"*, and it is why this branch is conditional rather
       than absolute.
    4. Otherwise the measurement — ``below_threshold`` when the best remaining
       opportunity's leverage is under the bar, ``open_opportunity`` when it
       clears it.

    ``best_leverage`` is published on every row, sufficient or not, so a
    collapsed surface is checkable rather than mysterious.

    Not in this function anywhere: a count of filled fields, a percentage, a
    deadline, or the word complete.
    """
    bar = _threshold(threshold)
    wanted = {collapsed_text(name) for name in (raised or ()) if collapsed_text(name)}
    domains = _domains_state(state)
    by_domain: dict = {}
    for row in rows or ():
        if isinstance(row, dict) and row.get("domain"):
            by_domain.setdefault(row["domain"], []).append(row)
    report: dict = {}
    for row in li.load_questions(framework_root):
        domain = row["domain"]
        found = by_domain.get(domain) or []
        best = max((int(r["leverage"]) for r in found), default=0)
        graph_best = max((int(r["leverage"]) for r in found
                          if r["kind"] in GRAPH_KINDS), default=0)
        if row.get("sensitive") and domain not in wanted:
            verdict, reason = True, REASON_OFFER_ONLY
        elif not found:
            verdict, reason = True, REASON_NOTHING_REMAINING
        elif (_domain_is_closable(row)
                and _list_declared_finished(domains.get(domain) or [], row)
                and graph_best < bar):
            verdict, reason = True, REASON_LIST_FINISHED
        elif best < bar:
            verdict, reason = True, REASON_BELOW_THRESHOLD
        else:
            verdict, reason = False, REASON_OPEN
        report[domain] = {"sufficient": verdict, "best_leverage": best,
                          "reason": reason}
    return report


def landmark_opportunities(projection: object, landmarks_state: object,
                           roster: object = (), *, threshold: object = None,
                           raised: object = (),
                           owner: object = twi.OWNER_SUBJECT_REF,
                           framework_root: object = None) -> list[dict]:
    """The opportunities a host may surface. **A sufficient domain has none.**

    That is the whole of R2 as a return value: the surface disappears because
    the list is empty, not because a component decided to hide a row it was
    given. ``raised`` names the domains the person has brought up themselves,
    which is the ONLY way an ``offer_only`` domain's opportunity is ever
    returned.
    """
    return surface(projection, landmarks_state, roster, threshold=threshold,
                   raised=raised, owner=owner, framework_root=framework_root)[0]


def landmark_sufficiency(projection: object, landmarks_state: object,
                         roster: object = (), *, threshold: object = None,
                         raised: object = (),
                         owner: object = twi.OWNER_SUBJECT_REF,
                         framework_root: object = None) -> dict:
    """:func:`sufficiency` over this projection's own candidates."""
    return surface(projection, landmarks_state, roster, threshold=threshold,
                   raised=raised, owner=owner, framework_root=framework_root)[1]


def surface(projection: object, landmarks_state: object, roster: object = (),
            *, threshold: object = None, raised: object = (),
            owner: object = twi.OWNER_SUBJECT_REF,
            framework_root: object = None) -> tuple[list, dict]:
    """``(opportunities, sufficiency)`` in ONE pass over the graph.

    The fold calls this, because the two answers are one measurement: computing
    them apart would let a published opportunity disagree with the published
    verdict about its own domain. Here they cannot, by construction —
    **a domain is sufficient exactly when it publishes nothing**, and an
    opportunity is published exactly when its own leverage clears the bar in a
    domain that is not sufficient.
    """
    bar = _threshold(threshold)
    found = candidates(projection, landmarks_state, roster, owner=owner,
                       framework_root=framework_root)
    verdicts = sufficiency(found, landmarks_state, threshold=bar, raised=raised,
                           framework_root=framework_root)
    offered = [row for row in found
               if row["leverage"] >= bar
               and not verdicts.get(row["domain"], {}).get("sufficient", True)]
    return offered, verdicts


__all__ = [
    "AMBIGUITY_KINDS",
    "GRAPH_KINDS",
    "LADDER_KINDS",
    "DOMAIN_BY_EPISODE_KIND",
    "LandmarkOpportunityError",
    "OPPORTUNITY_ID_PREFIX",
    "OPPORTUNITY_KINDS",
    "REASON_BELOW_THRESHOLD",
    "REASON_LIST_FINISHED",
    "REASON_NOTHING_REMAINING",
    "REASON_OFFER_ONLY",
    "REASON_OPEN",
    "SENSITIVITY_OFFER_ONLY",
    "SENSITIVITY_ORDINARY",
    "SPAN_END_TEXTS",
    "SPAN_START_TEXTS",
    "SUFFICIENCY_REASONS",
    "THRESHOLD_DIAL",
    "candidates",
    "default_threshold",
    "gain_for",
    "landmark_opportunities",
    "landmark_sufficiency",
    "opportunity_id",
    "sufficiency",
    "surface",
]
