#!/usr/bin/env python3
"""Mirror's actionable rows — a contradiction you can answer (v224).

`mirror.py` synthesizes what the classifier *noticed* about a life: tensions,
insights, stated positions. That page is a reading. This module is the other
half of Mirror the audited timeline plan requires **now** (§8.2): the rows a
person can *act* on — the two places where the temporal substrate knows it is
confused and only the person can settle it.

Two kinds render here and no others (§2.5's bounded scope):

* ``contradiction`` — two active claims that cannot both be true.
* ``identity_uncertain`` — a mention the resolver honestly could not place,
  candidates and all (`identity_resolution.identity_work_item`).

A missing anchor or a coarse date is *not* a Mirror row. Routine
incompleteness belongs on Timeline, where §2.3 says open gaps are a normal
state rather than user debt, and putting it here would bury the real
disagreements under a to-do list. That exclusion is enforced by
:data:`MIRROR_WORK_ITEM_KINDS`, not by convention.

Four properties are load-bearing, and each one is a refusal somewhere below.

**The row's identity is the work item's identity.** A row *is* a
:class:`temporal_projection.TemporalWorkItem` rendered; it has no id of its
own. ``work_item_id`` is derived from subject/event identity, so the same
disagreement is the same row across rebuilds, across surfaces, and after the
claims underneath it change — which is what makes "resolve once, closed
everywhere" (§2.3, §5.4) mean anything, and what lets the deferred Mirror
convergence work (lifehug-platform#663) attach comments and scores later
without re-identifying anything.

**Open/resolved is DERIVED, never stored.** :func:`row_for` reads the current
active claim index and asks whether the claims still disagree. Nothing here
edits a row to close it, and a stored ``state`` of ``resolved`` on an item
whose claims still conflict does **not** close the row — the substrate wins,
because §2.5 says a contradiction closes only when its active claims no longer
conflict or an explicit correction settles it. A row that could be closed by
writing to the row would be a second source of truth for the same fact.

**Resolution writes evidence, never a patch.** :func:`resolve_mirror_item`
promotes the person's own words as a durable source and files a correction
naming the claims that stop standing (#238's model). It never edits a claim,
never touches the projection, and never invents a replacement: saying what is
true *instead* is a separate traceable act — new claims through a new receipt,
which this function will do for you when you hand it ``claims_for``. And when
the person says "I don't know", skips, or closes Play, there is
:func:`abandon_mirror_item`, which takes no vault root at all and therefore
*cannot* write anything. §2.5, made structural.

**Quiet, and blocking nothing.** Rows are capped and ordered by conflict
severity. No count is pushed to another surface, no badge, no nag. Nothing in
this module is imported by timeline derivation, and nothing here gates it:
an unresolved contradiction leaves the rest of the timeline exactly as it was,
showing its best-supported reading beside the alternatives, indefinitely
(§2.5, §10). The read direction is one-way — this module reads the substrate;
the substrate does not read this module.

Deliberately NOT here, and not to be added without the owner: comments on a
row, a quantified resolution value, and admission of Mirror rows to the daily
question queue. That is lifehug-platform#663, deferred on purpose (§8.3,
§13). A daily-only user may never resolve a contradiction in this release
unless an ordinary conversation happens to supply the evidence, and claiming
otherwise before that issue ships would be a lie about the product.

Controlling contract: the audited final timeline build plan §2.5, §8.2, §10.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import chronology as chrono  # noqa: E402
import identity_resolution as ident  # noqa: E402
import temporal_store as store  # noqa: E402
import temporal_work_items as twi  # noqa: E402
from temporal_claims import (  # noqa: E402
    CONSTRAINT_ID_PREFIX,
    TemporalContractError,
    bounded_quote,
    collapsed_text,
    optional_text,
)
from temporal_projection import (  # noqa: E402
    WORK_ITEMS_FILE,
    TemporalWorkItem,
    work_item_from_dict,
)
from vault_paths import read_vault_text  # noqa: E402

# --------------------------------------------------------------------------
# The bounded scope
# --------------------------------------------------------------------------

#: The ONLY work item kinds Mirror renders as actionable rows (§2.5). A
#: ``missing_anchor`` or ``precision_gap`` is routine incompleteness and lives
#: on Timeline; promoting it here would turn an invitation into a chore list.
MIRROR_WORK_ITEM_KINDS = ("contradiction", "identity_uncertain")

#: The surface name a work item must allow. ``allowed_surfaces`` is the
#: mechanism §2.4 uses to keep sensitive discovery items off a surface, so an
#: item that does not list ``mirror`` is not rendered here even if its kind
#: matches.
MIRROR_SURFACE = "mirror"

#: What a row's derived state can be. There is no third value: ``dismissed``
#: and ``obsolete`` items simply do not render, and everything else is either
#: still disagreeing or no longer disagreeing.
ROW_STATES = ("open", "resolved")

#: Item states that never reach Mirror. ``dismissed`` is the person's own "not
#: this"; ``obsolete`` is the substrate saying the question stopped existing.
HIDDEN_ITEM_STATES = ("dismissed", "obsolete")

#: How many rows Mirror shows at once. Quiet is a product requirement, not a
#: performance one: the page is a place to see what actually conflicts, and a
#: hundred rows is a backlog. The rest stay available to any caller that asks
#: for them explicitly with a larger ``cap``.
MIRROR_ROW_CAP = 12

#: Bounded evidence in a Play target — enough for the conversation to be
#: grounded in the exact disagreement, never a transcript dump. §12's privacy
#: rule ("model context is bounded") applies to the prompt this feeds.
MAX_PLAY_EVIDENCE = 6

#: How many alternatives a row renders beside the best-supported reading.
#: Everything else stays in the claim substrate, which never drops anything.
MAX_ALTERNATIVES = 4

#: A contradiction whose claims are not dated — an ordering disagreement, an
#: identity claim — cannot be measured by :func:`chronology.conflict_strength`.
#: It is still a contradiction, so it sorts in the middle rather than at
#: either extreme, where an unmeasurable row would either crowd out measured
#: ones or vanish beneath them.
DEFAULT_CONTRADICTION_SEVERITY = 0.5

#: An identity question's severity when the item carries no ``system_value``.
#: "Who is this?" is real work but it is rarely more urgent than two dates
#: that cannot both be true, so it sits at the same neutral midpoint and
#: yields to a measured conflict.
DEFAULT_IDENTITY_SEVERITY = 0.5

#: The Play target's kind. One verb with a TARGET: Play on a Mirror row opens
#: a conversation grounded in *this* work item, exactly as Play on a timeline
#: unknown opens one grounded in that unknown.
#:
#: **ONE GAP, ONE CONVERSATION (v234).** The kind names the WORK ITEM, never
#: the surface the person happened to see it on. §2.3's cross-surface identity
#: — *"answering or resolving a temporal work item on any surface closes or
#: updates the same work item everywhere"* — is only true if the thing Play
#: opens is the same thing on Timeline, in Mirror, and in the daily queue. The
#: v227 spelling ``mirror_item`` baked one surface into that identity, so a
#: host binding Play would have had to grow a second kind the day a Timeline
#: gap got the same verb, and the two kinds would then have been two
#: conversations about one gap. The stage this target opens is
#: ``timeline_interaction.WORK_ITEM_STAGE``, and the two strings are the same
#: string on purpose (pinned by
#: ``test_the_play_kind_and_the_stage_are_one_word``).
PLAY_TARGET_KIND = "work_item"

#: Every kind string a Play target may ARRIVE as. v227–v233 emitted
#: ``mirror_item``; v234 accepted it on the read side for exactly one version
#: and promised its deletion in v235. This is v235: the alias is gone, the
#: tuple is the canonical kind alone, and a target still carrying the old word
#: is refused like any other stranger (pinned by
#: ``test_the_v227_alias_is_gone``).
PLAY_TARGET_KINDS = (PLAY_TARGET_KIND,)


def is_play_target_kind(value: object) -> bool:
    """Is this the Play kind?

    Canonically and only canonically since v235. v234 forgave v227's
    ``mirror_item`` on the read side for one version so stored targets kept
    opening; that version has passed and the two words are no longer one.
    """
    return collapsed_text(value) in PLAY_TARGET_KINDS

#: What :func:`resolve_mirror_item` can report. ``corrected`` means durable
#: evidence was written; it deliberately does NOT mean "closed", because
#: closure is derived from the claims and this function does not get a vote.
RESOLUTION_OUTCOMES = ("corrected", "abandoned")

#: Named refusals, so a caller can branch on a code instead of a message.
MIRROR_WORK_ERROR_CODES = (
    "work_items_unreadable",
    "mirror_item_not_actionable",
    "resolution_targets_uncited_claim",
    "resolution_needs_extractor_version",
    "resolution_publish_failed",
)


class MirrorWorkError(TemporalContractError):
    """A Mirror row or resolution the contract refuses."""


# --------------------------------------------------------------------------
# Reading the substrate — the entry point wave D wires
# --------------------------------------------------------------------------


def _root(vault_root: str | Path) -> Path:
    """The vault root, spelled exactly the way ``temporal_store`` spells it.

    Expanded and cwd-joined, never ``resolve()``d: the store's containment
    guard compares against this form, and a second normalization here would be
    a second definition of "which vault" — the thing ADR 0021 exists to stop.
    """
    root = Path(vault_root).expanduser()
    return root if root.is_absolute() else Path.cwd() / root


def load_work_items(vault_root: str | Path) -> list[dict]:
    """Every published temporal work item, or ``[]`` when none exist yet.

    This is the ONE seam between Mirror and the calculated projection. The
    minting side (wave D) publishes :data:`temporal_projection.WORK_ITEMS_FILE`
    atomically; this reads it and cares about nothing else — not how the items
    were derived, not which nodes they came from, not when the projection last
    ran. That is deliberate: Mirror must never become a reason the derivation
    has to know Mirror exists.

    A file that is absent means "the projection has not run", which is a normal
    early state and returns ``[]``. A file that is *present and unparseable* is
    not normal and is refused by name (``work_items_unreadable``) rather than
    silently read as empty — a read that zeroes itself on a bad byte is how a
    surface goes quietly blank in production and nobody notices for a week.

    Both published shapes are accepted: a bare list, or a mapping carrying the
    items under ``work_items`` (or ``items``) beside its own version fields.
    """
    root = _root(vault_root)
    path = store.store_path(root, WORK_ITEMS_FILE)
    if not path.is_file():
        return []
    try:
        content = read_vault_text(path, vault_root=root)
    except (OSError, ValueError) as exc:
        raise MirrorWorkError(
            "work_items_unreadable", f"{WORK_ITEMS_FILE} could not be read"
        ) from exc
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise MirrorWorkError(
            "work_items_unreadable", f"{WORK_ITEMS_FILE} is not JSON"
        ) from exc
    if isinstance(payload, dict):
        for key in ("work_items", "items"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        return []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    raise MirrorWorkError(
        "work_items_unreadable", f"{WORK_ITEMS_FILE} holds neither a list nor a mapping"
    )


def load_work_item_aliases(vault_root: str | Path) -> dict:
    """`{legacy_work_item_id: canonical_work_item_id}`, or `{}` (O-E6).

    Read from the SAME published file as the items themselves, so the map and
    the set it describes are one generation by construction — atomic
    publication already pairs them, and a second, separately-read table would
    be the drift this map exists to prevent.

    Absent is `{}`: a projection published before O-E6 has no map, and every id
    in it is then its own canonical id, which is exactly right.
    """
    root = _root(vault_root)
    path = store.store_path(root, WORK_ITEMS_FILE)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(read_vault_text(path, vault_root=root))
    except (OSError, ValueError):
        # `load_work_items` is the reader that refuses an unreadable file by
        # name. Refusing twice for the same byte would turn one honest error
        # into two, so the map degrades and the items raise.
        return {}
    aliases = payload.get("work_item_aliases") if isinstance(payload, dict) else None
    if not isinstance(aliases, dict):
        return {}
    return {
        collapsed_text(old): collapsed_text(new)
        for old, new in aliases.items()
        if collapsed_text(old) and collapsed_text(new)
    }


def resolve_work_item_id(ref: object, *, aliases: object = None) -> str:
    """One stored reference to the id it is addressed by now — the ONE lookup.

    Re-exported from `temporal_work_items` so Mirror has a single door and no
    caller writes `aliases.get(ref, ref)` by hand.
    """
    return twi.resolve_work_item_id(ref, aliases=aliases)


def load_active_index(vault_root: str | Path) -> dict:
    """The published active claim index, folded on demand when absent.

    The fold is pure and cheap and the published index is a materialized view,
    so "it has not been published yet" is never a reason for Mirror to show a
    person nothing. Nothing is written either way — reading Mirror must not
    have side effects on the substrate.
    """
    index = store.read_active_index(vault_root)
    if isinstance(index, dict):
        return index
    return store.fold_active_index(vault_root)


def _claims_by_id(index: object) -> dict[str, dict]:
    rows = index.get("claims") if isinstance(index, dict) else None
    return {
        str(row.get("claim_id")): row
        for row in (rows or ())
        if isinstance(row, dict) and row.get("claim_id")
    }


# --------------------------------------------------------------------------
# The row
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class MirrorWorkRow:
    """One actionable Mirror row: what conflicts, what the sources say, Play.

    Everything on it is either the work item's own (``work_item_id``, ``kind``)
    or derived from the current claim index (``state``, ``best_supported``,
    ``alternatives``, ``citations``, ``severity``). Nothing is stored, so a row
    cannot go stale relative to the substrate and there is no row-state file to
    reconcile.
    """

    work_item_id: str
    kind: str
    state: str
    headline: str
    description: str
    severity: float
    subject_ref: str | None = None
    event_ref: str | None = None
    node_ref: str | None = None
    best_supported: dict | None = None
    alternatives: tuple[dict, ...] = ()
    candidates: tuple[dict, ...] = ()
    citations: tuple[dict, ...] = ()
    claim_refs: tuple[str, ...] = ()
    active_claim_refs: tuple[str, ...] = ()
    missing_claim_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    prompt_intent: str | None = None
    updated_at: str = ""
    play: dict = field(default_factory=dict)

    @property
    def is_open(self) -> bool:
        return self.state == "open"

    def to_dict(self) -> dict:
        payload: dict = {
            "work_item_id": self.work_item_id,
            "kind": self.kind,
            "state": self.state,
            "headline": self.headline,
            "description": self.description,
            "severity": self.severity,
            "best_supported": self.best_supported,
            "alternatives": [dict(a) for a in self.alternatives],
            "candidates": [dict(c) for c in self.candidates],
            "citations": [dict(c) for c in self.citations],
            "claim_refs": list(self.claim_refs),
            "active_claim_refs": list(self.active_claim_refs),
            "missing_claim_refs": list(self.missing_claim_refs),
            "evidence_refs": list(self.evidence_refs),
            "updated_at": self.updated_at,
            "play": dict(self.play),
        }
        for key, value in (
            ("subject_ref", self.subject_ref),
            ("event_ref", self.event_ref),
            ("node_ref", self.node_ref),
            ("prompt_intent", self.prompt_intent),
        ):
            if value is not None:
                payload[key] = value
        return payload


def is_mirror_kind(kind: object) -> bool:
    """Does this work item kind render as an actionable Mirror row?"""
    return collapsed_text(kind) in MIRROR_WORK_ITEM_KINDS


#: Rows whose label is the FIELD they ask about, not the claims they cite.
#: A contradiction is normally between two datings of one event, and the cited
#: claims name it. A birth origin calculated from age statements is a
#: contradiction between two DERIVED readings, and its cited claims are about
#: whatever events those ages were stated at — labelling it from them would
#: read "about I — graduation" for a row that is about a birthday. The item
#: already says which field it wants; where that answers the question better
#: than the claims do, it wins.
LABELS_BY_REQUESTED_FIELD = {"birth_date": "your birthday"}


def _label(item: TemporalWorkItem, claims: list[dict]) -> str:
    """A short human handle for what the row is about, from what we have.

    The raw mention comes first because it is the person's own word for the
    thing (§5.1 keeps it on every claim for exactly this reason), and a row
    that says "Katie — married" is legible where one saying ``node:9f3c…`` is
    not. A contradiction names the event too; an identity row is about the
    mention alone — "Who is AJ?", never "Who is AJ — met?".

    :data:`LABELS_BY_REQUESTED_FIELD` comes first for the rows it names.
    """
    by_field = LABELS_BY_REQUESTED_FIELD.get(collapsed_text(item.requested_field))
    if by_field:
        return by_field
    for claim in claims:
        mention = collapsed_text(claim.get("subject_mention"))
        if not mention:
            continue
        if item.kind == "identity_uncertain":
            return mention
        event = collapsed_text(claim.get("event_kind")).replace("_", " ")
        return f"{mention} — {event}" if event else mention
    for ref in (item.subject_ref, item.event_ref, item.node_ref):
        text = collapsed_text(ref)
        if text:
            return _ref_display(text)
    return item.work_item_id


def _ref_display(ref: object) -> str:
    """``person/aj-lang`` → ``aj lang``; ``unresolved:aj`` → ``aj``."""
    text = collapsed_text(ref)
    if not text:
        return ""
    tail = text.split(":", 1)[1] if ":" in text else text
    tail = tail.rsplit("/", 1)[-1]
    return tail.replace("-", " ").replace("_", " ").strip() or text


def _source_view(claim: dict) -> dict:
    """The citation for one claim — where it came from and what it said."""
    source_ref = claim.get("source_ref") if isinstance(claim.get("source_ref"), dict) else {}
    quote = ""
    for span in claim.get("evidence") or ():
        if isinstance(span, dict):
            quote = bounded_quote(span.get("quote"))
            if quote:
                break
    view: dict = {
        "claim_id": collapsed_text(claim.get("claim_id")),
        "source_id": collapsed_text(source_ref.get("source_id")),
        "revision": collapsed_text(source_ref.get("revision")),
        "status": collapsed_text(claim.get("status")) or "active",
    }
    source_path = optional_text(source_ref.get("source_path"))
    if source_path:
        view["source_path"] = source_path
    if quote:
        view["quote"] = quote
    return view


def _reading(record: object, supporters: list[dict]) -> dict:
    """One dated reading: what it says, how well held, and who says so."""
    return {
        "display": chrono.display_date(record),
        "edtf": chrono.to_edtf(record),
        "basis": getattr(record, "basis", ""),
        "confidence": getattr(record, "confidence", ""),
        "score": round(chrono.claim_score(record), 4),
        "claim_refs": [collapsed_text(c.get("claim_id")) for c in supporters],
        "sources": [_source_view(c) for c in supporters],
    }


def _dated_view(active: list[dict]) -> dict | None:
    """Reconcile the row's active dated claims; ``None`` when none are dated.

    The reconciliation is `chronology.reconcile` — the package's one place
    where rival datings are ordered — run as a pure read (§6.5: reconciliation
    is never a mutating write authority). Nothing is dropped: the winner is the
    best-supported reading and every rival comes back as an alternative with
    the sources that support it.

    Supporters are recovered through ``chronology.claim_identity``, the same
    key ``merge_claims`` folds on, so two claims saying the same thing map to
    the one merged reading they produced instead of being counted twice.
    """
    records: list[object] = []
    by_identity: dict[tuple[str, str], list[dict]] = {}
    for claim in active:
        record = chrono.from_dict(claim.get("temporal_value"))
        if record is None:
            continue
        key = chrono.claim_identity(record)
        if key is None:
            continue
        by_identity.setdefault(key, []).append(claim)
        records.append(record)
    if not records:
        return None
    result = chrono.reconcile(records)
    best = result.get("best_supported")
    if best is None:
        return None

    def supporters(record: object) -> list[dict]:
        key = chrono.claim_identity(record)
        return by_identity.get(key, []) if key else []

    return {
        "best_supported": _reading(best, supporters(best)),
        "alternatives": [
            _reading(alt, supporters(alt))
            for alt in (result.get("alternates") or ())[:MAX_ALTERNATIVES]
        ],
        "conflict": round(float(result.get("conflict") or 0.0), 4),
        "dated_claims": len(records),
    }


def _uncertain_identity(claim: dict) -> bool:
    """Is this claim's subject still genuinely unplaced?

    Three ways to be unresolved and they all count: no subject at all, a
    subject that is the ``unresolved:`` handle rather than an entity, and a
    resolution record whose reason is one of
    :data:`identity_resolution.UNCERTAIN_REASONS` — "we looked and could not
    tell" is a decision the claim carries, not an absence.
    """
    subject_ref = collapsed_text(claim.get("subject_ref"))
    if not subject_ref or ident.is_unresolved_ref(subject_ref):
        return True
    resolution = claim.get("subject_resolution")
    if isinstance(resolution, dict):
        return collapsed_text(resolution.get("reason")) in ident.UNCERTAIN_REASONS
    return False


def _candidate_views(active: list[dict]) -> tuple[dict, ...]:
    """The candidate set an identity row offers, unioned over its claims.

    A claim carries the *summary* of §6.3's reversibility record —
    ``{candidates: [ref, ...], reason, confidence}`` — so refs are what Mirror
    has, and a ref is shown as its own readable tail rather than being looked
    up in a roster this module deliberately does not read.
    """
    views: dict[str, dict] = {}
    for claim in active:
        resolution = claim.get("subject_resolution")
        if not isinstance(resolution, dict):
            continue
        for raw in resolution.get("candidates") or ():
            ref = collapsed_text(raw.get("ref") if isinstance(raw, dict) else raw)
            if not ref:
                continue
            view = views.setdefault(
                ref, {"ref": ref, "name": _ref_display(ref), "claim_refs": []}
            )
            claim_id = collapsed_text(claim.get("claim_id"))
            if claim_id and claim_id not in view["claim_refs"]:
                view["claim_refs"].append(claim_id)
    return tuple(views.values())


def _cite(views: list[dict]) -> str:
    """``(source: msg-abc)`` — the voice contract's inline citation."""
    ids = [v.get("source_id") or v.get("claim_id") for v in views if v]
    ids = [str(i) for i in ids if i]
    if not ids:
        return ""
    label = "source" if len(ids) == 1 else "sources"
    return f" ({label}: {', '.join(ids)})"


