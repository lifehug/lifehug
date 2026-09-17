#!/usr/bin/env python3
"""Classify ingested Lifehug stories using the shared AI provider.

Extracts entities, themes, story functions, and generates smart
candidate questions from any source file or answer file.

Modes
-----
--classify <source_path>          Classify a single file via AI.
--prompt <source_path>            Print the prompt only (no API call).
--classify-all [--unclassified]   Batch classify all (or only unclassified) sources.
--stale-first                     With --classify-all: stale targets first, then
                                  newest-first, resuming after the durable cursor.
--dry-run                         Preview actions without model calls or writes.

Examples
--------
python3 system/classify_story.py --classify sources/manual/arizona.md
python3 system/classify_story.py --prompt sources/manual/arizona.md
python3 system/classify_story.py --classify-all --unclassified
python3 system/classify_story.py --classify-all --unclassified --stale-first --limit 5
python3 system/classify_story.py --classify-all --unclassified --dry-run
python3 system/classify_story.py --classify sources/manual/arizona.md --model claude-opus-4-20250514
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Iterator
from pathlib import Path

# ── path bootstrapping so the script is importable from anywhere ──────────────
SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))
LEGACY_FOCUS_KEY = "spot" "light_opportunities"

from ai_provider import AIResponseError, failure_metadata, normalize_question_records
import classifier_context as classifier_ctx
import timeline_evidence

from lifehug_core import (
    ANSWERS_DIR,
    CLASSIFICATION_BATCHES_DIR,
    CLASSIFICATIONS_DIR,
    CLASSIFY_CURSOR_FILE,
    DEFAULT_CORRECTION_ROLE,
    MANUAL_SOURCES_DIR,
    MISSION_FILE,
    QUESTION_CANDIDATES_FILE,
    QUESTIONS_FILE,
    REPO_DIR,
    SOURCES_DIR,
    STORY_FUNCTIONS,
    answer_body,
    correction_role_marks_stale,
    load_config,
    load_mission,
    now_utc,
    parse_categories,
    parse_questions,
    read_json,
    skip_leading_frontmatter_blocks,
    slugify,
    write_json,
    write_text,
)
from question_judgment import build_decision_context, load_judgment_rubric, owner_judgment_signals_block
from vault_paths import atomic_write_vault_text, read_vault_text

# ── constants ─────────────────────────────────────────────────────────────────
# Non-dated alias — tracks the current Sonnet tier instead of pinning a
# snapshot that ages out. Override with `classify_model` in config.yaml.
# claude-sonnet-5 is the current active Sonnet per Anthropic's model catalog;
# a 2026-07-05 report of it 404ing could not be reproduced and is believed
# misdiagnosed — if it recurs on an instance, set `classify_model:
# claude-sonnet-4-6` in config.yaml and capture the actual error.
DEFAULT_MODEL = "claude-sonnet-5"

BATCH_SCHEMA_VERSION = 1
BATCH_RECEIPT_SCHEMA_VERSION = 1
DEFAULT_BATCH_LIMIT = 50
MAX_BATCH_ITEMS = 500
MAX_BATCH_BYTES = 32 * 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_EXCLUDE_ITEMS_BYTES = 2 * 1024 * 1024
BATCH_RECEIPTS_DIR = CLASSIFICATION_BATCHES_DIR.relative_to(REPO_DIR)
CLASSIFICATION_MODES = ("full", "timeline")
CLASSIFICATION_SKIP_CANDIDATES_FIELD = "classification_skip_candidates"
BATCH_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")

# Taxonomy themes for the AI prompt
THEME_TAXONOMY = [
    "hunger", "agency", "faith", "money", "belonging", "grief", "ambition",
    "identity", "family", "friendship", "love", "loss", "risk", "fear",
    "purpose", "work", "creativity", "race", "class", "migration",
    "education", "mentorship", "failure", "resilience", "legacy",
    "culture", "politics", "community", "health", "spirituality", "shame",
    "pride", "forgiveness", "betrayal", "justice", "freedom", "adventure",
    "solitude", "home", "nostalgia", "regret", "hope", "joy",
    "parenting", "marriage", "aging",
]


# ── AI client ─────────────────────────────────────────────────────────────────


def classify_with_ai(prompt: str, model: str = DEFAULT_MODEL) -> dict:
    """Classify through the shared provider while prompt mode stays keyless."""
    from ai_provider import call_ai  # local import keeps prompt mode keyless

    return extract_json(call_ai(prompt, model))


def get_model(args: argparse.Namespace) -> str:
    """Resolve effective model: CLI flag > config.yaml > default."""
    if getattr(args, "model", None):
        return args.model
    config = load_config()
    return config.get("classify_model", DEFAULT_MODEL)


# ── source file parsing ───────────────────────────────────────────────────────

def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_text) from a markdown file.

    Handles both source files (--- YAML ---) and answer files. Delegates to
    `lifehug_core.skip_leading_frontmatter_blocks` — THE one frontmatter
    reader in the repo (issue #282) — so a source restored with two or three
    stacked leading blocks reads past every one of them here too, not only
    for the answers/*.md files `load_source_text` routes to `answer_body()`
    below. This used to be its own hand-rolled single-block parser; keeping
    it as a thin wrapper avoids a second, drifting implementation.
    """
    metadata, body, _block_count = skip_leading_frontmatter_blocks(content)
    return metadata, body


def load_source_text(source_path: Path) -> tuple[dict, str]:
    """Load a source or answer file and return (metadata, story_text)."""
    content = source_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(content)

    # Answer files: use answer_body() helper for cleaner extraction
    if source_path.parent.name == "answers" or source_path.is_relative_to(ANSWERS_DIR):
        body = answer_body(content)

    return fm, body


# Longest suffix appended to a stem is ".response.json" (14 chars); capping at
# 180 keeps every derived filename comfortably under the 255-byte filesystem
# limit. Stems at or under the cap are byte-identical to their historical
# values, so existing classification files keep matching.
MAX_STEM_LEN = 180


def classify_stem(source_path: Path) -> str:
    """Return the stable classification file stem for a given source path.

    Over-long stems (retraction slugs embed the full question text and can
    exceed the 255-byte filename limit by themselves) are truncated and made
    unique with a stable hash of the full stem."""
    if not source_path.is_absolute():
        source_path = REPO_DIR / source_path
    try:
        rel = source_path.relative_to(REPO_DIR)
        key = rel.with_suffix("").as_posix()
    except ValueError:
        key = source_path.stem
    stem = slugify(key)
    if len(stem) > MAX_STEM_LEN:
        import hashlib  # noqa: PLC0415

        digest = hashlib.sha256(stem.encode("utf-8")).hexdigest()[:12]
        stem = f"{stem[:MAX_STEM_LEN].rstrip('-')}-{digest}"
    return stem


def classification_path(source_path: Path) -> Path:
    return CLASSIFICATIONS_DIR / f"{classify_stem(source_path)}.json"


def legacy_classification_path(source_path: Path) -> Path:
    """Return the v14-v42 stem-only path, kept for existing state compatibility."""
    return CLASSIFICATIONS_DIR / f"{source_path.stem}.json"


def classification_paths(source_path: Path) -> list[Path]:
    paths = [classification_path(source_path)]
    legacy = legacy_classification_path(source_path)
    if legacy != paths[0]:
        paths.append(legacy)
    return paths


# ── the two predicates, side by side (v237, O-C) ──────────────────────────────
#
# They answer DIFFERENT questions and there is never a third:
#
#   is_classified(source)  — "does this source still need a classification
#                            RUN?"  The BATCH question.
#   is_current(source)     — "is this source's classification safe to READ?"
#                            The ONE reader gate.
#
# A `stale: true` classification (a correction was filed against its source,
# v103 -> `mark_stale`) answers YES to the first and NO to the second: the
# batch must re-derive it, and until it does no derived surface may show it.

WITHHELD_STALE_REASON = "withheld: stale, reclassification pending"

# Process-local diagnostic: which classification files `current_classification_files`
# actually withheld this run. Bounded by the number of classification files;
# read it with `withheld_stale()`, clear it with `reset_withheld_stale()`.
_WITHHELD_STALE: set[str] = set()


def withheld_stale() -> list[str]:
    """Sorted paths this process withheld from readers as stale."""
    return sorted(_WITHHELD_STALE)


def reset_withheld_stale() -> None:
    _WITHHELD_STALE.clear()


def is_classified(source_path: Path, *, context_catalog: dict | None = None) -> bool:
    """Does this source still need a classification RUN? — the BATCH question.

    A classification carrying `stale: true` (a correction was filed against
    its source, v103) counts as unclassified so the weekly batch re-derives
    it — the classify prompt already injects corrections as authoritative, so
    the re-derivation asserts the corrected facts. This is deliberately NOT
    the reader gate: see `is_current` below."""
    if not source_path.exists():
        return False
    for path in classification_paths(source_path):
        if path.exists():
            data = read_json(path, default=None) or {}
            if _is_stale_data(data):
                return False
            snapshot = (
                classifier_ctx.build_context_snapshot(REPO_DIR, source_path)
                if context_catalog is None else
                classifier_ctx.build_context_snapshot_from_catalog(
                    REPO_DIR, source_path, context_catalog
                )
            )
            return classifier_ctx.refresh_reason(snapshot, data) is None
    return False


def is_current(source_path: Path) -> bool:
    """Is this source's classification safe to READ? — the ONE reader gate.

    Classified AND not stale. A stale classification leaves every derived
    reader IMMEDIATELY (the Timeline, the Mirror, the Book, progress,
    research, focus recommendations, the wiki): the file stays on disk
    because it is the batch's target and the person's history, but a reading
    the vault already knows is wrong never feeds the product while the fresh
    one is pending. Compile proceeds without it; a model outage never
    restores a known-stale interpretation."""
    return any(classification_is_current(path)
               for path in classification_paths(source_path))


def classification_is_current(path: Path) -> bool:
    """The per-file half of `is_current`, for a reader that already holds the
    classification JSON path."""
    return path.exists() and not _is_stale(path)


def current_classification_files(
    directory: Path | None = None, *, reverse: bool = False
) -> Iterator[tuple[Path, dict]]:
    """Yield `(path, data)` for every CURRENT classification in `directory`
    (default `CLASSIFICATIONS_DIR`), path-sorted — THE ONE ITERATOR.

    Every derived reader goes through here, so the staleness gate exists in
    exactly one place and a ninth reader cannot re-glob by accident
    (`tests/test_classify_story_current.py` fails the build on any
    `CLASSIFICATIONS_DIR.glob` outside this module).

    `directory` is a parameter, not a module global read, because callers own
    their own vault roots — `timeline.vault_roots()` rebinds its caller's
    `CLASSIFICATIONS_DIR`, and a reader that passed nothing would silently
    split one call across two vaults."""
    root = CLASSIFICATIONS_DIR if directory is None else Path(directory)
    if not root.exists():
        return
    for path in sorted(root.glob("*.json"), reverse=reverse):
        data = read_json(path, default={}) or {}
        if _is_stale_data(data):
            _WITHHELD_STALE.add(str(path))
            continue
        yield path, data


def stale_classification_files(directory: Path | None = None) -> list[Path]:
    """Path-sorted classifications currently withheld from every reader."""
    root = CLASSIFICATIONS_DIR if directory is None else Path(directory)
    if not root.exists():
        return []
    return [p for p in sorted(root.glob("*.json")) if _is_stale(p)]


def classification_counts() -> dict[str, int]:
    """`{current, stale, unclassified}` over this vault's sources — the number
    the owner reads names the hole instead of hiding it inside one total."""
    counts = {"current": 0, "stale": 0, "unclassified": 0}
    for source in all_source_files():
        paths = [p for p in classification_paths(source) if p.exists()]
        if not paths:
            counts["unclassified"] += 1
        elif any(classification_is_current(p) for p in paths):
            counts["current"] += 1
        else:
            counts["stale"] += 1
    return counts


def _is_stale_data(data: dict) -> bool:
    """The ONE staleness definition; `_is_stale` is its file-reading form."""
    return bool(data.get("stale"))


def _is_stale(path: Path) -> bool:
    return _is_stale_data(read_json(path, default=None) or {})


def _stale_at(source_path: Path) -> str:
    for path in classification_paths(source_path):
        if not path.exists():
            continue
        data = read_json(path, default=None) or {}
        if _is_stale_data(data):
            return str(data.get("stale_at") or "")
    return ""


