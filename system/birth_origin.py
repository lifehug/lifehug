"""The calculated birth origin — a scaffold from what the person already said.

Eras design §3.2 (`docs/pr-specs/eras-o-bo-birth-origin.md`; ADR 0030). An age
frame is only a coordinate system if it has an origin, and §3.1's origin is the
owner's *explicit* birth claim. Most vaults hold age statements long before
they hold a birthday — *"I was 30 when I started at Etherfuse"*, *"I was about
twelve when we left the farm"* — and until this module existed those statements
produced a diagnostic, a work item, and no axis at all.

What this module does, and the five owner rulings it is made of
---------------------------------------------------------------

1. **A calculated interval may seed a visibly provisional scaffold.** With no
   explicit owner birth node, the fold seeds one from the age evidence and
   marks it `origin_basis: calculated` so nothing downstream can mistake it for
   a stated birthday.
2. **Compatible constraints INTERSECT.** `chronology.intersect` — terminus post
   quem ∧ terminus ante quem. Two statements about two different years make the
   window *smaller*.
3. **Nothing is ever averaged.** There is no midpoint anywhere in this file.
   The word does not appear in the arithmetic because false precision is
   exactly what §2.2 forbids.
4. **Disjoint constraints stay alternatives.** `intersect` answers `None` for
   evidence that cannot all be true; the readings then go into
   `alternate_values`, the frames are WITHHELD, and Mirror gets a
   contradiction. No arbitrary exact-looking winner is selected.
5. **The explicit-birthday work item stays open.** This module runs in the
   frames phase, long after reconciliation, so the age claims still carry their
   `age_without_birth_anchor` diagnostics and `missing_anchor`/`birth_date` is
   minted exactly as before. Nothing here suppresses a question.

Why it is its own module
------------------------
`temporal_timeline` is the fold, and the fold is edited by every phase of this
program at once. Everything but a hook lives here so the fold's diff is a hook.

Purity
------
No clock, no filesystem, no model. Given the same groups it returns the same
node, and the projection stays byte-identical across input orderings.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import chronology as chrono  # noqa: E402
import cross_dating as cd  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
from temporal_claims import collapsed_text, normalized_mention_key  # noqa: E402

#: The diagnostic finding the fold turns into a Mirror contradiction. One
#: name, read by `_derive_work_items` and by this module's own builder, so the
#: producer and the consumer cannot drift.
CONTRADICTION_FINDING = "birth_origin_contradicted"

#: The field a birth-origin question asks for. It is the SAME
#: ``requested_field`` the `missing_anchor` birth item uses, because it is the
#: same fact — which is what lets Mirror label the row *"your birthday"* and
#: what will let O-E6's answer-once closure treat them as one target.
BIRTH_DATE_FIELD = "birth_date"

#: A provisional origin is contradicted by construction when its evidence is
#: disjoint: the axis cannot be drawn at all, which is as material as a
#: temporal conflict gets.
CONTRADICTION_SYSTEM_VALUE = 1.0

#: The one sentence a frame shows when the origin was calculated. Its explicit
#: twin is `cross_dating.AGE_FRAME_PROVENANCE` ("from your birthday"), which
#: would be a lie on a vault that has no birthday. Re-exported, not re-typed:
#: it is the same sentence `cross_dating.frame_origin_provenance` files on the
#: frame's own record (lifehug#266), and one name for it is what keeps the
#: node's summary and the frame's rendered clause from drifting apart.
CALCULATED_ORIGIN_PROVENANCE = cd.AGE_FRAME_CALCULATED_PROVENANCE

#: How many stated phrases a provenance summary quotes before it stops. A
#: summary is a sentence a person reads, not the evidence list — which is
#: `input_claim_refs`, and is complete.
MAX_SUMMARY_PHRASES = 2


# --------------------------------------------------------------------------
# What one age statement, joined to one dated event, says about a birthday
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class OriginConstraint:
    """One `(age claim, dated event)` pair, and the birth window it allows."""

    node_id: str
    age_claim_id: str
    record: chrono.DateRecord
    phrase: str
    claims: tuple[dict, ...]
    event_grain: str
    approximate: bool

    def sort_key(self) -> tuple:
        """The DETERMINISTIC EVIDENCE ORDER (design §3.2).

        Tighter first, then finer-grained, then stated before hedged, then
        better-held, then the claim id. Total and stable, which is what makes
        "one interval strictly dominates" a fact about the evidence rather than
        a fact about dict ordering.
        """
        return (
            _span_days(self.record),
            _GRAIN_RANK.get(self.event_grain, len(chrono.GRANULARITIES)),
            1 if self.approximate else 0,
            -round(chrono.claim_score(self.record), 6),
            self.age_claim_id,
        )


@dataclass(frozen=True)
class ProvisionalOrigin:
    """The seeded origin: a node, the value the frames may use, and why."""

    node: dict
    node_id: str
    best: chrono.DateRecord | None
    alternates: tuple[chrono.DateRecord, ...]
    claims: tuple[dict, ...]
    contradicted: bool

    @property
    def origin(self) -> tuple[str, dict] | None:
        """What the fold's frame builder needs, or ``None`` when withheld.

        Shaped exactly like ``_owner_birth``'s return — the same
        ``(node_id, {"group": …, "best": …})`` — so the frames are built by one
        code path whether the origin was stated or calculated. ``None`` when
        the evidence is disjoint: §3.2 withholds the frames rather than
        drawing an axis on a disagreement.
        """
        if self.contradicted or self.best is None:
            return None
        return self.node_id, {"group": {"claims": list(self.claims)}, "best": self.best}


_GRAIN_RANK = {name: index for index, name in enumerate(chrono.GRANULARITIES)}


def origin_provenance_summary(origin_basis: object) -> str:
    """The sentence a frame shows for where its origin came from.

    One function so the explicit and calculated cases cannot be spelled two
    ways in two places, and so a frame built on a calculated origin never
    claims to come "from your birthday".
    """
    return (
        cd.AGE_FRAME_PROVENANCE
        if cd.origin_is_explicit(origin_basis)
        else CALCULATED_ORIGIN_PROVENANCE
    )


# --------------------------------------------------------------------------
# The seeding
# --------------------------------------------------------------------------


def provisional_origin(
    *,
    groups: dict,
    calculated: dict,
    owner: str,
    node_id: str,
    node_kind: str,
    label: str,
    rule_version: str,
    generation: int = 0,
    confidence_of=None,
    diagnostics: list | None = None,
) -> ProvisionalOrigin | None:
    """Seed the owner's birth from age evidence, or ``None`` when there is none.

    Called from ONE place: the fold's frames phase, when ``_owner_birth``
    answered ``None``. Everything it reads is already in the fold's hands —
    the groups, their reconciled values, the owner ref — and everything it
    needs from the fold's own definitions (the node id, the node kind, the
    rule version, the confidence normalizer) is passed in rather than
    re-derived, so there is no second copy of any of them.

    ``diagnostics`` receives the ``birth_origin_contradicted`` finding when the
    evidence is disjoint; :func:`contradiction_work_item` turns that row into
    the Mirror contradiction, in the fold, beside every other work item.
    """
    constraints = sorted(
        _constraints(groups, calculated, owner), key=OriginConstraint.sort_key
    )
    if not constraints:
        return None

    records = [item.record for item in constraints]
    combined = chrono.intersect(*records)
    contradicted = combined is None
    alternates: tuple[chrono.DateRecord, ...] = ()
    if contradicted:
        # Disjoint. Partition into the maximal compatible readings, greedily in
        # evidence order — the tightest evidence first, then everything that
        # still agrees with the running intersection — and offer every reading.
        # Choosing among them is exactly what the owner ruled out.
        alternates = _readings(constraints)

    claims = tuple(
        claim
        for item in constraints
        for claim in item.claims
    )
    claim_refs = _claim_refs(claims)
    conflict_state = "contradicted" if contradicted else "none"
    node = tp.validate_calculated_timeline_node({
        "node_id": node_id,
        "node_kind": node_kind,
        "event_kind": "birth",
        "subject_refs": [owner],
        "label": label,
        "best_temporal_value": combined.to_dict() if combined is not None else None,
        "alternate_values": [record.to_dict() for record in alternates],
        "input_claim_refs": claim_refs,
        "input_fingerprint": tp.derive_input_fingerprint(
            claim_ids=claim_refs, calculation_rule_version=rule_version
        ),
        "basis": tc.CLAIM_BASIS_BY_DATE_BASIS.get("age", "calculated"),
        "origin_basis": "calculated",
        "temporal_state": "contradictory" if contradicted else "partial",
        "confidence": (
            confidence_of(combined, 1.0 if contradicted else 0.0)
            if confidence_of is not None else 0.0
        ),
        "calculation_rule_version": rule_version,
        "projection_generation": generation,
        "conflict_state": conflict_state,
        "provenance_summary": _summary(constraints, contradicted=contradicted),
        "life_view": "lived",
    })

    if contradicted and diagnostics is not None:
        diagnostics.append({
            "finding": CONTRADICTION_FINDING,
            "node_id": node_id,
            "subject_ref": owner,
            # The AGE claims, and only those: they are the statements that
            # disagree, they are undated (a quantity is not a position), and
            # `mirror_work.derive_row_state` therefore keeps the row open while
            # `_describe_contradiction` writes the sentence that is true.
            "claim_ids": [item.age_claim_id for item in constraints],
            "evidence_refs": _evidence_refs(claims),
            "readings": [record.to_dict() for record in alternates],
            "prompt_intent": _contradiction_prompt(constraints),
        })

    return ProvisionalOrigin(
        node=node,
        node_id=node_id,
        best=None if contradicted else combined,
        alternates=alternates,
        claims=claims,
        contradicted=contradicted,
    )


def contradiction_work_item(row: dict) -> dict:
    """The ``_mint_work_item`` keywords for a ``birth_origin_contradicted`` row.

    The fold owns minting (one sink, one identity, one merge rule); this owns
    what the row says. Splitting it that way is what keeps the fold's hook to
    three lines while the sentence a person reads lives beside the arithmetic
    that produced it.
    """
    return {
        "kind": "contradiction",
        "event_kind": "birth",
        "subject_ref": collapsed_text(row.get("subject_ref")) or None,
        "event_ref": collapsed_text(row.get("node_id")) or None,
        "node_ref": collapsed_text(row.get("node_id")) or None,
        "requested_field": BIRTH_DATE_FIELD,
        "subject_resolved": True,
        "prompt_intent": row.get("prompt_intent"),
        "claim_refs": list(row.get("claim_ids") or ()),
        "evidence_refs": list(row.get("evidence_refs") or ()),
        "system_value": CONTRADICTION_SYSTEM_VALUE,
    }


# --------------------------------------------------------------------------
# Gathering the evidence
# --------------------------------------------------------------------------


def _constraints(groups: dict, calculated: dict, owner: str) -> list[OriginConstraint]:
    """Every owner age statement that sits on a DATED owner event.

    The join is the grouping the fold already did: an ``age`` claim lives in
    the group of the event it is about, beside that event's own ``date``
    claims, and a group is keyed on its subject — so "both the age claim and
    the dated event resolve to `self`" is a property of the key, not a check.

    The event's own reconciled value is used, never a propagated one: an event
    the substrate merely ORDERED is not an event with a date, and bounding a
    birthday off a bound is a precision nobody asserted. There is no
    circularity to break either — with no birth anchor, `_record_for_age_claim`
    contributed nothing to that value, so it is made of dated claims alone.
    """
    owner_key = normalized_mention_key(owner)
    found: list[OriginConstraint] = []
    for node_id in sorted(groups):
        group = groups[node_id]
        if normalized_mention_key(collapsed_text(group.get("subject"))) != owner_key:
            continue
        best = (calculated.get(node_id) or {}).get("best")
        event = chrono.from_dict(best) if best is not None else None
        if event is None:
            continue
        dated_claims = tuple(
            claim for claim in group.get("claims") or ()
            if collapsed_text(claim.get("claim_type")) in tc.DATED_CLAIM_TYPES
        )
        if not dated_claims:
            continue
        for claim in group.get("claims") or ():
            if collapsed_text(claim.get("claim_type")) != "age":
                continue
            phrase = _phrase(claim)
            if _reads_as_someone_else(_veto_phrases(claim)):
                continue
            quantity = claim.get("temporal_value")
            record = chrono.birth_origin_from_age(event, quantity, claim=phrase or None)
            if record is None:
                continue
            found.append(OriginConstraint(
                node_id=node_id,
                age_claim_id=collapsed_text(claim.get("claim_id")),
                record=record,
                phrase=phrase,
                claims=(claim,) + dated_claims,
                event_grain=event.granularity,
                approximate=bool(isinstance(quantity, dict)
                                 and quantity.get("approximate")),
            ))
    return found


def _reads_as_someone_else(phrases: tuple[str, ...]) -> bool:
    """*"Grandma was 30 in 1951"* never seeds the owner (design §2.5).

    A deterministic veto rather than a trust in whoever assigned the subject:
    the third-person age table is `general_listener.THIRD_PERSON_AGE_RES` and
    the first-person one is `cross_dating.AGE_STATEMENT_RES`, and a phrase that
    the third-person table matches while the first-person table does not is
    somebody else's age however it got filed. Both tables are borrowed, never
    re-typed — a fourth copy of "what an age statement looks like" is exactly
    the duplicate the recurring-defect doctrine forbids.

    Checked against every candidate phrase the claim carries (the stored
    quantity text AND every evidence quote), not just the one `_phrase` picks
    for display: a quantity's own `text` can be a trimmed fragment ("Grandma
    was 30") that drops the very clause ("… when they moved") the third-person
    table matches, and a claim FILED against the owner is still somebody
    else's age if any of its own words say so.

    The import is deferred because `general_listener` pulls the conversation
    stack in behind it and the fold must stay a pure derivation.
    """
    if not phrases:
        return False
    from general_listener import THIRD_PERSON_AGE_RES  # noqa: PLC0415

    for phrase in phrases:
        if not phrase:
            continue
        if not any(pattern.search(phrase) for pattern in THIRD_PERSON_AGE_RES):
            continue
        if not any(pattern.search(phrase) for pattern in cd.AGE_STATEMENT_RES):
            return True
    return False


def _phrase(claim: dict) -> str:
    """The person's own words for this age: the stored phrase, else the quote."""
    quantity = claim.get("temporal_value")
    if isinstance(quantity, dict):
        text = collapsed_text(quantity.get("text"))
        if text:
            return text
    for entry in claim.get("evidence") or ():
        if isinstance(entry, dict):
            quote = collapsed_text(entry.get("quote"))
            if quote:
                return quote
    return ""


