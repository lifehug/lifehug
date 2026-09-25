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

Cut 4c (timeline-unification decision record §4.5, §7 Cut 4) adds one more
file to what a real publish writes: `temporal_receipts.write_receipt` files
the realized-gain receipt — the before/after diff of this publish against
whatever was published previously — after the projection pair lands. It is
not part of :data:`PUBLICATION_ORDER`'s own atomicity guarantee (see
:func:`publish`); a reader that only needs the truth is unaffected either
way.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

SYSTEM_DIR = Path(__file__).resolve().parent
if str(SYSTEM_DIR) not in sys.path:
    sys.path.insert(0, str(SYSTEM_DIR))

import chronology as chrono  # noqa: E402
import episode_fold as ef  # noqa: E402
import episode_fold_contract as efc  # noqa: E402
import era_identity as ei  # noqa: E402
import era_memberships as era  # noqa: E402
import event_binding as eb  # noqa: E402
import identity_resolution as ident  # noqa: E402
import landmark_projection as lp  # noqa: E402
import relation_words as rw  # noqa: E402
import temporal_placement as tpl  # noqa: E402
import temporal_projection as tp  # noqa: E402
import temporal_receipts as trcpt  # noqa: E402
import temporal_store as store  # noqa: E402
import temporal_timeline as tt  # noqa: E402
import temporal_work_items as twi  # noqa: E402
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
#: v328: 2 — the envelope gained ``owner_identity_digest``. `_rule_identity`
#: folds this number, so the bump itself is what re-derives every standing
#: generation once and stamps the digest on it.
PUBLICATION_VERSION = 2

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

#: v318. What the STANDING generation was derived from, beside the pair it
#: describes. The semantic no-op below has always been able to say "this
#: republish says nothing new" — but only after deriving the whole projection
#: to compare against. On a 9,000-claim vault that derivation is seconds of
#: work to reach a conclusion the inputs already imply, and a compile runs it
#: on every pass. This file lets `publish` reach the same conclusion from the
#: inputs alone.
#:
#: It is a cache of a DECISION, never of content: nothing here is ever served
#: to a reader, and every field it holds is re-derived and re-compared before
#: it is believed. Missing, stale or unreadable costs one ordinary derive.
PUBLICATION_CACHE_FILE = f"{tp.TEMPORAL_STATE_DIR}/publication-cache.json"
PUBLICATION_CACHE_VERSION = 1

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
              timings: dict, owner_identity_digest: str | None = None) -> dict:
    envelope = {
        "version": PUBLICATION_VERSION,
        "schema_version": SCHEMA_VERSION,
        "projection_schema_version": tp.projection_schema_version(),
        "reached_frame_epoch": reached_frame_epoch(result),
        "projection_generation": result.projection_generation,
        "published_at": published_at,
        "calculation_rule_version": result.calculation_rule_version,
        "score_formula_version": result.score_formula_version,
        "input_digest": input_digest,
        "timings": {key: round(float(value), 9) for key, value in sorted(timings.items())},
    }
    if owner_identity_digest is not None:
        # v328: WHICH owner identity folded this generation (see
        # :func:`owner_identity_digest`). Derived from the fold's inputs, so it
        # is part of the rebuild signature, never excluded runtime metadata.
        envelope["owner_identity_digest"] = str(owner_identity_digest)
    return envelope


def projection_payload(result: tt.CalculatedTimeline, *, published_at: str,
                       input_digest: str, timings: dict,
                       owner_identity_digest: str | None = None) -> dict:
    """The whole projection, enveloped. §7's *whole materialized projection*.

    ``owner_identity_digest`` (v328) is stamped when given; :func:`publish` and
    :func:`verify` always give it. A caller building a payload from a fold it
    made itself passes the digest of the inputs IT used, or nothing at all —
    never a guess.
    """
    body = result.to_dict()
    payload = _envelope(result, published_at=published_at, input_digest=input_digest,
                        timings=timings, owner_identity_digest=owner_identity_digest)
    payload.update(body)
    # PR342: one explicit host-facing answer, derived from the same predicate
    # that owns work items and counts. Clients must not reconstruct this from
    # value shape, width, temporal_state, or the presence of a possible value.
    payload["nodes"] = [
        {
            **dict(node),
            "usable_placement": tpl.has_usable_placement(node),
        }
        for node in result.nodes
    ]
    payload["memberships"] = [dict(row) for row in result.memberships]
    # SCHEMA V3, BEHIND THE FLAG (design §9.6, eras §7.8 step 2). The fold
    # always derives these; only the WRITER is gated, so rollback is the flag
    # and nothing else — the v2 file is byte-identical to the one this package
    # published before E-L2d, which `tests/test_projection_schema_v3.py` pins.
    if tp.projection_schema_version() >= 3:
        payload["lanes"] = [dict(row) for row in result.lanes]
        payload["frame_display"] = [dict(row) for row in result.frame_display]
    payload["counts"] = {
        "claims": int((result.diagnostics or {}).get("claims") or 0),
        "nodes": len(result.nodes),
        "work_items": len(result.work_items),
        "memberships": len(result.memberships),
        "unplaced": len((result.diagnostics or {}).get("unplaced") or ()),
    }
    # Cut 2a (ADR 0027, decision record §4.3/§7): the per-year placement
    # certainty band, published alongside the nodes it is computed from.
    # ADDITIVE — a v1/v2 reader that has never heard of `placement` is
    # unaffected, and `projection_schema_version` is untouched: this is a
    # top-level envelope key like `counts`/`memberships`, not a per-node
    # field, so it needs no schema-version gate. `None` (an undated or
    # birthless projection) is published as absence, not as a null key, the
    # same way `timeline.placement_score` reports nothing rather than a
    # dead payload block. Guarded exactly like the legacy call site
    # (`timeline.timeline_data`, v208): a scoring problem must never take a
    # publish down.
    try:
        placement = tpl.placement_for_projection(payload)
    except Exception:  # noqa: BLE001
        placement = None
    if placement is not None:
        payload["placement"] = placement
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
    # O-E6: the alias map travels with the items in the SAME generation, so a
    # reader that resolves a stored id can never be holding a map that
    # describes a different set. Atomic publish already gives it the pairing.
    payload["work_item_aliases"] = dict(result.work_item_aliases)
    payload["reach"] = dict(result.reach)
    # Cut 3a: the star travels with the items it was planned over, in the SAME
    # generation, for the reason `work_item_aliases` does — a reader can never
    # hold a plan that describes a different set.
    payload["keystones"] = [dict(row) for row in result.keystones]
    payload["score_components"] = {
        key: dict(value) for key, value in result.score_components.items()
    }
    payload["counts"] = {"work_items": len(result.work_items)}
    return payload


