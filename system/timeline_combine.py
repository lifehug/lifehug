"""Combine and fold by drag — v365 (owner, 2026-09-26) (the owner).

The owner, on the Timeline's rows and landmark lines: dropping a row BETWEEN
rows places it (the move plus drag-to-tighten, unchanged). Two more gestures
share the same drag:

* :data:`A_ROW_DROPPED_ON_A_ROW_IS_THE_SAME_MOMENT` — dropped ONTO the middle
  of another row it means "these are the same moment". The two become one
  moment carrying both tellings. It is his statement and undoable like a move.
* :data:`A_ROW_DROPPED_ON_A_LANDMARK_FOLDS_INTO_IT` — dropped onto a landmark's
  boundary line (or the lines closing an empty landmark's slim row) it FOLDS
  into that landmark: it stops being a row and its telling shows in the
  landmark's form under "Your words about this". His statement, undoable.

What this module is, and what it is not:

* It invents NO identity store. A combine is event identity's own act — the
  `same_event` confirm (`identity_questions.resolve_same_event_answer`, the
  `resolve-work-item --kind same_event --answer same` path) for the first
  pair, `identity_questions._bind_into_episode` for any further tellings of a
  side, and its undo is `identity_questions.split_episode` (the
  `split-episode` path). A fold is the `landmark_fold` machinery
  (`folded_into_landmark`), with an owner-stated fold record the publisher
  reads (:func:`stated_folds`).
* What IS new is the statement each gesture files — ONE immutable correction
  source under ``sources/corrections/`` (``combine-<24 hex>.md``,
  ``landmark-fold-<24 hex>.md``), the same kind of record a move files
  (``move-<24 hex>.md``). It is his words for the act; every identity record a
  combine writes cites it as its ``source_ref``. It also carries the state the
  act found (which tellings were in which episode), so its undo knows what to
  give back. An undo is one more such source (``…-undo-<24 hex>.md``) naming
  the statement it undoes; nothing is deleted.

Synthetic data only in its tests.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import temporal_store as store
from temporal_claims import CORRECTION_SOURCES_DIR, TemporalContractError, collapsed_text

#: The owner's rulings, as the rules' names (v365 (owner, 2026-09-26)).
A_ROW_DROPPED_ON_A_ROW_IS_THE_SAME_MOMENT = (
    "a row dropped onto the middle of another row says they are the same "
    "moment: its tellings join the other's episode (event identity's own "
    "same_event confirm), both tellings kept, as the person's statement; undo "
    "splits them apart again"
)
A_ROW_DROPPED_ON_A_LANDMARK_FOLDS_INTO_IT = (
    "a row dropped onto a landmark's boundary line folds into that landmark: "
    "it is no longer drawn as a row, its tellings show in the landmark's form, "
    "and the fold is the person's statement; undo gives the row back"
)

COMBINE_RULE_VERSION = "timeline-combine:1"

COMBINE_TYPE = "timeline_combine"
COMBINE_UNDO_TYPE = "timeline_combine_undo"
FOLD_TYPE = "landmark_fold_statement"
FOLD_UNDO_TYPE = "landmark_fold_undo"

_PREFIX = {COMBINE_TYPE: "combine", COMBINE_UNDO_TYPE: "combine-undo",
           FOLD_TYPE: "landmark-fold", FOLD_UNDO_TYPE: "landmark-fold-undo"}
_ID_PREFIX = {COMBINE_TYPE: "combine", COMBINE_UNDO_TYPE: "combine-undo",
              FOLD_TYPE: "fold", FOLD_UNDO_TYPE: "fold-undo"}
_ID_RE = {"combine": re.compile(r"^combine:[0-9a-f]{24}$"), "fold": re.compile(r"^fold:[0-9a-f]{24}$")}

STANDALONE = "standalone"


class CombineError(TemporalContractError):
    """A combine or a fold could not be filed, with a code."""


def _require(condition: object, code: str, message: str) -> None:
    if not condition:
        raise CombineError(code, message)


# --------------------------------------------------------------------------
# The statement: one immutable correction source per act
# --------------------------------------------------------------------------

def _digest(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"))
                          .encode("utf-8")).hexdigest()[:24]


def _file_statement(vault_root: str | Path, *, kind: str, identity: dict, fields: dict,
                    sentence: str, reason: str = "", author: str | None = None,
                    now: object = None) -> dict:
    """File (or keep) one statement source. Idempotent on ``identity``."""
    short = _digest({"kind": kind, **identity})
    relative = f"{CORRECTION_SOURCES_DIR}/{_PREFIX[kind]}-{short}.md"
    statement_id = f"{_ID_PREFIX[kind]}:{short}"
    heading = collapsed_text(sentence)
    payload = f"# {heading}\n\n{collapsed_text(reason)[:2000] or heading}\n"
    frontmatter = {
        "title": heading,
        "type": kind,
        "source_id": f"correction:{_PREFIX[kind]}-{short}",
        "source_medium": collapsed_text(author) or "owner",
        "statement_id": statement_id,
        "rule_version": COMBINE_RULE_VERSION,
        **fields,
        "captured_at": store.normalized_timestamp(now, error=CombineError),
        "visibility": "owner_only",
        "status": "raw",
        "immutable": True,
        "schema_version": store.SCHEMA_VERSION,
        "source_path": relative,
        "content_sha256": store.payload_sha256(payload),
    }
    _, created = store.create_or_keep(vault_root, relative,
                                      f"{store.format_frontmatter(frontmatter)}\n\n{payload}")
    return {"statement_id": statement_id, "relative_path": relative, "created": created}


def _statements(vault_root: str | Path, kind: str) -> list[dict]:
    """Every statement of one kind on disk, oldest captured first."""
    base = Path(str(vault_root)) / CORRECTION_SOURCES_DIR
    if not base.is_dir():
        return []
    out = []
    for path in sorted(base.glob(f"{_PREFIX[kind]}-*.md")):
        relative = f"{CORRECTION_SOURCES_DIR}/{path.name}"
        text = store.read_store_text(vault_root, relative)
        if text is None:
            continue
        metadata, _body = store.split_frontmatter(text)
        if collapsed_text(metadata.get("type")) != kind:
            continue
        out.append({**metadata, "relative_path": relative})
    return sorted(out, key=lambda row: (collapsed_text(row.get("captured_at")),
                                        collapsed_text(row.get("statement_id"))))


def _undone_ids(vault_root: str | Path, undo_kind: str) -> set[str]:
    return {collapsed_text(row.get("undoes")) for row in _statements(vault_root, undo_kind)}


def _active(vault_root: str | Path, kind: str, undo_kind: str) -> list[dict]:
    undone = _undone_ids(vault_root, undo_kind)
    return [row for row in _statements(vault_root, kind)
            if collapsed_text(row.get("statement_id")) not in undone]


# --------------------------------------------------------------------------
# Which tellings a drawn row IS
# --------------------------------------------------------------------------

def _projection(vault_root: str | Path) -> dict:
    import temporal_publication as pub  # noqa: PLC0415

    return pub.read_projection(vault_root) or {}


def _drawn_nodes(projection: dict) -> dict[str, dict]:
    return {collapsed_text(n.get("node_id")): n for n in projection.get("nodes") or ()
            if isinstance(n, dict) and collapsed_text(n.get("node_id"))}


def node_tellings(vault_root: str | Path, projection: dict, node_id: str) -> tuple[list[str], str | None]:
    """``(tellings, episode_id)`` — what one drawn row is made of.

    An episode row is its episode's current ``same`` members (the one
    collapsed view `identity_questions` reads). Any other row is the tellings
    of its own claims (`episode_fold.claim_telling_index`, the fold's own
    reading, manifest first) — without the system's derivations, without a
    landmark record's telling, and without a telling that ALSO backs another
    drawn row: binding that one would carry the other row along, which is not
    what the person dropped."""
    import episode_fold as ef  # noqa: PLC0415
    import event_identity as ei  # noqa: PLC0415
    import identity_questions as iq  # noqa: PLC0415

    nodes = _drawn_nodes(projection)
    node = nodes.get(collapsed_text(node_id))
    _require(node is not None, "combine_node_not_drawn", f"{node_id} is not a drawn row")
    episode = collapsed_text(node.get("episode_id"))
    if episode:
        members = sorted(iq._grouped_members(vault_root, episode))  # noqa: SLF001 - the one collapsed view
        if members:
            return members, episode
    index = store.read_active_index(vault_root) or {}
    claims = {collapsed_text(c.get("claim_id")): c for c in store.active_claims(index)}
    try:
        manifest = ei.read_telling_manifest(vault_root)
    except TemporalContractError:
        manifest = None
    tellings = ef.claim_telling_index(claims.values(), manifest)

    def own(row: dict, *, derived: bool = False) -> list[str]:
        out = []
        for ref in row.get("input_claim_refs") or ():
            claim = claims.get(collapsed_text(ref))
            if not claim:
                continue
            if (collapsed_text(claim.get("source_kind")) == "system_derived") != derived:
                continue
            telling = tellings.get(collapsed_text(ref))
            if telling and not telling.startswith(("landmark:", "landmark_")) and telling not in out:
                out.append(telling)
        return out

    def exclusive(derived: bool) -> list[str]:
        others: set[str] = set()
        for other_id, other in nodes.items():
            if other_id != collapsed_text(node_id) and other.get("node_kind") != "period":
                others.update(own(other, derived=derived))
        return [t for t in own(node, derived=derived) if t not in others]

    # His tellings first. A row the system alone told (a resolver's reading)
    # is combined through that reading's own telling, when no other row has it.
    return exclusive(False) or exclusive(True), None


# --------------------------------------------------------------------------
# Combine
# --------------------------------------------------------------------------

def _label(node: dict | None) -> str:
    return collapsed_text((node or {}).get("label")) or collapsed_text((node or {}).get("node_id"))


def combine(vault_root: str | Path, *, subject_node_id: str, target_node_id: str,
            reason: str = "", author: str | None = None, now: object = None,
            projection: dict | None = None) -> dict:
    """:data:`A_ROW_DROPPED_ON_A_ROW_IS_THE_SAME_MOMENT`. Files, does not publish.

    The subject's tellings join the target's (or, when neither side is an
    episode yet, the two found one — `authority: human`, as a confirmed
    `same_event` answer does). Returns ``{combine_id, episode_id, ...}``."""
    import identity_questions as iq  # noqa: PLC0415

    subject_id, target_id = collapsed_text(subject_node_id), collapsed_text(target_node_id)
    _require(subject_id and target_id and subject_id != target_id, "combine_needs_two_rows",
             "a combine names two different rows")
    seen = projection if projection is not None else _projection(vault_root)
    nodes = _drawn_nodes(seen)
    for node_id in (subject_id, target_id):
        _require(node_id in nodes and nodes[node_id].get("node_kind") != "period",
                 "combine_node_not_drawn", f"{node_id} is not a drawn moment")
    subject, target = nodes[subject_id], nodes[target_id]
    mine, mine_episode = node_tellings(vault_root, seen, subject_id)
    theirs, their_episode = node_tellings(vault_root, seen, target_id)
    _require(mine, "combine_no_telling_of_its_own",
             f"{_label(subject)} has no telling of its own to combine")
    _require(theirs, "combine_no_telling_of_its_own",
             f"{_label(target)} has no telling of its own to combine")
    _require(not (mine_episode and mine_episode == their_episode), "combine_already_one_moment",
             f"{_label(subject)} and {_label(target)} are already one moment")
    everyone = list(dict.fromkeys(mine + theirs))
    before = {t: iq._active_same_episode(vault_root, t) for t in everyone}  # noqa: SLF001
    # Idempotent on the pair while it stands; a new statement after an undo.
    pair = sorted((subject_id, target_id))
    standing = [row for row in _active(vault_root, COMBINE_TYPE, COMBINE_UNDO_TYPE)
                if sorted((row.get("subject_node_id"), row.get("target_node_id"))) == pair]
    if standing:
        statement = {"statement_id": standing[-1]["statement_id"],
                     "relative_path": standing[-1]["relative_path"], "created": False}
        before = standing[-1].get("before") or before
    else:
        earlier = [row for row in _statements(vault_root, COMBINE_TYPE)
                   if sorted((row.get("subject_node_id"), row.get("target_node_id"))) == pair]
        sentence = f"{_label(subject)} and {_label(target)} are the same moment"
        statement = _file_statement(
            vault_root, kind=COMBINE_TYPE,
            identity={"pair": pair, "nth": len(earlier)},
            fields={"rule": "A_ROW_DROPPED_ON_A_ROW_IS_THE_SAME_MOMENT",
                    "subject_node_id": subject_id, "target_node_id": target_id,
                    "subject_label": _label(subject), "target_label": _label(target),
                    "subject_tellings": mine, "target_tellings": theirs, "before": before},
            sentence=sentence, reason=reason, author=author, now=now)
    source_ref = statement["relative_path"]
    first = iq.resolve_same_event_answer(
        vault_root, telling_ref=mine[0], answer="same",
        candidate_episode_id=their_episode,
        candidate_telling_ref=None if their_episode else theirs[0],
        telling_quote=_label(subject), episode_quote=_label(target),
        source_ref=source_ref, now=now,
    )
    episode = iq._active_same_episode(vault_root, mine[0])  # noqa: SLF001
    if episode is None:
        # The pair was combined once and undone: the human `create` over the
        # same two tellings already exists, and its bindings were split off.
        # Binding back INTO that episode supersedes each split departure.
        episode = collapsed_text(first.get("episode_id"))
        _require(episode, "combine_found_no_episode", "the same_event confirm named no episode")
    for telling in everyone:
        if iq._active_same_episode(vault_root, telling) != episode:  # noqa: SLF001
            iq._bind_into_episode(vault_root, telling_ref=telling, episode_id=episode,  # noqa: SLF001
                                  evidence={"telling_quote": _label(subject),
                                            "episode_quote": _label(target)},
                                  source_ref=source_ref, now=now)
    return {"combine_id": statement["statement_id"], "source": source_ref,
            "created": statement["created"], "episode_id": episode,
            "subject_node_id": subject_id, "target_node_id": target_id,
            "subject_label": _label(subject), "target_label": _label(target),
            "tellings": everyone, "before": before,
            "rule": "A_ROW_DROPPED_ON_A_ROW_IS_THE_SAME_MOMENT"}


def _statement(vault_root: str | Path, kind: str, statement_id: str) -> dict | None:
    return next((row for row in _statements(vault_root, kind)
                 if collapsed_text(row.get("statement_id")) == statement_id), None)


def undo_combine(vault_root: str | Path, combine_id: str, *, reason: str = "",
                 author: str | None = None, now: object = None) -> dict:
    """Split the tellings a combine joined back off its episode
    (`identity_questions.split_episode`). Files, does not publish.

    Each telling that joined goes back where it was: standalone when it stood
    alone, and a side that was already an episode of its own — a merge's
    absorbed episode — leaves together, into a new episode of its own."""
    import event_identity as ei  # noqa: PLC0415
    import identity_questions as iq  # noqa: PLC0415

    text = collapsed_text(combine_id)
    _require(_ID_RE["combine"].fullmatch(text), "combine_id_malformed", f"not a combine id: {combine_id!r}")
    row = _statement(vault_root, COMBINE_TYPE, text)
    _require(row is not None, "combine_unknown", f"no combine {text}")
    if text in _undone_ids(vault_root, COMBINE_UNDO_TYPE):
        return {"combine_id": text, "undone": False, "why": "already undone"}
    before = {collapsed_text(k): (collapsed_text(v) or None) for k, v in (row.get("before") or {}).items()}
    tellings = list(before)
    current = {t: iq._active_same_episode(vault_root, t) for t in tellings}  # noqa: SLF001
    episode = current.get(collapsed_text((row.get("subject_tellings") or [""])[0]))
    destinations: dict[str, str] = {}
    groups: dict[str, list[str]] = {}
    if episode:
        for telling, was in before.items():
            if current.get(telling) != episode or was == episode:
                continue
            if was is None:
                destinations[telling] = STANDALONE
            else:
                groups.setdefault(was, []).append(telling)
        for was, members in sorted(groups.items()):
            fresh = ei.episode_id_for(ei.operation_digest(
                authority="human", op="create", rule_version=ei.IDENTITY_RULE_VERSION,
                member_refs=[*members, text], acted_on_episode_ids=[was]))
            for telling in members:
                destinations[telling] = fresh
    undo = _file_statement(
        vault_root, kind=COMBINE_UNDO_TYPE, identity={"undoes": text},
        fields={"undoes": text, "episode_id": episode, "destinations": destinations},
        sentence=f"{row.get('subject_label')} and {row.get('target_label')} are not the same moment after all",
        reason=reason or "Undone on the timeline.", author=author, now=now)
    split = None
    if destinations:
        split = iq.split_episode(vault_root, episode_id=episode, destinations=destinations,
                                 source_ref=undo["relative_path"], now=now)
    return {"combine_id": text, "undone": True, "undo_id": undo["statement_id"],
            "episode_id": episode, "destinations": destinations,
            "split_operation": ((split or {}).get("envelope") or {}).get("operation", {}).get("operation_id")}


# --------------------------------------------------------------------------
# Fold into a landmark, as his statement
# --------------------------------------------------------------------------

def _landmark(projection: dict, entry_id: str) -> tuple[str, dict] | None:
    for domain in ((projection.get("landmarks_view") or {}).get("domains") or ()):
        for landmark in domain.get("landmarks") or ():
            if collapsed_text(landmark.get("entry_id")) == entry_id:
                return collapsed_text(domain.get("domain")), landmark
    return None


def fold_into_landmark(vault_root: str | Path, *, node_id: str, entry_id: str, stay_index: int = 0,
                       reason: str = "", author: str | None = None, now: object = None,
                       projection: dict | None = None) -> dict:
    """:data:`A_ROW_DROPPED_ON_A_LANDMARK_FOLDS_INTO_IT`. Files, does not
    publish; the next publish folds it (`landmark_fold.apply_folds`,
    ``stated``)."""
    seen = projection if projection is not None else _projection(vault_root)
    nodes = _drawn_nodes(seen)
    node = nodes.get(collapsed_text(node_id))
    _require(node is not None and node.get("node_kind") != "period", "fold_node_not_drawn",
             f"{node_id} is not a drawn moment")
    found = _landmark(seen, collapsed_text(entry_id))
    _require(found is not None, "fold_landmark_unknown", f"no landmark {entry_id}")
    domain, landmark = found
    stays = {int(s.get("stay_index") or 0) for s in landmark.get("stays") or ()}
    _require(int(stay_index) in stays, "fold_stay_unknown", f"{entry_id} has no stay {stay_index}")
    name = collapsed_text(landmark.get("nickname")) or collapsed_text(landmark.get("label"))
    key = {"node_id": collapsed_text(node_id), "entry_id": collapsed_text(entry_id),
           "stay_index": int(stay_index)}
    standing = [row for row in _active(vault_root, FOLD_TYPE, FOLD_UNDO_TYPE)
                if {k: row.get(k) for k in key} == key]
    if standing:
        return {"fold_id": standing[-1]["statement_id"], "source": standing[-1]["relative_path"],
                "created": False, **key, "landmark_label": name}
    earlier = [row for row in _statements(vault_root, FOLD_TYPE) if {k: row.get(k) for k in key} == key]
    statement = _file_statement(
        vault_root, kind=FOLD_TYPE, identity={**key, "nth": len(earlier)},
        fields={"rule": "A_ROW_DROPPED_ON_A_LANDMARK_FOLDS_INTO_IT", **key, "domain": domain,
                "label": _label(node), "landmark_label": name,
                "tellings": [collapsed_text(t) for t in node.get("tellings") or ()]},
        sentence=f"{_label(node)} is part of {name}", reason=reason, author=author, now=now)
    return {"fold_id": statement["statement_id"], "source": statement["relative_path"],
            "created": statement["created"], **key, "landmark_label": name}


def undo_fold(vault_root: str | Path, fold_id: str, *, reason: str = "",
              author: str | None = None, now: object = None) -> dict:
    text = collapsed_text(fold_id)
    _require(_ID_RE["fold"].fullmatch(text), "fold_id_malformed", f"not a fold id: {fold_id!r}")
    row = _statement(vault_root, FOLD_TYPE, text)
    _require(row is not None, "fold_unknown", f"no fold {text}")
    if text in _undone_ids(vault_root, FOLD_UNDO_TYPE):
        return {"fold_id": text, "undone": False, "why": "already undone"}
    undo = _file_statement(
        vault_root, kind=FOLD_UNDO_TYPE, identity={"undoes": text}, fields={"undoes": text},
        sentence=f"{row.get('label')} is not part of {row.get('landmark_label')} after all",
        reason=reason or "Undone on the timeline.", author=author, now=now)
    return {"fold_id": text, "undone": True, "undo_id": undo["statement_id"]}


def stated_folds(vault_root: str | Path) -> list[dict]:
    """Every standing owner-stated fold, for the publisher — ``{fold_id,
    node_id, entry_id, stay_index, tellings}``. ``[]`` for a vault with none."""
    try:
        rows = _active(vault_root, FOLD_TYPE, FOLD_UNDO_TYPE)
    except (OSError, TemporalContractError):
        return []
    return [{"fold_id": collapsed_text(row.get("statement_id")),
             "node_id": collapsed_text(row.get("node_id")),
             "entry_id": collapsed_text(row.get("entry_id")),
             "stay_index": int(row.get("stay_index") or 0),
             "tellings": [collapsed_text(t) for t in row.get("tellings") or ()]}
            for row in rows]


__all__ = [
    "A_ROW_DROPPED_ON_A_LANDMARK_FOLDS_INTO_IT", "A_ROW_DROPPED_ON_A_ROW_IS_THE_SAME_MOMENT",
    "COMBINE_RULE_VERSION", "CombineError", "combine", "fold_into_landmark", "node_tellings",
    "stated_folds", "undo_combine", "undo_fold",
]
