# Goldens — judged-verdict fixtures (format; fixtures land with the wiring PR)

This directory will hold committed golden fixtures once a runtime exists to
evaluate against them (the follow-up "decisions-feed-the-loop" PR wires
the JUDGE/RUBRIC-EDIT runtime; goldens land there, per the contract's
Scope). This README documents the intended fixture format now so the
wiring PR has a stable target rather than inventing the shape under
schedule pressure.

## JUDGE-mode goldens (`judge-*.json`, one candidate per file)

One committed candidate-and-verdict pair per file:

- `golden_id` — a short slug.
- `candidate` — `{text, source_ids: [...], story_function, targeted_scene_slot: string|null}`,
  the exact input a JUDGE call would receive.
- `expected_verdict` — `{verdict: "accept"|"reject", priority: number|null,
  evidence: string, flags: [...], purposes_served: [...]}`, matching
  `prompt/turn-instructions.md`'s JUDGE output shape exactly.
- `demonstrates` — which `prompt/behavior.md` rule number(s) or vocabulary
  section this fixture exists to test (e.g. `["rule_8", "penalty_vocabulary"]`).

A golden's `expected_verdict` must itself be a *correct* verdict per
`prompt/behavior.md` — deliberately-wrong fixtures proving a scorer's
failure path belong inline in the wiring PR's test file, not here, exactly
as `interactions/conversation/evals/goldens/README.md` establishes for its
own golden set.

## RUBRIC-EDIT-mode goldens (`rubric-edit-*.json`)

One committed weekly-pass scenario per file:

- `golden_id` — a short slug.
- `week_delta_summary`, `distilled_prior_amendments`, `current_learned_file`
  — the exact inputs `prompt/turn-instructions.md`'s RUBRIC-EDIT template
  specifies.
- `expected_amendment` — `{amendment: string|null, evidence: string|null,
  char_count: number|null}` — including the "no amendment justified this
  week" case (`amendment: null`), which is an expected, common outcome, not
  an edge case to under-test.

## Extension note

If the wiring PR needs a property beyond what's sketched here (the way
`interactions/conversation/evals/goldens/README.md` documents its own
`arc.topics` extension beyond the original contract sketch), it documents
the extension in this file when it lands the first fixture that needs it —
additive only, never silently.
