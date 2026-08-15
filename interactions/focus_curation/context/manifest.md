# Context manifest — the per-turn assembly recipe

This document specifies the deterministic per-turn context assembly for the
Focus-Curation interaction. `system/focus_curation.py`'s
`build_curation_prompt()` implements exactly this recipe.

## Assembly order

`[stable, cached]`

1. **`identity`** — `prompt/identity.md`, verbatim.
2. **`behavior`** — `prompt/behavior.md`, verbatim. THE RUBRIC — never
   truncated.
3. **`examples`** — `prompt/examples.md`, verbatim (or a relevant subset if
   truncation is needed to fit `budget.examples`).

`[per-call]`

4. **`turn_instructions`** — `prompt/turn-instructions.md`'s CURATE
   template with its `{pending_ideas}` / `{roster_context}` /
   `{existing_focuses}` slots filled for this specific call.

No `learned` block (this interaction has no learning file — there is no
weekly rubric-edit mode) and no `profile` block (quality-profile signal is
irrelevant to an identity-resolution judgment).

## Rules

- **Token budgets** come from `interaction.yaml`'s `budget.*` keys, one per
  block above.
- **`behavior` is never truncated to fit under budget in a way that cuts the
  numbered rules mid-rule** — mirrors `question_judgment/context/
  manifest.md`'s own never-truncate guarantee for the same reason: this
  interaction exists so the rubric a model is graded against is the one it
  actually reads.
- **Identical in both runtimes.** The OSS single-user runtime
  (`system/focus_curation.py`) and any future hosted-platform vendored
  equivalent assemble context in this same order from the same rules.