def moves_cited(item: TemporalWorkItem) -> tuple[str, ...]:
    """The ordering constraints a contradiction cites — what a DRAG contributed.

    A contradiction between a filed move and a stated date has one claim on one
    side and a constraint on the other, so counting active claims alone reads it
    as a settled row and Mirror silently drops it (plan §2.6: *"if the new
    constraint conflicts with an explicit date, keep both claims and
    create/update a Mirror contradiction"*). The refs travel in ``claim_refs``
    because the projection mints one ref list per item; the ``constraint:``
    prefix is what separates the two kinds, and it is frozen contract.

    A constraint id only reaches a published work item while the constraint is
    ACTIVE — the derivation drops superseded and retracted ones before it builds
    an edge — so a ref appearing here is itself the proof that the move stands.
    """
    return tuple(
        ref for ref in item.claim_refs
        if collapsed_text(ref).startswith(f"{CONSTRAINT_ID_PREFIX}:")
    )


def _describe_contradiction(
    label: str, view: dict | None, active: list[dict], *, moves: int = 0
) -> str:
    """Evidence-grounded prose. Every sentence cites, or it is not written."""
    if moves and active:
        if view is not None:
            best = view["best_supported"]
            stated = f"{best['display']}{_cite(best['sources'])}"
        else:
            stated = ", ".join(
                f"{collapsed_text(c.get('subject_mention'))}{_cite([_source_view(c)])}"
                for c in active[:MAX_ALTERNATIVES]
            )
        return (
            f"You moved {label} on the timeline, and the order that gives it "
            f"doesn't fit what you've said about when it happened: {stated}. "
            "The move and the date both stay on the record."
        )
    if view is None:
        cited = ", ".join(
            f"{collapsed_text(c.get('subject_mention'))}{_cite([_source_view(c)])}"
            for c in active[:MAX_ALTERNATIVES]
        )
        return (
            f"Two things you've said about {label} can't both be true: {cited}. "
            "Both stay on the record until you settle it."
        )
    best = view["best_supported"]
    alternatives = view["alternatives"]
    if not alternatives:
        return (
            f"You've said {best['display']}{_cite(best['sources'])} about {label}. "
            "The claims that disagreed with it no longer stand."
        )
    rivals = " and ".join(
        f"{alt['display']}{_cite(alt['sources'])}" for alt in alternatives
    )
    return (
        f"About {label}, you've said {best['display']}{_cite(best['sources'])} "
        f"and also {rivals}. The timeline shows {best['display']} for now, and "
        "every reading stays on the record."
    )


