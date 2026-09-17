# ADR 0036: Incremental Timeline Evidence Links

Date: 2026-09-17
Status: ratified (owner, 2026-09-17)

## Context

ADR 0035 and v306 made archive classification stable by deriving candidate
context from an independent temporal fold. That safety boundary also excluded
every classifier fact, including an ordinary story's exact statement of a date
or age. A new landmark could only improve an older story after another full
event extraction, and a corrected landmark bound invalidated links whose
identity and meaning had not changed. Null relations did not distinguish no
candidate, ambiguity, incomplete search, and a non-temporal item.

The failure modes are asymmetric. Reusing contextual output as independent
evidence creates a feedback loop; ignoring exact source facts prevents the
archive from learning. Treating every catalog change as relevant wastes model
work; omitting a same-entity competitor permits a confident wrong join. A
named person's age also exposed a separate arithmetic hazard: the temporal
fold could use the owner's birth when that person's own birth was absent.

## Decision

Extraction and relationship interpretation are separate contracts. Full mode
extracts new or source-changed events. Timeline mode returns link-only deltas
keyed by the one canonical event key and may update only source grounding,
timeline relation, and resolution. The outer four-key snapshot and schema-v1
batch/receipt envelopes remain unchanged.

A directly stated date or age may join independent candidate authority only
when one exact, unique source quote proves the temporal words and the exact
event subject. The framework computes offsets, source revision, and normalized
temporal value. Contextual relations, summaries, inferred dates, target-source
facts, corrected-away readings, and retracted sources remain excluded. Named
people use only their own independently supported birth for age arithmetic;
the owner birth is never a fallback.

Candidate search and freshness are event-local. Exact entity names, aliases,
reference terms, and event roles select candidates; all same-entity competing
roles or stays are retained. Generic owner references do not expand a source
into every owner fact. A relevant set has its own completeness and unmatched
reference keys. A relation requires a unique source quote that distinguishes
the selected candidate from supplied competitors, not a globally unique
entity reference.

Each event records one of `linked`, `missing_evidence`, `ambiguous`,
`incomplete`, or `not_temporal`, plus the complete relevant candidate IDs.
Incomplete and non-temporal outcomes do not create date questions. A proven
raw relative anchor is replaced by its canonical target when both readings
are the same edge; a genuinely different before/after constraint is retained.
Calculated nodes carry the additive `timeline_resolution_status` field when
all status-bearing claims in the node agree. This keeps the event and its raw
evidence intact while letting readers show `incomplete` honestly and exclude
`not_temporal` from chronological debt without guessing from missing work items.

Freshness fingerprints include candidate identity, role, source/subject
grounding identity, aliases, conflicts, alternatives, unmatched references,
and applicable human decisions. They exclude supported bounds, evidence text,
and source revision within an otherwise identical grounding identity. Thus a
date-only correction propagates through an existing canonical link during the
pure fold without another model call, while an identity, meaning, alias,
competitor, or authority change still invalidates the affected event.

Refinement is opportunistic, not a background objective. A refresh already
caused by relevant evidence may adopt any newly recognized supported
connection, including a more useful one. Bound-only changes flow through the
existing link deterministically. Unchanged evidence reuses the accepted result:
compile does not call the model, and no periodic job re-reads settled links just
to seek tighter bounds. Validation, stale-snapshot refusal, and human/direct
source authority are hard boundaries; they are not a promise that every valid
model choice is at least as precise as the previous one.

The full and incremental prompts share one verbatim eligibility instruction
block (v309, issue #352). Incremental resolution copies the exact supplied
event-local candidate IDs, including ineligible alternatives; selecting a link
still requires resolved identity, exact refs, and unique source evidence.
Clarifying these existing requirements leaves validator and cache versions
unchanged, so accepted results are not re-run solely for clearer instructions.

## Consequences

- Filing or publishing classifier output still cannot feed its contextual
  relation back into independent candidate context; v306's no-feedback rule
  remains binding.
- Existing event extraction and every non-timeline classification field remain
  byte-preserved during a timeline refresh.
- Candidate sets beyond the former first-64 slice are searchable by reference;
  only an actually oversized relevant set is incomplete.
- Manual identity decisions, moves, rejections, corrections, and append-only
  receipts retain their existing authority and storage contracts.
- Recorded synthetic evaluation proves retrieval, validation, and propagation
  plumbing only. Model quality is reported only by an explicit configured
  `timeline_evidence_evals.py --live` run.
- Settled links receive no speculative refinement calls. Relevant evidence can
  revisit them; otherwise compile is a deterministic no-op for interpretation.
- Hosted adoption must pin this implementation while preserving its own outer
  API schemas; this ADR does not claim hosted deployment.
