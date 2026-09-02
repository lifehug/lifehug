"""Event identity I2b — containers first: the entity signal and the containment rung.

Controlling design: lifehug-platform `docs/design/event-identity.md` **v4.2**,
amendment §12b (rulings 1, 2, 5, 6 and 7) and the §13.5 promises. I0 settled
what an identity record MEANS, I1 taught the fold to APPLY one, I2 built the
binder that DECIDES one and I3 built the question a person answers. All four
built SAMENESS — and the first real-vault dry run bound nothing, which the
owner read correctly as an emphasis error:

    *"Life is a tree — life → age frames → big named spans (Etherfuse,
    2021→now) → moments inside them. We're trying to collect things into
    events so they can be visualized."*

Most of a vault's tellings are not duplicates of each other; they are MEMBERS
of a stretch somebody lived. **Collection outranks dedup**, and this module is
the collecting half.

**Two things live here and nothing else.**

1. **The entity signal** (§12b ruling 1). A roster-resolved same entity — v221's
   own resolution machinery, the one that knows Betty-Jo is Betty Jo, pointed
   at organizations and periods as well as people — counts as ONE independent
   signal, in retrieval and in R1's condition 4, for `same` and for containment
   alike. It never counts twice with the participant signal it might otherwise
   double (:func:`shared_entities` is what the binder subtracts), and it is
   never sufficient on its own: R1's floor is unchanged at two.

2. **The containment rung** (§12b rulings 2 and 5). `part_of` records minted
   deterministically for exactly TWO rule ids — :data:`RULE_ID_ENTITY_SPAN` and
   :data:`RULE_ID_QUESTION_CONTEXT` — and for no other. C2's origin gate
   (`event_identity.validate_event_identity`) admits deterministic `part_of`
   exactly that far, refusing every third rule id by name.

**What a container is, in the person's own words** (:data:`CONTAINER_RULE_TEXT`).
Not "any dated telling": a telling that OPENS A SPAN. The substrate already
records that — a `started` claim with a stated value opens one, an `ended`
claim closes it, and a stated value that is itself a proper range IS one — so a
container is read off what somebody said rather than guessed from a shape. A
point-dated moment ("Charlee was born 2010-12-21") is not a container, which is
the whole difference between the two Etherfuse rows the design names as
containers and the four hundred moments that are not.

**Containment never narrows a date** (§5.3, untouched). A member gets the
POSSIBLE OUTER RANGE `episode_fold_contract.possible_outer_range` already
defines — never stored, never narrower than the span, never an anchor, never a
reason to stop asking when it happened. This module files an edge; it computes
no dates at all.

**A member may sit in two branches.** `episode_fold_contract.active_binding_index`
refuses two active `same` bindings and says nothing about two `part_of`s, which
is the eras program's own paradigm arriving here intact: *a membership is a
receipt, not a bound*. A telling that is inside both "the idea for Etherfuse"
and "Etherfuse" gets two receipts and the display role stays a separate
decision (I-P). The one-container-at-a-time rule I2 applied to the LANGUAGE
rung ("during Etherfuse", parsed out of prose) is unchanged and separate: that
rung guesses, and a guess picks once or not at all.

Synthetic data only; this module NEVER references any real vault.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import chronology as chrono  # noqa: E402
import episode_fold_contract as efc  # noqa: E402
import identity_resolution as ir  # noqa: E402
import temporal_store as store  # noqa: E402
from temporal_claims import (  # noqa: E402
    collapsed_text,
    normalized_mention_key,
)

# --------------------------------------------------------------------------
# Vocabulary — imported, never restated (ADR 0021)
# --------------------------------------------------------------------------

RULE_ID_ENTITY_SPAN = efc.RULE_ID_ENTITY_SPAN
RULE_ID_QUESTION_CONTEXT = efc.RULE_ID_QUESTION_CONTEXT
DETERMINISTIC_CONTAINMENT_RULE_IDS = efc.DETERMINISTIC_CONTAINMENT_RULE_IDS
CONTAINMENT_AUTHORITIES = efc.CONTAINMENT_AUTHORITIES
DEFAULT_CONTAINMENT_AUTHORITY = efc.DEFAULT_CONTAINMENT_AUTHORITY

#: The signal's name, in retrieval and in R1's condition 4. One string, one
#: home: `episode_binder` imports it rather than spelling it a second time.
ENTITY_SIGNAL = "entity"

#: §12b ruling 1's own sentence, so the module states the rule it implements.
ENTITY_SIGNAL_RULE_TEXT = (
    "A roster-resolved same entity counts as ONE independent signal, in "
    "retrieval and in R1's condition 4, for `same` and containment alike. It "
    "is never a second signal for a fact the participant signal already "
    "counted, and it never binds anything on its own: R1's floor is still two "
    "independent non-label signals."
)

#: Why this is evidence rather than the label said twice (#300's rule).
#:
#: A shared TOKEN is a fact about two strings. A shared ROSTER ENTITY is a
#: fact about the person's life that neither telling produced: the roster is
#: curated elsewhere — by `entity_roster`, by the owner's own verdicts, by the
#: alias folding that decided Betty-Jo and Betty Jo are one grandmother — and
#: a token that resolves through it has been recognized as somebody or
#: something this life actually contains. A token that resolves to nothing
#: yields nothing here, which is exactly the case #300 refused to count.
#: The binder still subtracts whatever the participant signal already counted
#: (:func:`shared_entities`), so one fact is never two signals.
ENTITY_SIGNAL_INDEPENDENCE_TEXT = (
    "the entity signal is the ROSTER's recognition, not the string: two "
    "tellings sharing a word that names nobody share nothing here, and an "
    "entity the participant signal already counted is subtracted rather than "
    "counted twice"
)

#: A one-token roster key shorter than this is not a name (`joy`, `mit`, `asu`,
#: `bj`): the same four-character floor §4.1 already applies to label tokens,
#: applied to the roster side so a three-letter theme cannot collect a life.
#: Multi-token keys ("joy labs", "arizona state") are exempt — a phrase that
#: long is a name by construction.
ENTITY_KEY_MIN_CHARS = 4

#: Which rosters are read. All of them: §12b ruling 1 says *people and
#: organizations alike*, and this repo's `entity_roster.ENTITY_TYPES` has no
#: `organization` — a company lands in `theme` or `object` and a named stretch
#: of life lands in `period`, so restricting the read to `person` would refuse
#: the exact entity the amendment was written about.
ENTITY_ROSTER_TYPES = ir.ENTITY_TYPES if hasattr(ir, "ENTITY_TYPES") else (
    "person", "place", "period", "object", "theme",
)


# --------------------------------------------------------------------------
# The container rule
# --------------------------------------------------------------------------

#: The claims that OPEN a span, and the ones that close it. These are
#: `temporal_claims.EVENT_KINDS`' own words for the act; a stated `started`
#: with no stated `ended` is an OPEN span, which is how "May 2022 - Present"
#: reads as a container rather than as a point.
SPAN_OPENING_KINDS = ("started",)
SPAN_CLOSING_KINDS = ("ended",)

CONTAINER_RULE_TEXT = (
    "A container is a telling whose own words open a span: a `started` claim "
    "at `stated` basis (closed by an `ended` claim when the person gave one, "
    "open otherwise), or a stated value that is itself a proper range. A "
    "point-dated moment is not a container. The container's ENTITIES are "
    "resolved from what the telling is ABOUT — its subject mentions — not "
    "from everything it happens to name, so a job telling that mentions "
    "college does not become the college."
)

#: §12b ruling 2's date leg, read literally. *"carries a date inside that span, "
#: "or no date at all"* — inside, not merely compatible: a member whose stated
#: interval reaches outside the container's is not placed by this rung, it is
#: left for the person. Implemented through `chronology.intersect` and nothing
#: private (:func:`date_inside_span`).
CONTAINMENT_DATE_RULE_TEXT = (
    "an undated telling qualifies; a dated one qualifies only when its whole "
    "stated interval lies inside the container's span, and containment never "
    "narrows it either way (§5.3)"
)

#: Which rule wins when both fire on one pair. The person's own session beats a
#: derived entity match: `question_context` is a fact about what was being
#: asked, `entity_span` is an inference from what was said.
CONTAINMENT_RULE_PRECEDENCE = (RULE_ID_QUESTION_CONTEXT, RULE_ID_ENTITY_SPAN)

#: And which ORIGIN wins when one pair is minted by both this rung and I2's
#: language rung. They share an `identity_id` by construction — `rule_id` and
#: `origin` are both outside `IDENTITY_IDENTITY_KEYS` — so a run that emitted
#: both would file whichever reached the writer first, which is a decision
#: nobody made. Deterministic containment outranks a proposal.
CONTAINMENT_ORIGIN_PRECEDENCE = ("stated", "confirmed", "deterministic", "proposed")


#: This module raises NOTHING of its own, and that is the honest shape rather
#: than an omission. Its two refusals belong to modules that already own them:
#: an unknown authority is `episode_fold_contract.containment_origin`'s
#: `containment_authority_unknown`, and a malformed record is
#: `event_identity.validate_event_identity`'s. A third error class here would
#: be one more vocabulary for a reader to learn and one more place for the two
#: to drift.
CONTAINER_REFUSALS_BELONG_TO_THEIR_OWNERS = (
    "an unknown containment authority is refused by "
    "`episode_fold_contract.containment_origin`; a malformed containment "
    "record is refused by `event_identity.validate_event_identity`; this "
    "module mints and reports, and defines no error of its own"
)


# --------------------------------------------------------------------------
# The entity index
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EntityIndex:
    """Roster keys to entity refs, over every roster type at once.

    Built out of `identity_resolution.roster_index` — v221's own read model —
    rather than re-reading roster JSON, so an alias the resolver folds and an
    alias this signal fires on are the same alias forever.
    """

    keys: dict = field(default_factory=dict)      # {(token, …): (ref, …)}
    names: dict = field(default_factory=dict)     # {ref: display name}
    by_first: dict = field(default_factory=dict)  # {first token: ((tokens, refs), …)}

    def size(self) -> int:
        return len(self.names)

    def name_of(self, ref: object) -> str:
        return self.names.get(collapsed_text(ref), "")


def _key_tokens(value: object) -> tuple:
    key = normalized_mention_key(value)
    return tuple(key.split()) if key else ()


def _key_is_a_name(tokens: Sequence[str]) -> bool:
    """§:data:`ENTITY_KEY_MIN_CHARS` — a one-word key must look like a name."""
    if len(tokens) != 1:
        return bool(tokens)
    return len(tokens[0]) >= ENTITY_KEY_MIN_CHARS


def entity_index(rosters: object) -> EntityIndex:
    """Build the read model from ``{entity_type: snapshot}`` (or a sequence).

    Every name, slug and alias `identity_resolution.roster_index` recognized
    becomes a lookup key; a key that could not be a name
    (:func:`_key_is_a_name`) is dropped, because a three-letter theme matching
    every sentence that says "joy" would make the signal noise rather than
    evidence.
    """
    if isinstance(rosters, EntityIndex):
        return rosters
    if isinstance(rosters, Mapping):
        pairs = [(kind, snapshot) for kind, snapshot in sorted(rosters.items())]
    else:
        pairs = [(None, snapshot) for snapshot in (rosters or ())]

    keys: dict[tuple, set] = {}
    names: dict[str, str] = {}
    for kind, snapshot in pairs:
        index = ir.roster_index(snapshot, entity_type=kind)
        for ref, name in index.refs.items():
            names.setdefault(ref, name)
        for table in (index.by_name_key, index.by_alias_key):
            for key, refs in table.items():
                tokens = _key_tokens(key)
                if not _key_is_a_name(tokens):
                    continue
                keys.setdefault(tokens, set()).update(refs)

    by_first: dict[str, list] = {}
    for tokens in sorted(keys):
        by_first.setdefault(tokens[0], []).append((tokens, tuple(sorted(keys[tokens]))))
    return EntityIndex(
        keys={tokens: tuple(sorted(refs)) for tokens, refs in keys.items()},
        names=names,
        by_first={token: tuple(rows) for token, rows in by_first.items()},
    )


def load_entity_index(vault_root: str | Path) -> EntityIndex:
    """Every roster a vault holds, as one index. The only impure read here.

    A missing roster is an EMPTY roster, never an error: a vault that has never
    curated its people simply scores one signal fewer, exactly the way a host
    that supplies no era memberships does.
    """
    rosters: dict[str, object] = {}
    for kind in ENTITY_ROSTER_TYPES:
        relative = f"state/entity_rosters/{kind}.json"
        text = store.read_store_text(vault_root, relative)
        if not text:
            continue
        try:
            import json  # noqa: PLC0415

            payload = json.loads(text)
        except (TypeError, ValueError):
            continue
        rosters[kind] = payload
    return entity_index(rosters)


def resolve_entities(text: object, index: object) -> frozenset:
    """Every roster entity a piece of the person's own words names.

    The match is a contiguous token run — "Started Etherfuse" names
    ``theme/etherfuse``, "Arizona State University" names ``period/college``
    through its alias — which is v221's normalization applied to a phrase
    rather than to a whole mention. Nothing here reads evidence prose: only
    the mentions the substrate already keeps as names.
    """
    if not isinstance(index, EntityIndex) or not index.by_first:
        return frozenset()
    tokens = _key_tokens(text)
    if not tokens:
        return frozenset()
    found: set[str] = set()
    for position, token in enumerate(tokens):
        for key, refs in index.by_first.get(token, ()):  # type: ignore[union-attr]
            end = position + len(key)
            if tuple(tokens[position:end]) == key:
                found.update(refs)
    return frozenset(found)


def resolve_entity_set(texts: object, index: object) -> frozenset:
    """:func:`resolve_entities` over several pieces of words, unioned."""
    found: set[str] = set()
    for text in texts or ():
        found |= resolve_entities(text, index)
    return frozenset(found)


#: The tell that one fact was about to be counted twice, and the fix.
#:
#: The first live run of this rung bound three pairs on ``place, entity`` where
#: the entity WAS the place — "Moved to San Diego" resolves ``place/san-diego``
#: out of its label while the shared ``place_mentions`` were already scoring
#: the ``place`` signal. That is #300's finding wearing different names, so the
#: subtraction is not only about participants: every fact another signal
#: already credited — a shared participant, a shared place — is removed before
#: the entities are counted, and a run where the entity is the ONLY thing
#: carrying the fact still counts it once.
ONE_FACT_ONE_SIGNAL_TEXT = (
    "an entity another signal already counted is subtracted before the entity "
    "signal is scored: a shared place that scored `place`, a shared "
    "participant that scored `participant`. The entity signal is what the "
    "roster recognizes that nothing else in the pair had already said."
)


def _entity_aliases(value: object) -> frozenset:
    """The spellings one counted fact can wear: the ref, and its bare slug.

    A participant is a ``subject_ref`` (``person/james``) when the claim
    resolved and a normalized MENTION (``james``) when it did not, while an
    entity is always a ref. Comparing only the refs would silently stop
    subtracting on every unresolved claim in a vault — which is most of them.
    """
    text = collapsed_text(value)
    if not text:
        return frozenset()
    tail = text.split("/", 1)[-1]
    return frozenset({text, tail, tail.replace("-", " "), normalized_mention_key(tail)}) - {""}


def shared_entities(left: object, right: object, *, already_counted: object = ()) -> frozenset:
    """The entities two sides share that some other signal has not counted.

    ``already_counted`` is every fact R1's condition 4 has already credited —
    `episode_binder.independent_of_the_label`'s surviving participants, and the
    place entities behind a ``place`` agreement. Subtracting them is
    :data:`ONE_FACT_ONE_SIGNAL_TEXT` in code.
    """
    counted: set = set()
    for value in already_counted or ():
        counted |= set(_entity_aliases(value))
    found = frozenset(left or ()) & frozenset(right or ())
    return frozenset(
        ref for ref in found if not (_entity_aliases(ref) & counted)
    )


# --------------------------------------------------------------------------
# The span a telling opens
# --------------------------------------------------------------------------


def _stated(record: object) -> bool:
    return getattr(record, "basis", None) == "stated"


def span_from_claims(claims: Sequence[object]) -> tuple:
    """``(span, open_ended)`` — the stretch this telling's own words open.

    ``(None, False)`` when the telling opens none. The three cases, in order:

    * a stated ``started`` claim, closed by a stated ``ended`` claim when the
      person gave one and OPEN when they did not — which is how "May 2022 -
      Present" reads as a container rather than as a month;
    * failing that, a stated value that is itself a proper range (a job filed
      as ``2012``–``2015``);
    * otherwise nothing. A point is a moment, not a container.
    """
    opens: list = []
    closes: list = []
    ranges: list = []
    for claim in claims or ():
        row = claim if isinstance(claim, dict) else {}
        record = chrono.from_dict(row.get("temporal_value"))
        if record is None or not _stated(record):
            continue
        kind = collapsed_text(row.get("event_kind"))
        if kind in SPAN_OPENING_KINDS:
            opens.append(record)
        elif kind in SPAN_CLOSING_KINDS:
            closes.append(record)
        elif record.earliest and record.latest and record.earliest != record.latest:
            ranges.append(record)

    if opens:
        start = min((r for r in opens if r.earliest), key=lambda r: r.earliest, default=None)
        if start is not None:
            end = max((r for r in closes if r.latest), key=lambda r: r.latest, default=None)
            # The substrate's own idiom for a stretch: an EDTF interval, with
            # `..` for the end the person did not give. Spelling it any other
            # way makes "May 2022 - Present" render as the month it started,
            # which is exactly the reading that turns a container back into a
            # moment on every surface that shows it.
            latest = end.latest if end is not None else None
            span = chrono.DateRecord(
                best=f"{start.earliest}/{latest or '..'}",
                earliest=start.earliest,
                latest=latest,
                granularity="range",
                confidence=start.confidence,
                basis="stated",
                provenance=tuple(start.provenance) + tuple(
                    end.provenance if end is not None else ()
                ),
            )
            return span, end is None
    if ranges:
        widest = max(ranges, key=lambda r: (r.latest or "", r.earliest or ""))
        return widest, False
    return None, False


def date_inside_span(member: object, span: object) -> bool:
    """Is the member's whole stated interval inside the container's span?

    ``chronology.intersect`` and nothing private: the intersection of a
    contained interval with its container IS the contained interval, and any
    other answer — a different bound, or ``None`` for disjoint — means the
    member reaches outside. An undated member is not this function's business
    (:data:`CONTAINMENT_DATE_RULE_TEXT` admits it separately).
    """
    if member is None or span is None:
        return False
    narrowed = chrono.intersect(member, span)
    if narrowed is None:
        return False
    return (narrowed.earliest == getattr(member, "earliest", None)
            and narrowed.latest == getattr(member, "latest", None))


# --------------------------------------------------------------------------
# Containers
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Container:
    """One stretch a telling can be placed inside, and how it is named."""

    key: str            # the binder unit key this container is
    episode_id: str     # the id a `part_of` record names
    label: str
    entities: frozenset
    span: object
    opened_by: str
    open_ended: bool = False
    kind: str = "prospective"
    #: The container's own EVENT kind — `residence`, `job`, `school`,
    #: `military` for a participation episode, whatever the telling declared
    #: otherwise. Read by the uniqueness rule below and by nothing else.
    event_kind: str = ""

    def display_span(self) -> str:
        try:
            return chrono.display_date(self.span, with_basis=False)
        except Exception:  # noqa: BLE001 - a container still describes itself
            return ""

    def as_dict(self) -> dict:
        return {
            "container_key": self.key,
            "episode_id": self.episode_id,
            "label": self.label,
            "event_kind": self.event_kind,
            "entities": sorted(self.entities),
            "span": self.display_span(),
            "span_open_ended": self.open_ended,
            "opened_by": self.opened_by,
            "container_kind": self.kind,
        }


def containment_reason(rule_id: object, container: Container, *,
                       entities: object = (), dated: bool = False,
                       date_outside: bool = False) -> str:
    """The one sentence a dry-run line carries for this pair."""
    name = collapsed_text(rule_id)
    if name == RULE_ID_QUESTION_CONTEXT:
        text = (f"the question this answer was given to targeted "
                f"{container.label or container.episode_id}")
        if date_outside:
            text += "; its stated date falls outside that span, recorded and not narrowed"
        return text
    shared = ", ".join(sorted(entities or ())) or "—"
    when = "dated inside the span" if dated else "undated, so the span cannot be contradicted"
    return (f"shares {shared} with {container.label or container.episode_id} "
            f"({container.display_span() or 'undated'}"
            f"{', open-ended' if container.open_ended else ''}), and is {when}")


# --------------------------------------------------------------------------
# The rung — pure, and deliberately duck-typed
# --------------------------------------------------------------------------
#
# `views` are `episode_binder.TellingView`s and `units` are its `Candidate`s,
# read through their attributes and never imported: `episode_binder` imports
# THIS module, and a second edge back would make the two files one file with a
# seam drawn through it. Every attribute read below is named in
# :data:`VIEW_FIELDS_READ` / :data:`UNIT_FIELDS_READ`, so a rename upstream
# breaks one documented surface rather than a dozen silent `getattr`s.

VIEW_FIELDS_READ = (
    "telling_ref", "label", "eligible", "dated", "bounds", "event_kind",
    "entities", "subject_entities", "span", "span_open_ended",
)
UNIT_FIELDS_READ = ("key", "kind", "members", "episode_id", "adopted", "authority")


def container_episode_id(telling_ref: object) -> str:
    """The episode id a container is named by when nothing has bound it yet.

    A container's identity may NOT depend on who is inside it. The obvious
    reading — reuse the pair key `episode_binder.prospective_episode_id` mints
    for a would-be `same` create — digests the MEMBER SET, so every new member
    would re-key the container and orphan every containment record already
    filed against it. So the id is the one a create naming the container ALONE
    would mint: stable while the container is unbound, and replaced by the real
    ``episode_id`` the moment the container becomes an episode.
    """
    import event_identity as ei  # noqa: PLC0415

    return ei.episode_id_for(ei.operation_digest(
        authority="deterministic", op="create",
        rule_version=efc.IDENTITY_RULE_VERSION,
        member_refs=[collapsed_text(telling_ref)],
    ))


#: Why a unit this run is about to bind is not offered as a container.
#: Its `episode_id` changes in the same run — an unbound telling's container id
#: is minted from the telling alone, and an episode's is minted from its
#: creation operation — so filing containment against the old id would orphan
#: every record the run wrote. The next run sees the episode and uses its id.
CONTAINER_SKIPPED_WHILE_BINDING = (
    "a unit whose identity this run is about to change is not a container in "
    "this run; the next run reaches it as an episode"
)


def containers(views: Mapping[str, object], units: Mapping[str, object],
               *, excluded_refs: object = ()) -> dict:
    """``{container_key: Container}`` — every stretch a member could go inside.

    A unit is a container when one of its tellings OPENS A SPAN in the person's
    own words (:func:`span_from_claims`, carried on the view) and that telling
    is ABOUT a roster entity (its subject mentions resolve). Both halves are
    required: the span is what makes it a stretch, and the entity is what makes
    it nameable by a member that never quotes it.
    """
    skip = {collapsed_text(ref) for ref in (excluded_refs or ())}
    found: dict[str, Container] = {}
    for key in sorted(units):
        unit = units[key]
        if collapsed_text(key) in skip:
            continue
        members = tuple(sorted(getattr(unit, "members", ()) or ()))
        if any(collapsed_text(ref) in skip for ref in members):
            continue
        opened_by = ""
        span = None
        open_ended = False
        for ref in members:
            view = views.get(ref)
            if view is None or getattr(view, "span", None) is None:
                continue
            if not getattr(view, "subject_entities", frozenset()):
                continue
            opened_by = ref
            span = view.span
            open_ended = bool(getattr(view, "span_open_ended", False))
            break
        if not opened_by or span is None:
            continue
        entities: set = set()
        for ref in members:
            view = views.get(ref)
            if view is not None:
                entities |= set(getattr(view, "subject_entities", frozenset()) or ())
        episode_id = collapsed_text(getattr(unit, "episode_id", "")) or \
            container_episode_id(opened_by)
        found[key] = Container(
            key=key,
            episode_id=episode_id,
            label=collapsed_text(getattr(views.get(opened_by), "label", "")),
            entities=frozenset(entities),
            span=span,
            opened_by=opened_by,
            open_ended=open_ended,
            kind=collapsed_text(getattr(unit, "kind", "")) or "prospective",
            event_kind=collapsed_text(
                getattr(views.get(opened_by), "event_kind", "")
            ),
        )
    return found


def resolves_to(stamp: object, container: Container) -> bool:
    """Does a session's stamped target name THIS container?

    Three spellings are accepted because three hosts hold three of them: the
    episode id (what a bound container is called), the container's unit key,
    and the telling ref of the telling that opened it (what a host holding a
    work item about that telling has). Anything else resolves to nothing and is
    REPORTED — never guessed at, and never quietly dropped.
    """
    text = collapsed_text(stamp)
    if not text:
        return False
    return text in {container.episode_id, container.key, container.opened_by}


#: §4.1 condition 4 (E-L2a), as the module's own sentence.
#:
#: The rung places a telling inside a container it shares an entity with. What
#: it may NOT do is choose between two stays at ONE entity: a person who lived
#: in Cedarport twice has two residence episodes, and an undated story that
#: names Cedarport belongs to one of them and nobody knows which. Picking the
#: earlier, the longer or the first-filed would be a guess wearing a rule's
#: clothes — the exact sentence the retired co-location pass used about the
#: same case, kept because it was right about it.
#:
#: So the refusal is per ENTITY, not per telling: a story that names Cedarport
#: (two stays) and Tidewheel Works (one tenure) still lands inside the tenure.
#: One fact being unanswerable does not make the other one unknown.
CONTAINMENT_UNIQUENESS_RULE_TEXT = (
    "given the telling's date, or its absence, EXACTLY ONE episode of a "
    "shared entity must be compatible; several compatible episodes of one "
    "entity place nothing for that entity and are asked instead "
    "(place_ambiguous for places, tenure_ambiguous for organizations and "
    "schools), while every other entity the telling shares still places"
)


def containment_rows(views: Mapping[str, object], found: Mapping[str, Container],
                     *, question_contexts: object = None,
                     ambiguities: object = None) -> list:
    """Every (telling, container) placement the two evidence-grade rules make.

    One row per pair, `question_context` winning over `entity_span` when both
    fire (:data:`CONTAINMENT_RULE_PRECEDENCE`). A telling may appear in several
    rows for several containers — a membership is a receipt, not a bound — and
    a telling is never placed inside a container it is already a member of.

    ``ambiguities`` is an optional list this function APPENDS to, one row per
    (telling, entity) that :data:`CONTAINMENT_UNIQUENESS_RULE_TEXT` refused.
    It is an out-parameter rather than a second function on purpose: the
    refusal and the placement are two halves of ONE walk over the same pairs,
    and computing them twice is how the two would eventually disagree about
    which pairs were refused.
    """
    stamps = {
        collapsed_text(key): collapsed_text(value)
        for key, value in dict(question_contexts or {}).items()
    }
    rows: list[dict] = []
    for telling_ref in sorted(views):
        view = views[telling_ref]
        if not getattr(view, "eligible", True):
            continue
        stamp = stamps.get(telling_ref, "")
        for key in sorted(found):
            container = found[key]
            if telling_ref == container.opened_by or telling_ref == container.key:
                continue
            dated = bool(getattr(view, "dated", False))
            bounds = getattr(view, "bounds", None)
            inside = date_inside_span(bounds, container.span) if dated else False
            rule_id = ""
            shared: frozenset = frozenset()
            if stamp and resolves_to(stamp, container):
                rule_id = RULE_ID_QUESTION_CONTEXT
            else:
                shared = frozenset(
                    set(getattr(view, "entities", frozenset()) or ())
                    & set(container.entities)
                )
                if shared and (not dated or inside):
                    rule_id = RULE_ID_ENTITY_SPAN
            if not rule_id:
                continue
            rows.append({
                "telling_ref": telling_ref,
                "container_key": container.key,
                "episode_id": container.episode_id,
                "rule_id": rule_id,
                "entities": sorted(shared),
                "dated": dated,
                "date_inside_span": inside,
                "reason": containment_reason(
                    rule_id, container, entities=shared, dated=dated,
                    date_outside=bool(dated and not inside),
                ),
            })
    rows = _unique_entity_rows(rows, found, refused=ambiguities)
    rows.sort(key=lambda row: (row["telling_ref"], row["episode_id"]))
    return rows


def _unique_entity_rows(rows: list, found: Mapping[str, Container],
                        *, refused: object = None) -> list:
    """:data:`CONTAINMENT_UNIQUENESS_RULE_TEXT`, applied to one run's rows.

    A row survives when every entity it was matched ON has exactly one
    compatible container for that telling. `question_context` rows are never
    touched: the person's own session named the container, so there is
    nothing to be ambiguous about — that is the same precedence
    :data:`CONTAINMENT_RULE_PRECEDENCE` already states, applied one layer
    down.

    **Only REPEATABLE containers contest.** The rule is about a person who was
    somewhere more than once, and `identity_resolution.REPEATABLE_EVENT_KINDS`
    is the substrate's own list of the kinds that can happen twice — the same
    list `derive_episode_ref` refuses to mint without a discriminator. Two
    open-ended spans about one THEME are not two stays; they are §13.5's
    *"a member of two containers renders in both"*, which is unchanged and
    still a receipt rather than a bound. Narrowing it here rather than
    everywhere is what lets both promises stand at once.
    """
    by_entity: dict[tuple, list] = {}
    for row in rows:
        if row["rule_id"] != RULE_ID_ENTITY_SPAN:
            continue
        container = found.get(row["container_key"])
        if container is None or not ir.is_repeatable_event(container.event_kind):
            continue
        for entity in row["entities"]:
            by_entity.setdefault((row["telling_ref"], entity), []).append(row)

    contested = {key: group for key, group in by_entity.items() if len(group) > 1}
    dropped = {id(row) for group in contested.values() for row in group}
    if refused is not None:
        for (telling_ref, entity), group in sorted(contested.items()):
            refused.append({
                "telling_ref": telling_ref,
                "entity": entity,
                "kind": ambiguity_kind(entity),
                "episode_ids": sorted({row["episode_id"] for row in group}),
                "container_keys": sorted({row["container_key"] for row in group}),
                "labels": sorted({
                    found[row["container_key"]].label for row in group
                    if row["container_key"] in found
                }),
                "spans": sorted({
                    found[row["container_key"]].display_span() for row in group
                    if row["container_key"] in found
                }),
                "reason": CONTAINMENT_UNIQUENESS_RULE_TEXT,
            })
    return [row for row in rows if id(row) not in dropped]


#: Which question an ambiguous entity owes. The split is the ROSTER TYPE's, not
#: a guess about the word: a `place` ref asks "which time in", everything else
#: — a company, a school, whatever type a vault files organizations under —
#: asks "which time at". `temporal_projection.WORK_ITEM_KINDS` declares both.
AMBIGUITY_KIND_BY_ENTITY_TYPE = {"place": "place_ambiguous"}
DEFAULT_AMBIGUITY_KIND = "tenure_ambiguous"


def ambiguity_kind(entity_ref: object) -> str:
    """``place_ambiguous`` or ``tenure_ambiguous`` for one roster ref."""
    entity_type = collapsed_text(entity_ref).partition("/")[0]
    return AMBIGUITY_KIND_BY_ENTITY_TYPE.get(entity_type, DEFAULT_AMBIGUITY_KIND)


def unresolved_question_contexts(views: Mapping[str, object],
                                 found: Mapping[str, Container],
                                 *, question_contexts: object = None) -> list:
    """Stamps that named no container this run knows — REPORTED, never guessed.

    A host that stamps an era id, a work-item id it did not resolve, or a
    container that has since been superseded gets a named diagnostic instead of
    a silent no-op: the difference between "nothing was targeted" and "we could
    not find what you targeted" is the whole reason this list exists.
    """
    rows = []
    for telling_ref, stamp in sorted(dict(question_contexts or {}).items()):
        ref = collapsed_text(telling_ref)
        text = collapsed_text(stamp)
        if not ref or not text or ref not in views:
            if ref and text:
                rows.append({"telling_ref": ref, "stamp": text,
                             "finding": "question_context_telling_unknown"})
            continue
        if any(resolves_to(text, container) for container in found.values()):
            continue
        rows.append({"telling_ref": ref, "stamp": text,
                     "finding": "question_context_container_unknown"})
    return rows


def containment_record(row: Mapping[str, object], container: Container,
                       view: object, *, authority: object = None,
                       now: object = None) -> dict:
    """One row as an `event_identity` binding — validated, never hand-written.

    ``origin`` is the ONLY field the authority flag touches
    (:data:`episode_fold_contract.CONTAINMENT_AUTHORITY_RULE_TEXT`), and it is
    outside `IDENTITY_IDENTITY_KEYS`, so the same pair mints the same
    ``identity_id`` under either flag and a host that flips it re-keys nothing.
    """
    import event_identity as ei  # noqa: PLC0415

    return ei.validate_event_identity({
        "telling_ref": row.get("telling_ref"),
        "episode_id": row.get("episode_id"),
        "relation": "part_of",
        "origin": efc.containment_origin(authority),
        "rule_version": efc.IDENTITY_RULE_VERSION,
        "rule_id": row.get("rule_id"),
        "candidates": [row.get("episode_id")],
        "evidence": {
            "telling_quote": collapsed_text(getattr(view, "label", "")),
            "episode_quote": container.label,
            "signals": [ENTITY_SIGNAL] if row.get("rule_id") == RULE_ID_ENTITY_SPAN
            else [RULE_ID_QUESTION_CONTEXT],
            "entities": list(row.get("entities") or ()),
            "span": container.display_span(),
            "reason": collapsed_text(row.get("reason")),
        },
        "created_at": now,
    })


def containment_authority_moves(rows: Sequence[Mapping], found: Mapping[str, Container],
                                views: Mapping[str, object], *,
                                active: Mapping[str, tuple],
                                authority: object = None,
                                now: object = None) -> tuple[list, list]:
    """``(upgrades, kept_stronger)`` for rows the I3c filter already dropped.

    :data:`episode_fold_contract.CONTAINMENT_AUTHORITY_UPGRADE_RULE_TEXT`, as
    the two lists a run reports. A containment row is dropped when its
    (telling, episode) pair ALREADY carries an active binding — which is right
    when that binding is a person's ``same``, and was wrong for the only case
    the filter could not tell apart: the rung's own record from a previous run,
    filed under the same ``identity_id`` at the other authority. That case is
    not a second, disagreeing proposal; it is this record, and the only field
    that would move is the one the flag owns.

    Pure. Both lists are CANDIDATES: whether the filed bytes really differ by
    nothing but ``origin`` is settled against the disk by
    `event_identity.refile_event_identity`, which is also the only thing that
    writes. A row whose filed counterpart is a DIFFERENT record — another
    relation, another rule, a person's own decision — appears in neither list
    and is filtered exactly as before.
    """
    import episode_fold_contract as efc_module  # noqa: PLC0415

    upgrades: list = []
    kept: list = []
    for row in rows or ():
        telling_ref = collapsed_text(row.get("telling_ref"))
        container = found.get(collapsed_text(row.get("container_key")))
        view = (views or {}).get(telling_ref)
        if container is None or view is None:
            continue
        record = containment_record(row, container, view, authority=authority,
                                    now=now)
        for binding in (active or {}).get(telling_ref) or ():
            if collapsed_text(binding.get("identity_id")) != record["identity_id"]:
                continue
            move = efc_module.origin_move(binding.get("origin"), record["origin"])
            if move == "upgrade":
                upgrades.append(record)
            elif move == "downgrade":
                kept.append(record["identity_id"])
            break
    return (sorted(upgrades, key=lambda row: row["identity_id"]), sorted(kept))


def merge_containment_records(records: Sequence[object]) -> list:
    """One record per ``identity_id``, by :data:`CONTAINMENT_ORIGIN_PRECEDENCE`.

    `rule_id` and `origin` are both outside the binding digest, so this rung's
    deterministic containment and I2's language-rung PROPOSAL for the same pair
    are one id wearing two hats. A writer that took whichever arrived first
    would be making a decision nobody made; this makes it, in one place, in
    favour of the stronger origin and then the stronger rule.
    """
    order = {name: index for index, name in enumerate(CONTAINMENT_ORIGIN_PRECEDENCE)}
    rules = {name: index for index, name in enumerate(CONTAINMENT_RULE_PRECEDENCE)}
    best: dict[str, dict] = {}
    for record in records or ():
        row = dict(record) if isinstance(record, Mapping) else {}
        identity_id = collapsed_text(row.get("identity_id"))
        if not identity_id:
            continue
        current = best.get(identity_id)
        if current is None:
            best[identity_id] = row
            continue
        rank = (order.get(collapsed_text(row.get("origin")), len(order)),
                rules.get(collapsed_text(row.get("rule_id")), len(rules)))
        held = (order.get(collapsed_text(current.get("origin")), len(order)),
                rules.get(collapsed_text(current.get("rule_id")), len(rules)))
        if rank < held:
            best[identity_id] = row
    return [best[key] for key in sorted(best)]


def group_by_container(rows: Sequence[Mapping], found: Mapping[str, Container],
                       *, authority: object = None) -> list:
    """§13.5's dry-run block: containments PER CONTAINER, with per-pair reasons.

    *"The dry run reports containments per container with per-pair reasons, and
    the founder run collects the Etherfuse tellings under the Etherfuse
    container."* This is that sentence as a data structure — the container
    named once, its members listed under it, each with the rule and the reason
    that put it there.
    """
    text = collapsed_text(authority) or DEFAULT_CONTAINMENT_AUTHORITY
    by_container: dict[str, list] = {}
    for row in rows or ():
        by_container.setdefault(collapsed_text(row.get("container_key")), []).append(dict(row))
    blocks = []
    for key in sorted(by_container):
        container = found.get(key)
        if container is None:
            continue
        members = sorted(by_container[key], key=lambda row: collapsed_text(row.get("telling_ref")))
        block = container.as_dict()
        block["authority"] = text
        block["origin"] = efc.containment_origin(text)
        block["member_count"] = len(members)
        block["members"] = [
            {"telling_ref": row.get("telling_ref"), "rule_id": row.get("rule_id"),
             "reason": row.get("reason"), "entities": list(row.get("entities") or ()),
             "dated": bool(row.get("dated")),
             "date_inside_span": bool(row.get("date_inside_span"))}
            for row in members
        ]
        blocks.append(block)
    blocks.sort(key=lambda block: (-int(block["member_count"]), block["episode_id"]))
    return blocks


def describe_containments(blocks: Sequence[Mapping], *, authority: object = None) -> list:
    """The lines a dry run prints for the containment rung."""
    text = collapsed_text(authority) or DEFAULT_CONTAINMENT_AUTHORITY
    heading = "containments" if text == "applied" else "containment_proposals"
    lines = [f"{heading} ({len(blocks)} container(s), authority: {text})"]
    if not blocks:
        lines.append("  no telling opened a span that another telling names")
        return lines
    for block in blocks:
        # `display_date` already says "after May 2022" for an open-ended span,
        # so the arrow the first draft appended was the same fact twice.
        lines.append(
            f"  ⊂ {block['label'] or block['episode_id']} "
            f"[{block['span'] or 'undated'}] "
            f"{block['episode_id']} — {block['member_count']} member(s)"
        )
        for member in block["members"]:
            lines.append(f"      {member['telling_ref']}  ({member['rule_id']})")
            lines.append(f"        {member['reason']}")
    return lines


__all__ = [
    "CONTAINER_REFUSALS_BELONG_TO_THEIR_OWNERS",
    "CONTAINER_RULE_TEXT",
    "CONTAINER_SKIPPED_WHILE_BINDING",
    "CONTAINMENT_AUTHORITIES",
    "CONTAINMENT_DATE_RULE_TEXT",
    "CONTAINMENT_ORIGIN_PRECEDENCE",
    "CONTAINMENT_RULE_PRECEDENCE",
    "DEFAULT_CONTAINMENT_AUTHORITY",
    "DETERMINISTIC_CONTAINMENT_RULE_IDS",
    "ENTITY_KEY_MIN_CHARS",
    "ENTITY_ROSTER_TYPES",
    "ENTITY_SIGNAL",
    "ENTITY_SIGNAL_INDEPENDENCE_TEXT",
    "ENTITY_SIGNAL_RULE_TEXT",
    "ONE_FACT_ONE_SIGNAL_TEXT",
    "RULE_ID_ENTITY_SPAN",
    "RULE_ID_QUESTION_CONTEXT",
    "SPAN_CLOSING_KINDS",
    "SPAN_OPENING_KINDS",
    "UNIT_FIELDS_READ",
    "VIEW_FIELDS_READ",
    "Container",
    "EntityIndex",
    "container_episode_id",
    "containers",
    "containment_authority_moves",
    "containment_reason",
    "containment_record",
    "containment_rows",
    "CONTAINMENT_UNIQUENESS_RULE_TEXT",
    "ambiguity_kind",
    "date_inside_span",
    "describe_containments",
    "entity_index",
    "group_by_container",
    "load_entity_index",
    "merge_containment_records",
    "resolve_entities",
    "resolve_entity_set",
    "resolves_to",
    "shared_entities",
    "span_from_claims",
    "unresolved_question_contexts",
]
