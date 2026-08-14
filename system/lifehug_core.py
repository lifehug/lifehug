#!/usr/bin/env python3
"""Shared Lifehug parsing and state helpers."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

from vault_paths import (
    append_vault_text,
    atomic_write_vault_text,
    framework_path,
    ensure_vault_directory,
    open_vault_file,
    read_vault_bytes,
    read_vault_text,
    resolve_framework_system_dir,
    resolve_vault_root,
    vault_data_path,
    vault_layout,
    unlink_vault_file,
)

SYSTEM_DIR = resolve_framework_system_dir()
FRAMEWORK_ROOT = SYSTEM_DIR.parent
_RESOLVED_VAULT_ROOT = resolve_vault_root(
    framework_system_dir=SYSTEM_DIR,
    bind_process=True,
)
VAULT_LAYOUT = vault_layout(_RESOLVED_VAULT_ROOT, framework_system_dir=SYSTEM_DIR)


class VaultPath(type(Path())):
    """A durable-data path whose ordinary pathlib I/O stays no-follow.

    ``Path`` preserves its concrete class through joins and globbing.  Making
    every contract-derived durable path a ``VaultPath`` therefore keeps legacy
    callers that use ``.read_text()`` or ``.mkdir()`` inside the single
    no-follow authority, including paths discovered after the initial vault
    preflight.
    """

    def _inside_selected_vault(self) -> bool:
        try:
            Path(os.path.abspath(self)).relative_to(REPO_DIR)
            return True
        except ValueError:
            return False

    def read_text(self, encoding: str | None = None, errors: str | None = None) -> str:
        if not self._inside_selected_vault():
            return super().read_text(encoding=encoding, errors=errors)
        return read_vault_text(self, vault_root=REPO_DIR, encoding=encoding or "utf-8", errors=errors)

    def read_bytes(self) -> bytes:
        if not self._inside_selected_vault():
            return super().read_bytes()
        return read_vault_bytes(self, vault_root=REPO_DIR)

    def write_text(
        self,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        if not self._inside_selected_vault():
            return super().write_text(data, encoding=encoding, errors=errors, newline=newline)
        if errors is not None or newline is not None:
            raise ValueError("VaultPath writes support UTF-8 without newline conversion")
        atomic_write_vault_text(self, data, vault_root=REPO_DIR, encoding=encoding or "utf-8")
        return len(data)

    def write_bytes(self, data: bytes) -> int:
        if not self._inside_selected_vault():
            return super().write_bytes(data)
        from vault_paths import atomic_write_vault_bytes

        atomic_write_vault_bytes(self, data, vault_root=REPO_DIR)
        return len(data)

    def open(
        self,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ):
        if not self._inside_selected_vault():
            return super().open(
                mode=mode, buffering=buffering, encoding=encoding, errors=errors, newline=newline
            )
        if buffering != -1 or newline is not None:
            raise ValueError("VaultPath open does not support buffering or newline overrides")
        return open_vault_file(
            self,
            mode,
            vault_root=REPO_DIR,
            encoding=encoding,
            errors=errors,
            create_parents=mode in {"w", "wb", "a", "ab", "x", "xb"},
        )

    def mkdir(self, mode: int = 0o777, parents: bool = False, exist_ok: bool = False) -> None:
        if not self._inside_selected_vault():
            return super().mkdir(mode=mode, parents=parents, exist_ok=exist_ok)
        if self.exists() and not exist_ok:
            raise FileExistsError(self)
        ensure_vault_directory(self, vault_root=REPO_DIR)

    def touch(self, mode: int = 0o666, exist_ok: bool = True) -> None:
        if not self._inside_selected_vault():
            return super().touch(mode=mode, exist_ok=exist_ok)
        if self.exists():
            if not exist_ok:
                raise FileExistsError(self)
            with open_vault_file(self, "a", vault_root=REPO_DIR, file_mode=mode):
                return
        with open_vault_file(
            self, "x", vault_root=REPO_DIR, create_parents=True, file_mode=mode
        ):
            return

    def unlink(self, missing_ok: bool = False) -> None:
        if not self._inside_selected_vault():
            return super().unlink(missing_ok=missing_ok)
        unlink_vault_file(self, vault_root=REPO_DIR, missing_ok=missing_ok)


# The root itself must retain the authority too: many runtime commands build
# user-selected descendants with ``REPO_DIR / relative_path`` rather than a
# named contract constant.  pathlib preserves this subclass through joins,
# globbing, and rglobbing, so those legacy call sites cannot silently fall
# back to symlink-following I/O after process binding.
REPO_DIR = VaultPath(_RESOLVED_VAULT_ROOT)


def _data(name: str) -> Path:
    return VaultPath(vault_data_path(name, vault_root=REPO_DIR, framework_system_dir=SYSTEM_DIR))


QUESTIONS_FILE = _data("question_bank")
ROTATION_FILE = _data("rotation")
COVERAGE_FILE = _data("coverage")
CONFIG_FILE = _data("config")
PROFILE_FILE = _data("profile")
README_FILE = _data("readme")
ANSWERS_DIR = _data("answers")
OUTPUTS_DIR = _data("outputs")
STATE_DIR = _data("state")
WIKI_DIR = _data("wiki")
SOURCES_DIR = _data("sources")
MANUAL_SOURCES_DIR = _data("manual_sources")
IMPORT_SOURCES_DIR = _data("import_sources")
CORRECTION_SOURCES_DIR = _data("correction_sources")
ARTIFACT_SOURCES_DIR = _data("artifact_sources")
QUESTION_CANDIDATES_FILE = _data("question_candidates")
QUESTION_QUEUE_FILE = _data("question_queue")
PLANNER_STATE_FILE = _data("planner_state")
SOURCE_MANIFEST_FILE = _data("source_manifest")
SOURCE_LINT_FINDINGS_FILE = _data("source_lint_findings")
LEARNING_FAILURES_FILE = _data("learning_failures")
CLASSIFICATIONS_DIR = _data("classifications")
NEIGHBORHOODS_FILE = _data("neighborhoods")
FOCUS_RECS_FILE = _data("focus_recommendations")
LEGACY_FOCUS_RECS_FILE = _data("legacy_focus_recommendations")
ROADMAP_FILE = _data("roadmap")
QUALITY_PROFILE_FILE = _data("quality_profile")
ANSWER_SCORES_FILE = _data("answer_scores")
ENTITY_ROSTERS_DIR = _data("entity_rosters")
CONNECTORS_STATE_DIR = _data("connectors_state")
SECOND_VOICE_OFFERS_FILE = _data("second_voice_offers")
BOOK_OFFERS_FILE = _data("book_offers")
TIMELINE_PLACEMENTS_FILE = _data("timeline_placements")
PERENNIALS_FILE = _data("perennials")
WIKI_SYNTHESIS_CACHE_FILE = _data("wiki_synthesis_cache")
SYNTHESIS_DIR = _data("synthesis")
REPORTS_DIR = _data("reports")
AGENT_TASKS_DIR = _data("agent_tasks")
JOBS_DIR = _data("jobs")
COMPILE_NEEDED_FILE = _data("compile_needed")
ARC_CARDS_FILE = _data("arc_cards")
CONVERSATIONS_DIR = _data("conversations")
MIRROR_RESPONSES_FILE = _data("mirror_responses")
CONVERSATION_DELIVERIES_FILE = _data("conversation_deliveries")
QUESTION_JUDGMENT_LEARNED_FILE = _data("question_judgment_learned")

TEMPLATES_DIR = framework_path("templates", framework_system_dir=SYSTEM_DIR)
MISSION_FILE = framework_path("mission", framework_system_dir=SYSTEM_DIR)
CONNECTORS_DIR = framework_path("connectors", framework_system_dir=SYSTEM_DIR)
INTERACTIONS_DIR = framework_path("interactions", framework_system_dir=SYSTEM_DIR)

QUESTION_ID_RE = r"[A-Z]\d+[a-z]*"
QUESTION_LINE_RE = re.compile(
    rf"^- \[([ xX])\] ({QUESTION_ID_RE}): (.+?)(?:\s+\*\(.+\)\*)?\s*$",
    re.MULTILINE,
)
CATEGORY_HEADER_RE = re.compile(r"^## ([A-Z]): (.+?)(?:\s*\((.*)\))?\s*$")

STORY_FUNCTIONS = (
    "foundation",
    "scene",
    "tension",
    "turning_point",
    "relationship",
    "meaning",
    "contradiction",
    "output_gap",
    # self-knowledge arc (WNRS / 36-Questions / IFS style)
    "self_image",
    "value",
    "fear",
    "perception_by_others",
    "growth_edge",
    # relational / dyadic arc
    "who_they_are",
    "shared_history",
    "what_i_see_in_them",
    "what_i_want_them_to_know",
    "how_they_see_me",
)


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path, default=None):
    try:
        if _is_vault_path(path):
            return json.loads(read_vault_text(path, vault_root=REPO_DIR))
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default


def read_text(path: Path, *, encoding: str = "utf-8", errors: str | None = None) -> str:
    if _is_vault_path(path):
        return read_vault_text(path, vault_root=REPO_DIR, encoding=encoding, errors=errors)
    return path.read_text(encoding=encoding, errors=errors)


def read_bytes(path: Path) -> bytes:
    if _is_vault_path(path):
        return read_vault_bytes(path, vault_root=REPO_DIR)
    return path.read_bytes()


def write_json(path: Path, data) -> None:
    content = json.dumps(data, indent=2) + "\n"
    if _is_vault_path(path):
        atomic_write_vault_text(path, content, vault_root=REPO_DIR)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    if _is_vault_path(path):
        atomic_write_vault_text(path, text, vault_root=REPO_DIR)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def append_text(path: Path, text: str) -> None:
    if _is_vault_path(path):
        append_vault_text(path, text, vault_root=REPO_DIR)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def _is_vault_path(path: Path) -> bool:
    try:
        Path(os.path.abspath(path)).relative_to(REPO_DIR)
        return True
    except ValueError:
        return False


def record_learning_failure(
    component: str,
    operation: str,
    error: object,
    *,
    context: dict[str, object] | None = None,
    exit_code: int | None = None,
    path: Path = LEARNING_FAILURES_FILE,
) -> dict[str, object]:
    """Append a non-blocking learning-loop failure for later doctor review."""
    record: dict[str, object] = {
        "recorded_at": now_utc(),
        "component": component,
        "operation": operation,
        "error": str(error)[:4000],
    }
    if exit_code is not None:
        record["exit_code"] = exit_code
    if context:
        record["context"] = context
    line = json.dumps(record, ensure_ascii=False) + "\n"
    if _is_vault_path(path):
        append_vault_text(path, line, vault_root=REPO_DIR)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    return record


def read_learning_failures(
    *,
    limit: int = 5,
    since_days: int | None = 14,
    path: Path = LEARNING_FAILURES_FILE,
) -> list[dict[str, object]]:
    if not path.exists():
        return []
    cutoff = None
    if since_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if cutoff is not None:
            recorded_at = str(row.get("recorded_at", ""))
            try:
                recorded_dt = datetime.strptime(recorded_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            except ValueError:
                recorded_dt = None
            if recorded_dt is not None and recorded_dt < cutoff:
                continue
        rows.append(row)
    return rows[-limit:][::-1]


def format_learning_failure(row: dict[str, object]) -> str:
    when = str(row.get("recorded_at", "?"))
    component = str(row.get("component", "?"))
    operation = str(row.get("operation", "?"))
    error = " ".join(str(row.get("error", "")).split())
    if len(error) > 160:
        error = error[:157] + "..."
    return f"{when} {component}/{operation}: {error or 'unknown failure'}"


def format_learning_failures_summary(limit: int = 3, since_days: int | None = 14) -> str:
    rows = read_learning_failures(limit=limit, since_days=since_days)
    if not rows:
        return "Learning-loop failures: none recorded recently"
    lines = [f"Learning-loop failures: {len(rows)} recent"]
    lines.extend(f"- {format_learning_failure(row)}" for row in rows)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sensitivity tiers (privacy phase 0, v73). THE CONTRACT:
#   - Raw sources (answers/, sources/) NEVER leave the private repo. Ever.
#   - The compiled wiki is the OWNER tier: permanently private, fully honest,
#     never censored. Sensitivity does not gate synthesis — it exists so
#     future audience surfaces can be generated as SEPARATE BUILDS
#     (filter at build time, never at read time).
#   - Everything unlabeled defaults to `private`. Tiers only ever open
#     material through an explicit, owner-reviewed promotion — never expose it.
# ---------------------------------------------------------------------------

# Most-open → most-closed. A page/source at level X is visible to a viewer
# tier V when rank(V) >= rank(X).
SENSITIVITY_LEVELS = ("public", "friends", "family", "private")
_SENSITIVITY_RANK = {level: i for i, level in enumerate(SENSITIVITY_LEVELS)}


def sensitivity_rank(level: str | None) -> int:
    """Unknown, blank, or legacy values ('personal') rank as private —
    the safe default is always the closed one."""
    return _SENSITIVITY_RANK.get(str(level or "").strip().lower(), _SENSITIVITY_RANK["private"])


def sensitivity_floor(levels) -> str:
    """The most-closed level among `levels` — a page is as sensitive as its
    most sensitive source."""
    best = 0
    for level in levels:
        best = max(best, sensitivity_rank(level))
    return SENSITIVITY_LEVELS[best]


def sensitivity_visible(content_level: str | None, viewer_level: str | None) -> bool:
    """Would content at `content_level` be included in a `viewer_level` build?
    The owner sees everything."""
    if str(viewer_level or "").strip().lower() in ("owner", "private", ""):
        return True
    return sensitivity_rank(viewer_level) >= sensitivity_rank(content_level)


# Telegram hard limit is 4096 chars/message; leave headroom for prefixes.
TELEGRAM_CHUNK_LIMIT = 3900


class TelegramSendResult(NamedTuple):
    """Content-free outcome for one Telegram notification attempt.

    ``ambiguous`` means bytes may have reached Telegram but no authoritative
    success/rejection response came back.  Callers that care about duplicate
    side effects must persist that state and require human confirmation before
    repeating the send.
    """

    status: str
    reason: str
    chunks_confirmed: int
    chunks_total: int


def chunk_message(text: str, limit: int = TELEGRAM_CHUNK_LIMIT) -> list[str]:
    """Split a long message into <=limit chunks on line boundaries so a big
    weekly/monthly summary is delivered in parts instead of being silently
    dropped by Telegram's 4096-char cap."""
    text = text.rstrip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.split("\n"):
        # A single pathological line longer than the limit gets hard-split.
        while len(line) > limit:
            if current:
                chunks.append("\n".join(current))
                current, current_len = [], 0
            chunks.append(line[:limit])
            line = line[limit:]
        if current_len + len(line) + 1 > limit and current:
            chunks.append("\n".join(current))
            current, current_len = [], 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    total = len(chunks)
    if total > 1:
        chunks = [f"({i}/{total})\n{chunk}" for i, chunk in enumerate(chunks, 1)]
    return chunks


