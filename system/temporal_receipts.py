#!/usr/bin/env python3
"""The realized-gain receipt: what a republish actually changed (Cut 4c).

The correction loop (decision record §4.5) ends *"show realized gain or a
recoverable failure"* and names the receipt precisely: *"a before/after diff
of intervals — placed means an interval went from unbounded to bounded;
narrowed means its width decreased. It is computed by the fold, never
written by a model."* §3.6 (`sources/02-review-fable.md`) is the same
promise from the review that produced the ruling. This module is that diff
and its deterministic sentence, in the `cross_dating.render_filing_gain`
style ("Got it — that dates nine moments and your Childhood years.").

**One width, reused, not reinvented.** ADR 0027's width arithmetic —
`timeline._record_width` for a dated interval, `timeline._years_width` for
an undated one — is already the ONE definition placement certainty (Cut 2a,
`temporal_placement.py`) runs over the calculated projection instead of
re-deriving a second one. This module reuses exactly the same call
(`timeline._record_width`), over the same field precedence
`temporal_placement._thing_from_node` already established — a node's own
``best_temporal_value`` first, its ``possible_temporal_value`` (a window,
never a bound) second — so "how wide is this node's interval" can never
answer two different numbers on the same vault. `temporal_placement._is_
scored_node` is reused too, for the identical reason: it is already the
one definition of "a thing whose own placement is in question" (an event
that is not the owner's birth anchor, a named era, a participation
episode) — the birth node and the age-frame ruler it measures against were
never "placed" or "unplaced" in the first place.

**"Bounded" means an interval, not a date.** A node the person never dated
but that a containment placed inside a window (`possible_temporal_value`,
`value_shape == "window"`) has a real, finite interval — narrower than the
undated fallback that has none — so it counts as bounded for this diff
exactly as it does for placement certainty's own width. A node with
neither field (`value_shape == "none"`) is unbounded: no interval, an entry
in ``still_unplaced``, never a width to compare.

**A whole-file diff, not a scheduler.** `diff_projections` takes two whole
projection payloads — the shape `temporal_publication.projection_payload`
writes, or `calculated_view`'s own `{"nodes": [...], ...}` — and produces
one receipt. There is no incremental tracking anywhere: every republish
recomputes the diff against whatever was on disk before the write, exactly
as the projection itself is a whole materialized fold every time (§7).

Controlling contracts: the 2026-09-03 timeline-unification decision record
§3.6 (`sources/02-review-fable.md`), §4.5 ("Correction loop"), §7 Cut 4;
the execution plan's "4c · OSS + platform · Realized-gain receipt; pending
→ published/failed on the page".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import chronology as chrono  # noqa: E402
import cross_dating as cd  # noqa: E402
import temporal_placement as tpl  # noqa: E402
import temporal_store as store  # noqa: E402
import timeline as tl  # noqa: E402
from temporal_claims import TEMPORAL_STATE_DIR, TemporalContractError  # noqa: E402
from vault_paths import atomic_write_vault_text  # noqa: E402

#: This file's own envelope version — the wrapper `write_receipt` adds
#: around `diff_projections`'s pure return, not the projection schema and
#: not the claim schema (the same three-numbers-never-collide discipline
#: `temporal_publication.PUBLICATION_VERSION` follows).
RECEIPT_SCHEMA_VERSION = 1

#: One receipt per published generation, kept — deliberately NOT overwritten
#: the way the projection files are, because a receipt is an audit trail of
#: what THAT publish changed, not a standing snapshot. A distinct directory
#: from `temporal_claims.RECEIPTS_DIR` (`state/temporal_claims/receipts`,
#: keyed by source revision + extractor): that one holds EXTRACTION
#: receipts — evidence that a source was folded — and this one holds
#: PUBLICATION receipts — what a fold changed. Sharing the directory would
#: let a generation number and a source digest collide in one namespace for
#: no reason.
RECEIPTS_DIR = f"{TEMPORAL_STATE_DIR}/publication_receipts"

#: The honest floor for a node whose interval has an open bound
#: (`timeline._record_width` needs a life span only to clamp one of those)
#: on a payload that carries no resolvable owner birth node at all. Never
#: published as a real answer — `temporal_placement.placement_for_
#: projection` refuses to score a birthless vault outright (ADR 0027 rule
#: 8) — this exists only so a receipt about such a vault still reports
#: finite widths instead of raising.
FALLBACK_LIFE_SPAN = (1, 9999)

ERROR_CODES = (
    "receipt_after_required",
    "receipt_generation_unusable",
    "receipt_unreadable",
    "receipt_unwritable",
)


class TemporalReceiptError(TemporalContractError):
    """A realized-gain receipt could not be built, read or written."""


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------


def receipt_relative_path(generation: object) -> str:
    """``state/temporal_claims/publication_receipts/<generation>.json``."""
    try:
        number = int(generation)
    except (TypeError, ValueError) as exc:
        raise TemporalReceiptError(
            "receipt_generation_unusable", f"not a generation: {generation!r}"
        ) from exc
    if number <= 0:
        raise TemporalReceiptError(
            "receipt_generation_unusable", f"non-positive generation: {number}"
        )
    return f"{RECEIPTS_DIR}/{number}.json"


def receipt_path(vault_root: str | Path, generation: object) -> Path:
    """Absolute path of one generation's realized-gain receipt."""
    return store.store_path(vault_root, receipt_relative_path(generation))