def mark_stale(
    source_path: Path,
    reason: str = "",
    *,
    correction_role: object = DEFAULT_CORRECTION_ROLE,
) -> bool:
    """Flag an existing classification for re-derivation (v103). Returns True
    if a classification file was found (already-stale counts).

    `correction_role` is the closed vocabulary from `lifehug_core` (v237,
    O-C2). A role that does not mark stale — `placement` — returns False and
    writes NOTHING: a person dating a moment is making a DATE DECISION about
    it, not refuting the text it was read out of, and under v237's
    `is_current` gate marking it stale would withhold the very moment they
    just placed. An unknown role raises rather than guessing which of those
    two it meant."""
    if not correction_role_marks_stale(correction_role):
        return False
    marked = False
    for path in classification_paths(source_path):
        if not path.exists():
            continue
        data = read_json(path, default=None) or {}
        if not data.get("stale"):
            data["stale"] = True
            data["stale_reason"] = reason
            data["stale_at"] = now_utc()
            write_json(path, data)
        marked = True
    return marked


CORRECTION_TYPE = "source_correction"
CORRECTIONS_SUBDIR = "corrections"


def _frontmatter_of(path: Path) -> dict:
    """Frontmatter of `path`, or `{}` when it has none or cannot be read.

    Reads through `Path.read_text` like every other source read in this
    module — a bare `.open()` bypasses the no-follow vault I/O authority
    (`vault_paths.py`) and `tests/test_v120_vault_only.py` fails the build
    on it, for reads exactly as much as for writes."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    if not content.startswith("---"):
        return {}
    fm, _body = parse_frontmatter(content)
    return fm


def is_correction_document(path: Path) -> bool:
    """A correction is never a classification TARGET (auditor response 3
    §4.5). Recognised by where it lives AND by what it says it is, so a
    correction filed outside `sources/corrections/` is caught too."""
    if CORRECTIONS_SUBDIR in path.parts and SOURCES_DIR.name in path.parts:
        return True
    return str(_frontmatter_of(path).get("type", "")).strip() == CORRECTION_TYPE


def classify_target_for(path: Path) -> Path | None:
    """The source a correction document corrects, or `None` for anything that
    is not a correction.

    "A correction source should cause reclassification of the corrected
    target, not accidental classification of the correction document itself."
    The join is the same one `corrections_for` reads from the other end
    (`corrects_path`, or `corrects: answer:<stem>`); the platform's enqueuer
    calls THIS helper through the pin so there is one definition and two
    hosts."""
    fm = _frontmatter_of(path)
    if str(fm.get("type", "")).strip() != CORRECTION_TYPE:
        return None
    corrects_path = str(fm.get("corrects_path", "")).strip()
    if corrects_path:
        target = Path(corrects_path)
        return target if target.is_absolute() else REPO_DIR / target
    corrects = str(fm.get("corrects", "")).strip()
    if corrects.startswith("answer:"):
        stem = corrects.split(":", 1)[1].strip()
        if stem:
            return ANSWERS_DIR / f"{stem}.md"
    return None


def all_source_files() -> list[Path]:
    """Return all classifiable source and answer files across the repo.

    Correction documents are excluded (v237): a correction is filed ABOUT a
    source, so classifying it would mint people/places/events out of an
    erratum and leave the corrected source's own stale classification
    standing. `classify_target_for` is how a correction reaches the batch."""
    files: list[Path] = []
    for directory in (SOURCES_DIR, ANSWERS_DIR):
        if directory.exists():
            files.extend(
                p for p in directory.rglob("*.md")
                if not p.name.startswith(".")
                and not is_correction_document(p)
            )
    return sorted(files)


# ── batch ordering: --stale-first and the durable cursor (v237) ───────────────

CLASSIFY_CURSOR_VERSION = 1


def source_key(source_path: Path) -> str:
    """The cursor's key for a source — the same stable stem its classification
    file is named after, so the cursor survives a rename of nothing else."""
    return classify_stem(source_path)


def read_classify_cursor() -> str:
    """The last source key this vault successfully filed, or `""`.

    A missing or malformed cursor is NEVER an error — it means "start at the
    head", which is exactly the pre-v237 behavior."""
    try:
        data = read_json(CLASSIFY_CURSOR_FILE, default=None)
    except (OSError, ValueError):
        # Malformed operational memory is not an error condition — it is a
        # cursor we do not have. Start at the head.
        return ""
    if not isinstance(data, dict):
        return ""
    key = data.get("last_source_key")
    return key if isinstance(key, str) else ""


def write_classify_cursor(source_path: Path, *, run_id: str = "") -> None:
    """Advance the cursor to `source_path`. Derived operational memory:
    rebuildable, deletable, never authority."""
    CLASSIFY_CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
    write_json(CLASSIFY_CURSOR_FILE, {
        "version": CLASSIFY_CURSOR_VERSION,
        "last_source_key": source_key(source_path),
        "updated_at": now_utc(),
        "run_id": run_id,
    })


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _resume_after(ordered: list[Path], cursor: str) -> list[Path]:
    """Rotate `ordered` to start just after `cursor`.

    A rotation, not a truncation: nothing is skipped, the head simply stops
    being where every run begins. When the cursor's source is no longer a
    candidate it has been filed — progress happened — and the head is
    genuinely new, so falling back to the head is correct."""
    if not cursor:
        return ordered
    for index, path in enumerate(ordered):
        if source_key(path) == cursor:
            return ordered[index + 1:] + ordered[: index + 1]
    return ordered


def order_targets(
    sources: list[Path],
    *,
    stale_first: bool = False,
    cursor: str = "",
) -> list[Path]:
    """The batch's candidate order — pure, so it is unit-tested without a model.

    Without `--stale-first` this is the historical alphabetical sweep, rotated
    past the cursor. With it:

      1. STALE first, oldest `stale_at` first. A stale classification is a
         known-wrong reading the product is already refusing to show, so it
         is the most valuable thing the batch can spend a call on. Stale
         ordering deliberately IGNORES the cursor: being passed over means it
         failed, and a failed target is not a served one.
      2. Then never-classified, NEWEST SOURCE FIRST — the answer filed
         yesterday reaches the Timeline before a 2011 email — rotated past
         the cursor so the tail is still reached.
      3. Then everything already current (only reachable without
         `--unclassified`).

    Deterministic given the same tree."""
    stale: list[Path] = []
    never: list[Path] = []
    current: list[Path] = []
    for source in sources:
        existing = [p for p in classification_paths(source) if p.exists()]
        if not existing:
            never.append(source)
        elif any(classification_is_current(p) for p in existing):
            current.append(source)
        else:
            stale.append(source)

    if not stale_first:
        return _resume_after(sorted(sources), cursor)

    stale.sort(key=lambda p: (_stale_at(p), source_key(p)))
    never.sort(key=lambda p: (-_mtime(p), source_key(p)))
    return stale + _resume_after(never, cursor) + sorted(current)


# ── prompt construction ───────────────────────────────────────────────────────

def load_question_categories() -> str:
    """Return a compact list of question-bank categories for the prompt."""
    if not QUESTIONS_FILE.exists():
        return "(question bank unavailable)"
    md_text = QUESTIONS_FILE.read_text(encoding="utf-8")
    categories = parse_categories(md_text)
    lines = [
        f"  {cat_id}: {info['name']} [{info['group']}]"
        for cat_id, info in sorted(categories.items())
    ]
    return "\n".join(lines) or "(no categories found)"



def _relative_path(source_path) -> str:
    """Return path relative to REPO_DIR when possible, else str."""
    try:
        return source_path.relative_to(REPO_DIR).as_posix()
    except ValueError:
        return str(source_path)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: object) -> str:
    raw = value if isinstance(value, bytes) else _canonical_json(value).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _existing_classification(source_path: Path) -> tuple[Path | None, dict | None]:
    for path in classification_paths(source_path):
        if not path.exists():
            continue
        value = read_json(path, default=None)
        if isinstance(value, dict):
            return path, value
    return None, None


def classification_mode(
    snapshot: dict,
    existing: object,
    *,
    require_candidates: bool = False,
) -> str | None:
    """Return the model work needed for this exact source/context state.

    Timeline-only refresh is deliberately narrow: only a context digest
    change on an otherwise compatible, non-stale classification qualifies.
    Source, prompt, extractor, legacy, and explicit-stale changes require a
    full reread. ``None`` means the existing result is already current.
    ``require_candidates`` additionally makes an explicitly skip-true full
    reading eligible for one full candidate-bearing pass.
    """
    if (require_candidates and isinstance(existing, dict)
            and existing.get(CLASSIFICATION_SKIP_CANDIDATES_FIELD) is True):
        return "full"
    reason = classifier_ctx.refresh_reason(snapshot, existing)
    if reason is None:
        return None
    return "timeline" if reason in ("context_changed", "relationship_changed") else "full"


def _corrections_block(source_path: Path) -> str:
    corrections = corrections_for(source_path)
    if not corrections:
        return ""
    joined = "\n".join(f"- {c}" for c in corrections)
    return (f"\n## LATER CORRECTIONS (authoritative — these OVERRIDE the story text "
            f"above; never extract the corrected-away version)\n{joined}\n")


def corrections_for(source_path: Path) -> list[str]:
    """Later authoritative corrections targeting this source (issue #24) —
    included in the classification prompt so a corrected-away fact is never
    re-derived into people/places/events/candidates.

    A thin binding, by contract O-E0d: `source_integrity.active_corrections_for`
    is the one definition of *which* corrections count, and since v236 that
    means the LEAVES of the supersession graph — a correction somebody later
    corrected never reaches this prompt again. This function's remaining job is
    to bind that definition to this module's own paths (which the tests move)
    and to hand back the bodies the prompt wants.
    """
    from source_integrity import active_corrections_for  # noqa: PLC0415

    return [
        record.body
        for record in active_corrections_for(
            source_path,
            corrections_dir=SOURCES_DIR / "corrections",
            repo_dir=REPO_DIR,
        )
    ]


_TIMELINE_EVIDENCE_DECISIONS = """
### Timeline Evidence Uses Two Independent Decisions

1. `source_grounding` proves only a direct `date.stated` or `date.age`. It
   requires exact temporal and subject words. It neither authorizes nor is
   required for `timeline_relation`.
2. `timeline_relation` places the event against a supplied candidate. Its exact
   quote may use role, sequence, stay, office, relationship, or other contextual
   words; it does NOT need a calendar date or age because the candidate carries
   the supported bounds. A relation can therefore be valid while
   `source_grounding` is null.

General contrasts:
- "I opened the shop before I ever drew a salary there" can distinguish an
  opening candidate from an employment candidate and link to it without any
  stated calendar words.
- "While I served my second term as chair" can link within that supplied term
  when the quote distinguishes it from the first term; it does not need a
  direct date or age.
- "Nina was 30 when she qualified" can have grounded age evidence even when no
  candidate exists; grounding does not by itself create a contextual relation.

Prefer the most specific relation the exact quote supports. Use this decision
order for every event. FIRST test whether a supplied candidate is the same
occurrence or a span containing the current event. When the exact quote supports
that match, use `within` and stop; do not choose a looser `before` or `after`
relation merely because the sentence also orders the event against another
candidate. ONLY after ruling out every supported `within` match may you select
`before` or `after`. For example, "I opened the clinic before I later joined its
advisory board" belongs within a supplied clinic-opening candidate; the
advisory-board ordering is weaker. If no opening candidate is supplied or the
quote does not identify one, preserve the supported `before` relation to the
advisory-board candidate rather than inventing a `within` link.

Relation direction is always CURRENT EXTRACTED EVENT relative to SELECTED
CANDIDATE. `after` candidate X means this event happened after X; it never means
X happened after some other event mentioned in the sentence. If the current
event is the selected candidate's own occurrence, use `within` that candidate.
Its independent `date.anchor_ref` may still retain a separate true before/after
constraint to another event.

Treat interval relations as relations to the candidate's WHOLE occurrence.
When the supplied role and name explicitly represent a duration, `before` means
before that duration starts and `after` means after it ends; "during", "while",
"early in", and "late in" the duration are all `within`. Use the supplied
`node_kind`, `event_role`, name, and bounds to distinguish a duration such as a
marriage, residence, job, or term from a point occurrence such as a wedding.
"After the wedding" may support `after` the wedding point, while "early in the
marriage" supports `within` the marriage duration. A range on a point event may
represent uncertainty, so never guess a duration or boundary the candidate does
not state. If the quote does not establish the required whole-occurrence
boundary, do not assert `before` or `after`. Apply the same direction and
interval meaning to `date.anchor_ref` plus `date.relation`.

Choose resolution from coverage, not candidate count. `incomplete` is allowed
ONLY when that event's context says `complete: false`. When `complete: true`,
an empty candidate set for a real event is `missing_evidence`, never
`incomplete`. With complete coverage, use `ambiguous` when multiple supplied
candidates remain plausible and the source cannot distinguish them, and use
`missing_evidence` when no supplied candidate has enough source support.
`not_temporal` is only for an extracted item that is not actually an event.
"""


