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
    "identity_merge_needs_absorbed_members",
    "containment_removal_needs_part_of",
    "containment_restore_needs_removal",
)

#: The two halves of design §5 rule 1 — the DRAG-OUT and its undo. Named as a
#: closed pair because they are one gesture read twice, and because a host
#: binding them (a CLI verb, a server route) should not be able to invent a
#: third.
CONTAINMENT_GESTURES = ("remove", "restore")


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


def _grouping_index(vault_root: str | Path) -> dict:
    """The properly-COLLAPSED active view (`episode_fold_contract.
    active_binding_index`) — never a raw scan filtered only by each record's
    own `status` field.

    Superseding a binding never flips the OLD record's own `status` to
    `"superseded"` — only a NEWER record's `supersedes` pointer says a prior
    one no longer counts, and `status` alone is a different, orthogonal
    concept (present at I0, never touched by a supersession). A raw filter
    on `status == "active"` therefore still finds an absorbed episode's OLD
    members after a merge, or the pre-confirmation record at a shared
    vertex — precisely the shape that let a merge's own idempotency check
    "pass" against a build that had lost its real short-circuit, for the
    wrong reason. This is the ONE collapsed view every lookup in this module
    reads from.
    """
    return efc.active_binding_index(ei.load_event_identities(vault_root))


def _active_same_episode(vault_root: str | Path, telling_ref: str) -> str | None:
    """The episode this telling is CURRENTLY `same`-bound to, if any — by a
    GROUPING-eligible origin (`episode_fold_contract.GROUPING_ORIGINS`:
    `stated`/`confirmed`/`deterministic`, never `proposed` — §2.3's "only
    the first three affect grouping", applied here too: an unconfirmed
    machine guess is not a home a composition decision should route around).

    Read FRESH at filing time — never trusted from a binder report's own
    precomputed pair. A telling confirmed into an episode by an EARLIER
    answer in the same batch is exactly what this catches: the a3-triangle
    defect (three tellings, two confirmed pairs sharing one telling) filed
    each pair against the report's own stale prospective id and produced two
    active `same` bindings on the shared telling — `identity_conflict`,
    correctly refused, on the very first fold or binder run afterward. This
    function is what lets the SECOND answer see what the FIRST one just did.
    """
    binding = efc.grouping_binding(telling_ref, _grouping_index(vault_root))
    return collapsed_text(binding.get("episode_id")) or None if binding else None


def _grouped_members(vault_root: str | Path, episode_id: str) -> dict[str, dict]:
    """``{telling_ref: binding}`` for every telling CURRENTLY grouped (by a
    grouping-eligible `same` binding) into ``episode_id`` — the merge growth
    path's own read of "who actually still belongs here right now".
    """
    index = _grouping_index(vault_root)
    found: dict[str, dict] = {}
    for telling_ref in index:
        binding = efc.grouping_binding(telling_ref, index)
        if binding is not None and collapsed_text(binding.get("episode_id")) == episode_id:
            found[telling_ref] = binding
    return found


def _resolve_counterpart(
    vault_root: str | Path, *, candidate_episode_id: object, candidate_telling_ref: object,
) -> tuple[str | None, str | None]:
    """``(counterpart_telling_ref, counterpart_episode_id)`` — read FRESH,
    never assumed from what a report said when it was generated.

    A pair's candidate half reaches this module three ways: a REAL existing
    episode id (§4.1's `candidate_kind == "episode"`); a raw sibling telling
    ref with NO episode id at all — a genuinely prospective pair, or simply a
    caller that only ever learned the counterpart's own ref (§6.1's own
    rehearsal calls it exactly this way, so `candidate_episode_id` is
    optional here); or a PROSPECTIVE id `episode_binder.prospective_episode_id`
    computed at REPORT time, which an earlier answer in the same batch may
    since have made stale. The precomputed id is trusted only when the vault
    actually holds an episode under it — never for routing a decision.
    """
    episode = collapsed_text(candidate_episode_id)
    telling = collapsed_text(candidate_telling_ref)
    if episode and _episode_exists(vault_root, episode):
        sibling = ei.validate_telling_ref(telling) if telling else None
        return sibling, episode
    if telling:
        sibling = ei.validate_telling_ref(telling)
        return sibling, _active_same_episode(vault_root, sibling)
    return None, None


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


