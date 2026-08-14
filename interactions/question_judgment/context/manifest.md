# Context manifest — the per-turn assembly recipe

This document specifies the deterministic per-turn context assembly for the
Question-Judgment interaction. The wiring PR implements exactly this
recipe; `system/question_judgment.py`'s `load_judgment_rubric()` (this PR)
already assembles the framework-scoped half of it (`identity` + `behavior`
+ `learned`) — the remaining per-call blocks (`examples`, `profile`,
`turn_instructions`) are filled by the generation-path caller per mode.

## Assembly order

`[stable, cached]`

1. **`identity`** — `prompt/identity.md`, verbatim.
2. **`behavior`** — `prompt/behavior.md`, verbatim. THE RUBRIC — never
   truncated. This is the seam the truncation bug lived in
   (`system/classify_story.py`'s old `research[:3000]` and
   `system/research_expand.py`'s old `research_notes[:800]`); this
   interaction's entire point is that this block is never cut.

`[per-vault, changes only on a rubric-edit]`

3. **`learned`** — `state/question_judgment/learned.md` if present, else
   empty (see `system/question_judgment.py`'s graceful-missing handling).
   Vault data, not framework data — a person's own accumulated amendments,
   registered in `system/vault_contract.json`. Not written by anything in
   this PR (see README §4); the follow-up "decisions-feed-the-loop" PR
   wires the writer.

`[stable, cached]`

4. **`examples`** — `prompt/examples.md`, verbatim (or a relevant subset if
   truncation is needed to fit `budget.examples`).

`[per-call, JUDGE mode only]`

5. **`profile`** block — a short distillate of relevant
   `state/quality_profile.json` signal for the candidate's topic/period
   (e.g. "Ohio period: 2 answers, no typical-day texture"), never the whole
   profile. Absent (or `"no signal — profile below activation threshold"`)
   when the quality profile hasn't activated yet
   (`quality_profile.ACTIVATION_THRESHOLD`).

`[last]`

6. **`turn_instructions`** — `prompt/turn-instructions.md`'s JUDGE or
   RUBRIC-EDIT template (per mode) with its `{placeholder}` slots filled
   for this specific call.

## Rules

- **Token budgets** come from `interaction.yaml`'s `budget.*` keys, one per
  block above. A runtime that assembles a block over its budget must trim
  that block, not silently ignore the budget — `budget.behavior` is
  intentionally the largest allocation (1600) because the rubric is the
  one block this interaction exists to never truncate; if the shipped
  `prompt/behavior.md` ever needs to grow past what a trim-safe budget can
  hold, the budget is what should move, not the file back toward
  truncation.
- **`behavior` is never truncated to fit under budget in a way that cuts
  the numbered rules mid-rule.** If a future edit makes `behavior.md`
  genuinely too large for `budget.behavior` on a smaller-context model,
  that is a budget or role-tier problem to fix explicitly (raise the
  budget, or don't seat that model for `role.worker`), not something a
  runtime silently solves by slicing the file.
- **`learned` is additive only.** It supplements `behavior`, it never
  overrides or contradicts a hard rule — see `prompt/turn-instructions.md`'s
  RUBRIC-EDIT constraints.
- **Identical in both runtimes.** The OSS single-user runtime
  (`system/question_judgment.py` plus the generation-path callers) and any
  future hosted-platform vendored equivalent assemble context in this same
  order from the same rules; differences in how a runtime fetches the
  underlying vault data are fine, differences in assembly order or the
  never-truncate guarantee on `behavior` are not.
