#!/usr/bin/env python3
"""Lifehug — Question-Judgment interaction loader.

The single authoritative definition (recurring-defect doctrine,
``docs/BUILDING.md`` §8) for assembling the judgment context every
question-generation path sends to a model:
``interactions/question_judgment/prompt/behavior.md`` (the rubric — never
truncated) plus this vault's ``state/question_judgment/learned.md`` (vault
data, empty when absent).

``system/classify_story.py``'s ``build_prompt`` and
``system/research_expand.py``'s expansion prompt path both call
``load_judgment_rubric()`` instead of hand-reading ``system/research.md``
and slicing it — the ``research[:3000]`` / ``research_notes[:800]``
truncations that used to sit between those two generation paths and the
craft doctrine are gone (``docs/pr-specs/question-judgment-interaction.md``).

Public API:

    load_judgment_rubric(*, vault_root=None, framework_root=None) -> str
    read_judgment_definition(*parts, framework_root=None) -> str
    build_decision_context(limit=15, *, path=None) -> str
    owner_judgment_signals_block(decision_context, *, heading=...) -> str
    run_weekly_edit(...) -> dict

Graceful degradation: when ``interactions/question_judgment/`` itself is
absent, or its ``prompt/behavior.md`` can't be read (a vault running
against a framework snapshot that predates this interaction — see the
contract's binding facts), the loader falls back to the PRE-MIGRATION
behavior: read ``system/research.md`` and truncate to 3000 characters,
exactly as the old ``classify_story.build_prompt`` did. This is an
intentional, temporary compatibility shim for a vault mid-upgrade, not a
re-introduction of the truncation bug — a vault on-version (the normal
case, since this interaction ships in ``system/version.json``'s
``framework_files``) never takes this path.

Every vault read goes through ``vault_paths`` (never a hand-built path);
every framework read goes through ``lifehug_core.INTERACTIONS_DIR`` /
an explicit ``framework_root`` override, the same convention
``system/conversation.py``'s ``_conversation_dir_path`` uses.

decisions-feed-the-loop (docs/pr-specs/decisions-feed-the-loop.md, ADR
0009) adds the second half of ADR 0007's declared-but-unwired
RUBRIC-EDIT mode: ``build_decision_context()`` assembles the "Owner
Judgment Signals" block both generation prompts inject (the Convergence
Principle's accelerator, ADR 0006), and ``run_weekly_edit()`` is the
runtime that actually invokes ``role.planner`` and writes AT MOST one
bounded, evidence-cited amendment to ``state/question_judgment/learned.md``
per run — never a rewrite, never a deterministic invention of an
amendment when no model is available (keyless machines emit a task
instead, the same ``--emit-task``/``--from-response`` convention
``system/entity_roster.py`` uses).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from lifehug_core import (
    INTERACTIONS_DIR,
    QUESTION_JUDGMENT_LEARNED_FILE,
    QUESTION_JUDGMENT_STATE_DIR,
    REPO_DIR,
    SYSTEM_DIR,
    now_utc,
    read_json,
    read_text,
    write_json,
    write_text,
)
from vault_paths import read_vault_text, vault_data_path

INTERACTION_NAME = "question_judgment"

# Pre-migration fallback constant, preserved verbatim from the old
# classify_story.build_prompt truncation so a mid-upgrade vault's behavior
# doesn't silently change out from under it. See module docstring.
LEGACY_RESEARCH_CHAR_LIMIT = 3000

# --- decisions-feed-the-loop additions --------------------------------

# state/question_judgment/ is one contracted directory (vault_contract.json's
# question_judgment_state entry) holding learned.md (question_judgment_learned,
# unchanged from #145) plus this PR's cursor file — both vault data, never
# framework files (contract's Scope 7 / Implementation notes).
LEARNED_FILE = QUESTION_JUDGMENT_LEARNED_FILE
CURSOR_FILE = QUESTION_JUDGMENT_STATE_DIR / "last_edit.json"

# role.planner: high capability tier (ADR 0007c) — mirrors the other
# high-tier defaults (research_model/wiki_model) in config.yaml.example.
# Override with judgment_edit_model in config.yaml.
DEFAULT_MODEL = "claude-opus-4-8"

# Fallbacks when interaction.yaml can't be read (mirrors interaction.yaml's
# own knob defaults, so a mid-upgrade vault degrades gracefully instead of
# raising).
WEEKLY_EDIT_MAX_CHARS_DEFAULT = 600
LEARNED_MAX_CHARS_DEFAULT = 8000

# Reserved budget for the compaction marker line itself when trimming
# state/question_judgment/learned.md back under knob.learned_max_chars.
_COMPACTION_RESERVE = 200

# Decision statuses the delta/context assembly reads, human-only —
# "auto_promoted" is a DIFFERENT status value (see auto_promote_candidates())
# and is excluded by construction, never by an extra filter.
_DECISION_LABELS = {"rejected": "DISMISSED", "deferred": "DEFERRED", "promoted": "PROMOTED"}

_ENTRY_HEADING_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})(?:\s*\(.*?\))?\s*$", re.MULTILINE)


def _definition_dir(*, framework_root: str | Path | None = None) -> Path:
    if framework_root is not None:
        return Path(framework_root) / "interactions" / INTERACTION_NAME
    return INTERACTIONS_DIR / INTERACTION_NAME


def read_judgment_definition(*parts: str, framework_root: str | Path | None = None) -> str:
    """Read one ``interactions/question_judgment/`` definition file verbatim.

    Raises OSError when the file is absent — the definition tree is a
    framework file, not optional vault state.
    """
    return _definition_dir(framework_root=framework_root).joinpath(*parts).read_text(encoding="utf-8")


def _legacy_research_path(*, framework_root: str | Path | None = None) -> Path:
    if framework_root is not None:
        return Path(framework_root) / "system" / "research.md"
    return SYSTEM_DIR / "research.md"


def _legacy_fallback(*, framework_root: str | Path | None = None) -> str:
    """Pre-migration behavior: system/research.md truncated to 3000 chars.

    Only reachable when interactions/question_judgment/'s behavior.md
    can't be read (a vault mid-upgrade). See module docstring.
    """
    path = _legacy_research_path(framework_root=framework_root)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")[:LEGACY_RESEARCH_CHAR_LIMIT]


def _load_learned(*, vault_root: str | Path | None = None, framework_root: str | Path | None = None) -> str:
    root = REPO_DIR if vault_root is None else Path(vault_root)
    framework_system_dir = Path(framework_root) / "system" if framework_root is not None else SYSTEM_DIR
    try:
        path = vault_data_path(
            "question_judgment_learned",
            vault_root=root,
            framework_system_dir=framework_system_dir,
        )
    except KeyError:
        # The data path isn't registered (e.g. an old vault_contract.json
        # snapshot mid-upgrade) — treat exactly like a missing file.
        return ""
    try:
        return read_vault_text(path, vault_root=root)
    except FileNotFoundError:
        return ""


def load_judgment_rubric(*, vault_root: str | Path | None = None, framework_root: str | Path | None = None) -> str:
    """Assemble the judgment context every generation path sends a model.

    ``prompt/behavior.md`` (never truncated) plus
    ``state/question_judgment/learned.md`` (empty when absent, appended
    under its own heading when present). Falls back to the pre-migration
    truncated ``research.md`` injection only when the interaction
    definition itself can't be read — see the module docstring.
    """
    try:
        behavior = read_judgment_definition("prompt", "behavior.md", framework_root=framework_root)
    except OSError:
        return _legacy_fallback(framework_root=framework_root)

    parts = [behavior.strip()]
    learned = _load_learned(vault_root=vault_root, framework_root=framework_root).strip()
    if learned:
        parts.append("## Learned amendments\n\n" + learned)
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Owner Judgment Signals — the decision context both generation prompts
# inject (contract Scope 2).
# ---------------------------------------------------------------------------

def _decided_rows(*, path: Path | None = None) -> list[dict]:
    """Human decisions (rejected/deferred/promoted), newest-updated first.
    Reuses question_candidates.load_store() — one candidate-store reader,
    not a re-derived path (recurring-defect doctrine)."""
    from question_candidates import load_store  # noqa: PLC0415 — avoid a hard import cycle at module load

    data = load_store(path) if path is not None else load_store()
    rows = [c for c in data.get("candidates", []) if c.get("status") in _DECISION_LABELS]
    rows.sort(key=lambda c: str(c.get("updated_at") or ""), reverse=True)
    return rows


def _format_decision_lines(rows: list[dict]) -> str:
    lines = []
    for c in rows:
        label = _DECISION_LABELS.get(c.get("status"), str(c.get("status") or "").upper())
        text = str(c.get("text", "")).strip()
        if len(text) > 120:
            text = text[:117] + "..."
        note = str(c.get("decision_reason") or "").strip()
        if not note:
            promoted_by = c.get("promoted_by")
            note = f"promoted_by: {promoted_by}" if promoted_by else "no reason given"
        lines.append(f'{label} "{text}" — {note}')
    return "\n".join(lines)


def build_decision_context(limit: int | None = 15, *, path: Path | None = None) -> str:
    """Compact lines for the most recent owner decisions, newest first,
    human-only (auto_promoted excluded). Empty history returns "" — callers
    (owner_judgment_signals_block, both generation prompts) must omit the
    block entirely rather than emit an empty heading."""
    rows = _decided_rows(path=path)
    if limit is not None:
        rows = rows[:limit]
    return _format_decision_lines(rows) if rows else ""


def owner_judgment_signals_block(decision_context: str, *, heading: str = "## Owner Judgment Signals") -> str:
    """Render the prompt block both classify_story.build_prompt and
    research_expand.build_expansion_prompt inject — one definition, used by
    both generation paths, so the instruction line can never drift between
    them (recurring-defect doctrine). "" when there's no decision history
    yet — the block is omitted entirely, never an empty heading."""
    if not decision_context.strip():
        return ""
    return (
        f"{heading}\n"
        f"{decision_context.strip()}\n\n"
        "Candidates matching the PATTERN of these recent dismissals must not "
        "be re-proposed — this is guidance about the pattern, not a literal "
        "blocklist of the exact questions above."
    )


# ---------------------------------------------------------------------------
# interaction.yaml knobs (weekly_edit_max_chars, learned_max_chars) —
# read at runtime, cast numeric, degrade to the defaults above on any read
# failure (mirrors system/conversation.py's load_interaction_manifest).
# ---------------------------------------------------------------------------

def _cast_numeric(value: str) -> object:
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def load_interaction_manifest(*, framework_root: str | Path | None = None) -> dict:
    """Parse interaction.yaml's flat scalar subset; cast knob.*/budget.* numerics."""
    from lifehug_core import _parse_simple_yaml  # noqa: PLC0415

    path = _definition_dir(framework_root=framework_root) / "interaction.yaml"
    raw = _parse_simple_yaml(path)
    manifest: dict[str, object] = {}
    for key, value in raw.items():
        manifest[key] = _cast_numeric(value) if key.startswith(("knob.", "budget.")) else value
    return manifest


