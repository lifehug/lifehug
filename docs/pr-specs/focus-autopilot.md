# Contract: focus-autopilot

## Why

Owner-directed (2026-08-14), the Convergence Principle's floor applied
to focus creation (ADR 0006: "never created without you" postures are
override defaults, not hard gates; every autonomous stage has a no-human
path). Today a passive user's system NEVER grows a new Focus — approval
is the only path. The owner's ratified rule: keep a target number of
focuses in active development; when the developing set thins and a
worthy idea is pending, the system approves it itself.

## Binding facts (as of origin/main v166)

- `system/recommend_focuses.py`: `approve_recommendation()` (the exact
  path autopilot reuses — scaffold via `roadmap.focus_new`, stamps
  status/approved_at/focus_id/category), `focus_start_gate()` +
  `FOCUS_READY_SCORE_FLOOR = 8.0`, `ready_to_start` on records,
  `apply_recommendation_expiry()`.
- `system/roadmap.py` + `system/progress.py`: saturation =
  answered/target_depth; verdict thresholds READY 0.70 / DEVELOPING
  0.40; `primary` flag; phase never auto-advances (unchanged here).
- `system/weekly_maintenance.sh`: `run_learning_step` convention; the
  step order note from ADR 0009 (quality update → judgment_update →
  auto-promote → queue).
- Zombie protection: a scaffold without its seed is a zombie —
  `focus_new`'s `_generate_and_promote` seeds starter questions; the
  AI-seeding path is keyless-safe (emit-task). Autopilot must not
  create zombies: on a keyless run where seeding cannot complete
  in-process, the approval still records and the seed rides the
  existing agent-task path — same behavior as a manual CLI approve.
- Owner decisions (verbatim intent): target 3 in development;
  "developing" = active, non-primary, saturation < READY (0.70);
  auto-approve the highest-scoring pending idea with score ≥ 8.0 while
  below target; owner dismissals are permanent vetoes; auto actions are
  fully auditable; manual approve remains unlimited (accelerator);
  autopilot never navigates/notifies beyond normal weekly summary lines.
- Version bumps to next free above origin/main at PR time (expect 167
  or 168 — the duplicate-curation PR is in flight in a sibling worktree
  and both touch recommend_focuses.py; coordinate via rebase at merge
  time, NOT by waiting). 21 pre-existing env failures — zero delta.

## Scope

1. **The algorithm** — `focus_autopilot(target=None, dry_run=False)` in
   `recommend_focuses.py`:
   ```
   target = knob (state/config override -> AUTOPILOT_TARGET_DEVELOPING default 3)
   developing = [f for f in roadmap: f.active, not f.primary, saturation(f) < 0.70]
   approvals = []
   while len(developing) + len(approvals) < target:
       idea = highest-score pending rec with score >= FOCUS_READY_SCORE_FLOOR (8.0),
              not owner-dismissed, not folding into an existing focus
       if idea is None or len(approvals) >= AUTOPILOT_MAX_PER_RUN (default 1): break
       approve_recommendation(idea, approved_by="auto")   # same scaffold+seed path
       approvals.append(idea)
   ```
   `approved_by: "auto"` stamped on the record (additive field; manual
   approvals stamp "owner" going forward, absent = legacy). Dry-run
   prints the would-approve decision and why.
2. **Per-run cap default 1** (gentle: one new focus a week at most —
   the owner can raise the knob) — deliberate: the owner's "up to
   three" end-state is reached over successive weeks, not in one burst,
   except `--catch-up` flag (manual CLI only) which fills to target in
   one run for the everything-done case.
3. **Weekly wiring**: `weekly_maintenance.sh` learning step
   `focus_autopilot` AFTER candidate auto-promotion and queue planning
   (a new focus's seeded questions enter NEXT week's planning — document
   the one-week lag in the ADR, mirroring ADR 0009's lag note).
   Dry-run mode previews.
4. **CLI**: `lifehug.py focus-autopilot [--dry-run] [--target N]
   [--catch-up]`.
5. **Policy surface (OSS viewer)**: the Review focus-ideas lane's
   policy line changes from "never created without you" to the honest
   new posture ("keeps N focuses in development — the highest-rated
   idea is started for you when a slot opens; approve more anytime;
   dismiss is forever") with the algorithm's numbers rendered from the
   real constants (no literals in the HTML builder — read them from the
   module). Platform twin rides the next pin bump (note in ADR).
6. **ADR 0011**: the autopilot decision, the target/cap/floor numbers,
   the developing definition, the one-week lag, catch-up semantics,
   `approved_by` provenance, and the explicit statement that this
   retires the "never created without you" posture per ADR 0006.
7. Version bump + changelog; mission.md/CLAUDE.md touch-ups where they
   state the old posture as current fact.

Out: navigation/notification UX (platform, later) · phase
auto-advancement (still manual — separate future decision) · target
personalization/learning.

## Test plan

`tests/test_focus_autopilot.py`, subtests: below-target + worthy idea →
one approval via the real approve path (record stamped auto, focus
scaffolded, category seeded in the keyless-task sense) · at-target → no
action · no idea ≥ floor → no action · dismissed ideas never chosen ·
per-run cap holds with two slots open · catch-up fills to target ·
dry-run writes nothing · primary focus never counts as developing ·
saturated/READY focuses don't count · idempotent within a week (second
run after one approval sees target met or cap spent). Update the
viewer-lane test pinning the old policy line. Baseline 21 env failures —
zero delta; CI arbiter. Viewer lane text changes → extend the existing
review walkthrough if one pins that line; otherwise evidence = dry-run
output pasted.

## Definition of done

Per TEMPLATE.md: version bump, ADR 0011, docs updated, evidence with
real `focus-autopilot --dry-run` output on a synthetic vault showing
both a triggering and a non-triggering state.

🤖 Contract authored by Claude Fable 5 via Claude Code
