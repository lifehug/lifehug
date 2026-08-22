# Entity Candidate Interaction

`entity_candidate` is an independently registered, auditable Interaction for
one entity roster candidate. It exact-composes Conversation by reference and
owns only the candidate-specific identity, evidence, next-gap, confirmation,
and completion contract.

**Play graduates.** Platform ADR 0020 and contract review-loop/57 retired the
model this Interaction was designed against: pressing Play runs
`entity-verdict <type> <slug> graduate` in a background job — one roster
mutation, one commit — and opens this conversation immediately. This
Interaction is that conversation, and its job is IDENTITY: the names they go
by, how they are related, whether they are living, and whether the roster
already holds this same person under a different name. The first reply
receives the answer, says once that they were added, and asks at most one
identity question; afterwards identity changes only when the user signals a
change. The model still writes nothing, graduates nothing, and claims nothing
— the platform has already graduated.

**No focus is ever created here.** The conversation may OFFER one, at most
once per session and only for an offer-worthy entity; a yes is recorded as
`entity_setup.start_focus` and the caller hands off through
`focus-recommend-from-entity`, which appends one pending recommendation row
and nothing else.

**Platform twin.** A host REPLAYs this package and reads exactly these —
nothing else is a contract (the shared shape: `interactions/README.md`
§ "The child-interaction paradigm"):

| What | Where |
|---|---|
| The tab's opening line | `entity_candidate.opening_question(name, entity_type)` |
| The `{entity_stage}` this turn is in | `entity_candidate.entity_stage_for_session(session)` |
| The `{possible_duplicates}` to substitute | `entity_candidate.possible_duplicates(entity_type, name, roster)` |
| Whether the offer is allowed at all | `entity_candidate.is_offer_worthy(entity_type, roster_entry)` |
| The one additive turn-output field | `conversation_delivery.parse_turn_output(...)["entity_setup"]`, enabled by `TurnShape(entity_stage=…)` |
| Closed validation of that field | `entity_candidate.validate_entity_setup(value, roster_slugs=…)` |
| The seven identity lints | `entity_candidate.lint_entity_setup_reply(text, stage=…, user_signaled=…, offered_before=…)` |
| The leaf the caller REPLAYs verbatim | `prompt/turn-instructions.md`, substituting `{entity_stage}`, `{entity_name}`, `{entity_type}`, `{possible_duplicates}` |
| Graduation + identity in ONE call | `entity-verdict <type> <slug> graduate [--alias A]... [--relationship R] [--living\|--not-living] [--maps-to SLUG]` |
| The focus hand-off seam (the only one) | `focus-recommend-from-entity <type> <slug>` |

**The research-mode assets are superseded for the Play path, not deleted.**
`prompt/behavior.md`'s evidence/readiness/completion rules, the seven-dimension
rubric, `action`/`next_gap`, `research_gates.*`, and
`entity_candidate.parse_entity_candidate_output` /
`validate_entity_candidate_decision` / `resolve_entity_candidate_completion`
all still serve the standalone CLI path
(`lifehug.py entity-candidate-prompt` / `entity-candidate-complete`), whose
structured-output contract now lives in
`entity_candidate._research_output_contract_block()` rather than in the leaf —
the leaf is appended to an ordinary Conversation prompt on the Play path, and
two competing output contracts in one prompt is a defect. Nothing about that
CLI path changed otherwise.

Run the deterministic seat gate with:

```bash
python3 system/lifehug.py entity-candidate-evals --json
```

See `docs/pr-specs/entity-identity-context.md` (v190) and
[ADR 0022](../../docs/adr/0022-entity-candidate-interaction.md), amended by it.