def _safe_manifest(*, framework_root: str | Path | None = None) -> dict:
    try:
        return load_interaction_manifest(framework_root=framework_root)
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------------------
# The weekly RUBRIC-EDIT runtime (contract Scope 3) — the accelerator half
# of the Convergence Principle (ADR 0006) for this interaction (ADR 0007c).
# ---------------------------------------------------------------------------

def _load_cursor(*, path: Path | None = None) -> dict:
    data = read_json(path or CURSOR_FILE, default=None)
    if not isinstance(data, dict):
        data = {}
    data.setdefault("version", 1)
    data.setdefault("last_edit_at", None)
    data.setdefault("last_run_at", None)
    data.setdefault("last_seen_at", None)
    data.setdefault("counts", {})
    data.setdefault("quality_profile_snapshot", {})
    return data


def _snapshot_multipliers(quality_profile: dict | None) -> dict:
    if not quality_profile or not quality_profile.get("active"):
        return {}
    by_fn = quality_profile.get("by_story_function") or {}
    if not isinstance(by_fn, dict):
        return {}
    out = {}
    for fn, data in by_fn.items():
        if isinstance(data, dict) and "multiplier" in data:
            try:
                out[fn] = float(data["multiplier"])
            except (TypeError, ValueError):
                continue
    return out


