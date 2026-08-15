# Contract: unified-quality-score

## Why

Owner-directed (2026-08-14): question candidates carry TWO disconnected
scores — the promotion score (`priority × story_function_multiplier`,
gated at 0.82/0.70) and the craft score (`check_quality`, a separate
0.60 gate) — while surfaces display a third thing (raw `priority`)
labeled "quality". The owner wants ONE published quality score whose
algorithm folds the craft penalties in, with the components stored and
displayable, so every surface shows the same honest number.

## Binding facts

- `system/question_candidates.py`: `AUTO_PROMOTE_THRESHOLD = 0.82`,
  `NEEDS_REVIEW_THRESHOLD = 0.70`, `QUALITY_GATE_MIN = 0.60`,
  `NEAR_DUPLICATE_JACCARD = 0.75`, `RESURFACEABLE_REVIEW_REASONS =
  ("score", "quality")`; `score_candidate_for_promotion()` (priority ×
  multiplier); `check_quality()` (start 1.0; duplicate −0.50, yes/no
  −0.25, self_directed_why −0.20, too_broad −0.20,
  no_scene_or_stakes_path −0.15, too_short −0.15, no_source_citation
  −0.10, possibly_vague −0.05); the auto-promote ladder in
  `auto_promote_candidates()` (defer_until → exact dup → near-dup park →
  craft gate park → missing category park → score bands → weekly cap →
  neighborhood cap).
- The viewer's candidates lane (`system/serve_wiki.py
  _candidates_section_html`) computes `check_quality` on demand for
  display and renders separate Priority and Quality columns.
- Platform note (no action here): the hosted read model surfaces
  `record["priority"]` as `quality_score`; after the next pin bump the
  platform will read the stored unified score — this PR must therefore
  keep the stored record fields additive and stable.
- Version bumps to the next free number above origin/main at PR time.

## Scope

In:
1. **The unified score** — one function, one definition:
   `unified_quality_score(candidate, quality_profile, existing_questions)
   -> dict` returning
   `{score, components: {priority, story_function_multiplier,
   craft_penalties: [{flag, penalty}], penalty_total}, computed_at}`
   where `score = clamp(priority × multiplier − penalty_total, 0, 1)`.
   Craft penalties come from `check_quality`'s flags — one shared
   vocabulary, no re-derivation (recurring-defect doctrine: the penalty
   table stays defined in exactly one place).
2. **The ladder re-expressed over the unified score**:
   - Hard structural parks unchanged: exact dup skip, near-duplicate
     park, missing-category park.
   - The separate `QUALITY_GATE_MIN` craft gate is RETIRED — craft
     flaws now drag the one score down instead of tripping a parallel
     gate. (A candidate with heavy flags lands below 0.70 and simply
     stays a candidate; a mid-flag candidate parks in the review band —
     both visible in the breakdown.)
   - Bands unchanged: ≥ 0.82 auto-promote; 0.70–0.82 park
     (`needs_review`, reason quotes the unified score and the penalty
     flags); < 0.70 stays candidate. Weekly/neighborhood caps unchanged.
   - `RESURFACEABLE_REVIEW_REASONS` semantics preserved: score/quality
     parks re-scored every run (now inherently, since penalties are part
     of the score).
3. **Persistence**: each auto-promote run stamps
   `candidate["quality"] = {score, components, computed_at}` (additive;
   never deletes existing fields; `promotion_score`/`promotion_reason`
   provenance keeps recording the promoted value).
4. **Viewer**: the candidates lane's Priority/Quality columns become one
   **Quality** column (the unified score) with a compact breakdown title
   attr or inline `(: components)` detail, reading the STORED value and
   falling back to computing it live for unstamped candidates.
5. **ADR 0008**: the unified score definition, the retirement of the
   parallel craft gate, band semantics, and the platform-parity note.
6. Version bump + changelog.

Out: threshold recalibration beyond the stated mapping (bands keep
0.82/0.70 — behavior change is limited to penalty-drag replacing the
binary craft gate; the ADR documents the delta); decision-signal
consumption (decisions-feed-the-loop PR); platform surfaces.

## Implementation notes

- `score_candidate_for_promotion` remains (callers exist) but delegates:
  it becomes the components' promotion part; grep all call sites and
  reconcile — no second scoring path may survive.
- The dry-run path must print the unified score + flags per candidate.
- Idempotence: stamping `quality` on a candidate then re-running with an
  unchanged profile yields the same score (`computed_at` refreshes only
  when components changed, so replays don't churn the store).

## Test plan

- `tests/test_unified_quality_score.py` (new), subtests: clean candidate
  score = priority×multiplier; each penalty flag drags exactly its
  weight; clamp at 0/1; heavy-flag candidate falls below 0.70 (stays
  candidate, no park) vs mid-flag parks in band with flags quoted in
  reason; near-dup/missing-category still park regardless of score;
  auto-promote at ≥0.82 unchanged for penalty-free candidates
  (behavior-preservation case); stamping idempotence; resurfaced park
  re-scores after profile change.
- Update existing `question_candidates` tests that pinned the old
  craft-gate park reason strings.
- Full-suite note: this workspace shows 21 pre-existing environment
  failures on clean origin/main — your delta must be zero; CI is the
  arbiter.

## Launch-and-verify

The viewer's Review lane changes → runnable walkthrough required:
`tests/walkthrough_unified_quality.py` on `WalkthroughHarness` +
`make walkthrough-unified-quality`: synthetic vault with 3 candidates
(clean-high, mid-flagged parked, heavy-flagged low) → Review lane
screenshot (1440x900 + 390x844) showing the single Quality column with
breakdown, park reason quoting flags. Evidence embedded SHA-pinned in a
PR comment.

## Definition of done

Per `docs/pr-specs/TEMPLATE.md` — version bump, ADR 0008, CLAUDE.md's
candidate-lifecycle description updated where it names the old dual
gates, walkthrough evidence embedded.

🤖 Contract authored by Claude Fable 5 via Claude Code