def _pair_binding(vault_root: str | Path, *, telling_ref: str, episode_id: str) -> dict | None:
    """The one ACTIVE binding this EXACT (telling, episode) pair currently
    holds, of ANY relation — never assumed `same`-only. From the properly
    collapsed view (:func:`_grouping_index`), so a binding a prior answer
    already superseded is never mistaken for what the pair says now.

    This is the read behind two rules at once (event identity I3c): a
    healthy vault never has more than one active relation on one exact
    pair (`episode_fold_contract.active_binding_index`'s own per-pair
    refusal, `identity_conflict` — proactively avoided here rather than
    triggered), so whatever this returns IS the pair's current answer,
    whole.
    """
    for row in _grouping_index(vault_root).get(telling_ref) or ():
        if collapsed_text(row.get("episode_id")) == episode_id:
            return row
    return None


def _bind_into_episode(
    vault_root: str | Path, *, telling_ref: str, episode_id: str,
    evidence: object = None, source_ref: object = None, now: object = None,
) -> dict:
    """One telling, bound `same` into an EXISTING episode — the growth path
    for case (a): one side of a confirmed pair already belongs somewhere,
    the other is standalone. Also the "same episode already" case, and the
    containment-absorption case (I3c) — one function, because in a healthy
    vault the pair carries at most ONE prior answer and this reads it once.

    No NEW operation envelope is minted. Active bindings are the sole fold
    authority (design §3.2); C2's operation vocabulary has no `add`, and
    `episode_binder.CLUSTER_RULE_TEXT`'s create-over-the-whole-cluster-and-
    alias path is the answer for a DETERMINISTIC rule specifically because a
    rule must stay REPRODUCIBLE from a digest of its inputs — re-run the
    binder on the same durable state and the same id must come back. A
    human's confirmed answer carries no such constraint: it is itself the
    durable fact, so one bare binding into the episode that already exists
    is the complete, correct record, with no id to re-derive and nothing to
    alias.

    **`same` ABSORBS membership (I3c, a real defect found rehearsing the
    founder apply pass).** `bind-episodes --apply`'s containment rung can
    file a `part_of` binding for this exact (telling, episode) pair before
    anyone ever answers a `same_event` question about it — the telling
    stops being a MEMBER and becomes the thing itself the moment a person
    confirms `same`, so the new binding supersedes whatever the pair
    already said, `part_of` included, exactly as it already superseded a
    machine `same` proposal. Only one prior answer can be active on one
    exact pair in a healthy vault, so ONE `supersedes` reference — the
    pair's own existing binding, whatever its relation — is always enough.
    """
    existing = _pair_binding(vault_root, telling_ref=telling_ref, episode_id=episode_id)
    if (
        existing is not None
        and existing.get("relation") == efc.GROUPING_RELATION
        and existing.get("origin") in ei.HUMAN_ORIGINS
    ):
        # Already a human `same` decision naming this exact pair — true
        # idempotency, not a fresh supersession chain (§5.8 row 2). Checked
        # and returned BEFORE anything is written, per §13.4's "answering
        # twice is idempotent by record digest" — no new record, not even a
        # superseding one, for a pair that already says exactly this.
        return {"answer": "same", "episode_id": episode_id, "binding": existing, "created": False}
    # `existing`, whatever it is, is superseded here: a machine `same`
    # proposal (the ordinary origin-transition), or a `part_of`/`related`/
    # `not_same` binding on the identical pair (`same` absorbing
    # membership, I3c) — one prior answer, one `supersedes` reference.
    binding, created = ei.file_event_identity(
        vault_root,
        telling_ref=telling_ref, episode_id=episode_id, relation=efc.GROUPING_RELATION,
        origin="confirmed", rule_version=ei.IDENTITY_RULE_VERSION,
        supersedes=existing["identity_id"] if existing is not None else None,
        evidence=evidence or {}, source_ref=source_ref, created_at=now,
    )
    return {"answer": "same", "episode_id": episode_id, "binding": binding, "created": created}


