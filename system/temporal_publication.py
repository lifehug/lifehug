#!/usr/bin/env python3
"""Publishing the calculated timeline: one compile, one drawing, one truth (v231).

Wave D item D3 of the audited final timeline build plan. Wave D built the pure
derivation (`temporal_timeline.derive_calculated_timeline` — active claims in,
a whole calculated timeline out, no I/O anywhere) and wave F built the reader
that turns published work items into daily questions
(`question_planner.work_items_from_projection`). Between them was a gap the
size of a file: nothing ever WROTE the projection, so the derivation was
correct and unreachable and the queue read an empty door. This module is that
write, and it is what makes the derivation load-bearing.

Plan §7 states the contract in four sentences and every one of them is a rule
here:

**A whole materialized projection.** :func:`publish` derives the entire
timeline from the entire active claim index. There is no node-level dirty
scheduler, no partial refresh, and no incremental path — §7 forbids putting one
on the critical path before wave H's measured gate, and the whole-file publish
is what keeps the clean rebuild the correctness oracle rather than a fallback.

**Atomic publication.** *"Readers see the prior complete generation or the next
complete generation, never a partial mix."* Each file lands through
``atomic_write_vault_text`` (temp + rename inside the vault), so no reader ever
sees half a file. Two files cannot share one rename, so the ORDER carries the
rest of the guarantee — see :data:`PUBLICATION_ORDER`.

**Generation.** Every publication carries a number one higher than any number
already on disk (:func:`published_generation` takes the MAX across both files,
precisely so a torn publication cannot make the counter go backwards). It is
stamped on the envelope AND on every node, which is how a stale reader is
recognizable instead of merely wrong.

**A clean full rebuild is always supported and remains the correctness
oracle.** Delete both files, publish again, and the result is identical apart
from the metadata §7 explicitly excludes. :func:`rebuild_signature` names those
exclusions rather than leaving each caller to guess them — it is the on-disk
twin of ``temporal_timeline.structural_signature``, which does the same job for
an in-memory result.

WHERE THIS RUNS. Nowhere new. The one seat is ``timeline.redraw_landmarks`` —
the flip's redraw (wave B item B3) — so a vault gets its landmark drawing and
its calculated timeline from the same trigger, over the same substrate, in the
same call. A second trigger would be a second answer to "when is the truth
current?", which is the dual-truth the flip removed. ``update.py``'s versioned
migration seat publishes once at upgrade so an existing vault arrives with a
projection rather than waiting for its next landmark write.

WHAT THIS DOES NOT DO. It does not replace ``timeline.timeline_data``'s own
derivation. That derivation is still the serving view for the Timeline page;
the calculated projection rides beside it this wave, exposed additively as
``timeline_data()["calculated"]``. Replacing the legacy derivation is a
deliberate later cutover with its own contract, not a side effect of learning
to write a file.

Ordering constraints — what a drag writes — got their home in v232
(``temporal_store.load_ordering_constraints``), and the publisher now READS it:
``constraints=None`` (the default) means "whatever this vault's filed moves
say", so the drag transaction's republish (plan §8.4 step 7) is the seat that
already exists rather than a second one. Passing an explicit sequence still
overrides, and passing ``()`` still means "none" — a test deriving over a
hand-built substrate is not silently given the vault's. Resolution records
(wave C's identity verdicts) have no vault storage yet; the derivation accepts
them and this module passes whatever its caller supplies.

Controlling contract: the audited final timeline build plan §3, §7, §7.1, §10
("Rebuild, parity, and operations"), wave D.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import era_identity as ei  # noqa: E402
import event_binding as eb  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_store as store  # noqa: E402
import temporal_timeline as tt  # noqa: E402
from temporal_claims import (  # noqa: E402
    SCHEMA_VERSION,
    TemporalContractError,
    normalized_timestamp,
)
from vault_paths import atomic_write_vault_text  # noqa: E402

# --------------------------------------------------------------------------
# Layout and vocabulary
# --------------------------------------------------------------------------

#: The published envelope's own schema version, and the `version` field
#: ``vault_contract.json`` validates both files against. It is NOT
#: :data:`~temporal_claims.SCHEMA_VERSION`: the records inside are frozen by
#: that one, while this covers the wrapper the publisher adds around them.
PUBLICATION_VERSION = 1

#: The projection, whole. `temporal_timeline.CalculatedTimeline.to_dict()`
#: inside a publication envelope.
PROJECTION_FILE = tp.PROJECTION_FILE

#: The queue's door. Deliberately a SLICE of the same generation rather than a
#: second derivation: `question_planner.work_items_from_projection` needs
#: `work_items` and `reach` and nothing else, and reading a small file on the
#: weekly planner's path should not mean parsing every node.
WORK_ITEMS_FILE = tp.WORK_ITEMS_FILE

#: **The order is the atomicity guarantee, and it is one way round.**
#:
#: Two files cannot land in one rename, so a crash between them is a real
#: state and the only question is which half is allowed to be ahead. The
#: projection goes first and the queue's slice goes last, so the torn state is
#: always "the truth is current, the queue is one generation behind" — a queue
#: that under-offers for a moment. The reverse order produces "the queue asks
#: about nodes the published truth does not contain yet", which is a question
#: about something the person cannot see.
#:
#: Both halves are re-runnable: :func:`published_generation` takes the max
#: across the files, so re-publishing after a tear mints a number above BOTH
#: and lands a matched pair.
PUBLICATION_ORDER = (PROJECTION_FILE, WORK_ITEMS_FILE)

#: §7's *"explicitly excluded runtime metadata"*, at the envelope level: when
#: the publication happened, how long each phase took, and which publication
#: this was. Content identity is what the substrate implies, not when it was
#: written down or how many times it has been written down before.
EXCLUDED_ENVELOPE_KEYS = (
    "published_at",
    "timings",
    "projection_generation",
    "version",
    "schema_version",
    "counts",
    "input_digest",
)

#: The same exclusion inside a node: the generation stamp. Everything else a
#: node carries — including its `input_fingerprint` — is derived and must
#: match across a rebuild.
EXCLUDED_NODE_KEYS = ("projection_generation",)

#: And inside a work item: the wall-clock stamps a queue needs.
#: ``temporal_timeline.structural_signature`` excludes exactly these two.
EXCLUDED_WORK_ITEM_KEYS = ("created_at", "updated_at")

#: Phase timings surfaced into the compile report (§7.1). The derivation's own
#: phases, plus the two this module owns.
PUBLICATION_PHASES = ("fold", "publish")

ERROR_CODES = (
    "publication_unreadable",
    "publication_unwritable",
    "publication_generation_unusable",
)


class TemporalPublicationError(TemporalContractError):
    """A publication could not be read or could not be written."""


# --------------------------------------------------------------------------
# Paths and reads
# --------------------------------------------------------------------------


def projection_path(vault_root: str | Path) -> Path:
    """Absolute path of the published projection in this vault."""
    return store.store_path(vault_root, PROJECTION_FILE)


def work_items_path(vault_root: str | Path) -> Path:
    """Absolute path of the published work-item slice in this vault."""
    return store.store_path(vault_root, WORK_ITEMS_FILE)


def _read(vault_root: str | Path, relative: str) -> dict | None:
    path = store.store_path(vault_root, relative)
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise TemporalPublicationError("publication_unreadable", str(exc)) from exc
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        raise TemporalPublicationError(
            "publication_unreadable", f"{relative} is not JSON: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise TemporalPublicationError(
            "publication_unreadable", f"{relative} is not an object"
        )
    return value


def read_projection(vault_root: str | Path) -> dict | None:
    """The published projection, or ``None`` when nothing has been published."""
    return _read(vault_root, PROJECTION_FILE)


def read_work_items(vault_root: str | Path) -> dict | None:
    """The published work-item slice, or ``None``. The shape wave F reads."""
    return _read(vault_root, WORK_ITEMS_FILE)


def _generation_of(payload: object) -> int:
    if not isinstance(payload, dict):
        return 0
    value = payload.get("projection_generation")
    if value is None:
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise TemporalPublicationError(
            "publication_generation_unusable", f"not a generation: {value!r}"
        ) from exc
    if number < 0:
        raise TemporalPublicationError(
            "publication_generation_unusable", f"negative generation: {number}"
        )
    return number


def published_generation(vault_root: str | Path) -> int:
    """The highest generation any published file in this vault carries.

    The MAX across both files, not the projection's alone, so a publication
    torn between the two renames can never be followed by one that re-uses a
    number already on disk. ``0`` means nothing has been published.
    """
    return max(
        _generation_of(read_projection(vault_root)),
        _generation_of(read_work_items(vault_root)),
    )


def next_generation(vault_root: str | Path) -> int:
    """The number the next publication will carry. Strictly monotonic."""
    return published_generation(vault_root) + 1


# --------------------------------------------------------------------------
# The payloads
# --------------------------------------------------------------------------


def _canonical(payload: object) -> str:
    """One serialization for both files: sorted keys, stable, newline-ended.

    The store's own convention (`temporal_store.active_index_bytes`), for the
    same reason: two runs over identical inputs must produce identical bytes,
    or a rebuild oracle can only ever compare parsed values.
    """
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def reached_frame_epoch(result: object) -> dict:
    """`{count, current}` — which age frames the person has reached (§3.4).

    The epoch is what makes "nothing moved" decidable without persisting
    ``as_of``: two publications on different days inside one epoch imply the
    same frames, and crossing a birthday boundary changes the count and the
    current band. It rides the ENVELOPE, which puts it inside
    :func:`rebuild_signature` by that function's own rule — one comparison, not
    a second definition sitting beside it.
    """
    nodes = result.nodes if isinstance(result, tt.CalculatedTimeline) else (
        (result or {}).get("nodes") or () if isinstance(result, dict) else ()
    )
    frames = [row for row in nodes
              if isinstance(row, dict) and row.get("event_kind") == tp.AGE_FRAME_EVENT_KIND]
    current = next((row for row in frames if row.get("life_clip_end") == "present"), None)
    band = None
    if current is not None:
        band = str(current.get("node_id") or "").rpartition(":")[2] or None
    return {"count": len(frames), "current": band}


def _envelope(result: tt.CalculatedTimeline, *, published_at: str, input_digest: str,
              timings: dict) -> dict:
    return {
        "version": PUBLICATION_VERSION,
        "schema_version": SCHEMA_VERSION,
        "projection_schema_version": tp.PROJECTION_SCHEMA_VERSION,
        "reached_frame_epoch": reached_frame_epoch(result),
        "projection_generation": result.projection_generation,
        "published_at": published_at,
        "calculation_rule_version": result.calculation_rule_version,
        "score_formula_version": result.score_formula_version,
        "input_digest": input_digest,
        "timings": {key: round(float(value), 9) for key, value in sorted(timings.items())},
    }


def projection_payload(result: tt.CalculatedTimeline, *, published_at: str,
                       input_digest: str, timings: dict) -> dict:
    """The whole projection, enveloped. §7's *whole materialized projection*."""
    body = result.to_dict()
    payload = _envelope(result, published_at=published_at, input_digest=input_digest,
                        timings=timings)
    payload.update(body)
    payload["memberships"] = [dict(row) for row in result.memberships]
    payload["counts"] = {
        "claims": int((result.diagnostics or {}).get("claims") or 0),
        "nodes": len(result.nodes),
        "work_items": len(result.work_items),
        "unplaced": len((result.diagnostics or {}).get("unplaced") or ()),
    }
    return payload


