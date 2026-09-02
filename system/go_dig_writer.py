#!/usr/bin/env python3
"""E-L3: Go Dig's one unit writer and its deterministic import (design §10).

Two doors, one writer underneath. `record_unit` files a single structured
Go Dig unit through `timeline.save_landmark` — the SAME writer
`landmark-record`/the recorder's `landmark_invocations` already call, per
design §10.3 ("one more door into the ONE recorder and the ONE landmark
writer"). `apply_import`/`preview_import` are `go-dig-import`'s batch layer:
a deterministic, model-free parse (`go_dig_grammar.py`) followed by ordered,
per-block, digest-idempotent calls to `record_unit` — never a second writer.

**Identity (design §10.4, H4).** A standalone unit's identity is the
ordinary ordinal-keyed landmark digest, unchanged. An IMPORTED unit's
identity is ``(import_operation_id, block_content_digest, unit_kind,
discriminator)`` — never the filing ordinal, which shifts on every retry as
earlier blocks land. :func:`go_dig_unit_digest` computes it;
`landmark_projection.promote_landmark_entry`'s ``digest`` override (E-L3)
is what lets `timeline.save_landmark` file under it while staying the one
writer. Re-running the SAME import (a crash-and-retry, or a re-ordered
paste of the same blocks — `go_dig_grammar.content_digest` is
order-independent) recomputes the same digests and files nothing new
(rows 15, 28).

**Zero model calls.** Nothing in this module or `go_dig_grammar.py` imports
an LLM client, a classifier, or a prompt-building module — the import is
finished before hosted classification of any filed note ever begins (design
§10.4/§10.5, M8). ``tests/test_go_dig.py`` asserts this by AST sweep, the
same discipline the eras program's own zero-model-at-compile promise uses.

**Roster persistence is process-bound**, exactly like every other CLI
mutation in this package (`entity_roster.ENTITY_DIR`,
`timeline.LANDMARKS_STORE`) — rebindable in tests by monkeypatching those
module attributes, never by threading a second vault-root convention
through this module.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SYSTEM_DIR = Path(__file__).resolve().parent
if str(_SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(_SYSTEM_DIR))

import chronology as chrono  # noqa: E402
import entity_roster  # noqa: E402
import event_identity as ei  # noqa: E402
import go_dig_grammar as grammar  # noqa: E402
import landmark_projection as lp  # noqa: E402
import landmarks_interaction as li  # noqa: E402
import roster_relations as rr  # noqa: E402
import temporal_store as store  # noqa: E402
import timeline  # noqa: E402
from temporal_claims import TemporalContractError, collapsed_text, normalized_timestamp  # noqa: E402


class GoDigError(ValueError):
    """A Go Dig unit or import could not be filed."""


#: The additive source type a Go Dig unit's free-text note carries (design
#: §10.3). The note is otherwise an ordinary promoted conversational source —
#: see `temporal_store.promote_conversational_source`'s ``source_type``.
GO_DIG_NOTE_TYPE = "go_dig_note"


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------


def go_dig_unit_digest(*, import_operation_id: object, block_content_digest: object,
                       unit_kind: object, discriminator: object = "") -> str:
    """The digest that replaces the ordinal-keyed one for an imported unit.

    See the module docstring and `landmark_projection.promote_landmark_entry`
    (E-L3's ``digest`` override). ``unit_kind`` and ``discriminator``
    distinguish the several units ONE block can mint (a residence stay, a
    tenure group that happens to start in this block, the block's own note)
    from one another and from a DIFFERENT block that shares
    ``import_operation_id``.
    """
    payload = {
        "import_operation_id": collapsed_text(import_operation_id),
        "block_content_digest": collapsed_text(block_content_digest),
        "unit_kind": collapsed_text(unit_kind),
        "discriminator": collapsed_text(discriminator),
    }
    return store.payload_sha256(lp.canonical_json(payload))


def _import_session_ref(import_operation_id: str, discriminator: str) -> str:
    return f"go-dig-import:{import_operation_id}:{discriminator}"


def _as_of_date(now: object) -> str:
    """The date half of ``now`` (or of "right now"), for a chain closure's
    ``as_of`` — a closure names a day, never a full timestamp."""
    return normalized_timestamp(now, error=TemporalContractError).split("T", 1)[0]


# --------------------------------------------------------------------------
# Roster (process-bound, exactly like `entity_roster`'s own CLI callers)
# --------------------------------------------------------------------------


def _roster_snapshot(entity_type: str) -> dict:
    return entity_roster.load_roster(entity_type)


def _persist_roster(entity_type: str, snapshot: dict) -> None:
    entity_roster.write_roster(entity_type, list(snapshot.get("entities") or []))


def resolve_place_ref(name: str) -> str:
    """Find-or-mint the roster PLACE named ``name`` (design §10.3)."""
    snapshot = _roster_snapshot("place")
    ref, updated, _created = rr.resolve_or_create("place", name, snapshot)
    _persist_roster("place", updated)
    return ref


def resolve_organization_ref(name: str, *, organization_kind: str | None = None) -> str:
    """Find-or-mint the roster ORGANIZATION named ``name`` (E-L2c's roster
    type, reused here so a job/school's own organization is matchable by
    the containment binder — design §10.6 rows 31/32/34's "one roster
    organization"/"one place")."""
    snapshot = _roster_snapshot("organization")
    ref, updated, _created = rr.resolve_or_create(
        "organization", name, snapshot, organization_kind=organization_kind
    )
    _persist_roster("organization", updated)
    return ref


def apply_place_alias(ref: str, alias: str) -> dict:
    """File a nickname as a roster alias on the place at ``ref`` (§4.3)."""
    snapshot = _roster_snapshot("place")
    result = rr.alias_decision("place", ref, alias, snapshot)
    if result.get("applied") and result.get("changed"):
        _persist_roster("place", result["snapshot"])
    return result


def apply_located_in(child_ref: str, parent_ref: str) -> None:
    """File ``child_ref located_in parent_ref`` on the roster (§3.3)."""
    snapshot = _roster_snapshot("place")
    updated = rr.located_in(child_ref, parent_ref, snapshot)
    _persist_roster("place", updated)


# --------------------------------------------------------------------------
# The telling a just-filed entry names — for a note's `question_context`
# --------------------------------------------------------------------------


def telling_ref_for_entry(vault_root, domain: str, entry: dict, *, row: object = None) -> str | None:
    """The telling ref of the NEWEST promoted source filed for this entry's
    identity — what `episode_containers.resolves_to` reads as "the telling
    ref of the telling that opened it" (event-identity §12b.5's own three
    accepted spellings).

    `timeline.save_landmark` does not hand back the `SourceRef` it just
    wrote, so this re-reads the promoted sources by the entry's own
    grouping key rather than threading a second return shape through the
    ONE writer. The newest ordinal for that key is the telling this call
    just filed, by construction: nothing else writes between the two reads.
    """
    if row is None:
        try:
            row = li.domain_row(domain)
        except li.LandmarkInteractionError:
            row = None
    entry_key = li.landmark_entry_key(entry, row)
    matches = [row_ for row_ in lp.load_landmark_sources(vault_root)
              if row_["domain"] == domain and row_["entry_key"] == entry_key]
    if not matches:
        return None
    newest = max(matches, key=lambda row_: row_["ordinal"])
    entry_id = newest["source_id"].partition(":")[2] or newest["source_id"]
    return ei.landmark_telling_ref(entry_id)


# --------------------------------------------------------------------------
# The note
# --------------------------------------------------------------------------


def promote_go_dig_note(vault_root, text: object, *, question_context: object = None,
                        session_ref: object = None, now: object = None):
    """File a Go Dig unit's optional free-text note as its own owner-only
    source (design §10.3). ``None`` when ``text`` is blank — a unit with no
    note promotes nothing extra, which is the common case.

    Reuses `temporal_store.promote_conversational_source` whole (storage
    path, digest, ``question_context`` mechanics) with
    ``source_type=GO_DIG_NOTE_TYPE`` — the note enters classification and
    the listener exactly like any other promoted conversational source
    (§10.3: "never the landmark schema, never dropped").
    """
    clean = str(text or "").strip()
    if not clean:
        return None
    metadata = {
        "channel": "go_dig",
        "visibility": "owner_only",
    }
    if session_ref:
        metadata["session_ref"] = collapsed_text(session_ref)
    if question_context:
        metadata["question_context"] = collapsed_text(question_context)
    if now:
        metadata["occurred_at"] = now
    return store.promote_conversational_source(
        vault_root, clean, metadata, source_type=GO_DIG_NOTE_TYPE
    )


# --------------------------------------------------------------------------
# One unit
# --------------------------------------------------------------------------


def record_unit(payload: object, *, now: object = None) -> dict:
    """File one Go Dig unit — the CLI's ``go-dig-record`` core (design §10.3).

    ``payload``: ``{"landmark": {...validate_landmark-shape fields, plus
    "place_name" to resolve/mint a roster place}, "note"?: str,
    "import_operation_id"?: str, "block_content_digest"?/"block_local_id"?:
    str, "unit_discriminator"?: str, "session_ref"?/"source_ref"?: str}``.

    Files through `timeline.save_landmark` — the ONE existing writer — with
    an idempotent digest override when import context is given (else the
    ordinary ordinal digest, unchanged). Resolves/creates the roster place
    by ``place_name`` when present, files the ``nickname`` alias decision on
    it, and promotes the optional ``note`` carrying the just-filed entry's
    own telling ref as its ``question_context`` (design §10.3/12b.5), so a
    moment later classified from the note is filed ``part_of`` this stay
    deterministically.
    """
    if not isinstance(payload, dict):
        raise GoDigError("a go-dig unit needs a JSON object")
    landmark = payload.get("landmark")
    if not isinstance(landmark, dict):
        raise GoDigError("a go-dig unit needs a `landmark` object")
    domain = collapsed_text(landmark.get("domain"))
    if not domain:
        raise GoDigError("a go-dig unit's landmark needs a domain")

    value = dict(landmark)
    place_name = value.pop("place_name", None)
    if isinstance(place_name, str) and place_name.strip():
        value["place_ref"] = resolve_place_ref(place_name)

    if not collapsed_text(value.get("label")):
        # `landmarks_interaction.identity_named`/`entry_subject_mention`
        # read `label` (then `name`) and NOTHING else — not the domain's own
        # identity rung — so a structural unit that never sets `label`
        # names its subject the DOMAIN WORD ("residences") to every
        # downstream reader: the containment rung's entity signal, the
        # promoted source's title, the ladder's own display. A Go Dig unit
        # always has a stated subject (the rung the person just filled), so
        # this defaults `label` from it rather than asking every caller to
        # remember.
        try:
            row_for_label = li.domain_row(domain)
        except li.LandmarkInteractionError:
            row_for_label = None
        rung = li.identity_rung(row_for_label) if row_for_label else None
        rung_value = value.get(rung) if rung else None
        if isinstance(rung_value, str) and rung_value.strip():
            value["label"] = rung_value.strip()

    validated = li.validate_landmark(value)
    if validated is None:
        raise GoDigError("nothing to record")

    import_operation_id = collapsed_text(payload.get("import_operation_id"))
    block_digest = (collapsed_text(payload.get("block_content_digest"))
                    or collapsed_text(payload.get("block_local_id")))
    digest_override = None
    if import_operation_id and block_digest:
        digest_override = go_dig_unit_digest(
            import_operation_id=import_operation_id,
            block_content_digest=block_digest,
            unit_kind=domain,
            discriminator=collapsed_text(payload.get("unit_discriminator")),
        )

    saved = timeline.save_landmark(
        validated["domain"], validated, digest_override=digest_override
    )

    alias_result = None
    nickname = validated.get("nickname")
    place_ref = validated.get("place_ref")
    if isinstance(nickname, str) and nickname.strip() and place_ref:
        alias_result = apply_place_alias(place_ref, nickname)

    root = timeline._projection_vault_root()  # noqa: SLF001 — one definition; see module docstring.
    row = None
    try:
        row = li.domain_row(domain)
    except li.LandmarkInteractionError:
        row = None
    telling_ref = telling_ref_for_entry(root, domain, validated, row=row)

    note_source = None
    note_text = payload.get("note")
    if isinstance(note_text, str) and note_text.strip():
        session_ref = (collapsed_text(payload.get("session_ref"))
                       or collapsed_text(payload.get("source_ref"))
                       or (_import_session_ref(import_operation_id, block_digest)
                           if import_operation_id and block_digest else None))
        note_source = promote_go_dig_note(
            root, note_text, question_context=telling_ref,
            session_ref=session_ref, now=now,
        )

    return {
        "domain": domain,
        "entry": saved,
        "place_ref": place_ref,
        "alias": alias_result,
        "telling_ref": telling_ref,
        "note_source": note_source.to_dict() if note_source is not None else None,
    }


# --------------------------------------------------------------------------
# The import — pure planning
# --------------------------------------------------------------------------


def _norm(text: object) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _stay_interval(dates: dict | None) -> dict | None:
    if not dates:
        return None
    start = dates.get("start") or {}
    end = dates.get("end") or {}
    earliest = start.get("edtf")
    latest = None if end.get("ongoing") else end.get("edtf")
    if not earliest and not latest:
        return None
    return {"earliest": earliest, "latest": latest}


def detect_overlaps(blocks: list) -> list:
    """Consecutive dated stays overlapping by MORE than three months (§10.6:
    "shown in the preview beforehand so the person can fix a date first").
    A shorter overlap is an ordinary move and is never reported here."""
    dated = [block for block in blocks if block.get("dates") and not block.get("errors")]
    overlaps = []
    for earlier, later in zip(dated, dated[1:]):
        interval_a = _stay_interval(earlier["dates"])
        interval_b = _stay_interval(later["dates"])
        if interval_a is None or interval_b is None:
            continue
        months = chrono.overlap_months(interval_a, interval_b)
        if months > 3:
            overlaps.append({
                "a_ordinal": earlier["ordinal"], "b_ordinal": later["ordinal"],
                "months": months,
            })
    return overlaps


def _year_of(edtf: object, *, end: bool) -> int | None:
    if not edtf:
        return None
    record = chrono.parse_edtf(str(edtf))
    if record is None:
        return None
    return chrono.year_of(record, end=end)


def _block_stay_bounds(block: dict) -> tuple:
    dates = block.get("dates") or {}
    start = dates.get("start") or {}
    end = dates.get("end") or {}
    start_edtf = start.get("edtf")
    end_edtf = None if end.get("ongoing") else end.get("edtf")
    return start_edtf, start.get("grain"), end_edtf, end.get("grain"), bool(end.get("ongoing"))


def group_tenures(blocks: list, *, kind: str) -> list:
    """Consecutive same-identity school/work mentions folded into tenure
    groups (§10.6, rows 31/32): one group per ``(what, where)`` (work) or
    school name, closing and re-opening a NEW group when the gap between
    the prior group's last stay-end and this block's stay-start exceeds one
    year. A block reported ``needs_a_hand`` contributes no mentions.
    """
    open_groups: dict[tuple, dict] = {}
    closed: list[dict] = []

    def close(key: tuple) -> None:
        group = open_groups.pop(key, None)
        if group is not None:
            closed.append(group)

    for block in blocks:
        if block.get("errors"):
            continue
        start_edtf, start_grain, end_edtf, end_grain, ongoing = _block_stay_bounds(block)
        stay_start_year = _year_of(start_edtf, end=False)
        stay_end_year = _year_of(end_edtf, end=True)

        mentions: list[dict] = []
        if kind == "school":
            school = block.get("school")
            if school and school.get("status") == "named" and school.get("name"):
                mentions.append({
                    "key": (_norm(school["name"]),),
                    "name": school["name"], "grades": school.get("grades"),
                })
        else:
            for item in block.get("work_items") or ():
                mentions.append({
                    "key": (_norm(item["what"]), _norm(item.get("where"))),
                    "what": item["what"], "org": item["org"], "where": item.get("where"),
                    "inline_start": item.get("start"), "inline_end": item.get("end"),
                })

        for mention in mentions:
            key = mention["key"]
            group = open_groups.get(key)
            if group is not None and group["last_end_year"] is not None \
                    and stay_start_year is not None \
                    and stay_start_year - group["last_end_year"] > 1:
                close(key)
                group = None
            if group is None:
                group = {
                    "kind": kind, "key": key, "mention": mention,
                    "first_ordinal": block["ordinal"], "last_ordinal": block["ordinal"],
                    "first_start_edtf": start_edtf, "first_start_grain": start_grain,
                    "last_end_edtf": end_edtf, "last_end_grain": end_grain,
                    "last_end_year": stay_end_year, "ongoing": ongoing,
                    "inline_start": mention.get("inline_start"),
                    "inline_end": mention.get("inline_end"),
                }
                open_groups[key] = group
            else:
                group["last_ordinal"] = block["ordinal"]
                group["last_end_edtf"] = end_edtf
                group["last_end_grain"] = end_grain
                group["last_end_year"] = stay_end_year
                group["ongoing"] = ongoing
                if mention.get("inline_start") and not group.get("inline_start"):
                    group["inline_start"] = mention["inline_start"]
                if mention.get("inline_end") and not group.get("inline_end"):
                    group["inline_end"] = mention["inline_end"]

    for key in list(open_groups):
        close(key)
    closed.sort(key=lambda group: (group["first_ordinal"], group["key"]))
    return closed


def plan_import(text: str) -> dict:
    """Pure: every block parsed, every tenure group resolved, every overlap
    flagged. `preview_import` and `apply_import` share this single plan so
    the two can never disagree about what the paste says (§10.4)."""
    blocks = grammar.parse_paste(text)
    return {
        "blocks": blocks,
        "school_tenures": group_tenures(blocks, kind="school"),
        "work_tenures": group_tenures(blocks, kind="work"),
        "overlaps": detect_overlaps(blocks),
        "schools_done": any(
            (block.get("school") or {}).get("status") == "done"
            and not block.get("errors")
            for block in blocks
        ),
    }


def preview_import(text: str) -> dict:
    """``go-dig-import --preview``: the plan, JSON-shaped, no writes."""
    plan = plan_import(text)
    return {
        "blocks": [
            {
                "ordinal": block["ordinal"],
                "block_local_id": block["block_local_id"],
                "status": block["status"],
                "errors": list(block["errors"]),
                "parsed": {
                    "dates": block["dates"], "place_name": block["place_name"],
                    "region_name": block["region_name"], "nickname": block["nickname"],
                    "address": block["address"], "link": block["link"],
                    "school": block["school"],
                    "work_items": [dict(item) for item in block["work_items"]],
                    "events_text": block["events_text"],
                },
                "note_lines": list(block["note_lines"]),
            }
            for block in plan["blocks"]
        ],
        "school_tenures": [
            {"name": g["mention"]["name"], "grades": g["mention"].get("grades"),
             "first_block": g["first_ordinal"], "last_block": g["last_ordinal"]}
            for g in plan["school_tenures"]
        ],
        "work_tenures": [
            {"what": g["mention"]["what"], "org": g["mention"]["org"],
             "where": g["mention"].get("where"),
             "first_block": g["first_ordinal"], "last_block": g["last_ordinal"]}
            for g in plan["work_tenures"]
        ],
        "overlaps": plan["overlaps"],
    }


# --------------------------------------------------------------------------
# The import — filing
# --------------------------------------------------------------------------


def _inferred_bound(edtf: object, *, grain: object, label: str) -> dict | None:
    """One end of a tenure's INFERRED window (§10.6 rows 31/32): the SAME
    value the owning stay carries, at ``basis="order"``/``confidence=
    "inferred"`` — `episode_fold_contract.CONTAINMENT_DATE_BASIS`'s own
    basis, read straight rather than re-derived, since this is the identical
    "a member with no value of its own reads its container's span" shape one
    layer earlier: FILED as the tenure's own claim rather than computed at
    read time, because a job/school entry is a real episode with its own
    identity, not a windowed member of the residence. A full
    ``best``/``earliest``/``latest``/... dict — the shape
    `chronology.normalized_date` reads straight through, no re-parsing.
    """
    if not edtf:
        return None
    return {
        "best": edtf, "earliest": edtf, "latest": edtf,
        "granularity": grain or "year",
        "confidence": "inferred",
        "basis": "order",
        "provenance": [{
            "basis": chrono.CALCULATED_PROVENANCE_BASIS,
            "claim": f"listed under the {label} stay",
            "source": "go_dig_import",
        }],
    }


def _tenure_bound(inline: dict | None, inferred_edtf: object, *, grain: object,
                  label: str) -> tuple:
    """``(value, approximate)`` for one end of a tenure (§10.6). A stated
    inline date wins (an EDTF string — `chronology.from_dict` reads a bare
    string as ``stated``); otherwise the inferred window (a full DateRecord
    dict, never separately flagged approximate — ``confidence: inferred``
    already says how firm it is)."""
    if inline and not inline.get("unparseable") and inline.get("edtf"):
        return inline["edtf"], bool(inline.get("approximate"))
    return _inferred_bound(inferred_edtf, grain=grain, label=label), False


def _apply_bound(span: dict, bound: str, value: object, *, approximate: bool) -> None:
    if value is None:
        return
    span[bound] = value
    if approximate:
        span[f"{bound}_approximate"] = True


def _file_tenure_group(domain: str, group: dict, *, import_operation_id: str,
                       block_content_digest_of, now: object) -> dict:
    mention = group["mention"]
    label = mention.get("name") or mention.get("what") or "stay"
    landmark: dict = {"domain": domain}
    if domain == "schools":
        landmark["name"] = mention["name"]
        if mention.get("grades"):
            landmark["grades"] = mention["grades"]
    else:
        landmark["what"] = mention["what"]
        if mention.get("where"):
            landmark["where"] = mention["where"]
            # `landmark_entry_key`/`identity_named` read `label` before the
            # domain's own identity rung (`what`) — and `what` alone is
            # "Boeing" for BOTH "Boeing" and "Boeing in Seattle", which
            # would let the interval-aware key MERGE two adjacent tenures
            # the grammar itself grouped as separate (§10.6 row 32: a
            # changed wording is a second tenure). `label` carries the
            # wording that actually differed, so the two tenures keep two
            # identities while `org` still resolves to one roster entity.
            landmark["label"] = f"{mention['what']} in {mention['where']}"
        else:
            landmark["label"] = mention["what"]

    span: dict = {}
    start_value, start_approx = _tenure_bound(
        group.get("inline_start"), group.get("first_start_edtf"),
        grain=group.get("first_start_grain"), label=label,
    )
    _apply_bound(span, "start", start_value, approximate=start_approx)
    if not group.get("ongoing"):
        end_value, end_approx = _tenure_bound(
            group.get("inline_end"), group.get("last_end_edtf"),
            grain=group.get("last_end_grain"), label=label,
        )
        _apply_bound(span, "end", end_value, approximate=end_approx)
    if span:
        landmark["span"] = span
    if group.get("ongoing"):
        landmark["ongoing"] = True

    organization_name = mention.get("org")
    if organization_name:
        resolve_organization_ref(organization_name, organization_kind=(
            "school" if domain == "schools" else "employer"
        ))

    discriminator = f"{domain}:{group['key']}"
    payload = {
        "landmark": landmark,
        "import_operation_id": import_operation_id,
        "block_content_digest": block_content_digest_of(group["first_ordinal"]),
        "unit_discriminator": discriminator,
    }
    return record_unit(payload, now=now)


def apply_import(text: str, *, import_operation_id: str, now: object = None) -> dict:
    """``go-dig-import --apply``: file every block, in order, exactly once.

    Per-block: a ``needs_a_hand`` block is reported and SKIPPED, every other
    block files its residence stay (when it carries one) and its note (when
    it carries one); the rest is retry-safe because every write below is
    digest-idempotent on ``(import_operation_id, block content, unit kind,
    discriminator)`` (design §10.4, rows 15/16/28). Zero model calls
    anywhere in this path (§10.5) — nothing here imports a classifier or an
    LLM client.
    """
    import_operation_id = collapsed_text(import_operation_id)
    if not import_operation_id:
        raise GoDigError("go-dig-import --apply needs --import-operation-id")

    plan = plan_import(text)
    blocks = plan["blocks"]
    digest_by_ordinal = {block["ordinal"]: block["content_digest"] for block in blocks}

    outcomes: dict[int, dict] = {}
    for block in blocks:
        if block["status"] == "needs_a_hand":
            outcomes[block["ordinal"]] = {
                "ordinal": block["ordinal"], "status": "needs_a_hand",
                "errors": list(block["errors"]),
            }
            continue

        filed_units: list[dict] = []
        landmark: dict = {"domain": "residences"}
        owns_residence = bool(
            block["place_name"] or block["dates"] or block["nickname"]
            or block["address"] or block["link"]
        )
        telling_ref = None
        if owns_residence:
            if block["place_name"]:
                # `city` is the ladder's own identity rung (the person's own
                # wording); `place_name` is consumed by `record_unit` to
                # resolve/mint the ROSTER entity into `place_ref` — the two
                # are deliberately not the same field (design §10.3 M5).
                landmark["city"] = block["place_name"]
                landmark["place_name"] = block["place_name"]
            if block["nickname"]:
                landmark["nickname"] = block["nickname"]
            if block["address"]:
                landmark["address"] = block["address"]
            if block["link"]:
                landmark["link"] = block["link"]
            dates = block["dates"] or {}
            start = dates.get("start") or {}
            end = dates.get("end") or {}
            span: dict = {}
            _apply_bound(span, "start", start.get("edtf"),
                        approximate=bool(start.get("approximate")))
            if not end.get("ongoing"):
                _apply_bound(span, "end", end.get("edtf"),
                            approximate=bool(end.get("approximate")))
            if span:
                landmark["span"] = span
            if end.get("ongoing"):
                landmark["ongoing"] = True

            residence_payload = {
                "landmark": landmark,
                "note": block["events_text"],
                "import_operation_id": import_operation_id,
                "block_content_digest": block["content_digest"],
                "unit_discriminator": "residences",
            }
            result = record_unit(residence_payload, now=now)
            filed_units.append(result)
            telling_ref = result["telling_ref"]

            place_ref = result.get("place_ref")
            if place_ref and block["region_name"]:
                region_ref = resolve_place_ref(block["region_name"])
                apply_located_in(place_ref, region_ref)
        elif block["events_text"]:
            # No structural fields at all — the note still files, just with
            # no known container to stamp (§10.3: never dropped).
            note_source = promote_go_dig_note(
                timeline._projection_vault_root(),  # noqa: SLF001
                block["events_text"], question_context=None,
                session_ref=_import_session_ref(import_operation_id,
                                                block["content_digest"]),
                now=now,
            )
            if note_source is not None:
                filed_units.append({"note_source": note_source.to_dict()})

        if block["school"] and block["school"].get("status") == "done":
            lp.file_chain_closure(
                timeline._projection_vault_root(),  # noqa: SLF001
                domain="schools", status="closed_for_now", as_of=_as_of_date(now),
                now=now,
            )

        outcomes[block["ordinal"]] = {
            "ordinal": block["ordinal"], "status": "filed",
            "telling_ref": telling_ref, "units": len(filed_units),
        }

    for domain, group_kind in (("schools", "school_tenures"), ("work", "work_tenures")):
        for group in plan[group_kind]:
            _file_tenure_group(
                domain, group, import_operation_id=import_operation_id,
                block_content_digest_of=lambda ordinal: digest_by_ordinal[ordinal],
                now=now,
            )

    filed = sum(1 for row in outcomes.values() if row["status"] == "filed")
    skipped = sum(1 for row in outcomes.values() if row["status"] == "needs_a_hand")
    return {
        "import_operation_id": import_operation_id,
        "blocks": [outcomes[block["ordinal"]] for block in blocks],
        "filed": filed, "needs_a_hand": skipped,
        "school_tenures": len(plan["school_tenures"]),
        "work_tenures": len(plan["work_tenures"]),
        "overlaps": plan["overlaps"],
    }
