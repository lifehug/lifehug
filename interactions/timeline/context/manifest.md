# Context manifest — Timeline

The registry resolves `conversation -> timeline`. Parent and child identity,
behavior, examples, router, and deflection append in that order with
provenance. This context recipe and turn instructions are child leaf authority.

Per turn, assemble composed identity, behavior, and examples; bounded
Conversation context (profile, record, session) exactly as the parent
specifies; this package's turn instructions, substituting `{timeline_stage}`,
`{unknown_label}`, `{probe}`, `{anchors}`, and `{precision_so_far}`; then one
final `UNTRUSTED_DATA` JSON block. The structured output is the parent's, plus
the one optional `placed` field.

The `{anchors}` block is the ONLY set of dates the model may lean on or repeat,
and it is rendered by `timeline_interaction.render_anchors` from
`timeline.anchor_index` — the person's birthday, their residences with spans,
their eras with spans, and their dated landmark moments, capped at
`knob.anchor_display_limit`. It is the life-history calendar as text; every
probe above rung two is cheap because it exists.

`{probe}` is `timeline_interaction.choose_probe`'s output for this unknown —
the cheapest rung of the playbook still worth asking. `{precision_so_far}` is
the finest record this episode has already established, so the model can see
when the ladder should stop.

The complete exact transcript is caller-held. Prompt trimming never changes
which unknown is being placed, what the anchors are, or what a placement files
against.