def work_items_payload(result: tt.CalculatedTimeline, *, published_at: str,
                       input_digest: str, timings: dict) -> dict:
    """The queue's slice of the same generation.

    Exactly the keys `question_planner.work_items_from_projection` consumes —
    ``work_items`` and ``reach`` — plus the envelope that lets a reader tell
    WHICH generation it is holding. ``score_components`` rides along because
    §8.5's queue is required to be able to explain itself, and re-deriving the
    components on the read side would be a second scorer.
    """
    payload = _envelope(result, published_at=published_at, input_digest=input_digest,
                        timings=timings)
    payload["work_items"] = [dict(row) for row in result.work_items]
    payload["reach"] = dict(result.reach)
    payload["score_components"] = {
        key: dict(value) for key, value in result.score_components.items()
    }
    payload["counts"] = {"work_items": len(result.work_items)}
    return payload


def rebuild_signature(payload: object) -> dict:
    """A published file reduced to what a rebuild must reproduce exactly.

    The on-disk twin of ``temporal_timeline.structural_signature``, and it
    exists for the same reason: §7's *"structurally identical output apart from
    explicitly excluded runtime metadata"* is only testable if the exclusions
    are named in one place. They are :data:`EXCLUDED_ENVELOPE_KEYS`,
    :data:`EXCLUDED_NODE_KEYS` and :data:`EXCLUDED_WORK_ITEM_KEYS`.

    The generation is excluded deliberately and it is the interesting one: a
    clean rebuild after deleting the files starts counting again, so keeping
    the generation in the comparison would make the oracle assert that repair
    is impossible. Generation says which publication this is; the signature
    says what the substrate implies. Only the second one is derived.
    """
    row = payload if isinstance(payload, dict) else {}
    signature = {
        key: value
        for key, value in row.items()
        if key not in EXCLUDED_ENVELOPE_KEYS
    }
    if isinstance(row.get("nodes"), list):
        signature["nodes"] = [
            {k: v for k, v in node.items() if k not in EXCLUDED_NODE_KEYS}
            if isinstance(node, dict) else node
            for node in row["nodes"]
        ]
    if isinstance(row.get("work_items"), list):
        signature["work_items"] = [
            {k: v for k, v in item.items() if k not in EXCLUDED_WORK_ITEM_KEYS}
            if isinstance(item, dict) else item
            for item in row["work_items"]
        ]
    return signature