def _describe_identity(label: str, candidates: tuple[dict, ...], active: list[dict]) -> str:
    citation = _cite([_source_view(c) for c in active[:2]])
    if not candidates:
        return (
            f"You've mentioned {label}{citation} and it isn't settled who that "
            "is. Nothing was guessed — the words are kept exactly as you said them."
        )
    names = " or ".join(c["name"] or c["ref"] for c in candidates)
    return (
        f"You've mentioned {label}{citation} and it could be {names}. "
        "Nothing was guessed — the claim is kept as it was said until you say which."
    )


def row_for(item: object, index: object, *,
            aliases: object = None) -> MirrorWorkRow | None:
    """Render ONE work item as a Mirror row against the current claim index.

    ``None`` — not an exception — for anything Mirror does not show: a kind
    outside :data:`MIRROR_WORK_ITEM_KINDS`, an item that does not allow the
    ``mirror`` surface, a dismissed or obsolete item, and an item the contract
    itself refuses. A read surface degrades to "no row"; it does not take the
    page down.

    The returned row's ``state`` is derived here and nowhere else. See
    :func:`derive_row_state`.
    """
    normalized = work_item_from_dict(item)
    if normalized is None:
        return None
    if not is_mirror_kind(normalized.kind):
        return None
    if MIRROR_SURFACE not in normalized.allowed_surfaces:
        return None
    if normalized.state in HIDDEN_ITEM_STATES:
        return None

    claims = _claims_by_id(index)
    cited = [claims[ref] for ref in normalized.claim_refs if ref in claims]
    missing = tuple(ref for ref in normalized.claim_refs if ref not in claims)
    active = [claim for claim in cited if claim.get("status") == "active"]

    view = _dated_view(active) if normalized.kind == "contradiction" else None
    candidates = (
        _candidate_views(active) if normalized.kind == "identity_uncertain" else ()
    )
    moves = moves_cited(normalized)
    state = derive_row_state(normalized, active, view=view, moves=len(moves))
    label = _label(normalized, cited)

    if normalized.kind == "contradiction":
        headline = (
            f"A move that doesn't fit {label}"
            if moves and active
            else (f"Two dates for {label}" if view else f"A disagreement about {label}")
        )
        description = _describe_contradiction(label, view, active, moves=len(moves))
        severity = (
            float(view["conflict"])
            if view is not None and view["conflict"] > 0
            else (0.0 if state == "resolved" else DEFAULT_CONTRADICTION_SEVERITY)
        )
    else:
        headline = f"Who is {label}?"
        description = _describe_identity(label, candidates, active)
        severity = float(
            normalized.scores.get("system_value", DEFAULT_IDENTITY_SEVERITY)
            if state == "open"
            else 0.0
        )

    row = MirrorWorkRow(
        # O-E6: a published generation written before the vocabulary converged
        # holds legacy ids, and a Play target minted from one has to keep
        # opening. Resolution decides what a row IS the same as; it never
        # rewrites what the item itself says.
        work_item_id=resolve_work_item_id(normalized.work_item_id, aliases=aliases),
        kind=normalized.kind,
        state=state,
        headline=headline,
        description=description,
        severity=round(severity, 4),
        subject_ref=normalized.subject_ref,
        event_ref=normalized.event_ref,
        node_ref=normalized.node_ref,
        best_supported=(view or {}).get("best_supported"),
        alternatives=tuple((view or {}).get("alternatives") or ()),
        candidates=candidates,
        citations=tuple(_source_view(claim) for claim in cited),
        claim_refs=tuple(normalized.claim_refs),
        active_claim_refs=tuple(
            collapsed_text(claim.get("claim_id")) for claim in active
        ),
        missing_claim_refs=missing,
        evidence_refs=tuple(normalized.evidence_refs),
        prompt_intent=normalized.prompt_intent,
        updated_at=normalized.updated_at,
    )
    return _with_play(row)


