# Landmark goldens

`landmark_fixtures.json` contains synthetic landmark passes: the landmarks
already filed, the domain the turn is asking about, its ladder rung, whether
that domain is sensitive, and the `landmark` value a correct model would
produce after BOTH validation layers.
`landmark_sample_predictions.json` is the deterministic recorded seat — the
reply text and the raw, pre-validation `landmark` object for each of those
turns. Live seating uses the same fixtures and gates and skips loudly without
a configured provider.

`landmarks-residence-chain` is the one that matters most: the ladder walked
from a town, to a street, to a span — the life-history calendar's own opening
(Freedman et al. 1988, "In what city and state were you living when you turned
15… Until what month and year did you live there… Where did you live next?")
run as a conversation.

`landmarks-vague-is-an-answer` and `landmarks-skip-is-final` are the two the
lane exists to protect: the coarse answer that is received rather than
sharpened, and the decline that is never asked twice.

`landmarks-reports-the-arithmetic-never-asks-agreement` pins the line the go-deep research draws (§4.3, Lindsay et al. 2004): saying what the
arithmetic gives you is right — *"anything at the Bell house lands between '84 and '90 now"* — and naming a date to be agreed with is the
banned move. `timeline_interaction.proposes_a_date` is the one definition, run by both lanes.

`landmarks-military-none-with-a-story-alongside` and
`landmarks-losses-are-recorded-not-only-received` are the two live v212
failures written as the turns they should have been: a plain *"I have not
served"* files `{"domain": "military", "none": true}` while the mission story
it arrived with goes to the capture path, and named losses file as records
carrying the name and the relationship with no date invented.
`landmarks-ambiguous-answer-is-not-a-missed-record` is their guard rail — a
real but unnameable answer that records nothing and must NOT lint, because
`landmark_gates.answer_must_record` blocks a send and ambiguity fails toward
skip.

`landmark-answer-not-recorded-bad-01.json` is INTENTIONALLY BROKEN and is not
part of the seat: it holds both live failures verbatim (surnames synthesized)
as the RECORDER's acceptance — the warm reply the person actually got, the
empty first extraction, and the extraction that comes back after ONE
`landmarks_interaction.recording_reminder()`. `tests/test_landmarks.py` drives
`landmark_recorder.record_answer` from those raw completions and walks the
whole path: lint fires, reminder, clean emit — and the same cases again with
the reply removed entirely, because the recorder never needed it (ADR 0028).