# --------------------------------------------------------------------------
# The publication
# --------------------------------------------------------------------------


def _write(vault_root: str | Path, relative: str, text: str) -> Path:
    path = store.store_path(vault_root, relative)
    try:
        atomic_write_vault_text(path, text, vault_root=Path(vault_root))
    except (OSError, ValueError) as exc:
        raise TemporalPublicationError("publication_unwritable", str(exc)) from exc
    return path


def publish(
    vault_root: str | Path,
    *,
    active_index: object = None,
    resolution_records: object = (),
    event_resolution_records: object = None,
    era_views: object = None,
    roster_snapshot: object = (),
    constraints: object = None,
    birth_date: object = None,
    owner_ref: object = None,
    now: object = None,
) -> dict:
    """Derive the whole calculated timeline and publish it. THE ONE WRITER.

    Returns a summary — generation, counts, the files it wrote, and the §7.1
    phase timings — which is what a compile log prints (see
    :func:`publication_report_line`) rather than a caller re-measuring.

    ``active_index`` defaults to a fresh fold of this vault's receipts and
    corrections, which is also what re-publishes the index itself; pass one in
    when the caller has already folded and wants exactly that generation.

    ``constraints`` defaults to this vault's filed moves (v232). ``None`` is
    "read them", an explicit sequence is "use exactly these", and ``()`` is
    "none" — the distinction matters because a drag's republish must pick up the
    move that was just filed without every caller remembering to load it.
    """
    started = time.perf_counter()
    timings: dict[str, float] = {}

    mark = time.perf_counter()
    index = (
        active_index
        if active_index is not None
        else store.rebuild_active_index(vault_root)
    )
    timings["fold"] = time.perf_counter() - mark

    if constraints is None:
        constraints = store.active_ordering_constraints(vault_root)
    if event_resolution_records is None:
        # `None` means "read them", exactly as it does for `constraints` above
        # and for the same reason: the act that files a binding must publish a
        # projection that HAS it, without every caller remembering to load the
        # record it just wrote. `()` still means "none".
        event_resolution_records = eb.load_event_resolutions(vault_root)
    if era_views is None:
        # Same `None` means "read them" rule as `constraints` above: the act
        # that creates an era must publish a projection that HAS it.
        era_views = ei.era_views(vault_root)

    generation = next_generation(vault_root)
    result = tt.derive_calculated_timeline(
        index,
        resolution_records=resolution_records,
        event_resolution_records=event_resolution_records,
        era_views=era_views,
        roster_snapshot=roster_snapshot,
        constraints=constraints,
        birth_date=birth_date,
        owner_ref=owner_ref,
        projection_generation=generation,
        now=now,
    )
    timings.update(result.timings or {})

    published_at = normalized_timestamp(now, error=TemporalPublicationError)
    digest = store.payload_sha256(_canonical(index if isinstance(index, dict) else list(index)))

    mark = time.perf_counter()
    payloads = {
        PROJECTION_FILE: projection_payload(
            result, published_at=published_at, input_digest=digest, timings=timings
        ),
        WORK_ITEMS_FILE: work_items_payload(
            result, published_at=published_at, input_digest=digest, timings=timings
        ),
    }

    # THE SEMANTIC NO-OP (eras design §3.4). Age frames make the projection a
    # function of the clock as well as of the receipts, so "publish again"
    # would otherwise mint a generation every single day and nobody could tell
    # a frame boundary from a heartbeat. When the standing pair says exactly
    # what the fresh render says, this writes nothing and mints nothing.
    standing = _unchanged_generation(vault_root, payloads)
    if standing is not None:
        timings["publish"] = time.perf_counter() - mark
        timings["publication_total"] = time.perf_counter() - started
        return _summary(result, generation=standing, unchanged=True,
                        published_at=str(_published_at_of(vault_root) or published_at),
                        digest=digest, timings=timings,
                        paths=[str(store.store_path(vault_root, name))
                               for name in PUBLICATION_ORDER])

    # Serialize BOTH before writing EITHER: a payload that cannot be rendered
    # must fail with nothing on disk changed, not halfway through the pair.
    rendered = {name: _canonical(payload) for name, payload in payloads.items()}
    written = [str(_write(vault_root, name, rendered[name])) for name in PUBLICATION_ORDER]
    timings["publish"] = time.perf_counter() - mark
    timings["publication_total"] = time.perf_counter() - started

    return _summary(result, generation=generation, unchanged=False,
                    published_at=published_at, digest=digest, timings=timings,
                    paths=written)