def _merge_order(vault_root: str | Path, episode_a: str, episode_b: str) -> tuple[str, str]:
    """``(survivor, absorbed)`` — deterministic, so replaying a merge (in
    either direction, or from either side of the pair) always picks the same
    side. An ADOPTED episode survives over an unadopted one — the human
    growth path's own echo of `CLUSTER_RULE_TEXT`'s "an adopted episode is
    never superseded" — because durable references (a URL, an open session,
    a work item) may already point at it. Otherwise the lexicographically
    smaller id survives, which is arbitrary but stable.
    """
    a_adopted = ei.is_adopted(vault_root, episode_a)
    b_adopted = ei.is_adopted(vault_root, episode_b)
    if a_adopted and not b_adopted:
        return episode_a, episode_b
    if b_adopted and not a_adopted:
        return episode_b, episode_a
    return tuple(sorted((episode_a, episode_b)))  # type: ignore[return-value]


def _existing_merge(vault_root: str | Path, *, episode_a: str, episode_b: str) -> dict | None:
    """A prior ACTIVE `merge` already joining these two episodes, found by
    the STABLE unordered pair they name — never by recomputing a digest.

    A merge's own `operation_id` digests `member_refs_sorted` too (C2's
    generic operation validator does not special-case merges), and those
    members are the absorbed episode's tellings AT FILING TIME — which
    become EMPTY the instant the merge succeeds. Recomputing "the same"
    digest after the fact is therefore structurally impossible once the
    merge has run; the pair of episode ids a merge names in its own
    `canonical_inputs.acted_on_episode_ids` is stable forever and is what
    this searches by instead.
    """
    pair = sorted((collapsed_text(episode_a), collapsed_text(episode_b)))
    for record in ei.load_episode_operations(vault_root):
        if record.get("op") != "merge" or record.get("status") != "active":
            continue
        acted = sorted((record.get("canonical_inputs") or {}).get("acted_on_episode_ids") or ())
        if acted == pair:
            return record
    return None


