# ADR 0008: One published quality score, craft penalties folded in

Date: 2026-08-14
Status: proposed

## Context

Question candidates carried TWO disconnected scores plus a display fiction.
`score_candidate_for_promotion()` computed `priority ×
story_function_multiplier` and gated auto-promotion at `AUTO_PROMOTE_THRESHOLD`
(0.82) / `NEEDS_REVIEW_THRESHOLD` (0.70). Separately, `check_quality()`
computed a craft score (yes/no wording, self-directed why, too broad, no
scene/stakes path, missing source, too short/vague, exact duplicate) and
tripped its OWN gate, `QUALITY_GATE_MIN` (0.60), inside
`auto_promote_candidates()` — a candidate could clear the promotion-score
band and still get parked by a completely separate craft check, or vice
versa, with no single number a human could point to as "the" quality of a
candidate. Meanwhile the viewer (`serve_wiki.py`'s Review lane) rendered
BOTH numbers side by side in Priority / Quality columns, and the platform's
hosted read model surfaced `record["priority"]` alone, labeled
`quality_score` — a third, even thinner, notion of quality. Owner-directed
2026-08-14: fold the craft penalties into the promotion math so there is one
honest, storable, displayable number.

## Decision

**One function, one definition.** `unified_quality_score(candidate,
quality_profile, existing_questions) -> dict` computes
`score = clamp(priority × story_function_multiplier − penalty_total, 0, 1)`
and returns `{score, components: {priority, story_function_multiplier,
craft_penalties: [{flag, penalty}, ...], penalty_total}, computed_at}`.
Craft penalties are read from `check_quality()`'s own per-flag weights
(`check_quality` now also returns a `penalties` list alongside its existing
`score`/`flags`/`notes`) — the weight table itself stays defined in exactly
one place, `check_quality`, per the recurring-defect doctrine.
`score_candidate_for_promotion()` remains as a public API (callers exist)
but now delegates into `unified_quality_score()`'s `components` for the
promotion-only product (priority × multiplier, no craft penalties) — it is
no longer an independent scoring path.

**The separate `QUALITY_GATE_MIN` craft gate is retired.** Craft flaws now
drag the ONE score down instead of tripping a parallel gate inside
`auto_promote_candidates()`'s ladder. The ladder's structural parks are
unchanged and still run first — exact-duplicate skip, near-duplicate park,
missing-category park — followed by the score bands, also unchanged:
`≥ 0.82` auto-promotes, `0.70–0.82` parks as `needs_review` (the reason now
quotes both the score and the tripped craft flags), `< 0.70` simply stays a
candidate (no park — a heavy-flag candidate that would previously have been
craft-gate-parked now just scores low and waits). This is a real behavior
delta, scoped narrowly: a candidate whose craft flaws would have parked it
under the old binary gate, but whose penalty-dragged score still lands
≥ 0.70, now parks in `needs_review` with the flags visible in the reason
instead of a separate `quality X.XX: notes` message — same outcome (parked,
human-reviewable, flags visible), one message format instead of two.

**Persistence is additive and idempotent.** Every `auto_promote_candidates()`
run stamps `candidate["quality"] = {score, components, computed_at}` on
every candidate it scores (the full eligible set — not just the promoted
ones), never deleting other fields. `computed_at` only advances when
`score`/`components` actually changed versus what was already stored, so an
unchanged replay does not churn the store; a resurfaced `needs_review`
candidate re-scores for real when its inputs (profile, priority, text)
change. `promotion_score`/`promotion_reason` provenance on a promoted
candidate now records the unified score, not the old promotion-only one.

**The viewer shows ONE Quality column.** `serve_wiki.py`'s candidates lane
(`_candidates_section_html` / new `_quality_cell_html`) drops the separate
Priority and Quality columns for a single Quality column: the stored
`candidate["quality"]` when a run has stamped it, falling back to computing
`unified_quality_score()` live (marked `live`) for candidates no run has
touched yet — never a second scoring path, never a silently stale number.
A compact breakdown (`priority×multiplier −penalties`, flags) renders next
to the score, with the full breakdown also in a hover title.

**Platform parity note (no action in this PR).** The hosted platform's read
model currently surfaces `record["priority"]` as `quality_score` — after the
next framework pin bump, it should read the stored `quality.score` instead.
This PR keeps the stored record shape additive and stable specifically so
that swap is a pure read-side change on the platform, not a data migration.

Alternatives considered. *Recalibrate the bands (0.82/0.70) now that craft
penalties are folded in*: rejected — out of scope per the contract; the
bands measure the same thing they always did (is this candidate good enough
to auto-promote), just against a more honest input. *Keep `check_quality`'s
gate as a hard floor UNDER the unified score (belt-and-suspenders)*:
rejected — that reintroduces exactly the two-gates confusion this ADR
exists to remove; a candidate below the craft floor already scores low
enough to miss the bands on its own.

## Consequences

- **Binds:** any future consumer of "candidate quality" (viewer, CLI
  `stats`/`review`, a future platform read) reads or computes
  `unified_quality_score()` — never `check_quality()` alone for a
  human-facing quality number, and never a second promotion-score
  computation. `check_quality()` stays the craft-weight authority; nothing
  outside it may re-list the weight table.
- **Binds:** `candidate["quality"]`'s shape (`score`, `components`,
  `computed_at`) is now a durable, additive contract — the platform's
  post-pin-bump read depends on it staying stable and forward-compatible.
- **Forecloses:** a parallel craft gate inside `auto_promote_candidates()`.
  `QUALITY_GATE_MIN` is deleted, not just unused — a reintroduction is a
  regression of this ADR, not a new feature.
- **Delete-when:** if the platform's pin bump lands and its read model is
  confirmed reading `quality.score`, the "Platform parity note" above can be
  struck from this ADR (or superseded) as fully resolved.