def derive_row_state(
    item: TemporalWorkItem,
    active: list[dict],
    *,
    view: dict | None = None,
    moves: int = 0,
) -> str:
    """``open`` or ``resolved``, decided by the claims and by nothing else.

    §2.5: *a contradiction closes only when its active claims no longer
    conflict or an explicit correction/supersession settles it.* Both halves
    of that sentence land in the same place here, because a correction's whole
    effect is that a claim stops being active:

    * A **contradiction** with fewer than two active claims cannot conflict —
      the correction retired one side, so it is resolved.
    * A contradiction whose active claims are all dated and whose reconciled
      conflict strength is zero is resolved too: *1984* beside *1980/1990* is
      corroboration at a coarser grain, not a disagreement.
    * If any active claim is undated, the row stays **open**. We cannot
      measure that it stopped conflicting, and guessing closure in the
      person's favour would hide a real disagreement.
    * An **identity_uncertain** row is open while any active claim it cites
      still has an unplaced subject, and resolved once none do — which is what
      happens when a new receipt supersedes the uncertain claim with a
      resolved one.

    The item's *stored* ``state`` is deliberately not consulted. A row that
    could be closed by writing to the row would make the row a second source
    of truth about claims it does not own.
    """
    if item.kind == "contradiction":
        # A filed move is a SIDE. `moves` is how many ordering constraints this
        # item cites (:func:`moves_cited`), and a drag that disagrees with one
        # stated date is a two-sided row even though only one side is a claim.
        if len(active) + moves < 2:
            return "resolved"
        if moves:
            return "open"
        if view is not None and view["dated_claims"] == len(active) and view["conflict"] <= 0:
            return "resolved"
        return "open"
    if not active:
        return "resolved"
    return "open" if any(_uncertain_identity(claim) for claim in active) else "resolved"


