# ADR 0032: Landmark sufficiency — a domain leaves the surface on value, not on completion

Date: 2026-09-03
Status: accepted (owner ruling R2, 2026-09-03; lands with Cut 5a)

Controlling decision: `lifehug-platform`
`docs/decisions/2026-09-03-timeline-unification/decision-record.md` — ruling
**R2**, §4.4 (landmark opportunities), §4.6 (one chooser) and §7 Cut 5; the
diagnosis is finding **F7** in that record's `sources/01-audit-codex.md`, and
the contract is `execution-plan.md` §5a. Amends ADR 0028 (the landmark
recorder) and ADR 0027 (the placement score) in one narrow place each: the
recorder's ladders keep every word they have, and this ADR decides who is
allowed to say a domain is *done*.

## Context

The landmark ladders (ADR 0028, `interactions/landmarks/questions.yaml`) are
nine specificity ladders, each with a `complete_at` rung. Every consumer since
has read completion as the stop condition:

1. `landmarks_interaction.status_for_domain` returns `open | partial |
   complete`, and `open_landmarks` drops every `complete` row.
2. The platform's `Landmarks.tsx` renders those rows, filters on
   `status !== 'complete'`, and shows **"Your landmarks are all filled in"**
   when the nine ladders are full.

The audit's F7 states the consequence exactly: *"'Sufficient' should mean the
remaining landmark questions no longer offer enough expected improvement to
justify a privileged surface — not that every field in nine ladders is
filled."* Two failures follow from the checklist, and both are live:

* **A finished ladder that still owes the timeline everything.** A residence
  entry with a city, an address and a stated start reaches `span` and reads
  `complete`. The participation episode it draws is `1990/..` — open at the
  end — and every event the containment rung placed inside it is holding a
  window instead of a date. The surface says "all filled in" while one
  question would place five stories.
* **A privileged surface for questions worth nothing.** A partial ladder is
  offered whatever its remaining rungs are worth, so a `household` rung that
  places nothing outranks nothing and still occupies the page.

The questions were also generic where they were generated rather than read off
the ladder: F7's *"A relationship question should be specific ('When did you
and Katie first meet?'), not 'When did this part begin?'"*.

What was already in place and did not need inventing: Cut 3a
(`system/timeline_gain.py`, v284) publishes `resolves` and `leverage = 1 +
len(resolves)` for every Timeline-owned item over the calculated dependency
graph, plus the `dependency_index` those numbers came from; v219 gave every
enumerating domain a per-event, subject-named question
(`landmarks_interaction.event_questions`); and the daily queue has had ONE
timeline dial since v196, `question_planner.DEFAULT_LANE_POLICY["timeline_
leverage_per_story"]` — the exchange rate that says how many timeline unknowns
one answer must place to be worth one ordinary story answer.

## Decision

1. **A landmark opportunity is a gap the graph can name.** `system/
   landmark_opportunities.py` derives them from the projection the fold has
   just computed: a participation episode with an open or missing bound
   (`span_open_end`, `span_open_start`, `span_missing`), a missing birth
   origin (`birth_origin`), a person the ladder enumerates with no dated
   anchor (`relationship_anchor`), and an episode the containment rung found
   ambiguous (`ambiguous_episode`). Each carries `id`, `domain`, `kind`,
   `subject`, `leverage`, `resolves`, `question`, `ladder_rung` and
   `sensitivity`.

2. **The leverage is Cut 3a's, not a new metric.** It is
   `timeline_gain.item_gain` over the same `dependency_index` the Needs
   Placing rows are ranked by, for the anchor the opportunity would supply.
   One base gain quantity, three hosts (§4.6). No precision weighting and no
   uncertainty estimate; those stay the later tier ADR 0027 ruled them.