# --------------------------------------------------------------------------
# The diff
# --------------------------------------------------------------------------


def _generation_of(payload: object) -> int:
    if not isinstance(payload, dict):
        return 0
    try:
        return int(payload.get("projection_generation") or 0)
    except (TypeError, ValueError):
        return 0


def _node_index(payload: object) -> dict:
    """Every SCORED node (`temporal_placement._is_scored_node`), by id.

    The same population placement certainty counts — episodes, events other
    than the owner's own birth, named eras — never the birth anchor itself
    or an age-frame period, which are the ruler the score is measured
    against rather than things whose own placement is in question.
    """
    if not isinstance(payload, dict):
        return {}
    nodes = payload.get("nodes")
    if not isinstance(nodes, list):
        return {}
    index: dict = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if not tpl._is_scored_node(node):  # noqa: SLF001
            continue
        node_id = node.get("node_id")
        if node_id:
            index[str(node_id)] = node
    return index


def _node_interval(node: object, life: tuple[int, int]) -> dict | None:
    """``{start, end, width}`` from a node's own interval, or ``None`` when
    the node is unbounded (`value_shape == "none"`: neither field set).

    Reuses `timeline._record_width` — the ONE width definition
    (`temporal_placement._thing_from_node`'s own reuse) — over
    ``best_temporal_value`` first and ``possible_temporal_value`` (a window,
    never a bound, but still a real finite interval) second.
    """
    if not isinstance(node, dict):
        return None
    record = node.get("best_temporal_value")
    if record is None:
        record = node.get("possible_temporal_value")
    if record is None:
        return None
    parsed = chrono.from_dict(record)
    if parsed is None:
        return None
    width = tl._record_width(record, life)  # noqa: SLF001
    return {"start": parsed.earliest, "end": parsed.latest, "width": width}


