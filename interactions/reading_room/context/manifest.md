# Context manifest — Reading Room

The registry resolves `conversation -> reading_room`. Parent and child
identity, behavior, examples, router, and deflection append in that order with
provenance. This context recipe and the turn instructions are child leaf
authority.

The caller assembles, in this order:

1. Conversation's own session block, unchanged.
2. `IN THE ROOM` — `reading_room.render_inventory(inventory)`, where
   `inventory` is what the person said they had in front of them, carried
   forward from the `open` turn. Before they have said, the block says so and
   the turn IS the inventory question.
3. `TODAY'S PLAN` — `reading_room.render_agenda(plan)` over
   `reading_room.recompute_plan(timeline.timeline_data(), ...)`, capped at
   `knob.agenda_display_limit`. Each line is what the ask would UNLOCK. Never
   a count of what remains.
4. `THE ONE THING TO ASK THIS TURN` — `reading_room.render_next_ask(plan)`,
   which is the head of the same plan plus its precision grade and what that
   grade buys.
5. `ANCHORS` — `timeline_interaction.render_anchors(anchors)`, exactly as the
   timeline lane assembles it. `placed.anchors` is validated against this set
   and nothing else.
6. `READING_ROOM_STAGE` — `reading_room.reading_room_stage_for_session(...)`.

Nothing else is added. The person's answers, the vault, and the timeline are
all reached through the ordinary Conversation context.

**The plan is recomputed, never persisted.** `recompute_plan` runs against the
graph as it now stands, so a prompt assembled after a placement legitimately
carries a shorter agenda — that is the design (design consequence 8), not
drift. There is no dig state, no homework inbox, and no outstanding-item
tracking anywhere in this Interaction.

The structured output is the PARENT's, plus the two fields this lane REUSES —
`placed` (the timeline lane's) and `landmark` (the landmarks lane's) — both
opened by the single `TurnShape.reading_room_stage` gate. This Interaction
mints no output field of its own.