#: Where the resolver keeps what it asked. Read here, never folded.
RESOLVER_LEDGER = Path("state") / "resolver" / "resolutions.json"


def resolver_questions(vault_root: str | Path) -> dict[str, str]:
    """``node_id -> the question the resolver says would settle it``.

    The resolver reads a story against the spine and, only when the vault
    genuinely cannot tell, proposes the ONE question that would place the
    moment (ADR 0037). That sentence is better than the generic *"When did X
    happen?"* the composer writes from a label, and it is the whole point of
    having asked a model: the card should say what is actually missing.

    Read, never folded. The ledger is the resolver's memory of what it asked,
    not a claim about the person's life, so it is deliberately NOT a
    derivation input — `CALCULATION_RULE_VERSION` describes the arithmetic
    that places moments, and a better sentence on a card is not that
    arithmetic. Unreadable or absent reads as "no questions".
    """
    try:
        raw = json.loads((Path(vault_root) / RESOLVER_LEDGER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = raw.get("nodes") if isinstance(raw, dict) else None
    found: dict[str, str] = {}
    for node_id, row in (rows or {}).items():
        if not isinstance(row, dict) or row.get("status") != "unknown":
            continue
        question = " ".join(str(row.get("question") or "").split())
        if node_id and question:
            found[str(node_id)] = question
    return found


def resolver_estimates(vault_root: str | Path) -> dict[str, dict]:
    """``node_id -> probable_window`` for every moment the resolver could not date.

    v325. When the vault genuinely cannot tell, the resolver keeps its question
    AND its best reading of the stretch the moment falls in — a bounded range
    with the lines it rests on (a residence, a tenure, a related dated moment).
    That reading is published on the moment's node and on its work item as
    ``probable_window`` so the page can float the dot over the years it
    probably belongs to instead of over the whole life. It is an ESTIMATE:
    never a placement, never read by the score or the strip, never an input
    to the derivation (same rule as :func:`resolver_questions` — read, never
    folded). Unreadable or absent reads as "no estimates".
    """
    try:
        raw = json.loads((Path(vault_root) / RESOLVER_LEDGER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = raw.get("nodes") if isinstance(raw, dict) else None
    found: dict[str, dict] = {}
    for node_id, row in (rows or {}).items():
        if not isinstance(row, dict) or row.get("status") not in ("unknown", "unverified"):
            continue
        estimate = row.get("estimate")
        if not isinstance(estimate, dict) or not estimate.get("earliest") or not estimate.get("latest"):
            continue
        basis = [dict(b) for b in estimate.get("basis") or () if isinstance(b, dict)]
        window = {
            "earliest": str(estimate["earliest"]),
            "latest": str(estimate["latest"]),
            "basis": basis,
            "source": "resolver",
        }
        try:
            window["confidence"] = float(estimate.get("confidence"))
        except (TypeError, ValueError):
            pass
        if node_id:
            found[str(node_id)] = window
    return found


def _with_resolver_estimates(payloads: dict, estimates: dict[str, dict]) -> None:
    """Put the resolver's probable window on the node and on its work item.

    v325. In place, on the rendered payloads, exactly as the question is —
    a display decision over the same generation, so ``calculation_rule_version``
    does not move and a reader that has never heard of ``probable_window`` is
    unaffected.

    A node that is actually PLACED gets no window (owner ruling 1, 2026-09-23).
    An estimate is *"never a placement"* — that is the whole rule it lives
    under — so once the substrate can place the moment for real, a stale
    estimate beside a stated interval is two answers to one question. The
    ledger row is left exactly as it is: it is the resolver's memory of what it
    asked, and it stops being drawn rather than being rewritten.
    """
    if not estimates:
        return
    for payload in payloads.values():
        rows = payload.get("work_items")
        if isinstance(rows, list):
            payload["work_items"] = [
                {**row, "probable_window": dict(estimates[str(row.get("node_ref"))])}
                if isinstance(row, dict) and str(row.get("node_ref") or "") in estimates
                else row
                for row in rows
            ]
        nodes = payload.get("nodes")
        if isinstance(nodes, list):
            payload["nodes"] = [
                {**node, "probable_window": dict(estimates[str(node.get("node_id"))])}
                if isinstance(node, dict) and str(node.get("node_id") or "") in estimates
                and not tpl.has_usable_placement(node)
                else node
                for node in nodes
            ]


def _with_resolver_questions(payloads: dict, questions: dict[str, str]) -> None:
    """Put the resolver's own question on the work item for that node.

    In place, on the rendered payloads and before the semantic no-op compares
    them, so a newly proposed question is a new generation exactly as a new
    date is. ``question_source`` says where the sentence came from; a reader
    that has never heard of it is unaffected.
    """
    if not questions:
        return
    for payload in payloads.values():
        rows = payload.get("work_items")
        if not isinstance(rows, list):
            continue
        payload["work_items"] = [
            {**row, "prompt_intent": questions[str(row.get("node_ref"))],
             "question_source": "resolver"}
            if isinstance(row, dict) and str(row.get("node_ref") or "") in questions
            else row
            for row in rows
        ]


def _without_stakeless_date_cards(payloads: dict) -> list[dict]:
    """Drop every date card the resolver's OWN window shows buys nothing.

    Owner ruling 2 (2026-09-23) is held by
    `temporal_work_items.date_card_changes_something`, which the fold already
    applies over the node's real placement. This is the second seam the same
    predicate has to run on, and the reason is the case the ruling was written
    about: the card the owner read said *"About how long before you recorded
    this (a week, a month, several months) did the mid-anger hug with James
    happen?"* over a probable window of 2026-01..2026-07 — seven months, a
    freestanding anecdote, and nothing at all waiting on it.

    The fold cannot see that window. The resolver's ledger is deliberately not
    a derivation input (ADR 0037: *read, never folded*), and an estimate is
    *"never a placement"* — so the fold is right to leave the card standing on
    a node it considers unplaced. But by the time the window has been stamped
    on, the projection DOES know how wide the moment's reading is, and the
    ruling's question — would narrowing change anything? — has an answer. So it
    is asked here, once, over the payloads that already carry the window.

    The four stakes inputs come off the published payloads rather than being
    re-derived: ``resolves`` from the item, ``conflict_state`` and
    ``input_constraint_refs`` from its node, and the frame-boundary test from
    the window's own decades plus the node's ``overlaps`` memberships — which
    is `cross_dating.frames_touching`' verdict as the fold already published
    it, not a second reading of it.

    In place on ``payloads``, exactly as the question and the window are, and
    for the same reason: nothing here re-derives a date, so
    ``calculation_rule_version`` does not move.

    Returns ONE row per card dropped, keyed by ``work_item_id`` — not one per
    payload. The same card lives in both published files and is judged
    identically in each (the predicate's inputs come from the projection's nodes
    either way), so counting it twice would make `_summary`'s
    ``work_items`` under-report by the number of files it happens to appear in.
    """
    dropped: dict[str, dict] = {}
    projection = payloads.get(PROJECTION_FILE) or {}
    nodes = {
        str(node.get("node_id") or ""): node
        for node in (projection.get("nodes") or ())
        if isinstance(node, dict)
    }
    overlapping = {
        str(row.get("member") or "")
        for row in (projection.get("memberships") or ())
        if isinstance(row, dict) and str(row.get("relation") or "") == "overlaps"
    }
    for payload in payloads.values():
        rows = payload.get("work_items")
        if not isinstance(rows, list):
            continue
        kept: list = []
        for row in rows:
            if not isinstance(row, dict):
                kept.append(row)
                continue
            window = row.get("probable_window")
            node = nodes.get(str(row.get("node_ref") or "")) or {}
            if not isinstance(window, dict) or tpl.has_usable_placement(node):
                kept.append(row)
                continue
            months = chrono.span_months({
                "earliest": str(window.get("earliest") or "") or None,
                "latest": str(window.get("latest") or "") or None,
            })
            low = chrono.year_of({"earliest": window.get("earliest")})
            high = chrono.year_of({"latest": window.get("latest")}, end=True)
            straddles = bool(
                (low is not None and high is not None and low // 10 != high // 10)
                or str(row.get("node_ref") or "") in overlapping
            )
            if twi.date_card_changes_something(
                row,
                window=months,
                orders=bool(node.get("input_constraint_refs")),
                contradicted=str(node.get("conflict_state") or "") == "contradicted",
                straddles_frame=straddles,
            ):
                kept.append(row)
                continue
            work_item_id = str(row.get("work_item_id") or "")
            dropped[work_item_id] = {
                "work_item_id": work_item_id,
                "node_ref": str(row.get("node_ref") or ""),
                "event_kind": str(row.get("event_kind") or ""),
                "label": str(node.get("label") or ""),
                "window": f"{window.get('earliest')}..{window.get('latest')}",
                "months": months,
                "reason": twi.NO_STAKES_INSIDE_A_YEAR,
            }
        if len(kept) != len(rows):
            payload["work_items"] = kept
            counts = payload.get("counts")
            if isinstance(counts, dict) and "work_items" in counts:
                counts["work_items"] = len(kept)
    return [dropped[key] for key in sorted(dropped)]


def _with_relation_words(payloads: dict, *, roster_snapshot: object, index: object,
                         landmark_entries: object, owner_names: object,
                         now: object) -> None:
    """`relation_words.with_relation_words` over the rendered pair, in place.

    Guarded like the placement score: a problem reading relation words must
    never take a publish down — it costs the words and the cards, and nothing
    the fold derived.
    """
    try:
        claims = store.active_claims(index) if isinstance(index, dict) else ()
        rw.with_relation_words(
            payloads, projection_key=PROJECTION_FILE, roster=roster_snapshot,
            claims=claims, landmark_entries=landmark_entries or (),
            owner_names=owner_names or (), now=now)
    except Exception:  # noqa: BLE001
        return


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
# Owner identity — ONE definition, every seat (v328)
# --------------------------------------------------------------------------

#: The profile keys that spell the owner's own name, in the order the fold is
#: handed them. WHOLE spellings only: a middle name is not the owner
#: (`tests/test_owner_name_subject.py`), so no key here is ever tokenized.
OWNER_NAME_PROFILE_KEYS = ("name", "full_name")


def _spelling(value: object) -> str:
    return " ".join(str(value or "").split())


def owner_profile(vault_root: str | Path) -> dict:
    """The owner's profile as THIS vault spells it.

    ``profile.yaml`` (committed: name, full_name) under ``config.yaml`` (local,
    wins on conflict) — the same two files and the same precedence as
    `lifehug_core.load_config`, read from the vault being published rather
    than from the process binding. A vault without either is ``{}``.
    """
    try:
        from lifehug_core import load_config  # noqa: PLC0415
        from vault_paths import vault_data_path  # noqa: PLC0415

        root = Path(str(vault_root))
        merged: dict = {}
        for name in ("profile", "config"):
            merged.update(load_config(vault_data_path(name, vault_root=root)) or {})
        return merged
    except Exception:  # noqa: BLE001 — no readable profile is simply no profile
        return {}


def owner_names_from_profile(profile: object) -> tuple[str, ...]:
    """The owner's own spellings: ``name`` and ``full_name``, whole, deduplicated.

    This is the set `temporal_timeline` folds with (`timeline-rules:8`, via
    `identity_resolution.owner_name_refs`): a roster entity answering to one of
    these WHOLE spellings is the owner. Interior tokens never enter — "Pat
    Quincy Example" puts "Pat Quincy Example" in, not "Quincy".
    """
    row = profile if isinstance(profile, dict) else {}
    names: list[str] = []
    for key in OWNER_NAME_PROFILE_KEYS:
        text = _spelling(row.get(key))
        if text and text not in names:
            names.append(text)
    return tuple(names)


def owner_name_variants(owner_names: object) -> tuple[str, ...]:
    """The whole spellings PLUS each one's first word ("Dave", "David").

    For the RESOLVER only (`resolver.spine`'s ``owner_names``, v325): the
    `subject_age_not_owner` refusal must not fire on the owner's own nickname.
    Never an input to the fold — a first name alone would make every namesake
    in the roster the owner, which is exactly the leak `timeline-rules:8`
    refuses. Order: the whole spellings first, then the new first words.
    """
    out: list[str] = []
    for name in owner_names or ():
        text = _spelling(name)
        if text and text not in out:
            out.append(text)
    for text in list(out):
        first = text.split()[0]
        if first not in out:
            out.append(first)
    return tuple(out)


def owner_identity_inputs(vault_root: str | Path) -> tuple[object, tuple[str, ...]]:
    """``(roster_snapshot, owner_names)`` for a fold of ``vault_root``.

    The one definition behind every publish seat (ADR 0021's "one definition,
    many hosts"): `timeline.publish_calculated_timeline`, a Mirror resolution's
    republish, the frame-display command, the CLI, `verify` — and
    `resolver.spine`, through :func:`owner_names_from_profile`. Before v328 each
    seat spelled its own inputs, and a vault whose roster listed the owner
    changed its mind about whose nodes they were according to which seat had
    republished last.

    * the roster is this vault's ``person`` roster (`entity_roster.load_roster`
      with ``vault_root``), an unreadable one being no roster (``()``);
    * the names are :func:`owner_names_from_profile` over :func:`owner_profile`.

    Both are read from the vault being published, never from the process
    binding, so the roster and the substrate can never come from two vaults
    (the split `timeline._projection_vault_root` exists to make impossible).
    """
    root = Path(str(vault_root))
    roster: object
    try:
        import entity_roster  # noqa: PLC0415

        roster = entity_roster.load_roster("person", vault_root=root)
    except Exception:  # noqa: BLE001 — a roster problem is "no roster"
        roster = ()
    return roster, owner_names_from_profile(owner_profile(root))


def owner_identity_digest(roster_snapshot: object, owner_names: object) -> str:
    """sha256 over the owner identity a fold was handed.

    The sorted whole spellings, plus the roster refs those spellings resolve
    to (`identity_resolution.owner_name_refs`) — which is exactly what
    `timeline-rules:8` acts on. Stamped into the projection envelope as
    ``owner_identity_digest`` so a reader can tell which definition folded a
    generation; two seats that fold with the same identity stamp the same
    digest, and a seat that folded with none stamps the digest of ``()``.
    """
    names = sorted({_spelling(name) for name in (owner_names or ()) if _spelling(name)})
    try:
        refs = sorted(ident.owner_name_refs(roster_snapshot, names))
    except Exception:  # noqa: BLE001 — an unreadable roster resolves nothing
        refs = []
    return store.payload_sha256(_canonical({"owner_names": names, "owner_refs": refs}))


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


def load_derivation_inputs(
    vault_root: str | Path,
    *,
    constraints: object = None,
    event_resolution_records: object = None,
    era_views: object = None,
    membership_assertions: object = None,
    display_decisions: object = None,
    frame_display_decisions: object = None,
    landmark_entries: object = None,
    episode_records: object = None,
) -> dict:
    """Read the canonical fold authorities without writing any materialization.

    Publication, its rebuild oracle and classifier context share this boundary.
    ``None`` loads the durable authority; an explicit empty sequence disables it.
    """
    return {
        "constraints": store.active_ordering_constraints(vault_root)
        if constraints is None else constraints,
        "event_resolution_records": eb.load_event_resolutions(vault_root)
        if event_resolution_records is None else event_resolution_records,
        "era_views": ei.era_views(vault_root) if era_views is None else era_views,
        "membership_assertions": era.active_era_memberships(vault_root)
        if membership_assertions is None else membership_assertions,
        "display_decisions": era.active_era_displays(vault_root)
        if display_decisions is None else display_decisions,
        "frame_display_decisions": era.active_frame_displays(vault_root)
        if frame_display_decisions is None else frame_display_decisions,
        "landmark_entries": lp.load_landmark_sources(vault_root)
        if landmark_entries is None else landmark_entries,
        "episode_records": ef.load_episode_records(vault_root)
        if episode_records is None else episode_records,
    }


def _resolved_owner_identity(vault_root: str | Path, *, roster_snapshot: object,
                             owner_names: object) -> tuple[object, object]:
    """Fill whichever of the two the caller left as ``None`` from the vault."""
    if roster_snapshot is None or owner_names is None:
        loaded_roster, loaded_names = owner_identity_inputs(vault_root)
        if roster_snapshot is None:
            roster_snapshot = loaded_roster
        if owner_names is None:
            owner_names = loaded_names
    return roster_snapshot, owner_names


def publish(
    vault_root: str | Path,
    *,
    active_index: object = None,
    resolution_records: object = (),
    event_resolution_records: object = None,
    episode_records: object = None,
    era_views: object = None,
    roster_snapshot: object = None,
    constraints: object = None,
    membership_assertions: object = None,
    display_decisions: object = None,
    frame_display_decisions: object = None,
    landmark_entries: object = None,
    birth_date: object = None,
    owner_ref: object = None,
    owner_names: object = None,
    now: object = None,
    correction_ref: object = None,
    full: bool = False,
) -> dict:
    """Derive the whole calculated timeline and publish it. THE ONE WRITER.

    Returns a summary — generation, counts, the files it wrote, and the §7.1
    phase timings — which is what a compile log prints (see
    :func:`publication_report_line`) rather than a caller re-measuring.

    Cut 4c: every publish that actually writes a new generation also writes
    that generation's realized-gain receipt (`temporal_receipts.write_
    receipt`) — the before/after diff of intervals against whatever was
    published previously (`None` on a vault's first publish). ``correction_
    ref`` is optional and does nothing on its own: a caller that just filed
    a correction (a drag, an undo) and is republishing in the same act may
    pass that correction's own receipt id here, and it rides into the
    written receipt as ``correction_ref`` — omitted, the receipt carries no
    such key, and every existing caller's behaviour is unchanged.

    ``active_index`` defaults to a fresh fold of this vault's receipts and
    corrections, which is also what re-publishes the index itself; pass one in
    when the caller has already folded and wants exactly that generation.
    ``full`` forwards to `temporal_store.rebuild_active_index`: the repair
    path reads every receipt from disk rather than trusting the store's input
    cache to say which ones have not moved.

    ``constraints`` defaults to this vault's filed moves (v232). ``None`` is
    "read them", an explicit sequence is "use exactly these", and ``()`` is
    "none" — the distinction matters because a drag's republish must pick up the
    move that was just filed without every caller remembering to load it.

    ``membership_assertions``, ``display_decisions`` and ``landmark_entries``
    (eras E2) follow exactly that convention, and for exactly that reason: a
    drag that files a membership receipt republishes in the same job, and the
    receipt it just wrote has to be in the projection it just published.

    ``roster_snapshot`` and ``owner_names`` (v328) follow the same convention:
    ``None`` is "read them" — :func:`owner_identity_inputs` over this vault —
    an explicit value is "use exactly this", and ``()`` is "none". Every seat
    that calls this function without naming them therefore folds with the ONE
    owner identity, and the envelope's ``owner_identity_digest`` says which.
    """
    started = time.perf_counter()
    timings: dict[str, float] = {}
    roster_snapshot, owner_names = _resolved_owner_identity(
        vault_root, roster_snapshot=roster_snapshot, owner_names=owner_names
    )
    identity_digest = owner_identity_digest(roster_snapshot, owner_names)

    # Cut 4c: read BEFORE anything is written — the receipt's "before" half
    # is what a reader could see up to this instant, never a value this same
    # call is about to overwrite.
    previous_projection = read_projection(vault_root)

    mark = time.perf_counter()
    index = (
        active_index
        if active_index is not None
        else store.rebuild_active_index(vault_root, full=full)
    )
    timings["fold"] = time.perf_counter() - mark

    generation = next_generation(vault_root)
    derivation_inputs = load_derivation_inputs(
        vault_root,
        event_resolution_records=event_resolution_records,
        episode_records=episode_records,
        era_views=era_views,
        constraints=constraints,
        membership_assertions=membership_assertions,
        display_decisions=display_decisions,
        frame_display_decisions=frame_display_decisions,
        landmark_entries=landmark_entries,
    )
    published_at = normalized_timestamp(now, error=TemporalPublicationError)
    questions = resolver_questions(vault_root)
    estimates = resolver_estimates(vault_root)
    digest = store.payload_sha256(_canonical(index if isinstance(index, dict) else list(index)))

    # v318. The derivation's inputs are all read by now; if they digest to what
    # the standing generation was derived from, and the day has not turned,
    # deriving again can only reproduce the pair already on disk. This is the
    # SAME no-op the block below reaches by comparing rendered payloads — taken
    # earlier, from the inputs, so a compile on an unchanged vault stops paying
    # for the answer it already has.
    fingerprint = derivation_fingerprint(
        index_digest=digest,
        derivation_inputs=derivation_inputs,
        resolution_records=resolution_records,
        roster_snapshot=roster_snapshot,
        owner_names=owner_names,
        birth_date=birth_date,
        owner_ref=owner_ref,
        resolver_questions=questions,
        resolver_estimates=estimates,
    )
    if not full:
        standing = _standing_publication(
            vault_root, fingerprint, today=_utc_day(published_at)
        )
        if standing is not None:
            timings["publish"] = 0.0
            timings["publication_total"] = time.perf_counter() - started
            return _standing_summary(
                standing,
                timings=timings,
                paths=[str(store.store_path(vault_root, name))
                       for name in PUBLICATION_ORDER],
            )

    result = tt.derive_calculated_timeline(
        index,
        resolution_records=resolution_records,
        roster_snapshot=roster_snapshot,
        owner_names=owner_names,
        **derivation_inputs,
        birth_date=birth_date,
        owner_ref=owner_ref,
        projection_generation=generation,
        now=now,
    )
    timings.update(result.timings or {})

    mark = time.perf_counter()
    payloads = {
        PROJECTION_FILE: projection_payload(
            result, published_at=published_at, input_digest=digest, timings=timings,
            owner_identity_digest=identity_digest,
        ),
        WORK_ITEMS_FILE: work_items_payload(
            result, published_at=published_at, input_digest=digest, timings=timings
        ),
    }
    # ADR 0037 (v316): a card asks the resolver's question when the resolver
    # has one. A display decision over the SAME generation — nothing here
    # re-derives a date, so `calculation_rule_version` does not move.
    _with_resolver_questions(payloads, questions)
    # v325: the resolver's probable window rides the same seam, for the same
    # reason and under the same rule.
    _with_resolver_estimates(payloads, estimates)
    # Owner ruling 2 (2026-09-23): and now that the window IS on the card, the
    # cards that the window shows buy nothing come off. Same seam, same rule.
    stakeless_cards = _without_stakeless_date_cards(payloads)
    # v358 (owner ruling 2026-09-25, `relation_words`): the word each roster
    # person is spoken of by, and at most one card per person whose word is not
    # yet known. Read from the roster and the claims this fold already holds —
    # a display decision over the SAME generation, so `calculation_rule_version`
    # does not move.
    _with_relation_words(payloads, roster_snapshot=roster_snapshot, index=index,
                         landmark_entries=derivation_inputs.get("landmark_entries"),
                         owner_names=owner_names, now=published_at)

    # THE SEMANTIC NO-OP (eras design §3.4). Age frames make the projection a
    # function of the clock as well as of the receipts, so "publish again"
    # would otherwise mint a generation every single day and nobody could tell
    # a frame boundary from a heartbeat. When the standing pair says exactly
    # what the fresh render says, this writes nothing and mints nothing.
    standing = _unchanged_generation(vault_root, payloads)
    if standing is not None:
        # The pair on disk still stands, so record what it was derived from:
        # the next publish over the same inputs takes the shortcut above
        # rather than rendering the whole projection to learn this again.
        _write_publication_cache(
            vault_root, fingerprint=fingerprint, generation=standing,
            published_at=str(_published_at_of(vault_root) or published_at),
            payloads={name: read_projection(vault_root) if name == PROJECTION_FILE
                      else read_work_items(vault_root)
                      for name in PUBLICATION_ORDER},
        )
        timings["publish"] = time.perf_counter() - mark
        timings["publication_total"] = time.perf_counter() - started
        return _summary(result, generation=standing, unchanged=True,
                        published_at=str(_published_at_of(vault_root) or published_at),
                        digest=digest, timings=timings,
                        paths=[str(store.store_path(vault_root, name))
                               for name in PUBLICATION_ORDER],
                        stakeless_cards=stakeless_cards)

    # Serialize BOTH before writing EITHER: a payload that cannot be rendered
    # must fail with nothing on disk changed, not halfway through the pair.
    rendered = {name: _canonical(payload) for name, payload in payloads.items()}
    written = [str(_write(vault_root, name, rendered[name])) for name in PUBLICATION_ORDER]
    _write_publication_cache(
        vault_root, fingerprint=fingerprint, generation=generation,
        published_at=published_at, payloads=payloads,
    )
    timings["publish"] = time.perf_counter() - mark
    timings["publication_total"] = time.perf_counter() - started

    # Cut 4c: the receipt lands AFTER the projection pair, through its own
    # writer (`temporal_receipts.write_receipt`) rather than `_write` — a
    # third file, deliberately not part of :data:`PUBLICATION_ORDER`'s own
    # atomicity guarantee, so a crash between the pair and the receipt
    # leaves the truth current and only the audit trail one generation
    # behind, never the other way round.
    receipt = trcpt.diff_projections(previous_projection, payloads[PROJECTION_FILE])
    if correction_ref is not None:
        text_ref = str(correction_ref).strip()
        if text_ref:
            receipt = {**receipt, "correction_ref": text_ref}
    trcpt.write_receipt(vault_root, receipt)

    # v319 (ADR 0037, issue #368): the work-item set just moved, so a question
    # minted from the PREVIOUS generation may have lost the gap it was asking
    # about — the resolver placed the moment and the keystone is simply not
    # here any more. One cheap set comparison decides whether the pass is worth
    # running at all; everything after it is guarded and best effort.
    _retire_stale_bank_questions(vault_root, previous=previous_projection,
                                 published=payloads[PROJECTION_FILE])

    return _summary(result, generation=generation, unchanged=False,
                    published_at=published_at, digest=digest, timings=timings,
                    paths=written, receipt=receipt,
                    stakeless_cards=stakeless_cards)


def _work_item_identities(payload: object) -> set:
    """The ids in one projection payload's ``work_items`` block."""
    row = payload if isinstance(payload, dict) else {}
    return {str(item.get("work_item_id") or "")
            for item in (row.get("work_items") or ())
            if isinstance(item, dict) and item.get("work_item_id")}


def _retire_stale_bank_questions(vault_root: str | Path, *, previous: object,
                                 published: object) -> list:
    """Retire the minted bank rows this generation left behind — GUARDED.

    Two refusals before anything is written:

    * the work-item set has to have actually MOVED. A publish that changes only
      dates has nothing to retire, and this is the cheap way to know that
      without reading the bank at all.
    * the vault being published has to be the one this process is BOUND to.
      `timeline_candidates` writes through `lifehug_core.QUESTIONS_FILE`, which
      is the process binding, so publishing a fixture vault must never reach a
      real bank — the same half-and-half split `timeline._projection_vault_
      root`'s docstring was written to make impossible.
    """
    try:
        if _work_item_identities(previous) == _work_item_identities(published):
            return []
        import lifehug_core  # noqa: PLC0415
        import timeline_candidates  # noqa: PLC0415

        bound = Path(str(lifehug_core.REPO_DIR)).expanduser().resolve()
        if Path(vault_root).expanduser().resolve() != bound:
            return []
        return timeline_candidates.retire_stale(dict(published))
    except Exception:  # noqa: BLE001 — a bank problem never breaks a publish
        return []


def _rule_identity() -> dict:
    """Every version that decides what a derivation would SAY, in one mapping.

    A framework upgrade that moves any of these must re-derive, whatever the
    substrate says — which is the difference between "nothing changed" and
    "nothing changed that this build would read the same way".
    """
    return {
        "publication_version": PUBLICATION_VERSION,
        "claim_schema_version": SCHEMA_VERSION,
        "projection_schema_version": tp.projection_schema_version(),
        "calculation_rule_version": tt.CALCULATION_RULE_VERSION,
        "score_formula_version": tt.SCORE_FORMULA_VERSION,
        # v358: what a projection says about relation words and their cards.
        "relation_word_rule_version": rw.RELATION_WORD_RULE_VERSION,
    }


def derivation_fingerprint(
    *, index_digest: str, derivation_inputs: dict, resolution_records: object,
    roster_snapshot: object, owner_names: object, birth_date: object,
    owner_ref: object, resolver_questions: dict, resolver_estimates: dict | None = None,
) -> str | None:
    """A digest over EVERY argument `derive_calculated_timeline` is given.

    That function is a pure function of its arguments and the clock (its own
    docstring says so, and the age frames are the clock's only route in), so
    two calls whose arguments digest the same and whose day is the same must
    produce the same projection. Nothing is sampled and nothing is summarized:
    the whole of each input goes in, so an input this module forgot to think
    about cannot be an input it forgot to compare.

    ``None`` when any input will not serialize — which reads as "cannot say",
    and the caller derives.
    """
    try:
        return store.payload_sha256(_canonical({
            "index_digest": index_digest,
            "rule": _rule_identity(),
            "derivation_inputs": derivation_inputs,
            "resolution_records": resolution_records,
            "roster_snapshot": roster_snapshot,
            "owner_names": list(owner_names or ()),
            "birth_date": birth_date,
            "owner_ref": owner_ref,
            "resolver_questions": resolver_questions,
            "resolver_estimates": resolver_estimates or {},
        }))
    except (TypeError, ValueError):
        return None


def _utc_day(value: object) -> str:
    return str(value or "")[:10]


def _read_publication_cache(vault_root: str | Path) -> dict | None:
    try:
        payload = _read(vault_root, PUBLICATION_CACHE_FILE)
    except TemporalPublicationError:
        # A published file that will not parse is a fault to report; a CACHE
        # that will not parse is simply not a cache.
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("cache_version") != PUBLICATION_CACHE_VERSION:
        return None
    return payload


def _standing_publication(
    vault_root: str | Path, fingerprint: str | None, *, today: str
) -> dict | None:
    """The published pair, when a fresh derive would reproduce it exactly.

    Six conditions, and the interesting one is the last. Age frames make the
    projection a function of the day as well as of the receipts, so a
    fingerprint match is only "nothing moved" WITHIN one day: cross a day
    boundary and this returns ``None``, the derivation runs, and the ordinary
    semantic no-op decides — which is how a birthday still mints a generation
    and an ordinary Tuesday still does not.
    """
    if not fingerprint:
        return None
    cache = _read_publication_cache(vault_root)
    if cache is None or cache.get("derivation_fingerprint") != fingerprint:
        return None
    if cache.get("published_day") != today:
        return None
    published = read_projection(vault_root)
    queue = read_work_items(vault_root)
    if published is None or queue is None:
        return None
    generation = _generation_of(published)
    if generation <= 0 or generation != _generation_of(queue) or generation != cache.get("generation"):
        return None
    # The pair must still be the pair this cache describes, byte for byte: a
    # projection somebody edited by hand is not a publication this module may
    # claim still stands.
    for name, payload in ((PROJECTION_FILE, published), (WORK_ITEMS_FILE, queue)):
        if store.payload_sha256(_canonical(payload)) != cache.get("digests", {}).get(name):
            return None
    return published


def _write_publication_cache(
    vault_root: str | Path, *, fingerprint: str | None, generation: int,
    published_at: str, payloads: dict,
) -> None:
    if not fingerprint:
        return
    payload = {
        "cache_version": PUBLICATION_CACHE_VERSION,
        "derivation_fingerprint": fingerprint,
        "generation": generation,
        "published_day": _utc_day(published_at),
        "digests": {
            name: store.payload_sha256(_canonical(body))
            for name, body in payloads.items()
        },
    }
    # Deliberately NOT through `_write`: that writer is the publication pair's,
    # and :data:`PUBLICATION_ORDER`'s atomicity is a promise about those two
    # files. A cache written beside them is a third thing and must not be able
    # to fail a publication or appear in its write order.
    try:
        atomic_write_vault_text(
            store.store_path(vault_root, PUBLICATION_CACHE_FILE),
            _canonical(payload),
            vault_root=Path(vault_root),
        )
    except (OSError, ValueError):
        # The pair is published and correct; only the shortcut is missing.
        return


def _standing_summary(published: dict, *, timings: dict, paths: list) -> dict:
    """The summary a no-op would have returned, read off what already stands."""
    diagnostics = published.get("diagnostics") if isinstance(published, dict) else None
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    return {
        "generation": _generation_of(published),
        "unchanged": True,
        "published_at": str(published.get("published_at") or ""),
        "input_digest": str(published.get("input_digest") or ""),
        "files": list(PUBLICATION_ORDER),
        "paths": list(paths),
        "receipt": None,
        "claims": int(diagnostics.get("claims") or 0),
        "nodes": len(published.get("nodes") or ()),
        "work_items": len(published.get("work_items") or ()),
        "unplaced": len(diagnostics.get("unplaced") or ()),
        "timings": {key: round(float(value), 9) for key, value in sorted(timings.items())},
    }


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
             published_at: str, digest: str, timings: dict, paths: list,
             receipt: dict | None = None, stakeless_cards: object = ()) -> dict:
    dropped = [dict(row) for row in (stakeless_cards or ()) if isinstance(row, dict)]
    return {
        "generation": generation,
        "unchanged": unchanged,
        "published_at": published_at,
        "input_digest": digest,
        "files": list(PUBLICATION_ORDER),
        "paths": list(paths),
        # Cut 4c: `None` on the unchanged no-op path (nothing new to diff —
        # the standing generation's receipt from when IT was published still
        # stands), the fresh receipt otherwise.
        "receipt": receipt,
        "claims": int((result.diagnostics or {}).get("claims") or 0),
        "nodes": len(result.nodes),
        "work_items": len(result.work_items) - len(dropped),
        "unplaced": len((result.diagnostics or {}).get("unplaced") or ()),
        # Owner ruling 2 (2026-09-23): the date cards this publish declined to
        # draw because narrowing them would change nothing, each with the label
        # and the window it was declined on. Reported rather than merely
        # counted, because a refusal the owner cannot read is a refusal he
        # cannot check.
        "stakeless_date_cards": dropped,
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
    "chapter_overlays": (),
    # E-L2d, schema v3 (design §9.6). Served EMPTY on a v1/v2 payload and on a
    # v3 payload with nothing in them — tolerant by construction, exactly like
    # the v2 node fields: absent means "this projection carries none", never
    # "this projection is unreadable".
    "lanes": (),
    "frame_display": (),
    "work_item_aliases": {},
    # Event identity I1 (design §3.5). Served, because a host that cannot see
    # them cannot resolve a node id a bind superseded — which is exactly the
    # O-E1b finding this key set exists to prevent, applied to a new layer.
    "node_aliases": {},
    "episode_aliases": {},
    "identity_rule_version": efc.IDENTITY_RULE_VERSION,
    "reach": {},
    # Cut 3a (ADR 0027 amendment). The greedy plan over the residual
    # dependency graph, at most `timeline_gain.KEYSTONE_CAP` rows. SERVED,
    # because the host stars `keystones[0]` and had been reading the legacy
    # projection's plan to do it; an empty tuple is "nothing would place
    # anything else", which is what it is.
    "keystones": (),
    # Cut 5a (R2, ADR 0032). SERVED, and this is the point of the cut: the
    # host that rendered nine legacy ladder rows and "all filled in" (audit
    # F7) renders these instead. An empty tuple is "nothing here is worth a
    # privileged surface right now", which is a real answer and the one a
    # settled vault should give; `landmark_sufficiency` says why, per domain,
    # so the collapse is checkable rather than mysterious.
    "landmark_opportunities": (),
    "landmark_sufficiency": {},
    # v358 (`relation_words`). SERVED, because it is what a person page reads
    # its relationship word from: one row per roster person with a
    # relationship — the neutral word, the gendered word when the owner has
    # said it, and the neutral plural. Empty is "no roster relationships".
    "relation_words": (),
    "reached_frame_epoch": {"count": 0, "current": None},
    "counts": {"nodes": 0, "work_items": 0, "memberships": 0, "claims": 0,
               "unplaced": 0},
    # Cut 2a (ADR 0027). `None` exactly as the published file omits the key
    # rather than writing a null one — "nothing to score" reads the same way
    # on both sides of the seam.
    "placement": None,
}


#: The one key :data:`EMPTY_VIEW` adds that the published file has no reason to
#: carry: a file that exists IS a publication, so "published" is a fact about
#: the read, not about the bytes.
VIEW_ONLY_KEYS = ("published",)

#: Every top-level key the published projection carries that
#: :func:`calculated_view` deliberately does NOT serve under that name, and why.
#:
#: This exists because of `O-E1b` finding 1 (lifehug-platform#691): a host pins
#: the view's block key-for-key, so a key served by the FILE and absent from the
#: BLOCK is unreadable to that host no matter what the file contains — and
#: nothing in the package failed when that happened. The two sides of the guard
#: are now derived from source: a new top-level key must either be served or be
#: named here with a reason, and a name here that the file has stopped
#: publishing fails too, so this table cannot go stale in either direction.
PUBLISHED_KEYS_NOT_SERVED = {
    "version": (
        "the publication FORMAT's version. A page never branches on it; a "
        "reader that had to would be reading bytes, not a projection."
    ),
    "schema_version": (
        "the CLAIM contract's version (`temporal_claims.SCHEMA_VERSION`). The "
        "view's own `schema_version` is the PROJECTION's "
        "(`projection_schema_version`) — the two numbers differ today (1 and "
        "2) and a page that branched on the receipt store's version would be "
        "asking the wrong question about the node shape it is rendering."
    ),
    "projection_schema_version": (
        "served, RENAMED: `calculated_view()['schema_version']` is exactly "
        "this number. One key on the read side, because a host branching on "
        "'which node contract is this' has exactly one question to ask."
    ),
    "input_digest": (
        "the derivation's input digest — the rebuild oracle's key, not a "
        "rendering input."
    ),
    "timings": "§7's explicitly excluded runtime metadata.",
    "owner_identity_digest": (
        "v328: WHICH owner identity folded this generation — sha256 over the "
        "owner's whole spellings and the roster refs they resolve to "
        "(`owner_identity_digest`). An audit key like `input_digest`: a "
        "maintainer compares it across two seats' publishes to prove they "
        "folded with one definition; a page has no reason to show it."
    ),
    "score_components": (
        "the QUEUE's explanation of its own scores, published in the "
        "work-items file and read there (§8.5)."
    ),
    "identity_diagnostics": (
        "findings about the IDENTITY LAYER — dormant bindings, bindings on "
        "era-bound claims, proposals deliberately not applied — plus the "
        "`not_same` closure the fold entailed. Same reasoning as "
        "`diagnostics` below: a maintainer's surface and a work item's input, "
        "and a person's page showing it would be the system talking about "
        "itself. The three tables a page DOES need — `node_aliases`, "
        "`episode_aliases`, `identity_rule_version` — are served."
    ),
    "diagnostics": (
        "findings about the FOLD — `age_frames_without_birth_anchor` and its "
        "kind. They are a maintainer's surface and a work item's input, and "
        "putting them on a person's page would be the system talking about "
        "itself."
    ),
    "dependency_index": (
        "Cut 3a: the GRAPH the gain was computed from, `{anchor_ref: [node "
        "ids]}`. The rendering inputs are the per-item `resolves`/`leverage` "
        "and `keystones`, both served; this is the working the page never "
        "shows, kept in the file so an oracle, a test or a maintainer can "
        "check that 'could place 18' names eighteen real nodes."
    ),
}


#: Schema v3 keys that are DECLARED and deliberately not written yet, with the
#: contract that owns each. They are named here rather than left unmentioned so
#: that the next PR adds a writer to a key a reader already knows about — the
#: same "the key lands first" discipline `memberships` and `chapter_overlays`
#: followed — and so nobody invents a second spelling for them.
#:
#: They are NOT in :data:`EMPTY_VIEW`: a key that is served must be served with
#: a meaning, and "coverage of a chain nothing computes yet" is an empty tuple
#: that reads like an answer. The reader lands with the writer, in E-L2c.
RESERVED_SCHEMA_V3_KEYS = {
    "coverage": (
        "`chain_coverage` per chain (design §8, H9) — covered stretches, "
        "unknown stretches named concretely, and the target window. E-L2c."
    ),
    "closures": (
        "the `chain_closure` decisions (design §8): a chain the person "
        "declared closed for now, which suppresses routine prompting and "
        "deletes nothing. E-L2c."
    ),
}


def view_block_keys() -> tuple[str, ...]:
    """The view's declared key set — what a host pins itself against."""
    return tuple(EMPTY_VIEW)


def published_block_keys() -> tuple[str, ...]:
    """The top-level keys a published projection is expected to carry.

    Derived from the view plus the named exclusions, never listed a third
    time — so the guard in `tests/test_eras_e1b.py` compares two things that
    are both computed rather than one computed thing against a literal.
    """
    served = set(EMPTY_VIEW) - set(VIEW_ONLY_KEYS)
    return tuple(sorted(served | set(PUBLISHED_KEYS_NOT_SERVED)))


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
        "chapter_overlays": tuple(payload.get("chapter_overlays") or ()),
        # TOLERANT BY CONSTRUCTION, the §7.8 step-1 discipline again: a
        # projection published at schema 2 carries neither key and reads here
        # as two empty tuples, which is what it is.
        "lanes": tuple(payload.get("lanes") or ()),
        "frame_display": tuple(payload.get("frame_display") or ()),
        "work_item_aliases": dict(payload.get("work_item_aliases") or {}),
        # Tolerant by construction, exactly like the v1/v2 node fields above:
        # a projection published before event identity I1 carries none of
        # these, and reads here as "nothing bound", which is what it is.
        "node_aliases": dict(payload.get("node_aliases") or {}),
        "episode_aliases": dict(payload.get("episode_aliases") or {}),
        "identity_rule_version": (
            payload.get("identity_rule_version") or efc.IDENTITY_RULE_VERSION
        ),
        "reach": dict(payload.get("reach") or {}),
        # Tolerant by construction, like every additive key above: a projection
        # published before Cut 3a carries no plan and reads here as an empty
        # tuple — "nothing has enough reach to be starred", which is true of a
        # vault with one undated thing in it.
        "keystones": tuple(payload.get("keystones") or ()),
        # Tolerant by construction, like every additive key above: a projection
        # published before Cut 5a carries neither, and reads here as "no
        # opportunities and nothing said about sufficiency" — which is what a
        # generation that never measured it knows.
        "landmark_opportunities": tuple(payload.get("landmark_opportunities") or ()),
        "landmark_sufficiency": dict(payload.get("landmark_sufficiency") or {}),
        # Tolerant by construction: a projection published before v358 (or a
        # vault with no roster relationships) carries none.
        "relation_words": tuple(payload.get("relation_words") or ()),
        "reached_frame_epoch": dict(epoch) if isinstance(epoch, dict) else {
            "count": 0, "current": None
        },
        "counts": {
            "nodes": int(counts.get("nodes") or len(payload.get("nodes") or ())),
            # E2: the SERVED block, not only the published file. A host reading
            # `calculated_view` is the platform's Timeline, and a membership it
            # cannot see is a row it draws in the wrong frame.
            "memberships": int(
                counts.get("memberships") or len(payload.get("memberships") or ())
            ),
            "work_items": int(
                counts.get("work_items") or len(payload.get("work_items") or ())
            ),
            "claims": int(counts.get("claims") or 0),
            "unplaced": int(counts.get("unplaced") or 0),
        },
        # Cut 2a (ADR 0027, decision record §4.3/§7): served under its own
        # name, not renamed and not excused — a host reading `calculated_view`
        # is the platform's Timeline overview, and `placement: None` here means
        # exactly what it means in the file: nothing to score yet.
        "placement": payload.get("placement"),
    }


# --------------------------------------------------------------------------
# The rebuild oracle
# --------------------------------------------------------------------------


def verify(
    vault_root: str | Path,
    *,
    resolution_records: object = (),
    event_resolution_records: object = None,
    episode_records: object = None,
    era_views: object = None,
    roster_snapshot: object = None,
    constraints: object = None,
    membership_assertions: object = None,
    display_decisions: object = None,
    frame_display_decisions: object = None,
    landmark_entries: object = None,
    birth_date: object = None,
    owner_ref: object = None,
    owner_names: object = None,
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
    # v328: the oracle folds with the same owner identity `publish` would, so a
    # generation published by any seat reproduces here — and one published
    # under another definition shows up as `owner_identity_digest`.
    roster_snapshot, owner_names = _resolved_owner_identity(
        vault_root, roster_snapshot=roster_snapshot, owner_names=owner_names
    )
    # The oracle reads every receipt: an answer that trusted a cache would be
    # asserting the cache rather than checking the substrate.
    index = store.rebuild_active_index(vault_root, full=True)
    derivation_inputs = load_derivation_inputs(
        vault_root,
        event_resolution_records=event_resolution_records,
        episode_records=episode_records,
        era_views=era_views,
        constraints=constraints,
        membership_assertions=membership_assertions,
        display_decisions=display_decisions,
        frame_display_decisions=frame_display_decisions,
        landmark_entries=landmark_entries,
    )
    result = tt.derive_calculated_timeline(
        index,
        resolution_records=resolution_records,
        roster_snapshot=roster_snapshot,
        owner_names=owner_names,
        **derivation_inputs,
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
        owner_identity_digest=owner_identity_digest(roster_snapshot, owner_names),
    )
    # v358: the same seam `publish` applies, so a generation carrying relation
    # words reproduces here rather than reading as drift.
    _with_relation_words({PROJECTION_FILE: fresh}, roster_snapshot=roster_snapshot,
                         index=index,
                         landmark_entries=derivation_inputs.get("landmark_entries"),
                         owner_names=owner_names,
                         now=str(published.get("published_at") or ""))
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
    # The repair path folds from the receipts themselves: "delete the files and
    # publish again" is only an oracle if it also declines the store's input
    # cache, so a suspected cache is repaired by the same command.
    print(publication_report_line(publish(root, full=args.rebuild)))
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
    "owner_identity_digest",
    "owner_identity_inputs",
    "owner_name_variants",
    "owner_names_from_profile",
    "owner_profile",
    "projection_path",
    "projection_payload",
    "publication_report_line",
    "publish",
    "published_generation",
    "read_projection",
    "read_work_items",
    "rebuild_signature",
    "resolver_questions",
    "verify",
    "work_items_path",
    "work_items_payload",
]