def _veto_phrases(claim: dict) -> tuple[str, ...]:
    """Every candidate phrase the veto checks — the stored text plus every quote.

    A tuple rather than the single string `_phrase` returns for display: the
    veto has to look at everything the claim says, not just the one fragment
    a provenance sentence would quote.
    """
    phrases: list[str] = []
    quantity = claim.get("temporal_value")
    if isinstance(quantity, dict):
        text = collapsed_text(quantity.get("text"))
        if text:
            phrases.append(text)
    for entry in claim.get("evidence") or ():
        if isinstance(entry, dict):
            quote = collapsed_text(entry.get("quote"))
            if quote:
                phrases.append(quote)
    return tuple(phrases)


# --------------------------------------------------------------------------
# Readings, and the sentences that explain them
# --------------------------------------------------------------------------


def _readings(constraints: list[OriginConstraint]) -> tuple[chrono.DateRecord, ...]:
    """Disjoint evidence, partitioned into maximal compatible readings.

    Greedy in the deterministic evidence order: each constraint joins the first
    reading it still agrees with, and starts a new one otherwise. Every
    constraint is in exactly one reading and no reading contains a
    contradiction, which is what makes each of them an honest alternative
    rather than an average of the set.
    """
    clusters: list[list] = []
    for item in constraints:
        for cluster in clusters:
            merged = chrono.intersect(cluster[0], item.record)
            if merged is not None:
                cluster[0] = merged
                break
        else:
            clusters.append([item.record])
    return tuple(cluster[0] for cluster in clusters)


