# ADR 0011: Focus Autopilot

Date: 2026-08-14
Status: ratified (owner, 2026-08-14)

## Context

ADR 0006 (the Convergence Principle) named Focus creation outright as a
gap: "Focus recommendations are approval-only ('never created without
you')" — a passive user who only ever answers questions, and never opens
a review surface, has no path by which the system grows a new Focus on
its own. Every other mission-critical autonomous stage (candidate
promotion, entity graduation, queue planning) already has a no-human
path; Focus creation did not. The owner's ratified rule, stated verbatim
in the design session: keep a target number of focuses in active
development; when the developing set thins and a worthy idea is pending,
the system approves it itself.

## Decision

`recommend_focuses.py` gains `focus_autopilot(target=None, dry_run=False,
*, catch_up=False)`, wired into `weekly_maintenance.sh` as the
`focus_autopilot` learning step and exposed as `lifehug.py focus-autopilot
[--dry-run] [--target N] [--catch-up]`.

**The algorithm.** While the "developing" set is thinner than `target`,
approve the single highest-scoring pending Focus idea at/above the floor,
through `approve_recommendation()` itself — never a parallel scaffold
path, so zombie protection (starter-question seeding via
`roadmap.focus_new`, including its existing keyless emit-task fallback
when no model is available in-process), category scaffolding, and
roadmap registration all ride along for free, exactly as a manual
CLI/viewer approval gets them.

- **Developing** = active (not `phase == "maintenance"`), non-primary,
  saturation < READY (0.70, `progress.py`). This mirrors
  `focus_start_gate()`'s own phase exemption but is deliberately **not**
  the gate's full definition: the gate additionally exempts a focus with
  zero pending questions ("exhausted" — nothing left to answer, so it
  can't be "unfinished" in the owner's sense). The developing SET answers
  a different question — "how many focuses are currently in active
  growth" — so an exhausted-but-unsaturated focus still counts here. The
  primary life-story focus is exempt either way, per ADR 0006/the
  original issue #79 gate: it is never "done."
- **Target** = `AUTOPILOT_TARGET_DEVELOPING` (3), the owner's ratified
  number, overridable per-vault via `config.yaml`'s
  `focus_autopilot_target` (an explicit `--target` always wins over
  both).
- **Floor** = `FOCUS_READY_SCORE_FLOOR` (8.0) — the existing issue #79
  constant, reused rather than a second competing threshold.
- **Per-run cap** = `AUTOPILOT_MAX_PER_RUN` (1) — gentle by default. The
  owner's "keep up to 3 in development" end-state is reached over
  successive weekly runs, never in one burst. `--catch-up` (manual CLI
  only; never wired into the weekly run) raises the effective cap to
  `target` for the everything-answered/idle-queue case, filling to target
  in a single run.
- A pending idea that "folds into an existing focus" — the roadmap has
  since grown a Focus whose id matches the recommendation's slugified
  entity name, newer than the persisted recommendation state — is skipped
  defensively; owner-dismissed and rot-expired ideas are never candidates
  at all, since `dismiss_recommendation()`/`apply_recommendation_expiry()`
  already move them out of the `recommendations` list before autopilot
  ever reads it.
- `dry_run=True` computes and returns the identical decision — which idea
  it would approve and why — without calling `approve_recommendation()`.
  Nothing is written.
- **Idempotent by construction, no cursor file.** A real approval
  scaffolds a new Focus that itself immediately counts toward
  `developing` (freshly created, unsaturated, non-primary) the moment the
  roadmap is re-read, so a second run the same week naturally sees a
  thinner gap — or an empty pending-ideas list, since the approved idea's
  status is no longer `pending` — purely from durable state.

**Provenance.** `approve_recommendation()` gains an additive `approved_by`
keyword (default `"owner"` — every manual CLI/viewer approval keeps
stamping this going forward; `focus_autopilot()` is the only caller that
passes `"auto"`). A record approved before this PR shipped simply lacks
the field: absent means legacy, and nothing backfills it retroactively.

**Weekly wiring and the one-run lag.** `weekly_maintenance.sh` runs
`focus_autopilot` after candidate auto-promotion (`auto_promote`) and
queue planning (`planner_queue`, then `arc_plan`). A Focus approved this
run gets its category scaffolded and (when a model is available) its
starter questions seeded, but this week's queue and arc cards were
already written before autopilot ran — the new material enters NEXT
week's planning. This is an accepted one-run lag, mirroring ADR 0009's
own lag note for the RUBRIC-EDIT step: making the new Focus retroactively
available to this run's already-planned queue would mean re-running
queue planning after autopilot, which is out of scope. Dry-run mode
(`focus-autopilot --dry-run`) previews in the weekly dry-run path too.

**Viewer policy line.** The Review lane's focus-ideas policy line drops
"focuses are never created without you" for the honest new posture —
"keeps 3 focuses in development — the highest-rated idea is started for
you when a slot opens; approve more anytime; dismiss is forever" — with
every number read live from `recommend_focuses`' module constants
(`AUTOPILOT_TARGET_DEVELOPING`, `FOCUS_READY_SCORE_FLOOR`,
`AUTOPILOT_MAX_PER_RUN`), never a restated literal. The completion gate's
open/closed state (issue #79) is unchanged and still appended to the same
line. The hosted platform's twin surface rides the next framework pin
bump rather than a same-session parity change.

This retires the "never created without you" posture ADR 0006 named as a
gap. Owner approval is unchanged as an accelerator (the Convergence
Principle's second tier): approving a pending idea manually, anytime,
still works exactly as before and is unlimited; a dismissal is still a
permanent veto autopilot can never override.

## Consequences

- **Binds**: any future Focus-approval path (autopilot or otherwise) MUST
  call `approve_recommendation()` — a parallel scaffold path that
  recreates category-scaffolding/seeding logic is a regression of this
  ADR. Any future autopilot-adjacent constant (target, cap, floor) is a
  module constant in `recommend_focuses.py`, read live by every consumer
  (CLI display, the viewer's policy line) — a restated literal anywhere
  is a regression.
- **Forecloses**: a deterministic Focus-creation path that bypasses
  `approve_recommendation()`'s zombie protection; auto-approving more
  than one idea per weekly run outside of the explicit, manual-only
  `--catch-up` escalation; retroactively stamping `approved_by` onto
  records approved before this PR (there is nothing there to recover).
- **Delete-when**: if a future ADR gives the developing-set definition
  the gate's zero-pending exemption too (making the two definitions
  identical), this ADR's explicit "deliberately not the gate's full
  definition" note should be struck or superseded.
