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

Nothing else is added in `collect` mode. The person's answers, the vault, and
the timeline are all reached through the ordinary Conversation context; that
mode adds exactly the four substitutions above.

## The `offer` mode adds three (v287, R3b, ADR 0033)

Add Landmark reverses the direction: the person volunteers text and the model
has to be able to say *"that overlaps your Boatworks years"* or *"this looks
like a second stay in Phoenix"* — which it can only do if what the vault
already knows is in front of it. Context awareness here is the MANIFEST's,
deterministically, not a clever prompt's. All three blocks are rendered by the
caller (`landmark_offer.offer_context`) from functions that live beside
`render_known_entries` and are pure over data the caller supplies. **The model
interprets; it does not fetch.**

6. `ROSTER` — `landmarks_interaction.render_roster(roster, landmarks=…)`: the
   people, places and organizations on file with their aliases, so "Katie" or
   "Mesa" resolves to a known entity or is flagged as new. Organizations the
   roster has not minted yet are named from the landmark entries of the
   domains whose `identity_kind` is `organization`, because a school the
   person has already told us about must resolve on the second telling.
7. `EXISTING EPISODES AND ERAS` —
   `landmarks_interaction.render_known_spans(projection)`: the episodes and
   named eras of the PUBLISHED calculated projection with their spans, read
   from the one materialized truth every other surface reads, so what the
   model is told matches what the page shows.
8. `AGE FRAMES` — `landmarks_interaction.render_age_frames(projection)`: the
   frames and the birth origin they are counted from, with the origin's own
   basis, so an age-relative phrase ("when I was about ten") has a coordinate
   and a CALCULATED origin never reads as a stated one.

The `offer` turn leaf (`prompt/turn-instructions-offer.md`,
`composition.offer_turn`) substitutes `{proposed_units}`
(`landmark_offer.render_proposal`) and `{open_questions}`
(`render_open_questions`), and keeps `{landmark_stage}` and `{filing_gain}`.
`landmark_offer.build_offer_turn(proposal, …)` composes it — `.replace`, never
`.format`, because the leaf carries the person's own words and their braces. The RECORDER and the LISTENER are the
same two passes the `collect` mode runs, with the same leaves and the same
`{known_entries}` block — the offer mode runs the listener with no domain and
then the recorder once per domain it named. There is no third extraction
prompt.
