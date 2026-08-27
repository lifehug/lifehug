# ADR 0024: Chronology with basis — dates as intervals, asking anchor-first

Date: 2026-08-22
Status: proposed

## Context

The timeline is the one surface whose whole job is to show a person how the
system understands the sequence of their life — and it has never held a date.
That was doctrine, stated in three places: the compiler wrote "absolute years
are deliberately NOT inferred (they telescope)"
(`wiki_compile.compile_timeline`), the planner banned the phrase `"what year"`
(`arc_planner.BANNED_PHRASE`), and the classifier was told "NEVER convert to a
year" (`classify_story.py`). An event was
`{description, when_hint, anchor, source, eras}` — free text, no granularity,
no confidence, no bounds, no provenance per claim.

The doctrine had a real basis and it is still half right. Dating a memory is
reconstructive inference rather than readout (Friedman 1993; Brown, Rips &
Shevell 1985), and reported dates drift later than the truth (Loftus &
Marburger 1983; Huttenlocher, Hedges & Bradburn 1990). Ask someone for a year
and you get a rounded, telescoped guess.

The v194 research (`system/research/chronology.md`) says the other half.
Historians never pin without bounding first: *terminus post quem* and
*terminus ante quem* produce an interval, **and the interval is itself a
finding, not a failure**. Documentary editors record inferred dates and mark
them *conjectural* rather than declining to record them. The life-history
calendar dates most of a life by inference from residence and role (Freedman
et al. 1988; Belli 1998; Conway & Pleydell-Pearce 2000) — the exact arithmetic
the package refused to do. And oral historians (Portelli) treat a
contradiction as a second dated claim with its own provenance, both retained.

Four concrete costs followed from conflating the two halves:

1. `approximate_dates` had **no writer**, so the corroboration window was
   usually absent and every connector badge fell back to "context-only".
2. The spine's order was a monthly roster-model opinion (`chrono`), so a
   period the owner had dated still sorted by a guess.
3. Gaps were prose (`{kind, period, message, hint}`), three of seven kinds
   reached the loop at ≤3/week, and none carried a question a person could
   answer now.
4. Nothing knew which single answer would be worth the most, so neither the
   weekly queue nor the page could prefer it.

## Decision

Split the doctrine: **asking stays anchor-first; storage gains real dates.**

1. **A date is an interval with a basis.** `system/chronology.py` defines
   `DateRecord {best, earliest, latest, granularity, confidence, basis,
   anchors, provenance}` over three closed vocabularies — `GRANULARITIES`
   (day/month/season/year/range/era), `CONFIDENCES`
   (certain/approximate/inferred/conjectural, the documentary-editing
   convention), and `BASES`
   (stated/age/anchor/order/public_event/connector). Storage is EDTF /
   ISO 8601-2 level 1 (`1984~`, `198X`, `1998-06`, `2001-21` for spring,
   `1984/1990`, `1984/..`, `../1984`), and every canonical form round-trips.
   This module is the single authoritative definition of the object and of
   every rule that manipulates it (recurring-defect doctrine).
   *Alternative rejected*: a bare `year: int | None`, which cannot express a
   bound, a season, a decade, or how the system came to believe it — and
   which would have made every one of the four costs above unfixable.
2. **The system does the arithmetic; the model never invents a year.** A
   birthday plus "about five" is `1984~` with basis `age`
   (`chronology.from_age`); a landmark plus a before/after is a terminus
   (`from_anchor`); several claims combine through `intersect`. The
   classifier's rule changes from "never convert to a year" to **"do not
   invent; do record what was said"**: it emits only the explicit claim
   (`stated` / `age` / `anchor_ref` + `relation`), never a computed year.
   `arc_planner.BANNED_PHRASE` is **unchanged**, and the new
   `timeline_gates.no_year_opener` lint enforces the same rule in the
   conversation — one rule, pinned in a test against the planner's own
   constant so the two cannot drift.
