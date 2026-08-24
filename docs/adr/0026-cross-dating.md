# ADR 0026: Cross-dating — a resolved anchor places its dependent moments

Date: 2026-08-24
Status: proposed

## Context

The owner filed his birth landmark on staging: **1981-07-11, granularity
day, basis stated**. `keystones()` had been telling him, since v196, that
*"one answer would place 53 more things."*

He answered it. Then he opened the timeline and the moment **"Born in
Redlands while the family lived in the area"** still read **undated** — and it
was still carrying the classifier's free-text `anchor: dad attending ASU`,
which is not merely unhelpful but *temporally wrong*: ASU came years later.

The gap is structural, not a bug in one function. **Nothing in the package has
ever propagated a resolved anchor to its dependent moments.** A date reached a
moment through exactly two doors:

1. the classifier's own `events[].date` claim, resolved by
   `chronology.record_from_claim` in `timeline.resolve_event_dates`; and
2. an explicit, per-moment `lifehug.py timeline-place`.

Everything else in the chronology machinery — `from_age`, `from_anchor`,
`intersect`, `widen_for_elapsed`, the whole anchor index — was *reachable* but
had no caller that walked the undated moments and tried it. The landmark set
(v197–v202) built the life-history calendar, the Reading Room (v204) built a
plan for filling it, and neither of them ever spent it.

So the leverage number was a promise the system could not keep, in the most
literal sense: `dependency_index` counted what an anchor *touched* — every
undated moment sharing its era, every moment sharing a person's sources, every
neighbour of a dated event — and answering the starred question placed exactly
none of them. **The promise and the delivery came from different places.**

## Decision

**Cross-dating is a derivation-time pass** (`system/cross_dating.py`), pure and
stateless, invoked by `timeline.timeline_data()` between `place_events` and
`build_bands`. For every still-undated moment it attempts one derivation,
strongest join first, and stops at the first that fires.

### 1. The ladder

**(a) Definitional joins — the moment IS a landmark fact.**

| Join | Marker | Date it takes |
|---|---|---|
| `birth` | the moment states the subject's OWN birth | the birth landmark, at its own granularity |
| `move_in` | a move verb **and** a residence landmark named in the prose | that span's `earliest` |
| `move_out` | a leaving verb **and** a residence landmark named in the prose | that span's `latest` |
| `graduation` | a graduation word **and** a schooling landmark named in the prose | that span's `latest` |
| `named_anchor` | the classifier's own `anchor` field resolves through `chronology.anchor_key` to an indexed landmark, EXACTLY | that landmark's span, as bounds |

The marker sets are small, explicit, and testable, and they are **matched per
field** — `^born` is a claim about one field, not about whichever field
happened to be concatenated first. Somebody else's birth in the same sentence
**vetoes** the birth join outright. There is no fuzzy semantic matching
anywhere in the pass and there never will be: **a miss is fine, a wrong join
is not.**

This is also the answer to the stale-anchor half of the report: `dad
attending ASU` names nothing in the anchor index, so it resolves to `None` and
derives nothing. The guard that fixes the owner's wrong anchor is the same
guard that makes the join safe.

**(b) Age statements** — an explicit age in the person's own words, plus the
birthday, through `chronology.from_age`. `parse_age` is deliberately greedy
(it reads any number handed to it), so the pass never hands it raw prose: an
age *statement* pattern matches first and only the matched fragment goes
through. "We drove 400 miles" is not an age; "at 19 I left home" is; "the
house at 19 Elm Street" is not. The number words come from
`chronology.NUMBER_WORDS` itself, so the detector and the parser cannot drift.

**(c) Containment** — a moment inside a place or an era whose **span** is known
takes that span as **bounds**: a *terminus post quem* and a *terminus ante
quem*, granularity `range`. Bounds, never a point. "The interval is itself a
finding, not a failure" (`system/research/chronology.md` §1). The place join
uses the same provable **source overlap** `timeline._place_for_event` uses —
never keyword matching — and is preferred over the era because it is tighter.

### 2. Four invariants

* **An explicit record is never overwritten.** A moment that already carries a
  date — stated, age-resolved, connector-corroborated, or pinned by the owner
  through `timeline-place` — is skipped before any marker is even read.
* **Nothing is invented.** Every derived interval is arithmetic over dates the
  person actually gave.
* **Everything says how it got there.** `basis` is `anchor` or `age`,
  `anchors` names the landmark, `provenance` carries the human sentence the
  page shows, and the row gains `date_derived` — the *only* marker of a
  derived date.