def _bucket_movements(quality_profile: dict | None, previous_snapshot: dict) -> list[str]:
    current = _snapshot_multipliers(quality_profile)
    lines = []
    for fn in sorted(set(current) | set(previous_snapshot or {})):
        old = (previous_snapshot or {}).get(fn)
        new = current.get(fn)
        if old is None or new is None or abs(old - new) < 0.01:
            continue
        lines.append(f"{fn}: {old:.2f} → {new:.2f} ({new - old:+.2f})")
    return lines


def _load_quality_profile_safely() -> dict | None:
    try:
        from quality_profile import load_profile  # noqa: PLC0415
        return load_profile()
    except Exception as exc:  # noqa: BLE001
        from lifehug_core import record_learning_failure  # noqa: PLC0415
        record_learning_failure("question_judgment", "load_quality_profile", exc)
        return None


def _decisions_since(last_seen_at: str | None, *, path: Path | None = None, cap: int = 50) -> list[dict]:
    rows = _decided_rows(path=path)
    if last_seen_at:
        rows = [c for c in rows if str(c.get("updated_at") or "") > last_seen_at]
    return rows[:cap]


def _format_week_delta(decisions: list[dict], bucket_moves: list[str]) -> str:
    parts = []
    if decisions:
        parts.append(f"Decisions since last edit ({len(decisions)}):")
        parts.append(_format_decision_lines(decisions))
    else:
        parts.append("Decisions since last edit: none.")
    if bucket_moves:
        parts.append("")
        parts.append("Quality-profile bucket movements since last edit:")
        parts.extend(bucket_moves)
    return "\n".join(parts)