# --------------------------------------------------------------------------
# The Play target
# --------------------------------------------------------------------------


def play_target(row: MirrorWorkRow) -> dict:
    """The target Play opens for this row — one verb, one exact item.

    Shaped like every other package-side target (``kind`` / ``ref`` / ``label``
    plus what that kind needs; compare
    ``timeline_interaction.timeline_plan``'s target), so a host binds one
    Play verb rather than one per surface. ``ref`` is the ``work_item_id``:
    the conversation is grounded in *this* disagreement, and whatever it
    resolves closes this row wherever it appears.

    The evidence carried is bounded (:data:`MAX_PLAY_EVIDENCE`) and made of
    quotations already stored on the claims. A grounded conversation needs the
    two things that disagree and the words they came from — not a transcript.

    ``resolvable_claim_ids`` is the *only* set :func:`resolve_mirror_item`
    will retire. A conversation cannot reach past its own row.
    """
    evidence: list[dict] = []
    for citation in row.citations:
        if citation.get("status") != "active":
            continue
        if not citation.get("quote"):
            continue
        evidence.append(
            {
                "claim_id": citation["claim_id"],
                "source_id": citation.get("source_id", ""),
                "quote": citation["quote"],
            }
        )
        if len(evidence) >= MAX_PLAY_EVIDENCE:
            break

    target: dict = {
        "kind": PLAY_TARGET_KIND,
        "ref": row.work_item_id,
        "label": row.headline,
        "item_kind": row.kind,
        "work_item_id": row.work_item_id,
        "evidence": evidence,
        "resolvable_claim_ids": list(row.active_claim_refs),
    }
    if row.prompt_intent:
        target["prompt_intent"] = row.prompt_intent
    for key, value in (
        ("subject_ref", row.subject_ref),
        ("event_ref", row.event_ref),
        ("node_ref", row.node_ref),
    ):
        if value:
            target[key] = value
    if row.best_supported:
        target["best_supported"] = dict(row.best_supported)
    if row.alternatives:
        target["alternatives"] = [dict(a) for a in row.alternatives]
    if row.candidates:
        target["candidates"] = [dict(c) for c in row.candidates]
    return target