def diff_projections(before: dict | None, after: dict) -> dict:
    """The realized-gain receipt: what changed from ``before`` to ``after``.

    Both are whole projection payloads (`temporal_publication.
    projection_payload`'s own shape, or anything carrying the same
    ``nodes``/``projection_generation`` keys) — ``before`` is ``None`` on a
    vault's first publish, and every currently-bounded node in ``after``
    then counts as ``placed`` (decision record §4.5: *"placed means an
    interval went from unbounded to bounded"*, and absent counts as
    unbounded).

    Returns::

        {
          "generation": int,
          "previous_generation": int | None,
          "placed": [node_id, ...],           # unbounded/absent -> bounded
          "narrowed": [{"node_id", "before": {start,end,width}, "after": {...}}],
          "widened":  [{"node_id", "before": {...}, "after": {...}}],
          "still_unplaced": int,               # unbounded nodes IN `after`
          "summary": {"placed": n, "narrowed": n, "widened": n},
        }

    Deterministic and pure: every list is sorted by node id, and the same
    two payloads always produce the same receipt (generation numbers
    aside, which come from the payloads themselves). ``narrowed`` requires
    the width to have STRICTLY decreased and ``widened`` STRICTLY
    increased — a node whose width is unchanged appears in neither, and an
    honest correction that widens an interval (the decision record's own
    example) is never folded into ``narrowed``.
    """
    if not isinstance(after, dict):
        raise TemporalReceiptError(
            "receipt_after_required", "diff_projections needs an `after` projection"
        )
    life = (
        tpl._life_span(after)  # noqa: SLF001
        or (tpl._life_span(before) if isinstance(before, dict) else None)  # noqa: SLF001
        or FALLBACK_LIFE_SPAN
    )
    after_nodes = _node_index(after)
    before_nodes = _node_index(before) if isinstance(before, dict) else {}

    placed: list[str] = []
    narrowed: list[dict] = []
    widened: list[dict] = []
    still_unplaced = 0

    for node_id in sorted(after_nodes):
        interval_after = _node_interval(after_nodes[node_id], life)
        if interval_after is None:
            still_unplaced += 1
            continue
        interval_before = (
            _node_interval(before_nodes[node_id], life)
            if node_id in before_nodes else None
        )
        if interval_before is None:
            placed.append(node_id)
        elif interval_after["width"] < interval_before["width"]:
            narrowed.append(
                {"node_id": node_id, "before": interval_before, "after": interval_after}
            )
        elif interval_after["width"] > interval_before["width"]:
            widened.append(
                {"node_id": node_id, "before": interval_before, "after": interval_after}
            )

    return {
        "generation": _generation_of(after),
        "previous_generation": (
            _generation_of(before) if isinstance(before, dict) else None
        ),
        "placed": sorted(placed),
        "narrowed": sorted(narrowed, key=lambda row: row["node_id"]),
        "widened": sorted(widened, key=lambda row: row["node_id"]),
        "still_unplaced": still_unplaced,
        "summary": {
            "placed": len(placed),
            "narrowed": len(narrowed),
            "widened": len(widened),
        },
    }


# --------------------------------------------------------------------------
# Reading and writing the file
# --------------------------------------------------------------------------


def _canonical(payload: object) -> str:
    """One serialization, the same convention every other publication file
    in this program uses (`temporal_publication._canonical`): sorted keys,
    stable, newline-ended — so two runs over identical inputs produce
    identical bytes."""
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def write_receipt(vault_root: str | Path, receipt: dict) -> Path:
    """Write one generation's receipt, atomically. THE ONE WRITER.

    Called from `temporal_publication.publish`, after the projection and
    work-item files have landed — never before, and never as part of the
    same `_write` pass those two share, so a crash between the projection
    pair and the receipt leaves the truth current and only the audit trail
    one step behind, the identical shape `PUBLICATION_ORDER`'s own ordering
    guarantee already gives the work-item slice.
    """
    payload = dict(receipt)
    payload.setdefault("schema_version", RECEIPT_SCHEMA_VERSION)
    path = receipt_path(vault_root, payload.get("generation"))
    try:
        atomic_write_vault_text(path, _canonical(payload), vault_root=Path(vault_root))
    except (OSError, ValueError) as exc:
        raise TemporalReceiptError("receipt_unwritable", str(exc)) from exc
    return path