def _build_timeline_prompt(
    source_path: Path,
    fm: dict,
    story_text: str,
    context_snapshot: dict,
) -> str:
    """Ask only for the temporal fields that can legitimately be refreshed."""
    _path, existing = _existing_classification(source_path)
    stored_events = copy.deepcopy((existing or {}).get("events") or [])
    for event in stored_events:
        if isinstance(event, dict):
            timeline_evidence.ensure_event_key(event)
    timeline_context = json.dumps({
        "classification_snapshot": classifier_ctx.snapshot_metadata(context_snapshot),
        "context_complete": context_snapshot.get("context_complete", False),
        "context_truncated": context_snapshot.get("context_truncated", False),
        "remaining_candidate_count": context_snapshot.get("remaining_candidate_count", 0),
        "catalog_omitted_count": context_snapshot.get("catalog_omitted_count", 0),
        "remaining_decision_count": context_snapshot.get("remaining_decision_count", 0),
        "candidates": context_snapshot.get("candidates", []),
        "human_identity_decisions": context_snapshot.get("human_identity_decisions", []),
        "prior_event_identities": context_snapshot.get("prior_event_identities", []),
        "event_contexts": context_snapshot.get("event_contexts", {}),
    }, indent=2, sort_keys=True)
    return f"""You are refreshing only the timeline evidence in an existing Lifehug story classification.

## Source File
Path: {_relative_path(source_path)}
Title: {fm.get('title', '(untitled)')}
Type: {fm.get('type', 'unknown')}

## Story Text
{story_text}
{_corrections_block(source_path)}

## Canonical Timeline Context
{timeline_context}

## Existing Events (immutable except the three link fields)
{json.dumps(stored_events, indent=2, sort_keys=True)}

Return ONLY one raw JSON object with exactly these fields:
{{
  "_classification_mode": "timeline",
  "_classification_snapshot": {json.dumps(classifier_ctx.snapshot_metadata(context_snapshot), sort_keys=True)},
  "events": [
    {{ "event_key": "exact existing event_key", "source_grounding": {{ "quote": "exact unique event quote", "temporal_quote": "exact date or age words inside quote", "subject_quote": "exact subject words inside quote", "kind": "date|age" }} or null, "timeline_relation": {{ "relation": "within|before|after", "candidate_id": "exact supplied candidate_id", "entity_refs": ["exact refs on that candidate"], "evidence": {{ "quote": "exact uniquely occurring Story Text quote" }} }} or null, "timeline_resolution": {{ "status": "linked|missing_evidence|ambiguous|incomplete|not_temporal", "candidate_ids": ["every supplied candidate id relevant to this event"], "reason": "bounded explanation" }} }}
  ]
}}

{_TIMELINE_EVIDENCE_DECISIONS}

Return each existing event key exactly once. Do not re-extract, rename, reorder,
add, or omit events. Return only the four event-delta fields shown. The framework
merges only grounding, relation and resolution into the stored event. A linked
outcome requires a relation; every other outcome requires null. `candidate_ids`
must list the full relevant set supplied for that event, including alternatives.
Treat each `event_contexts[event_key]` entry independently: its `complete` flag,
candidate ids, and competitors govern only that event. Use incomplete when that
event-local set is marked incomplete. Ground a direct date or age
only with one exact unique event quote whose temporal and subject fragments occur
inside it and support the stored date/age and subject. Never infer a calendar
year. A relation quote must occur exactly once and distinguish competing roles or
same-named stays in the source words. Do not return any document-level extraction
field. Echo the mode and four-key snapshot exactly.
"""


def build_prompt(
    source_path: Path,
    fm: dict,
    story_text: str,
    *,
    context_snapshot: dict | None = None,
    mode: str = "full",
    include_candidates: bool = True,
) -> str:
    """Construct the mode-bound AI classification prompt for one source."""
    if mode not in CLASSIFICATION_MODES:
        raise ValueError(f"unsupported classification mode: {mode}")
    if context_snapshot is None:
        source_bytes = source_path.read_bytes() if source_path.exists() else story_text.encode("utf-8")
        context_snapshot = classifier_ctx.build_context_snapshot(
            REPO_DIR, source_path, source_bytes=source_bytes
        )
    if mode == "timeline":
        return _build_timeline_prompt(source_path, fm, story_text, context_snapshot)
    mission = load_mission()
    judgment_section = ""
    categories_block = ""
    if include_candidates:
        judgment_rubric = load_judgment_rubric()
        judgment_section = f"## Question-Judgment Rubric\n{judgment_rubric}"
        signals_block = owner_judgment_signals_block(build_decision_context(limit=15))
        if signals_block:
            judgment_section += f"\n\n{signals_block}"
        categories_block = load_question_categories()
    themes_block = ", ".join(THEME_TAXONOMY)
    timeline_context = json.dumps({
        "classification_snapshot": classifier_ctx.snapshot_metadata(context_snapshot),
        "context_complete": context_snapshot.get("context_complete", False),
        "context_truncated": context_snapshot.get("context_truncated", False),
        "remaining_candidate_count": context_snapshot.get("remaining_candidate_count", 0),
        "catalog_omitted_count": context_snapshot.get("catalog_omitted_count", 0),
        "remaining_decision_count": context_snapshot.get("remaining_decision_count", 0),
        "candidates": context_snapshot.get("candidates", []),
        "human_identity_decisions": context_snapshot.get("human_identity_decisions", []),
        "prior_event_identities": context_snapshot.get("prior_event_identities", []),
        "event_contexts": context_snapshot.get("event_contexts", {}),
    }, indent=2, sort_keys=True)

    relative_path = _relative_path(source_path)
    question_schema = ""
    question_guidelines = ""
    question_categories_section = ""
    if include_candidates:
        question_schema = f''',
  "candidate_questions": [
    {{
      "text": "string — the actual question",
      "story_function": "one of: {', '.join(STORY_FUNCTIONS)}",
      "priority": 0.75,
      "reason": "why this question matters for the memoir",
      "defer": false,
      "target_category": "one of these category IDs or null — {', '.join(sorted(parse_categories(QUESTIONS_FILE.read_text(encoding='utf-8') if QUESTIONS_FILE.exists() else '').keys()))}"
    }}
  ]'''
        question_guidelines = f'''
- `candidate_questions`: generate 3–8 high-quality follow-up questions. **Craft rules (violations get parked, so follow them):**
  - **Two-sentence rule**: one sentence of context quoting or referencing the author's own words, then ONE open question. One question mark per candidate.
  - **Target the empty scene_slots.** "What does it say about you?" is the highest-value follow-up when that slot is empty.
  - **Action↔identity ladder**: after an action answer ask what it says about them; after an identity claim ask for one specific moment that proves it.
  - **Situation-rich/story-empty sources get the meaning-making question**; story-rich/situation-thin sources get the scene question ("pick one of those mornings — what did it smell like?").
  - **"What"/"When"/"Tell me about", never "Why", for the author's own feelings** (why-questions about one's own emotions produce confabulation). "Why" is fine for events and other people.
  - **Never restate the author's account with changed details** — quote exactly or ask fresh (memory reconsolidation contamination).
  - **New angles only** — if the source retells a story the archive already holds, ask for what's NEVER been told ("a detail from that day you've never mentioned to anyone"), never a re-rehearsal.
  - **High-negative-affect material**: offer ONE distanced question (fly-on-the-wall retelling, or "when you're 80, what will this chapter mean?") rather than digging straight in. If the story describes an upheaval within the last ~2 months, set `"defer": true` on deep-processing questions (they will wait ~60 days — expressive-writing evidence says too-soon is harmful).
  - **Draw from the high-yield families** where they fit: typical-day reconstruction; era anchors (what things cost, the car, the music, the house room by room); photo/song cues ("what song puts you back there?"); perspective-taking ("tell it as your dad would tell it"); off-script probes ("which milestone did NOT go the way the script says?"); forgiveness/blessing ("what do you wish for them that you've never said out loud?").
  - Assign story_function from the list: {', '.join(STORY_FUNCTIONS)}
  - Set priority between 0.4 (nice-to-have) and 0.95 (critical gap)'''
        question_categories_section = f'''### Question bank categories for target_category:
{categories_block}'''

    prompt = f"""You are a memoir analyst and oral history specialist helping to classify a personal story for the Lifehug memoir project.

## Lifehug Mission
{mission}

{judgment_section}

---

## Source File
Path: {relative_path}
Title: {fm.get('title', '(untitled)')}
Type: {fm.get('type', 'unknown')}
Captured at: {fm.get('captured_at', 'unknown')}

## Story Text
{story_text}
{_corrections_block(source_path)}

## Canonical Timeline Context
Only the exact `candidate_id` and `entity_refs` values below may be used for a
timeline relation. Candidate names and aliases are retrieval context, never
permission to bind by a label or substring. A truncated context is visibly
unfinished; do not assert a timeline relation from it. Do not infer candidates
that are not supplied. Follow every eligibility prerequisite in the Guidelines.
{timeline_context}

---

## Your Task
Analyze the story and return a single JSON object with the following keys.
Do NOT include any explanation before or after the JSON block.
Return ONLY the raw JSON (no markdown fences, no commentary).

### Required output schema:

{{
  "_classification_mode": "full",
  "_classification_snapshot": {json.dumps(classifier_ctx.snapshot_metadata(context_snapshot), sort_keys=True)},
  "people": [
    {{ "name": "string", "relationship": "string", "role": "string", "mention_count": 1 }}
  ],
  "places": [
    {{ "name": "string", "type": "city|region|country|building|neighborhood|other", "time_period": "string or null" }}
  ],
  "time_periods": [
    {{ "era": "string", "approximate_dates": "string or null", "life_stage": "string" }}
  ],
  "themes": ["list of theme strings from this taxonomy: {themes_block}"],
  "projects": [
    {{ "name": "string", "type": "business|personal|creative|community|other" }}
  ],
  "contradictions": ["list of unresolved tensions as plain strings"],
  "possible_outputs": [
    {{ "type": "letter|chapter|essay|post|speech|profile", "description": "string" }}
  ],
  "focus_opportunities": [
    {{
      "entity": "string",
      "type": "person|place|period|project|theme",
      "evidence_strength": "weak|moderate|strong",
      "reason": "string"
    }}
  ],
  "self_understanding_insights": ["list of patterns, beliefs, or values surfaced as plain strings"],
  "suggested_sensitivity": "private|family|friends|public",
  "sensitivity_reason": "string — one line on why",
  "scene_slots": {{
    "what_happened": true,
    "when_and_where": false,
    "who_was_there": true,
    "thought_and_felt": false,
    "what_it_says_about_me": false
  }},
  "situation_vs_story": "situation_rich_story_empty|story_rich_situation_thin|balanced|neither",
  "events": [
    {{ "title": "string — a noun phrase of at most 7 words naming the THING, not the telling ('Grandpa\'s two-page letter')", "description": "string — one datable moment", "subject": "string — who or what experienced this event", "places": ["source-grounded place names for this event only"], "when_hint": "string or null — as stated ('sixth grade', 'two weeks after the wedding')", "anchor": "string or null — nearest landmark (a move, wedding, birth, job change)", "date": {{ "stated": "string or null — a date or year the author ACTUALLY SAID", "age": "string or null — the subject's age at the time, in their words ('about five')", "anchor_ref": "string or null — the landmark this is dated against", "relation": "before|after|within|null" }}, "source_grounding": {{ "quote": "exact unique event quote", "temporal_quote": "exact date or age words inside quote", "subject_quote": "exact subject words inside quote", "kind": "date|age" }} or null, "timeline_relation": {{ "relation": "within|before|after", "candidate_id": "an exact supplied candidate_id", "entity_refs": ["one or more exact entity_refs supplied on that candidate"], "evidence": {{ "quote": "one exact, uniquely occurring quote from Story Text" }} }} or null, "timeline_resolution": {{ "status": "linked|missing_evidence|ambiguous|incomplete|not_temporal", "candidate_ids": ["every supplied candidate relevant to this event"], "reason": "bounded explanation" }} }}
  ]{question_schema}
}}

{_TIMELINE_EVIDENCE_DECISIONS}

### Guidelines
- `people`: include every named or described person; estimate mention_count from how prominent they are
- `themes`: prefer taxonomy terms when a close one exists; if the story's CENTRAL theme is genuinely absent from the taxonomy, name it (one or two words, lowercase) — the monthly theme roster curates and merges what you surface
- `suggested_sensitivity`: the most-open audience tier this source could EVER be rendered for.
  Taxonomy (default private when in doubt — the owner reviews before anything opens):
  private = sexuality/intimacy; raw mental-health texture; active wounds involving living
  people; other people's confided secrets; legal/deal specifics; anything a minor child
  disclosed. family = financial specifics, health/body specifics, children's inner lives
  (hard cap — never above family). friends = embarrassing-but-harmless stories, faith
  struggles. public = the narrative arcs themselves (struggle-and-rebuild, scarcity-to-
  success) told without the protected specifics.
- `scene_slots`: which of McAdams' five scene slots this story already fills — what happened / when & where / who was there / what the author thought & felt / what it says about them
- `situation_vs_story` (Gornick): situation = what happened; story = the insight, the thing the author has come to say. Tag which this source has.
- `events`: every datable moment. **Do not invent; do record what was said.** NEVER
  convert, infer, or guess a year the author did not say — record their own time
  words (`when_hint`) and the nearest landmark event (`anchor`); relative anchors
  beat guessed dates. Fill `date` ONLY from what the author explicitly stated: a
  date or year they actually said (`stated`), their age at the time in their own
  words (`age`), or the landmark plus the before/after/during relation they gave
  (`anchor_ref` + `relation`). Leave any key null when they did not say it, and
  leave `date` itself null when they said none of it. The system does the
  arithmetic from there — an age against a birthday, a relation against a dated
  landmark — so a guessed year is worse than no year at all.
- `events[].timeline_relation`: optional contextual placement. Use only
  `within`, `before`, or `after`; never invent `at_start`. Assert a relation ONLY
  when ALL of these already-enforced prerequisites hold:
  1. Compute this event's relevant candidates from its own source-grounded
     title, description, subject, places, anchor, and date.anchor_ref. Specific
     names, aliases, entity refs, and reference keys win; use role-only matches
     only when there is no specific match. Include every supplied competitor
     sharing a matched non-owner entity ref. Copy an exact supplied
     `candidate_id` only when that event-local set is complete. Existing events
     have their exact set in `event_contexts`; the provisional full-extraction
     context is retrieval input, not a candidate list to copy globally.
  2. That candidate must have no `unresolved_entity_mentions` and no
     `entity_ref_ambiguities`. A matching name or date does not resolve identity.
  3. `entity_refs` must be a nonempty list of exact refs supplied on THAT
     candidate, supported by this event. If multiple candidates in the event-local
     set share those refs, the exact source quote must distinguish the selected
     role or stay; a shared ref alone does not disambiguate them.
  4. `evidence.quote` must be one exact, unchanged substring of Story Text
     occurring exactly once. Do not paraphrase, normalize whitespace, combine
     excerpts, or quote context/metadata instead. The system derives offsets.
  If ANY prerequisite is unsupported or uncertain, including empty, null, or
  missing entity refs, return the WHOLE `timeline_relation` as null. Keep the
  event and its independently stated date or age; do not omit the event or
  invent references to make a relation pass. Document-level `places` are
  retrieval hints only, never evidence for every event. A supported contextual
  relation does not replace a direct stated date or age; return both when valid.
- `events[].source_grounding`: ground a direct `date.stated` or `date.age` only
  with one exact, uniquely occurring event quote. Its temporal and subject quote
  must be exact substrings inside that quote and support this event's existing
  date/age and subject. Use the event subject's age, never the owner's age for a
  relative. Description and when_hint summaries are not source quotations.
- `events[].timeline_resolution`: always present. `linked` requires a relation;
  every other status requires null. List every supplied candidate relevant to
  this event in `candidate_ids`, including rejected same-entity alternatives.
  This list is event-local, not the entire catalog. Use `incomplete` when the
  event-local set is incomplete and `not_temporal` only when this extracted item
  is not an event.
- Echo `_classification_snapshot` byte-for-byte as shown. It binds this response
  to the source and context seen in this prompt; never substitute newer values.
- `events[].title`: a noun phrase of at most seven words naming the thing, not the
  telling: "Grandpa's two-page letter", not "the time Grandpa wrote to me about the
  farm". No verbs of narration, no dates in the title.
{question_guidelines}
- `focus_opportunities`: entities rich enough to anchor a dedicated wiki page or chapter section
- `contradictions`: tensions or paradoxes in values, beliefs, or events — leave them unresolved, do not explain them away
- `possible_outputs`: concrete deliverables this story could contribute to

{question_categories_section}

Respond with ONLY valid JSON. No prose, no markdown fences.
"""
    # v96: opinion sources are STATED POSITIONS, not event accounts. The
    # addendum is strictly conditional so every other source's prompt stays
    # byte-identical.
    if fm.get("type") == "opinion":
        prompt += """
### OPINION ADDENDUM (this source is a stated position, not an event account)
- The author is stating a POSITION — a lens on life, a philosophical opinion.
  Do not treat it as a factual event narrative.
- Distill each distinct position it takes into `self_understanding_insights`,
  each prefixed with "position: " (e.g. "position: parents who rose above
  their natural selves deserve gratitude, not disappointment, when they
  revert"). These feed the author's self-knowledge surfaces.
- `contradictions`: only genuine tensions WITHIN the stated position or
  between it and the author's other known positions — never manufacture one.
- `events`: usually empty for an opinion; include only moments the author
  actually narrates.
"""
        if include_candidates:
            prompt += """- `candidate_questions`: use the SOCRATIC families instead of scene probes —
  origin (who taught this / what moment forged it → story_function "value"),
  lived counterexample (→ "contradiction"), how the position has changed
  (→ "growth_edge"), who would disagree and what they see (→
  "perception_by_others"), what holding it costs or protects (→ "fear").
  The Gornick rule still applies: an opinion is story without situation, so
  ONE grounding question asking for a specific lived moment behind the belief
  is high-value.
"""
    return prompt


