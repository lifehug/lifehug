"""The event binder — a mention becomes a link by a RECORD, never an edit.

Eras design §4.3 (lifehug-platform `docs/design/eras.md`), phase E3.

Somebody says *"College ran 2007 to 2011"*. The ear writes down two facts and
the words they used for the thing — `event_mention: "College"` — and stops
there, because ADR 0029 says the model may not emit an `event_ref` and the
claim is immutable anyway. So the link has to be made afterwards, by
something deterministic, and it has to be made in a way a later rename cannot
retroactively falsify.

**That thing is one record.** `state/temporal_claims/resolutions/<hex>.json`,
type ``event_resolution``, saying: this claim id, that mention, resolved to
that era, by this rule version, via the target or via an alias. The claim is
never touched. Re-deciding is a NEW record naming the one it supersedes, and
the fold takes the newest active one per claim — which is what makes "a claim
id can never resolve to two refs" a property rather than a hope. A second
ACTIVE record for one claim with no ``supersedes`` is not resolved by
recency: it is a **loud refusal** (T-B-03), because two writers disagreeing
about what a sentence meant is a bug in the writers and hiding it behind a
timestamp is how a wrong link becomes permanent.

**The match is deliberately narrow.** Exact, case-folded, whole-label,
against (i) the era the session is visibly about, then (ii) every era's
active label and aliases. Nothing fuzzy, no substrings, no edit distance.
Two eras answering to one name is NOT resolved by preferring either — it is
NO bind plus an `identity_uncertain` work item naming both, so the person is
asked instead of guessed at. No match at all is NO bind plus a
``claim_event_unbound`` diagnostic. ADR 0026's ranking, applied: **a miss is
cheap and a wrong link is not.**

**Aliases only ever reach the future.** Adding an alias tomorrow binds
mentions nobody has resolved yet; it does not walk back through the filed
resolutions and re-point them, because the record says what was decided and
when, and a decision that silently changes is not a decision.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Sequence

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import era_identity as ei  # noqa: E402
import temporal_store as store  # noqa: E402
from temporal_claims import (  # noqa: E402
    SCHEMA_VERSION,
    TemporalContractError,
    collapsed_text,
    digest_id,
    normalized_timestamp,
)

# --------------------------------------------------------------------------
# Layout and vocabulary
# --------------------------------------------------------------------------

#: Beside the receipts and the active index, under the same rebuildable
#: `state/temporal_claims/` tree. A resolution is a DECISION, not evidence:
#: deleting the directory and re-running the binder over the same claims and
#: the same label index gives the same files back, which is the property that
#: makes it safe to live in `state/`.
RESOLUTIONS_DIR = "state/temporal_claims/resolutions"

EVENT_RESOLUTION_TYPE = "event_resolution"

#: The binder's own version, stamped on every record. It is part of the
#: record's identity, so a future rule change lands on NEW records beside the
#: old ones rather than silently reinterpreting yesterday's decisions —
#: exactly what `extractor_version` does for a claim.
RESOLUTION_RULE_VERSION = "event-binding:1"

#: FROZEN. What makes two resolutions the same decision.
RESOLUTION_IDENTITY_KEYS = ("claim_id", "event_mention", "rule_version", "supersedes")

#: How a bind was reached. ``target`` = the era this session is visibly about
#: matched its own label; ``alias`` = a label or alias of some era matched;
#: ``none`` = nothing was bound, and the record exists to SAY that.
BIND_KINDS = ("target", "alias", "none")

#: The named finding for a mention that matched nothing. Diagnostics, not
#: exceptions: a person naming a stretch of life the vault has never heard of
#: is ordinary, and the claim is filed either way.
UNBOUND_FINDING = "claim_event_unbound"

#: The work-item kind an ambiguous mention mints. Already in
#: `temporal_timeline.WORK_ITEM_KINDS` for subjects; §4.3 gives it its second
#: use rather than inventing a parallel word for the same question.
AMBIGUOUS_WORK_ITEM_KIND = "identity_uncertain"

RESOLUTION_ERROR_CODES = (
    "event_resolution_not_a_mapping",
    "event_resolution_needs_claim",
    "event_resolution_needs_mention",
    "event_resolution_bind_unknown",
    "event_resolution_ambiguous",
    "event_resolution_unreadable",
)


class EventBindingError(TemporalContractError):
    """A binding could not be made, filed or folded, with a named code."""


# --------------------------------------------------------------------------
# The match
# --------------------------------------------------------------------------


def bind_event_mention(
    mention: object, *, index: object, target_era_id: object = None
) -> tuple[str | None, str, tuple[str, ...]]:
    """One mention → ``(event_ref | None, bound_by, candidates)``.

    ``index`` is `era_identity.label_index(era_views(...))`: normalized name →
    the tuple of era ids that answer to it. A tuple, not an id, precisely so
    that ambiguity is visible here instead of having been resolved by
    whichever era the dict happened to hold.

    The target era wins ONLY on an exact match with its own label or alias
    (design §4.3). It is not a fallback: a session about College does not
    capture a sentence that named the Mission, because "the conversation was
    about X" is context, not evidence.
    """
    key = ei.normalize_label(mention)
    if not key:
        return None, "none", ()
    table = index if isinstance(index, dict) else {}
    candidates = tuple(table.get(key) or ())
    target = collapsed_text(target_era_id)
    if target and target in candidates:
        return target, "target", candidates
    if len(candidates) == 1:
        return candidates[0], "alias", candidates
    # Zero candidates is a miss; two or more is a question for the person.
    return None, "none", candidates


def ambiguous_work_item(mention: object, candidates: Sequence[str], *, views: object = None) -> dict:
    """The `identity_uncertain` row a shared alias mints, naming BOTH eras.

    Shaped like `temporal_timeline`'s own work items (kind, headline,
    candidates with refs and names) so the queue, Mirror and Play read it with
    no special case. Its whole content is the ambiguity: what was said, and
    which two things it could be.
    """
    table = views if isinstance(views, dict) else {}
    rows = [
        {
            "ref": era_id,
            "name": collapsed_text((table.get(era_id) or {}).get("label")) or era_id,
        }
        for era_id in candidates
    ]
    said = collapsed_text(mention)
    return {
        "kind": AMBIGUOUS_WORK_ITEM_KIND,
        "requested_field": "event_ref",
        "mention": said,
        "headline": f"“{said}” could be {' or '.join(row['name'] for row in rows)}",
        "candidates": rows,
    }


# --------------------------------------------------------------------------
# The record
# --------------------------------------------------------------------------


def resolution_digest(
    *, claim_id: object, event_mention: object, rule_version: object = RESOLUTION_RULE_VERSION,
    supersedes: object = None,
) -> str:
    payload = {
        "claim_id": collapsed_text(claim_id),
        "event_mention": ei.normalize_label(event_mention),
        "rule_version": collapsed_text(rule_version),
        "supersedes": collapsed_text(supersedes) or None,
    }
    return digest_id(
        "event_resolution", {key: payload[key] for key in RESOLUTION_IDENTITY_KEYS}
    ).split(":", 1)[1]


def resolution_relative_path(digest: object) -> str:
    return f"{RESOLUTIONS_DIR}/{ei._hex24(digest)}.json"


def validate_event_resolution(value: object) -> dict:
    """Normalize one resolution record or raise. The door, as everywhere else."""
    if not isinstance(value, dict) or not value:
        raise EventBindingError(
            "event_resolution_not_a_mapping", "a resolution is a mapping"
        )
    claim_id = collapsed_text(value.get("claim_id"))
    if not claim_id:
        raise EventBindingError(
            "event_resolution_needs_claim", "a resolution names the claim it resolves"
        )
    mention = collapsed_text(value.get("event_mention"))
    if not mention:
        raise EventBindingError(
            "event_resolution_needs_mention", "a resolution names the words it read"
        )
    bound_by = collapsed_text(value.get("bound_by")) or "none"
    if bound_by not in BIND_KINDS:
        raise EventBindingError(
            "event_resolution_bind_unknown", f"unknown bound_by: {bound_by!r}"
        )
    event_ref = collapsed_text(value.get("event_ref"))
    normalized = {
        "type": EVENT_RESOLUTION_TYPE,
        "schema_version": int(value.get("schema_version") or SCHEMA_VERSION),
        "claim_id": claim_id,
        "event_mention": mention,
        "event_ref": event_ref or None,
        "rule_version": collapsed_text(value.get("rule_version")) or RESOLUTION_RULE_VERSION,
        "bound_by": bound_by,
        "status": collapsed_text(value.get("status")) or "active",
        "created_at": normalized_timestamp(value.get("created_at"), error=EventBindingError),
    }
    candidates = value.get("candidates")
    if isinstance(candidates, (str, bytes)):
        candidates = [candidates]
    cleaned = [collapsed_text(row) for row in (candidates or ()) if collapsed_text(row)]
    if cleaned:
        normalized["candidates"] = sorted(dict.fromkeys(cleaned))
    supersedes = collapsed_text(value.get("supersedes"))
    if supersedes:
        normalized["supersedes"] = supersedes
    normalized["resolution_id"] = resolution_digest(
        claim_id=claim_id,
        event_mention=mention,
        rule_version=normalized["rule_version"],
        supersedes=supersedes or None,
    )
    return normalized


def file_event_resolution(
    vault_root: str | Path,
    *,
    claim_id: object,
    event_mention: object,
    event_ref: object = None,
    bound_by: str = "none",
    candidates: Sequence[str] = (),
    supersedes: object = None,
    now: object = None,
) -> tuple[dict, bool]:
    """File one resolution. Returns ``(record, created)``; replay creates nothing.

    A record is written for a MISS too (``bound_by: "none"``, no
    ``event_ref``). That is deliberate: "we looked at this mention and could
    not place it" is a fact worth keeping — it is what stops the binder
    re-asking the same unanswerable question every publication, and it is what
    a later alias makes newly answerable by SUPERSEDING it rather than by
    quietly appearing.
    """
    record = validate_event_resolution({
        "claim_id": claim_id,
        "event_mention": event_mention,
        "event_ref": event_ref,
        "bound_by": bound_by,
        "candidates": candidates,
        "supersedes": supersedes,
        "created_at": now,
    })
    relative = resolution_relative_path(record["resolution_id"])
    content = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    try:
        _path, created = store.create_or_keep(vault_root, relative, content)
    except store.TemporalStoreError as exc:
        raise EventBindingError(
            getattr(exc, "code", "") or "event_resolution_unreadable", str(exc)
        ) from exc
    record["relative_path"] = relative
    return record, created


def read_event_resolution(vault_root: str | Path, relative: str) -> dict | None:
    """Tolerant reader — ``None`` when the file is not one of ours."""
    text = store.read_store_text(vault_root, relative)
    if text is None:
        return None
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("type") != EVENT_RESOLUTION_TYPE:
        return None
    try:
        record = validate_event_resolution(payload)
    except TemporalContractError:
        return None
    record["relative_path"] = relative
    return record


def load_event_resolutions(vault_root: str | Path) -> list[dict]:
    """Every filed resolution, in path order (so the fold is order-free)."""
    root = store.store_path(vault_root, RESOLUTIONS_DIR)
    if not root.is_dir():
        return []
    rows = []
    for path in sorted(root.glob("*.json")):
        record = read_event_resolution(
            vault_root, f"{RESOLUTIONS_DIR}/{path.name}"
        )
        if record is not None:
            rows.append(record)
    return rows


# --------------------------------------------------------------------------
# The fold's half
# --------------------------------------------------------------------------


def event_resolution_index(records: object) -> dict:
    """``{claim_id: record}`` — the newest ACTIVE resolution per claim.

    Supersession is followed first: a record named by another record's
    ``supersedes`` is out, whatever its timestamp. What survives should be one
    record per claim. If it is not — two active decisions about one sentence,
    neither naming the other — this RAISES
    :data:`event_resolution_ambiguous` (T-B-03) instead of picking the later
    one, because the later one is not more right, it is just later, and a
    projection that quietly prefers it would make a wrong link permanent and
    invisible.
    """
    rows = [
        record if isinstance(record, dict) else {}
        for record in (records or ())
    ]
    parsed: list[dict] = []
    for row in rows:
        if not row:
            continue
        if row.get("type") not in (None, EVENT_RESOLUTION_TYPE):
            continue
        try:
            parsed.append(validate_event_resolution(row))
        except TemporalContractError:
            continue
    superseded = {
        collapsed_text(row.get("supersedes"))
        for row in parsed
        if collapsed_text(row.get("supersedes"))
    }
    by_claim: dict[str, list[dict]] = {}
    for row in parsed:
        if row["status"] != "active":
            continue
        if row["resolution_id"] in superseded:
            continue
        by_claim.setdefault(row["claim_id"], []).append(row)
    index: dict[str, dict] = {}
    for claim_id, found in sorted(by_claim.items()):
        if len(found) > 1:
            raise EventBindingError(
                "event_resolution_ambiguous",
                f"{claim_id} carries {len(found)} active event resolutions and none "
                "supersedes another; a claim resolves to one event or to none",
                detail={"claim_id": claim_id,
                        "resolution_ids": sorted(row["resolution_id"] for row in found)},
            )
        index[claim_id] = found[0]
    return index


def resolve_events(claims: object, records: object) -> tuple[list[dict], list[dict]]:
    """Attach ``event_ref`` to the claims a resolution places. ``(claims, findings)``.

    An OVERLAY on a copy — the receipt on disk is untouched, exactly as
    subject resolution is data *about* a claim and never an edit of one. A
    claim that already carries an `event_ref` is left alone (something more
    specific than this pass decided it); a claim with an `event_mention` and
    no resolution produces a :data:`UNBOUND_FINDING` diagnostic so the miss is
    legible rather than silent.
    """
    index = event_resolution_index(records)
    resolved: list[dict] = []
    findings: list[dict] = []
    for claim in claims or ():
        if not isinstance(claim, dict):
            continue
        claim_id = collapsed_text(claim.get("claim_id"))
        record = index.get(claim_id)
        if collapsed_text(claim.get("event_ref")) or record is None:
            resolved.append(claim)
            if record is None and collapsed_text(claim.get("event_mention")) and not collapsed_text(
                claim.get("event_ref")
            ):
                findings.append({
                    "finding": UNBOUND_FINDING,
                    "claim_id": claim_id,
                    "event_mention": collapsed_text(claim.get("event_mention")),
                })
            continue
        if not record.get("event_ref"):
            resolved.append(claim)
            findings.append({
                "finding": UNBOUND_FINDING,
                "claim_id": claim_id,
                "event_mention": record["event_mention"],
                "candidates": list(record.get("candidates") or ()),
                "resolution_id": record["resolution_id"],
            })
            continue
        row = dict(claim)
        row["event_ref"] = record["event_ref"]
        row["event_resolution"] = {
            "resolution_id": record["resolution_id"],
            "bound_by": record["bound_by"],
            "rule_version": record["rule_version"],
            "event_mention": record["event_mention"],
        }
        resolved.append(row)
    return resolved, findings


__all__ = [
    "AMBIGUOUS_WORK_ITEM_KIND",
    "BIND_KINDS",
    "EVENT_RESOLUTION_TYPE",
    "EventBindingError",
    "RESOLUTIONS_DIR",
    "RESOLUTION_ERROR_CODES",
    "RESOLUTION_IDENTITY_KEYS",
    "RESOLUTION_RULE_VERSION",
    "UNBOUND_FINDING",
    "ambiguous_work_item",
    "bind_event_mention",
    "event_resolution_index",
    "file_event_resolution",
    "load_event_resolutions",
    "read_event_resolution",
    "resolution_digest",
    "resolution_relative_path",
    "resolve_events",
    "validate_event_resolution",
]
