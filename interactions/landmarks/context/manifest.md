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

Nothing else is added. The person's answers, the vault, and the timeline are
all reached through the ordinary Conversation context; this Interaction adds
exactly the three substitutions above.
