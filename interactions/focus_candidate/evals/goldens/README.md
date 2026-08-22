# Focus Candidate goldens

Two independent pairs, scored into one `check_gates` call
(`system/focus_candidate_evals.py`).

**The research pair — `fixtures.json` + `sample_predictions.json`.** Synthetic
prompt inputs, model proposals, and expected outcomes for the standalone
`focus-candidate-prompt` / `focus-candidate-complete` path, gated by
`research_gates.*`. `sample_predictions.json` is the deterministic recorded
seat. Live seating uses the same fixtures and gates and skips loudly without a
configured provider.

**The onboarding pair — `onboarding_fixtures.json` +
`onboarding_sample_predictions.json`** (v189,
`docs/pr-specs/focus-onboarding-context.md`). Short synthetic transcripts for
the Play path, gated by the six `focus_setup_gates.*` classes. A fixture turn
carries its `{focus_stage}` (`establish` | `settled`), the caller-owned
`user_signaled` fact, and the `expected_focus_setup` the turn should yield; the
parallel prediction carries the reply text and the raw, pre-validation
`focus_setup` value. Scoring runs `focus_candidate.lint_focus_setup_reply`
against the stage and passes the raw field through
`focus_candidate.validate_focus_setup`, so both validation layers are exercised
together exactly as a real caller exercises them. This pair is deterministic —
recorded replies only, no provider seat — so it scores on a `--live` run too.

The seven required onboarding golden ids
(`focus_candidate_evals.REQUIRED_ONBOARDING_GOLDEN_IDS`) pin, in order: the
aside plus one question; a person focus asking the relationship; an opener that
already answered, so nothing is asked; a settled turn staying silent; a
user-driven rename emitting `focus_setup`; a long settled turn staying null;
and an off-vocabulary relationship normalizing to no setup change without
failing the turn.