3. **Sufficiency replaces completion.** A domain is `sufficient` when its best
   remaining opportunity's `leverage` is below the shared threshold, and a
   sufficient domain **publishes no opportunities** — the surface collapses
   because there is nothing to draw, not because a component hid a row it was
   given. `landmark_sufficiency` publishes `{sufficient, best_leverage,
   reason}` per domain so the collapse is checkable. The reasons are
   `open_opportunity`, `below_threshold`, `nothing_remaining`,
   `list_declared_finished` and `offer_only`.

4. **The threshold is the queue's dial, read and never copied.**
   `landmark_opportunities.default_threshold()` returns
   `question_planner.DEFAULT_LANE_POLICY["timeline_leverage_per_story"]` (6 at
   this pin). The Timeline surface and the daily queue cannot drift, because
   there is one definition of the number and one definition of the bar.

5. **Closed lists keep their finishable semantics, and only those.** A domain
   the person can declare finished — `chain_complete`, or the `none` terminal
   — is sufficient once they declare it, even with rungs unfilled: *"that is
   everyone"* finishes `family`. But **declared closure closes a list, not a
   graph**: it never silences an opportunity the dependency graph named that
   clears the threshold. *"That's all the houses"* is not an answer to *"when
   did you move out of the Mesa house?"*.

6. **Questions are generated from the gap.** The domain's own verb for a
   missing bound (`SPAN_END_TEXTS` / `SPAN_START_TEXTS`), the ladder's own
   `span` rung when both bounds are missing, `event_questions` for a person
   (with the roster's display name), and the fold's own composed sentence for
   an ambiguity. An opportunity always names its subject: a rung whose answer
   would BE the name has no anchor in the graph and no measurable leverage, so
   it is not an opportunity and *"When did this part begin?"* is
   unrepresentable here.

7. **Nothing is ever asked twice.** The id is `lo:<24 hex>` over the gap
   itself — domain, kind, subject, event — through the substrate's one id
   derivation, so a rebuild produces the same id and the leverage or the
   wording moving does not retire and re-mint a person's open question. An
   answered gap simply stops being a gap: a filed entry, a `none` terminal or
   a retraction removes the opportunity rather than renaming it.

8. **Losses stay offer-only.** A sensitive domain nobody has raised is
   sufficient with reason `offer_only` and publishes nothing; its leverage is
   still measured and still published, because sensitivity changes whether a
   question may be surfaced and never what it is worth. A raised subject's
   opportunity carries `sensitivity: "offer_only"` so the host offers it
   rather than asking it.

9. **Additive publication.** `landmark_opportunities` and
   `landmark_sufficiency` ride `CalculatedTimeline.to_dict()`, the projection
   payload, `structural_signature` and `rebuild_signature`, and are served by
   `temporal_publication.calculated_view`. A projection published before this
   cut reads as an empty tuple and an empty mapping. The legacy
   `timeline.landmark_rows_for` and `landmarks_interaction.landmark_rows` are
   untouched; Cut 7b retires them.

## Consequences

* The platform's Landmarks surface can stop reading legacy rows and stop
  saying "all filled in": absence is natural, and `landmark_sufficiency` says
  why each domain is quiet. That is Cut 5c.
* A newly high-value anchor appears with a specific question the moment the
  graph implies it, on a ladder that was already complete — program criterion
  7 (§8.2).
* Cut 5b can mint these opportunities as queue candidates without a second
  scorer or a second bar: both hosts read one number and one dial.
* The threshold is a real product knob. Lowering it privileges more surfaces;
  raising it collapses them sooner. It is not tuned here and it is not
  per-domain — residence's preference stays a tie-break, never an override of
  a larger measured gain (§4.6).
* The `tenure_ambiguous` split between `work` and `schools` is decided by
  which domain's filed entries the fold's own sentence names, falling back to
  `work`. The fold's item does not publish the episodes it was choosing
  between; if that becomes wrong in practice, the honest fix is for the item
  to publish them, not for this module to guess harder.
* A still-current stay is exempted from the open-end question by the fold's
  `life_clip_end: "present"`, which is the only signal the projection has for
  "they still live there". A vault whose current residence lacks that stamp
  will be asked when they moved out; the fix belongs upstream, in the stamp.
