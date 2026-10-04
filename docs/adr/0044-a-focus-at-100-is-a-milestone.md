# ADR 0044: A Focus at 100% is a milestone, not an end

Date: 2026-10-04
Status: ratified (owner, 2026-10-04: D1 automatic, D2 candidates on Review, D3 coverage-of-category is the rule, D4 the Studio card waits for #569)

## Context

When a Focus's category ran out of open questions, nothing happened. The
planner had nothing to offer from it and moved on; the Focus kept its slot in
the autopilot's keep-3-developing set (ADR 0011), so a finished Focus could
block a new one; `focus-finish` only lifted a variety cap and marked nothing
complete; and no surface told the owner a Focus was done (lifehug-platform
#995, owner ask 2026-10-04: "Automate a focus when it reaches 100%, and what
to do").

## Decision

100% is a milestone. The system rests the Focus by default, proposes a second
pass the owner can ignore, and says so once.

1. **`complete` is automatic (D1).** The weekly step `focus-complete-sweep`
   (after `quality` and `judgment`, before `promote`) sets `phase = "complete"`
   on a non-primary Focus whose categories hold zero open, non-retired
   questions and at least one answered. The record gains
   `completion = {completed_at, answered, total, row, second_pass, ...}`.
   **The rule is coverage of the category, not the tier (D3):** tier decides how
   many questions were minted, never what "complete" means. `focus-finish` is
   unchanged and stays the manual accelerator.
2. **Rest.** A complete Focus is never queued (`focus_weight` is 0), leaves the
   autopilot's developing count so a new Focus can be promoted, and keeps its
   page and category. It returns to `developing` automatically when a new
   question for its category is approved into the bank: the reopen is derived
   (`roadmap.is_complete` reads the live fill) and persisted by the next
   roadmap rebuild (`roadmap.reopen_completed`).
3. **A second pass, as Review candidates (D2).** On the completion transition
   only, for that Focus's person only, the gap-finders the weekly run already
   computes (the published Timeline's landmark opportunities, keystones and open
   date gaps) are filed as candidates with `source: focus_complete:<slug>`,
   through `question_craft.evaluate`, at `needs_review` with a structural reason
   the auto-promoter never resurfaces, capped at three. Never into the bank,
   never a model call at completion time. Mirror contradictions about the person
   are counted on the row and stay Mirror's own work.
4. **Say so once.** One Mirror row kind, `focus_complete` ("<Focus> is complete
   — N of N answered"), id `fc:<slug>:<completed_at>`, minted once per
   completion and never re-minted while the Focus stays complete. Three Plays the
   host binds: `keep_going` (the second-pass candidates get Review attention),
   `rest` (the row closes, nothing else), `make` (a `studio_card` hint). Not a
   Today lane.
5. **Make something (D4).** `make` records a `studio_card` hint
   (`kind: focus_story`, "The story of <Focus> so far") on the completion record.
   The platform renders the Studio project card once Studio Phase 2 (#569)
   unparks; the package generates nothing.

## Alternatives considered

- Owner-confirmed completion: rejected (D1); a passive user never confirms.
- Auto-promoting the second pass into the bank: rejected (D2); the craft door
  and the owner's approval stay in front of every question.
- Tier-relative completion (8 answers for basic): rejected (D3); a Focus with
  open questions left is not done.

## Consequences

- **Binds:** every reader that asks "is this Focus finished?" calls
  `roadmap.is_complete`; a restated `phase == "complete"` test that ignores the
  live fill is a regression. Second-pass candidates reach the bank only through
  candidate promotion, on the owner's word.
- **Forecloses:** a model call at completion time; a second Mirror row for one
  completion; auto-promotion of `focus_complete:*` candidates.
- **Delete-when:** if the planner gains a first-class "rest" state for any
  saturated Focus, `complete` should fold into it.