def _with_play(row: MirrorWorkRow) -> MirrorWorkRow:
    """Every actionable row gets Play (§2.5). Not a subset, not a threshold."""
    return replace(row, play=play_target(row))


# --------------------------------------------------------------------------
# The rows
# --------------------------------------------------------------------------


def row_sort_key(row: MirrorWorkRow) -> tuple:
    """Hardest disagreement first; ties broken by identity, never by clock.

    A clock in the sort would reorder the page between two reads of the same
    substrate, and "the row moved" is indistinguishable from "the row changed"
    to a person looking at it.
    """
    return (-row.severity, -len(row.active_claim_refs), row.work_item_id)


def mirror_rows(
    work_items: object,
    index: object,
    *,
    cap: int = MIRROR_ROW_CAP,
    include_resolved: bool = False,
    aliases: object = None,
) -> list[MirrorWorkRow]:
    """Every actionable row, hardest first, capped. Pure — no vault, no clock.

    Resolved rows are excluded by default: a settled disagreement is history,
    and history belongs in the claim substrate, which still holds every claim
    that ever stood. ``include_resolved=True`` is for callers that want to show
    the person what they closed.
    """
    rows: list[MirrorWorkRow] = []
    for item in work_items or ():
        row = row_for(item, index, aliases=aliases)
        if row is None:
            continue
        if not include_resolved and row.state != "open":
            continue
        rows.append(row)
    rows.sort(key=row_sort_key)
    limit = max(0, int(cap)) if cap is not None else len(rows)
    return rows[:limit]