* **No state.** Derived dates live in the derived payload and nowhere else.
  They are recomputed on every read, so a better landmark improves the whole
  timeline instantly and a corrected landmark un-derives what it used to
  support. There is nothing to migrate, nothing to repair, and no second
  writer. (Explicitly considered and rejected: persisting derived records
  beside the placements. It buys nothing — the pass is microseconds — and it
  buys a staleness class the package would then have to police.)

### 3. Confidence is graded by how tight the join is

**A definitional join INHERITS the landmark record's own confidence**
(owner ruling, 2026-08-24). The marker sets are deliberately exact-match, and a
definitional identity — *this moment IS your birth*, *this moment IS that
residence span's start* — is not an estimate. So a certain birthday dates the
birth moment `certain`, and the owner's chip reads **"11 July 1981"**, not
"around 11 July 1981". Inheritance, not promotion: a hedged birthday (`1981~`)
yields an `approximate` moment.

`chronology.from_anchor` floors its result at `inferred`. That floor is right
for a RELATION — "before the move" genuinely is an inference over a span — and
wrong for an identity, so `cross_dating._inherited_confidence` lifts it, and
**only for the definitional rule**. An **age** join keeps whatever `from_age`
earned (the hedge, not the landmark); **containment** is `inferred` for a place
and `conjectural` for an era — the documentary editors' mark for a date the
system worked out rather than one the person asserted.

Inheriting the confidence never inherits the *warrant*: the basis stays
`anchor` (4.0) against `stated` (6.0), so `claim_score` keeps every stated
claim above every derived one, and ranks a place-bounded moment above an
era-bounded one, for free.

### 4. The displayed anchor becomes the landmark provenance

