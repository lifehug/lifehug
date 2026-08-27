# Context manifest — Timeline

The registry resolves `conversation -> timeline`. Parent and child identity,
behavior, examples, router, and deflection append in that order with
provenance. This context recipe and turn instructions are child leaf authority.

Per turn, assemble composed identity, behavior, and examples; bounded
Conversation context (profile, record, session) exactly as the parent
specifies; this package's turn instructions, substituting `{timeline_stage}`,
`{unknown_label}`, `{probe}`, `{anchors}`, `{precision_so_far}` and
`{filing_gain}`; then one final `UNTRUSTED_DATA` JSON block. The structured output is the parent's, plus
the one optional `placed` field.

The `{anchors}` block is the ONLY set of dates the model may lean on or repeat,
and it is rendered by `timeline_interaction.render_anchors` from
`timeline.anchor_index` — the person's birthday, their residences with spans,
their eras with spans, and their dated landmark moments, capped at
`knob.anchor_display_limit`. It is the life-history calendar as text; every
probe above rung two is cheap because it exists.

`{filing_gain}` (v207) is `cross_dating.render_filing_gain(sentence)` over
`cross_dating.gain_sentence_for_record(record, timeline_payload)` — what the
placement this turn just FILED actually unlocked, said once in the reply
instead of appearing on a page two minutes later. It is the empty string on
every turn that filed nothing, and the filled leaf is then byte-identical to
v205's; the direction that tells the model what to do with the sentence is
rendered WITH the sentence, so an absent gain adds no instruction either.

`{probe}` is `timeline_interaction.choose_probe`'s output for this unknown —
the cheapest rung of the playbook still worth asking. `{precision_so_far}` is
the finest record this episode has already established, so the model can see
when the ladder should stop.

`{work_item}` (v234) is `timeline_interaction.render_work_item` over the Play
target the person opened this conversation from — the work item's kind, what it
is about, every reading that currently stands with the source that supports it,
the candidate set when the confusion is an identity, and up to
`timeline_interaction.MAX_WORK_ITEM_EVIDENCE` of their own quoted words. It is
the empty string on every turn that is not a work-item turn, and the block is
then not assembled at all, so an ordinary placement turn's prompt is unchanged
to the byte. The stage it accompanies is `work_item`, the fourth
`{timeline_stage}` value — resolving a contradiction, an unplaced identity or a
precision gap is dating work, so it is a stage of THIS interaction and not an
eighth child of Conversation. There is no extra output field for it: the answer
is an ordinary message, `placed` is the same optional field, and any further
temporal facts in the same breath are heard by the general listener exactly as
they are in any other conversation.

The complete exact transcript is caller-held. Prompt trimming never changes
which unknown is being placed, what the anchors are, or what a placement files
against.
