# ADR 0040: The ring is a target

Date: 2026-09-29
Status: ratified (owner, 2026-09-29) — v378, issue #434

## Context

v372 drew the graph's ring only for a Focus page, as a fixed pixel gap on the
fill radius (`outer = r + 4 + (1 − sat) × 14`); the emitted `target` was never
read. The fill was a percentile rank within type, so a page with nothing told
could draw at full size. The audit of 2026-09-29 against the owner's vault
(86 nodes, 775 edges) found every relationship edge's `told` at 0 and credit
counting only `answers/*.md`, so conversations and email the classifier had
read about a person earned nothing.

The owner's rulings, 2026-09-29: the 1/n credit split is ratified;
conversation and email telling counts when the source is valid content about
the entity — the classifier tagged the entity as a subject, never a bare name
occurrence, and unclassified bulk imports earn nothing; **the ring means
TARGET**: every entity gets one, from a documented table that can be
revisited; ideal radii are an owner table by type and relation, not learned
from citations (graph-vis D4); peers compare within type (D5); no cross-type
metric by summing radii (D7); the graph is a companion view for now; every
number adjustable in one config.

## Decision

- `told(e) = credit(e)`, through the relevance gate
  `A_SOURCE_TELLS_ONLY_ITS_SUBJECTS`: an answer counts for the pages that
  list it; any other source only for the entities its current classification
  tags; each source gives `1/n` to each of its `n` holders.
- `target(e) = weight(type, kind) × tier multiplier × scale(type)`. The
  weights and multipliers are the table decided in
  `system/research/life-portrait-targets.md` §5, each with its rationale.
  `scale(type)` is calibrated per type so the best-told member (quantile 1.0)
  sits on its target; a type with too few credited members borrows the
  median scale; the owner's own person page is not calibrated on.
- `gap(e) = max(0, 1 − told/target)`, emitted on every node and relationship
  edge for the planner and the platform to read later.
- The ring is drawn at the target's radius on the fill's own scale
  (`radius_min + radius_span × sqrt(value / max)`); percentile ranking is
  dropped as the size signal.
- A relationship edge uses the same definition, with the relation of its
  non-owner end.
- Every number lives in `system/portrait_targets.json`; a vault overrides any
  subset in `state/portrait_targets.json` (validated, rejected whole when
  invalid); `portrait_weight` on a Focus or roster entry replaces one
  entity's weight; `doctor` prints the effective values, their origin, and
  the largest gaps per type.

Alternatives: learning weights from the vault's own citation counts (lost to
D4 — it rewards whatever was already told); a single cross-type completeness
score (lost to D7 and to chronology-vis §4.6's improper-meter argument);
keeping percentile as the size (it cannot show a target, and a lone or empty
page drew large).

## Consequences

- Binds: any reader of `gap` reads it from `graph_data()`; any change to a
  weight changes `system/portrait_targets.json` and the research note's table
  together.
- Forecloses: sizing by raw source count or by percentile; crediting a source
  because its text contains a name.
- The graph still changes nothing in the loop; wiring `gap` into the planner
  is a separate decision (graph-vis §5, the loop pulse).
- Revisit when: the owner changes the table; a study of narrative space per
  relation is obtained (research note queue); or one entity outgrows its
  type's scale so far that `calibration.quantile` 1.0 hides every peer's gap.

Cross-references: `system/research/graph-vis.md` (#435) D3–D7;
`system/research/life-portrait-targets.md`; ADR 0030 (eras, age frames).

## Amendment 2026-09-30 — one scale (v380)

The owner, on v378: "the biggest things would be my dad and my mom, to tell a
story about myself … why is Forgiveness two or three times the size of
Katie?" Per-type calibration let the best-told theme ("Family", tagged in
nearly every source) set every theme's target at 80 while people's were
about 21, keeping the within-type half of the owner table (D4) and dropping
the cross-type half. Amended: `scale(type)` is `type_scale[type] × anchor`
(`ONE_SCALE_FOR_THE_WHOLE_PORTRAIT`), where `anchor` is the
`calibration.anchor.quantile` of `credit / (weight × tier × type_scale)`
over the credited parents, spouses and partners (the owner's page still
excluded), and `type_scale` is the owner's provisional table — person 1.0,
life 1.0, place 0.6, period 0.6, project 0.5, lifes_work 0.6, object 0.3,
theme 0.3 (rationale: the research note's "Amendment 2026-09-30 — one
scale"). D7 is unchanged: nothing is summed across types. Told may now
exceed target: `over = max(0, told/target − 1)` is emitted, the fill is
capped at the ring with a thinner over-told ring outside it, and `doctor`
lists the most over-told per type beside the largest gaps. The v378
behaviour is `calibration.mode: per_type` and reproduces its numbers
exactly. Same day, `A_FOCUS_WEARS_GOLD`: an active Focus wears a static gold
halo outside its ring and a project a second-colour halo
(`drawing.focus_halo`, `drawing.project_halo`); nodes carry `focus` and
`project` flags, and the Focus name moved to `focus_label`.
