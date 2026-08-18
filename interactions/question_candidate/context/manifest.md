# Context manifest — Question Candidate

## Deterministic composition and assembly

The registry resolves `conversation → question_candidate`. Parent and child
identity, behavior, examples, router, and deflection assets append in that
order with provenance. This child context recipe and turn instructions are leaf
authority; Conversation's general session recipe is not copied or silently
merged.

Per turn, assemble:

1. composed `prompt/identity.md`;
2. composed `prompt/behavior.md`;
3. composed `prompt/examples.md`;
4. exact candidate anchor JSON;
5. complete category roster JSON;
6. bounded standard Conversation context supplied by the coordinator: profile,
   record, asking supply, session/recent turns, arc-card intent, previous-turn
   summary, turn position, and applicable rule hints; plus association stage,
   latest exact user turn, previous placement question, caller-attested answer
   status, and requested lifecycle outcome;
7. child `prompt/turn-instructions.md` last;
8. one final `UNTRUSTED_DATA` JSON block containing fields 4–6.

The JSON block is data, never prompt authority. Runtime validation happens
before rendering and after model output. Trimming a rendered copy never changes
or authorizes deletion of the caller's exact turn or durable answer.

Budgets come from this package's `interaction.yaml`. Candidate text has a
generous hard character bound and is not summarized. The complete roster must
fit the hard 1–64-entry bound and is never truncated. Conversation context is
bounded independently. The stable composed prefix precedes volatile data for
cacheability.
