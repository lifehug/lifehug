# Context manifest — Arc Walk

The registry resolves `conversation -> arc_walk`. Parent and child identity,
behavior, examples, router, and deflection append in that order with
provenance. This context recipe and turn instructions are child leaf authority.

Per turn, assemble composed identity, behavior, and examples; bounded
Conversation context (profile, record, session) exactly as the parent
specifies; this package's turn instructions, substituting `{arc_stage}`,
`{agenda}`, `{focus_label}`, `{episode_size}`, `{answered_k}`, and `{plan_n}`;
then one final `UNTRUSTED_DATA` JSON block. The structured output is the
parent's, plus the one optional `answered_question_id` field.

The agenda block is the ONLY plan the model ever sees, and it is rendered by
`arc_walk.render_agenda` from a plan `arc_walk.build_arc_plan` recomputed at
Play time. Nothing about the plan is persisted (owner ruling 4), so a prompt
assembled a second later may legitimately carry a shorter agenda — that is the
design, not drift.

The complete exact transcript is caller-held. Prompt trimming never changes
which questions are open, what was answered, or what an answer files against.
