"""One gap, one work id — the vocabulary every surface asks in (O-E6).

Two lanes reach the same question and always have. The **substrate** folds the
claims and mints a `TemporalWorkItem` naming the field it is missing in its own
vocabulary — `birth_date`, `date`, `start_date`, `order`. The **keystone** lane
looks at the timeline's own unknowns and mints the same ask under one flat
spelling, `temporal_anchor`. Because `requested_field` is inside
:data:`temporal_projection.WORK_ITEM_IDENTITY_KEYS`, that is not a cosmetic
difference: it is two identities for one question, and answer-once closure is
BY IDENTITY. The person answers their own birthday on Timeline and the daily
question asks for it again the same week.

This module is the one place that says which spelling is canonical, which
spellings are legacy, and how a stored reference to a legacy one is resolved:

* :data:`CANONICAL_REQUESTED_FIELDS` — the substrate's vocabulary wins. It is
  the richer one; a lane that only knows "some anchor" can always widen into
  it, and nothing can narrow back.
* :func:`canonical_ask` — the whole identity tuple, canonicalized together.
  The birth origin needs both halves moved (`birth` anchor → `self` subject,
  `temporal_anchor` → `birth_date`), and moving one without the other would
  produce a third id rather than one.
* :func:`work_item_aliases` — the DERIVED map `{legacy_id: canonical_id}`,
  published beside the items in the same generation. No new state: it is a
  pure function of the items, so deleting it and rebuilding is byte-identical.
* :func:`resolve_work_item_id` — the ONE lookup. Bank markers, sessions,
  whispers and Play targets all pass through it, which is what lets an id
  minted last month keep opening its conversation.

Two rules the alias map keeps, because both are ways of being wrong:

1. **An alias never crosses `kind`.** A `precision_gap` on a known-but-coarse
   birthday is a different question from the `missing_anchor` that asks for
   the birthday at all. Folding them would close one by answering the other.
2. **Two canonical items claiming one legacy id drop the alias.** A guess here
   would silently reroute a person's answer onto somebody else's question; an
   unresolved id merely fails to dedupe, which is visible.

The birth origin also owns its own score. `eras.md` §7 states it as
`system_value = clamp(0.6 + min(0.4, age_claims / REACH_SATURATION), 0, 1)`
under rule `temporal-score:2`: the scaffold term is the honest statement that
the birth origin is the coordinate system every age frame is derived from
(§3), not one more gap competing on reach, and the reach term is the ordinary
evidence on top. Without it the one item that unlocks the whole coordinate
system scores zero on the vault that has no dates yet.

Synthetic data only; NEVER references any real vault.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import chronology as chrono  # noqa: E402
import temporal_claims as tc  # noqa: E402
import temporal_projection as tp  # noqa: E402
from temporal_claims import collapsed_text  # noqa: E402

# --------------------------------------------------------------------------
# Who and how much
# --------------------------------------------------------------------------

#: The vault owner's subject ref in the claim substrate. Re-exported by
#: `temporal_timeline.DEFAULT_OWNER_REF` so there is one spelling of "me".
OWNER_SUBJECT_REF = "self"

#: Reach saturates: an anchor that would place five unplaced nodes is already
#: as valuable as this release knows how to say. Lives here rather than in the
#: fold because it is a property of a work item's worth, and both the fold and
#: the birth-origin rule need it. `temporal_timeline` re-exports it.
REACH_SATURATION = 5

# --------------------------------------------------------------------------
# The vocabulary
# --------------------------------------------------------------------------

#: What the substrate asks for, by name. This is the CANONICAL vocabulary: a
#: work item's `requested_field` is one of these or it is legacy.
REQUESTED_FIELD_BIRTH_DATE = "birth_date"
REQUESTED_FIELD_DATE = "date"
REQUESTED_FIELD_START_DATE = "start_date"
REQUESTED_FIELD_ORDER = "order"

CANONICAL_REQUESTED_FIELDS = (
    REQUESTED_FIELD_BIRTH_DATE,
    REQUESTED_FIELD_DATE,
    REQUESTED_FIELD_START_DATE,
    REQUESTED_FIELD_ORDER,
)

#: The keystone lane's single pre-O-E6 spelling. It is DEPRECATED and this
#: module is the only place in `system/` allowed to name it — a guard test
#: (`tests/test_work_item_aliases.py`) fails the build if the literal appears
#: anywhere else, because a second minter is exactly how the two identities
#: grew in the first place.
LEGACY_REQUESTED_FIELD = "temporal_anchor"

#: What an unrecognized legacy field widens to. A keystone that named no field
#: was always asking "when was this", which is `date`.
DEFAULT_CANONICAL_REQUESTED_FIELD = REQUESTED_FIELD_DATE

#: The event kind of the owner's birth, and the anchor spellings that have ever
#: meant it. `timeline`'s own anchor index keys it `"birth"` (`timeline.py`
#: `:3038`); the others are spellings this repo or a stored session may carry.
BIRTH_ORIGIN_EVENT_KIND = "birth"
BIRTH_ANCHOR_KEYS = (
    "birth",
    "birth_date",
    "self:birth",
    "owner:birth",
    "anchor:birth",
    "landmark:birth",
    "tl:birth",
)

#: The work-item kind the birth origin is asked as.
BIRTH_ORIGIN_KIND = "missing_anchor"

# --------------------------------------------------------------------------
# The birth origin's own score (design §7, rule `temporal-score:2`)
# --------------------------------------------------------------------------

#: The scoring rule this release derives under. Recorded on the birth-origin
#: item as `score_rule` and re-exported as
#: `temporal_timeline.SCORE_FORMULA_VERSION`, so a queue built under the older
#: formula is recognizable rather than silently comparable. v224 derived under
#: `temporal-score:1`, which stated the birth origin's worth as reach alone.
SCORE_FORMULA_VERSION = "temporal-score:2"

#: The same rule, named for what it changed. Stamped on the item itself so the
#: item can say which arithmetic minted its `system_value` without a reader
#: having to hold the envelope too.
BIRTH_ORIGIN_SCORE_RULE = SCORE_FORMULA_VERSION

#: "The coordinate system exists" — what the birth origin is worth before any
#: evidence at all. Not a priority CLASS: it is a stated term in one formula,
#: readable, versioned, and it competes on the same combined score as
#: everything else.
BIRTH_ORIGIN_SCAFFOLD_VALUE = 0.6

#: The most the ordinary reach evidence may add on top of the scaffold.
BIRTH_ORIGIN_REACH_CEILING = 0.4


def clamp_unit(value: object, default: float = 0.0) -> float:
    """``0.0..1.0``, or ``default`` when the number is unusable."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float(default)
    if math.isnan(number):
        return float(default)
    return max(0.0, min(1.0, number))


