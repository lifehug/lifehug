# ADR 0018: Question Candidate is a composed Interaction

Date: 2026-08-18
Status: proposed

## Context

Issue #170 replaces the setup modal between a question candidate and Answer
Now. A user pressing Play should reach Home/Today in a new tab with the exact
candidate preloaded and begin answering immediately. Category/focus placement
is necessary durable metadata, but repository structure must not become a
prerequisite UI. Placement may become clear from the candidate or from content
before, during, or after the substantive answer; only unresolved ambiguity
should produce one natural conversational question.

The earlier draft modeled placement as a specialized step inside Conversation.
That collapses two independently auditable roles. Conversation owns reusable
chat mechanics. Question Candidate owns a candidate anchor, placement timing,
answered-completion criteria, and candidate lifecycle coordination. The owner
uses “Interaction” to mean a complete, independently registered definition
with its own identity, behavior, context, router, evals, version, registration,
and seat surface—not a prompt fragment or runtime step.

A copied fork of Conversation would satisfy directory shape while creating
immediate behavioral drift. The framework did not previously have an explicit
registry or inheritance authority, so composition itself must become a small,
generic, audited framework contract.

## Decision

Add `question_candidate`, canonically packaged at
`interactions/question_candidate/`, as an independently registered Interaction.
Add `interactions/registry.json` as the closed list of executable Interaction
packages and `system/interaction_registry.py` as the stdlib-only validation,
lineage, asset-composition, and package-audit authority. A package absent from
the registry is not executable or seatable.

Question Candidate declares `extends: conversation` and an exact parent
manifest version. Its manifest declares which required assets append
parent-to-child and which use leaf authority. Composition reads current parent
files directly, inserts deterministic package/asset provenance, rejects path
escape, missing assets, unknown policy, cycles, unregistered parents, and
parent-version mismatch, and never permits callers to pick a different merge
strategy. Question Candidate does not copy Conversation clauses. Conversation
is restored to its v180 package, manifest, prompts, router, and eval bytes; an
ordinary Conversation caller never loads the child.

Question Candidate composes Conversation identity, behavior, examples,
router, and deflection so it inherits chat voice, response-before-ask,
receipts, question craft, scope, and closing mechanics. Its leaf context and
turn instructions own candidate-specific assembly/output while accepting the
standard bounded Conversation profile/record/asking-supply/session/arc/turn
context object from the coordinator. It has its own role
keys and eval harness. Passing Conversation alone does not seat a model in the
child; candidate-specific plus inherited-parity gates must also pass.

The runtime receives an exact hashed `CandidateAnchor` and a complete ordered
closed `CategoryRoster` of 1–64 entries. Candidate, category, and user strings
are rendered only as untrusted JSON data. The model has no tools and may echo
only one exact roster id. The runtime rejects unknown keys, duplicate ids,
forged revisions, ambiguous types, fuzzy/case-folded/out-of-roster matches,
invalid action combinations, and stale selected-category state.

Play supplies lifecycle action `engage`. It may resolve placement silently or
defer it and begin the substantive exchange immediately; initial Play never
requires a placement question. During engaged turns the model returns a
Conversation-shaped reply plus `placement_only|answer|mixed` metadata and one
placement action:

- `resolved`: exact roster id at confidence `>= 0.8`, no question;
- `defer`: no id/question, substantive exchange continues; or
- `ask_now`: no id, below threshold, exactly one natural open placement
  question embedded as the sole question in the reply.

The caller retains every original user turn independent of model metadata.
Only the durable coordinator may attest `answer_status: durable`. An answered
candidate becomes complete only when durable answer, revision-valid placement,
and answered outcome are all resolved. Play alone remains engaged and has no
promotion meaning. Explicit Decline/defer are caller actions and can terminate
without a model judgment; Direct Promote bypasses this Interaction entirely.

Canonical placement revisions bind the candidate revision, selected category
id, and selected category revision, not the entire roster. Selected-category
removal/rename/focus remapping invalidates placement; unrelated roster churn
does not. PR A is pure coordination authority and writes no candidate, session,
vault, question-bank, projection, or Git state.

Promotion remains separate. PR B will own question-id allocation, idempotency,
question-bank/candidate mutation, provenance, Git commit, and a structured
receipt containing canonical `question_id`, `category`, and `commit_sha`. No
PR A status or field claims that promotion occurred.

## Consequences

- The framework gains a reusable, auditable composition mechanism rather than
  a one-off Question Candidate loader. Future inheritance must use the same
  registry and explicit per-asset policy.
- The child can inherit Conversation fixes without copy drift, while an exact
  parent-version mismatch forces conscious review before seating/execution.
- Ordinary Conversation remains byte- and behavior-identical to v180.
- Platform #469 must route Play directly to Home/Today with candidate id and
  exact question preloaded, use Question Candidate (not a modal and not plain
  Conversation) for the engaged exchange, and persist progress only after
  revalidating runtime decisions.
- Category association can finish before, during, or after answer content. A
  partial durable answer is retained while placement remains unresolved.
- Roster completeness failures stop the interaction rather than silently
  removing valid choices.
- v181 is an intermediate upstream release. The platform waits for PR B's
  final release, then reconciles and pins both changes together.

## Platform pin-bump reconciliation surfaces

- Registry/composition: `interactions/registry.json`,
  `system/interaction_registry.py`, lineage/version rules, provenance seams,
  and package audit requirements.
- Independent package: all files under `interactions/question_candidate/`,
  manifest id/version/roles/composition/knobs/budgets, and empty default seat.
- Runtime/CLI: `system/question_candidate.py`,
  `system/question_candidate_evals.py`, `question-candidate-prompt`, and
  `question-candidate-evals`.
- Exact anchor/roster/input/proposal/decision/completion schemas; closed stage,
  turn-kind, placement-action, status, answer-status, requested-outcome, and
  candidate-outcome vocabularies; canonical revision recipes.
- Eval fixture/prediction shapes and child gate keys, including inherited
  Conversation parity and no-copy-drift checks.
- Removed interim Conversation step/prompt/eval surfaces; ordinary Conversation
  returns to v180 package semantics and bytes.
- Product routing: green Promote goes to PR B promotion; red Decline supplies
  explicit decline; Play opens Home/Today in a new tab, preloads candidate id
  and question, starts substantive exchange immediately, never promotes, and
  permits placement resolution before/during/after.

🤖 Generated with GPT-5.6-Sol via Codex
