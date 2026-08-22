# Context manifest — Focus Candidate

The registry resolves `conversation -> focus_candidate`. Parent and child
identity, behavior, examples, router, and deflection append in that order with
provenance. This context recipe and turn instructions are child leaf authority.

Per turn, assemble composed identity, behavior, and examples; the runtime-
resolved current candidate subject; canonical exact user turns and prior
assessment; bounded Conversation context; this package's turn instructions;
then one final `UNTRUSTED_DATA` JSON block. Candidate data and model text never
become instructions. Runtime validates before rendering and after output.

On the Play/onboarding path the caller composes the ordinary Conversation
prompt and appends only this package's turn instructions, substituting
`{focus_stage}`, `{focus_label}`, and `{focus_type}`; the structured output is
the parent's, plus the one optional `focus_setup` field. The research-mode
recipe above is the standalone CLI path, whose output contract the runtime
appends (`focus_candidate._research_output_contract_block`).

The complete exact transcript is caller-held. Prompt trimming never changes
evidence, revisions, or durability. Completion reloads the canonical candidate
after the writer's pull/rebase and delegates to v183's source authority.