def resolve_telegram_target() -> tuple[str, str]:
    """Resolve (token, chat_id) from env, config, or the OpenClaw config.
    Returns empty strings for whatever is missing — callers no-op gracefully."""
    import os

    config = load_config()
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID")
               or str(config.get("telegram_chat_id") or "")
               or str(config.get("group_chat_id") or ""))
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        openclaw_cfg = Path.home() / ".openclaw" / "openclaw.json"
        if openclaw_cfg.exists():
            try:
                data = json.loads(openclaw_cfg.read_text(encoding="utf-8"))
                token = str(data.get("channels", {}).get("telegram", {}).get("botToken", ""))
            except (OSError, json.JSONDecodeError):
                token = ""
    return token, chat_id


def send_telegram_result(text: str) -> TelegramSendResult:
    """Send Telegram text and preserve confirmed-vs-ambiguous semantics.

    The returned fields contain delivery metadata only.  A transport failure
    is ambiguous because the request may have reached Telegram before the
    response was lost; an explicit HTTP/API rejection is definitive only when
    no earlier chunk was confirmed.  This function never raises.
    """
    import urllib.error
    import urllib.parse
    import urllib.request

    token, chat_id = resolve_telegram_target()
    chunks = chunk_message(text)
    if not text.strip():
        return TelegramSendResult("not_attempted", "empty_message", 0, 0)
    if not token or not chat_id:
        return TelegramSendResult(
            "not_attempted", "telegram_credentials_missing", 0, len(chunks)
        )
    confirmed = 0
    for chunk in chunks:
        payload = urllib.parse.urlencode({"chat_id": chat_id, "text": chunk}).encode("utf-8")
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=payload)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw_body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            exc.close()
            if confirmed:
                return TelegramSendResult(
                    "ambiguous", "telegram_partial_delivery", confirmed, len(chunks)
                )
            return TelegramSendResult("rejected", "telegram_http_rejected", 0, len(chunks))
        except Exception:  # noqa: BLE001 — no response means delivery is unknowable
            return TelegramSendResult(
                "ambiguous", "telegram_transport_ambiguous", confirmed, len(chunks)
            )
        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError:
            return TelegramSendResult(
                "ambiguous", "telegram_response_ambiguous", confirmed, len(chunks)
            )
        if not isinstance(body, dict) or not body.get("ok"):
            if confirmed:
                return TelegramSendResult(
                    "ambiguous", "telegram_partial_delivery", confirmed, len(chunks)
                )
            return TelegramSendResult("rejected", "telegram_api_rejected", 0, len(chunks))
        confirmed += 1
    return TelegramSendResult("confirmed", "telegram_confirmed", confirmed, len(chunks))