3. **Contradictions keep both claims.** `chronology.reconcile(claims)` scores
   by basis, confidence, and consilience and returns
   `{best_supported, alternates}` — and never drops a claim. The renderer
   shows the best-supported interval and links the alternates.
   *Alternative rejected*: resolving to one date at write time, which is the
   destructive edit the mission forbids and which throws away the thing
   Portelli says is most worth having.

   **Amended v222 (wave B, item B4).** This ruling was written and then had
   no production caller for twenty-four releases, while
   `landmarks_interaction.merge_landmark_entry` resolved every date collision
   with `{**prior, **incoming}` — which is precisely the write-time
   resolution the paragraph above rejects, doing it silently. `reconcile` now
   holds that seat: all three landmark date fields (`date`, `span.start`,
   `span.end`) go through it, and the claims it does not pick are kept beside
   the winner (`DATE_ALTERNATES_KEY`, `SPAN_ALTERNATES_KEY`), read back by
   `landmarks_interaction.landmark_date`. Two additions the seat required.
   `merge_claims` runs in FRONT of it, folding repeat tellings of one claim —
   same interval, same basis — into a single record with anchors and
   provenance unioned, because an entry re-filed twenty times must not
   accumulate twenty alternates and a second telling is corroboration, not a
   rival. `conflict` comes back BEHIND it (`conflict_strength`): `0.0` unless
   a surviving rival cannot be true at the same time as the winner, `1.0` for
   a dead tie between two that contradict. And the ORDER gained a grain rung
   between score and text, because a refinement is not a rival — without it
   `2001` and `2001-06-14` tie on support, break on text, and the day the
   person just gave you loses to the year they gave you last month.
   Rendering alternates and conflict to the person is wave D/E; what this
   amendment settles is that the losing claim still exists to be rendered.
4. **Order is derived from dates where they exist.** `timeline.derive_chrono`
   anchors dated periods at their `date.earliest`, interpolates undated ones
   between their nearest dated neighbours in the old order, and dense-ranks.
   With zero dated periods it is a no-op and the spine is byte-identical to
   v194 — a required regression test. The roster ordinal stays as the floor,
   never as the ceiling.
5. **The band is the person's own chapter, then the places, then the events**
   (owner ruling 2, amended). `timeline_data()["bands"]` is the one render
   shape: a life-chapter band wherever a dated chapter covers the stretch, a
   period band everywhere else, places lined up inside by the existing
   provable source overlap, and events under their place.
   `align_chapters` prefers date containment and keeps the conservative
   name-match as its fallback.
6. **Every gap is a Play-able unknown, and leverage names the pivotal one.**
   `timeline.unknowns(data)` gives each gap `{kind, key, label, probe}` where
   the probe is the playbook's cheapest question; `era_gap` is the one new
   kind (a dated hole between dated eras — impossible to compute before this
   ADR). `dependency_index`/`leverage`/`keystones` score what a single anchor
   would resolve, capped at **two** starred keystones. *(The
   `leverage_boost` adjacency nudge this decision introduced is REPLACED by
   the v196 amendment below: a keystone is asked as itself.)*
7. **A deferral is a real state that never nags.** *(REVERSED by the v196
   amendment below — "I'll find out" is an ordinary answer and no state is
   kept.)*
8. **The elicitation is a child interaction.** `timeline`
   (`interactions/timeline/`, `system/timeline_interaction.py`) is the fifth
   child of Conversation, following the paradigm exactly: stages
   `open|place|close` derived from the transcript plus two caller facts,
   ONE additive output field `placed` (a date record or null — the deferral
   shape is removed by the v196 amendment) gated on
   `TurnShape.timeline_stage`, two validation layers,
   `timeline_gates.*` lints, goldens, and its own seat gate.
9. **Passive users are untouched.** With `TurnShape.timeline_stage` `None`
   the output-contract appendix is byte-identical to v194, pinned by a
   required test. The daily single question does not move by one byte.

## Consequences