def _merge_episodes(
    vault_root: str | Path, *, episode_a: str, episode_b: str,
    source_ref: object = None, now: object = None,
) -> dict:
    """Join two episodes into one, human authority — case (b): a confirmed
    pair whose two sides already belong to DIFFERENT episodes (including a
    third answer joining two otherwise-mature episodes, §12.5).

    Files ONE `merge` envelope (design §3.2): every active `same` member of
    the absorbed episode gets a fresh confirmed binding into the survivor,
    each superseding its own prior binding, and the absorbed id resolves
    forever via `aliases_created` (Law 5). Replaying the SAME merge — from
    either side, in either call order — is a no-op: :func:`_existing_merge`
    finds the prior envelope, by the STABLE pair of episode ids it names,
    before touching a single binding — which matters because by the time a
    replay arrives the absorbed episode legitimately has NO active members
    left to gather (they were already moved).
    """
    _require(
        collapsed_text(episode_a) and collapsed_text(episode_b),
        "identity_merge_needs_absorbed_members",
        "a merge needs both episode ids",
    )
    if episode_a == episode_b:
        return {"answer": "same", "episode_id": episode_a, "written": False,
                "reason": "already the same episode"}
    survivor, absorbed = _merge_order(vault_root, episode_a, episode_b)
    prior = _existing_merge(vault_root, episode_a=survivor, episode_b=absorbed)
    if prior is not None:
        return {
            "answer": "same", "episode_id": survivor, "merged": absorbed,
            "envelope": {"operation": prior, "bindings": [], "created": False,
                        "operation_created": False},
        }
    absorbed_bindings = _grouped_members(vault_root, absorbed)
    _require(
        absorbed_bindings, "identity_merge_needs_absorbed_members",
        f"{absorbed} has no active `same` members to move into {survivor}",
    )
    members = sorted(absorbed_bindings)
    creates_ids: list[str] = []
    supersedes_ids: list[str] = []
    bindings: list[dict] = []
    for telling in members:
        old = absorbed_bindings[telling]
        supersedes_ids.append(old["identity_id"])
        # The OLD binding rides along too, exactly as `split_episode` does —
        # an envelope's own `bindings` must include every record its
        # `supersedes_binding_ids` names, and re-filing an unchanged one is a
        # no-op (create-or-keep).
        bindings.append(dict(old))
        # I3c: the telling may ALSO already carry a stray binding of some
        # OTHER relation directly on the SURVIVOR (a containment membership
        # `bind-episodes` filed before anyone merged anything). `same`
        # absorbs it exactly as `_bind_into_episode` does — but `supersedes`
        # only names ONE record, and the absorbed-episode retirement above
        # is mandatory for the merge itself, so when both exist the two
        # retirements ride TWO records: the absorbed-episode `same` retires
        # via its own `none`-relation departure (the split-departure shape),
        # and the new `same` into the survivor supersedes the STRAY record
        # instead of `old`.
        stray = _pair_binding(vault_root, telling_ref=telling, episode_id=survivor)
        if stray is not None and stray.get("relation") != efc.GROUPING_RELATION:
            departure_id = ei.binding_digest(
                telling_ref=telling, episode_id=absorbed,
                relation=ei.SPLIT_DEPARTURE_RELATION, rule_version=ei.IDENTITY_RULE_VERSION,
                supersedes=old["identity_id"],
            )
            creates_ids.append(departure_id)
            bindings.append({
                "telling_ref": telling, "episode_id": absorbed,
                "relation": ei.SPLIT_DEPARTURE_RELATION, "origin": "confirmed",
                "rule_version": ei.IDENTITY_RULE_VERSION,
                "supersedes": old["identity_id"],
                "source_ref": source_ref, "created_at": now,
            })
            supersedes_ids.append(stray["identity_id"])
            bindings.append(dict(stray))
            new_supersede = stray["identity_id"]
        else:
            new_supersede = old["identity_id"]
        creates_ids.append(ei.binding_digest(
            telling_ref=telling, episode_id=survivor,
            relation=efc.GROUPING_RELATION, rule_version=ei.IDENTITY_RULE_VERSION,
            supersedes=new_supersede,
        ))
        bindings.append({
            "telling_ref": telling, "episode_id": survivor,
            "relation": efc.GROUPING_RELATION, "origin": "confirmed",
            "rule_version": ei.IDENTITY_RULE_VERSION,
            # Names whichever prior record this exact NEW binding retires —
            # the absorbed-episode `same` when the survivor pair was clean,
            # or the stray record above when it was not. WITHOUT this,
            # `validate_identity_set`/`active_binding_index` have no record
            # whose `supersedes` names the old one, it stays "active"
            # forever alongside the new one, and the very next fold refuses
            # with the `identity_conflict` this whole function exists to
            # prevent.
            "supersedes": new_supersede,
            "source_ref": source_ref, "created_at": now,
        })
    envelope = ei.file_operation_envelope(
        vault_root,
        operation={
            "authority": "human", "op": "merge", "rule_version": ei.IDENTITY_RULE_VERSION,
            "episode_id": survivor, "absorbed_episode_id": absorbed,
            "members": members, "creates_binding_ids": creates_ids,
            "supersedes_binding_ids": supersedes_ids,
            "aliases_created": [absorbed],
            "source_ref": source_ref, "created_at": now,
        },
        bindings=bindings,
    )
    return {"answer": "same", "episode_id": survivor, "envelope": envelope, "merged": absorbed}


# --------------------------------------------------------------------------
# `same_event` — the five answers (design §6.1, §13.4)
# --------------------------------------------------------------------------