# ── AI call ───────────────────────────────────────────────────────────────────

def extract_json(text: str) -> dict:
    """Extract a JSON object from the AI response text."""
    def require_object(value: object) -> dict:
        if isinstance(value, dict):
            return value
        raise AIResponseError(
            "AI response JSON had an invalid schema",
            provider="ai",
            operation="classify-parse",
            status="invalid_schema",
            response_bytes=len(text.encode("utf-8", errors="replace")),
        )

    # Try direct parse first
    stripped = text.strip()
    try:
        return require_object(json.loads(stripped))
    except json.JSONDecodeError:
        pass

    # Strip markdown code fences if present
    fence_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", stripped)
    if fence_match:
        try:
            return require_object(json.loads(fence_match.group(1)))
        except json.JSONDecodeError:
            pass

    # Find the first { ... } block
    brace_match = re.search(r"\{[\s\S]+\}", stripped)
    if brace_match:
        try:
            return require_object(json.loads(brace_match.group(0)))
        except json.JSONDecodeError:
            pass

    raise AIResponseError(
        "AI response was not valid JSON",
        provider="ai",
        operation="classify-parse",
        status="malformed",
        response_bytes=len(text.encode("utf-8", errors="replace")),
    )


# ── candidate store helpers ───────────────────────────────────────────────────

def load_candidate_store() -> dict:
    data = read_json(QUESTION_CANDIDATES_FILE, default=None)
    if not isinstance(data, dict):
        return {"version": 1, "candidates": []}
    data.setdefault("version", 1)
    data.setdefault("candidates", [])
    return data


def save_candidate_store(data: dict) -> None:
    data["last_updated"] = now_utc()
    write_json(QUESTION_CANDIDATES_FILE, data)


def next_candidate_index(store: dict, stem: str) -> int:
    """Return the next available candidate index for a given source stem."""
    prefix = f"cand-{slugify(stem)}-"
    existing = [
        c["id"] for c in store.get("candidates", [])
        if c.get("id", "").startswith(prefix)
    ]
    if not existing:
        return 1
    indices = []
    for cid in existing:
        m = re.search(r"-(\d+)$", cid)
        if m:
            indices.append(int(m.group(1)))
    return max(indices, default=0) + 1


def build_candidates(
    ai_questions: list[dict],
    source_path: Path,
    store: dict,
    created_at: str,
) -> list[dict]:
    """Convert AI candidate_questions into store-format candidate records."""
    stem = classify_stem(source_path)
    relative_path = _relative_path(source_path)

    existing_texts = {
        c.get("text", "").strip().lower()
        for c in store.get("candidates", [])
    }
    existing_ids = {c.get("id") for c in store.get("candidates", [])}

    start_idx = next_candidate_index(store, stem)
    candidates: list[dict] = []

    for offset, q in enumerate(ai_questions or []):
        text = str(q.get("text", "")).strip()
        if not text:
            continue
        if text.lower() in existing_texts:
            continue  # deduplicate by normalized text

        story_function = q.get("story_function", "")
        if story_function not in STORY_FUNCTIONS:
            story_function = "scene"  # safe fallback

        priority = float(q.get("priority", 0.5))
        priority = max(0.0, min(1.0, priority))

        cid = f"cand-{slugify(stem)}-{start_idx + offset}"
        # Ensure uniqueness even across concurrent runs
        while cid in existing_ids:
            start_idx += 1
            cid = f"cand-{slugify(stem)}-{start_idx + offset}"

        target_cat = q.get("target_category") or None
        if isinstance(target_cat, str):
            target_cat = target_cat.strip().upper() or None

        record: dict = {
            "id": cid,
            "text": text,
            "source_path": relative_path,
            "target_page": None,
            "kind": story_function,
            "priority": priority,
            "reason": str(q.get("reason", "")).strip(),
            "status": "candidate",
            "story_function": story_function,
            "created_at": created_at,
        }
        if target_cat:
            record["target_category"] = target_cat
        # Fresh-upheaval deferral (Pennebaker): deep-processing questions on a
        # recent upheaval wait ~60 days before becoming promotable.
        if q.get("defer"):
            from datetime import datetime, timedelta, timezone  # noqa: PLC0415
            defer_until = datetime.now(timezone.utc) + timedelta(days=60)
            record["defer_until"] = defer_until.isoformat().replace("+00:00", "Z")
            record["defer_reason"] = "fresh upheaval — deep processing deferred ~60 days"

        candidates.append(record)
        existing_texts.add(text.lower())
        existing_ids.add(cid)

    return candidates


# ── classification record ─────────────────────────────────────────────────────

def build_classification(
    source_path: Path,
    fm: dict,
    ai_result: dict,
    model: str,
    classified_at: str,
    candidate_ids: list[str],
    classification_snapshot: dict | None = None,
) -> dict:
    relative_path = _relative_path(source_path)
    return {
        "version": 2,
        "source_path": relative_path,
        "source_title": fm.get("title", ""),
        "source_type": fm.get("type", "unknown"),
        "classified_at": classified_at,
        "model_used": model,
        "reviewable": True,
        "candidate_question_ids": candidate_ids,
        "classification_snapshot": classifier_ctx.snapshot_metadata(
            classification_snapshot or ai_result.get("_classification_snapshot")
        ),
        # ── extracted fields (as-returned by AI, mark reviewable) ──
        "people": ai_result.get("people", []),
        "places": ai_result.get("places", []),
        "time_periods": ai_result.get("time_periods", []),
        "themes": ai_result.get("themes", []),
        "projects": ai_result.get("projects", []),
        "contradictions": ai_result.get("contradictions", []),
        "possible_outputs": ai_result.get("possible_outputs", []),
        "focus_opportunities": ai_result.get(
            "focus_opportunities",
            ai_result.get(LEGACY_FOCUS_KEY, []),
        ),
        "self_understanding_insights": ai_result.get("self_understanding_insights", []),
        # v70/v71: five-slot scene coverage, Gornick tag, and datable events
        # (relative anchors, never guessed years) for the timeline surface.
        "suggested_sensitivity": ai_result.get("suggested_sensitivity", "private"),
        "sensitivity_reason": ai_result.get("sensitivity_reason", ""),
        "scene_slots": ai_result.get("scene_slots", {}),
        "situation_vs_story": ai_result.get("situation_vs_story", ""),
        "events": ai_result.get("events", []),
    }


# ── printing helpers ──────────────────────────────────────────────────────────

def print_summary(classification: dict, new_candidates: list[dict]) -> None:
    src = classification.get("source_path", "?")
    model = classification.get("model_used", "?")
    classified_at = classification.get("classified_at", "?")

    print(f"\n✓ Classified: {src}")
    print(f"  model   : {model}")
    print(f"  at      : {classified_at}")

    people = classification.get("people", [])
    places = classification.get("places", [])
    themes = classification.get("themes", [])
    contradictions = classification.get("contradictions", [])
    outputs = classification.get("possible_outputs", [])
    focuses = classification.get("focus_opportunities", classification.get(LEGACY_FOCUS_KEY, []))
    insights = classification.get("self_understanding_insights", [])

    if people:
        names = ", ".join(p.get("name", "?") for p in people[:6])
        suffix = f" (+{len(people)-6} more)" if len(people) > 6 else ""
        print(f"  people  : {names}{suffix}")
    if places:
        place_names = ", ".join(p.get("name", "?") for p in places[:4])
        print(f"  places  : {place_names}")
    if themes:
        print(f"  themes  : {', '.join(themes[:8])}")
    if contradictions:
        print(f"  tensions: {len(contradictions)}")
    if outputs:
        out_types = ", ".join(o.get("type", "?") for o in outputs)
        print(f"  outputs : {out_types}")
    if focuses:
        focus_names = ", ".join(s.get("entity", "?") for s in focuses[:4])
        print(f"  focuses : {focus_names}")
    if insights:
        print(f"  insights: {len(insights)}")

    if new_candidates:
        print(f"  cands   : {len(new_candidates)} new question candidates")
        for c in new_candidates:
            print(f"    [{c['id']}] ({c.get('priority', 0):.2f}) {c['text']}")
    else:
        print("  cands   : 0 new question candidates")


