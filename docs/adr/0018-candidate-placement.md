# ADR 0018: Question Candidate is a composed Interaction

Date: 2026-08-18
Status: amended 2026-08-21 by docs/pr-specs/question-candidate-placement-aside.md;
amended 2026-08-22 by docs/pr-specs/focus-onboarding-context.md

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

Every model-controlled reply, including `resolved` and `defer`, passes the
inherited Conversation lint engine before its placement action is accepted.

The caller retains every original user turn independent of model metadata.
Only the durable coordinator may attest `answer_status: durable`. An answered
candidate becomes complete only when durable answer, revision-valid placement,
and answered outcome are all resolved. Play alone remains engaged and has no
promotion meaning. Explicit Decline/defer are caller actions and can terminate
without a model judgment; Direct Promote bypasses this Interaction entirely.

Canonical placement revisions bind the candidate revision, selected category
id, and selected category revision, not the entire roster. Selected-category
removal/rename/focus remapping invalidates placement; unrelated roster churn
does not. An unplaced decision must carry neither a category revision nor a
placement revision; any non-null value is rejected as forged or stale state.
PR A is pure coordination authority and writes no candidate, session, vault,
question-bank, projection, or Git state.

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

## Amendment (2026-08-21)

Platform ADR 0020 (`lifehug-platform/docs/adr/0020-play-is-a-deep-link.md`)
and platform contract review-loop/45 ("Play is a background promotion")
retired the machine this decision was designed against: Play is a deep link
that starts promotion immediately, in a background worker job, so the
conversation never waits on the vault. `docs/pr-specs/question-candidate-
placement-aside.md` (issue #181, v188) is the smallest reconciling change:
exactly one new turn-output field (`placement: {category} | null`), no new
lifecycle states, no placement model purpose, no new platform mechanism.
Sentences this decision made that the amendment changes:

| Location in this ADR | Change |
|---|---|
| Decision, "Play supplies lifecycle action `engage`. It may resolve placement silently or defer it… initial Play never requires a placement question." | Replaced: Play promotes in the background with the inferred category (platform ADR 0020); the first reply states that placement once as an aside, or asks once when there is no confident category. |
| Decision, the three-bullet `resolved` / `defer` / `ask_now` block | Superseded for the Play path. One optional output field `placement: {category}` replaces the triple; `defer` is expressed as `placement: null`; `ask_now` becomes a first-reply-only property, not an action; `resolved`'s confidence number moves to the caller, which evaluates `target_category` against `knob.placement_confidence_threshold` before composing the turn. |
| Decision, "Play alone remains engaged and has no promotion meaning." | Reversed: Play is approval; promotion starts immediately in the background. |
| Decision, "An answered candidate becomes complete only when durable answer, revision-valid placement, and answered outcome are all resolved." | Placement is no longer a completion precondition (the question is already placed). Completion is durable answer + answered outcome. |
| Consequences, "Category association can finish before, during, or after answer content. A partial durable answer is retained while placement remains unresolved." | Replaced: category association is settled at promotion time; a later correction is a move, not a resolution. There is no held answer (platform ADR 0020). |
| Consequences, "Platform #469 must route Play directly to Home/Today… and persist progress only after revalidating runtime decisions." | Superseded by platform ADR 0020 + review-loop/45: Play is a deep link, promotion is a background worker job, and every message files through the ordinary capture path. |
| Consequences, "v181 is an intermediate upstream release. The platform waits for PR B's final release…" | Historical; PR B shipped (`system/candidate_promotion.py`, v187). |
| Pin-bump reconciliation surfaces, "closed stage, turn-kind, placement-action, status…" | `placement-action` leaves the vocabulary list; `placement` joins the turn-output shape row. |

Unchanged by this amendment: the registry/composition mechanism, the closed
category roster and its exact-match discipline, the candidate anchor/revision
recipes, rule 8's "no lifecycle claims" doctrine, and ordinary Conversation's
byte-for-byte v180 freeze. `parse_question_candidate_output` and
`validate_question_candidate_decision` (the ADR-0018 `resolved|ask_now|defer`
triple) stay live for the standalone `question-candidate-prompt` CLI path
until a follow-up removes them — only the Play path's contract changes here.

A `question-move` package verb (re-id + alias a promoted question between
categories — a question's category is the first character of its id) is
required to complete the after-promotion half of this design and is
deliberately out of scope: filed as a follow-up OSS issue.

## Amendment (2026-08-22) — the additive-field discipline has a second instance

Recorded by `docs/pr-specs/focus-onboarding-context.md` (v189). **No decision
in this ADR changes.** This amendment exists so the pattern is not re-derived
a third time from scratch.

The 2026-08-21 amendment replaced the `resolved|ask_now|defer` triple with one
optional turn-output field, `placement`, split across two validation layers:
structural in `conversation_delivery.parse_turn_output` (owns no vocabulary,
degrades to `None`, never raises) and closed in
`question_candidate.validate_placement` (exact roster membership only). v189
adds the second instance of exactly that shape, for FOCUS candidates:

| | question candidates (v188) | focus candidates (v189) |
|---|---|---|
| output field | `placement: {category} \| null` | `focus_setup: {objective?, type?, relationship?, living?, label?} \| null` |
| gated on | `TurnShape.placement_stage` | `TurnShape.focus_stage` |
| structural layer | `conversation_delivery._parse_placement` | `conversation_delivery._parse_focus_setup` |
| closed layer | `question_candidate.validate_placement` (category roster) | `focus_candidate.validate_focus_setup` (`roadmap.FOCUS_TYPES`, `focus_candidate.FOCUS_RELATIONSHIPS`) |
| stage source | `placement_stage_for_session` (transcript) | `focus_stage_for_session` (transcript) |
| stages | `assert` \| `ask` \| `settled` | `establish` \| `settled` |
| lints | seven `placement_gates.*` | six `focus_setup_gates.*` |

The invariants both instances share, and which any third instance inherits:
the field is optional; absent or malformed degrades to the pre-existing
behavior and never errors a turn; the appendix is byte-identical when the
`TurnShape` gate is `None` (a required test on both); the stage is read from
the transcript rather than stored; and the model never raises the topic itself
after the first reply — only a user signal produces a value.

Pin-bump reconciliation surfaces: `focus_setup` joins the turn-output shape
row alongside `placement`.

🤖 Generated with Claude Opus via Claude Code
