# ADR 0046: A Focus is a queue preference; selection is one field

Date: 2026-10-19
Status: ratified (owner, 2026-10-19); amended 2026-10-20 (below)

## Context

A Focus had no off switch. Deleting one was manual surgery on
`state/roadmap.json` and the question bank (the focus skill said so), and a
Focus that reached its tier target kept a maintenance weight in the planner
and its row on Foundation forever, crowding out Focuses that still needed the
queue. The owner ruled (2026-10-19, platform design
`docs/design/focus-selection.md` §1, lifehug-platform#1034):

> "A focus is a preference to get a question in the question queue — it gets
> a higher chance of being the daily question. To remove a focus should only
> mean that it's no longer preferential in the queue, not anything more, no
> deletion or anything. If I re-added that focus it would once again get
> preference based on the algorithm for the question queue."
>
> "Removing it removes it from the foundation page view which shows focuses,
> but everything else still exists."
>
> "A Focus that reaches 100% automatically unselects so other Focuses get the
> queue's space."

## Decision

- **D2 — selection is one boolean on the roadmap row**, `selected` (absent ⇒
  `true`), orthogonal to `phase`, with a receipt
  `selection: {by: "owner" | "sweep", at, reason: "added" | "removed" |
  "tier_target" | "complete"}`. One module, `system/focus_selection.py`
  (`is_selected`, `select`, `unselect`, `should_rest`), is the only reader;
  the planner, the sweep, the autopilot, the CLI and the viewer import it, and
  a guard test fails the build on an inline read. Both fields survive a
  roadmap re-derive.
- **Unselected means no preference, nothing more.** `question_planner.focus_weight`
  returns 0.0 (as for a complete Focus); the autopilot's keep-3-developing
  count and the completion gate skip it; the viewer's Foundation list leaves
  it out. Its category, questions, answers, roster link and wiki page are
  untouched, and its open questions can still arrive by coverage rotation.
  `state/question_queue.json`'s `allocation.focuses` rows carry `selected`.
- **D1 — 100% is the tier target the Foundation bar shows**
  (`saturation >= 1.0`: basic 8 / standard 20 / extreme 50). The weekly
  `focus-complete-sweep` unselects every non-primary Focus at its target or
  complete (ADR 0044) with `by: sweep`, unless the owner last selected it.
  *(Superseded 2026-10-20: whoever selected it; see the amendment.)*
- **Owner verbs:** `lifehug.py focus-select ID [--json]` (Add back,
  `by: owner, reason: added`) and `focus-unselect ID [--json]` (Remove,
  `by: owner, reason: removed`). `focus-complete-play keep_going` selects as
  the owner; `rest` leaves it unselected. `focus-set --tier` never changes
  selection by itself.

Rejected: deleting or retiring the Focus (the ruling says no deletion);
reusing `phase` (a `finishing` Focus can be unselected, and `complete` is
derived from coverage, not from preference); resting at category-complete
only (the owner's 100% is the bar he sees, the tier target).

## Consequences

- Binds: every reader that asks "is this Focus preferred?" calls
  `focus_selection.is_selected`; the sweep never undoes an owner's select;
  hosts (Lifehug Cloud) bind the two verbs through the CLI door.
- Forecloses: a hidden or deleted Focus state; a second selection field.
- Delete-when: if the planner gains per-Focus weights the owner sets
  directly, selection becomes weight 0 and this field folds into it.

## Amendment 2026-10-20 — 100% rests whoever selected it; Keep going and a re-add raise the tier (v425)

The owner ruled (2026-10-19, lifehug#497) that the `by != "owner"` exemption
in `should_rest` was the assistant's addition, not his rule: "A Focus that
reaches 100% automatically unselects" holds whoever selected it. Then: "keep
going will need to raise the tier and if I want to add it again we'll need to
raise the tier." And on the ceiling: "if I want to keep adding it as a focus we
keep raising the tier proportional to what I size it."

- **Rest has no owner exemption.** `focus_selection.should_rest(focus, fill)`
  is `is_selected(focus) and (saturation >= 1.0 or is_complete(focus, fill))`
  (`A_FOCUS_AT_ITS_TARGET_RESTS`). `reopen_selection` (ADR 0044's reopen) is
  unchanged: it undoes only the sweep's own `complete` rest.
- **One raise rule, `roadmap.raise_tier(focus)`**
  (`focus_selection.A_RAISE_IS_PROPORTIONAL_TO_THE_TIER`). The tier moves one
  step up `basic → standard → extreme`, and extreme is not a ceiling: past it
  the label stays `extreme`. The new target is
  `max(next tier's base, current target + current tier's base)`, where the
  current target is the one `focus_fill` measures (`target_depth`, else the
  tier's base). So 8 → 20 → 50 → 100 → 150 → …: the step is the size of the
  tier the Focus is at. A target the owner set above its tier's base
  (`focus-set --target`) is never lowered: standard at 30 raises to extreme 50
  (max(50, 30 + 20)); basic at 15 raises to standard 23 (max(20, 15 + 8));
  extreme at 70 raises to 120. Returns `{tier, target_depth, was}`.
- **Keep going raises and selects.** `focus-complete-play <id> keep_going`
  calls `raise_tier` and selects with `by: owner, reason: kept_going` (a new
  reason); its JSON result carries `raised`. A raise moves the tier target, so
  the bar has room; a Focus whose category is still drained reads complete
  (ADR 0044) and the next sweep rests it as `complete`, and the reopen (a
  question approved into it, such as an approved second-pass candidate)
  selects it again.
- **A re-add at the target raises.** `focus-select` (`set_by_owner(id, True)`)
  on a non-primary Focus whose saturation is `>= 1.0` raises it one tier as
  part of the add (`focus_selection.raises_on_add`; the result's `raised`, the
  CLI line says so). Below its target the tier is unchanged. The viewer's Add
  sheet notes it beside a Focus at its target, and its flash says the add
  raises the tier.

Rejected: an owner exemption (the ruling); a ceiling at extreme (the ruling);
a fixed +50 step at every tier (the step is the size of the tier the Focus is
at, so a basic Focus is not jumped to 58).
