# Contract: timeline-chronology

## Why

The timeline is the one page whose whole job is to show the person **how the
system understands the sequence of their life** — and it is the one page that
has never held a date. The package's doctrine says so out loud: the compiler
writes "absolute years are deliberately NOT inferred (they telescope)"
(`system/wiki_compile.py:1409`), the planner bans the phrase `"what year"`
(`arc_planner.BANNED_PHRASE`, `system/arc_planner.py:104`), and the classifier
is instructed "NEVER convert to a year" (`system/classify_story.py:389`).

That doctrine is **right about asking and wrong about storage**. The research
landed as v194 (`system/research/chronology.md`, `system/research/QUEUE.md`,
`research.md` §4a) says both halves plainly:

- Dating a memory is *reconstructive inference*, not readout (Friedman 1993;
  Brown, Rips & Shevell 1985) — so a year prompt invites a rounded, telescoped
  guess, and "never open with 'what year'" survives as a lint.
- Historians never pin without bounding first: *terminus post quem* and
  *terminus ante quem* yield an interval, **and the interval is itself a
  finding, not a failure** (`chronology.md` §1). Documentary editors mark an
  inferred date *conjectural* rather than refusing to record it.
- The life-history calendar dates most of a life by *inference from residence
  and role* (Freedman et al. 1988; Belli 1998; Conway & Pleydell-Pearce 2000),
  which is exactly the arithmetic the package refuses to do today.
- Disagreement is data (Portelli): a contradiction is a second dated claim
  with its own provenance, both retained, best-supported rendered, alternates
  linked, never an AI-side silent pick.

So the package today can hear "I was about five when we moved to Mesa", know
the person's birthday, and still store nothing but the free-text
`when_hint: "about five"`. Five concrete holes follow from that:

1. **No date object exists.** An event is
   `{description, when_hint, anchor, source, eras}` (`timeline.load_events`,
   `system/timeline.py:308`). No granularity, no confidence, no basis, no
   bounds, no provenance-per-claim.
2. **`approximate_dates` has no writer.** The field is read in three places
   (`timeline.load_periods:158/183`, `timeline_corroboration._stated_range`)
   and written by nothing — the corroboration window is therefore usually
   absent, and every badge falls back to "context-only".
3. **Order is an LLM opinion.** `chrono` is assigned once a month by the
   roster model (`entity_roster.py:545–552, 683`) and is the sole spine order
   (`load_periods:186`), so a period the person has *dated* still sorts by a
   guess.
4. **Gaps are prose, not objects.** `compute_gaps` (`system/timeline.py:581`)
   emits seven kinds of `{kind, period, message, hint}`; three reach the loop
   at ≤3/week (`arc_planner.CONSUMED_GAP_KINDS`), the rest are display-only
   and nothing carries a question the person could be asked *now*.
5. **Nothing knows which answer would be worth the most.** There is no notion
   of one anchor resolving many unknowns, so the weekly queue cannot prefer it
   and the page cannot star it.

This PR is P0 of the timeline overhaul (platform design brief
`lifehug/lifehug-platform#581`): the package half. It adds the date object and
its arithmetic, gives events titles, gives periods/chapters/places real spans,
derives order from dates, turns gaps into Play-able unknowns with leverage and
a deferred memory, and adds the fifth child interaction — `timeline` — whose
one goal is **placing a memory in time**.

## Rulings (owner, 2026-08-22 — verbatim where it matters, binding)