def _published_at_of(vault_root: str | Path) -> str | None:
    payload = read_projection(vault_root)
    return (payload or {}).get("published_at")


def _unchanged_generation(vault_root: str | Path, payloads: dict) -> int | None:
    """The standing generation when a republish would say nothing new.

    All four conditions, and none of them is optional:

    1. both files are present and readable,
    2. they carry the SAME generation — a publication torn between the two
       renames is never a no-op, because repairing the tear is exactly what
       `published_generation`'s max exists for,
    3. the projection's signature matches, and
    4. the queue slice's signature matches.

    :func:`rebuild_signature` already excludes the generation, the timings, the
    publication timestamp and the input digest, so this compares what the
    substrate IMPLIES — including the reached-frame epoch, which rides the
    envelope for exactly this reason.
    """
    published = read_projection(vault_root)
    queue = read_work_items(vault_root)
    if published is None or queue is None:
        return None
    generation = _generation_of(published)
    if generation <= 0 or generation != _generation_of(queue):
        return None
    if rebuild_signature(payloads[PROJECTION_FILE]) != rebuild_signature(published):
        return None
    if rebuild_signature(payloads[WORK_ITEMS_FILE]) != rebuild_signature(queue):
        return None
    return generation


def _summary(result: tt.CalculatedTimeline, *, generation: int, unchanged: bool,
             published_at: str, digest: str, timings: dict, paths: list) -> dict:
    return {
        "generation": generation,
        "unchanged": unchanged,
        "published_at": published_at,
        "input_digest": digest,
        "files": list(PUBLICATION_ORDER),
        "paths": list(paths),
        "claims": int((result.diagnostics or {}).get("claims") or 0),
        "nodes": len(result.nodes),
        "work_items": len(result.work_items),
        "unplaced": len((result.diagnostics or {}).get("unplaced") or ()),
        "timings": {key: round(float(value), 9) for key, value in sorted(timings.items())},
    }


