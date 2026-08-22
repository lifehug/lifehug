# ADR 0021: Focus Candidate is an independent evidence-gathering Interaction

Date: 2026-08-18
Status: amended 2026-08-22 by docs/pr-specs/focus-onboarding-context.md

## Context

Issue #172 requires pending Focus recommendations to be researchable through a
natural conversation before approval. Conversation already owns chat mechanics,
Focus Curation owns duplicate judgment, and v183 owns exact candidate-research
evidence/source durability. Folding this behavior into any of those would hide
its prompt, lifecycle, eval, and seat boundary. Copying Conversation would make
ordinary chat and candidate research drift independently.

The issue names eight useful dimensions while v183 deliberately freezes a
seven-key source dimension schema plus a separate concrete-evidence minimum.
The interaction must honor both contracts without weakening grounding or
silently versioning the source format.

## Decision

Add registered `focus_candidate`, exact-composed from Conversation 1.0.0. It
owns candidate anchoring, natural next-gap choice, an eight-dimension
conversation rubric, explicit confirmation, and completion coordination. It
does not own approval or Git writes.

The first seven semantic dimensions map to v183's seven source dimensions.
`grounded_evidence` remains a separate interaction gate satisfied by an exact
concrete-event/observation span that also supports a source dimension. Trusted
runtime code validates exact spans and recomputes readiness. A distinct later,
closed whole-span affirmative user span confirms a ready assessment; qualified
or negated phrasing is not confirmation. Completion delegates unchanged to
`candidate_research.resolve_candidate_research_source()`; the recommendation
remains pending until the existing approval/autopilot authority acts.

Alternatives rejected: a Conversation mode is not independently auditable or
seatable; a Focus Curation mode conflates dedupe judgment with research; copied
Conversation prompts create drift; adding an eighth v183 source-schema key
breaks the frozen generic authority without adding evidence safety; approving
at completion collapses research consent into the separate creation decision.

## Consequences

- Future Focus Candidate behavior changes belong in its package/runtime/evals,
  while Conversation behavior remains inherited by exact reference.
- Play/start is read-only. Model output has no lifecycle, write, Git, receipt,
  or approval authority.
- Every completion uses v183's source resolver and post-pull subject
  revalidation; a second writer or approval shortcut is forbidden.
- Platform Play may deep-link into this Interaction after pinning v184, but
  must resolve the anchor server-side and must not approve on entry/completion.
- Entity Candidate may reuse the generic v183 source authority but must ship as
  its own registered package, runtime, rubric, evals, and seat.

## Amendment (2026-08-22) — Play approves, and this Interaction onboards

Recorded by `docs/pr-specs/focus-onboarding-context.md` (v189), forced by
platform ADR 0020 and platform contract review-loop/54. The Interaction is
not withdrawn; its PREMISE moved, and one path through it is superseded.

| Location in this ADR | Change |
|---|---|
| Decision, "It does not own approval or Git writes." | **Unchanged as to the model** — it still writes nothing and claims nothing. What moved is who has already acted: the platform approves the recommendation and scaffolds the Focus in a background job at Play, before the first reply is composed. |
| Consequences, "Play/start is read-only." | **Reversed.** Play is approval + start. The conversation that opens is onboarding — it establishes what the focus is about and how far it reaches — not research toward a later approval decision. |
| Consequences, "Platform Play may deep-link into this Interaction after pinning v184, but must resolve the anchor server-side and must not approve on entry/completion." | **Superseded.** Play approves on entry by design. The platform's only model-facing job is substituting `{focus_stage}` / `{focus_label}` / `{focus_type}` into `prompt/turn-instructions.md` and recording the turn's optional `focus_setup` output (owner ruling 5, 2026-08-22: "no platform model placement"). |
| Decision, the eight-dimension rubric, evidence spans, readiness, explicit confirmation, and completion delegation to `candidate_research` | **Superseded for the Play path; retained unchanged for the standalone CLI path** (`lifehug.py focus-candidate-prompt` / `focus-candidate-complete`, `research_gates.*`, `parse_focus_candidate_output`, `validate_focus_candidate_decision`, `resolve_focus_candidate_completion`). Nothing was deleted. That path's structured-output declaration moved out of the prompt leaf into `focus_candidate._research_output_contract_block()`, because the leaf is now replayed on top of an ordinary Conversation prompt that declares its own output contract. |
| Consequences, "Future Focus Candidate behavior changes belong in its package/runtime/evals" | Honored: the onboarding behavior, its six `focus_setup_gates.*` lints, and its seven goldens all live in this package. |

What the Play path adds, in full: one pure opener
(`focus_candidate.opening_question`), one transcript-derived stage
(`focus_stage_for_session` — no new session field, exactly as ADR 0018's
amendment established for placement), one additive turn-output field
(`focus_setup`, structurally parsed in `conversation_delivery` and validated
against closed vocabularies in `focus_candidate`), six lints, and one seed-time
CLI flag (`research-expand --context-file`) so the questions seeded for the
focus are grounded in what the person actually said when they started it. No
new lifecycle state and no new model purpose.

🤖 Generated with Claude Opus via Claude Code