def load_mirror_rows(
    vault_root: str | Path,
    *,
    cap: int = MIRROR_ROW_CAP,
    include_resolved: bool = False,
) -> list[MirrorWorkRow]:
    """The vault-bound read: work items + active claims → rows. Writes nothing."""
    return mirror_rows(
        load_work_items(vault_root),
        load_active_index(vault_root),
        cap=cap,
        include_resolved=include_resolved,
        aliases=load_work_item_aliases(vault_root),
    )


# --------------------------------------------------------------------------
# Resolution — a correction with a receipt, or nothing at all
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class MirrorResolution:
    """What a Play conversation actually wrote, and what it deliberately did not.

    ``outcome`` is ``corrected`` or ``abandoned``. It is never "closed":
    whether the row closes is derived from the claims by
    :func:`derive_row_state`, and this record does not get a vote in it.
    """

    work_item_id: str
    outcome: str
    reason: str = ""
    retired_claim_ids: tuple[str, ...] = ()
    correction_id: str | None = None
    correction_path: str | None = None
    source_id: str | None = None
    source_path: str | None = None
    receipt_path: str | None = None
    #: The generation this resolution published (O-E6, design §10). ``None`` on
    #: an abandoned resolution, which writes nothing and therefore changes
    #: nothing to publish.
    projection_generation: int | None = None

    @property
    def wrote_correction(self) -> bool:
        return self.outcome == "corrected"

    def to_dict(self) -> dict:
        payload: dict = {
            "work_item_id": self.work_item_id,
            "outcome": self.outcome,
            "reason": self.reason,
            "retired_claim_ids": list(self.retired_claim_ids),
        }
        for key, value in (
            ("correction_id", self.correction_id),
            ("correction_path", self.correction_path),
            ("source_id", self.source_id),
            ("source_path", self.source_path),
            ("receipt_path", self.receipt_path),
            ("projection_generation", self.projection_generation),
        ):
            if value is not None:
                payload[key] = value
        return payload


def _actionable(item: object) -> TemporalWorkItem:
    normalized = work_item_from_dict(item)
    if normalized is None or not is_mirror_kind(normalized.kind):
        raise MirrorWorkError(
            "mirror_item_not_actionable",
            "a Mirror resolution acts on a contradiction or an identity item",
        )
    return normalized


def abandon_mirror_item(item: object, *, reason: str = "") -> MirrorResolution:
    """"I don't know", a skip, a closed tab — and nothing is written. §2.5.

    This function takes **no vault root**, which is the point: the path out of
    a Play conversation that did not settle anything cannot write a correction
    even by mistake. The item remains available, exactly as it was, and the row
    stays open because its claims still disagree.
    """
    normalized = _actionable(item)
    return MirrorResolution(
        work_item_id=normalized.work_item_id,
        outcome="abandoned",
        reason=collapsed_text(reason),
    )


