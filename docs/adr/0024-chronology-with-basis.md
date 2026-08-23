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
   would resolve, capped at **two** starred keystones, and `leverage_boost`
   (1.2) lifts keystone-adjacent questions in the weekly queue through a
   guarded read that can never break the planner.
7. **A deferral is a real state that never nags.** `state/timeline_deferred.json`
   records "I'll find out"; the unknown goes quiet for `DEFERRED_QUIET_DAYS`
   (45), keeps its star and its leverage, and is never counted as
   outstanding. It is neither a decline nor a debt.
8. **The elicitation is a child interaction.** `timeline`
   (`interactions/timeline/`, `system/timeline_interaction.py`) is the fifth
   child of Conversation, following the paradigm exactly: stages
   `open|place|close` derived from the transcript plus two caller facts,
   ONE additive output field `placed` (a date record, `{"deferred": true}`,
   or null) gated on `TurnShape.timeline_stage`, two validation layers, five
   `timeline_gates.*` lints, ten goldens, and its own seat gate.
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
  field; more than two starred keystones; and re-asking a deferred unknown
  inside its window.
- **Deliberately deferred.** The timeline PAGE (era/chapter → place → event
  cards, date chips, Unknowns with Play, persisted expand state, the
  walkthrough) is P1 and lands on the host after the pin; drag-into-era and
  connectors-as-evidence are P2 (platform `#581`, `#580`).
- **Delete-when.** If a future medium can ask for dates without a
  conversation — a calendar import, a photo-EXIF connector — decision 2's
  "the model never invents a year" stays, but the elicitation child stops
  being the only writer and this ADR should be revisited rather than quietly
  outgrown.
