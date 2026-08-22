# ADR 0022: Entity Candidate is an independent evidence-gathering Interaction

Date: 2026-08-18
Status: amended 2026-08-22 by docs/pr-specs/entity-identity-context.md

## Context

Issue #172 requires pending entity roster candidates to be researchable through a
natural conversation before approval. Conversation already owns chat mechanics,
entity lifecycle owns duplicate judgment, and v183 owns exact candidate-research
evidence/source durability. Folding this behavior into any of those would hide
its prompt, lifecycle, eval, and seat boundary. Copying Conversation would make
ordinary chat and candidate research drift independently.

The issue names seven useful dimensions while v183 deliberately freezes a
seven-key source dimension schema plus a separate concrete-evidence minimum.
The interaction must honor both contracts without weakening grounding or
silently versioning the source format.

## Decision

Add registered `entity_candidate`, exact-composed from Conversation 1.0.0. It
owns candidate anchoring, natural next-gap choice, a seven-dimension
conversation rubric, explicit confirmation, and completion coordination. It
does not own approval or Git writes.

The first seven semantic dimensions map to v183's six source dimensions.
`grounded_evidence` remains a separate interaction gate satisfied by an exact
concrete-event/observation span that also supports a source dimension. Trusted
runtime code validates exact spans, recomputes readiness, and evaluates the
closed type meaning from canonical quotes (not a reference count). A distinct later,
closed whole-span affirmative user span confirms a ready assessment; qualified
or negated phrasing is not confirmation. Completion delegates unchanged to
`candidate_research.resolve_candidate_research_source()`; the recommendation
remains pending until the existing automatic eligibility or owner verdict authority acts.

Alternatives rejected: a Conversation mode is not independently auditable or
seatable; a entity lifecycle mode conflates dedupe judgment with research; copied
Conversation prompts create drift; adding another v183 source-schema key
breaks the frozen generic authority without adding evidence safety; approving
at completion collapses research consent into the separate creation decision.

## Consequences

- Future Entity Candidate behavior changes belong in its package/runtime/evals,
  while Conversation behavior remains inherited by exact reference.
- Play/start is read-only. Model output has no lifecycle, write, Git, receipt,
  or approval authority.
- Every completion entrypoint first recomputes the Entity interaction gates,
  validates a distinct current explicit confirmation, and then uses v183's
  source resolver and post-pull subject revalidation; a second writer or
  approval shortcut is forbidden.
- Platform Play may deep-link into this Interaction after pinning v185, but
  must resolve the anchor server-side and must not approve on entry/completion.
- Entity Candidate may reuse the generic v183 source authority but must ship as
  its own registered package, runtime, rubric, evals, and seat.

🤖 Generated with GPT-5.6-Sol via Codex

## Amendment (2026-08-22) — Play graduates; this Interaction establishes identity

Recorded by `docs/pr-specs/entity-identity-context.md` (v190), which applies
platform ADR 0020 + contract review-loop/57 to entity candidates the way v189
applied ADR 0020 + review-loop/54 to focus candidates.

Sentences this decision made that the amendment changes:

| Location in this ADR | Change |
|---|---|
| Decision, "It does not own approval or Git writes." | Unchanged as to the MODEL, but the surrounding premise moves: the platform graduates at Play, in a background job (`entity-verdict <type> <slug> graduate`); this Interaction is the identity conversation that follows, not research toward a later graduation. |
| Consequences, "Play/start is read-only." | **Reversed.** Play is graduation + start. The model still writes nothing, graduates nothing and claims nothing; the *platform* has already graduated. |
| Consequences, "Platform Play may deep-link into this Interaction after pinning v185, but must resolve the anchor server-side and must not approve on entry/completion." | Superseded: Play graduates on entry by design. The platform's only model-facing job is substituting `{entity_stage}`, `{entity_name}`, `{entity_type}` and `{possible_duplicates}` into the leaf and recording `entity_setup` (owner ruling 5 — no model placement of its own). |
| Decision, the seven-dimension research rubric, readiness, confirmation and completion delegation | **Superseded for the Play path, retained for the standalone CLI path.** `entity-candidate-prompt` / `entity-candidate-complete`, `parse_entity_candidate_output`, `validate_entity_candidate_decision`, `resolve_entity_candidate_completion` and their `research_gates.*` are unchanged. Their structured-output contract moved out of the prompt leaf into `entity_candidate._research_output_contract_block()` so the leaf can be replayed on top of an ordinary Conversation prompt without two output contracts fighting. |
| Decision, "the recommendation remains pending until the existing automatic eligibility or owner verdict authority acts." | Narrowed to the standalone path. On the Play path the owner-verdict authority acts FIRST — that is what Play is — and the conversation supplies identity to that same authority through `entity-verdict`'s new `--alias` / `--relationship` / `--living|--not-living` / `--maps-to` flags. |

What this amendment adds that 0022 had no position on:

- **Identity is the child's subject.** Aliases, relationship, living, type,
  disambiguation against an existing page. One additive turn-output field,
  `entity_setup`, in the ADR-0018 two-layer shape.
- **A focus is never created here** (owner ruling 4). The conversation may
  offer one, at most once per session and only for an offer-worthy entity;
  a yes is `entity_setup.start_focus`, and the ONLY seam is
  `focus-recommend-from-entity`, which appends one pending recommendation row
  and calls nothing that creates a Focus.
- **`--maps-to` beats `graduate` in the same call**, without raising: the
  identity job is a single background call that always carries the graduation,
  and failing it would strand the identity. Without `--maps-to`, `graduate` on
  an already-mapped entity keeps raising exactly as it did before v190.
- **Identity facts are settled facts.** `relationship` and `living` survive a
  roster refresh through `entity_roster.normalize` and
  `apply_previous_decisions`, the same recipe `keywords` and `owner_verdict`
  already use. A merge's durability lives on the SURVIVOR's aliases.

Unchanged by this amendment: the registry/composition mechanism, the closed
entity-type roster and its exact-match discipline, the candidate anchor/revision
recipes, rule 8's "no lifecycle claims" doctrine, ordinary Conversation's
byte-for-byte freeze, ADR 0013's owner-verdict semantics, and the graduation
thresholds.

Pin-bump reconciliation surfaces: `entity_setup` joins the turn-output shape
row alongside `placement` and `focus_setup`; `entity-verdict`'s flag set joins
the CLI-surface row.

🤖 Generated with Claude Opus via Claude Code
