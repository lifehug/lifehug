# Question Candidate goldens

`fixtures.json` contains synthetic exact inputs, model proposals, and expected
normalized facts. `sample_predictions.json` contains parallel predictions used
to prove scorer and threshold arithmetic without a provider. Fixture ids are
unique and predictions match them exactly. Live seating uses the same input and
scorer and skips loudly when no provider is ready.