def publication_report_line(summary: object) -> str:
    """One line for the compile log, carrying §7.1's phase timings.

    §7.1 asks for the phases to be instrumented *separately* — the fold, the
    derivation's own steps, and the publication — because the decision to ever
    build incremental recomputation (wave H) is a measured one and a single
    total tells nobody which phase to attack.
    """
    row = summary if isinstance(summary, dict) else {}
    timings = row.get("timings") if isinstance(row.get("timings"), dict) else {}
    phases = ", ".join(
        f"{name} {float(value) * 1000:.0f}ms" for name, value in sorted(timings.items())
    )
    # A compile log that says "generation 1" after writing nothing would be a
    # lie of omission — the whole point of the no-op is that it is visible.
    unchanged = " (unchanged — nothing written)" if row.get("unchanged") else ""
    return (
        f"calculated timeline generation {row.get('generation')}{unchanged}: "
        f"{row.get('nodes')} node(s), {row.get('work_items')} work item(s) "
        f"from {row.get('claims')} active claim(s)"
        + (f" [{phases}]" if phases else "")
    )


# --------------------------------------------------------------------------
# The additive read model
# --------------------------------------------------------------------------

#: What :func:`calculated_view` returns when nothing has been published, or
#: when the published file cannot be read. Absent is stated, never faked: a
#: reader can tell "no projection yet" from "a projection with no nodes".
EMPTY_VIEW = {
    "published": False,
    "projection_generation": 0,
    "published_at": None,
    "schema_version": tp.PROJECTION_SCHEMA_VERSION,
    "calculation_rule_version": tt.CALCULATION_RULE_VERSION,
    "score_formula_version": tt.SCORE_FORMULA_VERSION,
    "nodes": (),
    "work_items": (),
    "memberships": (),
    "reach": {},
    "reached_frame_epoch": {"count": 0, "current": None},
    "counts": {"nodes": 0, "work_items": 0, "claims": 0, "unplaced": 0},
}


