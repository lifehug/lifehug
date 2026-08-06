#!/usr/bin/env python3
"""Best-effort warm acknowledgment delivery for durable Lifehug answers.

This module is orchestration, not a provider or a tone authority.  It builds
the byte-identical prompt through :mod:`answer_ack`, calls the shared
``ai_provider` router, and sends through ``lifehug_core``'s shared Telegram
transport.  Its state contains metadata only: source ids, fixed reason codes,
timestamps, and attempt counts — never answer, prompt, or generated text.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ai_provider import (
    AIConfigurationError,
    AIProviderError,
    AIResponseError,
    AIUnavailableError,
    call_ai,
    provider_status,
)
from answer_ack import build_prompt
from lifehug_core import (
    ANSWERS_DIR,
    STATE_DIR,
    TelegramSendResult,
    load_config,
    now_utc,
    read_json,
    record_learning_failure,
    send_telegram_result,
    split_frontmatter,
    write_json,
)

ACK_STATE_FILE = STATE_DIR / "answer_acknowledgments.json"
DEFAULT_ACK_MODEL = "claude-sonnet-5"
ACK_MAX_CHARS = 1200

STATUS_CONFIRMED = "confirmed"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"
STATUS_AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class AcknowledgmentOutcome:
    source_id: str
    status: str
    reason: str
    attempted: bool


def _state(path: Path) -> dict:
    data = read_json(path, default={}) or {}
    if not isinstance(data, dict) or not isinstance(data.get("entries", {}), dict):
        return {"version": 1, "entries": {}}
    data.setdefault("version", 1)
    data.setdefault("entries", {})
    return data


def _write_outcome(
    path: Path,
    *,
    source_id: str,
    question_id: str,
    status: str,
    reason: str,
    attempts: int,
) -> None:
    data = _state(path)
    entry = {
        "source_id": source_id,
        "question_id": question_id,
        "status": status,
        "reason": reason,
        "attempts": attempts,
        "updated_at": now_utc(),
    }
    if status == STATUS_CONFIRMED:
        entry["confirmed_at"] = entry["updated_at"]
    if status == STATUS_AMBIGUOUS:
        entry["operator_action"] = "verify Telegram before retrying"
    data["entries"][source_id] = entry
    write_json(path, data)


def _fixed_provider_reason(exc: BaseException) -> str:
    if isinstance(exc, AIConfigurationError):
        return "provider_configuration_error"
    if isinstance(exc, AIResponseError):
        return "provider_malformed_response"
    if isinstance(exc, AIUnavailableError):
        return "provider_unavailable"
    return "generation_failed"


def _valid_completion(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    message = raw.strip()
    if not message or len(message) > ACK_MAX_CHARS or "\x00" in message:
        return None
    lowered = message.lower()
    if message.startswith(("```", "{", "[")):
        return None
    if "lifehug — answer acknowledgment" in lowered or "end of context" in lowered:
        return None
    return message


def _diagnostic(operation: str, reason: str, source_id: str) -> None:
    """Persist fixed metadata only; never accept exception/model text here."""
    record_learning_failure(
        "answer_ack_delivery",
        operation,
        reason,
        context={"source_id": source_id},
    )


def acknowledge_answer(
    *,
    source_id: str,
    question_id: str,
    question_text: str,
    question_category: str,
    answer_text: str,
    followup_pending: bool,
    state_path: Path = ACK_STATE_FILE,
    allow_ambiguous_retry: bool = False,
    prompt_builder: Callable[[dict], str] = build_prompt,
    ai_call: Callable[[str, str], str] | None = None,
    status_resolver: Callable[..., object] | None = None,
    telegram_send: Callable[[str], TelegramSendResult] | None = None,
) -> AcknowledgmentOutcome:
    """Generate and send one acknowledgment after its source is durable.

    Confirmed delivery is exactly-once from this workspace.  Ambiguous
    delivery is conservatively non-retryable unless an operator explicitly
    confirms that Telegram did not receive it.  Definitive failures/skips may
    be retried because no acknowledgment was sent.
    """
    data = _state(state_path)
    previous = data["entries"].get(source_id, {})
    previous_status = previous.get("status")
    if previous_status == STATUS_CONFIRMED:
        return AcknowledgmentOutcome(
            source_id, STATUS_CONFIRMED, "already_confirmed", False
        )
    if previous_status == STATUS_AMBIGUOUS and not allow_ambiguous_retry:
        return AcknowledgmentOutcome(
            source_id, STATUS_AMBIGUOUS, "ambiguous_not_retried", False
        )

    attempts = int(previous.get("attempts", 0) or 0) + 1
    try:
        cfg = load_config()
    except Exception:  # noqa: BLE001 — malformed local config cannot risk capture
        cfg = {}
    model = str(cfg.get("answer_ack_model") or DEFAULT_ACK_MODEL)
    resolve_status = status_resolver or provider_status
    selected = resolve_status(model, probe=False)
    if not getattr(selected, "ready", False):
        reason = (
            "no_unattended_provider"
            if getattr(selected, "provider", "") == "agent-task"
            else "provider_unavailable"
        )
        _write_outcome(
            state_path,
            source_id=source_id,
            question_id=question_id,
            status=STATUS_SKIPPED,
            reason=reason,
            attempts=attempts,
        )
        return AcknowledgmentOutcome(source_id, STATUS_SKIPPED, reason, True)

    payload = {
        "question_id": question_id,
        "question_text": question_text,
        "question_category": question_category,
        "answer_text": answer_text,
        "followup_pending": followup_pending,
    }
    try:
        prompt = prompt_builder(payload)
        generated = (ai_call or call_ai)(prompt, model)
    except AIProviderError as exc:
        reason = _fixed_provider_reason(exc)
        _write_outcome(
            state_path,
            source_id=source_id,
            question_id=question_id,
            status=STATUS_FAILED,
            reason=reason,
            attempts=attempts,
        )
        _diagnostic("generation", reason, source_id)
        return AcknowledgmentOutcome(source_id, STATUS_FAILED, reason, True)
    except Exception:  # noqa: BLE001 — answer durability always wins
        reason = "generation_failed"
        _write_outcome(
            state_path,
            source_id=source_id,
            question_id=question_id,
            status=STATUS_FAILED,
            reason=reason,
            attempts=attempts,
        )
        _diagnostic("generation", reason, source_id)
        return AcknowledgmentOutcome(source_id, STATUS_FAILED, reason, True)

    message = _valid_completion(generated)
    if message is None:
        reason = "malformed_generation"
        _write_outcome(
            state_path,
            source_id=source_id,
            question_id=question_id,
            status=STATUS_FAILED,
            reason=reason,
            attempts=attempts,
        )
        _diagnostic("generation", reason, source_id)
        return AcknowledgmentOutcome(source_id, STATUS_FAILED, reason, True)

    # Persist the conservative replay position BEFORE the external effect.  A
    # crash after this write is surfaced as ambiguous instead of blindly
    # repeating a send that may have reached Telegram.
    _write_outcome(
        state_path,
        source_id=source_id,
        question_id=question_id,
        status=STATUS_AMBIGUOUS,
        reason="send_in_progress",
        attempts=attempts,
    )
    send_result = (telegram_send or send_telegram_result)(message)
    if send_result.status == "confirmed":
        status, reason = STATUS_CONFIRMED, "telegram_confirmed"
    elif send_result.status == "ambiguous":
        status, reason = STATUS_AMBIGUOUS, send_result.reason
    elif send_result.status == "not_attempted":
        status, reason = STATUS_SKIPPED, send_result.reason
    else:
        status, reason = STATUS_FAILED, send_result.reason
    _write_outcome(
        state_path,
        source_id=source_id,
        question_id=question_id,
        status=status,
        reason=reason,
        attempts=attempts,
    )
    if status in {STATUS_FAILED, STATUS_AMBIGUOUS}:
        _diagnostic("telegram_send", reason, source_id)
    return AcknowledgmentOutcome(source_id, status, reason, True)


def _durable_answer_context(question_id: str) -> dict[str, str]:
    path = ANSWERS_DIR / f"{question_id}.md"
    metadata, body = split_frontmatter(path.read_text(encoding="utf-8"))
    if not metadata or not body.startswith("# Question "):
        raise ValueError("answer source is missing required metadata")
    _, separator, answer_text = body.partition("\n\n")
    if not separator:
        raise ValueError("answer source body is malformed")
    answer_text = answer_text.split("\n---\n\n## Follow-up Questions Generated", 1)[0].strip()
    required = {
        "source_id": metadata.get("source_id"),
        "question_id": metadata.get("question_id"),
        "question_text": metadata.get("question_text"),
        "question_category": metadata.get("category"),
        "answer_text": answer_text,
    }
    if any(not isinstance(value, str) or not value for value in required.values()):
        raise ValueError("answer source is missing required metadata")
    if required["question_id"] != question_id:
        raise ValueError("answer source question id does not match")
    return required


def retry_durable_answer(
    question_id: str,
    *,
    confirm_not_sent: bool = False,
    state_path: Path = ACK_STATE_FILE,
) -> AcknowledgmentOutcome:
    context = _durable_answer_context(question_id)
    return acknowledge_answer(
        **context,
        followup_pending=False,
        state_path=state_path,
        allow_ambiguous_retry=confirm_not_sent,
    )


def _print_status(question_id: str | None, *, state_path: Path = ACK_STATE_FILE) -> int:
    entries = _state(state_path)["entries"]
    if question_id:
        entries = {
            key: value
            for key, value in entries.items()
            if value.get("question_id") == question_id
        }
    if not entries:
        print("No answer acknowledgment metadata found.")
        return 0
    for source_id, entry in sorted(entries.items()):
        print(
            f"{source_id}: {entry.get('status', 'unknown')} "
            f"({entry.get('reason', 'unknown')}; attempts={entry.get('attempts', 0)})"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect or retry answer acknowledgments")
    sub = parser.add_subparsers(dest="command", required=True)
    status_parser = sub.add_parser("status", help="Show metadata-only delivery status")
    status_parser.add_argument("question_id", nargs="?")
    retry_parser = sub.add_parser("retry", help="Retry a definitively unsent acknowledgment")
    retry_parser.add_argument("question_id")
    retry_parser.add_argument(
        "--confirm-not-sent",
        action="store_true",
        help="Retry an ambiguous send only after verifying Telegram did not receive it",
    )
    args = parser.parse_args()
    if args.command == "status":
        return _print_status(args.question_id)
    try:
        outcome = retry_durable_answer(
            args.question_id, confirm_not_sent=args.confirm_not_sent
        )
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1
    print(f"{outcome.source_id}: {outcome.status} ({outcome.reason})")
    return 0 if outcome.status == STATUS_CONFIRMED else 1


if __name__ == "__main__":
    raise SystemExit(main())
