# ADR 0006: The Convergence Principle

Date: 2026-08-14
Status: Accepted (owner-ratified in design session, 2026-08-14)

## Context

The system's learning story had an unstated split. The README promises "the
answer itself is the only feedback the system needs," and the Loop's
automated stages (candidate auto-promotion, entity graduation, queue
planning) mostly honor that. But several mission-critical stages quietly
require a human to make progress: Focus recommendations are approval-only
("never created without you"), structurally-parked question candidates
wait "for a human" who has no affordance and then expire, and a saturated
Focus's phase never advances on its own. Meanwhile the explicit decisions
an engaged owner *does* make (promote/dismiss/defer, with reasons) are
recorded but consumed by nothing. Neither tier of user was being served
by a stated principle.

## Decision

`system/mission.md` gains **The Convergence Principle**, binding on every
loop stage and every surface:

1. **Floor** — answering alone must converge. Every autonomous stage has
   a no-human path; a stage that silently requires manual input to make
   progress is a defect, not a design choice.
2. **Accelerator** — manual signals are optional and multiplicative.
   They speed up the same convergence, never unlock different behavior;
   no manual affordance may become a dependency, and every explicit
   decision is signal the loop must actually consume.

Corollaries: "never without you" postures are override defaults, not hard
gates; parked-for-a-human work must either resurface autonomously or be
reachable by a real affordance.

## Consequences

- Focus creation needs an autonomous path (bounded by stated policy) with
  manual choice as the override; the current approval-only posture is
  reclassified as a gap.
- Structural candidate parks must gain either autonomous resolution or a
  real owner affordance (both are in flight on the hosted surface).
- Review decisions and their reasons become required inputs to the
  learning loop (see the decisions-feed-the-loop and question-judgment
  interaction work).
- The Loop-audit acceptance criterion (lifehug-platform#410) becomes
  concrete: for each stage, "does it close without a human?"
- mission.md remains a draft awaiting full ratification (#126); this
  section's substance was ratified verbally by the owner on 2026-08-14
  and rides the same review.
