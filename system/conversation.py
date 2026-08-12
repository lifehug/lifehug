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
    "session",
)

CHARS_PER_TOKEN = 4  # contract-pinned approximation for budget truncation


class ConversationError(Exception):
    """Base error for conversation-store operations."""


class TurnConflictError(ConversationError):
    """The expected turn count did not match — a concurrent writer won."""


class SessionClosedError(ConversationError):
    """The session is already closed; no further turns may be appended."""


class InvalidCloseError(ConversationError):
    """A close was attempted with a vocabulary or idempotency mismatch."""


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
    for optional in ("router", "model", "question_id", "source_path"):
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


def _truncate(text: str, budget_tokens: object) -> str:
    if not isinstance(budget_tokens, int):
        return text
    limit = budget_tokens * CHARS_PER_TOKEN
    return text if len(text) <= limit else text[:limit]


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


#: The closed six-kind arc-card intent vocabulary (mid-flight audit amendment
#: M10) — arc.intents holds typed objects shaped like {"kind": <one of
#: these>, ...}, never plain strings.
ARC_INTENT_KINDS = frozenset({
    "scene_slot",
    "neighborhood_sibling",
    "timeline_gap",
    "studio_slot",
    "sit_with",
    "demonstrated_knowledge_summary",
})


def _intent_label(intent: object) -> str:
    """A short human/model-readable label for one typed arc-card intent."""
    if isinstance(intent, dict):
        return str(intent.get("kind", intent))
    return str(intent)


def _assemble_session_block(session: dict) -> str:
    parts: list[str] = []
    arc = session.get("arc")
    if arc:
        opening = arc.get("opening", "")
        intents = arc.get("intents") or []
        labels = ", ".join(_intent_label(intent) for intent in intents)
        parts.append(f"Arc card: {opening} (intents: {labels})")
    summary = session.get("rolling_summary")
    if summary:
        parts.append(f"Rolling summary: {summary}")
    for turn in session.get("turns") or []:
        parts.append(f"{turn.get('role')}: {turn.get('text')}")
    return "\n".join(parts)


def assemble_context(
    session: dict,
    *,
    vault_root: str | Path | None = None,
    blocks: dict[str, str] | None = None,
) -> str:
    """Deterministic identity->behavior->examples->profile->record->session context."""
    root = _resolve_root(vault_root)
    blocks = blocks or {}
    manifest = _safe_manifest()
    content = {
        "identity": _read_framework_text("prompt", "identity.md"),
        "behavior": _read_framework_text("prompt", "behavior.md"),
        "examples": _read_framework_text("prompt", "examples.md"),
        "profile": blocks.get("profile") if "profile" in blocks else _assemble_profile_block(root),
        "record": blocks.get("record") if "record" in blocks else _assemble_record_block(session, root),
        "session": _assemble_session_block(session),
    }
    rendered = []
    for name in ASSEMBLE_CONTEXT_BLOCK_ORDER:
        budget = manifest.get(f"budget.{name}")
        text = _truncate(content[name], budget)
        rendered.append(f"## {name.upper()}\n\n{text}")
    return "\n\n".join(rendered)


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
        if exchanges_done == target - 1:
            return "exit-friendly"
        return "mid-arc"
    cap = manifest.get("knob.conversation_turn_cap_exchanges")
    cap = cap if isinstance(cap, int) else 25
    if len(turns) >= cap * 2:
        return "closing-candidate"
    return "mid-arc"


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
        .replace("{arc_card_current_intent}", _intent_label(intents[0]) if intents else "(no arc card)")
        .replace("{turn_position}", position)
        .replace("{previous_turn_summary}", (turns[-1]["text"][:200] if turns else "(none — this is the opening)"))
        .replace("{applicable_rule_hints}", _rule_hints_for_position(position))
    )
    return (
        f"{context}\n\n## TURN_INSTRUCTIONS\n\n{filled}\n\n"
        f"Hard length cap for this message: {length_cap} characters."
    )


def _rule_hints_for_position(position: str) -> str:
    """Deterministic behavior.md rule hints per turn position (definition file
    slot {applicable_rule_hints}; the mapping mirrors behavior.md's own
    structure — opening leans on framing/grammar rules, middle on
    respond-before-ask/register, closing on rule 8)."""
    hints = {
        "opening": "2 (respond-before-ask), 3 (question grammar), 5 (register), 7 (escalation)",
        "middle": "1 (one question max), 2 (respond-before-ask), 5 (register), 6 (payout anatomy), 13 (back-off)",
        "exit_door": "1 (one question max), 8 (closings — offer the door, do not push past it)",
        "closing": "8 (closings: takeaway, appreciation, continuity, hook, stop)",
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


def build_router_prompt(payload: dict) -> str:
    """Substitute message/state into router.md — never restates its schema/intents."""
    message = payload["message"]
    session_open = payload["session_open"]
    pending_question_id = payload.get("pending_question_id")
    template = _read_framework_text("router", "router.md")
    pending = "(none)" if pending_question_id is None else str(pending_question_id)
    return (
        f"{template}\n\n"
        "## INPUT (assembled at runtime — classify this message)\n\n"
        f"SESSION OPEN: {session_open}\n"
        f"PENDING QUESTION: {pending}\n\n"
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


def build_closing_prompt(payload: dict) -> str:
    """Assemble the closing-takeaway prompt per behavior rule 8."""
    session = payload["session"]
    manifest = _safe_manifest()
    deposit_framing = str(manifest.get("knob.deposit_framing", "off")).strip().lower() == "on"
    lines = [
        "=" * 70,
        "LIFEHUG — CLOSING TAKEAWAY",
        "=" * 70,
        "",
        f"Mode: {session.get('mode', '')}",
        f"Rolling summary: {session.get('rolling_summary', '')}",
        "",
        "Write the closing message for this session (behavior rule 8):",
        "  1. A takeaway — NOT a recap.",
        "  2. Specific appreciation.",
        "  3. A continuity line.",
    ]
    if deposit_framing:
        lines.append("  4. An optional deposit-frame (knob.deposit_framing is ON).")
    else:
        lines.append("  4. Deposit-framing is OFF — do not use a deposit frame.")
    lines.append("  5. A named hook for next time, then STOP — no trailing question.")
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
    except (OSError, ValueError, KeyError) as exc:
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