def _format_full_ledger(decisions: list[dict]) -> str:
    if not decisions:
        return "Full decision ledger: no human decisions recorded yet."
    return f"Full decision ledger ({len(decisions)} decisions):\n" + _format_decision_lines(decisions)


def _split_learned_entries(text: str) -> list[tuple[str, str]]:
    """[(date, full_entry_text_including_heading), ...] in file order
    (oldest first — entries are always appended at the end)."""
    if not text.strip():
        return []
    matches = list(_ENTRY_HEADING_RE.finditer(text))
    entries = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        entries.append((m.group(1), text[start:end].rstrip("\n") + "\n"))
    return entries


def _distill_prior_amendments(learned_text: str, max_entries: int = 10) -> str:
    """A short summary of already-made amendments (turn-instructions.md's
    {distilled_prior_amendments}), distinct from {current_learned_file}
    (the verbatim file) — one bullet per recent dated entry."""
    entries = _split_learned_entries(learned_text)
    if not entries:
        return "No prior amendments yet."
    lines = []
    for date, block in entries[-max_entries:]:
        body_lines = [ln.strip() for ln in block.splitlines()[1:] if ln.strip()]
        gist = body_lines[0] if body_lines else ""
        if len(gist) > 140:
            gist = gist[:137] + "..."
        lines.append(f"- {date}: {gist}")
    return "\n".join(lines)


def _compact_learned(text: str, max_chars: int) -> str:
    """Drop the oldest dated entries and write ONE bare compaction marker
    in their place when the file exceeds knob.learned_max_chars. The
    marker never tries to summarize what was folded — the rubric-edit
    prompt is told to fold going forward (contract Scope 3), the code
    only ever mechanically drops."""
    if len(text) <= max_chars:
        return text
    entries = _split_learned_entries(text)
    if not entries:
        return text  # unstructured content — leave it alone rather than mangle it
    kept: list[tuple[str, str]] = []
    total = 0
    for date, block in reversed(entries):  # newest first
        if kept and total + len(block) > max_chars - _COMPACTION_RESERVE:
            break
        kept.insert(0, (date, block))
        total += len(block)
    dropped = len(entries) - len(kept)
    if dropped <= 0:
        return text
    today = now_utc()[:10]
    plural = "s" if dropped != 1 else ""
    marker = f"## {today} (compacted {today}: {dropped} earlier amendment{plural} folded)\n"
    body = "\n".join(block for _date, block in kept)
    return f"{marker}\n{body}" if body else marker