def _summary(constraints: list[OriginConstraint], *, contradicted: bool) -> str:
    """*"Calculated from “I was 30 in June 2011” — no birthday on file yet."*"""
    phrases = [item.phrase for item in constraints if item.phrase]
    quoted = ", ".join(f"“{text}”" for text in phrases[:MAX_SUMMARY_PHRASES])
    if len(phrases) > MAX_SUMMARY_PHRASES:
        quoted += f" and {len(phrases) - MAX_SUMMARY_PHRASES} more"
    head = f"Calculated from {quoted}" if quoted else "Calculated from what you have said"
    tail = (
        "these cannot all be true, so no dates are drawn from them yet"
        if contradicted
        else "no birthday on file yet"
    )
    return f"{head} — {tail}"


def _contradiction_prompt(constraints: list[OriginConstraint]) -> str:
    readings = len(_readings(constraints))
    return (
        f"{readings} different birth years fit what you have said about your age. "
        "What is your date of birth?"
    )


def _claim_refs(claims) -> list[str]:
    return sorted({collapsed_text(claim.get("claim_id")) for claim in claims
                   if collapsed_text(claim.get("claim_id"))})


def _evidence_refs(claims) -> list[str]:
    refs = set()
    for claim in claims:
        ref = claim.get("source_ref")
        if not isinstance(ref, dict):
            continue
        key = f"{collapsed_text(ref.get('source_id'))}@{collapsed_text(ref.get('revision'))}"
        if key.strip("@"):
            refs.add(key)
    return sorted(refs)


def _span_days(record: chrono.DateRecord) -> int:
    """How wide this window is, in days — the first key of the evidence order."""
    from datetime import date as _date  # noqa: PLC0415

    low = chrono._ordinal(record.earliest, end=False)  # noqa: SLF001
    high = chrono._ordinal(record.latest, end=True)  # noqa: SLF001
    if low is None or high is None:
        # An open-ended window bounds the least of all; it sorts last.
        return 10 ** 6
    try:
        return (_date(*high) - _date(*low)).days
    except (TypeError, ValueError):
        return 10 ** 6


__all__ = [
    "BIRTH_DATE_FIELD",
    "CALCULATED_ORIGIN_PROVENANCE",
    "CONTRADICTION_FINDING",
    "OriginConstraint",
    "ProvisionalOrigin",
    "contradiction_work_item",
    "origin_provenance_summary",
    "provisional_origin",
]
