# Arc Walk goldens

`arc_fixtures.json` contains synthetic episodes: a target with its plan's
question ids, and one row per turn carrying the turn's `{arc_stage}`, whether
the agenda has already been announced, whether the user signalled leaving, and
the `answered_question_id` a correct model would produce after BOTH validation
layers. `arc_sample_predictions.json` is the deterministic recorded seat —
the reply text and the raw, pre-validation `answered_question_id` for each of
those turns. Live seating uses the same fixtures and gates and skips loudly
without a configured provider.