# ── core classify action ──────────────────────────────────────────────────────

FULL_LIST_FIELDS = (
    "people", "places", "time_periods", "themes", "projects",
    "contradictions", "possible_outputs", "focus_opportunities",
    "self_understanding_insights", "events",
)


class ClassificationPreparationError(ValueError):
    """A content-free, stable refusal raised before classification writes."""

    def __init__(self, message: str, *, code: str) -> None:
        self.code = code
        super().__init__(message)


def _validate_mode_result(
    result: dict,
    *,
    mode: str,
    require_mode: bool,
    strict_schema: bool,
    include_candidates: bool,
) -> None:
    echoed = result.get("_classification_mode")
    if require_mode or echoed is not None:
        if echoed != mode:
            raise ClassificationPreparationError(
                "classification mode is missing or does not match the requested mode",
                code="mode_mismatch",
            )
    if mode == "timeline":
        if strict_schema and set(result) != {
            "_classification_mode", "_classification_snapshot", "events"
        }:
            raise ClassificationPreparationError(
                "timeline response contained fields outside the timeline contract",
                code="timeline_schema_invalid",
            )
        if not isinstance(result.get("events"), list):
            raise ClassificationPreparationError(
                "timeline events must be a list", code="context_events_not_list"
            )
        for event in result["events"]:
            if not isinstance(event, dict) or set(event) != timeline_evidence.EVENT_DELTA_KEYS:
                raise ClassificationPreparationError(
                    "timeline events must be exact link-only deltas",
                    code="timeline_schema_invalid",
                )
        return
    if not strict_schema:
        return
    for field in FULL_LIST_FIELDS:
        if not isinstance(result.get(field), list):
            raise ClassificationPreparationError(
                f"full response field {field} must be a list",
                code="full_schema_invalid",
            )
    if include_candidates and not isinstance(result.get("candidate_questions"), list):
        raise ClassificationPreparationError(
            "full response candidate_questions must be a list",
            code="full_schema_invalid",
        )
    if not isinstance(result.get("scene_slots"), dict):
        raise ClassificationPreparationError(
            "full response scene_slots must be an object",
            code="full_schema_invalid",
        )
    for field in ("suggested_sensitivity", "sensitivity_reason", "situation_vs_story"):
        if not isinstance(result.get(field), str):
            raise ClassificationPreparationError(
                f"full response field {field} must be a string",
                code="full_schema_invalid",
            )


def prepare_classification(
    source_path: Path,
    model: str,
    result: dict,
    *,
    mode: str,
    snapshot: dict,
    candidate_store: dict,
    skip_candidates: bool = False,
    require_mode: bool = False,
    strict_schema: bool = False,
) -> dict:
    """Validate and normalize one result without writing any vault state."""
    if mode not in CLASSIFICATION_MODES:
        raise ClassificationPreparationError("unsupported mode", code="mode_invalid")
    fm, story_text = load_source_text(source_path)
    if not story_text.strip():
        raise ClassificationPreparationError("source has no story text", code="source_empty")
    if not isinstance(result, dict):
        # Preserve the classifier context validator's established typed code
        # and failure metadata for ordinary single-source callers.
        classifier_ctx.validate_response(result, snapshot, story_text)
    _validate_mode_result(
        result,
        mode=mode,
        require_mode=require_mode,
        strict_schema=strict_schema,
        include_candidates=not skip_candidates,
    )
    _path, existing = _existing_classification(source_path)
    classifier_ctx.validate_response(
        result,
        snapshot,
        story_text,
        mode=mode,
        existing_events=(existing or {}).get("events") if isinstance(existing, dict) else None,
        require_event_contract=(mode == "timeline" or strict_schema),
    )
    base_digest = _digest(existing) if isinstance(existing, dict) else ""
    expected_mode = classification_mode(
        snapshot,
        existing,
        require_candidates=(mode == "full" and not skip_candidates),
    )
    if expected_mode is None:
        return {
            "status": "already_current",
            "source_path": source_path,
            "mode": mode,
            "snapshot": classifier_ctx.snapshot_metadata(snapshot),
            "base_digest": base_digest,
        }
    if expected_mode != mode:
        raise ClassificationPreparationError(
            "response mode is no longer valid for the current base classification",
            code="mode_stale",
        )

    classified_at = now_utc()
    if mode == "timeline":
        if not isinstance(existing, dict):
            raise ClassificationPreparationError(
                "timeline refresh has no compatible base classification",
                code="timeline_base_missing",
            )
        classification = copy.deepcopy(existing)
        by_key = {event["event_key"]: event for event in result["events"]}
        merged_events: list[dict] = []
        for stored in classification.get("events") or ():
            merged = copy.deepcopy(stored)
            key = timeline_evidence.ensure_event_key(merged)
            delta = by_key[key]
            for field in ("source_grounding", "timeline_relation", "timeline_resolution"):
                merged[field] = copy.deepcopy(delta[field])
            merged_events.append(merged)
        classification["events"] = merged_events
        classification["classification_snapshot"] = classifier_ctx.snapshot_metadata(snapshot)
        classification["classified_at"] = classified_at
        classification["model_used"] = model
        new_candidates: list[dict] = []
        updated_store = candidate_store
    else:
        updated_store = copy.deepcopy(candidate_store)
        ai_questions = [] if skip_candidates else normalize_question_records(
            result.get("candidate_questions", []),
            operation="classify-schema",
        )
        new_candidates = build_candidates(
            ai_questions, source_path, updated_store, classified_at
        )
        prior_ids = existing.get("candidate_question_ids", []) if isinstance(existing, dict) else []
        candidate_ids = list(dict.fromkeys([
            *[str(value) for value in prior_ids if value],
            *[candidate["id"] for candidate in new_candidates],
        ]))
        classification = build_classification(
            source_path,
            fm,
            result,
            model,
            classified_at,
            candidate_ids,
            snapshot,
        )
        classification["classification_snapshot"] = classifier_ctx.snapshot_metadata_for_events(
            snapshot, classification["events"]
        )
        classification[CLASSIFICATION_SKIP_CANDIDATES_FIELD] = bool(skip_candidates)
        if new_candidates:
            updated_store["candidates"].extend(new_candidates)
    return {
        "status": "accepted",
        "source_path": source_path,
        "mode": mode,
        "snapshot": classifier_ctx.snapshot_metadata(snapshot),
        "base_digest": base_digest,
        "classification": classification,
        "new_candidates": new_candidates,
        "candidate_store": updated_store,
    }


def apply_prepared_classification(prepared: dict, *, write_candidates: bool = True) -> None:
    """Persist one already-validated item; batch callers may share one store write."""
    if prepared.get("status") != "accepted":
        return
    source_path = prepared["source_path"]
    CLASSIFICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    write_json(classification_path(source_path), prepared["classification"])
    if write_candidates and prepared["new_candidates"]:
        save_candidate_store(prepared["candidate_store"])

def classify_file(
    source_path: Path,
    model: str,
    *,
    dry_run: bool = False,
    verbose: bool = False,
    skip_candidates: bool = False,
    precomputed_result: dict | None = None,
    require_mode: bool = False,
) -> int:
    """Classify a single source file. Returns 0 on success, 1 on error.

    `precomputed_result` (keyless path, --from-response): an externally-produced
    classification JSON that flows through the SAME validation/persistence as
    the AI path. `skip_candidates` suppresses candidate-question generation —
    used for archive backfills where hundreds of new candidates would flood
    the review store without adding craft value."""
    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        return 1

    fm, story_text = load_source_text(source_path)

    if not story_text.strip():
        print(f"Warning: no story text found: {_relative_path(source_path)}", file=sys.stderr)
        return 1

    if dry_run:
        clf_path = classification_path(source_path)
        print(f"[dry-run] would classify: {_relative_path(source_path)}")
        print(f"[dry-run] would call model: {model}")
        print(f"[dry-run] would write classification: {clf_path}")
        if not skip_candidates:
            print("[dry-run] would append candidate questions returned by the model")
        return 0

    prompt_snapshot = classifier_ctx.build_context_snapshot(REPO_DIR, source_path)
    _existing_path, existing = _existing_classification(source_path)
    mode = classification_mode(prompt_snapshot, existing)
    if mode is None:
        print(f"Already current: {_relative_path(source_path)}")
        return 0
    if precomputed_result is not None:
        ai_result = precomputed_result
    else:
        prompt = build_prompt(
            source_path,
            fm,
            story_text,
            context_snapshot=prompt_snapshot,
            mode=mode,
            include_candidates=not skip_candidates,
        )
        if verbose:
            print(f"[verbose] calling model={model} for {source_path}")
        try:
            ai_result = classify_with_ai(prompt, model=model)
        except Exception as exc:
            print(
                "Error: AI classification failed: "
                + failure_metadata("classify", exc, provider="ai"),
                file=sys.stderr,
            )
            return 1

    try:
        # Rebuild after the model returns. A response to an older source or
        # context is rejected before either classification or candidates write.
        current_snapshot = classifier_ctx.build_context_snapshot(REPO_DIR, source_path)
        store = load_candidate_store()
        prepared = prepare_classification(
            source_path,
            model,
            ai_result,
            mode=mode,
            snapshot=current_snapshot,
            candidate_store=store,
            skip_candidates=skip_candidates,
            require_mode=require_mode,
        )
    except Exception as exc:  # noqa: BLE001 — model schema failures stay private
        print(
            "Error: AI classification schema failed: "
            + failure_metadata("classify-schema", exc, provider="ai"),
            file=sys.stderr,
        )
        return 1

    apply_prepared_classification(prepared)
    if prepared["status"] == "already_current":
        print(f"Already current: {_relative_path(source_path)}")
        return 0
    print_summary(prepared["classification"], prepared["new_candidates"])
    return 0


# ── canonical archive batch ──────────────────────────────────────────────────

