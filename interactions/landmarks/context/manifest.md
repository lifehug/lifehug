# Context manifest — Landmarks

The caller assembles, in this order:

1. Conversation's own session block, unchanged.
2. `LANDMARKS` — `landmarks_interaction.render_landmarks(rows)` over
   `landmarks_interaction.landmark_rows(...)`, capped at
   `knob.landmark_display_limit`. Status only, never counts of what remains.
3. `THE ONE THING TO ASK THIS TURN` — the `text` of the first row from
   `landmarks_interaction.open_landmarks(rows)`, which is
   `landmarks_interaction.next_rung`'s output for that domain.
4. `LANDMARK_STAGE` — `landmarks_interaction.landmark_stage_for_session(...)`.
5. `{filing_gain}` (v207) — `cross_dating.render_filing_gain(sentence)` over
   `cross_dating.gain_sentence_for_record(record, timeline_payload)`: what the
   landmark this turn just FILED actually unlocked ("Got it — that dates nine
   moments and your Childhood years."), said in the conversation instead of
   appearing on a page two minutes later. It is the empty string on every turn
   that filed nothing, and the filled leaf is then byte-identical to v205's —
   the direction that tells the model what to do with the sentence is rendered
   WITH the sentence, so an absent gain adds no instruction either.

The RECORDER is a separate pass with a separate leaf and is not part of this
assembly (ADR 0028). Its own block, `{known_entries}`, is
`landmarks_interaction.render_known_entries(landmarks, domain)` — the filed
ENTRIES of the one domain being asked about, not the domain statuses item 2
renders (v216).

Nothing else is added. The person's answers, the vault, and the timeline are
all reached through the ordinary Conversation context; this Interaction adds
exactly the four substitutions above.
