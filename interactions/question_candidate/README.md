# Question Candidate Interaction

## Why this Interaction exists

Question Candidate is the behavior authority for turning one exact candidate
question into a substantive, correctly placed answer without making the user
operate repository structure first. **Play** begins the exchange immediately;
category/focus association can resolve from the candidate or from conversation
before, during, or after the answer. One natural placement question is allowed
only when it is still needed and appropriate. Play promotes in the background
with the inferred category (platform ADR 0020); this Interaction states that
placement once, as an aside, and accepts a correction as a move.

This is deliberately separate from Conversation. Conversation supplies chat
mechanics. Question Candidate owns the candidate anchor, placement timing,
completion criteria, and `engaged|answered|declined|deferred` lifecycle facts.
It composes Conversation files through the registered framework loader instead
of copying them. See [ADR 0018](../../docs/adr/0018-candidate-placement.md).

## Product actions

- **Play** enters this Interaction with `requested_outcome: engage`, the exact
  candidate id/question, and the complete category roster. It is neither
  promotion nor acceptance.
- **Decline** enters with `requested_outcome: decline` and resolves without a
  model call.
- **Defer** enters with `requested_outcome: defer` and resolves without a model
  call.
- **Promote** does not enter this Interaction. PR B of issue #170 shipped that
  explicit idempotent write and receipt (`system/candidate_promotion.py`,
  v187); Play now triggers it in the background.

## How it is built

`interaction.yaml` registers an exact Conversation parent version and declares
append-versus-leaf asset composition. `system/interaction_registry.py` audits
the package and assembles inherited assets with provenance. The child behavior
adds only candidate responsibilities; all ordinary chat rules stay in
Conversation.

`system/question_candidate.py` validates closed-roster input and untrusted
model proposals. It is pure: it does not write candidate, answer, question
bank, session, vault, projection, or Git state. A consuming coordinator alone
attests that an answer is durable and revalidates revisions before transition.

## The Play path's surface (the Platform twin)

**Platform twin.** A host (the hosted platform, or any other runtime)
REPLAYs this package and reads exactly these — nothing else is a contract:

| What | Where |
|---|---|
| The tab's opening line | the candidate's own question text — this child has no `opening_question` helper |
| The `{placement_stage}` this turn is in | `question_candidate.placement_stage_for_session(session)` |
| The one additive turn-output field | `conversation_delivery.parse_turn_output(...)["placement"]`, enabled by `TurnShape(placement_stage=…)` |
| Closed validation of that field | `question_candidate.validate_placement(value, roster=…)` |
| The seven placement lints | `question_candidate.lint_placement_reply(text, stage=…, roster=…, placement_question=…)` |
| The leaf the caller REPLAYs verbatim | `prompt/turn-instructions.md`, substituting `{placement_stage}` and `{focus_label}` |
| The confidence knob the CALLER evaluates | `knob.placement_confidence_threshold: 0.8` (`interaction.yaml`) |
| The promotion the host runs in the background | `system/candidate_promotion.py` (v187) |

**Play approves and starts** (platform ADR 0020): the promotion is already
running when the first reply is composed, so this Interaction never claims
it, gates on it, or waits for it. The shared shape lives in
`interactions/README.md` § "The child-interaction paradigm".

## Evaluation and seating

`python3 system/lifehug.py question-candidate-evals` runs the independent
harness. It audits registration/composition, validates synthetic fixtures,
scores sample predictions and completion/staleness cases, runs inherited
Conversation lints, and skips live seating loudly when no provider is ready.
A model is seated only after this harness passes; passing Conversation alone is
not sufficient. Provider overlays remain empty until a verified delta exists.

🤖 Generated with GPT-5.6-Sol via Codex