def resolve_mirror_item(
    vault_root: str | Path,
    *,
    item: object,
    resolution_text: str,
    retire_claim_ids: object = (),
    correction_kind: str = "supersede",
    publish: bool = True,
    claims_for: object = None,
    extractor_version: str | None = None,
    extractor: object = None,
    recorder: str | None = None,
    metadata: object = None,
    author: str | None = None,
    now: object = None,
) -> MirrorResolution:
    """Write what the person said as durable evidence, then retire what it settles.

    The order is the store's pairing rule and it is not negotiable:

    1. **The person's words become a source.** ``promote_conversational_source``
       files the resolution as an ordinary vault document, so the correction's
       reason has a citation and no claim's only evidence is a session row.
    2. **Replacements are new claims through a new receipt.** Pass
       ``claims_for`` — the same callable ``file_message_extraction`` takes,
       receiving the promoted :class:`SourceRef` — and the replacement is filed
       as an extraction over the words that produced it, provenanced exactly
       like the claim it replaces. Omit it and nothing new is asserted; the
       resolution only retires.
    3. **A correction retires the losing claims.** ``supersede`` by default,
       ``retract`` or ``dispute`` when that is what happened. The correction is
       a source too: written once, never edited, read by every fold. The claim
       is *not* deleted and never will be.

    Then the row closes — or does not — because the next fold says so.

    Two refusals guard the seam. ``resolution_targets_uncited_claim``: Mirror
    may only retire claims the row itself cites, so a conversation cannot reach
    past its own disagreement. ``resolution_needs_extractor_version``: claims
    without an extractor version are unprovenanced, and this is not the place
    that gets to invent one.

    And the quiet case, which is the one §2.5 spends a whole bullet on: **no
    resolution text, or nothing named to retire, writes nothing at all** and
    returns an ``abandoned`` outcome. Opening Play and leaving invents no
    correction. Every call here is idempotent — the promotion, the receipt and
    the correction are each keyed by content — so a retried resolution is one
    record, not two.

    **Then it PUBLISHES** (O-E6; `eras.md` §10). A correction that only reaches
    the receipts leaves every surface showing the row the person just closed —
    Timeline, the whisper lane, the daily queue and Mirror itself all read the
    PUBLISHED generation, and "answer once, closed everywhere" is a promise
    about what they show, not about what the store holds. The order is the one
    that cannot lose the answer: the correction is durable BEFORE the
    projection is derived, so a publish that fails raises
    ``resolution_publish_failed`` naming the correction that survived it, and
    a retry republishes with nothing written twice. ``publish=False`` is for a
    caller batching several resolutions into one generation; it is never a way
    to skip the publish.
    """
    normalized = _actionable(item)
    text = collapsed_text(resolution_text)
    targets = sorted({collapsed_text(ref) for ref in (retire_claim_ids or ()) if collapsed_text(ref)})
    if not text or not targets:
        return abandon_mirror_item(normalized, reason=text)

    uncited = [ref for ref in targets if ref not in normalized.claim_refs]
    if uncited:
        raise MirrorWorkError(
            "resolution_targets_uncited_claim",
            f"{normalized.work_item_id} does not cite {', '.join(uncited)}",
            detail={"work_item_id": normalized.work_item_id, "claims": uncited},
        )

    meta = dict(metadata) if isinstance(metadata, dict) else {}
    receipt_path: Path | None = None
    if callable(claims_for):
        if not collapsed_text(extractor_version):
            raise MirrorWorkError(
                "resolution_needs_extractor_version",
                "a replacement claim names the extractor version that produced it",
            )
        source_ref, receipt_path = store.file_message_extraction(
            vault_root,
            message_text=text,
            extractor_version=str(extractor_version),
            claims_for=claims_for,
            metadata=meta,
            extractor=extractor,
            recorder=recorder,
            now=now,
        )
    else:
        source_ref = store.promote_conversational_source(vault_root, text, meta)

    correction = store.file_temporal_correction(
        vault_root,
        kind=correction_kind,
        claim_ids=targets,
        reason=text,
        scope=normalized.work_item_id,
        title=f"Mirror resolution — {normalized.kind}",
        author=author,
        occurred_at=now,
    )

    generation: int | None = None
    if publish:
        try:
            import temporal_publication  # noqa: PLC0415

            generation = int(temporal_publication.publish(vault_root, now=now)
                             .get("generation") or 0)
        except Exception as exc:  # noqa: BLE001
            # LOUD, and naming what survived: the correction is already on
            # disk, content-keyed, so the caller can retry the publish (or let
            # the next compile do it) without writing anything twice. Swallowing
            # this would leave the person looking at the row they just closed
            # with nothing anywhere saying why.
            raise MirrorWorkError(
                "resolution_publish_failed",
                f"{normalized.work_item_id} was corrected but not published: {exc}",
                detail={
                    "work_item_id": normalized.work_item_id,
                    "correction_id": correction.correction_id,
                    "correction_path": correction.relative_path,
                },
            ) from exc

    return MirrorResolution(
        work_item_id=normalized.work_item_id,
        outcome="corrected",
        reason=text,
        retired_claim_ids=tuple(targets),
        correction_id=correction.correction_id,
        correction_path=correction.relative_path,
        source_id=source_ref.source_id,
        source_path=source_ref.source_path,
        receipt_path=(
            receipt_path.relative_to(_root(vault_root)).as_posix()
            if receipt_path is not None
            else None
        ),
        projection_generation=generation,
    )


__all__ = [
    "DEFAULT_CONTRADICTION_SEVERITY",
    "LABELS_BY_REQUESTED_FIELD",
    "DEFAULT_IDENTITY_SEVERITY",
    "HIDDEN_ITEM_STATES",
    "MAX_ALTERNATIVES",
    "MAX_PLAY_EVIDENCE",
    "MIRROR_ROW_CAP",
    "MIRROR_SURFACE",
    "MIRROR_WORK_ERROR_CODES",
    "MIRROR_WORK_ITEM_KINDS",
    "PLAY_TARGET_KIND",
    "PLAY_TARGET_KINDS",
    "RESOLUTION_OUTCOMES",
    "ROW_STATES",
    "MirrorResolution",
    "MirrorWorkError",
    "MirrorWorkRow",
    "abandon_mirror_item",
    "derive_row_state",
    "is_mirror_kind",
    "is_play_target_kind",
    "load_active_index",
    "load_mirror_rows",
    "load_work_item_aliases",
    "load_work_items",
    "mirror_rows",
    "moves_cited",
    "play_target",
    "resolve_mirror_item",
    "resolve_work_item_id",
    "row_for",
    "row_sort_key",
]