def _read_transport_json(path_value: str, *, max_bytes: int) -> object:
    path = Path(path_value)
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ClassificationPreparationError(
            "transport input must be a regular non-symlink file",
            code="input_path_unsafe",
        )
    if info.st_size > max_bytes:
        raise ClassificationPreparationError(
            "transport input exceeds its byte limit", code="input_too_large"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_source_path(value: object) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ClassificationPreparationError("source path is invalid", code="source_path_invalid")
    supplied = Path(value)
    candidate = supplied if supplied.is_absolute() else REPO_DIR / supplied
    try:
        lexical = candidate.absolute().relative_to(REPO_DIR.resolve())
    except ValueError as exc:
        raise ClassificationPreparationError(
            "source path escapes the vault", code="source_path_escape"
        ) from exc
    if ".." in supplied.parts:
        raise ClassificationPreparationError(
            "source path traversal is not allowed", code="source_path_escape"
        )
    current = REPO_DIR.resolve()
    try:
        for part in lexical.parts:
            current = current / part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise ClassificationPreparationError(
                    "source path may not traverse a symlink", code="source_path_symlink"
                )
    except FileNotFoundError as exc:
        raise ClassificationPreparationError(
            "source file does not exist", code="source_missing"
        ) from exc
    resolved = candidate.resolve(strict=True)
    try:
        relative = resolved.relative_to(REPO_DIR.resolve())
    except ValueError as exc:
        raise ClassificationPreparationError(
            "source path escapes the vault", code="source_path_escape"
        ) from exc
    allowed_roots = {SOURCES_DIR.resolve(), ANSWERS_DIR.resolve()}
    if not any(resolved.is_relative_to(root) for root in allowed_roots):
        raise ClassificationPreparationError(
            "source is outside the classifiable inventory", code="source_not_classifiable"
        )
    if not resolved.is_file() or resolved.suffix != ".md" or resolved.name.startswith("."):
        raise ClassificationPreparationError(
            "source is not a classifiable markdown file", code="source_not_classifiable"
        )
    if is_correction_document(resolved):
        raise ClassificationPreparationError(
            "correction documents are not classification targets",
            code="source_is_correction",
        )
    return REPO_DIR / relative


def _explicit_sources(path_value: str) -> list[Path]:
    payload = _read_transport_json(path_value, max_bytes=2 * 1024 * 1024)
    values = payload.get("sources") if isinstance(payload, dict) else payload
    if not isinstance(values, list):
        raise ClassificationPreparationError(
            "sources JSON must be a list or an object with a sources list",
            code="sources_schema_invalid",
        )
    if len(values) > MAX_BATCH_ITEMS:
        raise ClassificationPreparationError(
            "explicit source inventory exceeds 500 items", code="too_many_sources"
        )
    result: list[Path] = []
    seen: set[str] = set()
    for value in values:
        source = _safe_source_path(value)
        relative = _relative_path(source)
        if relative in seen:
            raise ClassificationPreparationError(
                "explicit source inventory contains duplicates", code="duplicate_source"
            )
        seen.add(relative)
        result.append(source)
    return result


def classification_inventory(
    sources: list[Path] | None = None,
) -> tuple[list[Path], list[dict]]:
    """One eligibility definition for refresh and archive completion reports."""
    inventory = all_source_files() if sources is None else list(sources)
    eligible: list[Path] = []
    ineligible: list[dict] = []
    seen: set[str] = set()
    for value in inventory:
        label = _relative_path(value)
        try:
            source = _safe_source_path(label)
            relative = _relative_path(source)
            if relative in seen:
                raise ClassificationPreparationError(
                    "source inventory contains duplicates", code="duplicate_source"
                )
            seen.add(relative)
            _fm, story_text = load_source_text(source)
            if not story_text.strip():
                raise ClassificationPreparationError(
                    "source has no story text", code="source_empty"
                )
            eligible.append(source)
        except Exception as exc:  # noqa: BLE001 - content-free inventory outcome
            ineligible.append({
                "source_path": label,
                "refusal_code": _batch_error_code(exc),
            })
    ineligible.sort(key=lambda row: row["source_path"])
    return eligible, ineligible


def _normalize_exclude_items(value: object) -> set[tuple[str, tuple[str, ...]]]:
    """Validate exact attempted source/snapshot identities for planner paging."""
    if value is None:
        return set()
    if not isinstance(value, list):
        raise ClassificationPreparationError(
            "exclude items must be a list", code="exclude_schema_invalid"
        )
    identities: set[tuple[str, tuple[str, ...]]] = set()
    snapshot_keys = tuple(classifier_ctx.SNAPSHOT_KEYS)
    for row in value:
        if not isinstance(row, dict) or set(row) != {"source_path", "snapshot"}:
            raise ClassificationPreparationError(
                "exclude item must bind source_path and snapshot",
                code="exclude_schema_invalid",
            )
        source_path = _relative_path(_safe_source_path(row["source_path"]))
        snapshot = row["snapshot"]
        if not isinstance(snapshot, dict) or set(snapshot) != set(snapshot_keys):
            raise ClassificationPreparationError(
                "exclude snapshot must contain exactly four identity fields",
                code="exclude_schema_invalid",
            )
        metadata = classifier_ctx.snapshot_metadata(snapshot)
        if (not DIGEST_PATTERN.fullmatch(metadata["source_revision"])
                or not DIGEST_PATTERN.fullmatch(metadata["context_digest"])
                or not all(0 < len(metadata[key]) <= 200 for key in (
                    "prompt_version", "extractor_version"
                ))):
            raise ClassificationPreparationError(
                "exclude snapshot identity is malformed", code="exclude_schema_invalid"
            )
        identity = (source_path, tuple(metadata[key] for key in snapshot_keys))
        if identity in identities:
            raise ClassificationPreparationError(
                "exclude items contain a duplicate identity", code="duplicate_exclude_item"
            )
        identities.add(identity)
    return identities


def _exclude_items(path_value: str) -> list[dict]:
    payload = _read_transport_json(path_value, max_bytes=MAX_EXCLUDE_ITEMS_BYTES)
    if (not isinstance(payload, dict)
            or set(payload) != {"schema_version", "items"}
            or payload.get("schema_version") != BATCH_SCHEMA_VERSION):
        raise ClassificationPreparationError(
            "exclude document must be a schema-v1 items object",
            code="exclude_schema_invalid",
        )
    _normalize_exclude_items(payload["items"])
    return payload["items"]


def _pending_identity(row: dict) -> tuple[str, tuple[str, ...]]:
    metadata = row["snapshot"]
    return (
        row["source_path"],
        tuple(metadata[key] for key in classifier_ctx.SNAPSHOT_KEYS),
    )


def build_batch_plan(
    *,
    limit: int = DEFAULT_BATCH_LIMIT,
    sources: list[Path] | None = None,
    skip_candidates: bool = False,
    require_candidates: bool = False,
    exclude_items: list[dict] | None = None,
) -> dict:
    """Build one bounded private transport document from one shared catalog."""
    if isinstance(limit, bool) or not 0 <= int(limit) <= MAX_BATCH_ITEMS:
        raise ClassificationPreparationError(
            "batch limit must be between 0 and 500", code="limit_invalid"
        )
    if require_candidates and (
            sources is None or len(sources) != 1 or skip_candidates):
        raise ClassificationPreparationError(
            "candidate generation requires one explicit source and skip_candidates=false",
            code="candidate_request_scope_invalid",
        )
    inventory_scope = "all" if sources is None else "explicit"
    excluded_identities = _normalize_exclude_items(exclude_items)
    safe_inventory, ineligible = classification_inventory(sources)
    catalog = classifier_ctx.load_context_catalog(REPO_DIR)
    pending: list[dict] = []
    for source in safe_inventory:
        snapshot = classifier_ctx.build_context_snapshot_from_catalog(
            REPO_DIR, source, catalog
        )
        _path, existing = _existing_classification(source)
        reason = classifier_ctx.refresh_reason(snapshot, existing)
        candidate_generation_needed = (
            require_candidates
            and isinstance(existing, dict)
            and existing.get(CLASSIFICATION_SKIP_CANDIDATES_FIELD) is True
        )
        if reason is None and not candidate_generation_needed:
            continue
        if reason is None:
            reason = "candidate_generation_needed"
        mode = classification_mode(
            snapshot,
            existing,
            require_candidates=require_candidates,
        )
        pending.append({
            "source": source,
            "source_path": _relative_path(source),
            "reason": reason,
            "mode": mode,
            "snapshot": classifier_ctx.snapshot_metadata(snapshot),
            "context_snapshot": snapshot,
        })
    pending.sort(key=lambda row: (row["reason"] != "stale", row["source_path"]))
    excluded_count = sum(
        _pending_identity(row) in excluded_identities for row in pending
    )
    selectable = [
        row for row in pending if _pending_identity(row) not in excluded_identities
    ]
    selected = []
    for row in selectable[: int(limit)]:
        fm, story_text = load_source_text(row["source"])
        selected.append({
            "source_path": row["source_path"],
            "reason": row["reason"],
            "mode": row["mode"],
            "snapshot": row["snapshot"],
            "prompt": build_prompt(
                row["source"],
                fm,
                story_text,
                context_snapshot=row["context_snapshot"],
                mode=row["mode"] or "full",
                include_candidates=not skip_candidates,
            ),
        })
    return {
        "schema_version": BATCH_SCHEMA_VERSION,
        "skip_candidates": bool(skip_candidates),
        "inventory_scope": inventory_scope,
        "eligible_count": len(safe_inventory),
        "ineligible_count": len(ineligible),
        "ineligible_items": ineligible,
        "excluded_count": excluded_count,
        "selected_count": len(selected),
        "pending_count": len(pending),
        "remaining_count": max(0, len(selectable) - len(selected)),
        "items": selected,
    }


def _batch_id(value: object) -> str:
    if (not isinstance(value, str) or len(value) > 80
            or BATCH_ID_PATTERN.fullmatch(value) is None):
        raise ClassificationPreparationError(
            "batch_id must be a lowercase hyphenated slug", code="batch_id_invalid"
        )
    return value


def batch_receipt_relative_path(batch_id: str) -> str:
    return (BATCH_RECEIPTS_DIR / f"{_batch_id(batch_id)}.json").as_posix()


def _read_batch_receipt(relative: str) -> dict | None:
    try:
        value = json.loads(read_vault_text(relative, vault_root=REPO_DIR))
    except FileNotFoundError:
        return None
    if not isinstance(value, dict):
        raise ClassificationPreparationError(
            "existing batch receipt is invalid", code="receipt_invalid"
        )
    return value


def _write_batch_receipt(relative: str, receipt: dict) -> None:
    atomic_write_vault_text(
        relative,
        json.dumps(receipt, indent=2) + "\n",
        vault_root=REPO_DIR,
    )


def _batch_error_code(exc: Exception) -> str:
    if isinstance(exc, (ClassificationPreparationError, classifier_ctx.ClassifierContextError)):
        code = exc.code
        return code.value if hasattr(code, "value") else str(code)
    if isinstance(exc, AIResponseError):
        return str(exc.status or "response_invalid")
    if isinstance(exc, json.JSONDecodeError):
        return "input_json_invalid"
    if isinstance(exc, (OSError, UnicodeError)):
        return "input_read_failed"
    return "response_invalid"


def _batch_item_identity(item: object, index: int) -> dict:
    row = item if isinstance(item, dict) else {}
    response = row.get("response_text")
    try:
        if isinstance(response, str):
            response_digest = _digest(response.encode("utf-8"))
        else:
            response_digest = _digest(response)
    except (TypeError, ValueError) as exc:
        raise ClassificationPreparationError(
            "batch items must be JSON values", code="batch_schema_invalid"
        ) from exc
    identity = {
        "index": index,
        "source_path": row.get("source_path") if isinstance(row.get("source_path"), str) else "",
        "mode": row.get("mode") if isinstance(row.get("mode"), str) else "",
        "response_digest": response_digest,
    }
    if (not isinstance(item, dict)
            or set(item) != {"source_path", "mode", "response_text"}
            or not isinstance(item.get("source_path"), str)
            or not isinstance(item.get("mode"), str)
            or not isinstance(item.get("response_text"), str)):
        try:
            identity["malformed_digest"] = _digest(item)
        except (TypeError, ValueError) as exc:
            raise ClassificationPreparationError(
                "batch items must be JSON values", code="batch_schema_invalid"
            ) from exc
    return identity


def _batch_envelope_identity(payload: object) -> dict:
    if (not isinstance(payload, dict)
            or set(payload) != {"schema_version", "batch_id", "skip_candidates", "items"}
            or type(payload.get("schema_version")) is not int
            or payload.get("schema_version") != BATCH_SCHEMA_VERSION):
        raise ClassificationPreparationError(
            "batch response schema_version must be 1", code="batch_schema_invalid"
        )
    batch_id = _batch_id(payload.get("batch_id"))
    if not isinstance(payload.get("skip_candidates"), bool):
        raise ClassificationPreparationError(
            "batch response skip_candidates must be boolean",
            code="batch_schema_invalid",
        )
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise ClassificationPreparationError(
            "batch response items must be a list", code="batch_schema_invalid"
        )
    if len(raw_items) > MAX_BATCH_ITEMS:
        raise ClassificationPreparationError(
            "batch response exceeds 500 items", code="too_many_items"
        )
    identities = [_batch_item_identity(item, index) for index, item in enumerate(raw_items)]
    receipt_sources = [
        identity["source_path"] or f"<item:{index}>"
        for index, identity in enumerate(identities)
    ]
    if len(set(receipt_sources)) != len(receipt_sources):
        raise ClassificationPreparationError(
            "batch contains duplicate source labels", code="duplicate_source"
        )
    skip_candidates = payload["skip_candidates"]
    item_digests = [
        _digest({
            "batch_id": batch_id,
            "skip_candidates": skip_candidates,
            **identity,
        })
        for identity in identities
    ]
    return {
        "batch_id": batch_id,
        "skip_candidates": skip_candidates,
        "raw_items": raw_items,
        "identities": identities,
        "item_digests": item_digests,
        "input_digest": _digest({
            "schema_version": BATCH_SCHEMA_VERSION,
            "batch_id": batch_id,
            "skip_candidates": skip_candidates,
            "items": identities,
        }),
        "receipt_path": batch_receipt_relative_path(batch_id),
    }


def _receipt_counts(items: list[dict]) -> dict:
    return {
        status: sum(row["status"] == status for row in items)
        for status in ("accepted", "refused", "already_current")
    }


def validate_batch_receipt(envelope: object, receipt: object) -> dict:
    """Purely validate a receipt's exact input binding and internal consistency."""
    binding = _batch_envelope_identity(envelope)
    receipt_keys = {
        "schema_version", "batch_id", "skip_candidates", "input_digest",
        "receipt_path", "items", "counts",
    }
    if not isinstance(receipt, dict) or set(receipt) != receipt_keys:
        raise ClassificationPreparationError(
            "batch receipt has invalid fields", code="receipt_invalid"
        )
    if (type(receipt.get("schema_version")) is not int
            or not isinstance(receipt.get("batch_id"), str)
            or type(receipt.get("skip_candidates")) is not bool
            or not isinstance(receipt.get("input_digest"), str)
            or not isinstance(receipt.get("receipt_path"), str)):
        raise ClassificationPreparationError(
            "batch receipt field types are invalid", code="receipt_invalid"
        )
    expected_top = {
        "schema_version": BATCH_RECEIPT_SCHEMA_VERSION,
        "batch_id": binding["batch_id"],
        "skip_candidates": binding["skip_candidates"],
        "input_digest": binding["input_digest"],
        "receipt_path": binding["receipt_path"],
    }
    if any(receipt.get(key) != value for key, value in expected_top.items()):
        raise ClassificationPreparationError(
            "batch receipt does not match its envelope", code="receipt_invalid"
        )
    raw_items = receipt.get("items")
    if not isinstance(raw_items, list) or len(raw_items) != len(binding["identities"]):
        raise ClassificationPreparationError(
            "batch receipt item count is invalid", code="receipt_invalid"
        )
    statuses = {"accepted", "refused", "already_current"}
    seen_sources: set[str] = set()
    for index, (item, identity, item_digest) in enumerate(zip(
            raw_items, binding["identities"], binding["item_digests"], strict=True)):
        if (not isinstance(item, dict)
                or set(item) != {
                    "source_path", "mode", "input_digest", "status", "refusal_code",
                }):
            raise ClassificationPreparationError(
                "batch receipt item has invalid fields", code="receipt_invalid"
            )
        expected_source = identity["source_path"] or f"<item:{index}>"
        expected_mode = identity["mode"] if identity["mode"] in CLASSIFICATION_MODES else "full"
        if (item.get("source_path") != expected_source
                or item.get("mode") != expected_mode
                or item.get("input_digest") != item_digest):
            raise ClassificationPreparationError(
                "batch receipt item does not match its envelope", code="receipt_invalid"
            )
        if expected_source in seen_sources:
            raise ClassificationPreparationError(
                "batch receipt has duplicate sources", code="receipt_invalid"
            )
        seen_sources.add(expected_source)
        status = item.get("status")
        refusal_code = item.get("refusal_code")
        if not isinstance(status, str) or status not in statuses:
            raise ClassificationPreparationError(
                "batch receipt status is invalid", code="receipt_invalid"
            )
        if status == "refused":
            if not isinstance(refusal_code, str) or not refusal_code:
                raise ClassificationPreparationError(
                    "refused batch receipt item needs a refusal code",
                    code="receipt_invalid",
                )
        elif refusal_code is not None:
            raise ClassificationPreparationError(
                "successful batch receipt item cannot have a refusal code",
                code="receipt_invalid",
            )
    counts = receipt.get("counts")
    expected_counts = _receipt_counts(raw_items)
    if (not isinstance(counts, dict)
            or set(counts) != set(expected_counts)
            or any(type(value) is not int for value in counts.values())
            or counts != expected_counts):
        raise ClassificationPreparationError(
            "batch receipt counts are invalid", code="receipt_invalid"
        )
    return receipt


def file_batch_response(payload: object, *, model: str = "external-agent") -> dict:
    """Validate one envelope, apply valid siblings, then publish its receipt."""
    binding = _batch_envelope_identity(payload)
    batch_id = binding["batch_id"]
    skip_candidates = binding["skip_candidates"]
    raw_items = binding["raw_items"]
    identities = binding["identities"]
    item_digests = binding["item_digests"]
    input_digest = binding["input_digest"]
    receipt_relative = binding["receipt_path"]
    existing_receipt = _read_batch_receipt(receipt_relative)
    if isinstance(existing_receipt, dict):
        if not isinstance(existing_receipt.get("input_digest"), str):
            return validate_batch_receipt(payload, existing_receipt)
        if existing_receipt.get("input_digest") != input_digest:
            raise ClassificationPreparationError(
                "batch_id is already bound to different input",
                code="batch_id_conflict",
            )
        return validate_batch_receipt(payload, existing_receipt)

    structural: list[dict] = []
    canonical_seen: set[str] = set()
    valid_rows: list[dict] = []
    duplicate_source = False
    preflight_sources: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict) or not isinstance(item.get("source_path"), str):
            continue
        try:
            canonical = _relative_path(_safe_source_path(item["source_path"]))
        except ClassificationPreparationError:
            continue
        if canonical in preflight_sources:
            raise ClassificationPreparationError(
                "batch contains duplicate source targets", code="duplicate_source"
            )
        preflight_sources.add(canonical)
    for index, item in enumerate(raw_items):
        identity = identities[index]
        source_label = identity["source_path"] or f"<item:{index}>"
        item_digest = item_digests[index]
        try:
            if not isinstance(item, dict) or set(item) != {"source_path", "mode", "response_text"}:
                raise ClassificationPreparationError(
                    "batch item has invalid fields", code="item_schema_invalid"
                )
            if item["mode"] not in CLASSIFICATION_MODES:
                raise ClassificationPreparationError("batch item mode is invalid", code="mode_invalid")
            if not isinstance(item["response_text"], str):
                raise ClassificationPreparationError(
                    "batch response_text must be a string", code="response_not_string"
                )
            if len(item["response_text"].encode("utf-8")) > MAX_RESPONSE_BYTES:
                raise ClassificationPreparationError(
                    "batch response_text exceeds its byte limit", code="response_too_large"
                )
            source = _safe_source_path(item["source_path"])
            relative = _relative_path(source)
            if item["source_path"] != relative:
                raise ClassificationPreparationError(
                    "batch source paths must be canonical vault-relative paths",
                    code="source_path_invalid",
                )
            if relative in canonical_seen:
                duplicate_source = True
                raise ClassificationPreparationError(
                    "batch contains duplicate source targets", code="duplicate_source"
                )
            canonical_seen.add(relative)
            valid_rows.append({
                "index": index,
                "source": source,
                "source_path": relative,
                "mode": item["mode"],
                "response_text": item["response_text"],
                "input_digest": item_digest,
            })
        except OSError:
            raise
        except Exception as exc:  # noqa: BLE001 - every item gets a typed outcome
            structural.append({
                "index": index,
                "source_path": source_label,
                "mode": identity["mode"] if identity["mode"] in CLASSIFICATION_MODES else "full",
                "input_digest": item_digest,
                "status": "refused",
                "refusal_code": _batch_error_code(exc),
            })

    if duplicate_source:
        raise ClassificationPreparationError(
            "batch contains duplicate source targets", code="duplicate_source"
        )

    catalog = classifier_ctx.load_context_catalog(REPO_DIR)
    base_store = load_candidate_store()
    first_pass: list[dict] = []
    for row in valid_rows:
        try:
            snapshot = classifier_ctx.build_context_snapshot_from_catalog(
                REPO_DIR, row["source"], catalog
            )
            _path, existing = _existing_classification(row["source"])
            needed = classification_mode(
                snapshot,
                existing,
                require_candidates=(row["mode"] == "full" and not skip_candidates),
            )
            if needed is None:
                first_pass.append({**row, "status": "already_current", "snapshot": snapshot})
                continue
            if needed != row["mode"]:
                raise ClassificationPreparationError(
                    "batch mode is stale for the current source", code="mode_stale"
                )
            result = extract_json(row["response_text"])
            prepared = prepare_classification(
                row["source"],
                model,
                result,
                mode=row["mode"],
                snapshot=snapshot,
                candidate_store=base_store,
                skip_candidates=skip_candidates,
                require_mode=True,
                strict_schema=True,
            )
            first_pass.append({**row, "status": prepared["status"], "snapshot": snapshot})
        except OSError:
            raise
        except Exception as exc:  # noqa: BLE001
            first_pass.append({**row, "status": "refused", "refusal_code": _batch_error_code(exc)})

    # Re-read the whole catalog once after validation. Final preparation below
    # uses this single shared view and refuses any source/context race before
    # the first classification write.
    final_catalog = classifier_ctx.load_context_catalog(REPO_DIR)
    virtual_store = base_store
    prepared_items: list[tuple[dict, dict]] = []
    outcomes = list(structural)
    for row in first_pass:
        if row["status"] == "refused":
            outcomes.append({
                "index": row["index"],
                "source_path": row["source_path"],
                "mode": row["mode"],
                "input_digest": row["input_digest"],
                "status": row["status"],
                "refusal_code": row.get("refusal_code"),
            })
            continue
        try:
            snapshot = classifier_ctx.build_context_snapshot_from_catalog(
                REPO_DIR, row["source"], final_catalog
            )
            if classifier_ctx.snapshot_metadata(snapshot) != classifier_ctx.snapshot_metadata(row["snapshot"]):
                raise ClassificationPreparationError(
                    "source or context changed during batch validation",
                    code="source_context_race",
                )
            _path, existing = _existing_classification(row["source"])
            needed = classification_mode(
                snapshot,
                existing,
                require_candidates=(row["mode"] == "full" and not skip_candidates),
            )
            if row["status"] == "already_current":
                if needed is not None:
                    raise ClassificationPreparationError(
                        "current classification changed during validation",
                        code="source_context_race",
                    )
                outcomes.append({
                    "index": row["index"],
                    "source_path": row["source_path"],
                    "mode": row["mode"],
                    "input_digest": row["input_digest"],
                    "status": "already_current",
                    "refusal_code": None,
                })
                continue
            result = extract_json(row["response_text"])
            prepared = prepare_classification(
                row["source"],
                model,
                result,
                mode=row["mode"],
                snapshot=snapshot,
                candidate_store=virtual_store,
                skip_candidates=skip_candidates,
                require_mode=True,
                strict_schema=True,
            )
            virtual_store = prepared["candidate_store"]
            prepared_items.append((row, prepared))
            outcomes.append({
                "index": row["index"],
                "source_path": row["source_path"],
                "mode": row["mode"],
                "input_digest": row["input_digest"],
                "status": "accepted",
                "refusal_code": None,
            })
        except OSError:
            raise
        except Exception as exc:  # noqa: BLE001
            outcomes.append({
                "index": row["index"],
                "source_path": row["source_path"],
                "mode": row["mode"],
                "input_digest": row["input_digest"],
                "status": "refused",
                "refusal_code": _batch_error_code(exc),
            })

    # The final named-source/base check happens after every item is prepared and
    # before the first write. It catches source edits and another classifier
    # filing into the same target during validation without a third catalog read.
    survivors: list[tuple[dict, dict]] = []
    outcome_by_source = {row["source_path"]: row for row in outcomes}
    virtual_store = base_store
    for row, prepared in prepared_items:
        try:
            if cc_revision := prepared["snapshot"].get("source_revision"):
                if classifier_ctx.effective_source_revision(
                    REPO_DIR, row["source"]
                ) != cc_revision:
                    raise ClassificationPreparationError(
                        "source changed after preparation", code="source_context_race"
                    )
            _path, existing = _existing_classification(row["source"])
            current_base = _digest(existing) if isinstance(existing, dict) else ""
            if current_base != prepared["base_digest"]:
                raise ClassificationPreparationError(
                    "base classification changed after preparation",
                    code="source_context_race",
                )
            result = extract_json(row["response_text"])
            prepared = prepare_classification(
                row["source"], model, result, mode=row["mode"],
                snapshot=row["snapshot"], candidate_store=virtual_store,
                skip_candidates=skip_candidates, require_mode=True,
                strict_schema=True,
            )
            if classifier_ctx.effective_source_revision(
                REPO_DIR, row["source"]
            ) != prepared["snapshot"].get("source_revision"):
                raise ClassificationPreparationError(
                    "source changed after final preparation",
                    code="source_context_race",
                )
            _path, existing = _existing_classification(row["source"])
            current_base = _digest(existing) if isinstance(existing, dict) else ""
            if current_base != prepared["base_digest"]:
                raise ClassificationPreparationError(
                    "base classification changed after final preparation",
                    code="source_context_race",
                )
            virtual_store = prepared["candidate_store"]
            survivors.append((row, prepared))
        except OSError:
            raise
        except Exception as exc:  # noqa: BLE001
            target = outcome_by_source[row["source_path"]]
            target["status"] = "refused"
            target["refusal_code"] = _batch_error_code(exc)

    outcomes.sort(key=lambda row: row["index"])
    receipt_items = [
        {key: row[key] for key in (
            "source_path", "mode", "input_digest", "status", "refusal_code",
        )}
        for row in outcomes
    ]
    receipt = {
        "schema_version": BATCH_RECEIPT_SCHEMA_VERSION,
        "batch_id": batch_id,
        "skip_candidates": skip_candidates,
        "input_digest": input_digest,
        "receipt_path": receipt_relative,
        "items": receipt_items,
        "counts": _receipt_counts(receipt_items),
    }
    validated = validate_batch_receipt(payload, receipt)
    for _row, prepared in survivors:
        apply_prepared_classification(prepared, write_candidates=False)
    if any(prepared["new_candidates"] for _row, prepared in survivors):
        save_candidate_store(virtual_store)
    _write_batch_receipt(receipt_relative, validated)
    return validated