def read_receipt(vault_root: str | Path, generation: object) -> dict | None:
    """One generation's receipt, or ``None`` when it was never published."""
    path = receipt_path(vault_root, generation)
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise TemporalReceiptError("receipt_unreadable", str(exc)) from exc
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        raise TemporalReceiptError("receipt_unreadable", f"not JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise TemporalReceiptError("receipt_unreadable", "receipt is not an object")
    return value


def latest_receipt_generation(vault_root: str | Path) -> int | None:
    """The highest generation this vault holds a receipt for, or ``None``."""
    base = store.store_path(vault_root, RECEIPTS_DIR)
    if not base.is_dir():
        return None
    numbers: list[int] = []
    for entry in base.iterdir():
        if entry.is_file() and entry.suffix == ".json":
            try:
                numbers.append(int(entry.stem))
            except ValueError:
                continue
    return max(numbers) if numbers else None


# --------------------------------------------------------------------------
# The sentence
# --------------------------------------------------------------------------


def _nonneg_int(value: object) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _clause_join(clauses: list[str]) -> str:
    if len(clauses) == 1:
        return clauses[0]
    if len(clauses) == 2:
        return f"{clauses[0]} and {clauses[1]}"
    return f"{', '.join(clauses[:-1])}, and {clauses[-1]}"


def render_realized_gain(
    receipt: dict, *, moved_label: str | None = None, target_label: str | None = None
) -> str:
    """The realized-gain sentence, in the `cross_dating.render_filing_gain`
    style — deterministic, never a model call.

    *"Moved 'College graduation' into North Desert Village. That narrowed
    three related stories and placed one. Two items still need placing."*

    ``moved_label``/``target_label`` are display names for the correction
    that triggered this publish (a drag's subject and its new container);
    given together they prefix "Moved '{X}' into {Y}." — given alone,
    neither is used, because "Moved into Y." and "Moved 'X'." both promise
    more than they say. With neither, or when nothing moved at all, the
    sentence opens with what changed: "Nothing else moved." when the
    summary is empty, or "That {clauses}." otherwise. A trailing "N item(s)
    still need(s) placing." names what is left ONLY when ``still_unplaced``
    is nonzero — the count of what remains is never invented where there is
    none, the same restraint `cross_dating.gain_sentence` already keeps.
    """
    row = receipt if isinstance(receipt, dict) else {}
    summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
    placed = _nonneg_int(summary.get("placed"))
    narrowed = _nonneg_int(summary.get("narrowed"))
    widened = _nonneg_int(summary.get("widened"))
    still_unplaced = _nonneg_int(row.get("still_unplaced"))

    moved = " ".join(str(moved_label or "").split())
    target = " ".join(str(target_label or "").split())
    prefix = f"Moved '{moved}' into {target}. " if moved and target else ""

    clauses: list[str] = []
    if narrowed:
        clauses.append(
            f"narrowed {cd.spoken_count(narrowed)} related "
            f"{'story' if narrowed == 1 else 'stories'}"
        )
    if placed:
        clauses.append(f"placed {cd.spoken_count(placed)}")
    if widened:
        clauses.append(f"widened {cd.spoken_count(widened)}")

    body = f"That {_clause_join(clauses)}." if clauses else "Nothing else moved."

    tail = ""
    if still_unplaced:
        noun = "item" if still_unplaced == 1 else "items"
        verb = "needs" if still_unplaced == 1 else "need"
        tail = (
            f" {cd.spoken_count(still_unplaced).capitalize()} {noun} "
            f"still {verb} placing."
        )

    return f"{prefix}{body}{tail}"


__all__ = [
    "ERROR_CODES",
    "FALLBACK_LIFE_SPAN",
    "RECEIPTS_DIR",
    "RECEIPT_SCHEMA_VERSION",
    "TemporalReceiptError",
    "diff_projections",
    "latest_receipt_generation",
    "read_receipt",
    "receipt_path",
    "receipt_relative_path",
    "render_realized_gain",
    "write_receipt",
]
