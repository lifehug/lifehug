# Goldens — judged-verdict fixtures

decisions-feed-the-loop lands the first two committed fixtures
(`judge-scene-slot-accept-01.json`, `rubric-edit-era-anchor-carveout-01.json`)
per the format below, plus a RUBRIC-EDIT runtime
(`system/question_judgment.py`'s `run_weekly_edit()`) that
`rubric-edit-era-anchor-carveout-01.json` is directly exercised against
(`tests/test_decisions_feed_loop.py`): its `expected_amendment` is fed
through `run_weekly_edit(from_response=...)` and the write is asserted
bounded, evidence-cited, and lint-passing. No JUDGE-mode runtime exists
yet — `judge-scene-slot-accept-01.json` is a structural/lint fixture only
(the per-candidate JUDGE call itself is a future generation path's job),
mirroring `interactions/conversation/evals`'s own bootstrap PR for the
pieces it doesn't wire yet.

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
