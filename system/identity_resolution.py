#!/usr/bin/env python3
"""Who is who, and which event is which — resolution that never destroys.

Wave C1 of the audited final timeline build plan (§6.3 "Identity and
episodes", §10 "Event and identity semantics", §2.5). This module answers two
questions the claim substrate deliberately left open:

1. **Which person is this mention about?** ``"AJ"`` should resolve to the known
   AJ when the vault makes that unambiguous — and when it does not, the claim
   is *kept* as an unresolved claim with its candidate set, never dropped.
2. **Which event/episode is this claim about?** A relationship is not one
   timeless fact: first meeting, dating start, engagement and marriage are
   distinct events on one *edge*. A second stint at the same employer is a
   second episode, not an amendment of the first.

It is pure — no I/O, no model, no vault, no clock it does not receive. The
entity roster is taken as an **argument** (a snapshot dict or its entity list),
because ``entity_roster`` imports ``lifehug_core``, ``ai_provider`` and
``recommend_focuses``, and dragging vault paths and a provider into this module
would make it unusable from the worker, the sandboxed prompt seam and the
platform mirror. Callers load the snapshot with ``entity_roster.load_roster()``
and hand it over; the alias *data* still has exactly one owner.

What this module is NOT
-----------------------

The **model-assisted high-confidence nickname link** that §6.3 also permits is
a Wave C listener/platform seam and is deliberately *not* here. What is here is
the deterministic resolver plus :func:`validate_resolution_record` — the record
contract that the deterministic rules and the model rung both emit, so a
resolution's provenance reads the same however it was reached
(``reason="model"`` versus a named deterministic rule).

There is also **no containment folding and no fuzzy matching**. The prior audit
rejected both: a rule that lets ``"Jim"`` silently absorb ``"Jimmy Carter"``,
or that merges two people because their names are three edits apart, destroys
information that no later correction can recover. Every rule in this module is
exact-match plus a uniqueness gate. When exactness runs out, the answer is
``uncertain`` with the candidates attached — which is a Mirror item, not a
guess (§2.5: uncertain surfaces, never drops).

The ladder
----------

In order, each step a *named* rule that appears in the record's ``reason``:

``exact_ref``
    The mention is already a stable entity ref (``person/katie``). Resolution
    is idempotent: running the resolver over an already-resolved ref returns
    the same ref rather than re-deciding it.

``roster_alias`` / ``unique_name``
    The mention's :func:`~temporal_claims.normalized_mention_key` matches the
    roster keys of **exactly one** entity in the whole roster. The reason names
    which kind of key matched: an alias the roster curation already folded
    (``roster_alias``), or the entity's own name/slug (``unique_name``).

``ambiguous_candidates`` / ``no_candidate``
    Everything else. Two or more entities answer to the mention, or none does.
    Either way the resolution is ``uncertain``, the claim is retained, and the
    candidate set travels with it.

A note on why alias-matching is *uniqueness-gated* rather than a strict
precedence rung above name-matching. Consider a roster where entity A is named
``"Mom"`` and entity B carries ``"Mom"`` as an alias. A strict alias-first
ladder silently picks B — a rule that merges two people without saying so,
which is precisely the class the audit rejected. Here that roster yields two
candidates and one honest ``uncertain``. The ordering is preserved where it is
safe (a ref beats a key match; among key matches the reason records which kind
it was) and abandoned exactly where it would become a silent merge.

Episodes
--------

:func:`derive_episode_ref` mints the ``episode`` node id a claim's ``event_ref``
points at, through :func:`temporal_projection.derive_node_id` — the one
identity function — so an episode ref *is* the node id Wave D's projection
publishes. Two rules are enforced rather than documented:

* A **relationship transition** requires a counterpart. It attaches to the
  edge between two people, order-normalized, so ``derive_episode_ref`` gives
  the same answer whichever person is named the subject.
* A **repeatable** episode (job, school, residence, move, military) requires a
  discriminator. Without one, a second stint at the same employer would collide
  with the first and be silently merged — so the ref is refused loudly instead.
  :func:`episode_discriminator` builds the discriminator from the episode's own
  start claim, which is what makes "second Boeing stint" a *second* episode.

Reversibility
-------------

Resolution is data **about** a claim, never mutation **of** it. A claim's
identity derives from its raw ``subject_mention`` (``temporal_claims``
``CLAIM_IDENTITY_KEYS``, which deliberately excludes ``subject_ref``), so
attaching a resolution cannot re-mint the claim — :func:`apply_resolution`
asserts that rather than trusting it. :func:`unresolve` reverses a link without
destroying it: the previously resolved ref stays in the candidate set and the
reversed decision is recorded in ``reverses``.

Controlling contract: the audited final timeline build plan §2.5, §6.3, §10,
and the prior audit's accepted amendment — entity identity is not event or
episode identity, and a display label is never a primary key.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

from temporal_claims import (
    SCHEMA_VERSION,
    TemporalContractError,
    collapsed_text,
    digest_id,
    normalized_mention_key,
    normalized_timestamp,
    optional_text,
    unit_score,
    validate_temporal_claim,
)
from temporal_projection import (
    derive_node_id,
    validate_temporal_work_item,
)

# --------------------------------------------------------------------------
# The closed vocabularies
# --------------------------------------------------------------------------

#: What a resolution record can say. ``same`` links the mention to an entity;
#: ``different`` records a *negative* link (the model rung or an owner verdict
#: saying "this AJ is not that AJ"), which is knowledge worth keeping and not
#: the same thing as never having looked; ``uncertain`` is the honest answer
#: that keeps the claim and hands the question to Mirror (§2.5).
RESOLUTIONS = ("same", "different", "uncertain")

#: Named deterministic rules, in ladder order. These are the values ``reason``
#: may take when the resolver reached the verdict on its own.
DETERMINISTIC_REASONS = (
    "exact_ref",
    "roster_alias",
    "unique_name",
    "ambiguous_candidates",
    "no_candidate",
)

#: The reason a resolution reached by the Wave C model rung carries. It is one
#: token on purpose: *which* model and at what version belongs to the claim's
#: ``extractor_version`` and the receipt, not to a free-text reason field.
MODEL_REASON = "model"

#: A person settled it directly (an entity verdict, a Mirror answer).
OWNER_REASON = "owner_verdict"

#: What :func:`unresolve` stamps. It is its own reason so a reversal is
#: legible as a reversal rather than as a fresh failure to resolve.
UNRESOLVED_REASON = "unresolved"

#: The subject a landmark entry that names nobody falls back to is its own
#: DOMAIN word (``landmark_projection.entry_subject_mention``), and for one
#: domain — ``birth`` — that word denotes the person themselves. Receipts
#: filed before design §3.1's extractor rule therefore say ``"birth"`` where
#: they mean ``self``. This is the named deterministic rule that reads them,
#: recorded on the record like every other resolution so it is visible and
#: reversible rather than a silent rewrite of the receipt.
OWNER_BIRTH_DOMAIN_REASON = "owner_birth_domain_word"

#: The legacy spelling that rule answers to.
LEGACY_OWNER_BIRTH_MENTION = "birth"

RESOLUTION_REASONS = DETERMINISTIC_REASONS + (
    OWNER_BIRTH_DOMAIN_REASON,
    MODEL_REASON,
    OWNER_REASON,
    UNRESOLVED_REASON,
)

#: The reasons that mean "we did not decide". Both are ``uncertain``; they
#: differ in whether anybody was in the running.
UNCERTAIN_REASONS = ("ambiguous_candidates", "no_candidate", UNRESOLVED_REASON)

#: How a candidate got into the running — the "score-basis" the record carries
#: per candidate, so a human reading a Mirror row can see *why* each name is
#: there rather than only that it is.
CANDIDATE_BASES = ("exact_ref", "alias", "name", "model")

#: Transitions in a relationship. §5.1 and §10: first meeting, dating start,
#: engagement, marriage, separation, divorce and reconciliation are distinct
#: records about the same two people, and each one attaches to the *edge*
#: between them rather than to one person. ``met`` and ``first_met`` are both
#: here because ``temporal_claims.EVENT_KINDS`` seeds ``first_met`` while §5.1's
#: prose says ``met``; accepting both is cheaper than a mismatch that silently
#: routes one of them down the non-relationship path.
RELATIONSHIP_EVENT_KINDS = (
    "met",
    "first_met",
    "dating_started",
    "engaged",
    "married",
    "separated",
    "divorced",
    "reconciled",
)

#: Event kinds a life can hold more than one of. §6.3: "do not collapse every
#: event involving the same people into one timeless relationship", and a
#: repeated school or job period is not one incompatible span (§10). For these,
#: :func:`derive_episode_ref` REFUSES to mint a ref without a discriminator,
#: because a missing discriminator is exactly how a second stint at the same
#: employer silently becomes an edit of the first.
REPEATABLE_EVENT_KINDS = (
    "job",
    "school",
    "move",
    "residence",
    "military",
    "transition",
    "span",
)

#: Which surfaces an identity work item may reach. §6.3 sends ambiguous
#: identity to Mirror; §2.5 defers Mirror's daily-question convergence to the
#: issue tracked separately, so ``daily_question`` is deliberately absent.
IDENTITY_WORK_SURFACES = ("mirror", "timeline")

#: The field an identity work item asks for.
IDENTITY_REQUESTED_FIELD = "identity"

#: Prefix for a relationship edge id. An edge is not a node — it is the
#: event-kind-free grouping key that proves "dating started in 2005" and
#: "married in 2007" are two facts about ONE pair of people.
EDGE_ID_PREFIX = "edge"

#: Prefix for the handle standing in for a subject that has not resolved.
#: It is a handle, never an entity ref: the amendment says a display label is
#: never a primary key, and this is what keeps an unresolved mention from
#: being mistaken for a resolved identity downstream. It is derived from the
#: mention key, so the same unresolved mention produces the same work item
#: across Timeline, Mirror and the queue — one row, not one per sighting.
UNRESOLVED_REF_PREFIX = "unresolved"

#: Keys on a roster entity this module reads. Nothing else is touched:
#: ``entity_roster`` owns the roster's internals and this module is a reader.
ROSTER_NAME_KEYS = ("name", "slug")
ROSTER_ALIAS_KEY = "aliases"


class IdentityResolutionError(TemporalContractError):
    """A resolution record or an episode ref that cannot be trusted."""


ERROR_CODES = (
    "resolution_not_a_mapping",
    "resolution_needs_mention",
    "unknown_resolution",
    "unknown_resolution_reason",
    "unknown_candidate_basis",
    "candidate_needs_ref",
    "resolution_needs_evidence",
    "resolved_ref_required",
    "resolved_ref_forbidden",
    "resolved_ref_not_a_candidate",
    "ambiguous_needs_candidates",
    "no_candidate_has_candidates",
    "resolution_not_reversible",
    "resolution_would_remint",
    "owner_ref_required",
    "episode_needs_event_kind",
    "episode_needs_subject",
    "episode_needs_counterpart",
    "episode_needs_discriminator",
    "edge_needs_two_subjects",
    "timestamp_unusable",
    "score_out_of_range",
)


# --------------------------------------------------------------------------
# The roster, read as a snapshot
# --------------------------------------------------------------------------


def entity_ref(entity_type: object, slug: object) -> str:
    """``person/katie`` — the ref shape the rest of the substrate already uses.

    It is a *type plus slug*, never a display name, so renaming "Mom" to
    "Desi" on a page does not re-point every claim that ever mentioned her.
    """
    kind = normalized_mention_key(entity_type).replace(" ", "_") or "entity"
    tail = normalized_mention_key(slug).replace(" ", "-")
    return f"{kind}/{tail}"


def _entity_slug(entity: dict) -> str:
    """The entity's slug, falling back to its name.

    ``entity_roster`` slugifies through ``lifehug_core.slugify``; importing it
    here would pull vault paths into a pure module, so the fallback re-derives
    a slug from the mention key (lowercase, unpunctuated, hyphen-joined) and is
    only ever reached for a snapshot entry that has no ``slug`` at all. Rosters
    written by ``entity_roster.write_roster`` always carry one.
    """
    slug = collapsed_text(entity.get("slug"))
    if slug:
        return normalized_mention_key(slug).replace(" ", "-")
    return normalized_mention_key(entity.get("name")).replace(" ", "-")


@dataclass(frozen=True)
class RosterCandidate:
    """One entity the roster offers for a mention, and why it is in the running."""

    ref: str
    name: str
    basis: str

    def to_dict(self) -> dict:
        return {"ref": self.ref, "name": self.name, "basis": self.basis}


@dataclass(frozen=True)
class RosterIndex:
    """An immutable read model over one roster snapshot.

    Built once, queried many times. It holds only what resolution needs — the
    ref, the display name, and the exact keys each entity answers to, split by
    whether the key came from the entity's own name/slug or from curated alias
    data, because the split is what the ``reason`` reports.
    """

    entity_type: str = "person"
    refs: dict = field(default_factory=dict)
    by_name_key: dict = field(default_factory=dict)
    by_alias_key: dict = field(default_factory=dict)

    def size(self) -> int:
        return len(self.refs)

    def name_of(self, ref: object) -> str:
        return self.refs.get(collapsed_text(ref), "")

    def has_ref(self, ref: object) -> bool:
        return collapsed_text(ref) in self.refs


def roster_index(snapshot: object, *, entity_type: object = None) -> RosterIndex:
    """Build the read model from an ``entity_roster`` snapshot.

    Accepts what ``entity_roster.load_roster()`` returns (``{"type": ...,
    "entities": [...]}``), a bare list of entities, or an already-built
    :class:`RosterIndex` (so callers may pass either through the resolver
    without branching).

    Entities the owner marked ``owner_verdict: never`` are kept. That verdict
    suppresses a wiki *page*; ``entity_roster`` says so in its own comment
    ("suppression is about pages, not alias folding"), and an unresolvable
    mention is a worse outcome than a resolved mention with no page.
    """
    if isinstance(snapshot, RosterIndex):
        return snapshot
    if isinstance(snapshot, dict):
        entities = snapshot.get("entities") or []
        kind = collapsed_text(entity_type) or collapsed_text(snapshot.get("type")) or "person"
    else:
        entities = list(snapshot or ())
        kind = collapsed_text(entity_type) or "person"

    refs: dict = {}
    by_name_key: dict = {}
    by_alias_key: dict = {}
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        name = collapsed_text(entity.get("name"))
        slug = _entity_slug(entity)
        if not name and not slug:
            continue
        ref = entity_ref(kind, slug or name)
        refs.setdefault(ref, name or slug)

        for key_field in ROSTER_NAME_KEYS:
            key = normalized_mention_key(entity.get(key_field))
            if key:
                by_name_key.setdefault(key, []).append(ref)
        raw_aliases = entity.get(ROSTER_ALIAS_KEY) or ()
        if isinstance(raw_aliases, (str, bytes)):
            raw_aliases = [raw_aliases]
        for alias in raw_aliases:
            key = normalized_mention_key(alias)
            if key:
                by_alias_key.setdefault(key, []).append(ref)

    return RosterIndex(
        entity_type=kind,
        refs=refs,
        by_name_key={k: tuple(dict.fromkeys(v)) for k, v in by_name_key.items()},
        by_alias_key={k: tuple(dict.fromkeys(v)) for k, v in by_alias_key.items()},
    )


# --------------------------------------------------------------------------
# The resolution record
# --------------------------------------------------------------------------


def unresolved_subject_ref(mention: object) -> str:
    """``unresolved:<mention key>`` — a handle, never an entity ref.

    Deterministic in the mention, so every sighting of the same unresolved name
    produces the same work-item identity: one Mirror row for "who is AJ?", not
    one per claim (§5.4's "answer once, update everywhere"). It carries no
    ``/`` so it is a legal document id on the hosted side.
    """
    key = normalized_mention_key(mention)
    return f"{UNRESOLVED_REF_PREFIX}:{key}" if key else UNRESOLVED_REF_PREFIX


def is_unresolved_ref(value: object) -> bool:
    """Is this a handle for an unresolved mention rather than a real ref?"""
    text = collapsed_text(value)
    return text == UNRESOLVED_REF_PREFIX or text.startswith(f"{UNRESOLVED_REF_PREFIX}:")


def _candidate_dict(value: object) -> dict:
    """Normalize one candidate, or raise."""
    if isinstance(value, RosterCandidate):
        value = value.to_dict()
    if isinstance(value, (str, bytes)):
        value = {"ref": value}
    if not isinstance(value, dict):
        raise IdentityResolutionError(
            "candidate_needs_ref", "a candidate is a mapping with a ref"
        )
    ref = collapsed_text(value.get("ref"))
    if not ref:
        raise IdentityResolutionError(
            "candidate_needs_ref", "a candidate without a ref names nobody"
        )
    basis = collapsed_text(value.get("basis")) or "name"
    if basis not in CANDIDATE_BASES:
        raise IdentityResolutionError(
            "unknown_candidate_basis", f"unknown candidate basis: {basis!r}"
        )
    candidate: dict = {"ref": ref, "name": collapsed_text(value.get("name")), "basis": basis}
    if value.get("score") is not None:
        try:
            candidate["score"] = unit_score(value.get("score"), error=IdentityResolutionError)
        except TemporalContractError as exc:
            raise IdentityResolutionError("score_out_of_range", exc.message) from None
    return candidate


def validate_resolution_record(value: object, *, now: object = None) -> dict:
    """Normalize a resolution record or raise :class:`IdentityResolutionError`.

    This is the door every resolution goes through, deterministic or model, so
    the two cannot describe the same decision differently. The refusals that
    carry §6.3's weight:

    * ``resolution_needs_mention`` — the raw mention is the record's spine. A
      resolution that dropped it could not be reversed, because the thing being
      reversed *to* would be gone.
    * ``resolution_needs_evidence`` — a link with no evidence is an assertion,
      and §6.3 requires the evidence be preserved so the link is reversible.
    * ``resolved_ref_required`` / ``resolved_ref_forbidden`` — ``same`` names
      exactly one ref; ``different`` and ``uncertain`` name none. An "uncertain"
      record still carrying a resolved ref is a guess wearing a hedge.
    * ``resolved_ref_not_a_candidate`` — the answer must be one of the names
      that was in the running, so a Mirror row can show the alternatives that
      lost rather than a ref that appeared from nowhere.
    * ``ambiguous_needs_candidates`` — ambiguity *is* the candidate set. An
      ambiguous record with no candidates gives Mirror nothing to offer.
    * ``resolution_not_reversible`` — ``reversible`` is a stated property of
      this contract, not a per-record choice; a caller trying to write an
      irreversible resolution is refused.
    """
    if isinstance(value, ResolutionRecord):
        value = value.to_dict()
    if not isinstance(value, dict):
        raise IdentityResolutionError(
            "resolution_not_a_mapping", "a resolution record must be a mapping"
        )

    mention = collapsed_text(value.get("mention"))
    if not mention:
        raise IdentityResolutionError(
            "resolution_needs_mention", "a resolution record keeps the raw mention"
        )

    resolution = collapsed_text(value.get("resolution"))
    if resolution not in RESOLUTIONS:
        raise IdentityResolutionError(
            "unknown_resolution", f"unknown resolution: {resolution!r}"
        )

    reason = collapsed_text(value.get("reason"))
    if reason not in RESOLUTION_REASONS:
        raise IdentityResolutionError(
            "unknown_resolution_reason", f"unknown reason: {reason!r}"
        )

    evidence_ref = optional_text(value.get("evidence_ref"))
    if not evidence_ref:
        raise IdentityResolutionError(
            "resolution_needs_evidence",
            "a resolution cites the claim or span it was drawn from",
        )

    raw_candidates = value.get("candidates")
    if isinstance(raw_candidates, (str, bytes, dict, RosterCandidate)):
        raw_candidates = [raw_candidates]
    candidates: list[dict] = []
    seen: set[str] = set()
    for raw in raw_candidates or ():
        candidate = _candidate_dict(raw)
        if candidate["ref"] in seen:
            continue
        seen.add(candidate["ref"])
        candidates.append(candidate)

    resolved_ref = optional_text(value.get("resolved_ref"))
    if resolution == "same":
        if not resolved_ref:
            raise IdentityResolutionError(
                "resolved_ref_required", "a 'same' resolution names the ref it resolved to"
            )
        if resolved_ref not in seen:
            raise IdentityResolutionError(
                "resolved_ref_not_a_candidate",
                f"{resolved_ref!r} was never a candidate for {mention!r}",
            )
    elif resolved_ref:
        raise IdentityResolutionError(
            "resolved_ref_forbidden",
            f"a {resolution!r} resolution cannot carry a resolved ref",
        )

    if reason == "ambiguous_candidates" and len(candidates) < 2:
        raise IdentityResolutionError(
            "ambiguous_needs_candidates",
            f"ambiguity is the candidate set, got {len(candidates)}",
        )
    if reason == "no_candidate" and candidates:
        raise IdentityResolutionError(
            "no_candidate_has_candidates",
            f"'no_candidate' contradicts {len(candidates)} candidate(s)",
        )

    if value.get("reversible") is False:
        raise IdentityResolutionError(
            "resolution_not_reversible",
            "every resolution in this substrate is reversible; see unresolve()",
        )

    created_at = normalized_timestamp(
        value.get("created_at") or now, error=IdentityResolutionError
    )

    normalized: dict = {
        "schema_version": SCHEMA_VERSION,
        "mention": mention,
        "mention_key": normalized_mention_key(mention),
        "candidates": candidates,
        "resolution": resolution,
        "reason": reason,
        "evidence_ref": evidence_ref,
        "reversible": True,
        "created_at": created_at,
    }
    if resolved_ref:
        normalized["resolved_ref"] = resolved_ref
    if value.get("confidence") is not None:
        try:
            normalized["confidence"] = unit_score(
                value.get("confidence"), error=IdentityResolutionError
            )
        except TemporalContractError as exc:
            raise IdentityResolutionError("score_out_of_range", exc.message) from None
    reverses = value.get("reverses")
    if isinstance(reverses, dict) and reverses:
        normalized["reverses"] = {
            key: reverses[key]
            for key in ("resolution", "resolved_ref", "reason", "created_at")
            if reverses.get(key)
        }
    return normalized


@dataclass(frozen=True)
class ResolutionRecord:
    """§6.3's reversible link: the mention, who it could be, what we decided, why.

    ``reversible`` is a constant rather than a field a writer may set — see
    :func:`unresolve`. ``reverses`` is the audit trail of a reversal: the
    decision that was undone, kept so that undoing an undo is possible and so
    that a Mirror row can say what changed.
    """

    mention: str
    resolution: str
    reason: str
    evidence_ref: str
    mention_key: str = ""
    candidates: tuple[dict, ...] = ()
    resolved_ref: str | None = None
    confidence: float | None = None
    created_at: str = ""
    reverses: dict | None = None
    schema_version: int = SCHEMA_VERSION

    @property
    def reversible(self) -> bool:
        return True

    def to_dict(self) -> dict:
        payload: dict = {
            "schema_version": self.schema_version,
            "mention": self.mention,
            "mention_key": self.mention_key or normalized_mention_key(self.mention),
            "candidates": [dict(c) for c in self.candidates],
            "resolution": self.resolution,
            "reason": self.reason,
            "evidence_ref": self.evidence_ref,
            "reversible": True,
            "created_at": self.created_at,
        }
        for key, value in (
            ("resolved_ref", self.resolved_ref),
            ("confidence", self.confidence),
            ("reverses", self.reverses),
        ):
            if value is not None:
                payload[key] = value
        return payload

    def is_resolved(self) -> bool:
        return self.resolution == "same" and bool(self.resolved_ref)


def resolution_record(value: object, *, now: object = None) -> ResolutionRecord:
    """Validate and build. The strict constructor every writer should use."""
    normalized = validate_resolution_record(value, now=now)
    return record_from_dict(normalized)


def record_from_dict(value: object) -> ResolutionRecord | None:
    """Tolerant reader — ``None`` rather than an exception (the substrate's rule)."""
    try:
        normalized = validate_resolution_record(value)
    except TemporalContractError:
        return None
    return ResolutionRecord(
        mention=normalized["mention"],
        mention_key=normalized["mention_key"],
        candidates=tuple(normalized["candidates"]),
        resolution=normalized["resolution"],
        reason=normalized["reason"],
        evidence_ref=normalized["evidence_ref"],
        resolved_ref=normalized.get("resolved_ref"),
        confidence=normalized.get("confidence"),
        created_at=normalized["created_at"],
        reverses=normalized.get("reverses"),
        schema_version=normalized["schema_version"],
    )


# --------------------------------------------------------------------------
# The deterministic resolver
# --------------------------------------------------------------------------


def candidates_for(mention: object, roster: object, *, entity_type: object = None) -> tuple[dict, ...]:
    """Every roster entity that answers to this mention, exactly.

    Exposed so a caller — including the Wave C model rung, which must choose
    *among the deterministic candidate set* rather than invent a name — can see
    the running without committing to a verdict. Exact keys only: no
    containment, no edit distance, no first-name folding.
    """
    index = roster_index(roster, entity_type=entity_type)
    key = normalized_mention_key(mention)
    text = collapsed_text(mention)

    if index.has_ref(text):
        return (
            RosterCandidate(ref=text, name=index.name_of(text), basis="exact_ref").to_dict(),
        )

    out: list[dict] = []
    seen: set[str] = set()
    for ref in index.by_name_key.get(key, ()):
        if ref in seen:
            continue
        seen.add(ref)
        out.append(RosterCandidate(ref=ref, name=index.name_of(ref), basis="name").to_dict())
    for ref in index.by_alias_key.get(key, ()):
        if ref in seen:
            continue
        seen.add(ref)
        out.append(RosterCandidate(ref=ref, name=index.name_of(ref), basis="alias").to_dict())
    return tuple(out)


def resolve_mention(
    mention: object,
    *,
    roster: object = (),
    evidence_ref: object,
    entity_type: object = None,
    now: object = None,
) -> ResolutionRecord:
    """Resolve one raw mention against a roster snapshot, deterministically.

    Returns a validated :class:`ResolutionRecord` in every case — including
    when nothing resolves, because "we looked and could not tell" is knowledge
    the claim should carry (§2.5: uncertain surfaces, never drops). The caller
    attaches it with :func:`apply_resolution`; the claim is never modified here
    and never re-minted anywhere.

    The verdict is ``same`` only when exactly one entity answers to the mention.
    Two or more is ``uncertain`` with the full running attached, which
    :func:`identity_work_item` turns into a Mirror row. ``different`` is never
    produced by this function: a deterministic exact-match resolver has no way
    to learn that two names denote different people, so that verdict belongs to
    the model rung and to owner judgment, both of which write through
    :func:`resolution_record`.
    """
    matches = candidates_for(mention, roster, entity_type=entity_type)

    if len(matches) == 1:
        only = matches[0]
        reason = {
            "exact_ref": "exact_ref",
            "alias": "roster_alias",
            "name": "unique_name",
        }.get(only["basis"], "unique_name")
        return resolution_record(
            {
                "mention": mention,
                "candidates": matches,
                "resolution": "same",
                "resolved_ref": only["ref"],
                "reason": reason,
                "evidence_ref": evidence_ref,
            },
            now=now,
        )

    return resolution_record(
        {
            "mention": mention,
            "candidates": matches,
            "resolution": "uncertain",
            "reason": "ambiguous_candidates" if matches else "no_candidate",
            "evidence_ref": evidence_ref,
        },
        now=now,
    )


def is_owner_birth_domain_word(mention: object, event_kind: object) -> bool:
    """Is this claim a legacy birth landmark naming the domain instead of the person?

    BOTH halves are required, on purpose. The word alone proves nothing — a
    person may be mentioned by any word — so the rule fires only where the
    claim is also *about a birth*, which is the one place
    ``entry_subject_mention``'s domain fallback ever meant "the person whose
    vault this is". A ``birth``-worded mention on any other event kind is left
    exactly where it is, unresolved, for the ordinary resolver to answer.
    """
    return (
        normalized_mention_key(mention) == normalized_mention_key(LEGACY_OWNER_BIRTH_MENTION)
        and collapsed_text(event_kind) == "birth"
    )


def owner_birth_domain_resolution(
    mention: object,
    *,
    owner_ref: object,
    evidence_ref: object,
    now: object = None,
) -> ResolutionRecord:
    """The :data:`OWNER_BIRTH_DOMAIN_REASON` rule, as a record.

    It resolves ``same`` to the owner's own handle and carries that handle as
    its single candidate, so the decision reads back through exactly the same
    door — and the same ``unresolve`` — as a roster match or an owner verdict.
    """
    ref = collapsed_text(owner_ref)
    if not ref:
        raise IdentityResolutionError(
            "owner_ref_required", "the owner-birth rule resolves to the owner's own handle"
        )
    return resolution_record(
        {
            "mention": mention,
            "candidates": [{"ref": ref, "name": ref, "basis": "exact_ref"}],
            "resolution": "same",
            "resolved_ref": ref,
            "reason": OWNER_BIRTH_DOMAIN_REASON,
            "evidence_ref": evidence_ref,
        },
        now=now,
    )


def unresolve(record: object, *, now: object = None) -> ResolutionRecord:
    """Reverse a resolution without destroying it (§6.3's "reversible").

    The returned record is ``uncertain`` with reason ``unresolved``. Nothing is
    thrown away: the candidate set survives intact — including the ref that had
    won, so the reversal can itself be reversed — and the undone decision is
    recorded in ``reverses``. This is the only supported way to undo a link,
    and it produces *new* data rather than editing old data, which is the same
    rule the claim substrate applies to supersession.

    Unresolving an already-uncertain record is a no-op that still returns a
    valid record, so a caller need not check first.
    """
    current = record if isinstance(record, ResolutionRecord) else record_from_dict(record)
    if current is None:
        raise IdentityResolutionError(
            "resolution_not_a_mapping", "unresolve needs a valid resolution record"
        )
    if current.resolution == "uncertain":
        return current

    payload: dict = {
        "mention": current.mention,
        "candidates": [dict(c) for c in current.candidates],
        "resolution": "uncertain",
        "reason": UNRESOLVED_REASON,
        "evidence_ref": current.evidence_ref,
        "reverses": {
            "resolution": current.resolution,
            "resolved_ref": current.resolved_ref,
            "reason": current.reason,
            "created_at": current.created_at,
        },
    }
    return resolution_record(payload, now=now)


# --------------------------------------------------------------------------
# Attaching a resolution to a claim — annotation, never mutation
# --------------------------------------------------------------------------


def resolution_annotation(record: object) -> dict:
    """Project a record into ``TemporalClaim.subject_resolution``'s shape.

    ``temporal_claims`` already reserves a slot for §6.3's reversibility record
    and normalizes it to ``{candidates: [ref, ...], reason, confidence}``. This
    is the one projection into it, so the richer record here and the claim's
    stored annotation cannot drift. The full record — per-candidate names and
    bases, the ``reverses`` trail — belongs to the resolution ledger Wave B/D
    stores beside the receipts; the claim carries the summary.
    """
    current = record if isinstance(record, ResolutionRecord) else record_from_dict(record)
    if current is None:
        return {}
    annotation: dict = {
        "candidates": [c["ref"] for c in current.candidates],
        "reason": current.reason,
    }
    if current.confidence is not None:
        annotation["confidence"] = current.confidence
    return annotation


def apply_resolution(claim: object, record: object, *, now: object = None) -> dict:
    """Return a NEW claim dict carrying the resolution. The claim id must not move.

    §6.3 and §5.1: the raw mention is what identity derives from, so resolving
    an alias later never re-mints the claim. That is a property of
    ``temporal_claims.CLAIM_IDENTITY_KEYS`` — but a property nothing checks is a
    property waiting to break at the next pin bump, so this function asserts it
    and raises ``resolution_would_remint`` rather than filing a duplicate.

    The input claim is not mutated. ``subject_mention`` is untouched; only
    ``subject_ref`` (when the record resolved) and ``subject_resolution`` (in
    every case, including uncertain — the fact that we looked is worth keeping)
    are added.
    """
    if not isinstance(claim, dict):
        claim = validate_temporal_claim(claim, now=now)
    before = validate_temporal_claim(claim, now=now)

    current = record if isinstance(record, ResolutionRecord) else record_from_dict(record)
    if current is None:
        raise IdentityResolutionError(
            "resolution_not_a_mapping", "apply_resolution needs a valid resolution record"
        )

    after_input = dict(before)
    after_input["subject_resolution"] = resolution_annotation(current)
    if current.is_resolved():
        after_input["subject_ref"] = current.resolved_ref
    else:
        after_input.pop("subject_ref", None)

    after = validate_temporal_claim(after_input, now=now)
    if after["claim_id"] != before["claim_id"]:
        raise IdentityResolutionError(
            "resolution_would_remint",
            f"resolving {current.mention!r} moved the claim id "
            f"{before['claim_id']} -> {after['claim_id']}",
        )
    return after


# --------------------------------------------------------------------------
# The Mirror hand-off
# --------------------------------------------------------------------------


def identity_work_item(
    record: object,
    *,
    claim_refs: object = (),
    now: object = None,
) -> dict | None:
    """Mint the ``identity_uncertain`` work item an ambiguous mention deserves.

    §6.3: "Ambiguous identity becomes a Mirror item; it does not justify
    dropping the claim." The item's identity is derived from the *mention*
    handle, so every claim that ever said "AJ" ambiguously points at one row
    — answer once, update everywhere (§5.4).

    Returns ``None`` for anything that is not genuine ambiguity, and the two
    exclusions are deliberate rather than incidental:

    * A **resolved** record has nothing to ask.
    * A record with **no candidates** is a name nobody in the roster resembles
      — which is a person we have not met yet, not a disagreement. Minting a
      Mirror row for every first mention of a new name would fill Mirror with
      noise and bury the real contradictions §2.5 exists to surface. Nothing is
      lost by the omission: the claim is retained with its ``uncertain``
      record, and the mention resolves the moment the roster learns the name.

    Surfacing, scoring and queue admission are Wave D/E; this wires the shape.
    """
    current = record if isinstance(record, ResolutionRecord) else record_from_dict(record)
    if current is None or current.resolution != "uncertain" or not current.candidates:
        return None

    refs = claim_refs
    if isinstance(refs, (str, bytes)):
        refs = [refs]
    names = [c["name"] or c["ref"] for c in current.candidates]

    return validate_temporal_work_item(
        {
            "kind": "identity_uncertain",
            "state": "open",
            "subject_ref": unresolved_subject_ref(current.mention),
            "requested_field": IDENTITY_REQUESTED_FIELD,
            "prompt_intent": (
                f"Which {' or '.join(names)} is {current.mention!r} here?"
                if names
                else f"Who is {current.mention!r}?"
            ),
            "claim_refs": list(refs or ()),
            "evidence_refs": [current.evidence_ref],
            "allowed_surfaces": list(IDENTITY_WORK_SURFACES),
        },
        now=now,
    )


# --------------------------------------------------------------------------
# Episode identity — which event is which
# --------------------------------------------------------------------------


def is_relationship_event(event_kind: object) -> bool:
    """Does this event kind describe a transition between two people?"""
    return collapsed_text(event_kind) in RELATIONSHIP_EVENT_KINDS


def is_repeatable_event(event_kind: object) -> bool:
    """Can a life hold more than one of these, needing a discriminator?"""
    return collapsed_text(event_kind) in REPEATABLE_EVENT_KINDS


def relationship_edge_ref(subject: object, counterpart: object) -> str:
    """``edge:<24 hex>`` — the order-normalized pair, free of any event kind.

    This is the grouping key that makes "dating started in 2005" and "married
    in 2007" two facts about ONE relationship rather than two unrelated events
    or one collapsed blob (§6.3, §10). It deliberately excludes the event kind,
    the dates and the direction: ``edge(a, b) == edge(b, a)``, forever.
    """
    keys = sorted({normalized_mention_key(v) for v in (subject, counterpart) if collapsed_text(v)})
    if len(keys) != 2:
        raise IdentityResolutionError(
            "edge_needs_two_subjects",
            "a relationship edge joins two distinct subjects",
        )
    return digest_id(EDGE_ID_PREFIX, {"subject_keys": keys})


def episode_discriminator(start_value: object) -> str | None:
    """The episode's OWN start, as the thing that separates it from its repeats.

    §6.3 and §10: a second stint at the same employer is a second episode. What
    makes it a second one is its own start claim, so the discriminator is drawn
    from that rather than from an arrival order the fold cannot reproduce.

    Accepts an EDTF string, a ``chronology.DateRecord``-shaped mapping (any of
    ``best``/``start``/``edtf``/``value``), or ``None``. Returns ``None`` when
    there is nothing to discriminate on — the caller then supplies an explicit
    ordinal, or :func:`derive_episode_ref` refuses.

    Note this is not the "never a timestamp" ``derive_node_id`` warns about: a
    wall clock records when the fold ran and moves on every rebuild, while an
    asserted start date is part of what the episode *is* and is stable across
    every rebuild from the same claims.
    """
    if isinstance(start_value, dict):
        for key in ("best", "start", "edtf", "value"):
            text = collapsed_text(start_value.get(key))
            if text:
                return text
        return None
    text = collapsed_text(start_value)
    return text or None


def derive_episode_ref(
    *,
    event_kind: object,
    subject_ref: object = None,
    subject_mention: object = None,
    counterpart_ref: object = None,
    discriminator: object = None,
) -> str:
    """``node:<24 hex>`` — the stable identity of one event or episode.

    Built through :func:`temporal_projection.derive_node_id`, the substrate's
    one identity function, so an episode ref *is* the node id Wave D's
    projection publishes and a claim's ``event_ref`` points at the same thing a
    Mirror row and a work item do.

    The subject may be a resolved ref or, when identity has not resolved, the
    raw mention — an unresolved subject must still be able to hold an event, or
    §2.5's "never dropped" would fail exactly where identity is hardest. Both
    normalize through ``normalized_mention_key``, so an episode minted against
    ``"Katie"`` before resolution and against ``person/katie`` after it are
    *different* refs; the fold re-derives event refs from resolved subjects, and
    that re-derivation is a projection rebuild, never a claim edit.

    Two refusals, each preventing a silent merge:

    * ``episode_needs_counterpart`` — a relationship transition without the
      other person would attach to one half of an edge and collide with every
      other relationship that person ever had.
    * ``episode_needs_discriminator`` — a repeatable kind (job, school, move,
      residence, military) without one collapses a second stint into the first.
      Pass ``episode_discriminator(start)`` or an explicit ordinal.
    """
    kind = collapsed_text(event_kind)
    if not kind:
        raise IdentityResolutionError(
            "episode_needs_event_kind",
            "a date is the date OF AN EVENT; an episode ref needs its kind",
        )

    subject = collapsed_text(subject_ref) or collapsed_text(subject_mention)
    if not subject:
        raise IdentityResolutionError(
            "episode_needs_subject", "an episode is about somebody or something"
        )

    counterpart = collapsed_text(counterpart_ref)
    relationship = is_relationship_event(kind)
    if relationship and not counterpart:
        raise IdentityResolutionError(
            "episode_needs_counterpart",
            f"{kind!r} is a transition between two people; name the counterpart",
        )

    disc = collapsed_text(discriminator) or None
    if is_repeatable_event(kind) and not disc:
        raise IdentityResolutionError(
            "episode_needs_discriminator",
            f"{kind!r} can happen more than once; a second one without a "
            "discriminator would silently merge into the first",
        )

    subjects = [subject, counterpart] if counterpart else [subject]
    return derive_node_id(
        node_kind="episode" if (relationship or is_repeatable_event(kind)) else "event",
        event_kind=kind,
        subject_refs=subjects,
        discriminator=disc,
    )


__all__ = [
    "CANDIDATE_BASES",
    "DETERMINISTIC_REASONS",
    "EDGE_ID_PREFIX",
    "ERROR_CODES",
    "IDENTITY_REQUESTED_FIELD",
    "IDENTITY_WORK_SURFACES",
    "MODEL_REASON",
    "OWNER_REASON",
    "RELATIONSHIP_EVENT_KINDS",
    "REPEATABLE_EVENT_KINDS",
    "RESOLUTIONS",
    "RESOLUTION_REASONS",
    "OWNER_BIRTH_DOMAIN_REASON",
    "LEGACY_OWNER_BIRTH_MENTION",
    "is_owner_birth_domain_word",
    "owner_birth_domain_resolution",
    "UNCERTAIN_REASONS",
    "UNRESOLVED_REASON",
    "UNRESOLVED_REF_PREFIX",
    "IdentityResolutionError",
    "ResolutionRecord",
    "RosterCandidate",
    "RosterIndex",
    "apply_resolution",
    "candidates_for",
    "derive_episode_ref",
    "entity_ref",
    "episode_discriminator",
    "identity_work_item",
    "is_relationship_event",
    "is_repeatable_event",
    "is_unresolved_ref",
    "record_from_dict",
    "relationship_edge_ref",
    "resolution_annotation",
    "resolution_record",
    "resolve_mention",
    "roster_index",
    "unresolve",
    "unresolved_subject_ref",
]