# ── modes ─────────────────────────────────────────────────────────────────────

def cmd_classify(args: argparse.Namespace) -> int:
    source_path = Path(args.classify)
    if not source_path.is_absolute():
        source_path = REPO_DIR / source_path
    target = classify_target_for(source_path)
    if target is not None:
        print(
            f"Error: classify_target_is_correction: {_relative_path(source_path)} "
            f"is a correction, not a classification target — its target is "
            f"{_relative_path(target)}",
            file=sys.stderr,
        )
        return 1
    model = get_model(args)
    return classify_file(
        source_path,
        model,
        dry_run=args.dry_run,
        verbose=getattr(args, "verbose", False),
        skip_candidates=getattr(args, "skip_candidates", False),
    )


def cmd_prompt(args: argparse.Namespace) -> int:
    """Print the classification prompt for a source file (no API call)."""
    source_path = Path(args.prompt_file)
    if not source_path.is_absolute():
        source_path = REPO_DIR / source_path

    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        return 1

    fm, story_text = load_source_text(source_path)

    if not story_text.strip():
        print(f"Warning: no story text found: {_relative_path(source_path)}", file=sys.stderr)
        return 1

    snapshot = classifier_ctx.build_context_snapshot(REPO_DIR, source_path)
    _path, existing = _existing_classification(source_path)
    mode = classification_mode(snapshot, existing)
    if mode is None:
        print(f"Already current: {_relative_path(source_path)}", file=sys.stderr)
        return 0
    prompt = build_prompt(
        source_path,
        fm,
        story_text,
        context_snapshot=snapshot,
        mode=mode,
        include_candidates=not args.skip_candidates,
    )
    print(prompt)
    return 0