def birth_origin_system_value(age_claims: object = 0, *,
                              saturation: object = None) -> float:
    """`clamp(0.6 + min(0.4, age_claims / REACH_SATURATION), 0, 1)` — design §7.

    ``age_claims`` is the raw count of things the person dated by age that
    cannot be placed until the birthday is known. It is annotation as well as
    input: the fold keeps the raw number in `CalculatedTimeline.reach`.
    """
    try:
        raw = max(0, int(age_claims))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raw = 0
    try:
        divisor = float(saturation) if saturation else float(REACH_SATURATION)
    except (TypeError, ValueError):
        divisor = float(REACH_SATURATION)
    if divisor <= 0:
        divisor = float(REACH_SATURATION)
    reach = min(BIRTH_ORIGIN_REACH_CEILING, raw / divisor)
    return clamp_unit(BIRTH_ORIGIN_SCAFFOLD_VALUE + reach)


# --------------------------------------------------------------------------
# The published class of a date — one definition
# --------------------------------------------------------------------------


def node_claim_basis(record: object) -> str:
    """``explicit | calculated | inferred`` for one date record.

    `temporal_claims.CLAIM_BASIS_BY_DATE_BASIS` is the one mapping between
    *how the interval was arrived at* and *what class the product renders*; a
    date basis the mapping does not cover reads as ``inferred``, which is the
    safe direction — the birth-origin item stays OPEN rather than being closed
    by something nobody stated.
    """
    if record is None:
        return "inferred"
    basis = getattr(record, "basis", None)
    if basis is None:
        try:
            basis = chrono.from_dict(record).basis
        except Exception:  # noqa: BLE001 — an unreadable record is not an explicit one
            return "inferred"
    return tc.CLAIM_BASIS_BY_DATE_BASIS.get(collapsed_text(basis), "inferred")


def is_explicit_origin(record: object) -> bool:
    """Did somebody actually STATE this date?

    §3.2: a provisional origin calculated from age statements *"never closes
    the explicit-birthday work item"*. Because the predicate is the published
    class and not the presence of a node, E-BO's provisional origin needs no
    new flag to keep the item open — it arrives as ``calculated`` and this
    returns ``False``.
    """
    return node_claim_basis(record) == "explicit"