- **Binds.** The three vocabularies and the EDTF forms are a durable data
  contract: they appear in `state/timeline_placements.json`, in classification
  JSON, in period/place page frontmatter, and in the `placed` output field. A
  host reads `chronology`'s names and `timeline`'s names, and re-implements
  none of them (`interactions/timeline/README.md`'s platform-twin table).
- **Binds.** "Never open with 'what year'" survives as BOTH the planner's
  banned phrase and a scored lint class, tested against each other. Widening
  storage is not permission to widen asking.
- **Binds.** `approximate_dates` is now DERIVED from `date` and no longer
  hand-written. Every existing reader keeps working; the string finally has a
  source.
- **Forecloses.** A single scalar year on an event; silent contradiction
  resolution; a model-emitted computed year; a third "when did this happen"
  field; and more than two starred keystones.
- **Deliberately deferred.** The timeline PAGE (era/chapter → place → event
  cards, date chips, Unknowns with Play, persisted expand state, the
  walkthrough) is P1 and lands on the host after the pin; drag-into-era and
  connectors-as-evidence are P2 (platform `#581`, `#580`).
- **Delete-when.** If a future medium can ask for dates without a
  conversation — a calendar import, a photo-EXIF connector — decision 2's
  "the model never invents a year" stays, but the elicitation child stops
  being the only writer and this ADR should be revisited rather than quietly
  outgrown.

## Amendment (2026-08-23, owner-ruled — v196, `timeline-whispers-and-keystones`)

Owner rulings on lifehug/lifehug-platform#586, after the hosted Today ★
appeared on an ordinary reflective question that never asks for a date.

1. **Decision 7 is REVERSED. There is no deferral state.** "I'll find out" is
   an ordinary answer: it files nothing, it is remembered nowhere, and the
   unknown simply stays outstanding with its star, its leverage and its Play.
   `state/timeline_deferred.json`, `DEFERRED_QUIET_DAYS`, `defer_unknown`,
   `is_deferred`, `load_deferred` and the `deferred` field on unknowns are
   deleted, and a remnant guard keeps them deleted. The courtesy survives
   where it always belonged — the ladder's `defer` rung and the
   `timeline_gates.accepts_defer` lint. The consequence "re-asking a deferred
   unknown inside its window" is likewise foreclosed no longer: there is no
   window to be inside.
2. **Decision 6's `leverage_boost` is REPLACED, not tuned.** Lifting a bank
   question because its focus *resembled* a keystone slug is adjacency, and
   adjacency is what starred a question that never asks for a date. A keystone
   is asked **as itself**, matched by its own identity `tl:<anchor-slug>`, in
   exactly two ways: a **whisper** on the week's arc card (the real probe plus
   the person's own anchors, raised only where it fits, at most one per
   conversation, any precision accepted, never pressed), and a **keystone
   question** minted as an ordinary bank row in the new `timeline` group.
   One dial governs both: `timeline_leverage_per_story` (6) is the exchange
   rate between timeline unknowns and one ordinary story answer — below it
   nothing is minted, above it the minted question's weight is
   `leverage / per_story` in the queue's own objective currency. The group cap
   (1) bounds the week.
3. **Decision 8's additive field loses its deferral shape.** `placed` is a
   date record or null. A RANGE WITH A BASIS is first-class and is the
   expected good outcome, not a degraded one: "about preschool, three to five"
   files as an interval. Any accepted `placed` files through `timeline-place`
   on the answer path (`conversation_delivery.run_post_answer_turn`), and the
   next compile re-derives the timeline — nothing else has to move.
4. **A sixth lint class**, `timeline_gates.one_per_conversation`, joins the
   five: the timeline is raised once per conversation, where it fits. The
   caller counts the asks (`timeline_asks_so_far`, the same posture as
   `no_new_bound_streak`); the rule is also structural — a session that has
   raised it carries no item on the next turn.
5. **The loop learns about arcs.** The weekly `judgment-update` step gains an
   arc-yield pass over data the vault already holds (session documents: filed
   answers, placements, new entities, per arc-card intent kind) and may make
   one bounded, evidence-cited amendment to
   `state/question_judgment/arc_learned.md`, composed into the arc-plan prompt
   as `## Arc judgment signals` — the same ADR 0009 mechanism, and the same
   composition split `load_judgment_rubric` uses. It is a vault file, never an
   edit to the framework's `plan/arc-templates.md`, which `update.py` would
   overwrite and `test_exact_file_git.py` pins.

