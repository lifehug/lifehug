#!/usr/bin/env python3
"""Canonical candidate-to-question mutation and Git receipt authority.

The question-bank marker and the Git commit that introduced it are durable
authority. ``state/question_candidates.json`` is a repairable projection and
is never consulted when adopting an already-committed promotion receipt.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path

import exact_file_git
import question_candidate
from lifehug_core import now_utc, parse_categories, parse_questions
from vault_paths import (
    read_vault_text,
    resolve_framework_system_dir,
    resolve_vault_root,
    vault_data_path,
)

SCHEMA_VERSION = 1
MARKER_PREFIX = "  <!-- lifehug:candidate-promotion:v1 "
MARKER_SUFFIX = " -->"
PROMOTION_MODES = frozenset({"manual", "auto", "neighborhood"})
MANUAL_PROMOTABLE_STATUSES = frozenset(
    {"candidate", "accepted", "deferred", "needs_review"}
)
NEIGHBORHOOD_PROMOTABLE_STATUSES = frozenset({"candidate", "accepted", "deferred"})
AUTO_PROMOTABLE_STATUSES = MANUAL_PROMOTABLE_STATUSES
PROMOTABLE_STATUSES_BY_MODE = {
    "manual": MANUAL_PROMOTABLE_STATUSES,
    "auto": AUTO_PROMOTABLE_STATUSES,
    "neighborhood": NEIGHBORHOOD_PROMOTABLE_STATUSES,
}
REQUEST_KEYS = frozenset(
    {
        "schema_version",
        "candidate_id",
        "category_id",
        "source_revision",
        "candidate_revision",
        "category_revision",
        "placement_revision",
        "proposal_revision",
        "decision_revision",
    }
)
PROVENANCE_KEYS = frozenset(
    {
        "source_revision",
        "candidate_revision",
        "category_revision",
        "placement_revision",
        "proposal_revision",
        "decision_revision",
        "request_revision",
    }
)
MARKER_KEYS = frozenset(
    {
        "schema_version",
        "candidate_id",
        "category_id",
        "question_id",
        "question_revision",
        "promoted_at",
        "candidate_provenance",
    }
)
RECEIPT_KEYS = frozenset(
    {
        "candidate_id",
        "category_id",
        "question_id",
        "changed",
        "commit_sha",
        "candidate_provenance",
    }
)
REVISION_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
CATEGORY_RE = re.compile(r"^[A-Z]$")
QUESTION_ID_RE = re.compile(r"^([A-Z])(\d+)$")
CANDIDATE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
MARKER_RE = re.compile(
    rf"^{re.escape(MARKER_PREFIX)}([A-Za-z0-9+/]+={{0,2}}){re.escape(MARKER_SUFFIX)}$"
)
QUESTION_LINE_RE = re.compile(r"^- \[ \] ([A-Z][0-9]+): (.+)$")
SOURCE_FIELDS = (
    "source_path",
    "source_id",
    "origin",
    "source_type",
    "created_at",
    "reason",
    "neighborhood_id",
)


class CandidatePromotionError(ValueError):
    """Promotion request, marker, vault, or Git state failed closed."""


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
    except (TypeError, ValueError) as exc:
        raise CandidatePromotionError("value is not canonical JSON") from exc


def _revision(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not REVISION_RE.fullmatch(value):
        raise CandidatePromotionError(f"{name} must be sha256:<64 lowercase hex>")
    return value


def _nullable_revision(value: object, *, name: str) -> str | None:
    if value is None:
        return None
    return _revision(value, name=name)


def _candidate_id(value: object) -> str:
    if not isinstance(value, str) or not CANDIDATE_ID_RE.fullmatch(value):
        raise CandidatePromotionError("candidate_id is invalid")
    return value


def _category_id(value: object) -> str:
    if not isinstance(value, str):
        raise CandidatePromotionError("category_id must be a string")
    value = value.upper()
    if not CATEGORY_RE.fullmatch(value):
        raise CandidatePromotionError("category_id must be one uppercase letter")
    return value


def _candidate_text(candidate: dict) -> str:
    text = candidate.get("text")
    if not isinstance(text, str) or not text.strip():
        raise CandidatePromotionError("candidate question text is missing")
    text = text.strip()
    if "\n" in text or "\r" in text or len(text) > 20_000:
        raise CandidatePromotionError("candidate question must be one bounded line")
    return text


def _candidate_source(candidate: dict) -> dict:
    source: dict[str, str | None] = {}
    for field in SOURCE_FIELDS:
        value = candidate.get(field)
        if value is not None and not isinstance(value, str):
            raise CandidatePromotionError(f"candidate.{field} must be string or null")
        source[field] = value
    return source


def _candidate_facts(candidate: dict) -> tuple[dict, str]:
    if not isinstance(candidate, dict):
        raise CandidatePromotionError("candidate must be an object")
    candidate_id = _candidate_id(candidate.get("id"))
    text = _candidate_text(candidate)
    source_revision = question_candidate.canonical_revision(
        _candidate_source(candidate)
    )
    anchor = question_candidate.build_candidate_anchor(
        candidate_id, text, source_revision
    )
    return anchor, text


def _category_roster(question_bank_text: str) -> dict:
    categories = parse_categories(question_bank_text)
    rows = [
        {
            "category_id": category_id,
            "label": metadata["name"],
            "group": metadata["group"],
            "qualifier": metadata["qualifier"] or None,
            "focus_id": None,
            "focus_label": None,
        }
        for category_id, metadata in categories.items()
    ]
    try:
        return question_candidate.build_category_roster(rows)
    except question_candidate.QuestionCandidateError as exc:
        raise CandidatePromotionError(f"category roster is invalid: {exc}") from exc


def _category_facts(question_bank_text: str, category_id: str) -> tuple[dict, dict]:
    category_id = _category_id(category_id)
    roster = _category_roster(question_bank_text)
    category = next(
        (row for row in roster["categories"] if row["category_id"] == category_id),
        None,
    )
    if category is None:
        raise CandidatePromotionError(
            f"category not found in question bank: {category_id}"
        )
    return roster, category


def _placement_revision(candidate_revision: str, category: dict) -> str:
    return question_candidate.canonical_revision(
        {
            "candidate_revision": candidate_revision,
            "category_id": category["category_id"],
            "category_revision": category["category_revision"],
        }
    )


def build_candidate_promotion_request(
    candidate: dict,
    question_bank_text: str,
    category_id: str,
    *,
    proposal: object | None = None,
    decision: dict | None = None,
) -> dict:
    """Build exact promotion facts from current candidate/category authority."""
    anchor, _text = _candidate_facts(candidate)
    roster, category = _category_facts(question_bank_text, category_id)
    if decision is not None:
        try:
            validated = question_candidate.validate_question_candidate_decision(
                decision,
                current_candidate=anchor,
                current_roster=roster,
            )
        except question_candidate.QuestionCandidateError as exc:
            raise CandidatePromotionError(
                f"Question Candidate decision invalid: {exc}"
            ) from exc
        if (
            validated["status"] != "complete"
            or validated["candidate_outcome"] != "answered"
            or validated["answer_status"] != "durable"
            or validated["category_id"] != category["category_id"]
            or not validated["completion"]["complete"]
        ):
            raise CandidatePromotionError(
                "Question Candidate decision is not complete for this category"
            )
    try:
        proposal_revision = (
            question_candidate.canonical_revision(proposal)
            if proposal is not None
            else None
        )
        decision_revision = (
            question_candidate.canonical_revision(decision)
            if decision is not None
            else None
        )
    except (TypeError, ValueError) as exc:
        raise CandidatePromotionError(
            "proposal/decision is not canonical JSON"
        ) from exc
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": anchor["candidate_id"],
        "category_id": category["category_id"],
        "source_revision": anchor["source_revision"],
        "candidate_revision": anchor["candidate_revision"],
        "category_revision": category["category_revision"],
        "placement_revision": _placement_revision(
            anchor["candidate_revision"], category
        ),
        "proposal_revision": proposal_revision,
        "decision_revision": decision_revision,
    }


def validate_candidate_promotion_request(
    request: dict,
    candidate: dict,
    question_bank_text: str,
    *,
    proposal: object | None = None,
    decision: dict | None = None,
) -> dict:
    """Revalidate a closed request against fresh source/category facts."""
    if not isinstance(request, dict) or frozenset(request) != REQUEST_KEYS:
        raise CandidatePromotionError("promotion request keys are invalid")
    if request["schema_version"] != SCHEMA_VERSION:
        raise CandidatePromotionError("promotion request schema_version must be 1")
    candidate_id = _candidate_id(request["candidate_id"])
    category_id = _category_id(request["category_id"])
    normalized = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "category_id": category_id,
        "source_revision": _revision(
            request["source_revision"], name="source_revision"
        ),
        "candidate_revision": _revision(
            request["candidate_revision"], name="candidate_revision"
        ),
        "category_revision": _revision(
            request["category_revision"], name="category_revision"
        ),
        "placement_revision": _revision(
            request["placement_revision"], name="placement_revision"
        ),
        "proposal_revision": _nullable_revision(
            request["proposal_revision"], name="proposal_revision"
        ),
        "decision_revision": _nullable_revision(
            request["decision_revision"], name="decision_revision"
        ),
    }
    if normalized["proposal_revision"] is not None and proposal is None:
        raise CandidatePromotionError(
            "proposal_revision requires the exact bound proposal object"
        )
    if normalized["decision_revision"] is not None and decision is None:
        raise CandidatePromotionError(
            "decision_revision requires the exact bound decision object"
        )
    if normalized["proposal_revision"] is None and proposal is not None:
        raise CandidatePromotionError("proposal object has no bound revision")
    if normalized["decision_revision"] is None and decision is not None:
        raise CandidatePromotionError("decision object has no bound revision")
    current = build_candidate_promotion_request(
        candidate,
        question_bank_text,
        category_id,
        proposal=proposal,
        decision=decision,
    )
    for field in (
        "candidate_id",
        "category_id",
        "source_revision",
        "candidate_revision",
        "category_revision",
        "placement_revision",
    ):
        if normalized[field] != current[field]:
            raise CandidatePromotionError(f"promotion request {field} is stale")
    for field in ("proposal_revision", "decision_revision"):
        if normalized[field] != current[field]:
            raise CandidatePromotionError(f"promotion request {field} is stale")
    return normalized


def request_revision(request: dict) -> str:
    if not isinstance(request, dict) or frozenset(request) != REQUEST_KEYS:
        raise CandidatePromotionError("promotion request keys are invalid")
    return question_candidate.canonical_revision(request)


def _candidate_provenance(request: dict) -> dict:
    return {
        "source_revision": request["source_revision"],
        "candidate_revision": request["candidate_revision"],
        "category_revision": request["category_revision"],
        "placement_revision": request["placement_revision"],
        "proposal_revision": request["proposal_revision"],
        "decision_revision": request["decision_revision"],
        "request_revision": request_revision(request),
    }


def _assert_bound_interaction_objects(
    request: dict,
    *,
    proposal: object | None,
    decision: dict | None,
) -> None:
    for field, value in (
        ("proposal_revision", proposal),
        ("decision_revision", decision),
    ):
        if (
            field == "decision_revision"
            and value is not None
            and not isinstance(value, dict)
        ):
            raise CandidatePromotionError("bound decision must be an object")
        expected = _nullable_revision(request.get(field), name=field)
        if expected is not None and value is None:
            label = field.removesuffix("_revision")
            raise CandidatePromotionError(
                f"{field} requires the exact bound {label} object"
            )
        if expected is None and value is not None:
            raise CandidatePromotionError(
                f"{field.removesuffix('_revision')} object has no bound revision"
            )
        if value is not None:
            try:
                actual = question_candidate.canonical_revision(value)
            except (TypeError, ValueError) as exc:
                raise CandidatePromotionError(
                    f"bound {field.removesuffix('_revision')} is not canonical JSON"
                ) from exc
            if actual != expected:
                raise CandidatePromotionError(f"promotion request {field} is stale")


def _encode_marker(payload: dict) -> str:
    raw = _canonical_json(payload).encode("utf-8")
    return MARKER_PREFIX + base64.b64encode(raw).decode("ascii") + MARKER_SUFFIX


def _decode_marker(line: str) -> dict:
    match = MARKER_RE.fullmatch(line)
    if not match:
        raise CandidatePromotionError("promotion marker syntax is invalid")
    token = match.group(1)
    try:
        raw = base64.b64decode(token, validate=True)
        if len(raw) > 16_384:
            raise CandidatePromotionError("promotion marker is too large")
        decoded = raw.decode("utf-8")
        payload = json.loads(decoded)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidatePromotionError("promotion marker encoding is invalid") from exc
    if base64.b64encode(raw).decode("ascii") != token:
        raise CandidatePromotionError("promotion marker is not canonical base64")
    if _canonical_json(payload) != decoded:
        raise CandidatePromotionError("promotion marker JSON is not canonical")
    return _validate_marker_payload(payload)


def _validate_marker_payload(payload: object) -> dict:
    if not isinstance(payload, dict) or frozenset(payload) != MARKER_KEYS:
        raise CandidatePromotionError("promotion marker keys are invalid")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise CandidatePromotionError("promotion marker schema_version must be 1")
    candidate_id = _candidate_id(payload["candidate_id"])
    category_id = _category_id(payload["category_id"])
    question_id = payload["question_id"]
    if not isinstance(question_id, str) or not QUESTION_ID_RE.fullmatch(question_id):
        raise CandidatePromotionError("promotion marker question_id is invalid")
    if not question_id.startswith(category_id):
        raise CandidatePromotionError("promotion marker category/question mismatch")
    promoted_at = payload["promoted_at"]
    if not isinstance(promoted_at, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", promoted_at
    ):
        raise CandidatePromotionError("promotion marker promoted_at is invalid")
    provenance = payload["candidate_provenance"]
    if not isinstance(provenance, dict) or frozenset(provenance) != PROVENANCE_KEYS:
        raise CandidatePromotionError("candidate_provenance keys are invalid")
    for field in (
        "source_revision",
        "candidate_revision",
        "category_revision",
        "placement_revision",
        "request_revision",
    ):
        _revision(provenance[field], name=f"candidate_provenance.{field}")
    for field in ("proposal_revision", "decision_revision"):
        _nullable_revision(provenance[field], name=f"candidate_provenance.{field}")
    _revision(payload["question_revision"], name="question_revision")
    return {
        **payload,
        "candidate_id": candidate_id,
        "category_id": category_id,
        "candidate_provenance": dict(provenance),
    }


def _marker_records(question_bank_text: str) -> list[tuple[dict, str, str]]:
    lines = question_bank_text.splitlines()
    records: list[tuple[dict, str, str]] = []
    for index, line in enumerate(lines):
        if "lifehug:candidate-promotion:v1" not in line:
            continue
        payload = _decode_marker(line)
        if index == 0:
            raise CandidatePromotionError("promotion marker has no question line")
        question_match = QUESTION_LINE_RE.fullmatch(lines[index - 1])
        if not question_match:
            raise CandidatePromotionError(
                "promotion marker must immediately follow an unchecked question"
            )
        question_id, question_text = question_match.groups()
        if question_id != payload["question_id"]:
            raise CandidatePromotionError("promotion marker question line id mismatch")
        expected = question_candidate.canonical_revision(
            {"question_id": question_id, "question": question_text}
        )
        if expected != payload["question_revision"]:
            raise CandidatePromotionError("promoted question bytes changed")
        records.append((payload, line, question_text))
    seen: set[str] = set()
    for payload, _line, _text in records:
        if payload["candidate_id"] in seen:
            raise CandidatePromotionError(
                f"duplicate promotion markers for {payload['candidate_id']}"
            )
        seen.add(payload["candidate_id"])
    return records


def _marker_for_candidate(
    question_bank_text: str, candidate_id: str
) -> tuple[dict, str, str] | None:
    matches = [
        record
        for record in _marker_records(question_bank_text)
        if record[0]["candidate_id"] == candidate_id
    ]
    return matches[0] if matches else None


def _assert_marker_matches_request(payload: dict, request: dict) -> None:
    expected = _candidate_provenance(request)
    if (
        payload["candidate_id"] != request["candidate_id"]
        or payload["category_id"] != request["category_id"]
        or payload["candidate_provenance"] != expected
    ):
        raise CandidatePromotionError(
            "candidate is already promoted with conflicting provenance"
        )


def _normalize_question(text: str) -> str:
    lowered = text.strip().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", lowered)).strip()


def _next_question_id(question_bank_text: str, category_id: str) -> str:
    numbers = []
    for question in parse_questions(question_bank_text):
        match = re.fullmatch(
            rf"{re.escape(category_id)}(\d+)[a-z]*", str(question["id"])
        )
        if match:
            numbers.append(int(match.group(1)))
    return f"{category_id}{max(numbers, default=0) + 1}"


def _ensure_not_duplicate(question_bank_text: str, question_text: str) -> None:
    wanted = _normalize_question(question_text)
    for question in parse_questions(question_bank_text):
        if _normalize_question(str(question["text"])) == wanted:
            raise CandidatePromotionError(
                f"duplicate question text already exists: {question['id']}"
            )


def _insert_question(
    question_bank_text: str,
    candidate: dict,
    request: dict,
    *,
    promoted_at: str,
) -> tuple[str, dict, str]:
    _roster, _category = _category_facts(question_bank_text, request["category_id"])
    question_text = _candidate_text(candidate)
    _ensure_not_duplicate(question_bank_text, question_text)
    question_id = _next_question_id(question_bank_text, request["category_id"])
    payload = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": request["candidate_id"],
        "category_id": request["category_id"],
        "question_id": question_id,
        "question_revision": question_candidate.canonical_revision(
            {"question_id": question_id, "question": question_text}
        ),
        "promoted_at": promoted_at,
        "candidate_provenance": _candidate_provenance(request),
    }
    marker = _encode_marker(payload)
    pattern = re.compile(
        rf"^(## {re.escape(request['category_id'])}:.+?)(?=\n## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(question_bank_text)
    if not match:
        raise CandidatePromotionError(
            f"category section not found: {request['category_id']}"
        )
    line = f"- [ ] {question_id}: {question_text}\n{marker}"
    prefix = question_bank_text[: match.end()]
    seam = "" if prefix.endswith("\n") else "\n"
    updated = prefix + seam + line + "\n" + question_bank_text[match.end() :]
    return updated, payload, marker


def apply_candidate_promotion(
    data: dict,
    question_bank_text: str,
    request: dict,
    *,
    promotion_mode: str = "manual",
    promoted_at: str | None = None,
    auto_score: float | None = None,
    proposal: object | None = None,
    decision: dict | None = None,
) -> tuple[str, dict]:
    """Pure compatibility planner; all promotion rendering lives here."""
    if promotion_mode not in PROMOTION_MODES:
        raise CandidatePromotionError("promotion_mode is invalid")
    if not isinstance(data, dict) or not isinstance(data.get("candidates"), list):
        raise CandidatePromotionError("candidate store is invalid")
    candidate = next(
        (
            row
            for row in data["candidates"]
            if isinstance(row, dict) and row.get("id") == request.get("candidate_id")
        ),
        None,
    )
    if candidate is None:
        raise CandidatePromotionError(
            f"candidate not found: {request.get('candidate_id')}"
        )
    validate_candidate_promotion_request(
        request,
        candidate,
        question_bank_text,
        proposal=proposal,
        decision=decision,
    )
    status = candidate.get("status", "candidate")
    promotable_statuses = PROMOTABLE_STATUSES_BY_MODE[promotion_mode]
    if status not in promotable_statuses:
        raise CandidatePromotionError(
            f"candidate {request['candidate_id']} cannot be promoted from status {status!r}"
        )
    promoted_at = promoted_at or now_utc()
    updated_bank, payload, _marker = _insert_question(
        question_bank_text, candidate, request, promoted_at=promoted_at
    )
    candidate["status"] = "auto_promoted" if promotion_mode == "auto" else "promoted"
    candidate["target_category"] = request["category_id"]
    candidate["promoted_question_id"] = payload["question_id"]
    candidate["promoted_at"] = promoted_at
    candidate["promotion_request_revision"] = payload["candidate_provenance"][
        "request_revision"
    ]
    candidate["updated_at"] = promoted_at
    if promotion_mode == "auto":
        candidate["promoted_by"] = "auto"
        if auto_score is not None:
            candidate["promotion_score"] = auto_score
            candidate["promotion_reason"] = f"auto: score {auto_score:.2f}"
    data["last_updated"] = promoted_at
    return updated_bank, payload


def _paths(vault_root: str | Path | None) -> tuple[Path, Path, Path]:
    framework_system = resolve_framework_system_dir()
    root = resolve_vault_root(
        vault_root, framework_system_dir=framework_system, bind_process=False
    )
    return (
        root,
        vault_data_path(
            "question_bank", vault_root=root, framework_system_dir=framework_system
        ),
        vault_data_path(
            "question_candidates",
            vault_root=root,
            framework_system_dir=framework_system,
        ),
    )


def _read_store(path: Path, root: Path) -> dict:
    try:
        text = read_vault_text(path, vault_root=root)
    except (FileNotFoundError, json.JSONDecodeError, UnicodeError, ValueError) as exc:
        raise CandidatePromotionError(f"cannot read candidate store: {exc}") from exc
    return _parse_store_text(text)


def _parse_store_text(text: str) -> dict:
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, UnicodeError, ValueError) as exc:
        raise CandidatePromotionError(f"cannot read candidate store: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("candidates"), list):
        raise CandidatePromotionError("candidate store is invalid")
    return value


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise CandidatePromotionError("promotion path escaped vault root") from exc


def _receipt(payload: dict, commit_sha: str, *, changed: bool) -> dict:
    if not COMMIT_RE.fullmatch(commit_sha):
        raise CandidatePromotionError("promotion commit_sha is invalid")
    receipt = {
        "candidate_id": payload["candidate_id"],
        "category_id": payload["category_id"],
        "question_id": payload["question_id"],
        "changed": changed,
        "commit_sha": commit_sha,
        "candidate_provenance": dict(payload["candidate_provenance"]),
    }
    if frozenset(receipt) != RECEIPT_KEYS:
        raise AssertionError("receipt schema drift")
    return receipt


def canonical_receipt_json(receipt: dict) -> str:
    if not isinstance(receipt, dict) or frozenset(receipt) != RECEIPT_KEYS:
        raise CandidatePromotionError("receipt keys are invalid")
    return _canonical_json(receipt)


def parse_question_candidate_bindings(raw: str) -> tuple[object | None, dict | None]:
    """Parse the closed, bounded stdin envelope for hash-bound interaction facts."""
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 1_000_000:
        raise CandidatePromotionError("Question Candidate binding JSON is too large")
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise CandidatePromotionError(
            "Question Candidate binding JSON is invalid"
        ) from exc
    if not isinstance(value, dict) or frozenset(value) != {"proposal", "decision"}:
        raise CandidatePromotionError(
            "Question Candidate binding JSON keys are invalid"
        )
    decision = value["decision"]
    if decision is not None and not isinstance(decision, dict):
        raise CandidatePromotionError("bound decision must be an object or null")
    return value["proposal"], decision


def _resolve_locked(
    request: dict,
    *,
    root: Path,
    bank_path: Path,
    store_path: Path,
    promotion_mode: str,
    push: bool,
    failpoint: Callable[[str], None] | None,
    auto_score: float | None,
    proposal: object | None,
    decision: dict | None,
) -> dict:
    if promotion_mode not in PROMOTION_MODES:
        raise CandidatePromotionError("promotion_mode is invalid")
    bank_relative = _relative(root, bank_path)
    store_relative = _relative(root, store_path)
    intended: dict[str, object] = {}

    def decide(snapshot: exact_file_git.Snapshot) -> exact_file_git.ExactFilePlan:
        bank_text = snapshot[bank_relative]
        existing = _marker_for_candidate(
            bank_text, _candidate_id(request.get("candidate_id"))
        )
        data = _parse_store_text(snapshot[store_relative])
        candidate = next(
            (
                row
                for row in data["candidates"]
                if isinstance(row, dict)
                and row.get("id") == request.get("candidate_id")
            ),
            None,
        )
        if existing is not None:
            payload, marker_line, question_text = existing
            _assert_marker_matches_request(payload, request)
            intended.update(
                payload=payload,
                marker_line=marker_line,
                question_text=question_text,
            )
            if candidate is None:
                return exact_file_git.ExactFilePlan(
                    (),
                    bank_relative,
                    marker_line,
                    f"Adopt candidate {payload['candidate_id']} at {payload['question_id']}",
                )
            validate_candidate_promotion_request(
                request,
                candidate,
                bank_text,
                proposal=proposal,
                decision=decision,
            )
            if _candidate_text(candidate) != question_text:
                raise CandidatePromotionError(
                    "uncommitted promotion marker question differs from candidate"
                )
            status = candidate.get("status")
            if status not in PROMOTABLE_STATUSES_BY_MODE[promotion_mode] | {
                "promoted",
                "auto_promoted",
            }:
                raise CandidatePromotionError(
                    f"candidate projection has conflicting status {status!r}"
                )
            candidate["status"] = (
                "auto_promoted" if promotion_mode == "auto" else "promoted"
            )
            candidate["target_category"] = payload["category_id"]
            candidate["promoted_question_id"] = payload["question_id"]
            candidate["promoted_at"] = payload["promoted_at"]
            candidate["updated_at"] = payload["promoted_at"]
            candidate["promotion_request_revision"] = payload["candidate_provenance"][
                "request_revision"
            ]
            data["last_updated"] = payload["promoted_at"]
            updated_bank = bank_text
        else:
            if candidate is None:
                raise CandidatePromotionError(
                    f"candidate not found: {request.get('candidate_id')}"
                )
            validated = validate_candidate_promotion_request(
                request,
                candidate,
                bank_text,
                proposal=proposal,
                decision=decision,
            )
            updated_bank, payload = apply_candidate_promotion(
                data,
                bank_text,
                validated,
                promotion_mode=promotion_mode,
                auto_score=auto_score,
                proposal=proposal,
                decision=decision,
            )
            marker_line = _encode_marker(payload)
            intended.update(
                payload=payload,
                marker_line=marker_line,
                question_text=_candidate_text(candidate),
            )
        store_text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        return exact_file_git.ExactFilePlan(
            ((bank_relative, updated_bank), (store_relative, store_text)),
            bank_relative,
            marker_line,
            f"Promote candidate {payload['candidate_id']} to {payload['question_id']}",
        )

    def validate(
        snapshot: exact_file_git.Snapshot, plan: exact_file_git.ExactFilePlan
    ) -> None:
        expected_payload = intended.get("payload")
        expected_text = intended.get("question_text")
        expected_marker = intended.get("marker_line")
        if not isinstance(expected_payload, dict) or not isinstance(expected_text, str):
            raise CandidatePromotionError("promotion intended record is unavailable")
        existing = _marker_for_candidate(
            snapshot[bank_relative], _candidate_id(request.get("candidate_id"))
        )
        if existing is None:
            raise CandidatePromotionError("promotion marker changed during rebase")
        payload, marker_line, question_text = existing
        if (
            payload != expected_payload
            or marker_line != expected_marker
            or marker_line != plan.marker_line
            or question_text != expected_text
        ):
            raise CandidatePromotionError(
                "promotion intended record changed during rebase"
            )
        _assert_marker_matches_request(payload, request)
        # Revalidate source, candidate text, category, placement, proposal, and
        # decision facts whenever the repairable projection still has the row.
        data = _parse_store_text(snapshot[store_relative])
        candidates = data["candidates"]
        candidate = next(
            (
                row
                for row in candidates
                if isinstance(row, dict)
                and row.get("id") == request.get("candidate_id")
            ),
            None,
        )
        if candidate is not None:
            validate_candidate_promotion_request(
                request,
                candidate,
                snapshot[bank_relative],
                proposal=proposal,
                decision=decision,
            )
            if _candidate_text(candidate) != expected_text:
                raise CandidatePromotionError(
                    "promotion candidate question changed during rebase"
                )

    def transaction_failpoint(stage: str) -> None:
        if not failpoint:
            return
        translated = {
            f"after_write:{bank_relative}": "after_bank_write",
            f"after_write:{store_relative}": "after_projection_write",
        }.get(stage, stage)
        failpoint(translated)

    try:
        result = exact_file_git.resolve_exact_file_transaction(
            vault_root=root,
            declared_paths=(bank_relative, store_relative),
            decide=decide,
            validate=validate,
            push=push,
            failpoint=transaction_failpoint,
        )
    except exact_file_git.ExactFileTransactionError as exc:
        raise CandidatePromotionError(str(exc)) from exc
    payload = intended.get("payload")
    if not isinstance(payload, dict):
        raise CandidatePromotionError("promotion intended record is unavailable")
    return _receipt(payload, result.commit_sha, changed=result.changed)


def resolve_candidate_promotion(
    request: dict,
    *,
    vault_root: str | Path | None = None,
    promotion_mode: str = "manual",
    push: bool = True,
    failpoint: Callable[[str], None] | None = None,
    auto_score: float | None = None,
    proposal: object | None = None,
    decision: dict | None = None,
) -> dict:
    """Resolve, commit, optionally push, and return an idempotent receipt."""
    if not isinstance(request, dict) or frozenset(request) != REQUEST_KEYS:
        raise CandidatePromotionError("promotion request keys are invalid")
    _assert_bound_interaction_objects(request, proposal=proposal, decision=decision)
    root, bank_path, store_path = _paths(vault_root)
    return _resolve_locked(
        dict(request),
        root=root,
        bank_path=bank_path,
        store_path=store_path,
        promotion_mode=promotion_mode,
        push=push,
        failpoint=failpoint,
        auto_score=auto_score,
        proposal=proposal,
        decision=decision,
    )


def resolve_candidate_promotions(
    requests: list[dict],
    *,
    vault_root: str | Path | None = None,
    promotion_mode: str = "neighborhood",
    push: bool = True,
) -> list[dict]:
    if not isinstance(requests, list):
        raise CandidatePromotionError("requests must be a list")
    return [
        resolve_candidate_promotion(
            request,
            vault_root=vault_root,
            promotion_mode=promotion_mode,
            push=push,
        )
        for request in requests
    ]


def build_current_request(
    candidate_id: str,
    category_id: str,
    *,
    vault_root: str | Path | None = None,
    proposal: object | None = None,
    decision: dict | None = None,
) -> dict:
    root, bank_path, store_path = _paths(vault_root)
    bank = read_vault_text(bank_path, vault_root=root)
    data = _read_store(store_path, root)
    candidate = next(
        (
            row
            for row in data["candidates"]
            if isinstance(row, dict) and row.get("id") == candidate_id
        ),
        None,
    )
    if candidate is None:
        raise CandidatePromotionError(f"candidate not found: {candidate_id}")
    return build_candidate_promotion_request(
        candidate,
        bank,
        category_id,
        proposal=proposal,
        decision=decision,
    )


def build_revision_bound_request(
    candidate_id: str,
    category_id: str,
    *,
    candidate_revision: str,
    category_revision: str,
    placement_revision: str,
    source_revision: str | None = None,
    proposal_revision: str | None = None,
    decision_revision: str | None = None,
    proposal: object | None = None,
    decision: dict | None = None,
    vault_root: str | Path | None = None,
) -> dict:
    """Build the stable CLI request while rejecting stale caller-held facts."""
    if proposal_revision is not None and proposal is None:
        raise CandidatePromotionError(
            "proposal_revision requires the exact bound proposal object"
        )
    if decision_revision is not None and decision is None:
        raise CandidatePromotionError(
            "decision_revision requires the exact bound decision object"
        )
    request = build_current_request(
        candidate_id,
        category_id,
        vault_root=vault_root,
        proposal=proposal,
        decision=decision,
    )
    supplied = {
        "candidate_revision": _revision(candidate_revision, name="candidate_revision"),
        "category_revision": _revision(category_revision, name="category_revision"),
        "placement_revision": _revision(placement_revision, name="placement_revision"),
    }
    if source_revision is not None:
        supplied["source_revision"] = _revision(source_revision, name="source_revision")
    for field, value in supplied.items():
        if request[field] != value:
            raise CandidatePromotionError(f"promotion request {field} is stale")
    supplied_bindings = {
        "proposal_revision": _nullable_revision(
            proposal_revision, name="proposal_revision"
        ),
        "decision_revision": _nullable_revision(
            decision_revision, name="decision_revision"
        ),
    }
    for field, value in supplied_bindings.items():
        if request[field] != value:
            raise CandidatePromotionError(f"promotion request {field} is stale")
    return request


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate_id")
    parser.add_argument("--category", required=True)
    parser.add_argument("--vault-root")
    parser.add_argument("--no-push", action="store_true")
    parser.add_argument("--json", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        request = build_current_request(
            args.candidate_id, args.category, vault_root=args.vault_root
        )
        receipt = resolve_candidate_promotion(
            request,
            vault_root=args.vault_root,
            push=not args.no_push,
        )
    except CandidatePromotionError as exc:
        print(f"candidate-promotion: {exc}", file=sys.stderr)
        return 2
    print(canonical_receipt_json(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