# --------------------------------------------------------------------------
# Canonicalization
# --------------------------------------------------------------------------


def _key(value: object) -> str:
    return collapsed_text(value).strip().lower()


def is_birth_anchor(ref: object = None, *, anchor_kind: object = None) -> bool:
    """Is this reference the OWNER's birth, under any spelling it has had?

    ``anchor_kind`` is the timeline anchor index's own `kind` field, which is
    authoritative when a caller has it. The key list is the fallback for a
    stored reference that arrived with nothing but a string.
    """
    if _key(anchor_kind) == BIRTH_ORIGIN_EVENT_KIND:
        return True
    return _key(ref) in {_key(name) for name in BIRTH_ANCHOR_KEYS}


def canonical_requested_field(value: object = None, *,
                              anchor: object = None,
                              anchor_kind: object = None) -> str:
    """The canonical spelling of the field an ask is missing.

    A canonical field passes through untouched. The legacy `temporal_anchor`
    (and an empty field) widens into the substrate's vocabulary: `birth_date`
    when the anchor IS the owner's birth, `date` otherwise — which is exactly
    what a keystone was ever asking for.
    """
    field = collapsed_text(value)
    if field in CANONICAL_REQUESTED_FIELDS:
        return field
    if is_birth_anchor(anchor, anchor_kind=anchor_kind):
        return REQUESTED_FIELD_BIRTH_DATE
    return DEFAULT_CANONICAL_REQUESTED_FIELD


def canonical_ask(*, kind: object, subject_ref: object = None,
                  event_ref: object = None, requested_field: object = None,
                  anchor_kind: object = None) -> tuple[str, str | None, str | None, str | None]:
    """``(kind, subject_ref, event_ref, requested_field)``, canonicalized together.

    The birth origin is the case that needs both halves moved: the keystone
    lane names the anchor (`birth`) as the subject and `temporal_anchor` as
    the field, and the substrate names the owner (`self`) and `birth_date`.
    Canonicalizing one without the other mints a THIRD identity, which is why
    this returns the whole tuple rather than a field at a time.
    """
    item_kind = collapsed_text(kind)
    subject = collapsed_text(subject_ref) or None
    event = collapsed_text(event_ref) or None
    field = canonical_requested_field(
        requested_field, anchor=subject or event, anchor_kind=anchor_kind
    )
    if item_kind == BIRTH_ORIGIN_KIND and (
        is_birth_anchor(subject, anchor_kind=anchor_kind)
        or (field == REQUESTED_FIELD_BIRTH_DATE and _key(subject) == _key(OWNER_SUBJECT_REF))
    ):
        return (BIRTH_ORIGIN_KIND, OWNER_SUBJECT_REF, None, REQUESTED_FIELD_BIRTH_DATE)
    return (item_kind, subject, event, field)


def canonical_work_item_id(*, kind: object, subject_ref: object = None,
                           event_ref: object = None, requested_field: object = None,
                           anchor_kind: object = None) -> str:
    """The canonical `work:<24 hex>` for one ask, from whichever lane asked it."""
    item_kind, subject, event, field = canonical_ask(
        kind=kind, subject_ref=subject_ref, event_ref=event_ref,
        requested_field=requested_field, anchor_kind=anchor_kind,
    )
    if not subject and not event:
        return ""
    return tp.derive_work_item_id(
        kind=item_kind, subject_ref=subject, event_ref=event, requested_field=field
    )


def birth_origin_work_item_id() -> str:
    """The ONE id the owner's missing birthday is asked under, everywhere."""
    return tp.derive_work_item_id(
        kind=BIRTH_ORIGIN_KIND,
        subject_ref=OWNER_SUBJECT_REF,
        event_ref=None,
        requested_field=REQUESTED_FIELD_BIRTH_DATE,
    )


# --------------------------------------------------------------------------
# The derived alias map
# --------------------------------------------------------------------------


