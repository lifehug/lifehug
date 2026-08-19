# ADR 0021: Focus Candidate is an independent evidence-gathering Interaction

Date: 2026-08-18
Status: proposed

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
runtime code validates exact spans and recomputes readiness. A distinct later
user span confirms a ready assessment. Completion delegates unchanged to
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

🤖 Generated with GPT-5.6-Sol via Codex