Where a date was derived, the viewer and the compiled page show the landmark
sentence ("from your birthday", "from when you moved to Mesa", "within your
years at Mesa") where `· anchor: <classifier text>` used to sit. The
classifier's own anchor is **demoted to the detail line**, never destroyed —
the owner's `dad attending ASU` still reads on the row, under the source,
where a wrong model note belongs.

### 5. Leverage counts what this pass can derive — the same join, both ways

`timeline.dependency_index`'s **moment** claims are now computed by
`cross_dating.derivable_moments`, which is the containment rule read backwards.
Two claims went away with it, both fictions:

* a **dated event** no longer claims its undated neighbours — a point is not a
  span, and nothing has ever derived a date from an adjacent moment; and
* a **person entity** no longer claims the moments sharing its sources — an
  arrival bounds nothing.

Each keeps what IS definitional: an era's own bounds, the `era_gap`s it would
close, the `place_span` rows that fall out of a dated era's moments
(`_place_span` derives a residence's span from the moments that happened
there), and a place's own span. `keystones()`, `dig_plan()` and the greedy
plan are untouched — they read this index and nothing about their algorithm
changed.

A test asserts the reconciliation directly: take the promise off an undated
synthetic vault, supply exactly that one answer, and count what dates. It is
the same number.

### 6. Unknowns shrink because the moments left the undated set

`unknowns()` reads `event["date"] is None` off the same payload the pass just
wrote, so a dated moment stops being an unknown with no further wiring. The
downstream effect is the one that matters most: `_place_span` derives a
residence's span from the dated moments that happened there, so dating an era
transitively closes the `place_span` unknowns inside it, and `build_bands`
runs after the pass so it sees them.

## Consequences

- **Binds:** any new join goes in `system/cross_dating.py` behind an explicit,
  testable marker set and a golden. Adding one to `timeline.py`, to
  `classify_story.py`'s prompt, or to a renderer is the drift this module
  exists to prevent.
- **Binds:** any new anchor kind that should place moments must appear in BOTH
  `cross_dating.derive` and `cross_dating.derivable_moments`, or the promise
  and the delivery diverge again. The two functions sit next to each other for
  exactly that reason.
- **Binds:** a derived date is identified by `event["date_derived"]` and
  nothing else. A renderer must not sniff `basis == "anchor"` — a stated
  anchor claim has that basis too.
- **Forecloses:** a stored derived-date file, a "re-derive" job, a repair pass,
  and a second writer of any kind. It also forecloses fuzzy or model-driven
  joins: this pass is arithmetic over stated facts, and a moment it cannot
  reach stays honestly undated.
- **Forecloses:** a moment taking a *point* date from an era or a place. Those
  joins yield bounds; a point would be a manufactured precision the person
  never gave.
- **Delete-when:** if the classifier ever emits a reliable `anchor_ref` for
  every moment, joins (a)-`named_anchor` and (b) become redundant with
  `record_from_claim` and should collapse into it rather than being maintained
  twice.

## Platform twin (lifehug/lifehug-platform)

| What | Platform action |
|---|---|
| `timeline_data()["cross_dating"]` report | none — additive key on an existing payload |
| `counts.events_cross_dated` | none — additive count |
| `event["date_derived"]` on moment rows | none to render correctly; **optional** to render *well* — the hosted timeline's date chips already read `event["date"]`, so derived dates appear with no platform change. To show the landmark provenance in place of the stale classifier anchor (this ADR §4), the platform's timeline view reads `date_derived.provenance` the way `serve_wiki._event_html` does. |
| `dependency_index` / `keystones` numbers | none — same shape, honester values. Hosted surfaces that display leverage will show smaller, true numbers after the pin bump. |
| `chronology.anchor_key` / `lookup_anchor` / `NUMBER_WORDS` | none — new public names; the private `_`-prefixed aliases are kept. |

**The honest claim: zero platform code is required.** Everything the pass adds
is additive to payloads the platform already reads, and the derived dates flow
through the existing `date` field. The one thing the platform *should* pick up
at the next pin bump is `date_derived.provenance`, because without it a hosted
timeline keeps showing the stale classifier anchor beside a correct derived
chip — which is the exact contradiction the owner reported.

## Decisions this one rests on

- [ADR 0024 — Chronology with basis](0024-chronology-with-basis.md) — the
  `DateRecord`, the anchor index, and every piece of arithmetic this pass
  calls.
- [ADR 0025 — The Reading Room](0025-the-reading-room.md) — the greedy plan
  over `dependency_index`, whose numbers this ADR makes true.
- `system/research/chronology.md` §1 (bounding before pinning, conjectural
  marking), §6 (the elicitation playbook), and `system/research/go-deep.md` §7
  (genealogy's apparatus — the discipline this pass mechanizes).

---

## Amendment (2026-08-24 — v207, `band-dating` · design D2/D3/T3)

Companion to `lifehug-platform` `docs/design/dating-dataflow.md`, the audit the
owner asked for after this ADR's own incident ("a quick fix isn't going to
work; a complete audit of how the system should work"). The audit found the
original decision correct and **half-applied**: v205 taught a resolved anchor
to place its dependent MOMENTS, and the founder's case was still only half
fixed. His birth is filed. *"Born in Redlands"* is dated to the day. The era it
sits in — **"Childhood"** — still read `undated`, because `build_bands` and
`chapter_date` have only ever read a band's OWN `date` (audit finding **D2**),
and until a band is dated nothing re-derives the spine's order from it (**D3**).
And nothing ever told him, in the conversation, what his answer had just done
(**T3**).

### 1. Bands date themselves, from a ladder of their own

`cross_dating.date_bands` walks every UNDATED period and gives it a span:

| Rule | Join | The span it takes |
|---|---|---|
| `residence` | `residence_span` | the union of the spans of the PLACES that line up with the era — each place's own page span, or the residence landmark whose label the page names **exactly** |
| `moments` | `moment_envelope` | the envelope of the moments already dated inside it — the same arithmetic `timeline._place_span` has applied to a residence since v195 |
| `age_label` | `age_label` | an era the roster NAMED after an age (*"My 20s"*) joined to the birthday |

**The order is deliberately not [§1](#1-the-ladder)'s.** For a MOMENT, the
definitional marker is the person's own sentence, so it leads. For a BAND, the
"definitional" rung is an age sitting in a name a **roster model** wrote, so it
ranks under the two rungs grounded in what the person actually did — where they
lived, and what is already dated inside. In a real vault this is also simply
tighter: an era holding moments dated 2003–2008 is better described by them
than by the decade its label implies. `my` is REQUIRED on the label — *"the
80s"* is a decade of the century and *"his 40s"* is somebody else's life, and
neither of them is this person's era.

Everything §2 binds still binds. An explicit band date — a page's frontmatter,
a roster span, a `timeline-place` correction — is never overwritten. A derived
band carries `date_derived` (the only marker), the `approximate_dates` display
alias every other reader already uses, and a provenance sentence the viewer and
the compiled export now print beside the span:
`## Childhood — around 1981 · from the moments you have already dated`.
Nothing is stored.

### 2. A floor is not a ceiling

This is the sharpest line in the amendment. A residence union and a moment
envelope say *"this era at least covers that"* — they bound its extent from
**inside**, and they are honest to display, to order the spine by, and to
measure a hole between eras with. They are **dishonest pushed back down onto
the era's other moments**, where one dated moment would pin forty-seven undated
ones to its own year — a manufactured precision of exactly the kind §2 forbids.

`BAND_RULES_THAT_BOUND` names the only rule whose span is closed at both ends
(`age_label`: *"My 20s"* IS the decade from the twentieth birthday), and
`cross_dating.containment_periods` hides every floor-only span from the
containment rung without touching the row a renderer holds. An **explicitly**
dated era bounds its moments exactly as it did in v205.

### 3. The pass is three phases, not two mechanisms

Moments → bands → the moments the newly dated bands now bound. The third phase
is the SAME idempotent sweep as the first (a moment already carrying a date is
skipped in both); it exists because containment reads a band's span, which
phase two is what supplies. `timeline_data` then re-runs `derive_chrono` when a
band was derived, which is **D3, for free**: a filed landmark improves the
spine's ORDER on the same read it improves the dates.

The unknown and gap accounting updates with no extra wiring, exactly as §6
predicted one level down: a derived era leaves the `period_bound` set because
`unknowns()` reads `period["date"]` off the payload the pass just wrote, and
`era_gaps` measures holes against derived spans. `counts.periods_cross_dated`
is additive beside `counts.events_cross_dated`.

### 4. The filing beat — the conversation says what the answer placed

`cross_dating.gain_sentence_for_record(record, timeline_payload)` answers, at
the moment a landmark or a placement is filed, the only question the person
actually has: *what did that just do?* It is pure, and it computes the answer
by running **this pass** over copies of the current payload with the new record
folded in. That is §5's promise-equals-delivery discipline applied to a sentence
instead of a star: the conversation can only claim what the next derivation
will actually deliver, because the same code computed both.

> Got it — that dates nine moments and your Childhood years.

The moment clause is `cross_dating.moment_clause`, which
`reading_room.placement_gain_sentence` now also says — one definition, so the
Reading Room and the two filing lanes can never drift into two wordings of the
same true thing. Past one era the eras are counted rather than listed; a count
of what REMAINS is still forbidden everywhere.

The landmark and timeline leaves gained a `{filing_gain}` slot rendered by
`cross_dating.render_filing_gain`. The **direction is rendered together with
the sentence**, so a turn that filed nothing substitutes the empty string and
the filled prompt is byte-identical to v205's — no blank line, no dangling
instruction. The honest latency lives in the direction, not in the sentence:
the pages catch up in a minute or two, and the person hears the good news now.

### 5. Consequences this amendment adds

- **Binds:** a new band rule goes in `cross_dating.BAND_RULES` behind an
  explicit marker set and a golden, and must declare whether it BOUNDS. A rule
  that yields a floor and is added to `BAND_RULES_THAT_BOUND` is the
  manufactured precision this section exists to prevent.
- **Binds:** the envelope has ONE definition, `cross_dating.span_from_dated`.
  `timeline._place_span` delegates to it; a third copy is the recurring-defect
  doctrine's exact failure case.
- **Forecloses:** a stored band date, a "re-derive the spine" job, and a second
  writer of `period["date"]` — for the same reasons §2 forecloses them for
  moments.
- **Open, deliberately:** chapters still date only from the chapters exercise's
  own words (`timeline.chapter_date`). Deriving a chapter's span from the
  periods inside it would fight `align_chapters`, which already aligns by date
  containment when both sides carry spans; if chapters should date from
  landmarks too, that is its own change with its own goldens.

## Platform twin — additions

| What | Platform action |
|---|---|
| `period["date_derived"]` on band rows | none to render correctly; **optional** to render *well* — take the provenance line beside the span, the same way the moment rows already do |
| `counts.periods_cross_dated`, `cross_dating.bands` in the report | none — additive keys |
| `{filing_gain}` on the landmark and timeline leaves | the engine fills the kwarg **after** it files the turn's record, from the timeline payload it already holds, with `cross_dating.gain_sentence_for_record` → `render_filing_gain`; `""` (or omitting it) on every other turn keeps the prompt byte-identical. Additive — nothing else about the REPLAY moves. |