def legacy_work_item_ids(item: object) -> tuple[str, ...]:
    """Every id this canonical item has ever been addressed by, sorted.

    Derived, never stored: re-mint the item's own identity tuple under the
    legacy vocabulary. Two families exist and both are mechanical rather than
    remembered —

    * the **legacy field** twin: the same subject and event under
      `temporal_anchor`, which is every keystone-minted row ever written;
    * for the birth origin only, the **legacy subject** spellings: the anchor
      keys that have meant the owner's birth, crossed with the legacy field and
      with the canonical one, because a stored reference may carry either.

    An alias is never minted across `kind`: the caller's kind is used as-is.
    """
    row = item if isinstance(item, dict) else {}
    kind = collapsed_text(row.get("kind"))
    if not kind:
        return ()
    canonical = collapsed_text(row.get("work_item_id")) or canonical_work_item_id(
        kind=kind,
        subject_ref=row.get("subject_ref"),
        event_ref=row.get("event_ref"),
        requested_field=row.get("requested_field"),
    )
    subject = collapsed_text(row.get("subject_ref")) or None
    event = collapsed_text(row.get("event_ref")) or None
    if not subject and not event:
        return ()

    spellings: list[tuple[str | None, str | None, str]] = [
        (subject, event, LEGACY_REQUESTED_FIELD),
    ]
    if canonical and canonical == birth_origin_work_item_id():
        for anchor in BIRTH_ANCHOR_KEYS:
            spellings.append((anchor, None, LEGACY_REQUESTED_FIELD))
            spellings.append((anchor, None, REQUESTED_FIELD_BIRTH_DATE))
            spellings.append((anchor, None, REQUESTED_FIELD_DATE))

    found: set[str] = set()
    for subject_spelling, event_spelling, field in spellings:
        legacy = tp.derive_work_item_id(
            kind=kind, subject_ref=subject_spelling,
            event_ref=event_spelling, requested_field=field,
        )
        if legacy and legacy != canonical:
            found.add(legacy)
    return tuple(sorted(found))


def work_item_aliases(items: object) -> dict:
    """``{legacy_id: canonical_id}`` for a whole generation of items.

    Published beside the items themselves in the SAME generation (design §7
    row 6), so a reader never holds a map that describes a different set. A
    legacy id claimed by two canonical items is DROPPED — silently rerouting
    one person's answer onto another question is worse than not deduping.
    """
    claims: dict[str, set[str]] = {}
    for item in items or ():
        row = item if isinstance(item, dict) else {}
        canonical = collapsed_text(row.get("work_item_id"))
        if not canonical:
            continue
        for legacy in legacy_work_item_ids(row):
            claims.setdefault(legacy, set()).add(canonical)
    return {
        legacy: next(iter(owners))
        for legacy, owners in sorted(claims.items())
        if len(owners) == 1
    }


def resolve_work_item_id(ref: object, *, aliases: object = None) -> str:
    """The ONE lookup: a stored reference to its current canonical id.

    An id that is already canonical, or that no map knows, is returned
    unchanged — resolution never invents an identity. Chains are followed and
    cycles terminate, because a published map is data and data can be wrong.
    """
    wanted = collapsed_text(ref)
    if not wanted:
        return ""
    table = aliases if isinstance(aliases, dict) else {}
    seen: set[str] = set()
    while wanted in table and wanted not in seen:
        seen.add(wanted)
        nxt = collapsed_text(table[wanted])
        if not nxt:
            break
        wanted = nxt
    return wanted


def resolve_work_item_ids(refs: object, *, aliases: object = None) -> tuple[str, ...]:
    """:func:`resolve_work_item_id` over a sequence, order and duplicates kept."""
    return tuple(
        resolve_work_item_id(ref, aliases=aliases)
        for ref in (refs or ())
        if collapsed_text(ref)
    )


__all__ = [
    "BIRTH_ANCHOR_KEYS",
    "BIRTH_ORIGIN_EVENT_KIND",
    "BIRTH_ORIGIN_KIND",
    "BIRTH_ORIGIN_REACH_CEILING",
    "BIRTH_ORIGIN_SCAFFOLD_VALUE",
    "BIRTH_ORIGIN_SCORE_RULE",
    "CANONICAL_REQUESTED_FIELDS",
    "DEFAULT_CANONICAL_REQUESTED_FIELD",
    "LEGACY_REQUESTED_FIELD",
    "OWNER_SUBJECT_REF",
    "REACH_SATURATION",
    "REQUESTED_FIELD_BIRTH_DATE",
    "REQUESTED_FIELD_DATE",
    "REQUESTED_FIELD_ORDER",
    "REQUESTED_FIELD_START_DATE",
    "SCORE_FORMULA_VERSION",
    "birth_origin_system_value",
    "birth_origin_work_item_id",
    "canonical_ask",
    "canonical_requested_field",
    "canonical_work_item_id",
    "clamp_unit",
    "is_birth_anchor",
    "is_explicit_origin",
    "legacy_work_item_ids",
    "node_claim_basis",
    "resolve_work_item_id",
    "resolve_work_item_ids",
    "work_item_aliases",
]