## Amendment (2026-08-26, v234 — one gap, one conversation; lifehug-platform#664)

The audited final timeline build plan gives every actionable Mirror row a
**Play now** that "opens a conversation grounded in that exact contradiction"
(§2.5) and rules that "answering or resolving a temporal work item on any
surface closes or updates the same work item everywhere" (§2.3). Building
that raised one design question and this amendment answers it.

**The question.** A `temporal_projection.TemporalWorkItem` — a contradiction,
an unplaced identity, a missing anchor, a precision gap — is a thing the
system is confused about and only the person can settle. Play on one opens a
conversation. Is that conversation a NEW child interaction of Conversation,
the eighth, or a stage of one that exists?

**The decision: a stage of `timeline`, named `work_item`.** Two reasons, and
the second is the load-bearing one.

1. **It is dating work.** Every kind of temporal work item is a question about
   when something happened, or about which thing a "when" belongs to.
   `timeline`'s whole goal — *place a memory in time without ever demanding a
   year* — is that goal. A second interaction would have restated it, and the
   restatement would have drifted.

2. **An eighth child is a build-breaker until it is fully wired, and it buys
   nothing here.** The child-interaction paradigm (`interactions/README.md`)
   is deliberately unforgiving: a new child needs a registry row, a stage
   selector, prompt kwargs, output validation, lints, a `Turn` field and a
   filer, in the package AND in every host — and a pin bump that adds one
   fails the build until they all exist. That cost is right when a child
   brings a new output vocabulary. This one brings none. The output is the
   lane's existing optional `placed` field; any further temporal facts in the
   same message are heard by the v229 general listener exactly as they are in
   every other conversation; the filing is
   `mirror_work.resolve_mirror_item`, which already promotes the words, files
   replacement claims through a receipt, and retires by correction. Paying a
   new child's whole price to say the same things in different words is the
   parallel implementation ADR 0021 exists to prevent.

**What the stage is.**

- `timeline_interaction.WORK_ITEM_STAGE` is the fourth `{timeline_stage}`
  value, and it is deliberately the SAME STRING as
  `mirror_work.PLAY_TARGET_KIND`. That kind was `mirror_item` in v227–v232 and
  is `work_item` from v234; `mirror_item` is accepted on the read side for one
  version and emitted nowhere. A surface-named kind bakes the surface into the
  identity, and §2.3's whole promise is that the identity has no surface —
  one gap opens one conversation whether the person saw it on Mirror, on
  Timeline, or as the daily question.
- Its context is the Play target's own bounded evidence
  (`timeline_interaction.render_work_item`): the readings that stand and the
  sources under them, the candidate set for an identity, the gap statement for
  a missing anchor or a precision gap, and the person's own quoted words. It
  is composed exactly as `_story_context_block` is — appended when there is a
  target, absent otherwise — so an ordinary turn's prompt does not move by a
  byte.
- Its behavior is §2.5 and §2.2: both readings go up together and neither is
  proposed for agreement (`timeline_gates.never_proposes_a_date`,
  unconditional); approximations are accepted; "I don't know", a skip, or a
  cooler register ends the attempt and nothing is written; the item stays
  available. One carve-out is deliberate:
  `timeline_gates.one_per_conversation` does NOT apply here. That class stops
  the timeline being raised twice in a conversation the person opened to talk
  about something else; a work-item episode IS the conversation they opened,
  and §2.2 allows "several progressively precise questions while the person
  remains willing" there. Willingness is measured by `MAX_PROBES` and the
  no-new-bound streak instead.
- Its filing decision is pure and lives in
  `timeline_interaction.work_item_resolution`. It returns `None` — write
  nothing — unless the person named one of the readings already on the table.
  A third answer retires nothing either: that is new evidence, it files as a
  claim through the ordinary extraction, and the fold decides what it does to
  the conflict. This module never resolves a contradiction it was only asked
  to host.

**Consequence for hosts.** A host binds ONE Play verb over the `work_item`
kind and one stage. The platform twin — the interaction-registry row that
consumes this stage, and converging both web switches on `work_item` — rides
the pin-bump wiring PR.
