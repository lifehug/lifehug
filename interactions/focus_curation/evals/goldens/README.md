# Goldens — curated-verdict fixtures

This PR (focus-duplicate-curation) lands the first committed fixture
(`curate-betty-jo-merge-01.json`) per the format below. It is a
structural/lint fixture: `system/focus_curation.py`'s `apply_verdicts()` is
directly exercised against it in `tests/test_focus_duplicate_curation.py`
(fed through `apply_verdicts(from_response=...)`-equivalent application and
asserted to dismiss the correct variant record with `dismissed_by:
"curation"`). No live-model CURATE call is made by this PR or its tests —
the golden proves the fixture-and-runtime shape, mirroring
`interactions/question_judgment/evals/goldens/README.md`'s own bootstrap
convention for the same reason (a keyless CI environment, dependency-free by
design).

## CURATE-mode goldens (`curate-*.json`, one call per file)

One committed input-and-verdict pair per file:

- `golden_id` — a short slug.
- `pending_ideas` — the exact `{id, type, entity, evidence}` array a CURATE
  call would receive.
- `roster_context` — the exact roster-entry array a CURATE call would
  receive (may be empty).
- `existing_focuses` — the exact `{slug: label}` object a CURATE call would
  receive (may be empty).
- `expected_verdict` — `{merge: [[...]], map_to_focus: {...}, keep: [...]}`,
  matching `prompt/turn-instructions.md`'s output shape exactly.
- `demonstrates` — which `prompt/behavior.md` rule number(s) this fixture
  exists to test (e.g. `["rule_3", "rule_4", "rule_5"]`).

A golden's `expected_verdict` must itself be a *correct* verdict per
`prompt/behavior.md` — deliberately-wrong fixtures proving a scorer's
failure path belong inline in a future wiring PR's test file, not here,
exactly as `interactions/question_judgment/evals/goldens/README.md`
establishes for its own golden set.

## Extension note

If a future wiring PR needs a property beyond what's sketched here, it
documents the extension in this file when it lands the fixture that needs
it — additive only, never silently.