def calculated_view(vault_root: str | Path) -> dict:
    """The published projection, shaped for a page. Read, never derive.

    This is what ``timeline.timeline_data()["calculated"]`` exposes. It READS
    the published generation rather than deriving one, which is the whole point
    of a materialized projection: the page is cheap, and what it shows is
    exactly what was published — the same bytes the queue read.
    """
    payload = read_projection(vault_root)
    if payload is None:
        return dict(EMPTY_VIEW)
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    epoch = payload.get("reached_frame_epoch")
    return {
        "published": True,
        "projection_generation": _generation_of(payload),
        "published_at": payload.get("published_at"),
        # TOLERANT BY CONSTRUCTION (eras design §7.8 step 1): a v1 payload has
        # no `projection_schema_version` key and no v2 node fields, and reads
        # here as schema 1 with the same nodes. Absent means unchanged; it never
        # means unreadable.
        "schema_version": int(payload.get("projection_schema_version") or 1),
        "calculation_rule_version": payload.get("calculation_rule_version"),
        "score_formula_version": payload.get("score_formula_version"),
        "nodes": tuple(payload.get("nodes") or ()),
        "work_items": tuple(payload.get("work_items") or ()),
        "memberships": tuple(payload.get("memberships") or ()),
        "reach": dict(payload.get("reach") or {}),
        "reached_frame_epoch": dict(epoch) if isinstance(epoch, dict) else {
            "count": 0, "current": None
        },
        "counts": {
            "nodes": int(counts.get("nodes") or len(payload.get("nodes") or ())),
            "work_items": int(
                counts.get("work_items") or len(payload.get("work_items") or ())
            ),
            "claims": int(counts.get("claims") or 0),
            "unplaced": int(counts.get("unplaced") or 0),
        },
    }


# --------------------------------------------------------------------------
# The rebuild oracle
# --------------------------------------------------------------------------


