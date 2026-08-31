#!/usr/bin/env python3
"""Event identity I3 — the questions: five answers, a split gesture.

Controlling design: lifehug-platform `docs/design/event-identity.md` v4 §6.1
(`same_event`'s five answers), §6.3 (`possible_overmerge`'s four), §5.5 (the
split rules table) and the §13.3/§13.4 promises. I0 (`event_identity.py`,
`episode_fold_contract.py`, `episode_routing_contract.py`) settled what a
record MEANS; I1 (`episode_fold.py`) taught the fold to apply one; I2
(`episode_binder.py`) taught the substrate to DECIDE one, pairwise, as data.
This module is the first thing a PERSON'S answer reaches — it holds no new
vocabulary, no interaction, no stage: every write goes through `event_identity`'s
own writers, and the Play kind stays `work_item` (paradigm 3).

**Five answers, one seam.** `same_event`'s probe (`timeline_interaction.
WORK_ITEM_PROBES["same_event"]`) is a CLOSED choice, not free text this
module parses — the same "structured payload, not prose" shape
`lifehug.py timeline-move --relation` already uses. :func:`resolve_same_event_answer`
is the whole filing decision: **Same** → a confirmed `same` binding
(superseding a state-side proposal when one exists — the origin-transition
rule, §3.3); **Part of it** → a confirmed `part_of` binding (containment;
`event_identity.validate_event_identity` already admits `part_of` at
`confirmed`/`stated` origin — only a `deterministic` origin is pinned to
`same`, so no validator amendment is needed here); **Related but
different** → `related`; **Different** → `not_same`, source-backed and
pair-permanent; **Not sure** → :func:`defer_pair`'s epistemic state on the
PAIR, never a relation (§2.2) — no binding, a 90-day cooldown
(`episode_routing_contract.DEFERRAL_COOLDOWN_DAYS`), reopened early by
material new evidence.

**The candidate may not exist yet.** A `same_event` pair's candidate is
either an EXISTING episode (`episode_binder.Candidate.kind == "episode"`) or
a PROSPECTIVE one keyed by the id a deterministic `create` would mint
(`episode_binder.prospective_episode_id`, `authority="deterministic"`). A
human's **Same** answer to a prospective pair is not that same act: R1 already
declined it, so nothing deterministic would ever re-derive it, and the
create this module files is `authority="human"` — a different, and entirely
legitimate, id (Law 7: human decisions are sources, not state).
:func:`_episode_exists` tells the two cases apart by asking the vault rather
than trusting a caller's flag.

**`possible_overmerge`'s four answers** (§6.3) are **keep together** (the
bind is untouched — nothing is filed, exactly as the re-audit rule requires:
:data:`episode_routing_contract.FORBIDDEN_REAUDIT_ACTIONS` already refuses
"confirm" as a SYSTEM act, and a person confirming it is simply not an
identity write), **split** (:func:`split_episode`), **part of** (the
over-merged telling's `same` binding is superseded by a `part_of` one — it
keeps the episode's company without pretending to be the same event), and
**fix the date** (an ordinary date correction, never an identity write — this
module returns a typed no-write result naming the target rather than reaching
for `event_identity`'s writers over evidence it was never asked to judge).

**The split gesture** (§5.5, §12.5). :func:`split_episode` files ONE `split`
envelope naming a destination per departing telling (`standalone` or a new
episode created in the same envelope), then calls
`episode_routing_contract.split_routing` — already fully specified and
tested at I0 — to route every other reference off the surviving id. This
module adds no new routing rule; it is the first thing to actually WRITE a
split.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Mapping, Sequence

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import episode_fold_contract as efc  # noqa: E402
import episode_routing_contract as erc  # noqa: E402
import event_identity as ei  # noqa: E402
import temporal_store as store  # noqa: E402
from temporal_claims import (  # noqa: E402
    TemporalContractError,
    collapsed_text,
)
from vault_paths import atomic_write_vault_text  # noqa: E402

# --------------------------------------------------------------------------
# Vocabulary — imported, never restated (ADR 0021)
# --------------------------------------------------------------------------

#: `same_event`'s five answers (design §6.1). A CLOSED choice — the CLI's
#: `resolve-work-item --answer` flag, never a free-text field this module
#: parses. Order matches the probe's own listing.
RELATION_ANSWERS = ("same", "part_of", "related", "different", "not_sure")

#: The four answers that file a binding. "not_sure" is deliberately absent —
#: it asserts nothing about the world (§2.2) and is handled by
#: :func:`defer_answer` alone.
ANSWER_RELATION = {
    "same": efc.GROUPING_RELATION,
    "part_of": "part_of",
    "related": "related",
    "different": "not_same",
}

#: `possible_overmerge`'s four answers (design §6.3, §12.5).
OVERMERGE_ANSWERS = ("keep_together", "split", "part_of", "fix_the_date")

#: The projection this module writes — a bookkeeping log, not evidence, and
#: safe to delete: a person's "Not sure" is real, but the RECORD OF HAVING
#: ASKED is rebuildable from the work-item generation itself the same way
#: every other cooldown in this codebase is (`classify_story.py`'s
#: `defer_until`). Living under `state/` is the honest read of §2.2: `unknown`
#: is an epistemic state about a QUESTION, never a relation about the world,
#: so it does not belong beside `sources/identity/`'s durable human decisions.
IDENTITY_DEFERRALS_FILE = f"{ei.TEMPORAL_STATE_DIR}/identity_deferrals.json"

IDENTITY_QUESTIONS_ERROR_CODES = (
    "identity_answer_unknown",
    "identity_overmerge_answer_unknown",
    "identity_answer_needs_sibling",
    "identity_answer_needs_episode_or_sibling",
)


class IdentityQuestionsError(TemporalContractError):
    """An answer or a split could not be filed, with a code."""


def _require(condition: object, code: str, message: str, **detail: object) -> None:
    if not condition:
        raise IdentityQuestionsError(code, message, detail=detail or None)


# --------------------------------------------------------------------------
# Reading the vault for what already exists
# --------------------------------------------------------------------------


def _episode_exists(vault_root: str | Path, episode_id: str) -> bool:
    """Is this an EXISTING episode, or the id a prospective `create` would mint?

    `episode_binder.prospective_episode_id` computes an `authority:
    "deterministic"` id for a pair R1 never actually bound — nothing was ever
    filed under it. Asking the vault, rather than trusting a caller-supplied
    flag, is what lets this module have no `candidate_kind` parameter at all.
    """
    for record in ei.load_episode_operations(vault_root):
        if record.get("status") == "active" and record.get("episode_id") == episode_id:
            return True
    return False


def _active_binding(
    vault_root: str | Path, *, telling_ref: str, episode_id: str, relation: str
) -> dict | None:
    """The one active binding this (telling, episode, relation) already has,
    if any — the record a confirmed answer must name in ``supersedes`` for
    the origin-transition rule (§3.3) to hold."""
    for record in ei.load_event_identities(vault_root):
        if record.get("status") != "active":
            continue
        if (
            record.get("telling_ref") == telling_ref
            and record.get("episode_id") == episode_id
            and record.get("relation") == relation
        ):
            return record
    return None


def _machine_origin_to_supersede(existing: dict | None) -> str | None:
    """Only a MACHINE-origin record needs the origin-transition supersede
    (§3.3's ``proposed`` → ``confirmed`` rule). Re-filing an identical HUMAN
    decision is plain create-or-keep idempotency (audit A6) — naming it in
    ``supersedes`` would move the digest and mint a new record every time the
    same answer is given twice, which is precisely the "answering twice is
    idempotent by record digest" promise (§5.8 row 2) failing.
    """
    if existing is None:
        return None
    if existing.get("origin") in ei.MACHINE_ORIGINS:
        return existing["identity_id"]
    return None


def _create_singleton(
    vault_root: str | Path, telling_ref: str, *, source_ref: object = None, now: object = None
) -> str:
    """Give a standalone telling its OWN episode so a binding can name it.

    §3.2's `create` admits a single member — nothing in the schema requires
    two. Used when a person answers `part_of` / `related` / `different`
    against a PROSPECTIVE candidate: those three relations need an
    `episode_id`, and a raw sibling telling is not one yet.
    """
    operation_id = ei.operation_digest(
        authority="human", op="create", rule_version=ei.IDENTITY_RULE_VERSION,
        member_refs=[telling_ref],
    )
    episode_id = ei.episode_id_for(operation_id)
    if _episode_exists(vault_root, episode_id):
        return episode_id
    binding_id = ei.binding_digest(
        telling_ref=telling_ref, episode_id=episode_id,
        relation=efc.GROUPING_RELATION, rule_version=ei.IDENTITY_RULE_VERSION,
    )
    ei.file_operation_envelope(
        vault_root,
        operation={
            "authority": "human", "op": "create", "rule_version": ei.IDENTITY_RULE_VERSION,
            "members": [telling_ref], "creates_binding_ids": [binding_id],
            "source_ref": source_ref, "created_at": now,
        },
        bindings=[{
            "telling_ref": telling_ref, "episode_id": episode_id,
            "relation": efc.GROUPING_RELATION, "origin": "confirmed",
            "rule_version": ei.IDENTITY_RULE_VERSION,
            "source_ref": source_ref, "created_at": now,
        }],
    )
    return episode_id


# --------------------------------------------------------------------------
# `same_event` — the five answers (design §6.1, §13.4)
# --------------------------------------------------------------------------


def resolve_same_event_answer(
    vault_root: str | Path,
    *,
    telling_ref: object,
    candidate_episode_id: object,
    answer: object,
    candidate_telling_ref: object = None,
    telling_quote: object = None,
    episode_quote: object = None,
    source_ref: object = None,
    now: object = None,
) -> dict:
    """File one of the five answers to a `same_event` pair.

    Every write goes through `event_identity`'s own writers — no new
    interaction, stage or awaiting state (design §6.1). Returns a dict naming
    what happened; ``answer`` echoes the normalized code so a caller need not
    re-derive it.
    """
    telling = ei.validate_telling_ref(telling_ref)
    answer_code = collapsed_text(answer)
    _require(
        answer_code in RELATION_ANSWERS,
        "identity_answer_unknown",
        f"unknown same_event answer: {answer!r}",
    )
    candidate_episode = collapsed_text(candidate_episode_id)
    evidence = {
        "telling_quote": collapsed_text(telling_quote),
        "episode_quote": collapsed_text(episode_quote),
    }

    if answer_code == "not_sure":
        deferral = erc.defer_pair(
            telling_ref=telling, candidate_episode_id=candidate_episode,
            evidence_signature=evidence, now=now,
        )
        record = file_deferral(vault_root, deferral)
        return {"answer": "not_sure", "event_key": deferral["event_key"], "deferral": record}

    exists = _episode_exists(vault_root, candidate_episode)

    if answer_code == "same" and not exists:
        _require(
            collapsed_text(candidate_telling_ref), "identity_answer_needs_sibling",
            "confirming Same against a prospective pair names the sibling telling",
        )
        sibling = ei.validate_telling_ref(candidate_telling_ref)
        members = sorted({telling, sibling})
        operation_id = ei.operation_digest(
            authority="human", op="create", rule_version=ei.IDENTITY_RULE_VERSION,
            member_refs=members,
        )
        episode_id = ei.episode_id_for(operation_id)
        bindings = []
        creates_ids = []
        for ref in members:
            payload = {
                "telling_ref": ref, "episode_id": episode_id,
                "relation": efc.GROUPING_RELATION, "origin": "confirmed",
                "rule_version": ei.IDENTITY_RULE_VERSION,
                "source_ref": source_ref, "created_at": now,
            }
            if ref == telling:
                payload["evidence"] = evidence
            creates_ids.append(ei.binding_digest(
                telling_ref=ref, episode_id=episode_id,
                relation=efc.GROUPING_RELATION, rule_version=ei.IDENTITY_RULE_VERSION,
            ))
            bindings.append(payload)
        envelope = ei.file_operation_envelope(
            vault_root,
            operation={
                "authority": "human", "op": "create", "rule_version": ei.IDENTITY_RULE_VERSION,
                "members": members, "creates_binding_ids": creates_ids,
                "source_ref": source_ref, "created_at": now,
            },
            bindings=bindings,
        )
        return {"answer": "same", "episode_id": episode_id, "envelope": envelope}

    relation = ANSWER_RELATION[answer_code]

    if not exists:
        _require(
            collapsed_text(candidate_telling_ref),
            "identity_answer_needs_episode_or_sibling",
            f"answering {answer_code!r} against a prospective pair names the sibling telling",
        )
        episode_id = _create_singleton(
            vault_root, ei.validate_telling_ref(candidate_telling_ref),
            source_ref=source_ref, now=now,
        )
    else:
        episode_id = candidate_episode

    existing = _active_binding(
        vault_root, telling_ref=telling, episode_id=episode_id, relation=relation,
    )
    binding, created = ei.file_event_identity(
        vault_root,
        telling_ref=telling, episode_id=episode_id, relation=relation,
        origin="confirmed", rule_version=ei.IDENTITY_RULE_VERSION,
        supersedes=_machine_origin_to_supersede(existing),
        evidence=evidence, source_ref=source_ref, created_at=now,
    )
    return {
        "answer": answer_code, "episode_id": episode_id, "relation": relation,
        "binding": binding, "created": created,
    }


# --------------------------------------------------------------------------
# "Not sure" — an epistemic state, filed and reopened (design §2.2, §13.4)
# --------------------------------------------------------------------------


def _deferrals_path(vault_root: str | Path) -> Path:
    root = store.store_path(vault_root, ".")
    return store.store_path(root, IDENTITY_DEFERRALS_FILE)


def read_deferrals(vault_root: str | Path) -> dict:
    """``{event_key: deferral}`` — a projection, safe to delete (see module
    docstring: the record of having asked is rebuildable bookkeeping, not a
    durable human decision)."""
    text = store.read_store_text(vault_root, IDENTITY_DEFERRALS_FILE)
    if text is None:
        return {}
    import json  # noqa: PLC0415

    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return {}
    rows = payload.get("deferrals") if isinstance(payload, dict) else None
    return dict(rows) if isinstance(rows, dict) else {}


def file_deferral(vault_root: str | Path, deferral: Mapping[str, object]) -> dict:
    """Write one "Not sure" deferral, keyed on the pair. Overwrites any prior
    deferral for the same pair — a fresh "Not sure" simply restarts the
    cooldown from now, which is the honest reading of the person saying it
    again."""
    rows = read_deferrals(vault_root)
    record = dict(deferral)
    rows[record["event_key"]] = record
    import json  # noqa: PLC0415

    payload = {"schema_version": 1, "deferrals": dict(sorted(rows.items()))}
    root = store.store_path(vault_root, ".")
    path = store.store_path(root, IDENTITY_DEFERRALS_FILE)
    try:
        atomic_write_vault_text(
            path, json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            vault_root=root,
        )
    except ValueError as exc:
        raise IdentityQuestionsError("identity_deferral_unwritable", str(exc)) from exc
    return record


def is_pair_deferred(
    vault_root: str | Path, event_key: str, *, evidence_signature: object = None, now: object
) -> bool:
    """§13.4: a pair answered Not sure is not re-asked inside the cooldown,
    and reopens early on material new evidence."""
    rows = read_deferrals(vault_root)
    row = rows.get(event_key)
    if row is None:
        return False
    return erc.cooldown_active(row, evidence_signature=evidence_signature, now=now)


# --------------------------------------------------------------------------
# `possible_overmerge` — the four answers (design §6.3, §12.5)
# --------------------------------------------------------------------------


def resolve_possible_overmerge_answer(
    vault_root: str | Path,
    *,
    telling_ref: object,
    episode_id: object,
    answer: object,
    destinations: Mapping[str, str] | None = None,
    references: Sequence[Mapping[str, object]] = (),
    source_ref: object = None,
    now: object = None,
) -> dict:
    """File one of `possible_overmerge`'s four answers.

    **keep together** files NOTHING — the audit's own rule
    (:data:`episode_routing_contract.FORBIDDEN_REAUDIT_ACTIONS`) already
    refuses a SYSTEM confirm; a person confirming the bind is simply not an
    identity write. **fix the date** is a date correction, never an identity
    write, and this function returns a typed no-write result naming the
    target rather than reaching for a writer it was not asked to use.
    """
    telling = ei.validate_telling_ref(telling_ref)
    episode = collapsed_text(episode_id)
    answer_code = collapsed_text(answer)
    _require(
        answer_code in OVERMERGE_ANSWERS,
        "identity_overmerge_answer_unknown",
        f"unknown possible_overmerge answer: {answer!r}",
    )
    if answer_code == "keep_together":
        return {"answer": "keep_together", "episode_id": episode, "written": False}
    if answer_code == "fix_the_date":
        return {
            "answer": "fix_the_date", "episode_id": episode, "written": False,
            "next": "an ordinary date correction on the disagreeing claim, "
                    "not an identity write",
        }
    if answer_code == "part_of":
        existing = _active_binding(
            vault_root, telling_ref=telling, episode_id=episode,
            relation=efc.GROUPING_RELATION,
        )
        binding, created = ei.file_event_identity(
            vault_root,
            telling_ref=telling, episode_id=episode, relation="part_of",
            origin="confirmed", rule_version=ei.IDENTITY_RULE_VERSION,
            supersedes=_machine_origin_to_supersede(existing),
            source_ref=source_ref, created_at=now,
        )
        return {"answer": "part_of", "episode_id": episode, "binding": binding, "created": created}
    # answer_code == "split"
    _require(
        destinations, "identity_answer_needs_episode_or_sibling",
        "a split names each departing telling and where it goes",
    )
    return split_episode(
        vault_root, episode_id=episode, destinations=dict(destinations),
        references=references, source_ref=source_ref, now=now,
    )


# --------------------------------------------------------------------------
# The split gesture (design §5.5, §12.5)
# --------------------------------------------------------------------------


def split_episode(
    vault_root: str | Path,
    *,
    episode_id: object,
    destinations: Mapping[str, str],
    references: Sequence[Mapping[str, object]] = (),
    source_ref: object = None,
    now: object = None,
) -> dict:
    """File one `split` envelope, then route every other reference off it.

    ``destinations`` is ``{departing_telling_ref: "standalone" | new episode
    id}`` exactly as §3.2 defines it. This function supersedes the departing
    tellings' active `same`/`part_of` bindings — each with the split
    envelope's `SPLIT_DEPARTURE_RELATION` (``"none"``) — routes each
    destination's own `create` when the departure names a NEW episode
    (never a dangling id, §3.2), and then calls
    `episode_routing_contract.split_routing` over ``references`` (§5.5's
    ordering constraints / era memberships / display decisions / labels /
    work items / open sessions / everything else) so the caller gets back
    ONE routing plan naming exactly where each reference goes — including
    the Mirror-judgment residue row for anything genuinely unattributable.
    """
    episode = collapsed_text(episode_id)
    routed = {
        ei.validate_telling_ref(ref): collapsed_text(where)
        for ref, where in dict(destinations or {}).items()
    }
    _require(routed, "identity_answer_needs_episode_or_sibling",
             "a split names each departing telling and where it goes")

    departing_bindings: list[dict] = []
    prior_bindings: list[dict] = []
    supersedes_ids: list[str] = []
    new_creates: dict[str, list[str]] = {}
    for telling, target in sorted(routed.items()):
        existing = None
        for relation in (efc.GROUPING_RELATION, "part_of"):
            existing = _active_binding(
                vault_root, telling_ref=telling, episode_id=episode, relation=relation,
            )
            if existing is not None:
                break
        supersede_id = existing["identity_id"] if existing else None
        if supersede_id:
            supersedes_ids.append(supersede_id)
            # The OLD binding must be among the envelope's own `bindings` for
            # `validate_envelope` to find what `supersedes_binding_ids` names
            # — filing it again is a no-op (create-or-keep, audit A6).
            prior_bindings.append(existing)
        departing_bindings.append({
            "telling_ref": telling, "episode_id": episode,
            "relation": ei.SPLIT_DEPARTURE_RELATION, "origin": "confirmed",
            "rule_version": ei.IDENTITY_RULE_VERSION,
            "supersedes": supersede_id, "source_ref": source_ref, "created_at": now,
        })
        if target != erc.SPLIT_DESTINATION_STANDALONE:
            new_creates.setdefault(target, []).append(telling)

    creates_binding_ids = [
        ei.binding_digest(
            telling_ref=row["telling_ref"], episode_id=row["episode_id"],
            relation=row["relation"], rule_version=row["rule_version"],
            supersedes=row["supersedes"],
        )
        for row in departing_bindings
    ]
    bindings = list(departing_bindings)
    # Each new destination gets its own `same` binding, created in the SAME
    # envelope (§3.2: a split destination is never a dangling id).
    for new_episode_id, members in sorted(new_creates.items()):
        for telling in sorted(members):
            payload = {
                "telling_ref": telling, "episode_id": new_episode_id,
                "relation": efc.GROUPING_RELATION, "origin": "confirmed",
                "rule_version": ei.IDENTITY_RULE_VERSION,
                "source_ref": source_ref, "created_at": now,
            }
            creates_binding_ids.append(ei.binding_digest(
                telling_ref=telling, episode_id=new_episode_id,
                relation=efc.GROUPING_RELATION, rule_version=ei.IDENTITY_RULE_VERSION,
            ))
            bindings.append(payload)

    envelope = ei.file_operation_envelope(
        vault_root,
        operation={
            "authority": "human", "op": "split", "rule_version": ei.IDENTITY_RULE_VERSION,
            "episode_id": episode, "destinations": routed,
            "supersedes_binding_ids": supersedes_ids,
            "creates_binding_ids": creates_binding_ids,
            "source_ref": source_ref, "created_at": now,
        },
        # The OLD bindings ride along too — an envelope's own `bindings`
        # must include every record its `supersedes_binding_ids` names, and
        # re-filing an already-existing one is a no-op (create-or-keep).
        bindings=prior_bindings + bindings,
    )
    routing = erc.split_routing(
        envelope=envelope["operation"], references=references,
    )
    return {"episode_id": episode, "envelope": envelope, "routing": routing.as_dict()}


__all__ = [
    "ANSWER_RELATION",
    "IDENTITY_DEFERRALS_FILE",
    "IDENTITY_QUESTIONS_ERROR_CODES",
    "IdentityQuestionsError",
    "OVERMERGE_ANSWERS",
    "RELATION_ANSWERS",
    "file_deferral",
    "is_pair_deferred",
    "read_deferrals",
    "resolve_possible_overmerge_answer",
    "resolve_same_event_answer",
    "split_episode",
]
