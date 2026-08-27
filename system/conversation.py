#!/usr/bin/env python3
"""Lifehug — Conversation session store + pure prompt/context builders.

Infrastructure for the Conversation Interaction (issue #115, Wave 1 PR 2 of
2). This module is the "build" half only, in the same shape as
``answer_ack.py``: pure functions that read the vault and the
``interactions/conversation/`` definition (issue #114) and either persist a
durable session document or print a prompt. It never calls a model and never
sends a message — Wave 2 wires the engine on top of this store.

Session documents live one-per-file at ``state/conversations/<id>.json``
(``session_version: 1``; see the PR contract, Deliverable 2, for the exact
schema). ``session_id`` format: ``conv-YYYYMMDD-HHMMSS-<6 hex>`` (UTC) so
filenames sort chronologically.

Session store CRUD (each takes an optional ``vault_root`` override so tests
can point at a synthetic temp vault without rebinding the process):

    open_session(mode, channel, *, arc=None, vault_root=None) -> dict
    load_session(session_id, *, vault_root=None) -> dict
    list_sessions(*, status=None, vault_root=None) -> list[dict]
    append_turn(session_id, turn, *, expected_turns, vault_root=None) -> dict
    close_session(session_id, close, *, vault_root=None) -> dict

``append_turn`` is a compare-and-set: it re-reads the document, and if the
current turn count does not equal ``expected_turns`` it raises
``TurnConflictError`` instead of writing — the same idiom the platform uses
for follow-up-id minting, adapted to a full re-read/compare/atomic-replace
since this store has no in-process lock. A closed session raises
``SessionClosedError`` on any further append.

Manifest + assembly:

    load_interaction_manifest(*, framework_root=None) -> dict
    assemble_context(session, *, vault_root=None, blocks=None) -> str

Prompt builders (each pure; each has a stdin-JSON CLI path exactly like
``answer_ack.py`` — see ``main()`` below):

    build_turn_prompt(payload) -> str
    build_router_prompt(payload) -> str
    build_arc_prompt(payload) -> str
    build_closing_prompt(payload) -> str

Arc-card helpers (minimal, typed; storage only — the planner is Wave 2):

    load_arc_card(question_id, *, vault_root=None) -> dict | None
    save_arc_card(card, *, vault_root=None) -> None
    load_arc_cards(*, vault_root=None) -> dict          # the whole container
    save_arc_cards(container, *, vault_root=None) -> None

(The two container-level helpers and ``read_conversation_definition`` are
the issue #118 extension: ``system/arc_planner.py`` rewrites the container
wholesale every week and reads ``plan/arc-templates.md``, and both go
through this module rather than re-deriving the container defaults or
hand-building a path into the interaction definition.)

There is deliberately no ``append_mirror_response`` here (mid-flight
cross-contract audit amendment M14): issue #119 ships the single mirror
writer (``mirror.append_mirror_responses``); this PR only registers the
``mirror_responses`` vault-contract data path.

The ``state/arc_cards.json`` shape here is intentionally minimal (mid-flight
audit amendment M1): this PR pins only the ``load_arc_card``/``save_arc_card``
signatures and the top-level container fields; the arc-planning authority
(#118 / platform PR #124) owns the generation-run bookkeeping
(``generated_at``, ``queue_generated_at``, ``expires_at``, ``source``,
``thread_offers``) and the card-intent object shape.

Every vault read/write goes through ``vault_paths`` (never a hand-built
path); every framework read (the ``interactions/`` definition) goes through
``lifehug_core.INTERACTIONS_DIR`` / ``framework_path``.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

from lifehug_core import (
    INTERACTIONS_DIR,
    REPO_DIR,
    SYSTEM_DIR,
    _parse_simple_yaml,
    now_utc,
    split_frontmatter,
)
from vault_paths import atomic_write_vault_text, read_vault_text, vault_data_path

SESSION_VERSION = 1
VALID_MODES = frozenset({"chat", "conversation"})
VALID_CHANNELS = frozenset({"telegram", "web", "cli"})
VALID_CLOSE_REASONS = frozenset({"done", "idle_timeout", "exit_taken", "day_rollover"})
VALID_ROLES = frozenset({"user", "lifehug"})
SESSION_ID_RE = re.compile(r"^conv-\d{8}-\d{6}-[0-9a-f]{6}$")

# The manifest's load_order for the STABLE + PER-USER + PER-SESSION blocks
# assemble_context itself builds. `turn_instructions` is the 7th and final
# load_order element, appended separately by build_turn_prompt (it needs
# per-turn runtime state assemble_context doesn't take) — a doc-drift guard
# test asserts (*ASSEMBLE_CONTEXT_BLOCK_ORDER, "turn_instructions") equals
# interaction.yaml's load_order exactly.
ASSEMBLE_CONTEXT_BLOCK_ORDER = (
    "identity",
    "behavior",
    "examples",
    "profile",
    "record",
    "asking_supply",
    "session",
)

CHARS_PER_TOKEN = 4  # contract-pinned approximation for budget truncation

#: Default `budget.closing_transcript` (tokens) when interaction.yaml's own
#: knob is absent or the manifest fails to load — sized like the turn
#: prompt's own transcript allowance (`budget.session`, ADR 0015).
DEFAULT_CLOSING_TRANSCRIPT_BUDGET = 1200

#: Default `budget.session` (tokens) when the manifest is absent or the
#: knob isn't an int — the turn prompt's own transcript allowance.
DEFAULT_SESSION_BUDGET = 1200

#: Default `knob.asking_supply_top_k` (ADR 0016) when the manifest is
#: absent or the knob isn't an int.
DEFAULT_ASKING_SUPPLY_TOP_K = 3

#: Default `knob.router_roster_max` (issue #169, ADR 0017 — the thread
#: binder) when the manifest is absent or the knob isn't a positive int.
DEFAULT_ROUTER_ROSTER_MAX = 6

#: A14 -> A14, A14b -> A14 (the suffix chain's root). Single authority —
#: moved here from conversation_delivery.py (issue #168 / ADR 0016) so the
#: focus-derivation ladder (arc.question_id / turn question_ids ->
#: _chain_root -> qid[0] -> question_planner.build_focus_index()) and the
#: turn engine's session-selection matching both read the SAME function
#: rather than each keeping their own copy of this regex (recurring-defect
#: doctrine); conversation_delivery imports this one.
_CHAIN_ROOT_RE = re.compile(r"^([A-Z]\d+)[a-z]*$")


def _chain_root(question_id: str) -> str:
    match = _CHAIN_ROOT_RE.match(question_id or "")
    return match.group(1) if match else (question_id or "")


class ConversationError(Exception):
    """Base error for conversation-store operations."""


class TurnConflictError(ConversationError):
    """The expected turn count did not match — a concurrent writer won."""


class SessionClosedError(ConversationError):
    """The session is already closed; no further turns may be appended."""


class InvalidCloseError(ConversationError):
    """A close was attempted with a vocabulary or idempotency mismatch."""


class ConversationPromptError(ConversationError):
    """A prompt builder was given a payload it cannot honestly build from.

    ADR 0015 (issue #167): raised by ``build_closing_prompt`` when the
    session carries no user turns AND no non-empty rolling summary — there
    is nothing to close on, and a model asked to appreciate nothing
    confabulates (the #163/2026-08-16 incident pair). Callers degrade per
    the engine's degradation table (``conversation_delivery._deliver_closing``)
    rather than ever emitting a starved prompt.
    """


# --------------------------------------------------------------------------
# Path resolution — every CRUD function accepts an optional vault_root
# override (tests point at a synthetic temp vault); the default resolves to
# the process-bound REPO_DIR via lifehug_core's precomputed constants.
# --------------------------------------------------------------------------


def _resolve_root(vault_root: str | Path | None) -> Path:
    return REPO_DIR if vault_root is None else Path(vault_root)


def _conversations_dir(root: Path) -> Path:
    # Equivalent to lifehug_core.CONVERSATIONS_DIR when root is REPO_DIR (same
    # vault_paths.vault_data_path call under the hood) — computed uniformly
    # here so every CRUD function honors an explicit vault_root override.
    return vault_data_path("conversations", vault_root=root, framework_system_dir=SYSTEM_DIR)


def _arc_cards_path(root: Path) -> Path:
    return vault_data_path("arc_cards", vault_root=root, framework_system_dir=SYSTEM_DIR)


def _answers_dir(root: Path) -> Path:
    return vault_data_path("answers", vault_root=root, framework_system_dir=SYSTEM_DIR)


def _profile_path(root: Path) -> Path:
    return vault_data_path("profile", vault_root=root, framework_system_dir=SYSTEM_DIR)


def _roadmap_path(root: Path) -> Path:
    return vault_data_path("roadmap", vault_root=root, framework_system_dir=SYSTEM_DIR)


def _session_path(session_id: str, *, vault_root: str | Path | None = None) -> Path:
    _validate_session_id(session_id)
    root = _resolve_root(vault_root)
    return _conversations_dir(root) / f"{session_id}.json"


def _validate_session_id(session_id: str) -> None:
    if not isinstance(session_id, str) or not SESSION_ID_RE.fullmatch(session_id):
        raise ValueError(f"invalid session id: {session_id!r}")


def _new_session_id(now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    return f"conv-{moment.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"


def _read_json_at(path: Path, *, vault_root: Path, default: object) -> object:
    try:
        text = read_vault_text(path, vault_root=vault_root)
    except FileNotFoundError:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def _write_json_at(path: Path, data: object, *, vault_root: Path) -> None:
    atomic_write_vault_text(path, json.dumps(data, indent=2) + "\n", vault_root=vault_root)


# --------------------------------------------------------------------------
# Session store CRUD
# --------------------------------------------------------------------------


def open_session(
    mode: str,
    channel: str,
    *,
    arc: dict | None = None,
    vault_root: str | Path | None = None,
    session_id: str | None = None,
    now: str | None = None,
) -> dict:
    """Create and persist a new session document; return it."""
    if mode not in VALID_MODES:
        raise ValueError(f"invalid mode: {mode!r}")
    if channel not in VALID_CHANNELS:
        raise ValueError(f"invalid channel: {channel!r}")
    root = _resolve_root(vault_root)
    sid = session_id or _new_session_id()
    _validate_session_id(sid)
    manifest = _safe_manifest()
    doc = {
        "session_version": SESSION_VERSION,
        "session_id": sid,
        "mode": mode,
        "channel": channel,
        "interaction_version": manifest.get("version", "0.0.0"),
        "status": "open",
        "arc": arc,
        "turns": [],
        "rolling_summary": "",
        "extracted": {
            "facts": [],
            "entities": [],
            "candidate_ideas": [],
            "mirror_responses": [],
        },
    }
    _write_json_at(_conversations_dir(root) / f"{sid}.json", doc, vault_root=root)
    return doc


def load_session(session_id: str, *, vault_root: str | Path | None = None) -> dict:
    """Load one session document by id; raises FileNotFoundError if absent."""
    root = _resolve_root(vault_root)
    path = _session_path(session_id, vault_root=root)
    text = read_vault_text(path, vault_root=root)
    return json.loads(text)


def list_sessions(
    *,
    status: str | None = None,
    vault_root: str | Path | None = None,
) -> list[dict]:
    """Metadata-only summaries; [] on a cold vault (no state/conversations/ yet)."""
    root = _resolve_root(vault_root)
    directory = _conversations_dir(root)
    if not directory.exists():
        return []
    summaries: list[dict] = []
    for path in sorted(directory.glob("conv-*.json")):
        try:
            doc = json.loads(read_vault_text(path, vault_root=root))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        if status is not None and doc.get("status") != status:
            continue
        turns = doc.get("turns") or []
        summaries.append({
            "session_id": doc.get("session_id"),
            "mode": doc.get("mode"),
            "status": doc.get("status"),
            "channel": doc.get("channel"),
            "turn_count": len(turns),
            "opened": turns[0]["ts"] if turns else None,
            "last": turns[-1]["ts"] if turns else None,
        })
    summaries.sort(key=lambda entry: entry["session_id"] or "", reverse=True)
    return summaries


def append_turn(
    session_id: str,
    turn: dict,
    *,
    expected_turns: int,
    vault_root: str | Path | None = None,
    now: str | None = None,
) -> dict:
    """Compare-and-set turn append; typed failure on mismatch or a closed session."""
    root = _resolve_root(vault_root)
    doc = load_session(session_id, vault_root=root)
    if doc.get("status") == "closed":
        raise SessionClosedError(f"session {session_id} is closed")
    turns = doc.get("turns") or []
    if len(turns) != expected_turns:
        raise TurnConflictError(
            f"expected {expected_turns} turns, found {len(turns)} — a concurrent writer won"
        )
    role = turn.get("role")
    if role not in VALID_ROLES:
        raise ValueError(f"invalid turn role: {role!r}")
    text = turn.get("text")
    if not isinstance(text, str) or not text:
        raise ValueError("turn text is required")
    channel = turn.get("channel")
    if channel not in VALID_CHANNELS:
        raise ValueError(f"invalid turn channel: {channel!r}")
    new_turn = {
        "role": role,
        "text": text,
        "ts": turn.get("ts") or now or now_utc(),
        "channel": channel,
    }
    # "source_path" (issue #117): tags a story-turn's user turn with the raw
    # source it came from — the close-time supersede hook reads it back to
    # find which template candidates a session's classifier-grade extraction
    # should flip to "superseded". Optional and additive; existing callers
    # that never pass it are unaffected.
    # "asked_from_supply" (issue #168, ADR 0016): marks a lifehug turn's
    # question_id as a HELD pick from asking_supply, not an ordinary minted
    # follow-up — the decline-detection rule (Scope 4) reads this back to
    # know which turns' offers are even eligible to be "declined".
    # "placed" / "timeline_probe_id" (v196) and "work_item_id" (v234): the
    # timeline lane's additive turn fields. They were written by
    # `conversation_delivery.run_post_answer_turn` and dropped HERE, silently,
    # because this allowlist never learned them — so `precision_so_far` read
    # an empty ladder on every OSS session and the placement a person named
    # left no trace on the turn that carried it. Additive and absent by
    # default, exactly like the four above (pinned by
    # `test_the_lanes_additive_turn_fields_survive_the_append`).
    for optional in ("router", "model", "question_id", "source_path",
                     "asked_from_supply", "placed", "timeline_probe_id",
                     "work_item_id"):
        if turn.get(optional) is not None:
            new_turn[optional] = turn[optional]
    doc["turns"] = [*turns, new_turn]
    _write_json_at(_conversations_dir(root) / f"{session_id}.json", doc, vault_root=root)
    return doc


def close_session(
    session_id: str,
    close: dict,
    *,
    vault_root: str | Path | None = None,
) -> dict:
    """Store close only — no send, no commit (Wave 2). Idempotent on identical payload.

    Mid-flight audit amendment M15: this stays intentionally minimal
    (``close = {"reason": ...}`` plus an optional ``takeaway``) — issue #116
    upgrades ``conversation-close`` in place to add sending and an
    ``--expired`` sweep; this PR's surface does not grow extra flags.
    """
    if close.get("reason") not in VALID_CLOSE_REASONS:
        raise ValueError(f"invalid close reason: {close.get('reason')!r}")
    root = _resolve_root(vault_root)
    doc = load_session(session_id, vault_root=root)
    if doc.get("status") == "closed":
        if doc.get("close") == close:
            return doc
        raise InvalidCloseError(
            f"session {session_id} is already closed with a different close payload"
        )
    doc["status"] = "closed"
    doc["close"] = close
    _write_json_at(_conversations_dir(root) / f"{session_id}.json", doc, vault_root=root)
    return doc


#: The four extraction buckets a turn may contribute to (schema-pinned).
EXTRACTED_BUCKETS = ("facts", "entities", "candidate_ideas", "mirror_responses")


def merge_session_extraction(
    session_id: str,
    *,
    rolling_summary: str | None = None,
    extracted: dict | None = None,
    vault_root: str | Path | None = None,
) -> dict:
    """Merge one turn's extraction deltas into an OPEN session document.

    Wave 1 shipped turn-append and close only; issue #116's engine needs the
    ``extracted``/``rolling_summary`` half of the schema to actually persist,
    because the close step files ``extracted.candidate_ideas`` into the
    candidate store and records ``extracted.entities`` on the close block.
    Keeping that write here (rather than in the engine) preserves the
    contract rule that ``state/conversations/`` is only ever touched through
    this module's CRUD.

    Deltas are appended, de-duplicated conservatively (exact repeats of a
    JSON-serializable item are dropped), and unknown buckets are ignored.
    """
    root = _resolve_root(vault_root)
    doc = load_session(session_id, vault_root=root)
    if doc.get("status") == "closed":
        raise SessionClosedError(f"session {session_id} is closed")
    if rolling_summary is not None:
        if not isinstance(rolling_summary, str):
            raise ValueError("rolling_summary must be a string")
        doc["rolling_summary"] = rolling_summary
    if extracted:
        if not isinstance(extracted, dict):
            raise ValueError("extracted must be an object")
        current = doc.get("extracted")
        if not isinstance(current, dict):
            current = {}
        for bucket in EXTRACTED_BUCKETS:
            existing = current.get(bucket)
            if not isinstance(existing, list):
                existing = []
            additions = extracted.get(bucket)
            if not isinstance(additions, list):
                current[bucket] = existing
                continue
            seen = {json.dumps(item, sort_keys=True) for item in existing}
            for item in additions:
                key = json.dumps(item, sort_keys=True)
                if key in seen:
                    continue
                seen.add(key)
                existing.append(item)
            current[bucket] = existing
        doc["extracted"] = current
    _write_json_at(_conversations_dir(root) / f"{session_id}.json", doc, vault_root=root)
    return doc


def record_declined_questions(
    session_id: str,
    question_ids: list[str],
    *,
    vault_root: str | Path | None = None,
) -> dict:
    """Additively record held-question ids this session has declined.

    Issue #168 / ADR 0016, Scope 4 (session-scoped decline memory): a held
    question offered from ``asking_supply`` and declined (the next user
    turn doesn't engage it — ``conversation_delivery``'s deterministic
    detection rule) is excluded from that block for the rest of this
    session — rule 4's "never re-offer" made structural. De-duplicated,
    order-preserving; a no-op on a closed session (nothing left to protect)
    or an empty ``question_ids``. Plain read-modify-write, same posture as
    ``merge_session_extraction`` above — this field is additive-only and a
    concurrent double-write is at worst a harmless duplicate-suppressed
    append, never a data loss.
    """
    if not question_ids:
        return load_session(session_id, vault_root=vault_root)
    root = _resolve_root(vault_root)
    doc = load_session(session_id, vault_root=root)
    if doc.get("status") == "closed":
        return doc
    existing = doc.get("declined_question_ids")
    current = list(existing) if isinstance(existing, list) else []
    changed = False
    for qid in question_ids:
        text = str(qid) if qid else ""
        if text and text not in current:
            current.append(text)
            changed = True
    if changed:
        doc["declined_question_ids"] = current
        _write_json_at(_conversations_dir(root) / f"{session_id}.json", doc, vault_root=root)
    return doc


# --------------------------------------------------------------------------
# Arc-card helpers (storage only)
#
# Mid-flight audit amendment M1: state/arc_cards.json is NOT dict-keyed by
# question_id with per-card expiry/mode (this PR's original contract shape).
# The container is a single weekly-generation-run record the arc authority
# (#118 / platform PR #124) owns: {version, generated_at, queue_generated_at,
# expires_at, source, cards: [...], thread_offers: [...]}. This PR pins only
# the load_arc_card/save_arc_card SIGNATURES and the container defaults —
# cards is a plain list of typed card objects (each expected to carry a
# "question_id" key so load/save can find it), never interpreted further
# here.
# --------------------------------------------------------------------------

ARC_CARDS_VERSION = 1


def _arc_cards_default() -> dict:
    # A fresh dict/list on every call — never a shared module-level mutable
    # (a `dict(SHARED_CONSTANT)` shallow copy would alias the "cards" list
    # across every vault this process touches; the bug this factory avoids
    # was caught by this PR's own upsert-without-duplicating test).
    return {
        "version": ARC_CARDS_VERSION,
        "generated_at": None,
        "queue_generated_at": None,
        "expires_at": None,
        "source": None,
        "cards": [],
        "thread_offers": [],
    }


def load_arc_cards(*, vault_root: str | Path | None = None) -> dict:
    """The whole arc-card CONTAINER, defaults filled (issue #118 extension).

    ``load_arc_card`` answers "one card for this question"; the arc planner
    rewrites the container wholesale each week (generation-run bookkeeping
    included), so both halves resolve the container through this one
    function rather than each re-deriving the defaults. A cold vault, a
    corrupt file, or a non-object payload all degrade to the default
    container — never an exception on a read path the daily loop touches.
    """
    root = _resolve_root(vault_root)
    data = _read_json_at(_arc_cards_path(root), vault_root=root, default=None)
    if not isinstance(data, dict):
        return _arc_cards_default()
    for key, default in _arc_cards_default().items():
        data.setdefault(key, default)
    if not isinstance(data.get("cards"), list):
        data["cards"] = []
    if not isinstance(data.get("thread_offers"), list):
        data["thread_offers"] = []
    return data


def save_arc_cards(data: dict, *, vault_root: str | Path | None = None) -> None:
    """Write the whole container (issue #118 extension; defaults filled)."""
    if not isinstance(data, dict):
        raise ValueError("arc-card container must be a JSON object")
    payload = dict(data)
    for key, default in _arc_cards_default().items():
        payload.setdefault(key, default)
    root = _resolve_root(vault_root)
    _write_json_at(_arc_cards_path(root), payload, vault_root=root)


def load_arc_card(question_id: str, *, vault_root: str | Path | None = None) -> dict | None:
    root = _resolve_root(vault_root)
    data = _read_json_at(_arc_cards_path(root), vault_root=root, default=None)
    if not isinstance(data, dict):
        return None
    cards = data.get("cards")
    if not isinstance(cards, list):
        return None
    for card in cards:
        if isinstance(card, dict) and card.get("question_id") == question_id:
            return card
    return None


def save_arc_card(card: dict, *, vault_root: str | Path | None = None) -> None:
    """Upsert one card into the cards list, matched by question_id."""
    question_id = card.get("question_id")
    if not question_id:
        raise ValueError("arc card requires a question_id")
    root = _resolve_root(vault_root)
    data = load_arc_cards(vault_root=root)
    cards = data["cards"]
    for index, existing in enumerate(cards):
        if isinstance(existing, dict) and existing.get("question_id") == question_id:
            cards[index] = card
            break
    else:
        cards.append(card)
    save_arc_cards(data, vault_root=root)


# --------------------------------------------------------------------------
# Manifest + assembly
# --------------------------------------------------------------------------


def _conversation_dir_path(*parts: str, framework_root: str | Path | None = None) -> Path:
    base = Path(framework_root) / "interactions" / "conversation" if framework_root is not None \
        else INTERACTIONS_DIR / "conversation"
    return base.joinpath(*parts)


def load_interaction_manifest(*, framework_root: str | Path | None = None) -> dict:
    """Parse interaction.yaml's flat scalar subset; cast knob.*/budget.* numerics."""
    path = _conversation_dir_path("interaction.yaml", framework_root=framework_root)
    raw = _parse_simple_yaml(path, validate_ai_routing=False)
    manifest: dict[str, object] = {}
    for key, value in raw.items():
        if key.startswith("knob.") or key.startswith("budget."):
            manifest[key] = _cast_numeric(value)
        else:
            manifest[key] = value
    return manifest


def _cast_numeric(value: str) -> object:
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _safe_manifest() -> dict:
    """Degrade to {} rather than raise — the framework tree may be absent.

    The manifest is FRAMEWORK-scoped (interactions/), never vault-scoped —
    unlike the CRUD helpers above it takes no vault_root.
    """
    try:
        return load_interaction_manifest()
    except (OSError, ValueError):
        return {}


def read_conversation_definition(*parts: str, framework_root: str | Path | None = None) -> str:
    """Read one ``interactions/conversation/`` definition file verbatim.

    The public accessor (issue #118 extension) so other modules — the arc
    planner reads ``plan/arc-templates.md`` — never hand-build a path into
    the interaction definition. Raises OSError when the file is absent; the
    definition tree is a framework file, not optional vault state.
    """
    return _conversation_dir_path(*parts, framework_root=framework_root).read_text(encoding="utf-8")


def _read_framework_text(*parts: str) -> str:
    return read_conversation_definition(*parts)


#: The marker appended to any block this module had to shorten, and the
#: marker that stands in for whole turns dropped out of a transcript
#: (v201, lifehug#206). It exists because a BARE cut is indistinguishable
#: from a person who stopped mid-sentence: the incident that produced this
#: constant was a model that read a budget cut as an interrupted speaker
#: and spent three consecutive turns asking the person to finish a sentence
#: they had already finished. A marker the prompt explains is elision is
#: the difference between "there is more I cannot see" and "you trailed
#: off".
ELISION_MARKER = "[…]"

#: The transcript-level form, on its own line — whole turns were dropped,
#: not characters shaved.
TRANSCRIPT_ELISION_LINE = "[… earlier turns in this conversation elided for length …]"

#: How many characters of slack `_elide` will walk backward looking for a
#: clean boundary before it gives up and accepts a word break. Bounded so a
#: block with no whitespace at all still gets shortened.
_ELISION_LOOKBACK = 400


def _elide(text: str, budget_tokens: object) -> str:
    """Shorten ``text`` to its budget WITHOUT ever cutting mid-word.

    v201 (lifehug#206). The previous implementation was ``text[:limit]`` — a
    bare character cut that routinely landed inside a word, and, on the
    SESSION block, inside the person's own most recent sentence. A model
    reading that cannot tell a budget from a speaker who trailed off.

    So: walk back to the nearest paragraph break, then sentence end, then
    word break, and append `ELISION_MARKER` so the reader is TOLD the block
    was shortened. Never a bare cut, never mid-word.
    """
    if not isinstance(budget_tokens, int):
        return text
    limit = budget_tokens * CHARS_PER_TOKEN
    if len(text) <= limit:
        return text
    room = max(limit - len(ELISION_MARKER) - 1, 0)
    head = text[:room]
    floor = max(len(head) - _ELISION_LOOKBACK, 0)
    for boundary in ("\n\n", ". ", ".\n", "? ", "! ", "\n", " "):
        cut = head.rfind(boundary, floor)
        if cut > 0:
            head = head[: cut + (len(boundary) if boundary.strip() else 0)]
            break
    return f"{head.rstrip()} {ELISION_MARKER}"


def _truncate(text: str, budget_tokens: object) -> str:
    """Back-compat alias for `_elide` — kept because callers and tests
    outside this module reference the older name."""
    return _elide(text, budget_tokens)


def _assemble_profile_block(root: Path) -> str:
    lines: list[str] = []
    try:
        lines.append(read_vault_text(_profile_path(root), vault_root=root).strip())
    except FileNotFoundError:
        pass
    try:
        roadmap = json.loads(read_vault_text(_roadmap_path(root), vault_root=root))
    except (FileNotFoundError, json.JSONDecodeError):
        roadmap = None
    if isinstance(roadmap, dict):
        focuses = roadmap.get("focuses")
        if isinstance(focuses, list) and focuses:
            names = [str(item.get("name", item)) if isinstance(item, dict) else str(item)
                     for item in focuses]
            lines.append("Active focuses: " + ", ".join(names))
    return "\n".join(line for line in lines if line)


def _assemble_record_block(session: dict, root: Path) -> str:
    arc = session.get("arc") or {}
    question_id = arc.get("question_id")
    if not question_id:
        return ""
    answer_path = _answers_dir(root) / f"{question_id}.md"
    try:
        content = read_vault_text(answer_path, vault_root=root)
    except FileNotFoundError:
        return ""
    metadata, body = split_frontmatter(content)
    answered_date = metadata.get("answered_date", "unknown")
    return f"[{question_id}, {answered_date}] {body.strip()}"


# --------------------------------------------------------------------------
# The asking_supply block (issue #168, ADR 0016) — conversations see and ask
# the session focus's held bank questions. Producer is
# `_assemble_asking_supply_block`; `asking_supply_selection` /
# `asking_supply_question_ids` are the public seam `conversation_delivery`'s
# invitation-hatch gate reuses so the "which qids are actually in the block"
# answer is never re-derived (recurring-defect doctrine) — one selection,
# read by both the renderer and the gate.
# --------------------------------------------------------------------------


def _declined_question_ids(session: dict) -> frozenset[str]:
    ids = session.get("declined_question_ids")
    if not isinstance(ids, list):
        return frozenset()
    return frozenset(str(i) for i in ids if i)


def _session_focus_question_id(session: dict) -> str | None:
    """arc.question_id first, else any turn's question_id (contract's
    focus-derivation ladder, step 1) — a story session's turns carry
    ``source_path``, never ``question_id``, so this returns None for them
    and the ladder resolves nothing, honestly (Binding facts)."""
    arc = session.get("arc") or {}
    if isinstance(arc, dict) and arc.get("question_id"):
        return str(arc["question_id"])
    for turn in session.get("turns") or []:
        qid = turn.get("question_id")
        if qid:
            return str(qid)
    return None


def _resolve_session_focus_and_candidates(session: dict) -> tuple[dict | None, list[dict]]:
    """The focus-derivation ladder + gate-ranked candidate rows.

    Ladder: arc.question_id / turn question_ids -> ``_chain_root`` ->
    ``qid[0]`` (the category letter) -> ``question_planner.build_focus_index``'s
    ``cat_to_focus`` -> the roadmap focus object. Any failure at any rung
    (no question id, no category match, question_planner unavailable)
    degrades to ``(None, [])`` — an honestly empty supply, never a
    fabricated focus (Binding facts: "Story sessions may resolve nothing").

    Candidate rows come from ``question_planner.enriched_pending_questions``
    — REUSED, never re-derived (recurring-defect doctrine): its own
    rumination-cooldown and escalation-gate weight multipliers govern
    ranking here exactly as they do the weekly queue. Declined-in-session
    ids (rule 4, made structural) are excluded before ranking. Sorted
    richest-weight-first; the caller trims to ``knob.asking_supply_top_k``.
    """
    question_id = _session_focus_question_id(session)
    if not question_id:
        return None, []
    category = _chain_root(question_id)[:1]
    if not category:
        return None, []
    try:
        import question_planner  # noqa: PLC0415

        questions, categories, coverage = question_planner.load_question_state()
        roadmap = question_planner.resolve_roadmap(questions)
        focuses = roadmap.get("focuses") or []
        findex = question_planner.build_focus_index(focuses, questions)
        focus_id = findex["cat_to_focus"].get(category)
        if not focus_id:
            return None, []
        focus = findex["info"].get(focus_id, {}).get("focus")
        if not isinstance(focus, dict):
            return None, []
        focus_categories = {str(c) for c in (focus.get("categories") or [])}
        if not focus_categories:
            return focus, []
        declined = _declined_question_ids(session)
        rows = question_planner.enriched_pending_questions(questions, categories, coverage, [], findex)
        candidates = [
            row for row in rows
            if str(row.get("category")) in focus_categories and str(row.get("id")) not in declined
        ]
        candidates.sort(key=lambda r: (-float(r.get("weight") or 0.0), str(r.get("id"))))
        return focus, candidates
    except Exception:  # noqa: BLE001 — an honestly empty block beats a crash
        return None, []


def asking_supply_selection(session: dict) -> tuple[dict | None, list[dict]]:
    """(focus_or_None, top-K selected rows) — the exact rows the
    ``asking_supply`` block renders for this session right now. Public seam:
    ``conversation_delivery``'s invitation-hatch gate calls this (via
    ``asking_supply_question_ids`` below) rather than re-deriving the
    selection, so "is this qid actually in the block" is always answered
    from the one true selection."""
    focus, candidates = _resolve_session_focus_and_candidates(session)
    if focus is None:
        return None, []
    manifest = _safe_manifest()
    top_k = manifest.get("knob.asking_supply_top_k")
    top_k = top_k if isinstance(top_k, int) and top_k > 0 else DEFAULT_ASKING_SUPPLY_TOP_K
    return focus, candidates[:top_k]


def asking_supply_question_ids(session: dict) -> frozenset[str]:
    """The qids currently in this session's asking_supply selection."""
    _focus, selected = asking_supply_selection(session)
    return frozenset(str(row["id"]) for row in selected)


def _assemble_asking_supply_block(session: dict, root: Path) -> str:
    focus, selected = asking_supply_selection(session)
    if focus is None or not selected:
        return ""
    try:
        import question_planner  # noqa: PLC0415
        from roadmap import focus_fill  # noqa: PLC0415

        questions, _categories, _coverage = question_planner.load_question_state()
        fill = focus_fill(focus, questions)
    except Exception:  # noqa: BLE001
        return ""
    label = str(focus.get("label") or focus.get("id") or "this focus")
    lines = [f"Focus: {label} — {fill['answered']} of {fill['total']} answered"]
    for row in selected:
        lines.append(f"[{row['id']}] {row['text']}")
    return "\n".join(lines)


#: The closed SEVEN-kind arc-card intent vocabulary (mid-flight audit amendment
#: M10; widened to seven by v200) — arc.intents holds typed objects shaped like
#: {"kind": <one of these>, ...}, never plain strings.
#:
#: v200 adds `place_no_stories` DELIBERATELY, as the schema bump ADR 0002's
#: arc-card amendment requires rather than an additive change. The rationale:
#: v199's landmark set is the first thing that can tell us about a place
#: NOTHING in the vault happened in — "I lived in Costa Mesa" with no moments
#: attached is new information the system could not see before, and the owner's
#: ruling (lifehug/lifehug-platform#590) is that it is a gap the loop should
#: ask about. It has no other way in: it is not a `timeline.UNKNOWN_KINDS`
#: member (it asks WHAT, not WHEN, so the dating ledger must not count it) and
#: it is never minted as a bank question (an open landmark is a resting state,
#: not a debt). An arc-card intent is the only lane that fits, and reusing
#: `timeline_gap` would have made one kind mean two different asks and made
#: `question_judgment.arc_yield` unable to tell them apart.
ARC_INTENT_KINDS = frozenset({
    "scene_slot",
    "neighborhood_sibling",
    "timeline_gap",
    "studio_slot",
    "sit_with",
    "demonstrated_knowledge_summary",
    "place_no_stories",
})


def _intent_label(intent: object) -> str:
    """A short human/model-readable label for one typed arc-card intent."""
    if isinstance(intent, dict):
        return str(intent.get("kind", intent))
    return str(intent)


def timeline_whisper(session: object) -> dict | None:
    """This session's unraised timeline whisper, or None (v196).

    The whisper is the week's arc-card timeline item. It is offered to the
    prompt ONLY while this conversation has not raised the timeline yet —
    "at most one per conversation" is structural here, and
    `timeline_gates.one_per_conversation` is the belt to that braces. Guarded:
    a timeline problem never costs a turn its prompt.
    """
    doc = session if isinstance(session, dict) else {}
    arc = doc.get("arc") if isinstance(doc.get("arc"), dict) else {}
    intents = [i for i in (arc.get("intents") or [])
               if isinstance(i, dict) and str(i.get("kind")) == "timeline_gap"
               and str(i.get("probe") or "").strip()]
    if not intents:
        return None
    try:
        import timeline_interaction  # noqa: PLC0415

        if timeline_interaction.timeline_asks_so_far(doc) >= 1:
            return None
    except Exception:  # noqa: BLE001
        return None
    return intents[0]


def render_timeline_whisper(intent: object) -> str:
    """The whisper's one rendering (`timeline_interaction.render_whisper`)."""
    try:
        import timeline_interaction  # noqa: PLC0415

        return timeline_interaction.render_whisper(intent)
    except Exception:  # noqa: BLE001
        return _intent_label(intent)


def place_no_stories_aside(session: object) -> dict | None:
    """This session's place-with-no-stories aside, or None (v200).

    The whisper's sibling, and deliberately simpler. A whisper has a raised/
    unraised state because the timeline may be asked at most once per
    conversation and a probe can be answered mid-session; a place aside has NO
    counter to consult, because it leaves no side state behind at all — the
    once-per-card cap is structural, applied by `arc_planner` when it plans the
    card (at most one, ranked after `timeline_gap`, counted within the same
    `DEFAULT_GAP_MAX`).

    Like the whisper, an intent qualifies only when it carries a real probe, so
    a bare ``{"kind": "place_no_stories"}`` renders exactly like every other
    kind and nothing that reads a pre-v200 card changes shape.
    """
    doc = session if isinstance(session, dict) else {}
    arc = doc.get("arc") if isinstance(doc.get("arc"), dict) else {}
    for intent in arc.get("intents") or []:
        if not isinstance(intent, dict) or str(intent.get("kind")) != "place_no_stories":
            continue
        probe = intent.get("probe")
        text = probe.get("text") if isinstance(probe, dict) else probe
        if str(text or "").strip():
            return intent
    return None


def render_place_no_stories_aside(intent: object) -> str:
    """The aside's one rendering
    (`landmarks_interaction.render_place_no_stories`)."""
    try:
        import landmarks_interaction  # noqa: PLC0415

        return landmarks_interaction.render_place_no_stories(intent)
    except Exception:  # noqa: BLE001
        return _intent_label(intent)


def _session_transcript_lines(turns: list, char_budget: int) -> list[str]:
    """The transcript lines for the turn prompt, budgeted BY TURN.

    v201 (lifehug#206) — the same doctrine ADR 0015 already applied to the
    CLOSING prompt (`_closing_transcript_lines`), finally applied to the
    turn prompt, which is where every ordinary reply is actually written:

    * the FINAL turn is verbatim and unbudgeted — it is the reason a reply
      is owed, and a person's own last sentence is the single worst thing
      in the whole prompt to cut in half;
    * older turns yield OLDEST-FIRST and WHOLE — a turn is either in the
      transcript or it is not, never half of one;
    * when anything was dropped, `TRANSCRIPT_ELISION_LINE` says so, so the
      model reads a gap as a gap rather than as an interrupted speaker.

    The bug this replaces: `_assemble_session_block` rendered every turn and
    the caller cut the JOINED STRING at `budget.session`. Because turns are
    append-only, once a session crossed the budget the visible prefix FROZE
    — every later turn, including the person saying "you're repeating",
    landed past the cut and never reached the model at all. The model saw
    the same transcript, ending mid-sentence, on every subsequent turn, and
    loyally answered it again. See tests/test_transcript_budget.py.
    """
    lines = [f"{turn.get('role')}: {turn.get('text')}"
             for turn in turns if isinstance(turn, dict)]
    if not lines:
        return []
    final = lines[-1]
    kept_reversed: list[str] = []
    used = len(final) + 1
    for line in reversed(lines[:-1]):
        length = len(line) + 1
        if used + length > char_budget:
            break
        kept_reversed.append(line)
        used += length
    kept = list(reversed(kept_reversed))
    if len(kept) < len(lines) - 1:
        kept.insert(0, TRANSCRIPT_ELISION_LINE)
    return [*kept, final]


def _assemble_session_block(session: dict, *, char_budget: int | None = None) -> str:
    """The SESSION block. ``char_budget`` (v201, lifehug#206) budgets the
    transcript BY TURN; ``None`` renders every turn (the shape every
    non-prompt reader — tests, whisper/aside checks — already relies on)."""
    parts: list[str] = []
    arc = session.get("arc")
    if arc:
        opening = arc.get("opening", "")
        intents = arc.get("intents") or []
        labels = ", ".join(_intent_label(intent) for intent in intents)
        parts.append(f"Arc card: {opening} (intents: {labels})")
        # v196 (whispers): the timeline item is the one intent that carries a
        # real question, so it is the one intent rendered in full — the probe
        # and the person's own landmarks. Every other kind renders exactly as
        # it did before, byte for byte (test_intent_labels_are_byte_identical).
        whisper = timeline_whisper(session)
        if whisper is not None:
            parts.append(f"Timeline whisper: {render_timeline_whisper(whisper)}")
        # v200: the second intent that carries a real ask. Same treatment, same
        # gate (a probe must be present), and it never displaces the whisper —
        # the planner already guarantees a card carries at most one of the two.
        aside = place_no_stories_aside(session)
        if aside is not None:
            parts.append(f"Place with no stories: {render_place_no_stories_aside(aside)}")
    summary = session.get("rolling_summary")
    if summary:
        parts.append(f"Rolling summary: {summary}")
    turns = session.get("turns") or []
    if char_budget is None:
        parts.extend(f"{turn.get('role')}: {turn.get('text')}" for turn in turns)
    else:
        header = "\n".join(parts)
        remaining = char_budget - (len(header) + 1 if header else 0)
        parts.extend(_session_transcript_lines(turns, remaining))
    return "\n".join(parts)


def assemble_context(
    session: dict,
    *,
    vault_root: str | Path | None = None,
    blocks: dict[str, str] | None = None,
) -> str:
    """Deterministic identity->behavior->examples->profile->record->asking_supply->session context."""
    root = _resolve_root(vault_root)
    blocks = blocks or {}
    manifest = _safe_manifest()
    content = {
        "identity": _read_framework_text("prompt", "identity.md"),
        "behavior": _read_framework_text("prompt", "behavior.md"),
        "examples": _read_framework_text("prompt", "examples.md"),
        "profile": blocks.get("profile") if "profile" in blocks else _assemble_profile_block(root),
        "record": blocks.get("record") if "record" in blocks else _assemble_record_block(session, root),
        # issue #168 / ADR 0016: the platform seam — the pinned
        # assemble_context accepts "asking_supply" in the blocks override
        # exactly like "profile"/"record" above, so the hosted platform can
        # resolve this block from its own projections rather than the
        # vault-local question_planner producer below.
        "asking_supply": blocks.get("asking_supply") if "asking_supply" in blocks
        else _assemble_asking_supply_block(session, root),
        # v201 (lifehug#206): the SESSION block budgets ITSELF, by turn —
        # never by a character cut across a joined transcript. It is the one
        # block whose content is a person's own words arriving in order, so
        # it is the one block a bare `_elide` must never touch.
        "session": _assemble_session_block(session, char_budget=_session_char_budget(manifest)),
    }
    rendered = []
    for name in ASSEMBLE_CONTEXT_BLOCK_ORDER:
        text = content[name] if name == "session" else _elide(content[name], manifest.get(f"budget.{name}"))
        rendered.append(f"## {name.upper()}\n\n{text}")
    return "\n\n".join(rendered)


def _session_char_budget(manifest: dict) -> int:
    """`budget.session` in characters — the allowance the SESSION block's own
    turn-wise windowing spends (v201, lifehug#206)."""
    budget = manifest.get("budget.session")
    if not isinstance(budget, int):
        budget = DEFAULT_SESSION_BUDGET
    return budget * CHARS_PER_TOKEN


# --------------------------------------------------------------------------
# Prompt builders — each pure; each has a stdin-JSON CLI path (see main()).
# --------------------------------------------------------------------------


def _validate_fields(payload: object, required: dict[str, type]) -> str | None:
    if not isinstance(payload, dict):
        return "payload must be a JSON object"
    for field, expected_type in required.items():
        if field not in payload:
            return f"missing required field: {field}"
        value = payload[field]
        if expected_type is bool:
            if not isinstance(value, bool):
                return f"field {field!r} must be a boolean"
        elif not isinstance(value, expected_type):
            return f"field {field!r} must be a {expected_type.__name__}"
    return None


TURN_PROMPT_REQUIRED_FIELDS = {"session": dict}
ROUTER_PROMPT_REQUIRED_FIELDS = {"message": str, "session_open": bool}
ARC_PROMPT_REQUIRED_FIELDS = {"question": dict, "record_summary": str, "gap_inputs": list}
CLOSING_PROMPT_REQUIRED_FIELDS = {"session": dict}


def _turn_position(session: dict, manifest: dict) -> str:
    """Descriptive `{turn_position}` label for the prompt only — advisory
    text, not a gate (the actual question-allowed decision is
    ``conversation_delivery.decide_turn_shape`` + its output-contract
    appendix, applied after this template). Pure-chat wave (issue #139):
    the distinct "exit-friendly" state is removed — the turn just before
    the exchange budget is reached is an ordinary ``mid-arc`` turn like any
    other; there is no dedicated "make stopping feel good" label or turn.
    """
    turns = session.get("turns") or []
    if not turns:
        return "opening"
    mode = session.get("mode")
    if mode == "chat":
        target = manifest.get("knob.chat_target_exchanges")
        target = target if isinstance(target, int) else 3
        exchanges_done = (len(turns) + 1) // 2  # this turn will start the next exchange
        if exchanges_done >= target:
            return "closing-candidate"
        return "mid-arc"
    cap = manifest.get("knob.conversation_turn_cap_exchanges")
    cap = cap if isinstance(cap, int) else 25
    if len(turns) >= cap * 2:
        return "closing-candidate"
    return "mid-arc"


def _current_intent_label(session: dict, intents: list) -> str:
    """What `{arc_card_current_intent}` says this turn.

    v196: an unraised timeline whisper wins the slot — it is the only intent
    that carries an actual question, and turn-instructions.md's direction for
    it ("only where it fits, once, any precision, never press") is attached
    right here. v200: a place-with-no-stories aside is the second such intent
    and takes the slot when there is no whisper. Without either, this is v195's
    expression, unchanged.
    """
    whisper = timeline_whisper(session)
    if whisper is not None:
        return render_timeline_whisper(whisper)
    # v200: ranked after the whisper, exactly as the planner ranks them.
    aside = place_no_stories_aside(session)
    if aside is not None:
        return render_place_no_stories_aside(aside)
    return _intent_label(intents[0]) if intents else "(no arc card)"


def build_turn_prompt(payload: dict) -> str:
    """Assemble the context + filled turn-instructions.md for this turn."""
    session = payload["session"]
    blocks = payload.get("blocks")
    manifest = _safe_manifest()
    context = assemble_context(session, blocks=blocks)
    turns = session.get("turns") or []
    arc = session.get("arc") or {}
    intents = arc.get("intents") or []
    template = _read_framework_text("prompt", "turn-instructions.md")
    length_cap = _lint_cap_turn_chars()
    position = _turn_position(session, manifest)
    filled = (
        template
        .replace("{mode}", str(session.get("mode", "")))
        .replace("{arc_card_current_intent}", _current_intent_label(session, intents))
        .replace("{turn_position}", position)
        .replace("{previous_turn_summary}", _previous_turn_summary(turns))
        .replace("{applicable_rule_hints}", _rule_hints_for_position(position))
    )
    return (
        f"{context}\n\n## TURN_INSTRUCTIONS\n\n{filled}\n\n"
        f"Hard length cap for this message: {length_cap} characters."
    )


#: `{previous_turn_summary}`'s allowance, in characters. A one-line hint,
#: not a transcript — the SESSION block above carries the real thing.
PREVIOUS_TURN_SUMMARY_CHARS = 200


def _previous_turn_summary(turns: list) -> str:
    """One line describing the turn just before this one.

    v201 (lifehug#206): this used to be `turns[-1]["text"][:200]` — a bare
    character cut of the person's NEWEST message, the second mid-word cut in
    the same prompt. A 215-character message arrived here as 200 characters
    ending inside a word. Now it stops at a boundary and says it stopped.
    """
    if not turns:
        return "(none — this is the opening)"
    text = " ".join(str(turns[-1].get("text") or "").split())
    if not text:
        return "(none — this is the opening)"
    return _elide(text, PREVIOUS_TURN_SUMMARY_CHARS // CHARS_PER_TOKEN)


def _rule_hints_for_position(position: str) -> str:
    """Deterministic behavior.md rule hints per turn position (definition file
    slot {applicable_rule_hints}; the mapping mirrors behavior.md's own
    structure — opening leans on framing/grammar rules, middle on
    respond-before-ask/register, closing on rule 8)."""
    hints = {
        "opening": "2 (respond-before-ask), 3 (question grammar), 5 (register), 7 (escalation)",
        "middle": "1 (one question max), 2 (respond-before-ask), 5 (register), 6 (payout anatomy), 13 (back-off)",
        "closing": "8 (closings: takeaway, appreciation, continuity, hook, stop, declarative — no offer, no meta-framing)",
    }
    return hints.get(position, "1, 2, 5")


def _lint_cap_turn_chars() -> int:
    """The turn length cap — evals/lints.yaml's cap.turn_chars is the single source."""
    try:
        import conversation_lints  # noqa: PLC0415
        config = conversation_lints.load_lints_config()
        cap = config.get("cap.turn_chars")
        if isinstance(cap, int):
            return cap
    except (OSError, ValueError):
        pass
    return 1200


def _build_router_roster_block(threads: list) -> str:
    """Render the optional ROSTER block for build_router_prompt (issue #169,
    ADR 0017 — the thread binder). Returns "" when ``threads`` is empty —
    the caller relies on this to keep the prompt BYTE-IDENTICAL to
    pre-#169 output whenever no roster is given (contract, Scope 1).

    Bounded to ``knob.router_roster_max`` (default
    ``DEFAULT_ROUTER_ROSTER_MAX``) — a top-K whisper, never the whole
    day's thread history, even if a caller hands in more.
    """
    if not threads:
        return ""
    manifest = _safe_manifest()
    roster_max = manifest.get("knob.router_roster_max")
    roster_max = roster_max if isinstance(roster_max, int) and roster_max > 0 else DEFAULT_ROUTER_ROSTER_MAX
    lines = ['ROSTER (candidate threads — "target" must be one of these ids, "new", or null):']
    for candidate in threads[:roster_max]:
        if not isinstance(candidate, dict):
            continue
        cid = candidate.get("id", "")
        question = candidate.get("question", "")
        last_exchange = candidate.get("last_exchange", "")
        awaiting = "true" if candidate.get("awaiting_ask") else "false"
        lines.append(
            f"- id={cid} awaiting_ask={awaiting} question: {question} | last_exchange: {last_exchange}"
        )
    return "\n".join(lines) + "\n\n"


def build_router_prompt(payload: dict) -> str:
    """Substitute message/state into router.md — never restates its schema/intents.

    ``threads`` (issue #169, ADR 0017 — the thread binder, additive) is an
    optional bounded roster of candidate threads
    (``{"id","question","last_exchange","awaiting_ask"}`` each); absent or
    empty, the rendered prompt is BYTE-IDENTICAL to pre-#169 output
    (contract, Scope 1) — the ROSTER block only appears when ``threads``
    is non-empty.
    """
    message = payload["message"]
    session_open = payload["session_open"]
    pending_question_id = payload.get("pending_question_id")
    # "recently_closed" (issue #139, pure-chat wave): no session is open,
    # but one closed on this channel without a new one opening since — the
    # Reply-after-close rule's own signal (router.md). Optional/additive:
    # callers that never pass it get "False", the pre-#139 reading.
    recently_closed = bool(payload.get("recently_closed", False))
    threads = payload.get("threads") or []
    template = _read_framework_text("router", "router.md")
    pending = "(none)" if pending_question_id is None else str(pending_question_id)
    roster_block = _build_router_roster_block(threads)
    return (
        f"{template}\n\n"
        "## INPUT (assembled at runtime — classify this message)\n\n"
        f"SESSION OPEN: {session_open}\n"
        f"PENDING QUESTION: {pending}\n"
        f"RECENTLY CLOSED: {recently_closed}\n\n"
        f"{roster_block}"
        "MESSAGE:\n"
        f"{message}\n"
    )


def build_arc_prompt(payload: dict) -> str:
    """Assemble a planning prompt for one arc card per plan/arc-templates.md."""
    question = payload["question"]
    record_summary = payload["record_summary"]
    gap_inputs = payload["gap_inputs"]
    template = _read_framework_text("plan", "arc-templates.md")
    gaps = "; ".join(str(item) for item in gap_inputs) or "(none)"
    return (
        f"{template}\n\n"
        "## INPUT (assembled at runtime — plan one arc card for this question)\n\n"
        f"QUESTION [{question.get('id', '')}] (category {question.get('category', '')}, "
        f"focus {question.get('focus', '')}):\n{question.get('text', '')}\n\n"
        f"RECORD SUMMARY:\n{record_summary}\n\n"
        f"GAP INPUTS:\n{gaps}\n"
    )


def _final_user_turn_index(turns: list) -> int | None:
    """Index of the LAST turn with role == "user", or None if there is none."""
    for idx in range(len(turns) - 1, -1, -1):
        turn = turns[idx]
        if isinstance(turn, dict) and turn.get("role") == "user":
            return idx
    return None


def _closing_transcript_lines(turns: list, final_index: int, char_budget: int) -> list[str]:
    """Preceding-turn lines (chronological) that fit ``char_budget``.

    ADR 0015: the FINAL user turn is handled separately and is never
    truncated or dropped — this only windows the turns strictly BEFORE it.
    Walks backward from the most recent preceding turn so that, when the
    budget is tight, the OLDEST turns yield first (contract, Scope 1).
    """
    preceding = turns[:final_index]
    kept_reversed: list[str] = []
    used = 0
    for turn in reversed(preceding):
        if not isinstance(turn, dict):
            continue
        line = f"{turn.get('role', '')}: {turn.get('text', '')}"
        length = len(line) + 1  # +1 for the joining newline
        if used + length > char_budget:
            break
        kept_reversed.append(line)
        used += length
    return list(reversed(kept_reversed))


def build_closing_prompt(payload: dict) -> str:
    """Assemble the closing-takeaway prompt per behavior rule 8.

    ADR 0015 (issue #167, content-first close): unlike the pre-#167
    builder, this one actually reads the conversation. It includes the
    FINAL USER TURN verbatim — never truncated away, regardless of length
    or budget, because it is the reason a reply is owed — preceded by
    recent turns within ``budget.closing_transcript`` (oldest dropped
    first when the window is tight), plus ``rolling_summary`` when
    non-empty (older context the window dropped). RAISES
    ``ConversationPromptError`` when the session has no user turns AND no
    non-empty rolling summary — a model with nothing to see never speaks
    (fix B, the starvation guard); the engine
    (``conversation_delivery._deliver_closing``) degrades per its own
    table, never by emitting a starved prompt.

    ADR 0014 (issue #163): the close is STRUCTURED — this checklist
    describes what goes into the ONE woven ``takeaway_prose`` statement;
    the exact ``{takeaway_prose, hook}`` JSON mechanics are appended
    separately by the caller via ``conversation_delivery
    ._closing_output_contract()`` (same split as every other builder here —
    this function states the behavior, the engine appends the wire format).
    """
    session = payload["session"]
    manifest = _safe_manifest()
    turns = session.get("turns") or []
    rolling_summary = str(session.get("rolling_summary") or "").strip()
    final_index = _final_user_turn_index(turns)

    if final_index is None and not rolling_summary:
        raise ConversationPromptError(
            "build_closing_prompt: no user turns and no rolling summary — "
            "nothing to close on"
        )

    deposit_framing = str(manifest.get("knob.deposit_framing", "off")).strip().lower() == "on"
    budget_tokens = manifest.get("budget.closing_transcript")
    if not isinstance(budget_tokens, int):
        budget_tokens = DEFAULT_CLOSING_TRANSCRIPT_BUDGET
    char_budget = budget_tokens * CHARS_PER_TOKEN

    transcript_lines = (
        _closing_transcript_lines(turns, final_index, char_budget)
        if final_index is not None else []
    )

    lines = [
        "=" * 70,
        "LIFEHUG — CLOSING TAKEAWAY",
        "=" * 70,
        "",
        f"Mode: {session.get('mode', '')}",
    ]
    if rolling_summary:
        lines.append(
            f"Rolling summary (earlier context the recent window dropped): "
            f"{rolling_summary}"
        )
    lines.append("")
    if transcript_lines:
        lines.append("Recent conversation (oldest first):")
        lines.extend(transcript_lines)
        lines.append("")
    if final_index is not None:
        final_turn = turns[final_index]
        lines.append(
            "FINAL MESSAGE — the reason a reply is owed here, included in "
            "full regardless of length:"
        )
        lines.append(f"user: {final_turn.get('text', '')}")
        lines.append("")

    lines.append(
        "Respond to the FINAL MESSAGE FIRST — give it the same receipt and "
        "payout an ordinary turn would (rules 2 and 6) — and let that "
        "response settle into the closing takeaway_prose for this session "
        "(behavior rule 8): ONE woven statement, never labeled sections,"
    )
    lines.append("composed of:")
    lines.append("  1. A takeaway growing out of what they just said — NOT a recap.")
    lines.append(
        "  2. Specific appreciation for what they shared (never commentary"
    )
    lines.append("     on how they conversed).")
    lines.append("  3. A continuity line, woven into the prose.")
    if deposit_framing:
        lines.append("  4. An optional deposit-frame (knob.deposit_framing is ON).")
    else:
        lines.append("  4. Deposit-framing is OFF — do not use a deposit frame.")
    lines.append(
        "  5. Weave the hook in naturally when one exists, then STOP — no "
        "trailing question, no labeled \"Hook for next time:\" line."
    )
    lines.append(
        "Then name that same hook again, separately, as a short machine-only "
        "continuity label — it is never shown to the user."
    )
    lines.append(
        "A close that ignores what was just said is a defect — respond to "
        "it, do not summarize past it."
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _read_stdin_json() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        print("Error: empty stdin — expected a JSON payload", file=sys.stderr)
        sys.exit(1)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON on stdin: {exc}", file=sys.stderr)
        sys.exit(1)


def _run_prompt_builder(required: dict[str, type], builder) -> None:
    payload = _read_stdin_json()
    error = _validate_fields(payload, required)
    if error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
    try:
        print(builder(payload))
    except (OSError, ValueError, KeyError, ConversationError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_open(args: argparse.Namespace) -> int:
    arc = None
    if args.question_id:
        card = load_arc_card(args.question_id)
        arc = card if card else {"question_id": args.question_id, "opening": "", "intents": []}
    doc = open_session(args.mode, args.channel, arc=arc)
    path = _session_path(doc["session_id"])
    print(f"{doc['session_id']} {path}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    if args.session_id:
        try:
            doc = load_session(args.session_id)
        except FileNotFoundError:
            print(f"Error: no such session: {args.session_id}", file=sys.stderr)
            return 1
        turns = doc.get("turns") or []
        print(f"{doc['session_id']}: {doc.get('status')} ({doc.get('mode')}/{doc.get('channel')})")
        print(f"turns: {len(turns)}")
        if args.full:
            for turn in turns:
                print(f"  {turn.get('role')} [{turn.get('ts')}]: {turn.get('text')}")
        return 0
    sessions = list_sessions()
    if not sessions:
        print("No conversation sessions found.")
        return 0
    for summary in sessions:
        print(
            f"{summary['session_id']}: {summary['status']} "
            f"({summary['mode']}/{summary['channel']}; turns={summary['turn_count']})"
        )
    return 0


def cmd_record_turn(args: argparse.Namespace) -> int:
    text = sys.stdin.read().strip()
    if not text:
        print("Error: turn text must be provided on stdin", file=sys.stderr)
        return 1
    turn = {"role": args.role, "text": text, "channel": args.channel}
    try:
        doc = append_turn(args.session_id, turn, expected_turns=args.expected_turns)
    except (TurnConflictError, SessionClosedError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"{doc['session_id']}: {len(doc['turns'])} turn(s)")
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    takeaway = sys.stdin.read().strip() if not sys.stdin.isatty() else ""
    close = {"reason": args.reason}
    if takeaway:
        close["takeaway"] = takeaway
    try:
        doc = close_session(args.session_id, close)
    except (InvalidCloseError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"{doc['session_id']}: closed ({args.reason})")
    return 0


def cmd_turn_prompt(_args: argparse.Namespace) -> int:
    _run_prompt_builder(TURN_PROMPT_REQUIRED_FIELDS, build_turn_prompt)
    return 0


def cmd_router_prompt(_args: argparse.Namespace) -> int:
    _run_prompt_builder(ROUTER_PROMPT_REQUIRED_FIELDS, build_router_prompt)
    return 0


def cmd_arc_prompt(_args: argparse.Namespace) -> int:
    _run_prompt_builder(ARC_PROMPT_REQUIRED_FIELDS, build_arc_prompt)
    return 0


def cmd_closing_prompt(_args: argparse.Namespace) -> int:
    _run_prompt_builder(CLOSING_PROMPT_REQUIRED_FIELDS, build_closing_prompt)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Lifehug conversation session store + builders")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("open", help="Open a new session; prints its id and document path")
    p.add_argument("--mode", required=True, choices=sorted(VALID_MODES))
    p.add_argument("--channel", required=True, choices=sorted(VALID_CHANNELS))
    p.add_argument("--question-id", default=None, help="Attach the arc card for this question, if one exists")
    p.set_defaults(func=cmd_open)

    p = sub.add_parser("status", help="Metadata-only list/detail (turn text needs --full)")
    p.add_argument("session_id", nargs="?")
    p.add_argument("--full", action="store_true", help="Also print turn text (private content)")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("record-turn", help="CAS-append one turn; text on stdin")
    p.add_argument("session_id")
    p.add_argument("--role", required=True, choices=sorted(VALID_ROLES))
    p.add_argument("--channel", default="cli", choices=sorted(VALID_CHANNELS))
    p.add_argument("--expected-turns", required=True, type=int)
    p.set_defaults(func=cmd_record_turn)

    p = sub.add_parser("close", help="Store close only; takeaway on stdin optional")
    p.add_argument("session_id")
    p.add_argument("--reason", required=True, choices=sorted(VALID_CLOSE_REASONS))
    p.set_defaults(func=cmd_close)

    p = sub.add_parser("turn-prompt", help="stdin JSON -> the turn prompt")
    p.set_defaults(func=cmd_turn_prompt)

    p = sub.add_parser("router-prompt", help="stdin JSON -> the router prompt")
    p.set_defaults(func=cmd_router_prompt)

    p = sub.add_parser("arc-prompt", help="stdin JSON -> the arc-planning prompt")
    p.set_defaults(func=cmd_arc_prompt)

    p = sub.add_parser("closing-prompt", help="stdin JSON -> the closing-takeaway prompt")
    p.set_defaults(func=cmd_closing_prompt)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