def verify(
    vault_root: str | Path,
    *,
    resolution_records: object = (),
    event_resolution_records: object = None,
    era_views: object = None,
    roster_snapshot: object = (),
    constraints: object = None,
    birth_date: object = None,
    owner_ref: object = None,
    now: object = None,
) -> dict:
    """Does the published projection still reproduce from the substrate?

    §7's oracle, run WITHOUT publishing: fold the receipts again, derive again,
    and compare :func:`rebuild_signature` against the file on disk. A mismatch
    means the published generation no longer follows from the vault's evidence
    — either the substrate moved since it was published, or something wrote a
    projection that was never derived.

    Non-mutating apart from the active index, which is itself a materialized
    view that `rebuild_active_index` is defined to be able to rewrite at any
    time ("deleting the file first must change nothing").
    """
    published = read_projection(vault_root)
    if published is None:
        return {"published": False, "identical": False, "generation": 0}
    index = store.rebuild_active_index(vault_root)
    if constraints is None:
        constraints = store.active_ordering_constraints(vault_root)
    if event_resolution_records is None:
        # `None` means "read them", exactly as it does for `constraints` above
        # and for the same reason: the act that files a binding must publish a
        # projection that HAS it, without every caller remembering to load the
        # record it just wrote. `()` still means "none".
        event_resolution_records = eb.load_event_resolutions(vault_root)
    if era_views is None:
        # Same `None` means "read them" rule as `constraints` above: the act
        # that creates an era must publish a projection that HAS it.
        era_views = ei.era_views(vault_root)
    result = tt.derive_calculated_timeline(
        index,
        resolution_records=resolution_records,
        event_resolution_records=event_resolution_records,
        era_views=era_views,
        roster_snapshot=roster_snapshot,
        constraints=constraints,
        birth_date=birth_date,
        owner_ref=owner_ref,
        projection_generation=_generation_of(published),
        now=now,
    )
    fresh = projection_payload(
        result,
        published_at=str(published.get("published_at") or ""),
        input_digest=str(published.get("input_digest") or ""),
        timings=dict(result.timings or {}),
    )
    want, have = rebuild_signature(fresh), rebuild_signature(published)
    return {
        "published": True,
        "generation": _generation_of(published),
        "identical": want == have,
        "differences": sorted(
            key for key in set(want) | set(have) if want.get(key) != have.get(key)
        ),
    }


def main(argv: list[str] | None = None) -> int:
    """`python3 system/temporal_publication.py` — publish, repair, or check.

    The repair path §7 names ("a clean full rebuild is always supported and
    remains the correctness oracle") deserves to be a command rather than a
    paragraph, so ``--rebuild`` deletes both files and publishes from nothing.
    """
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        description="Publish the calculated timeline projection (plan §7)."
    )
    parser.add_argument("--vault-root", default=None,
                        help="the vault to publish (default: this process's vault)")
    parser.add_argument("--rebuild", action="store_true",
                        help="delete both published files first — the clean-rebuild repair path")
    parser.add_argument("--check", action="store_true",
                        help="verify the published projection still reproduces; write nothing")
    args = parser.parse_args(argv)

    if args.vault_root:
        root: str | Path = args.vault_root
    else:
        from lifehug_core import REPO_DIR  # noqa: PLC0415

        root = REPO_DIR

    if args.check:
        report = verify(root)
        if not report["published"]:
            print("No calculated timeline has been published yet.")
            return 1
        if report["identical"]:
            print(f"Generation {report['generation']} reproduces exactly.")
            return 0
        print(
            f"Generation {report['generation']} does NOT reproduce; "
            f"differs in: {', '.join(report['differences']) or '(unknown)'}"
        )
        return 1

    if args.rebuild:
        for relative in PUBLICATION_ORDER:
            store.store_path(root, relative).unlink(missing_ok=True)
    print(publication_report_line(publish(root)))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "EMPTY_VIEW",
    "EXCLUDED_ENVELOPE_KEYS",
    "EXCLUDED_NODE_KEYS",
    "EXCLUDED_WORK_ITEM_KEYS",
    "PROJECTION_FILE",
    "PUBLICATION_ORDER",
    "PUBLICATION_PHASES",
    "PUBLICATION_VERSION",
    "WORK_ITEMS_FILE",
    "TemporalPublicationError",
    "calculated_view",
    "next_generation",
    "projection_path",
    "projection_payload",
    "publication_report_line",
    "publish",
    "published_generation",
    "read_projection",
    "read_work_items",
    "rebuild_signature",
    "verify",
    "work_items_path",
    "work_items_payload",
]