def _rubric_edit_template(*, framework_root: str | Path | None = None) -> str:
    full = read_judgment_definition("prompt", "turn-instructions.md", framework_root=framework_root)
    marker = "## Mode: RUBRIC-EDIT"
    idx = full.index(marker)
    return full[idx:].strip()


def _build_rubric_edit_prompt(
    week_delta_summary: str,
    distilled_prior_amendments: str,
    current_learned_file: str,
    *,
    framework_root: str | Path | None = None,
) -> str:
    """Assemble the RUBRIC-EDIT call: identity -> behavior -> examples ->
    the RUBRIC-EDIT turn-instructions template with its {placeholder}s
    filled (context/manifest.md's assembly order; turn-instructions.md's
    own {current_learned_file} input carries the learned-file content, so
    it is not ALSO prepended as a separate manifest "learned" block)."""
    identity = read_judgment_definition("prompt", "identity.md", framework_root=framework_root)
    behavior = read_judgment_definition("prompt", "behavior.md", framework_root=framework_root)
    try:
        examples = read_judgment_definition("prompt", "examples.md", framework_root=framework_root)
    except OSError:
        examples = ""
    template = _rubric_edit_template(framework_root=framework_root)
    filled = (
        template
        .replace("{week_delta_summary}", week_delta_summary or "(none)")
        .replace("{distilled_prior_amendments}", distilled_prior_amendments or "(none)")
        .replace("{current_learned_file}", current_learned_file or "(empty)")
    )
    parts = [identity.strip(), behavior.strip()]
    if examples.strip():
        parts.append(examples.strip())
    parts.append(filled)
    return "\n\n".join(parts)