def cmd_from_response(args: argparse.Namespace) -> int:
    """Keyless ingest: a classification JSON produced externally (an agent as
    the model) flows through the normal pipeline. Mirrors the entity_roster /
    research_expand --from-response pattern."""
    source_path = Path(args.source)
    if not source_path.is_absolute():
        source_path = REPO_DIR / source_path
    response_path = Path(args.from_response)
    try:
        raw_response = response_path.read_text(encoding="utf-8")
        result = extract_json(raw_response)
    except Exception as exc:  # noqa: BLE001
        print(
            "Error: could not parse response JSON: "
            + failure_metadata("classify-from-response", exc, provider="agent"),
            file=sys.stderr,
        )
        return 1
    skip_candidates = (
        getattr(args, "skip_candidates", None) is True
        or getattr(args, "no_candidates", None) is True
    )
    return classify_file(
        source_path,
        model=args.model or "external-agent",
        dry_run=args.dry_run,
        verbose=getattr(args, "verbose", False),
        skip_candidates=skip_candidates,
        precomputed_result=result,
        require_mode=False,
    )


def cmd_batch_plan(args: argparse.Namespace) -> int:
    """Print exactly one private JSON transport object and no prose."""
    try:
        sources_json = getattr(args, "sources_json", None)
        exclude_items_json = getattr(args, "exclude_items_json", None)
        sources = _explicit_sources(sources_json) if sources_json else None
        exclude_items = (
            _exclude_items(exclude_items_json) if exclude_items_json else None
        )
        plan = build_batch_plan(
            limit=DEFAULT_BATCH_LIMIT if args.limit is None else args.limit,
            sources=sources,
            skip_candidates=args.skip_candidates,
            require_candidates=getattr(args, "require_candidates", False),
            exclude_items=exclude_items,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Error: batch plan refused ({_batch_error_code(exc)})", file=sys.stderr)
        return 1
    print(json.dumps(plan, sort_keys=True))
    return 0


def cmd_from_batch_response(args: argparse.Namespace) -> int:
    """File valid siblings from one bounded response envelope."""
    try:
        payload = _read_transport_json(args.from_batch_response, max_bytes=MAX_BATCH_BYTES)
        if (not isinstance(payload, dict)
                or payload.get("skip_candidates") is not bool(args.skip_candidates)):
            raise ClassificationPreparationError(
                "CLI and envelope candidate policies do not match",
                code="candidate_policy_mismatch",
            )
        report = file_batch_response(payload, model=args.model or "external-agent")
    except Exception as exc:  # noqa: BLE001
        print(f"Error: batch response refused ({_batch_error_code(exc)})", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


def emit_prompts(
    sources: list[Path], out_dir: Path, *, skip_candidates: bool = False
) -> int:
    """Keyless batch path: write one classification prompt per source plus a
    manifest.json the agent works through via --from-response. Mirrors the
    entity_roster --emit-task pattern."""
    out_dir.mkdir(parents=True, exist_ok=True)
    items = []
    catalog = classifier_ctx.load_context_catalog(REPO_DIR)
    for source_path in sources:
        fm, story_text = load_source_text(source_path)
        if not story_text.strip():
            print(f"Warning: no story text found: {_relative_path(source_path)}", file=sys.stderr)
            continue
        stem = classify_stem(source_path)
        prompt_file = out_dir / f"{stem}.prompt.md"
        snapshot = classifier_ctx.build_context_snapshot_from_catalog(
            REPO_DIR, source_path, catalog
        )
        _path, existing = _existing_classification(source_path)
        mode = classification_mode(snapshot, existing)
        if mode is None:
            continue
        write_text(
            prompt_file,
            build_prompt(
                source_path,
                fm,
                story_text,
                context_snapshot=snapshot,
                mode=mode,
                include_candidates=not skip_candidates,
            ),
        )
        items.append({
            "source": _relative_path(source_path),
            "mode": mode,
            "skip_candidates": skip_candidates,
            "prompt": prompt_file.name,
            "response": f"{stem}.response.json",
            "classification_snapshot": classifier_ctx.snapshot_metadata(snapshot),
        })
    manifest_path = out_dir / "manifest.json"
    write_json(manifest_path, {
        "task": "classify",
        "emitted_at": now_utc(),
        "ingest_command": (
            "python3 system/classify_story.py --from-response <response> --source <source>"
            + (" --skip-candidates" if skip_candidates else "")
        ),
        "items": items,
    })
    print(f"✓ Emitted {len(items)} classification prompt(s) to {out_dir}")
    print(f"  Manifest: {manifest_path}")
    print("  For each item: write the classification JSON to <response>, then run the ingest_command.")
    return 0


def cmd_classify_all(args: argparse.Namespace) -> int:
    """Batch classify all (or unclassified) source files."""
    model = get_model(args)
    sources = all_source_files()

    if args.unclassified:
        catalog = classifier_ctx.load_context_catalog(REPO_DIR) if sources else None
        sources = [s for s in sources if not is_classified(s, context_catalog=catalog)]
    stale_first = bool(getattr(args, "stale_first", False))
    sources = order_targets(
        sources, stale_first=stale_first, cursor=read_classify_cursor())
    if args.limit is not None:
        sources = sources[: max(0, args.limit)]

    if not sources:
        print("No source files to classify.")
        return 0

    if getattr(args, "emit_prompts", None):
        out_dir = Path(args.emit_prompts)
        if not out_dir.is_absolute():
            out_dir = REPO_DIR / out_dir
        rc = emit_prompts(
            sources, out_dir, skip_candidates=getattr(args, "skip_candidates", False)
        )
        # The keyless path is the one that actually starved: nothing is filed
        # here, so without advancing the cursor the same first-N heads are
        # re-emitted every week forever and the tail is never reached.
        if rc == 0 and not args.dry_run:
            write_classify_cursor(sources[-1], run_id="emit-prompts")
        return rc

    action = "Previewing" if args.dry_run else "Classifying"
    print(f"{action} {len(sources)} source file(s) with model={model}")

    errors: list[str] = []
    for i, source_path in enumerate(sources, start=1):
        print(f"\n[{i}/{len(sources)}] {_relative_path(source_path)}")
        rc = classify_file(
            source_path,
            model,
            dry_run=args.dry_run,
            verbose=getattr(args, "verbose", False),
            skip_candidates=getattr(args, "skip_candidates", False),
        )
        if rc != 0:
            errors.append(str(source_path))
        elif not args.dry_run:
            write_classify_cursor(source_path, run_id="classify-all")

    if errors:
        print(f"\n✗ {len(errors)} file(s) failed:")
        for e in errors:
            print(f"  {e}")
        return 1

    done_action = "Previewed" if args.dry_run else "Classified"
    print(f"\n✓ Done. {done_action} {len(sources) - len(errors)} file(s).")
    return 0


def cmd_refresh_targets(args: argparse.Namespace) -> int:
    """Print the canonical bounded classifier-refresh selection as JSON."""
    sources, ineligible = classification_inventory()
    report = classifier_ctx.select_refresh_targets(
        REPO_DIR,
        sources,
        limit=args.limit if args.limit is not None else classifier_ctx.MAX_REFRESH_TARGETS,
    )
    report["inventory_scope"] = "all"
    report["eligible_count"] = len(sources)
    report["ineligible_count"] = len(ineligible)
    report["ineligible_items"] = ineligible
    report["complete"] = bool(report["complete"] and not ineligible)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Classify Lifehug story sources with AI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--classify",
        metavar="SOURCE_PATH",
        help="Classify a single source file.",
    )
    mode.add_argument(
        "--prompt",
        dest="prompt_file",
        metavar="SOURCE_PATH",
        help="Print the AI prompt only (no API call).",
    )
    mode.add_argument(
        "--classify-all",
        action="store_true",
        help="Batch classify source files.",
    )
    mode.add_argument(
        "--from-response",
        metavar="RESPONSE_JSON",
        help="Keyless: ingest an externally-produced classification JSON (requires --source).",
    )
    mode.add_argument(
        "--refresh-targets",
        action="store_true",
        help="Print canonical bounded refresh targets and unfinished count as JSON.",
    )
    mode.add_argument(
        "--batch-plan",
        action="store_true",
        help="Print one bounded canonical archive plan as private JSON (default 50, max 500).",
    )
    mode.add_argument(
        "--from-batch-response",
        metavar="BATCH_JSON",
        help="Validate and file a schema-v1 archive response envelope (max 500 items).",
    )

    parser.add_argument(
        "--unclassified",
        action="store_true",
        help="With --classify-all: skip already-classified files.",
    )
    parser.add_argument(
        "--emit-prompts",
        metavar="DIR",
        help="With --classify-all: keyless agent path — write one prompt per "
             "pending source plus a manifest.json instead of calling AI.",
    )
    parser.add_argument(
        "--stale-first",
        action="store_true",
        help="With --classify-all: run stale classifications first (oldest "
             "first), then never-classified newest-source-first, resuming "
             "after state/classify_cursor.json so the tail is never starved.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="With --classify-all: maximum files to classify. With "
             "--stale-first the cap is spent on stale files first.",
    )
    parser.add_argument(
        "--sources-json",
        metavar="PATH",
        help="With --batch-plan: explicit JSON source list (max 500).",
    )
    parser.add_argument(
        "--exclude-items-json",
        metavar="PATH",
        help="With --batch-plan: exact source/snapshot identities already attempted.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without model calls or writes.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=f"Override the AI model (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--source",
        metavar="SOURCE_PATH",
        help="With --from-response: the source file the response classifies.",
    )
    parser.add_argument(
        "--skip-candidates", "--no-candidates",
        dest="skip_candidates",
        action="store_true",
        help="Explicitly omit and suppress candidate questions (archive backfills only).",
    )
    parser.add_argument(
        "--require-candidates",
        action="store_true",
        help="With a one-source --batch-plan: select an archive reading that skipped candidates.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Extra diagnostic output.",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.require_candidates and not args.batch_plan:
        print("Error: --require-candidates requires --batch-plan", file=sys.stderr)
        return 1
    if args.classify:
        return cmd_classify(args)
    if args.prompt_file:
        return cmd_prompt(args)
    if args.from_response:
        if not args.source:
            print("Error: --from-response requires --source <file>", file=sys.stderr)
            return 1
        return cmd_from_response(args)
    if args.from_batch_response:
        return cmd_from_batch_response(args)
    if args.batch_plan:
        return cmd_batch_plan(args)
    if args.classify_all:
        return cmd_classify_all(args)
    if args.refresh_targets:
        return cmd_refresh_targets(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