def resolve_same_event_answer(
    vault_root: str | Path,
    *,
    telling_ref: object,
    answer: object,
    candidate_episode_id: object = None,
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

    **Composition, not a second violation of Law 2.** The founder's own
    confirmed pairs overlap — one telling can be the shared vertex of several
    confirmed `same` answers, arriving in any order, each one filed against
    whatever the report said BEFORE any of them were answered. Treating every
    answer as "create a fresh episode for this prospective pair" mints a
    SECOND active `same` binding on the shared telling the moment two such
    answers land, which the fold correctly refuses (`identity_conflict`).
    This function instead reads each side's CURRENT membership fresh, at
    filing time, and routes through C2's own operations: a standalone
    counterpart is bound INTO an existing side's episode
    (:func:`_bind_into_episode`); two sides already in different episodes are
    merged (:func:`_merge_episodes`, also what a third answer joining two
    otherwise-mature episodes does); the same episode already is a no-op;
    and only two genuinely standalone sides mint a fresh `create`.
    `candidate_episode_id` is OPTIONAL — a caller that only ever learned the
    counterpart's own telling ref names it in `candidate_telling_ref` alone
    (:func:`_resolve_counterpart`).
    """
    telling = ei.validate_telling_ref(telling_ref)
    answer_code = collapsed_text(answer)
    _require(
        answer_code in RELATION_ANSWERS,
        "identity_answer_unknown",
        f"unknown same_event answer: {answer!r}",
    )
    evidence = {
        "telling_quote": collapsed_text(telling_quote),
        "episode_quote": collapsed_text(episode_quote),
    }
    counterpart_ref, counterpart_episode = _resolve_counterpart(
        vault_root, candidate_episode_id=candidate_episode_id,
        candidate_telling_ref=candidate_telling_ref,
    )

    if answer_code == "not_sure":
        candidate_key = collapsed_text(candidate_episode_id) or counterpart_episode \
            or counterpart_ref or collapsed_text(candidate_telling_ref)
        _require(
            candidate_key, "identity_answer_needs_episode_or_sibling",
            "a deferral names the pair it defers",
        )
        deferral = erc.defer_pair(
            telling_ref=telling, candidate_episode_id=candidate_key,
            evidence_signature=evidence, now=now,
        )
        record = file_deferral(vault_root, deferral)
        return {"answer": "not_sure", "event_key": deferral["event_key"], "deferral": record}

    telling_episode = _active_same_episode(vault_root, telling)

    if answer_code == "same":
        if telling_episode and counterpart_episode:
            if telling_episode == counterpart_episode:
                # Both sides already point at the SAME episode — including
                # the origin-transition case where `candidate_episode_id` is
                # exactly the episode a prior PROPOSAL already named: that is
                # not "nothing to do", it is "confirm the proposal", so this
                # reuses `_bind_into_episode`'s own existing/no-op/supersede
                # judgment rather than a bespoke no-op here.
                return _bind_into_episode(
                    vault_root, telling_ref=telling, episode_id=telling_episode,
                    evidence=evidence, source_ref=source_ref, now=now,
                )
            return _merge_episodes(
                vault_root, episode_a=telling_episode, episode_b=counterpart_episode,
                source_ref=source_ref, now=now,
            )
        if telling_episode and not counterpart_episode:
            _require(
                counterpart_ref, "identity_answer_needs_sibling",
                "confirming Same against a standalone counterpart names its telling ref",
            )
            return _bind_into_episode(
                vault_root, telling_ref=counterpart_ref, episode_id=telling_episode,
                evidence=evidence, source_ref=source_ref, now=now,
            )
        if counterpart_episode and not telling_episode:
            return _bind_into_episode(
                vault_root, telling_ref=telling, episode_id=counterpart_episode,
                evidence=evidence, source_ref=source_ref, now=now,
            )
        # Both sides standalone: a fresh `create` over exactly the two of
        # them, `authority: human` — R1 already declined this pair, so
        # nothing deterministic would ever re-derive it, and this id is
        # legitimately different from the report's own prospective one
        # (`episode_binder.prospective_episode_id`, `authority:
        # deterministic`).
        _require(
            counterpart_ref, "identity_answer_needs_sibling",
            "confirming Same against a prospective pair names the sibling telling",
        )
        members = sorted({telling, counterpart_ref})
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

    if counterpart_episode:
        episode_id = counterpart_episode
    else:
        _require(
            counterpart_ref,
            "identity_answer_needs_episode_or_sibling",
            f"answering {answer_code!r} against a prospective pair names the sibling telling",
        )
        episode_id = _create_singleton(vault_root, counterpart_ref, source_ref=source_ref, now=now)

    # `same` ABSORBS membership; the reverse never happens (I3c). A pair the
    # person already confirmed `same` on is not up for revision by a
    # DIFFERENT relation on the identical pair — that is a contradiction of
    # what they already said, not a correction of it. The way out is a
    # `possible_overmerge` split (or an ordinary answer on a genuinely
    # different candidate pair), never a silent overwrite here.
    pair_now = _pair_binding(vault_root, telling_ref=telling, episode_id=episode_id)
    _require(
        pair_now is None or pair_now.get("relation") != efc.GROUPING_RELATION,
        "identity_answer_contradicts_same",
        f"{telling} already carries an active `same` binding to {episode_id}; "
        f"answering {answer_code!r} on the identical pair would contradict it, "
        "not revise it",
    )
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
# Out of a container, and back in — design §5 rules 1 and 2, audit H5
# --------------------------------------------------------------------------


def _creation_inputs(vault_root: str | Path, episode_id: str,
                     container_telling_ref: object = None) -> tuple[dict, str | None]:
    """``(creation canonical inputs, canonical event kind)`` for an adopt.

    Three cases and no guessing. An episode an operation CREATED carries its
    own canonical inputs, and they are copied. A PARTICIPATION container —
    a residence, a job, a schooling minted by the recorder rather than by an
    identity operation — has no create envelope at all, and its id is the one
    a deterministic create naming its opening telling ALONE would mint
    (`episode_containers.container_episode_id`), so given that telling the
    inputs are re-derived rather than remembered. Given neither, the envelope
    carries an empty view: an adopt whose inputs are unknown is still a
    durable record of the person's decision, and inventing inputs to fill the
    field would make the id explainable from something nobody filed.
    """
    for record in ei.load_episode_operations(vault_root):
        if record.get("status") != "active" or record.get("episode_id") != episode_id:
            continue
        if collapsed_text(record.get("op")) == "create":
            return (dict(record.get("canonical_inputs") or {}),
                    collapsed_text(record.get("canonical_event_kind")) or None)
    telling = collapsed_text(container_telling_ref)
    if telling:
        return ei.canonical_operation_inputs(
            authority="deterministic", op="create",
            rule_version=ei.IDENTITY_RULE_VERSION,
            member_refs=[telling],
        ), None
    return {}, None


def remove_from_container(
    vault_root: str | Path,
    *,
    telling_ref: object,
    episode_id: object,
    container_telling_ref: object = None,
    reason: object = None,
    source_ref: object = None,
    now: object = None,
) -> dict:
    """DRAG-OUT: *this telling is not in that container any more* (§5 rule 1).

    Audit finding H5, completed. Retraction of an era membership was already
    durable and `not_same` was already consulted by the binder, but `not_same`
    is the WRONG relation for this — it asserts the two are different EVENTS,
    which is a claim nobody made, and the containment rung never reads it. The
    relation that says exactly this already exists
    (`event_identity.SPLIT_DEPARTURE_RELATION`), so a removal is a ``stated``
    ``none`` binding on the (telling, episode) pair, superseding the active
    ``part_of``, plus an ``adopt`` envelope when the episode had not been
    touched by a person before (event identity's lifecycle row 3 — the moment
    a person acts on a deterministic episode its identity becomes durable
    human authority).

    ONE vault mutation and IDEMPOTENT BY DIGEST: a second removal of the same
    pair writes nothing and reports ``created: False``, because the record it
    would write is the record already on disk (create-or-keep, audit A6).

    The refusal is narrow and named. A pair the person confirmed ``same`` is
    not removed by this verb — that would contradict what they said rather
    than correct it, exactly as `_bind_into_episode`'s own comment reasons in
    the other direction; the way out of a wrong ``same`` is a split.
    """
    telling = ei.validate_telling_ref(telling_ref)
    episode = collapsed_text(episode_id)
    existing = _pair_binding(vault_root, telling_ref=telling, episode_id=episode)
    relation = collapsed_text(existing.get("relation")) if existing else ""
    if relation == ei.SPLIT_DEPARTURE_RELATION:
        return {"gesture": "remove", "episode_id": episode, "telling_ref": telling,
                "relation": relation, "binding": existing, "created": False,
                "adopted": False}
    _require(
        existing is None or relation == "part_of",
        "containment_removal_needs_part_of",
        f"{telling} → {episode} is an active {relation or 'absent'} binding; a "
        "removal supersedes a `part_of` and nothing else",
    )
    adopted = False
    if existing is not None and not ei.is_adopted(vault_root, episode):
        inputs, kind = _creation_inputs(vault_root, episode, container_telling_ref)
        ei.file_adopt_envelope(
            vault_root, episode_id=episode, creation_canonical_inputs=inputs,
            canonical_event_kind=kind, source_ref=source_ref, created_at=now,
        )
        adopted = True
    binding, created = ei.file_event_identity(
        vault_root,
        telling_ref=telling, episode_id=episode,
        relation=ei.SPLIT_DEPARTURE_RELATION, origin="stated",
        rule_version=ei.IDENTITY_RULE_VERSION,
        supersedes=existing["identity_id"] if existing is not None else None,
        evidence={"reason": collapsed_text(reason)} if collapsed_text(reason) else {},
        source_ref=source_ref, created_at=now,
    )
    return {"gesture": "remove", "episode_id": episode, "telling_ref": telling,
            "relation": ei.SPLIT_DEPARTURE_RELATION, "binding": binding,
            "created": created, "adopted": adopted}


def restore_to_container(
    vault_root: str | Path,
    *,
    telling_ref: object,
    episode_id: object,
    reason: object = None,
    source_ref: object = None,
    now: object = None,
) -> dict:
    """UNDO the drag-out: a ``stated`` ``part_of`` superseding the ``none``.

    One tap, and from then on the pair is HUMAN-placed rather than back in the
    rung's hands (§5 rule 1) — which is why the restored record's origin is
    ``stated`` and not a re-run of the rule. Idempotent: restoring a pair that
    already carries an active ``part_of`` writes nothing.
    """
    telling = ei.validate_telling_ref(telling_ref)
    episode = collapsed_text(episode_id)
    existing = _pair_binding(vault_root, telling_ref=telling, episode_id=episode)
    relation = collapsed_text(existing.get("relation")) if existing else ""
    if relation == "part_of":
        return {"gesture": "restore", "episode_id": episode, "telling_ref": telling,
                "relation": relation, "binding": existing, "created": False}
    _require(
        existing is not None and relation == ei.SPLIT_DEPARTURE_RELATION,
        "containment_restore_needs_removal",
        f"{telling} → {episode} carries no active removal to undo "
        f"(it is {relation or 'absent'})",
    )
    binding, created = ei.file_event_identity(
        vault_root,
        telling_ref=telling, episode_id=episode, relation="part_of",
        origin="stated", rule_version=ei.IDENTITY_RULE_VERSION,
        supersedes=existing["identity_id"],
        evidence={"reason": collapsed_text(reason)} if collapsed_text(reason) else {},
        source_ref=source_ref, created_at=now,
    )
    return {"gesture": "restore", "episode_id": episode, "telling_ref": telling,
            "relation": "part_of", "binding": binding, "created": created}


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
        # The overmerge audit's own sanctioned reverse: demoting an ACTIVE
        # `same` to `part_of` is exactly what this answer is FOR (I3c),
        # unlike a bare `same_event` pair's `part_of` answer, which never
        # overwrites one. Superseded unconditionally, regardless of origin —
        # a human's own overmerge decision, not an origin-transition.
        existing = _active_binding(
            vault_root, telling_ref=telling, episode_id=episode,
            relation=efc.GROUPING_RELATION,
        )
        binding, created = ei.file_event_identity(
            vault_root,
            telling_ref=telling, episode_id=episode, relation="part_of",
            origin="confirmed", rule_version=ei.IDENTITY_RULE_VERSION,
            supersedes=existing["identity_id"] if existing is not None else None,
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

# Not part of the public seam (no vocabulary, no new writer), but exposed for
# the property tests this fix's own promises need: composing an overlapping
# pair set has to be provable at the routing/merge granularity, not only at
# the whole-answer one.
__all__ += [
    "_active_same_episode",
    "_bind_into_episode",
    "_existing_merge",
    "_grouped_members",
    "_grouping_index",
    "_merge_episodes",
    "_merge_order",
    "_resolve_counterpart",
]