def send_telegram(text: str) -> bool:
    """Backward-compatible boolean Telegram helper for ordinary notices."""
    return send_telegram_result(text).status == "confirmed"


class ConfigSyntaxError(ValueError):
    """A security-relevant config entry could not be parsed safely."""


AI_ROUTING_CONFIG_KEYS = frozenset({
    "ai_provider",
    "ai_timeout_seconds",
    "anthropic_api_key",
    "kimi_api_key",
    "kimi_base_url",
    "kimi_max_tokens",
    "kimi_model",
    "local_ai_allow_non_loopback",
    "local_ai_api_key",
    "local_ai_base_url",
    "local_ai_model",
    "local_ai_timeout_seconds",
})
_AI_ROUTING_PREFIXES = ("ai_", "anthropic_", "kimi_", "local_ai_")


def _parse_simple_yaml(
    path: Path,
    *,
    validate_ai_routing: bool = False,
) -> dict[str, str]:
    """Read the flat top-level scalar subset of a YAML file used by scripts."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        content = line.split("#", 1)[0].strip()
        has_colon = ":" in content
        raw_key = content.partition(":")[0].strip() if has_colon else content
        key_candidate = raw_key.strip('"').strip("'")
        if validate_ai_routing:
            leading = content.lstrip("- ").lstrip('"').lstrip("'")
            references_known_key = any(
                re.match(rf"{re.escape(key)}(?![A-Za-z0-9_])", leading)
                for key in AI_ROUTING_CONFIG_KEYS
            )
            namespaced_key = key_candidate.startswith(_AI_ROUTING_PREFIXES)
            valid_known_shape = has_colon and key_candidate in AI_ROUTING_CONFIG_KEYS
            if (
                (references_known_key and not valid_known_shape)
                or (namespaced_key and key_candidate not in AI_ROUTING_CONFIG_KEYS)
            ):
                raise ConfigSyntaxError(
                    "invalid AI routing configuration syntax"
                )
        if not has_colon:
            continue
        key, _, val = line.partition(":")
        key = key.strip().strip('"').strip("'")
        if not key or val.strip().startswith("|"):
            if validate_ai_routing and key in AI_ROUTING_CONFIG_KEYS:
                raise ConfigSyntaxError(
                    "AI routing configuration values must be flat scalars"
                )
            continue
        out[key] = val.split("#", 1)[0].strip().strip('"').strip("'")
    return out


def load_config(
    path: Path | None = None,
    *,
    validate_ai_routing: bool = False,
) -> dict[str, str]:
    """Merge committed identity/preferences with local secrets.

    `profile.yaml` (committed to the repo — safe to share: name, full_name,
    timezone, channel) is the base; `config.yaml` (gitignored — secrets like
    anthropic_api_key / telegram tokens, and local overrides) layers on top and
    wins on conflict. Legacy installs with only config.yaml keep working
    unchanged. Passing an explicit path other than config.yaml reads just that
    file (back-compat for callers/tests)."""
    if path is None or path == CONFIG_FILE:
        merged = _parse_simple_yaml(
            PROFILE_FILE, validate_ai_routing=validate_ai_routing
        )
        merged.update(_parse_simple_yaml(
            CONFIG_FILE, validate_ai_routing=validate_ai_routing
        ))
        return merged
    return _parse_simple_yaml(path, validate_ai_routing=validate_ai_routing)


def normalize_group(group: str | None) -> str:
    """Normalize old category group names to the current vocabulary."""
    if group == "spot" "light":
        return "focus"
    return group or "main"


def category_group(cat_id: str, section_group: str | None = None) -> str:
    section_group = normalize_group(section_group)
    if section_group in {"main", "project", "focus"}:
        return section_group
    if cat_id >= "K":
        return "focus"
    if cat_id >= "F":
        return "project"
    return "main"


def parse_categories(md_text: str) -> dict[str, dict[str, str]]:
    """Discover categories and their metadata from question-bank.md."""
    categories: dict[str, dict[str, str]] = {}
    group = "main"
    for line in md_text.splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("## focus") or stripped.startswith("## " + ("spot" "light")):
            group = "focus"
            continue
        if stripped.startswith("## project"):
            group = "project"
            continue

        match = CATEGORY_HEADER_RE.match(line)
        if match:
            cat_id = match.group(1)
            name = match.group(2).strip()
            qualifier = (match.group(3) or "").strip()  # the "(...)" suffix, e.g. "Etherfuse Story"
            categories[cat_id] = {
                "name": name,
                "group": category_group(cat_id, group),
                "qualifier": qualifier,
            }
    return categories


def parse_questions(md_text: str) -> list[dict[str, object]]:
    """Parse question-bank.md into question records.

    Supports base IDs (`A14`) and generated follow-up IDs (`A14a`, `G5c`).
    """
    questions: list[dict[str, object]] = []
    for match in QUESTION_LINE_RE.finditer(md_text):
        qid = match.group(2)
        questions.append({
            "id": qid,
            "category": qid[0],
            "text": match.group(3).strip(),
            "answered": match.group(1).lower() == "x",
        })
    return questions


def question_by_id(questions: list[dict[str, object]], question_id: str):
    wanted = question_id.strip()
    return next((q for q in questions if q["id"] == wanted), None)


def compute_coverage(
    questions: list[dict[str, object]],
    categories: dict[str, dict[str, str]],
) -> dict:
    coverage = {
        "version": 1,
        "last_updated": datetime.now().isoformat(),
        "categories": {},
    }
    known_cats = sorted(set(categories) | {str(q["category"]) for q in questions})
    for cat_id in known_cats:
        cat_qs = [q for q in questions if q["category"] == cat_id]
        total = len(cat_qs)
        answered = sum(1 for q in cat_qs if q["answered"])
        ratio = answered / total if total else 0
        if ratio >= 0.7:
            status = "green"
        elif ratio >= 0.3:
            status = "yellow"
        else:
            status = "red"
        coverage["categories"][cat_id] = {
            "total": total,
            "answered": answered,
            "status": status,
        }
    return coverage


def rebuild_coverage() -> dict:
    md_text = QUESTIONS_FILE.read_text()
    questions = parse_questions(md_text)
    categories = parse_categories(md_text)
    coverage = compute_coverage(questions, categories)
    write_json(COVERAGE_FILE, coverage)
    return coverage


def mark_answered_in_bank(question_id: str, answered_date: str | None = None) -> bool:
    md = QUESTIONS_FILE.read_text()
    date_text = answered_date or datetime.now().date().isoformat()
    qid = re.escape(question_id)
    pattern = re.compile(
        rf"^(- \[) \] ({qid}: .+?)(?:\s+\*\(.+\)\*)?\s*$",
        re.MULTILINE,
    )
    new_md, count = pattern.subn(rf"\1x] \2 *({date_text})*", md, count=1)
    if count:
        write_text(QUESTIONS_FILE, new_md)
        return True
    return False


def answer_id_from_filename(path: Path) -> str | None:
    match = re.match(rf"^({QUESTION_ID_RE})", path.stem)
    return match.group(1) if match else None


def split_frontmatter(content: str) -> tuple[dict[str, object], str]:
    """Return simple YAML-ish frontmatter and body.

    Lifehug only emits scalar JSON-compatible values in frontmatter, so this
    intentionally stays small instead of depending on a YAML parser.
    """
    if not content.startswith("---\n"):
        return {}, content
    lines = content.splitlines()
    end_index = None
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = idx
            break
    if end_index is None:
        return {}, content

    metadata: dict[str, object] = {}
    for raw in lines[1:end_index]:
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if not value:
            metadata[key] = ""
            continue
        try:
            metadata[key] = json.loads(value)
        except json.JSONDecodeError:
            metadata[key] = value.strip('"').strip("'")

    body = "\n".join(lines[end_index + 1:])
    if body.startswith("\n"):
        body = body[1:]
    if content.endswith("\n"):
        body += "\n"
    return metadata, body


def answer_body(content: str) -> str:
    _metadata, frontmatter_body = split_frontmatter(content)
    target = frontmatter_body if frontmatter_body != content else content
    body_match = re.search(r"---\n+(.*?)(?:\n+---|\Z)", target, re.DOTALL)
    if body_match:
        captured = body_match.group(1).strip()
        if captured.startswith("## Follow-up"):
            # v89: that --- was the divider BEFORE the generated follow-up
            # section, not a body wrapper — the answer is what precedes it.
            # (Without this, N10's Iron Man moment compiled as just its
            # follow-up list.)
            return target[: body_match.start()].strip()
        return captured
    return target.strip()


def status_emoji(answered: int, total: int) -> str:
    if total == 0:
        return "⚪"
    ratio = answered / total
    if ratio >= 0.7:
        return "🟢"
    if ratio >= 0.3:
        return "🟡"
    return "🔴"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return slug.strip("-") or "untitled"


def load_mission() -> str:
    """Load mission.md content for AI prompt injection."""
    if MISSION_FILE.exists():
        return MISSION_FILE.read_text(encoding="utf-8")
    return ""