1. **Dates are intervals with a basis; the system does the arithmetic.**
   Birthday + "about 5" → ~1984, basis `age`. Asking stays anchor-first —
   *"never open with 'what year'" remains a lint* — but **STORAGE gains real
   dates**. ("asking for dates is okay… if I'm not good with dates, it's hard
   to know for sure… 'When were you born?' → birthday; 'When did you live
   here?' → 'about 5' — approximate.")
2. **Events get titles from the classifier** — a noun phrase of at most seven
   words, *the thing, not the telling* ("Grandpa's two-page letter").
   **Amendment (owner, same session): the timeline hierarchy is Chapter →
   Places → Events.** The person's own life chapter (the McAdams exercise) is
   the band whenever one covers the stretch; the places lived sit inside it;
   events sit under each place; the system's era/period is the band ONLY where
   no chapter covers that stretch.
3. **Contradictions: both claims kept with provenance**; the best-supported
   interval is rendered; alternates are linked; never silently resolved.
4. **Unknowns are Play-able**, and every placement answer flows through the
   existing `timeline-place` write path (a dated correction in the archive
   plus a display pin).
5. **Keystones**: leverage = how many unknowns one anchor would resolve; the
   top 1–2 are starred; leverage is a planner weight; a **deferred** state
   ("I'll find out") sits beside declined and **never nags**.
6. **The `timeline` child interaction follows the sourced playbook**: content
   → residence/role → parallel domain → sequence → personal landmark →
   schema/season → offered bounds → convergence → defer; a precision ladder
   that stops early; one question per reply.
7. **Passive users are untouched**: the daily single question is
   byte-identical.

## Binding facts

As of `origin/main` `bc963ea`, `system/version.json` version **194**, released
2026-08-22.

- **The child-interaction paradigm** is `interactions/README.md`
  § "The child-interaction paradigm": one goal, composition never a fork, a
  stage-keyed leaf the host REPLAYs, **exactly one** additive structured-output
  field gated on a `TurnShape` flag, its own lints/goldens/harness, its own
  version bump and ADR. `timeline` is the fifth child; `arc_walk` (v193) is
  the newest and closest precedent and is copied line for line.
- **The `TurnShape` gates**, in order: `placement_stage` · `focus_stage` ·
  `entity_stage` · `arc_stage` (`system/conversation_delivery.py:152–192`).
  Every one defaults to `None`, and each ships with a required test that the
  output-contract appendix is byte-identical when the gate is `None`. That
  test is ruling 7's mechanical form.
- **Two validation layers.** Structural in `conversation_delivery` (owns no
  vocabulary, returns `None`, never raises); closed in the child's own module
  (owns the roster). Precedents: `_parse_answered_question_id` /
  `arc_walk.validate_answered_question_id`.
- **The registry is closed** (`interactions/registry.json`), and
  `interaction_registry.audit_interaction_package` requires, for any package
  declaring `extends`, that `composition.append ∪ composition.leaf` equals
  `COMPOSABLE_FILES` **exactly** — all seven prompt/context/router assets. A
  child therefore always ships `router/router.md` and `router/deflection.md`.
- **Flat scalar YAML only** (`lifehug_core._parse_simple_yaml`): every
  `interaction.yaml` and `evals/lints.yaml` key is a flat dotted key.
- **The write path already exists and is already durable.** `timeline-place`
  (`lifehug.py:696`) files a `--kind date` correction source through
  `source_integrity.py correct` and then saves a content-keyed display pin
  (`timeline.save_placement`); the pin auto-retires when the loop catches up
  (`retire_redundant_placements`, weekly). `jobs.py:600` (`_build_timeline_place`)
  and `serve_wiki.act_timeline_place` are its two callers. Ruling 4 means this
  PR **extends** that path and adds no second one.
- **Children's additive output fields are host-filed.** No package runtime
  consumes `placement`, `focus_setup`, `entity_setup`, or
  `answered_question_id`; they are parsed, validated, and evaluated here, and
  the host writes. `placed` follows that precedent (see Deviations).
- **`framework_files`** in `system/version.json` must list every new file
  under `interactions/` and `docs/`; `scripts/ci/check_framework_files.py` is
  a required CI check, and `scripts/ci/check_version_bump.py` requires the
  version bump in the same PR.

## Scope

**In:**

A. `system/chronology.py` — the date record, EDTF/ISO 8601-2 serialization,
   display, and the arithmetic (age, anchor, intersection, elapsed-time
   widening, reconciliation). Pure: no I/O, no model, no vault.
B. Model + writers — `title` and `date` on events; `date` on periods,
   chapters, and places; `chrono` derived from dates; the classifier's two new
   emissions; `timeline-place --date/--basis/--anchor`; the compiler and the
   corroboration window; **`bands`** as the one render shape (ruling 2's
   amendment).
C. Unknowns + leverage — every gap becomes `{kind, key, label, probe}`, the
   new `era_gap` kind, `leverage()`, `keystones()`, the
   `state/timeline_deferred.json` memory, `arc-plan-target --timeline`, and
   the `leverage_boost` planner knob.
D. The `timeline` child interaction — `interactions/timeline/`,
   `system/timeline_interaction.py`, the one additive `placed` field gated on
   `TurnShape.timeline_stage`, five `timeline_gates.*` lint classes, ten
   goldens, and `system/timeline_evals.py` (`lifehug.py timeline-evals`).
E. Docs — ADR 0024, the amended doctrine comments, two handbook pages, the
   glossary rows, the fifth row in `interactions/README.md`'s table,
   `version.json` 194 → 195, and the platform-twin table.

**Out (P1/P2, platform or later):** the timeline PAGE itself (era/chapter →
place → event cards, date chips, Unknowns with Play, persisted expand state,
the walkthrough) — that is `#581`'s P1 and lands on the host after the pin;
`?play=timeline:<kind>` deep links; drag-into-era; connectors-as-evidence
(#580); a zoomable canvas; synthesizing exact dates for tidiness.

## Design

### A. `system/chronology.py` — the date record

One frozen dataclass, one vocabulary, no I/O.

```python
@dataclass(frozen=True)
class DateRecord:
    best: str | None          # EDTF: the best single expression of the date
    earliest: str | None      # ISO bound, "YYYY[-MM[-DD]]" — terminus post quem
    latest: str | None        # ISO bound — terminus ante quem
    granularity: str          # day | month | season | year | range | era
    confidence: str           # certain | approximate | inferred | conjectural
    basis: str                # stated | age | anchor | order | public_event | connector
    anchors: tuple[str, ...]  # the landmark keys the arithmetic leaned on
    provenance: tuple[dict, ...]  # {source, claim, captured_at, session, answer_id}
```

Closed vocabularies: `GRANULARITIES`, `CONFIDENCES`, `BASES`. A record whose
granularity/confidence/basis is off-vocabulary is rejected at construction
(`ChronologyError`) — this module is the single authoritative definition
(recurring-defect doctrine, `docs/BUILDING.md` §7 / `interactions/README.md`).

**Serialization — EDTF / ISO 8601-2 level 1.**

| Form | Meaning | Granularity | Confidence |
|---|---|---|---|
| `1984` | the year 1984 | `year` | `certain` |
| `1984~` | approximately 1984 | `year` | `approximate` |
| `1984?` | 1984, uncertain | `year` | `conjectural` |
| `1984%` | approximate **and** uncertain | `year` | `conjectural` |
| `198X` | some year in the 1980s | `era` | `approximate` |
| `1998-06` | June 1998 | `month` | `certain` |
| `1998-06-12` | 12 June 1998 | `day` | `certain` |
| `2001-21` | **spring** 2001 (EDTF sub-year 21–24) | `season` | `certain` |
| `1984/1990` | the interval 1984–1990 | `range` | — |
| `1984/..` | 1984 or later (terminus post quem) | `range` | — |
| `../1984` | 1984 or earlier (terminus ante quem) | `range` | — |

`parse_edtf(text) -> DateRecord | None` and `to_edtf(record) -> str | None` are
inverses over every row above. `parse_edtf` additionally *accepts* the human
forms a person or an older vault will produce — `2001–2021`, `2001-2021`,
`spring 1998`, `1970s`, `about 1984` — and normalizes them onto the canonical
EDTF above. Unparseable text is `None`, never an exception, on every read path.

`display_date(record) -> str` renders the person's own words back:
`"around 1984 — you said you were about 5"`, `"spring 1998"`,
`"sometime in the 1980s"`, `"1984–1990"`, `"after the move to Mesa"`. The
basis clause is appended only when the record carries a provenance `claim`.

**The arithmetic** (each pure, each unit-tested rule by rule):

- `from_age(birth_date, age_text)` — "about 5" against a birthday →
  `1984~` with `earliest`/`latest` widened by the hedge (`about`/`around`/
  `roughly`/`or so` → ±1 year; "5 or 6" → the union; a bare "5" → the exact
  birthday-year window), `basis="age"`, `anchors=("birth",)`.
- `from_anchor(anchor_date_record, relation, grain)` — `before` → `../<anchor
  earliest>`; `after` → `<anchor latest>/..`; `during` → the anchor's own
  bounds. `basis="anchor"`, confidence at best `inferred`.
- `intersect(*records)` — the terminus post/ante quem instrument: the tightest
  bounds all inputs allow. Disjoint inputs return `None` (that is a
  contradiction, and `reconcile` owns contradictions — `intersect` never picks
  a winner). Anchors union, provenance concatenates, basis is the common one
  or `anchor`, confidence is the weakest input, floored at `inferred` whenever
  more than one record combined.
- `widen_for_elapsed(record, *, as_of)` — Huttenlocher, Hedges & Bradburn
  (1990): grain coarsens with distance and rounding pushes reports later.
  Deterministic: widen the bounds by `ELAPSED_WIDENING_YEARS_PER_DECADE`
  (0.5) per decade elapsed, rounded up to whole years, and coarsen the
  granularity by one rung once the widened span crosses that rung. `certain`
  is never widened (a stated calendar date does not decay); everything else
  drops at most one confidence rung, to `inferred`.
- `reconcile(claims) -> {"best_supported": DateRecord | None, "alternates":
  [...]}` — ruling 3. Scores each claim by basis (`stated` > `age` >
  `anchor` > `public_event` > `connector` > `order`), confidence, and
  *consilience* (distinct provenance sources corroborating it — the historians'
  criterion, `chronology.md` §4). **Never drops a claim**: every input appears
  either as `best_supported` or in `alternates`, in score order, with ties
  broken deterministically by EDTF then insertion order.

### B. Model + writers

**Events.** `timeline.load_events` gains two keys, both additive:

- `title` — the classifier's noun phrase, `""` when absent. `event_title(event)`
  is the single fallback definition (first clause of the description, ≤7 words)
  so no caller invents a second one.
- `date_claim` — the classifier's *raw claim* (below), `None` when absent.
- `date` — a `DateRecord | None`. `load_events` resolves stated claims only
  (it has no anchors); `timeline_data()` re-resolves every event against the
  assembled anchor index (`resolve_event_dates`), which is where `age` and
  `anchor` claims become records.

**Periods** gain `date: DateRecord | None`, read from (in order) the roster
entry's `date` (EDTF string), the page frontmatter's `date:`, or — the
back-compatible path — `parse_edtf(approximate_dates)`. `approximate_dates`
survives as a **derived display alias**: `display_date(period["date"])` when a
date exists, else the legacy string. Nothing that reads `approximate_dates`
breaks; it simply now has a writer.

**Chapters** gain `date: DateRecord | None` (ruling 2 amendment): parsed from
the chapters exercise's own transition statements ("It ends when…", "from X to
Y") via `chapter_date(chapter)`, else supplied by the skeleton episode through
a placement.

**Places** gain `date: DateRecord | None` — a residence span. Sources, in
order: an explicit `date:` in the place page's frontmatter (what the skeleton
episode writes), else the union of the dated events lined up with that place.

**`chrono` becomes derived.** `derive_chrono(periods)`:

1. Order periods by the LLM `chrono` (None last, slug tiebreak) — the fallback
   order, unchanged from today when nothing is dated.
2. Anchor every period that has a `date.earliest` at its year.
3. Estimate a year for each undated period by linear interpolation between its
   nearest dated neighbours in that fallback order (±1 per step outside the
   ends).
4. Sort by `(estimated_year, fallback_index, slug)` and dense-rank → `chrono`.
5. Record `chrono_source ∈ {"date", "roster", "page", None}` per period.

With zero dated periods this is byte-identical to today's ordering — the
required regression test.

**Bands — the one render shape** (ruling 2 amendment). `timeline_data()` gains:

```python
"bands": [
  {"kind": "chapter" | "period",
   "ref": "<chapter number or period slug>",
   "label": "...",
   "date": DateRecord | None,
   "places": [{"slug", "label", "date", "events": [...]}],
   "unplaced_events": [...]}
]
```

Band selection: a **chapter** band covers a stretch when its `date` span
contains that stretch; a **period** band fills every stretch no chapter covers.
Inside a band, events group by the PLACE they line up with
(`entity_lineup` type `place`, the existing source-overlap evidence), and
events matching no place fall to the band's own `unplaced_events`.
`places_by_chapter` and `places_by_period` are exposed alongside for callers
that want the grouping without the band envelope.

**`align_chapters` becomes date-containment when spans exist**: a chapter with
a `date` aligns to the periods its span contains/overlaps; the existing
conservative name-match stays as the fallback for undated chapters. Neither
path ever guesses — an unaligned chapter still stacks in its own order.

**Classifier** (`system/classify_story.py`). The `events[]` schema row gains
two keys:

```
{ "title": "string — noun phrase, ≤7 words, the thing not the telling",
  "description": "string — one datable moment",
  "when_hint": "string or null — as stated",
  "anchor": "string or null — nearest landmark",
  "date": { "stated": "string or null — a date/year the author actually said",
            "age": "string or null — their age at the time, as stated",
            "anchor_ref": "string or null — the landmark this is dated against",
            "relation": "before|after|during|null" } | null }
```

The `:389` guideline is **amended, not deleted** — from "NEVER convert to a
year" to *"do not invent; do record what was said"*: the classifier still
never converts, infers, or guesses a year; it records only what the author
explicitly stated, and the system does the arithmetic. `possible_date_claim`
in `chronology` is the single parser for that object; a malformed claim is
`None`, never an error.

**The write path.** `timeline-place` gains `--date <edtf>`, `--basis <basis>`,
and repeatable `--anchor <key>`. The filed date-kind correction's text carries
the rendered `display_date`, so the durable archive says *"…happened around
1984 (you said you were about five)"* rather than only naming the period. The
placement record gains `date` (the serialized record). `jobs._build_timeline_place`
accepts the three optional fields with the same validation discipline it
already applies to `period`. `serve_wiki.act_timeline_place` passes them
through when present.

**The compiler and the viewer.** `compile_timeline` renders
`[date chip] **Title**` per event with the description beneath, and writes the
period's date into page frontmatter (`date:`). The `:1409` doctrine comment is
rewritten to the new rule. The OSS viewer (`serve_wiki.view_timeline`) shows
the same chip and title.

**Corroboration.** `timeline_corroboration` takes its window from
`period["date"]` when present (`earliest`/`latest` years), falling back to
`_stated_range(approximate_dates)` exactly as today — one behavior change, a
strictly better window, no new failure mode.

### C. Unknowns, leverage, keystones, deferred

**Unknowns.** `compute_gaps` keeps its seven kinds and gains one:

- `era_gap` — a dated hole *between* two adjacent dated bands ("2000–2006 ·
  nothing placed here yet"). Emitted only when both neighbours carry dates,
  the hole is at least `MIN_ERA_GAP_YEARS` (1) wide, and nothing is placed
  inside it.

`unknowns(data) -> list[dict]` turns every gap into a Play-able record
`{kind, key, label, probe}` where `key` is stable and content-derived
(`"<kind>:<period-or-item>"`) and `probe` is the playbook's **cheapest**
question for that kind (`timeline_interaction.choose_probe`). The gap's
`message`/`hint` survive on the record so nothing that reads gaps today
changes.

**Leverage.** `dependency_index(data) -> {anchor_key: set[unknown_key]}` over
the anchor candidates ruling 5 names — a period's start/end, a landmark
(dated) event, an entity's arrival:

- a period anchor resolves that period's own unknowns, every `era_gap`
  touching it, and every undated event or entity lined up in it;
- a landmark-event anchor resolves undated events sharing its period or its
  source;
- an entity-arrival anchor resolves that entity's own unknowns and the undated
  events sharing its sources.

`leverage(anchor_key, index) -> int` is `len(index[anchor_key])`.
`keystones(data, n=KEYSTONE_CAP)` returns the top `n` by
`(-leverage, playbook_cost, key)`; `KEYSTONE_CAP = 2` (owner's cap).

**Deferred.** `state/timeline_deferred.json`,
`{"version": 1, "deferred": [{"key": "...", "deferred_at": "..."}]}`,
registered in `system/vault_contract.json`. `defer_unknown(key)`,
`load_deferred()`, `is_deferred(key, *, now=None)` with
`DEFERRED_QUIET_DAYS = 45`. A deferred unknown is **excluded from probe
selection inside the window and never counted as outstanding** — ruling 5's
"never nags". It keeps its star and its leverage.

**`arc-plan-target --timeline [--era <slug>]`** prints a timeline plan:
unknowns ordered by leverage descending, then playbook cost ascending, then
key; keystones first and starred; deferred rows listed but not offered.
Read-only, zero AI, no writer lock — registered in
`lifehug.READ_ONLY_COMMANDS` exactly as `arc-plan-target` already is.

**The planner knob.** `DEFAULT_LANE_POLICY["leverage_boost"] = 1.2` — a modest
multiplier applied in `build_queue`'s `weighted_pick` to a pending question
whose focus or category matches a keystone's slug. `build_queue` gains
`keystone_slugs: Iterable[str] | None = None`; the CLI/`plan()` entry points
supply them through a guarded read (`timeline.keystone_slugs()`, any failure →
empty), so the planner can never break on a timeline problem and no test's
vault is read implicitly.

### D. The `timeline` child interaction

`interactions/timeline/`, registered fifth, `extends: conversation` at
`extends.version: 1.0.0`, `composition.append` = identity/behavior/examples/
router×2, `composition.leaf` = turn-instructions + context manifest.

**Stages** — `open | place | close`, derived by
`timeline_interaction.timeline_stage_for_session(session, *, user_leaving=False,
placement_settled=False, no_new_bound_streak=0)`:

- `user_leaving`, `placement_settled`, or `no_new_bound_streak >=
  STOP_AFTER_UNPRODUCTIVE_PROBES (2)` → `close` (playbook stop rules);
- no assistant turn yet → `open`;
- `MAX_PROBES (4)` user turns reached → `close`;
- otherwise → `place`.

The two caller facts mirror `arc_walk`'s `user_leaving` precedent exactly: the
stage is derived from the transcript, plus signals only the caller can know.

**The leaf** substitutes `{timeline_stage}`, `{unknown_label}`, `{probe}`,
`{anchors}`, `{precision_so_far}`.

- `anchors_for_person(*, birth_date=None, periods=(), places=(), events=())`
  → the person's own landmarks, ordered: birthday, residences with spans,
  transitions, dated landmark events. This is the life-history calendar,
  rendered as text (`render_anchors`).
- `choose_probe(unknown, *, anchors=(), precision_so_far=None)` walks the
  playbook ladder — `content → residence → role → parallel_domain → sequence →
  landmark → season → bounds → convergence → defer` — returning the cheapest
  step still useful for that unknown, adapted to the anchors actually
  available. **The ladder stops early**: once `precision_so_far` is at or
  below the unknown's target granularity, the probe is `convergence`
  ("spring 1998, or is 'sometime 97–99' more honest?"), and after that,
  `defer`.

**The one additive field.** `"placed": DateRecord-shaped | {"deferred": true}
| null`, gated on `TurnShape.timeline_stage`.

- Structural layer: `conversation_delivery._parse_placed` — accepts an object
  that is either exactly `{"deferred": true}` or a date-record shape with a
  bounded key set and bounded string lengths; owns **no vocabulary**; returns
  `None` on anything else; never raises.
- Closed layer: `timeline_interaction.validate_placed(value, *, anchors)` —
  the vocabularies (`GRANULARITIES`/`CONFIDENCES`/`BASES`), EDTF parseability,
  and **exact** anchor membership: an anchor key the caller did not supply
  drops the record to `None`, exactly as `arc_walk.validate_answered_question_id`
  refuses an off-plan qid.

**Lints — five `timeline_gates.*` classes** (`lint_timeline_reply(text, *,
stage, probe_step=None)`):

| Class | Rule |
|---|---|
| `timeline_gates.no_year_opener` | the first probe of an episode never asks for a calendar year (ruling 1; `arc_planner.BANNED_PHRASE` stays) |
| `timeline_gates.one_question_per_reply` | at most one `?` (ruling 6) |
| `timeline_gates.offers_bounds` | at the `bounds` rung the reply offers an interval or a choice, never demands a point |
| `timeline_gates.accepts_defer` | "I'll find out" is received and closed, never re-asked or argued with (ruling 5) |
| `timeline_gates.never_invents_a_date` | the reply never asserts a year the person did not say (a year in the reply must appear in `{anchors}` or in the user's own words) |

"Never pressure" is inherited: the parent Conversation contract and
`arc_walk`'s `no_pressure` phrasing already own it, and duplicating it here
would be a second definition of one rule.

**Goldens — ten** (`interactions/timeline/evals/goldens/timeline_fixtures.json`
+ `timeline_sample_predictions.json`):

1. `timeline-open-anchors-not-years` — the opener probes content/residence, never a year.
2. `timeline-place-residence-anchor` — "where were you living then?" produces a bound.
3. `timeline-place-age-arithmetic` — birthday + "about five" → `1984~`, basis `age`.
4. `timeline-place-offers-bounds` — spring 1998 vs "sometime 97–99".
5. `timeline-place-sequence-cue` — relative order recovered when dates are not.
6. `timeline-place-parallel-domain` — job ↔ home cue when a domain stalls.
7. `timeline-close-convergence` — the ladder stops; nothing more is asked.
8. `timeline-defer-is-accepted` — "I'll call my mom" → `{"deferred": true}`, closed warmly.
9. `timeline-contradiction-keeps-both` — a second claim is recorded, neither is overwritten (ruling 3).
10. `timeline-skeleton-episode` — **the episode that matters**: birthday →
    places lived by age → periods dated by inference. This is the
    life-history calendar run conversationally, and it is what makes every
    later probe cheap.

Plus the required byte-identity golden: `timeline-passive-single-question-is-
byte-identical` is expressed as a unit test (ruling 7), matching the
`arc_walk` precedent.

**The harness.** `system/timeline_evals.py`, `lifehug.py timeline-evals
[--live] [--json]`, read-only, scored exactly like `arc_walk_evals`:
per-turn lints scored into whichever classes apply at that stage, and the raw
`placed` field passed through BOTH layers together and compared with the
fixture's expectation.

### E. Docs

- **ADR 0024** — "Chronology with basis: dates as intervals, asking
  anchor-first". Records the split ruling 1 makes (asking doctrine kept,
  storage doctrine reversed), the closed vocabularies as a durable data
  contract, the deferred memory, the keystone cap, and the Chapter → Places →
  Events hierarchy.
- **Doctrine comments amended** — `wiki_compile.compile_timeline`'s ":1409"
  paragraph and `classify_story`'s `:389` guideline. `arc_planner.BANNED_PHRASE`
  is **unchanged** and gains a comment saying why it survives.
- **Handbook** — `docs/handbook/timeline.md` (the seven-section template) and
  `docs/handbook/interactions/timeline.md` (with the verbatim `behavior.md`
  embed the parity suite requires), plus the glossary rows: *date record*,
  *basis*, *keystone*, *deferred*, *unknown*.
- **`interactions/README.md`** — the fifth row in the children table, the
  `TurnShape` gate order line, and `timeline` removed from "Proposed, not
  built".
- **`system/version.json`** — 194 → 195, changelog, and every new file in
  `framework_files`.

## Required tests

`tests/test_chronology.py`
- every EDTF row above round-trips `parse_edtf` → `to_edtf`;
- human forms normalize (`2001–2021`, `spring 1998`, `1970s`, `about 1984`);
- unparseable text is `None`, never an exception;
- `display_date` for each granularity, with and without a basis clause;
- `from_age` — bare, hedged, and "5 or 6"; the birthday-window arithmetic;
- `from_anchor` for all three relations;
- `intersect` — tightening, open-ended bounds, disjoint → `None`;
- `widen_for_elapsed` — `certain` never widens; the per-decade rule; the
  granularity coarsening rung;
- `reconcile` — the basis ordering, consilience, deterministic ties, and
  **never drops a claim** (count in == count out).

`tests/test_timeline_dates.py`
- events carry `title` and `date`; a missing title falls back to `event_title`;
- period/chapter/place dates from every source, with the `approximate_dates`
  alias preserved;
- `derive_chrono` — zero dated periods is byte-identical to today's order; one
  dated period re-anchors the interpolation; the dense rank and `chrono_source`;
- `bands` — a chapter band wins where it covers, a period band fills the rest,
  places nest, unmatched events fall to the band's `unplaced_events`;
- `align_chapters` — containment when spans exist, name-match fallback when not;
- corroboration windows from the date record;
- `timeline-place --date/--basis/--anchor` files the display date into the
  correction and stores the record on the pin;
- `jobs._build_timeline_place` accepts and validates the three new fields.

`tests/test_timeline_unknowns.py`
- one unknown per gap, stable keys, a probe on every row;
- `era_gap` emitted only between dated neighbours with a real hole;
- `dependency_index`/`leverage`/`keystones` on a fixture graph, cap = 2;
- the deferred memory: written, honoured inside the window, expired after it,
  and **never counted as outstanding**;
- `arc-plan-target --timeline` ordering and `--era` scoping;
- `leverage_boost` — present in `DEFAULT_LANE_POLICY`, applied only to matching
  questions, and `build_queue` unchanged when `keystone_slugs` is empty.

`tests/test_timeline_interaction.py`
- the manifest audits clean and the registry is exact (six → seven entries);
- composition covers `COMPOSABLE_FILES` exactly;
- **`test_output_contract_block_byte_identical_without_timeline_stage`** —
  ruling 7;
- stage derivation for every branch, including both caller facts;
- `anchors_for_person` ordering and `render_anchors`;
- `choose_probe` — the ladder order, early stop, deferred exclusion;
- `validate_placed` — vocabularies, EDTF, exact anchor membership, the
  `{"deferred": true}` form, and every malformed shape → `None`;
- `lint_timeline_reply` — one positive and one negative per gate class;
- the manifest knobs equal the module constants.

`tests/test_timeline_evals.py`
- fixture shape validation catches every malformed row;
- the ten required golden ids are present;
- the shipped sample predictions pass every gate at its threshold;
- `--json` output shape.

Suite-wide: `TMPDIR=/private/tmp python3 -m pytest -q`, `timeline-evals`, the
four existing eval harnesses unchanged, `check_framework_files.py`,
`check_version_bump.py`, and `tests/test_handbook_parity.py`.

## Version bump

194 → **195**. User-visible: the timeline learns dates, events get titles,
gaps become Play-able unknowns with keystones, and the fifth child interaction
ships.

## Platform twin

A host REPLAYs this package and reads exactly these — nothing else is a
contract.

| What | Where |
|---|---|
| The date record | `chronology.DateRecord`, `chronology.GRANULARITIES\|CONFIDENCES\|BASES` |
| Serialize / parse | `chronology.to_edtf(record)`, `chronology.parse_edtf(text)`, `record.to_dict()`, `chronology.from_dict(value)` |
| Render a date | `chronology.display_date(record)` |
| The arithmetic | `chronology.from_age(birth_date, age_text)`, `chronology.from_anchor(anchor, relation, grain)`, `chronology.intersect(*records)`, `chronology.widen_for_elapsed(record, as_of=…)`, `chronology.reconcile(claims)` |
| A classifier date claim | `chronology.possible_date_claim(value)`, `chronology.record_from_claim(claim, birth_date=…, anchors=…)` |
| Event title (with fallback) | `timeline.event_title(event)` |
| Derived order | `timeline.derive_chrono(periods)`; each period's `chrono_source` |
| The render shape | `timeline.timeline_data()["bands"]`, `["places_by_chapter"]`, `["places_by_period"]` |
| Unknowns | `timeline.unknowns(data)` → `{kind, key, label, probe}`; `timeline.UNKNOWN_KINDS` |
| Leverage & keystones | `timeline.dependency_index(data)`, `timeline.leverage(key, index)`, `timeline.keystones(data, n=…)`, `timeline.KEYSTONE_CAP`, `timeline.keystone_slugs()` |
| Deferred memory | `timeline.defer_unknown(key)`, `timeline.load_deferred()`, `timeline.is_deferred(key)`, `timeline.DEFERRED_QUIET_DAYS` |
| The `{timeline_stage}` this turn is in | `timeline_interaction.timeline_stage_for_session(session, user_leaving=…, placement_settled=…, no_new_bound_streak=…)` |
| The person's landmarks | `timeline_interaction.anchors_for_person(...)`, `timeline_interaction.render_anchors(anchors)` |
| The next question to ask | `timeline_interaction.choose_probe(unknown, anchors=…, precision_so_far=…)`; `timeline_interaction.PLAYBOOK_STEPS` |
| The one additive turn-output field | `conversation_delivery.parse_turn_output(...)["placed"]`, enabled by `TurnShape(timeline_stage=…)` |
| Closed validation of that field | `timeline_interaction.validate_placed(value, anchors=…)` |
| The five timeline lints | `timeline_interaction.lint_timeline_reply(text, stage=…, probe_step=…)`; `timeline_interaction.TIMELINE_LINT_CLASSES` |
| The leaf the caller REPLAYs verbatim | `interactions/timeline/prompt/turn-instructions.md`, substituting `{timeline_stage}`, `{unknown_label}`, `{probe}`, `{anchors}`, `{precision_so_far}` |
| The write verb (extended) | `lifehug.py timeline-place <source> --period <slug> [--date <edtf>] [--basis <basis>] [--anchor <key>]…` |
| The read-only plan verb | `lifehug.py arc-plan-target --timeline [--era <slug>] [--json]` |
| The seat gate | `lifehug.py timeline-evals [--live] [--json]` |
| The job payload | `jobs` command `timeline-place`, optional `date` / `basis` / `anchors` |

The FILING of a `placed` record is host-side: the package names the date, the
host writes it through `timeline-place`.

## Deviations from the design brief (honest notes)

1. **`2001-21` is a SEASON, not a compact range.** The brief lists it beside
   `1984~`/`198X`/`1984/..` as an EDTF form; in ISO 8601-2 `-21..-24` are the
   sub-year season codes, and `2001-21` therefore means *spring 2001*. A
   2001–2021 interval is `2001/2021`. Both are supported; the table above is
   the contract.
2. **`process-answer` has no `placed` path to extend.** The brief says
   "`process-answer`'s existing path passes `placed` outputs into
   `timeline-place`". No package runtime consumes any child's additive output
   field — `placement`, `focus_setup`, `entity_setup`, and
   `answered_question_id` are all parsed, validated, evaluated, and then
   **filed by the host** (ADR 0018/0023). `placed` follows that precedent;
   what this PR delivers instead is the pure bridge
   `timeline_interaction.place_invocation(placed, source=…, description=…,
   period=…)` returning the exact `timeline-place` argv, plus the extended
   verb and job payload it targets.
3. **`--timeline` is not an `arc_walk` target kind.** `arc_walk.normalize_target`
   requires bank categories and builds a plan of bank questions; a timeline
   unknown is neither. `arc-plan-target --timeline` therefore dispatches to
   the timeline plan builder rather than widening `ARC_TARGET_KINDS`, keeping
   `arc_walk`'s closed roster closed.
4. **"Never pressure" is inherited, not re-implemented.** Five lint classes,
   not six: re-defining a rule the parent contract and `arc_walk` already own
   would be exactly the second definition the recurring-defect doctrine
   forbids.

## Acceptance checklist

- [ ] `python3 -m pytest -q` green (and `python3 -m unittest discover -s tests`).
- [ ] `python3 system/lifehug.py timeline-evals --json` passes.
- [ ] The four existing eval harnesses pass unchanged.
- [ ] `python3 scripts/ci/check_framework_files.py` exits 0.
- [ ] `tests/test_handbook_parity.py` green (every quoted number annotated).
- [ ] `interaction_registry.audit_interaction_package("timeline") == []`.
- [ ] The passive daily question's prompt does not move by one byte.