def _write_task(
    path: Path,
    *,
    prompt: str,
    week_delta_summary: str,
    distilled_prior_amendments: str,
    current_learned_file: str,
    recalibrate: bool,
) -> None:
    """Keyless emit-task convention (same shape as system/entity_roster.py's
    --emit-task): prompt + context + a response_format hint."""
    payload = {
        "type": "question_judgment_rubric_edit",
        "mode": "recalibrate" if recalibrate else "weekly",
        "prompt": prompt,
        "week_delta_summary": week_delta_summary,
        "distilled_prior_amendments": distilled_prior_amendments,
        "current_learned_file": current_learned_file,
        "response_format": {"amendment": None, "evidence": None, "char_count": None},
    }
    write_text(Path(path), json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def _apply_response(
    raw_response: str,
    *,
    max_edit_chars: int,
    max_file_chars: int,
    learned_path: Path | None = None,
) -> dict:
    """Parse + apply one RUBRIC-EDIT response. Raises ValueError on any
    malformed/over-budget response — the caller must never silently
    truncate or invent a fallback amendment (contract Scope 3)."""
    from research_expand import parse_ai_json  # noqa: PLC0415 — avoid the classify_story/research_expand import cycle

    data = parse_ai_json(raw_response)
    amendment = data.get("amendment")
    if amendment is None or (isinstance(amendment, str) and not amendment.strip()):
        reason = str(data.get("reason", "")).strip()
        return {"status": "no_change", "amended": False, "reason": reason or "model declined to amend"}

    amendment_text = str(amendment).strip()
    evidence = str(data.get("evidence", "")).strip()
    if not evidence:
        raise ValueError("rubric-edit response has an amendment but no evidence line")
    if len(amendment_text) > max_edit_chars:
        raise ValueError(
            f"rubric-edit amendment exceeds knob.weekly_edit_max_chars "
            f"({len(amendment_text)} > {max_edit_chars} chars)"
        )

    date = now_utc()[:10]
    path = learned_path or LEARNED_FILE
    try:
        existing = read_text(path)
    except FileNotFoundError:
        existing = ""
    separator = "\n" if existing.strip() else ""
    entry = f"{separator}## {date}\n\n{amendment_text}\n\nEvidence: {evidence}\n"
    updated = _compact_learned(existing + entry, max_file_chars)
    write_text(path, updated)
    return {"status": "amended", "amended": True, "date": date, "amendment": amendment_text, "evidence": evidence}


def _advance_cursor(
    cursor: dict,
    *,
    decisions: list[dict],
    quality_profile: dict | None,
    amended: bool,
    path: Path | None = None,
) -> dict:
    now = now_utc()
    counts = dict(cursor.get("counts") or {})
    counts["runs"] = int(counts.get("runs", 0)) + 1
    counts["decisions_seen"] = int(counts.get("decisions_seen", 0)) + len(decisions)
    if amended:
        counts["amendments"] = int(counts.get("amendments", 0)) + 1
    new_cursor = {
        "version": 1,
        "last_edit_at": now if amended else cursor.get("last_edit_at"),
        "last_run_at": now,
        "last_seen_at": now,
        "counts": counts,
        "quality_profile_snapshot": _snapshot_multipliers(quality_profile),
    }
    write_json(path or CURSOR_FILE, new_cursor)
    return new_cursor


def _resolve_model(explicit: str | None) -> str:
    if explicit:
        return explicit
    from lifehug_core import load_config  # noqa: PLC0415
    return str(load_config().get("judgment_edit_model", DEFAULT_MODEL))


def run_weekly_edit(
    *,
    dry_run: bool = False,
    emit_task: str | Path | None = None,
    from_response: str | Path | None = None,
    recalibrate: bool = False,
    model: str | None = None,
    candidates_path: Path | None = None,
    cursor_path: Path | None = None,
    learned_path: Path | None = None,
    max_edit_chars: int | None = None,
    max_file_chars: int | None = None,
    framework_root: str | Path | None = None,
) -> dict:
    """The weekly RUBRIC-EDIT runtime (ADR 0007c/0009): at most ONE bounded,
    evidence-cited amendment to state/question_judgment/learned.md per run.

    Single-writer discipline: like every other weekly_maintenance.sh
    learning step, this writes vault state directly — the whole weekly run
    is already serialized through jobs.py's single-writer worker (see
    system/jobs.py's module docstring; weekly_maintenance.sh re-execs
    itself through `jobs.py enqueue weekly --wait` before any step runs),
    so no additional per-step locking is needed here, mirroring how
    quality_profile.save_profile() writes directly.
    """
    manifest = _safe_manifest(framework_root=framework_root)
    if max_edit_chars is None:
        max_edit_chars = int(manifest.get("knob.weekly_edit_max_chars", WEEKLY_EDIT_MAX_CHARS_DEFAULT) or WEEKLY_EDIT_MAX_CHARS_DEFAULT)
    if max_file_chars is None:
        max_file_chars = int(manifest.get("knob.learned_max_chars", LEARNED_MAX_CHARS_DEFAULT) or LEARNED_MAX_CHARS_DEFAULT)

    cursor = _load_cursor(path=cursor_path)
    quality_profile = _load_quality_profile_safely()

    if recalibrate:
        decisions = _decided_rows(path=candidates_path)
        bucket_moves: list[str] = []
        week_delta_summary = _format_full_ledger(decisions)
    else:
        decisions = _decisions_since(cursor.get("last_seen_at"), path=candidates_path)
        bucket_moves = _bucket_movements(quality_profile, cursor.get("quality_profile_snapshot") or {})
        week_delta_summary = _format_week_delta(decisions, bucket_moves)

    try:
        current_learned = read_text(learned_path or LEARNED_FILE)
    except FileNotFoundError:
        current_learned = ""
    distilled = _distill_prior_amendments(current_learned)

    prompt = _build_rubric_edit_prompt(
        week_delta_summary, distilled, current_learned, framework_root=framework_root,
    )

    result: dict = {
        "mode": "recalibrate" if recalibrate else "weekly",
        "delta": week_delta_summary,
        "distilled_prior_amendments": distilled,
        "decisions_count": len(decisions),
    }

    if dry_run:
        result.update({"status": "dry_run", "prompt": prompt})
        return result

    is_empty_delta = not recalibrate and not decisions and not bucket_moves
    if is_empty_delta:
        cursor = _advance_cursor(cursor, decisions=decisions, quality_profile=quality_profile,
                                 amended=False, path=cursor_path)
        result.update({
            "status": "no_change",
            "reason": "empty delta — nothing new since the last edit",
            "cursor": cursor,
        })
        return result

    if emit_task:
        _write_task(
            Path(emit_task), prompt=prompt, week_delta_summary=week_delta_summary,
            distilled_prior_amendments=distilled, current_learned_file=current_learned,
            recalibrate=recalibrate,
        )
        result.update({"status": "emitted_task", "task_path": str(emit_task), "prompt": prompt})
        return result

    if from_response:
        raw_response = Path(from_response).read_text(encoding="utf-8", errors="replace")
    else:
        from ai_provider import call_ai  # noqa: PLC0415
        model_name = _resolve_model(model)
        try:
            raw_response = call_ai(prompt, model_name)
        except Exception as exc:  # noqa: BLE001
            from ai_provider import failure_metadata  # noqa: PLC0415
            result.update({"status": "failed", "error": failure_metadata("judgment-rubric-edit", exc, provider="ai")})
            return result

    try:
        applied = _apply_response(
            raw_response, max_edit_chars=max_edit_chars, max_file_chars=max_file_chars,
            learned_path=learned_path,
        )
    except Exception as exc:  # noqa: BLE001
        result.update({"status": "invalid_response", "error": str(exc)[:500]})
        return result

    cursor = _advance_cursor(
        cursor, decisions=decisions, quality_profile=quality_profile,
        amended=applied.get("amended", False), path=cursor_path,
    )
    result.update(applied)
    result["cursor"] = cursor
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print the assembled question-judgment context, or run the weekly RUBRIC-EDIT.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview the weekly rubric-edit delta and prompt without writing")
    parser.add_argument("--emit-task", metavar="PATH",
                        help="Keyless: emit the rubric-edit prompt for agent completion")
    parser.add_argument("--from-response", metavar="PATH",
                        help="Apply an agent-written rubric-edit response (no model call)")
    parser.add_argument("--recalibrate", action="store_true",
                        help="Full decision-ledger context instead of the weekly delta (quarterly, manual only)")
    parser.add_argument("--model", help="AI model override for the rubric-edit call")
    args = parser.parse_args()

    if not (args.dry_run or args.emit_task or args.from_response or args.recalibrate):
        print(load_judgment_rubric())
        return 0

    result = run_weekly_edit(
        dry_run=args.dry_run,
        emit_task=args.emit_task,
        from_response=args.from_response,
        recalibrate=args.recalibrate,
        model=args.model,
    )
    status = result.get("status", "unknown")
    prefix = "[RECALIBRATE] " if args.recalibrate else ""

    if status == "dry_run":
        print(f"{prefix}[DRY RUN] judgment-update ({result['mode']})")
        print()
        print("--- DELTA ---")
        print(result["delta"])
        print()
        print("--- PROMPT ---")
        print(result["prompt"])
        return 0
    if status == "no_change":
        print(f"{prefix}✓ judgment-update: no change — {result.get('reason', '')}")
        return 0
    if status == "emitted_task":
        print(f"{prefix}✓ Emitted rubric-edit task to {result['task_path']}")
        recal_flag = " --recalibrate" if args.recalibrate else ""
        print(f"  Complete it, then: python3 system/question_judgment.py --from-response <file>{recal_flag}")
        return 0
    if status == "amended":
        print(f"{prefix}✓ judgment-update: amended learned.md ({result['date']}) — {len(result['amendment'])} chars")
        print(f"  evidence: {result['evidence']}")
        return 0
    if status == "failed":
        print(f"{prefix}✗ judgment-update failed: {result.get('error')}", file=sys.stderr)
        return 1
    if status == "invalid_response":
        print(f"{prefix}✗ judgment-update: invalid rubric-edit response: {result.get('error')}", file=sys.stderr)
        return 1
    print(f"{prefix}✗ judgment-update: unknown status {status!r}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
