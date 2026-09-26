---
title: The Timeline & Chronology
parent: Handbook
nav_order: 11
---

# The Timeline & Chronology

**Note 2026-09-03:** the platform program ports the placement score, per-year band, leverage/resolves, keystones and landmark rows into the calculated projection (`temporal_projection` / `temporal_publication`) in Cuts 2–5 and retires the legacy `timeline_data()` projection in Cut 7 (owner ruling R4, `lifehug-platform docs/decisions/2026-09-03-timeline-unification/decision-record.md`). The arithmetic is unchanged; the `system/timeline.py` locations named below are the legacy home until then. Queue eligibility for landmark and timeline questions is owner ruling R2 (same record, Cut 5b, **landed v288**: `system/timeline_candidates.py` mints the published `landmark_opportunities` and `keystones` above `timeline_leverage_per_story` as `timeline`-group bank rows with provenance `timeline-gain`, and the whisper reuses the same identity). **Landed v284 (Cut 3a):** the leverage/resolves and keystone half is now ALSO published from the calculated projection by `system/timeline_gain.py` — every Timeline-owned work item carries `resolves` and `leverage = 1 + len(resolves)`, the projection carries `keystones` (`tl:<anchor-slug>`, cap 2) and the `dependency_index` they were computed from, and Mirror-owned kinds keep `combined_score` alone. Same arithmetic, second graph; the legacy home below still stands until Cut 7. **Landed v286 (Cut 5a, ADR 0032):** the LANDMARK half is now computed from that same graph — `system/landmark_opportunities.py` publishes `landmark_opportunities` (a named gap, its `leverage`/`resolves`, and a question generated from the gap) and `landmark_sufficiency` (`{sufficient, best_leverage, reason}` per domain, against the queue's own `timeline_leverage_per_story` dial), so a domain leaves the privileged surface when its remaining questions stop being worth one. `timeline.landmark_rows_for` is untouched and retires in Cut 7b.

## 1. What it does & what it's for

The timeline is not a feature for storing dates. It is the page where you
check whether the system has understood the *sequence* of your life — as the
owner put it: "this is what Lifehug sees based on what I've said — and here
are some gaps, things that are unplaced."

Until v195 it could not hold a date at all, by doctrine. That doctrine was
half right: asking someone what year something happened buys a rounded,
telescoped guess, because dating a memory is reconstruction rather than recall
(Friedman 1993). It was also half wrong: historians never pin a date without
*bounding* it first, and the interval they end up with is a finding, not a
failure. A person who tells you their birthday and that they were "about five"
has told you the year. Refusing to do the arithmetic was not humility; it was
throwing away what they said.

So from v195, **asking stays anchor-first and storage gains real dates**. The
system does the arithmetic, records how it got there, and shows its work. And
because dates exist, three things become possible that were not: eras can be
ordered by when they happened rather than by a model's opinion; a *hole*
between two dated eras becomes a computable thing you can answer; and the
system can tell you which single answer would put the most pieces in place.

The main use case: "the timeline looks wrong, or empty in the middle — what do
I do about it?" The answer is Play, and the conversation that follows never
asks you for a year.

## 2. The nouns

- **Date record** — a date as an *interval with a basis*:
  `{best, earliest, latest, granularity, confidence, basis, anchors,
  provenance}` (`chronology.DateRecord`). Stored as EDTF / ISO 8601-2 level 1
  — `1984`, `1984~` (approximately), `198X` (some year in the 80s),
  `1998-06`, `2001-21` (spring 2001), `1984/1990`, `1984/..` (1984 or later),
  `../1984` (1984 or earlier).
- **Granularity** — how precise the claim is: day, month, season, year, range,
  era.
- **Confidence** — how sure: certain, approximate, inferred, conjectural. The
  last is the documentary editors' convention for a date the system worked
  out rather than one the person asserted.
- **Basis** — *how* the system came to believe it: `stated` (they said it),
  `age` (their age against their birthday), `anchor` (a landmark plus a
  before/after), `order` (sequence only), `public_event`, `connector`, plus
  three **evidence** bases (v204, ADR 0025): `document` (a date printed
  on paper, read out), `photo` (a contextual date, which is a *window* by
  construction and says so on the record), and `relative` (someone else's
  memory, relayed, with the witness named in provenance).
- **Landmarks** — the **universal** set of dating questions everyone gets:
  birth, **the family you came from**, the places lived, schooling,
  partnerships, children, jobs. Same for every person, and the skeleton that
  makes everything else placeable by arithmetic. Some are answered at
  onboarding; the rest sit here with Play and surface later.
  (`system/research/landmarks.md` is the authority for the set and its
  wording.)
- **Family** (v202) — the second domain, where practitioner intake puts it. A
  sibling's birth year anchors **childhood**, the stretch the residence chain
  covers worst; parents and grandparents are the **witnesses** who can supply
  the two closed lists when memory cannot. The *dates* are landmarks; the
  *people* are roster entities with a relationship fact — never a second
  store. (research §2.9)
- **Anchor** — a landmark of the person's own *once it is dated*: their
  birthday, a residence with a span, an era with a span, a dated moment.
  Collectively they are the life-history calendar, and every probe above the
  second rung is cheap because they exist. Landmarks are the questions;
  anchors are what the answers become.
- **Band** — a row of the timeline. The person's own life **chapter** is the
  band wherever a dated chapter covers the stretch; the system's **period** is
  the band everywhere else. Inside a band, the **places** lived nest, and the
  **events** sit under their place.
- **Unknown** — ONE concrete thing the person can answer about:
  `{kind, key, label, probe}`, where the label names the subject and the probe
  is a real question about it. Seven kinds: a specific undated **moment**, an
  era's missing **bounds**, a **place**'s span, an **era gap** (a dated hole
  between two dated bands — the kind that could not exist before dates did),
  a **date contradiction**, and — v202, the *unknowns are concrete* principle
  applied to the landmark set — a **landmark subject** (one half-filled person
  or place inside an enumeration domain, named: "What year was Jackie born?")
  and a **residence gap** (a hole between two dated residence spans: "Where
  did you live between Mesa and Yucaipa, around 1992–1995?"). The last two
  arrive carrying the ladder's own subject-named question, so `unknowns()`
  leaves their probe alone rather than replacing it with a generic opener.
  Never a count: "116 moments I can't place" is
  a number, and a number is not a question (owner-set, 2026-08-23). The counts
  live on the **ledger** (`unknown_ledger`), and the page offers the top
  `UNKNOWNS_PAGE_CAP` unknowns by leverage.
  <!-- parity: timeline.UNKNOWNS_PAGE_CAP = 30 -->
- **Leverage** — how many unknowns one anchor would resolve. **Keystones** are
  the top two, starred. <!-- parity: timeline.KEYSTONE_CAP = 2 -->
- **Cornerstone** (owner-named, 2026-09-25; ADR 0038) — one of the small FIXED
  set of dates everything is measured from, and the only dates asked to the
  day: the owner's birth; each child's birth; the births of his parents,
  siblings and spouse; each of his weddings and divorces; the deaths of his
  parents, spouse, siblings, children and grandparents; his baptism once
  mentioned (`cornerstones.CORNERSTONES`). A keystone is computed and changes
  with every answer; a cornerstone is the same set for every life.
- **Landmarks view / Cornerstones view** (v360, owner 2026-09-25,
  `timeline_views`) — the two read models behind the Timeline's two square
  buttons, published as the additive `landmarks_view` and `cornerstones_view`
  keys beside `relation_words` (a display decision; the rule version does not
  move). The **landmarks view** is every landmark entry you gave, after the
  merge records, by domain: a place you lived twice is one landmark with both
  stays, each at the grain you gave, and a home always shows nickname,
  address, city, state and country — `null` where you have not said it, never
  guessed (`timeline_views.A_HOME_SHOWS_EVERY_FIELD`). Homes, schools and work
  show their **gaps** — a hole of more than two months between stays
  (`timeline_views.A_GAP_IS_A_HOLE_OF_MORE_THAN_TWO_MONTHS`), shown ░ and
  never asked; a residence gap names `landmarks_interaction.residence_gaps`'
  own unknown key rather than redefining it — and their **covered** stretches
  ◇: a stretch another landmark accounts for, a mission or military service,
  is covered, not a gap (`timeline_views.A_COVERED_STRETCH_IS_NOT_A_GAP`). The
  **cornerstones view** is one row per person in the cornerstone set, grouped
  You / Spouse / Children / Parents / Siblings / Grandparents, with born,
  married, divorced and died, each `exact` (a day), `needs_day`,
  `disagreement` (an open contradiction on it) or `missing`; a death nobody
  has told is `not_owed`, never asked. Each person is shown by what you call
  them ("Dad", "Mom", "AJ"). A row that needs settling carries its Play: the
  open work item on it, else its landmarks ladder.
- **Cross-dating** (v205) — the pass that spends the landmarks. For every
  still-undated moment it tries one derivation, strongest join first:
  **definitional** (the moment IS a landmark fact — a birth, a move, a
  graduation), then an **age statement**, then **containment** (a place or an
  era whose span is known bounds what happened inside it). Pure, stateless and
  recomputed on every read. Before v205 nothing propagated a resolved anchor at
  all, so a filed birthday left "Born in Redlands" undated and the leverage
  number promised what no pass delivered.
- **Date before you place** (v254) — the pass runs in two halves, and the half
  that needs no era runs **first**, before a moment is slotted anywhere. Until
  v254 it ran entirely afterwards, so a moment whose date the pass supplies was
  undated at the moment something asked where it goes: twelve of the founder's
  thirteen dated moments landed by era LANGUAGE instead of by their date, and
  "Married Katie" (2007) sat in `high-school` while `my-20s` held nothing.
- **Band dating** (v207, narrowed in v254) — the same pass, one level up. An
  **undated** era takes a span from the places lived in it (their own span, or
  the residence landmark the page names exactly), else — when the roster NAMED
  it after an age, "My 20s" — from the birthday. The order is deliberately not
  the moment ladder's: an age label is a name a model wrote, so it ranks under
  the rung grounded in what the person actually did.
- **An era is never dated by its members** (v254) — the envelope of the moments
  inside an era used to be band rule 2, and it is gone. What is "inside" an era
  is a placement this same pass helps decide, so dating the era from it makes
  the accident of slotting look like a fact: `high-school` read `1997/2021` off
  moments that were only there because the rung above had failed. The coverage
  is still computed and still published — `observed_envelope` on the row, the
  same key and the same arithmetic the calculated projection uses — and it
  never reaches `date`. It says what the era's members happen to span. It does
  not say when the era was.
- **A floor is not a ceiling** (v207) — a residence union bounds an era from
  *inside*: it says the era at least covers that. Honest to display, to order
  the spine by, and to measure a gap between eras with; never pushed back down
  onto the era's other moments, where one dated moment would pin every undated
  one to its own year. Only a span closed at both ends — an age label, or an
  explicitly dated era — bounds what is inside it
  (`cross_dating.BAND_RULES_THAT_BOUND`).
- **The filing beat** (v207) — when a landmark or a placement is filed, the
  reply says what it just unlocked: *"Got it — that dates nine moments and your
  Childhood years."* The count is computed by running the pass itself over the
  current payload with the new record folded in, so the conversation can only
  claim what the next derivation will deliver. The pages catch up about two
  minutes later; the person hears it now.
- **Derived date** — a date this pass worked out rather than one the person
  stated, marked by `date_derived` on the row — a moment's or, since v207, a
  band's — and by nothing else. It
  carries the landmark it leaned on (`anchors`), the sentence the page shows
  ("from your birthday"), and a confidence graded by how tight the join was: a
  **definitional** join inherits the landmark's own confidence (an identity is
  not an estimate — a certain birthday gives a certain date), an **age** join
  keeps the hedge the person gave, and **containment** is `inferred` for a
  place, `conjectural` for an era. An explicit record is never overwritten.
- **Placement** (v208) — how much of this life the timeline can order and
  place, as one number from 0 to 1. Scored on the WIDTH of what is known, never
  on whether a field has a value; a **floor**, never an exact reading; a
  **pair**, stated beside derived; and shown as one of five **bands**, never a
  bare percentage. The word is *placement* — never "completeness", never
  "accuracy", and never a verdict on the life.
  <!-- parity: timeline.PLACEMENT_ROUNDING = 4 -->
- **Ghost** (v208) — what a dated moment's interval would be *absent its date*:
  its era's span where the era has one, else the life (`prior_span`). It is
  reconstructed on every read, never stored — so after an era's own dates
  improve, old ghosts tighten. A ghost is today's honest reconstruction of
  "before", not a screenshot of what the page once said.
- **Glow** (v208) — how much one unanswered thing would light up if it were
  answered: `resolves` (the other unknowns the anchor this row would *become*
  would also place) and `leverage` (`1 + len(resolves)`, self-inclusive, so a
  row with no reach is exactly 1). The glow is relative and its ranking is the
  host's; the package supplies raw honest numbers and ranks nothing.
- **Whisper** — the week's arc card carrying a keystone's real probe and the
  person's own landmarks into an ordinary conversation. Raised only where it
  fits, at most once, any precision accepted, never pressed.
- **Keystone question** — the same probe minted as an ordinary bank question
  in the `timeline` group, asked as the day's question. Answered once, never
  re-asked, by the bank's own mechanism.
- **Place aside** (v200) — the whisper's sibling for a **place with no
  stories**: a residence the landmark set named, with a known span and no
  moments attached. A **story** gap, not a dating one — it asks what life was
  like there, never when it was. It rides an arc card exactly as a whisper
  does, ranked after the whisper, at most one per card, counted within the
  same weekly `arc_planner.DEFAULT_GAP_MAX`; like any landmark question it may
  enter the daily queue only above the shared value threshold (owner ruling R2,
  2026-09-03, `lifehug-platform docs/decisions/2026-09-03-timeline-unification/decision-record.md`;
  Cut 5b, v288) and is never a reminder. `timeline.timeline_data()["place_no_stories"]` →
  `arc_planner.collect_places_without_stories` →
  `landmarks_interaction.render_place_no_stories`.
  <!-- parity: arc_planner.DEFAULT_GAP_MAX = 3 -->
- **"I'll find out"** — an ordinary answer. Nothing is filed, nothing is
  remembered, the unknown simply stays outstanding and keeps its star. (v196
  deleted the deferral side-state v195 had introduced.)

**How the timeline words relate.** Landmarks are the universal
skeleton — spans and points, by domain; **keystones** are the per-person gaps
that skeleton leaves — the one date that would place the most moments,
computed from the dependency graph; **cornerstones** are the fixed dated
points everything is measured from, asked to the day while everything else
stops at a month; and **whispers** and **keystone questions** are the two ways
the loop asks.

### The substrate nouns

The nouns above are the *chronology* vocabulary — how one date is represented
and reasoned about. Beneath them sits the **claim substrate**, the durable layer
the calculated projection is folded from, and it has its own named set. They are
defined once, with their files and their code seats, in the framework README
under [The substrate](https://github.com/lifehug/lifehug#the-substrate--the-nouns-the-timeline-is-actually-made-of);
this page uses them with exactly those meanings:

**source** (immutable raw text) → **telling** (one account of one event inside
one source) → **claim** (one assertion, with an interval, a basis, a confidence
and a quote; seven `claim_type`s, of which `identity` and `occurrence` carry no
interval at all) → **receipt** (the append-only file a filing writes) → **the
fold** (the pure function from every receipt to the drawing) → **node** (a group
of claims about one event — a dated moment) and **work item** (the card asking
what is still missing). Beside them: **episode** and **binding envelope** (the
identity layer's answer to *"are these two tellings one event?"*), **alias** (a
published redirect from an id that moved), **landmark entry** and its **domain
ladder**, **frame** (calculated period) and **era** (person-created period),
**axis membership**, **the spine** and **the resolver**.

Two invariants a reader should carry into every section below. The receipts are
the only authority — everything else, including `state/landmarks.json` and the
published projection, is a *drawing* that is recomputed, which is why un-drawing
a record never loses it and why a correction needs no migration. And a losing
claim is never deleted: it is `superseded`, `retracted` or left `disputed`
beside the claim it disagrees with.

**What a re-reading may retire (v354).** The fold elects one winning receipt per
`(source_id, revision, extractor identity)` and keeps the rest as *previous
interpretations of the same words*, `superseded / reextracted`. The unit is the
READER as well as the document revision: a prompt edit, a new model or a bumped
rule version is a later version of one reader and its earlier reading is retired,
while `general_listener` and `answer_placement` reading one promoted reply are two
readings of it and neither retires the other
(`temporal_store.A_READING_IS_ONLY_SUPERSEDED_BY_THE_SAME_READER`, lifehug#409).
WHO read a document is the name at the head of its extractor version
(`temporal_claims.extractor_identity`); everything after the name is which version
of that reader did the reading.

## 3. How it works

**Where a date comes from.** The classifier records only what the author
explicitly said: a year they actually named, their age in their own words, or
a landmark plus a before/after. It never converts and never guesses — that
rule is unchanged, just restated as *"do not invent; do record what was
said"*. Then `chronology` does the arithmetic: `from_age` turns a birthday and
"about five" into `1984~` with basis `age`; `from_anchor` turns "before we
moved" into `../1984`; `intersect` combines several claims into the tightest
interval they all allow.

**How moments get dates** (v205, [ADR 0026](../adr/0026-cross-dating.md)).
Until v205 a date reached a moment through exactly two doors: the classifier's
own claim, and an explicit `timeline-place`. So you could file your birthday —
the highest-leverage answer the system knows how to ask for — and the moment
*"Born in Redlands while the family lived in the area"* would still read
**undated**, still carrying whatever the classifier had written in its free-text
`anchor` field. The star said *"one answer would place 53 more things"* and
answering it placed none.

**Cross-dating** is the third door, and it runs on every read. For each
still-undated moment it tries one derivation and stops at the first that fires:

| Order | Rule | What it needs | What it gives |
|---|---|---|---|
| 1 | **definitional** | the moment IS a landmark fact — an explicit birth/move/graduation marker naming a landmark you filed, or an `anchor` field that resolves to one exactly | that landmark's own date |
| 2 | **age** | an explicit age in your own words, plus your birthday | `from_age`'s interval |
| 3 | **containment** | a place or an era whose span is known | that span, as **bounds** |

Four rules keep it honest. **An explicit record is never overwritten** — a
stated date that contradicts a landmark survives untouched and the two are
reconciled the usual way. **Nothing is invented**: every interval is arithmetic
over dates you actually gave, so a moment no anchor reaches stays honestly
undated. **Everything shows its work** — a derived date names the landmark it
leaned on and renders the reason where the classifier's anchor used to sit
("from your birthday"), with the model's own note demoted to the detail line
rather than deleted. And **nothing is stored**: derived dates live only in the
derived payload, so correcting a landmark instantly re-derives everything that
leaned on it, and there is no repair job because there is no state to repair.

The join is deliberately narrow. Markers are small, explicit pattern sets — a
sibling's birth in the same sentence vetoes the birth join outright, and a
free-text anchor that names nothing in your landmark index derives nothing at
all. **A miss is fine; a wrong join is not.**

**How ordinary stories teach later stories** (v307,
[ADR 0036](../adr/0036-incremental-timeline-evidence-links.md)). Event extraction
is stable; when independent timeline evidence changes, the classifier receives
only exact event-key link deltas. Each event records whether it linked, lacked
evidence, was ambiguous, had an incomplete search, or was not temporal. A direct
date or age joins independent authority only when exact source words prove the
date or age and the event's subject. A contextual placement never does. Search
is per event, includes every same-entity competing stay or role, and ignores
generic owner references, so a narrow River House reference is not crowded out
by many unrelated owner facts. Correcting only an anchor's bounds updates linked
events through the deterministic fold without another model call. Named-person
age arithmetic requires that person's own birth; it never borrows the owner's.
When a calculated node's status-bearing claims agree, the published node carries
their `timeline_resolution_status`. Incomplete and non-temporal events therefore
remain visible with their source evidence, while timeline readers can keep them
out of the missing-date count without inferring meaning from an absent question.

**How organised is it** (v208, [ADR 0027](../adr/0027-the-placement-score.md)).
The owner asked for a level — *how placed is this life, 0 → 1* — and already
had the margin: the star's *"one answer would place 53 things"*. They turned
out to be one arithmetic. `timeline.unknown_width` has ranked the Reading
Room's plan on interval width since v204, because a threshold count is not
submodular and a width-sum is; the level is that same sum, normalised:

```
score = 1 − Σwᵢ / (n · L)
```

over every thing the timeline holds — placed moments, unplaced moments, eras,
place spans — where `wᵢ` is the width in years of the interval that thing
currently occupies and `L` is the life span. A dated thing contributes its own
interval; an undated one contributes `unknown_years`, the ONE definition of
"the interval this occupies absent an answer" that the score, the chart's cloud
and the ghost all read.

Four things about that number are not optional.

**It scores width, never presence.** A meter that asks *does this field have a
value?* is an improper scoring rule in Gneiting & Raftery's exact sense — it is
maximised by writing anything down, true or not. A width score is not, because
the ladder refuses to record a narrower interval than the person can hold and
stores a hedge as a *wider* one with a weaker confidence. **Guessing cannot
pay.** And the score is downstream of the never-propose-a-date rule: it does
not police itself, and it is only honest while that rule holds above it.

**It is a floor.** Marginal width sums measure the smallest box containing the
possibilities, so a well-ordered but loosely-bounded life reads as more
disorganised than it is — by 3× in the worked case in the research. The copy
says *at least this organised*, never *exactly*, and `caveat_floor` stays
`True` until the concurrent-flexibility correction lands.

**It comes as a pair.** `score_stated` recomputes with every derived record
read as undated, so the cross-dating pass moves `score` and **cannot** move
`score_stated`. That is the documentary editors' italic convention expressed as
two numbers, and it is what stops derivation from flattering the person's own
work.

**It is banded, and it is not a verdict.** `band` is 1–5 on fixed thresholds —
arbitrary, stable, documented as such, never peer-relative, because there are
no peers in a private vault. One measure shown alone is treated as the thing
itself; a banded chip beside other readings is not. And the number is scoped to
what the timeline can *order and place*: it is never a score for the life.

With **no birth landmark there is no score at all** — no life span, no floor
for a thing nothing can bound, no honest denominator. The block is simply
absent. That is correct, and it is why `birth` wears the ★.

**The strip.** `per_year_band` gives one row per calendar year: each thing
contributes `min(1, 1/wᵢ)` to every year its interval covers, normalised by how
many things cover that year — the aoristic weight, uniform prior, from crime
mapping by way of archaeology. A day-pinned thing contributes ~1 to its year; a
decade-wide thing ~0.1 to each of ten. This is the half that answers Crema's
summation problem: five moments smeared over five blocks and five pinned inside
those blocks sum *identically*, and the strip tells them apart. An empty year
reads `0`, honestly — a flat stretch means nobody asked, which is coverage, not
biography.

**The margin.** `next_gain` is the top row of the existing greedy plan,
re-expressed in score units: the level recomputed with that anchor's resolve
set collapsed to the anchor's own grain — one year
(<!-- parity: timeline.ANCHOR_GRAIN_YEARS = 1.0 -->`ANCHOR_GRAIN_YEARS`), the
coarsest thing the ladder accepts as *placed* — minus the level now. It runs
the same arithmetic over a copied population, the way the filing beat runs the
pass itself rather than guessing at it, so the margin can only claim what
answering will actually deliver.

**The ghost's honesty note.** Every dated moment carries `prior_span`, what its
interval would be absent its date, stamped on the pass's own walk so stated and
derived moments alike have it. Nothing is stored — so when an era's own dates
improve, the old ghosts *tighten* on the next read. The ghost is today's honest
reconstruction of "before", not a historical screenshot. That is the trade
statelessness buys, and it is said out loud rather than fixed by keeping
history nobody asked us to keep.

**What answering one thing is worth.** Every unknown row now carries
`resolves` and `leverage` — the other unknowns the anchor this row would
*become* would also place, and `1 + len(resolves)`. A row with no reach is
exactly 1, because answering it still places itself. That is the **glow**, and
its ranking is deliberately not computed here: the package gives raw numbers
and the host quantiles them. A keystone's `gain` is a different number and
stays one — display reach against marginal plan value.

**What happens when accounts disagree.** Nothing is overwritten.
`chronology.reconcile` scores every claim by its basis, its confidence, and
how many independent sources corroborate it, and returns the best-supported
one *plus every alternate*. The page renders the best-supported interval and
links the others. A disagreement is data about how you have made meaning of
your past, not a bug to fix.

Since v222 that is true of the landmark store too, and it was not before: a
landmark entry merged the ordinary way, so a date you stated in March was
overwritten in April by one the system worked out from an age, with nothing
left to show you had ever said it. All three landmark dates now go through
`reconcile` and keep what they beat (`landmarks_interaction.landmark_date`).
Telling us the same thing twice does **not** make a second claim — repeat
tellings fold, and the extra source counts as corroboration. Telling us
something *finer* — "June 14th" after "2001" — replaces rather than fights
the coarser claim, because a refinement is not a rival.

**How the spine gets its order.** Dated eras anchor at their earliest year;
undated eras are interpolated between their nearest dated neighbours in the
old order; the result is dense-ranked into `chrono`. With nothing dated, the
order is exactly what it was before v195.

**How a hole becomes a question.** Every hole the timeline computes becomes an
unknown ABOUT SOMETHING — *the dog that followed you home*, *when the Yucaipa
years ended*, *the stretch between two dated eras* — and its probe names that
subject and hangs it on a landmark you already gave: "Dad lost the truck keys
while camping — was that before or after the move to San Diego?" Press Play and
the `timeline` interaction opens on that question, then climbs the ladder only
while it stays cheap, offering bounds rather than demanding points, and
stopping the moment the answer is good enough for that unknown's slot. If you
say you will find out, that is simply your answer: nothing is filed, nothing is
remembered, and the unknown keeps its place.

**The spine and the resolver (v314).** The three doors above are joins:
an exact label, an exact quote, a candidate list built by rules. Every join
that failed used to become a question for the owner, which is how a vault
that plainly says when a company was founded still asked *"when was the
founding?"*. The owner's ruling: *if you can answer this from the vault, so
should the system, and once answered it must never be asked again.* So the
loop is now, on purpose, one simple thing — **a model resolving and
calculating placement against a spine**:

- The **spine** (`resolver.spine`) is the set of dated facts every question is
  read against: birth and the **age table** it implies (`resolver.age_table`,
  every age → a date range, for any birthday), stays, tenures and schooling
  as intervals, dated points, people. It is **generic first** — any lifetime
  has this shape and a birthday alone fills the age table — and the person's
  **landmarks** and **keystone** answers make it specific. That is what a
  landmark is *for*: each one improves the spine, and the next run reads the
  whole vault against the better spine.
- The **resolver** (`system/resolver.py`) indexes every source, answer,
  landmark and fact (SQLite FTS5, rebuilt per run), shows the model one story
  at a time with the spine, the passages retrieved for that story's events
  and the events still undated, and asks for a date or range with a basis,
  citations and — only when the vault cannot tell — the one question that
  would settle it. Bare age handles resolve from the age table without a
  model call.
- **Whose moments it plans** (v324, unchanged by v334): the ones on the
  owner's axis by the EVIDENCE test —
  `occurrence_subject_scope == "owner"`, or any relation in
  `temporal_projection.AXIS_RELATIONS`, which is how a grandparent's death
  told as *"when I was in 9th grade"* (`other_person` / `lived_effect`) is
  dated from the owner's own school spine. A `contextual_only` node — a
  relative's own milestone, family history from before the owner was born —
  is never planned: nothing in this vault dates it. v334 draws more rows on the
  axis than this test plans (see below) and deliberately did not widen the
  resolver: a `family` row is drawn, not newly dated from his spine.
- **Whose moments are DRAWN on the axis** (v334, owner ruling 2026-09-23):
  every node publishes `axis_membership` (`owner` | `family` | `none`) and
  `axis_membership_reason` (`lived` | `immediate_family_in_lifetime` |
  `pre_birth` | `not_family` | `subject_unresolved` | `relationship_unknown`),
  derived at fold time by
  one pure rule (`system/axis_membership.py`) from the person roster's
  `relationship` field and the owner's birth date — never from a judgement
  about who the words say was present. He lived it → his axis, whoever else it
  is about. An immediate family member's own event during his lifetime
  (spouse/partner, parents, siblings, grandparents, children, grandchildren) →
  his axis, drawn as a moment about them. Anyone else's own event, and
  anything before his birth → not on his axis; it stays in the substrate and on
  that person's page, and it mints no owner-axis date question unless something
  else is anchored to it. Those two — `not_family` and `pre_birth` — are the
  ruling's only DECISIONS
  (`temporal_projection.AXIS_DECIDED_OFF_AXIS_REASONS`), and only they suppress
  anything. A subject nobody has identified (`subject_unresolved`) and a person
  nobody has said is family or not (`relationship_unknown`, v338: a roster row
  with no `relationship`, or a name the roster has never heard of) are also
  `none` — not drawn until somebody says who this is — but they KEEP their date
  and identity questions, because nothing has been decided about them. **The "About someone else" group is retired**: hosts
  read the field rather than inferring a surface from `contextual_only`, which
  keeps every value it had. ADR 0030's 2026-09-23 amendment has the ruling in
  the owner's own terms. **The owner's age table
  is never applied to another person's age.** It answers how old the OWNER
  was, and an answer that reads somebody else's age off it is refused
  mechanically (`subject_age_not_owner`), in the model lane and in the
  bare-age arithmetic lane alike.
- **It revisits, aims, and estimates** (v325). A newly filed story re-opens
  the settled unknowns it bears on — the moment the message's own
  conversation was answering (`session_ref` names the work item), and every
  unknown whose retrieval query now returns a passage of the new story — each
  once per story, with the new passages first in its prompt and its story
  planned right after the one just told. The story's own prompt lists those
  open questions, and an answer may return `handle_binds` ("this moment's
  unresolved handle names THAT node"), which files a `relative_order` claim
  anchored on the node id and retires the raw handle, so the fold places the
  moment through an ordinary edge and the `missing_anchor` card leaves. And
  whenever the vault genuinely cannot tell, the answer carries an `estimate`
  — a bounded stretch with the lines it rests on — verified mechanically
  (parseable, ordered, closed, never before the birth), kept in the ledger
  beside the question and published as the node's and work item's
  `probable_window`. An estimate is never a claim: the score, the strip and
  the derivation do not read it; the page floats the dot over it and draws
  its height as the window's width. A wide range the resolver itself filed is
  re-asked once when an exact date arrives and only a narrower verified
  answer replaces it; `python3 system/resolver.py --vault-root <root>
  --estimate-missing` backfills the windows once (the module's own entrypoint —
  `lifehug.py resolve` does not forward this flag). See ADR 0037's v325
  amendment.
- **It is not asked for what "recent" already says** (v333, owner ruling,
  2026-09-23). A moment the person called recent in a telling the vault knows
  the capture date of is PLACED, not estimated: `chronology.RECENCY_RUNGS` is
  the one recency vocabulary and `classifier_claims` reads it into a stated
  range ending at the capture date, so the moment arrives on the timeline as
  *placed by you* and the resolver never plans it. A node that IS placed no
  longer carries a probable window beside its real interval — an estimate is
  never a placement, so it is never drawn as a second answer to a settled
  question.
- **A date card is minted only when narrowing would change something** (v333,
  owner ruling, 2026-09-23). An ordering constraint or a contradiction, a
  decade or age-frame boundary the interval straddles, another placement
  waiting on it (`resolves` non-empty), or a real life event — any one of
  those and the card stands. A freestanding anecdote already placed inside
  about a year gets no card at all: *"higher fidelity can happen later on the
  timeline, ideally not at all."* One predicate,
  `temporal_work_items.date_card_changes_something`, applied in the fold and
  again where the probable window is known. A question may still ask for
  higher fidelity when that would settle many things, and its wording may
  name the grain it needs.
- **A day is asked only of a cornerstone** (owner ruling, 2026-09-25, ADR
  0038). *"We almost never need more than month precision except for
  extremely important dates like birth, death, wedding, divorce."* Every date
  card carries `requested_grain`: `day` for a cornerstone — missing, or held
  coarser than a day, and that card keeps its stakes whatever the gate above
  says; `year` for a cornerstone-type event about somebody outside the set
  (*"When did your sister get divorced?"*), asked once, accepted at any grain
  and never pressed; and never finer than `month` for anything else. Leverage
  raises a card's rank, never its grain
  (`temporal_work_items.A_DAY_IS_ASKED_ONLY_OF_A_CORNERSTONE`). A day worked
  out by arithmetic is DISPLAYED as its month
  (`chronology.A_WORKED_OUT_DAY_IS_SHOWN_AS_ITS_MONTH`); the stored interval
  keeps it. A marriage is drawn as a span that opens on the wedding
  cornerstone and stays open while married
  (`temporal_timeline.A_MARRIAGE_IS_A_SPAN`).
- **A place mention is an outer bound** (v360 follow-up, owner 2026-09-25,
  `timeline-rules:23`). "In Arizona" bounds a moment by his Arizona stays and
  the moment's other evidence narrows it — the event its own handle names, his
  age, a span — never across a gap between stays
  (`temporal_timeline.A_PLACE_MENTION_IS_AN_OUTER_BOUND`). A house he lived at
  twice spans both stays minus the gap, and one place never asks "which time?"
  (`A_HOUSE_LIVED_IN_TWICE_SPANS_BOTH_STAYS`). "Dad's house" is a relative
  place, never a residence (`landmark_identity.A_RELATION_WORDS_HOME_IS_A_RELATIVE_PLACE`).
- **An estimate is capped at about five years**
  (`resolver.AN_ESTIMATE_WIDER_THAN_FIVE_YEARS_STAYS_A_WINDOW`): a wider one
  stays the probable window and is asked about only when hot
  (`temporal_publication.A_WIDE_ESTIMATE_IS_ASKED_ONLY_WHEN_HOT`).
- **An estimate is not guessed again** (v361, the A14bc churn of 2026-09-26).
  A moment the resolver placed by its own estimate is never planned again by
  the vault-wide ordering; only a new story that carries a date, or the
  person's answer to that moment's card, re-opens it
  (`resolver.AN_ESTIMATE_IS_REVISITED_ONLY_BY_A_DATED_STORY`). A standing
  estimate is replaced only by a verified answer, by an estimate read from that
  new dated evidence, or by a window materially narrower inside it — a
  different month guessed from the same undated story files nothing
  (`resolver.A_GUESS_NEVER_REPLACES_A_GUESS`). A plan item files only against
  the ledger rows it was planned from, so two hosted chains that planned the
  same moment file it once (`resolver.A_PLAN_IS_FILED_AGAINST_THE_LEDGER_IT_READ`),
  and a re-ask that comes back silent leaves a settled reading exactly as it
  stood (`resolver.A_SILENCE_NEVER_UNSETTLES_A_READING`). An answer to a card
  that names one date inside a sentence — *"her freshmen year January 2026"* —
  is that date (`answer_placement.A_DATE_HE_SAID_IN_A_SENTENCE_IS_A_DATE_HE_SAID`).
- **Verification is mechanical**: every cited quote must occur in the cited
  passage, every date must parse, ranges must be ordered, a `derived` answer
  must cite the spine fact it came from. What fails files nothing.
- **Filing is a claim like any other**: a `date` claim on the moment's own
  node under `resolver/rule:3`, declared on the classifier's telling, the raw
  handle superseded. The fold, the projection and the page treat it as
  durable, dated and correctable.
- **Memory**: `state/resolver/resolutions.json` records every outcome —
  resolved, unverified, unknown with its question — so nothing is asked or
  bought twice. New information re-opens a question; a clock never does.

The resolver never dates a residence episode (two stays that look alike are an
identity problem), never edits a source, and lets owner statements outrank
inference with the latest dated correction winning. It runs after every
accepted classification batch (`classification_refresh.run_batch`) and by hand
as `lifehug.py resolve --execute`. (`--eval`, which answers known-answer
questions without filing, is on `system/resolver.py`'s own entrypoint and is not
forwarded by the wrapper.) Since v316 that run is also available as two halves a
host can run apart — `lifehug.py resolve --plan --out <file>` writes the prompts
it would buy and touches nothing in the vault, `lifehug.py resolve
--from-response <envelope>`
files the answers that come back (refusing any whose story has changed since,
or — v361 — whose moments another filing has answered since),
and a card carries the resolver's own proposed question rather than the
generic one. Since v317 the resolver can also answer that a listed moment is
**not an event** — an anticipated future milestone, a conversation about the
data itself, a bare statement of a fact, or a restatement of a moment already
dated — and files that verdict as a dated retraction, so the moment leaves the
page on the next publish instead of becoming a card nobody can answer.

What is *not* a landmark never becomes a node in the first place (v317): a
`none` or skipped answer completes its domain and draws nothing, and a `work`
or `schools` record that names no organization is refused at filing rather
than drawn as a tenure. Design and consequences:
[ADR 0037](../adr/0037-the-spine-and-the-resolver.md).

### The laws that protect the drawing

Deciding two tellings are one event, and deciding a landmark entry no longer
stands, are both *destructive* readings: get them wrong and a dated moment
leaves the page silently. Each of the following is one named constant with one
seat, added because a real vault lost something real, and each is guarded by a
test that reproduces the loss with the guard removed.

| Law | Constant | Seat | What it refuses |
|---|---|---|---|
| A merge never moves a dated moment (v340) | `episode_binder.A_MERGE_NEVER_MOVES_A_DATED_MOMENT` | `R2c`, `R2d` | a pair whose **stated** dates contradict, *and* a pair whose dates the **fold already has them at** contradict — the second half is what two *"Family moved to Yucaipa"* 32 years apart needed, since a moment placed by containment states nothing of its own. `R2a`/`R2b` are deliberately ungoverned: two readings of *one fact* disagreeing about its date is the contradiction a fold exists to surface, as a card naming both dates with the loser kept as an alternate. |
| An alias never names a node the drawing publishes (v342) | `episode_fold.AN_ALIAS_NEVER_NAMES_A_NODE_THE_DRAWING_PUBLISHES` | `EpisodeIdentity.plan_carries` | a redirect to one of the two things an undiscriminated id means. A claim **follows** the node it folds under; a leftover whose own date contradicts the merge does not follow, and a key some claim still holds is dropped from the table entirely (`identity_node_alias_contested`). Checkable in one line: no key of `node_aliases` is the id of a node the drawing publishes. |
| A stated entry is never retired by shape (v349) | `landmarks_interaction.A_STATED_ENTRY_IS_NEVER_RETIRED_BY_SHAPE` | `entry_superseded_by`, `timeline.save_landmark` | retiring an entry for the fields it happens to carry. Only a demonstrable machine-collapsed aggregate counts, the readable set is **derived** from the writer rather than hand-listed, **provenance outranks shape** (an entry with its own promoted source is never retired by rule 3), and **one answer is one entry** — a record that would retire more than one prior entry retires *nothing* and says so (`SUPERSESSION_FAN_OUT_LINT`). A `none` is exempt: retiring the whole domain is what *"I never served"* means. The record itself always files. |
| Answering a card places its moment (v352) | `answer_placement.ANSWERING_A_CARD_PLACES_ITS_MOMENT` | `place_answers`, `landmark_recorder.file_claims` | reading a reply as if nobody had asked it anything. A reply promoted with `session_ref: conversation:cand:work_item:<id>` is an answer to THAT work item: the time it carries becomes a claim on the node the card is about, its subject is the **node's** and never a pronoun in the reply, and a reply with no time at all is still filed as a **telling** of that node, so the card stays open with the owner's words on it and never silently nothing. The rungs are `chronology`'s own, in `classifier_claims.temporal_reading`'s order — a stated date, a stated age, a recency cue against the reply's own capture date — plus one closed vocabulary, `AGE_PHRASE_RES`, because `parse_age` over prose reads *"March 1998"* as age 8. |
| An episode node's kind is the node's, not its first claim's (v353) | `episode_fold.AN_EPISODE_NODES_KIND_IS_THE_NODES_AND_NOT_ITS_FIRST_CLAIMS` | `EpisodeIdentity.episode_of`, `_group_claims`, `EpisodeIdentity.node_block` | reading *"is this node an episode?"* off whichever claim was read first. An episode's node id carries `node_kind: episode` inside its own digest, so a group drawn at that id **is** that episode whatever its claims say — and one reading of it, asked of the node and shared by the grouping and the episode block, is what stops the fold drawing a node the projection must refuse. A **telling** of an episode is ordinary and is not refused (the reply really is another telling of it); whether it is the same event stays the binder's decision, so the episode's member list is untouched. The draw also fails **soft** for this one class — `temporal_projection.EPISODE_BLOCK_ON_NON_EPISODE_NODE` is repaired and reported as `episode_node_kind_redrawn`, never raised — because `publish` raising parks the hosted compile job and stops the vault updating for *everything*. |
| A reading is only superseded by the same reader (v354) | `temporal_store.A_READING_IS_ONLY_SUPERSEDED_BY_THE_SAME_READER` | `temporal_store._fold` step 1, `temporal_claims.extractor_identity` | one reader's reading retiring another's. The fold elects ONE winning receipt per group and marks the rest `superseded / reextracted`; the group was `(source_id, revision)`, so v352's `answer_placement` receipt — written on the promoted **reply itself** — won the group on every message the `general_listener` had already read and retired that whole reading. It cost the owner's vault `claim:36bae1eb0bbfd2120274471d`, a 2006 `graduation`, and with it `node:091ec8a898daa8548afaf104` and its placement (lifehug#409). The unit is now `(source_id, revision, extractor identity)`: WHO read it is the **name** at the head of the extractor version (`temporal_claims.AN_EXTRACTORS_NAME_IS_WHO_READ_IT`), everything after it is which VERSION of that reader did the reading. A prompt edit, a new model or a bumped rule version still supersedes — that is what supersession is for — and two readers of one message coexist, which their **claims** already did (`CLAIM_IDENTITY_KEYS` carries `extractor_version`). |
| A gendered word when it is known (v358) | `relation_words.A_GENDERED_WORD_WHEN_IT_IS_KNOWN`, `relation_words.A_CARD_ONLY_WHERE_THE_WORD_HAS_A_GENDERED_PAIR` | `temporal_publication._with_relation_words` (publish and verify), `answer_placement.place_answers`, `landmark_recorder.file_claims` | asking a person page anything, and asking about a word that has no gendered form. The projection publishes `relation_words` — one row per roster person with a relationship: the neutral word, the gendered word when the owner has said it, the neutral plural — and at most ONE `relation_word` card per real named person whose relationship has a gendered pair and whose word is unknown: *"Is Harvey your son or your daughter — or would you rather keep “child”?"*, Timeline surface only, no node, priced below every dating card (`WORK_ITEM_VALUE_DEFAULTS`), never for an alias row (`maps_to_focus`), a collective or role row, the owner, or a friend/colleague/`other`. The reply files through the ordinary card-answer path into the roster field and the card is never minted again. A display decision over the same generation: `CALCULATION_RULE_VERSION` does not move; `relation_words.RELATION_WORD_RULE_VERSION` joins the publication fingerprint. |
| An answer outlives its card (v359) | `answer_placement.AN_ANSWER_OUTLIVES_ITS_CARD`, `answer_placement.NARRATOR_AGE_RE` | `answer_placement.card_for_work_item` (read by `place_answers` and `landmark_recorder.file_claims`), `closed_cards`, `temporal_work_items.asked_work_item_ids` | voiding an answer because its card closed after it was shown. On the owner's vault 20 of 28 card answers were refused `card_not_published` because the resolver had dated the node, or the node had re-keyed, before the answer was placed — his *"19-21 years old"* for his father's mission among them. A card the generation no longer carries is RE-DERIVED from what it asked: a work id is `derive_work_item_id` over (kind, subject, node, field), so the ids every drawn node, every `node_aliases` key and every node a filed claim names could have been asked under are arithmetic (with the raw `subject_mention` a card was minted from before its subject resolved), and the answer is placed on that node where it is drawn now, under the node's own subject. Refused only when no node could have asked it (`card_not_published`) or its node is no longer drawn (`card_node_not_drawn`), and every refused answer is listed on the report (`unplaced`). An `offered` card is answerable; a row marked settled is still `card_not_open`. A first-person age (*"when I was 4 or 5"*) is the narrator's, filed under `self` on the card's node — never measured from the node subject's birth. `CALCULATION_RULE_VERSION` does not move. |
| Nothing to bind costs nothing (v348) | `episode_binder.NOTHING_TO_BIND_COSTS_NOTHING` | `bind_episodes` | deriving a plan a receipt already holds. `BINDER_RECEIPT_SIGNATURE_FIELDS` is the six fields a receipt and a fresh signature must agree on — three content digests (`telling_digest` over the telling manifest, `bindings_digest` over the binding and operation stores, `landmark_digest` over the filed `sources/landmarks/entry-*.md`) and three versions (`rule_version`, `calculation_rule_version`, `framework_version`) — checked against a receipt of the matching `BINDER_RECEIPT_SCHEMA_VERSION`. Any difference is the full pass. A vault with no telling manifest has no cheap signature and always takes the full pass: a missing manifest is *unknown*, never *nothing new*. |

**The five ways a node id moves.** A node id is derived — from the episode, the
event kind and the subject — never assigned, so a reading that changes any of
those moves the id while every work item, session and URL still names the old
one. All five publish a redirect under the second law, and all five report it:

| # | Cause | Reported | Release |
|---|---|---|---|
| 1 | a **bind** re-keys the node a telling folds under | `node_aliases` (Law 5 of the identity design) | v342 |
| 2 | the fold **minted** an id for a telling the I0 contract cannot see | `identity_node_alias_followed` | v342 |
| 3 | an episode **absorbed** by a merge takes a new episode id, and a node id derives from it | `episode_aliases` composed through `node_aliases` | v342 |
| 4 | a **landmark redraw** changes what an entry's date dates | `landmark_date_kind_redrawn` | v345 |
| 5 | an **identity re-key** — a subject that newly resolves | `identity_subject_rekeyed` | v350 |

Three refusals are shared: a claim carrying its own `event_ref` never moved (its
id was never derived), a former id two claims disagree about the destination of
is dropped whole, and a map that would be a chain drops both ends. The identity
layer's own tables win a collision with a redraw, because a person's decision
outranks arithmetic. The full amendment history is
[the I0 fold contract](../contracts/event-identity-i0-fold.md).

## 4. The algorithm

**The elicitation ladder** (`timeline_interaction.PLAYBOOK_STEPS`), in order,
from `system/research/chronology.md` §6:

| Rung | Probe | Why it is here |
|---|---|---|
| 1 content | what happened | dating is inference from context; the context comes first |
| 2 residence | where were you living | lifetime periods are indexed by place (Conway & Pleydell-Pearce) |
| 3 role | what work were you doing | the other half of that index |
| 4 parallel domain | what else was going on | Belli's parallel retrieval, when one domain stalls |
| 5 sequence | before or after X | relative order survives when dates do not |
| 6 landmark | had X happened yet | personal landmarks bound as well as public ones (Loftus & Marburger) |
| 7 season | what was the weather doing | seasons are recalled when months are not |
| 8 bounds | one stretch, or "somewhere in a couple of years"? | two bounds beat one guess |
| 9 convergence | that's enough to place it | the stop rule |
| 10 defer | find out whenever you like | never a nag |

Rungs 5 and 6 are skipped when the person has supplied no landmark yet. The
ladder stops early whenever the precision already reached is at or finer than
the unknown's target: a year for an era gap, an era for a thin lineup. It also
stops after two probes that add no new bound, and at a hard ceiling of four
probes — dating is never worth the relationship.

**Leverage — the promise and the delivery are the same join** (v205). Anchor
candidates are a period's start/end, a dated landmark event, and an entity's
arrival. A period anchor resolves that period's own bounds, every `era_gap`
touching it, and — through cross-dating's containment rule — every undated
moment inside it; a place resolves its own span and the moments its sources
cite. Two pre-v205 claims are gone because they were fictions: a **dated
event** no longer claims its undated neighbours (a point is not a span), and a
**person** no longer claims the moments sharing its sources (an arrival bounds
nothing). The MOMENT half of every resolve set is now computed by
`cross_dating.derivable_moments` — the pass's own rule read backwards — so the
number on the star is the number that dates on the next read. Leverage is the
size of that set, and keystones are the top two by leverage then by how cheap
their probe is. A keystone becomes a QUESTION in exactly two ways, both matched by its own
identity `tl:<anchor-slug>` — the week's whisper on an arc card, and a minted
bank question when its leverage clears `timeline_leverage_per_story` (6), the
one dial. That number is an exchange rate: how many unknowns one answer must
place to be worth one ordinary story answer, and it sets both the mint cutoff
and the minted question's weight in the queue's own objective currency.
<!-- parity: question_planner.DEFAULT_LANE_POLICY["timeline_leverage_per_story"] = 6 -->
Adjacency is gone: a bank question whose focus merely resembled a keystone is
not a keystone and is never starred.

**The cross-dating pass, and where placement sits inside it** (v207, split in
v254). `cross_date_moments` runs first, **before** anything is placed: it is
every rung that needs no era — a definitional anchor, an age statement, a
place's containment — and it exists so that placement's own first rung, *dated
→ frame arithmetic*, has a date to read. Then moments are placed. Then
`cross_date` runs the rungs that need to know which era a moment is in: band
spans, then the moments those newly dated bands now bound. That last sweep is
the *same* idempotent one — a moment already carrying a date is skipped — and
there is no cycle, because a date derived from an era can never move the moment
out of the era it was derived from. `timeline_data` re-runs `derive_chrono`
whenever a band was derived, so a filed landmark improves the spine's **order**
on the same read it improves the dates. The two halves report one set of
counts. The band ladder's own order is `cross_dating.BAND_RULES`.

**A worked example.** Your birthday is 12 April 1979. You say a letter arrived
when you were "about five". `parse_age` reads `(5, 5, hedged)`; the hedge
widens the window a year on each side; `from_age` returns
`best 1984~, earliest 1983, latest 1986, granularity range, confidence
approximate, basis age, anchors ("birth",)`. The page shows a chip reading
"around 1984", and the conversation says: *"About five puts that somewhere
around 1984, give or take a year — does that feel right?"* If you then say it
was definitely before you moved to Mesa, `from_anchor` gives `../1984` and
`intersect` tightens the interval to 1983–1984 without either claim being
thrown away.

## 5. In the loop

Per answer, classification records any explicit date claim and the event's
title; since v314 the resolver then reads that story against the spine and
files whatever the vault can already answer, so the only questions that
reach you are the ones the vault cannot settle. The timeline is recomputed on every read and written to
`wiki/timeline.md` on every compile, so a new answer's dates appear
immediately. Since v205 the **cross-dating pass runs inside that same
recomputation**, which is why answering one landmark question visibly moves
dozens of moments on the next page load and why nothing has to be re-run,
migrated, or repaired when a landmark is corrected. Weekly, `timeline-retire` retires display pins the classifier has
caught up with, and `planner-queue` mints the earned keystones through a
guarded read that degrades to "no keystone questions" rather than ever
breaking the queue.
Playing an unknown writes through the path that already existed —
`timeline-place` files a dated correction source into the archive and saves
the display pin — so a placement teaches the loop exactly as it always did,
on demand instead of at three whispers a week.

**One key, minted and joined (v215).** A placement's identity is
`timeline.placement_key` — `sha1(source + "\n" + description)` — and it is
both the mint and the join. A pin is stored under it and
`timeline.resolve_placements` is the only thing that pairs a stored pin with a
live moment. Because an unknown row is *named* by the moment's title, a host
filing from conversation once minted from that title against a join expecting
the description: the record landed in `stale_placements` and rendered nowhere,
with exit 0 (lifehug#228). So identity now travels whole — an unknown row
carries its moment's own `placement_key`, `place_invocation` passes it as
`--placement-key`, and the CLI stores it verbatim. `resolve_placements` also
re-joins the pins the old recipe orphaned, deterministically and at read time:
no migration, no state file, no model call, and never a guess when two moments
share one legacy key. Anything that still joins nothing stays in
`stale_placements` and is counted at `counts["stale_placements"]`, with
`counts["placements_rejoined"]` naming what the repair rescued on that read.

**A pin survives its moment's reclassification (v253).** A content key is only
as stable as the content, and rewriting a moment's description is `classify-story`'s
ordinary weekly job — so every reclassification used to orphan the pin of every
moment it touched: the person named a date, the date was on disk, and the moment
rendered undated (lifehug#276). `resolve_placements` therefore has a **third
rung**: a stored key that joins nothing, whose row's own `source` mints exactly
one live moment, re-keys to that moment. Zero candidates or several and the rung
does not run — the row stays orphaned under the named diagnostic
`placement_orphaned_ambiguous` (`timeline_data()["placement_diagnostics"]`,
counted at `counts["placements_orphaned_ambiguous"]`), because filing the
person's date onto the wrong moment is worse than leaving it stranded. Rung 3 is
also the only rung whose repair is **durable**: `rekey_orphaned_placements`
rewrites the row's key with `rekeyed_from`/`rekeyed_at` provenance, seated in the
weekly `timeline-retire` pass that runs right after `classify-story` — the read
heals immediately, the store heals on that pass, and replaying it is a no-op.
Rungs 1 and 2 still leave the stored key exactly as v215 pinned it. At the
filing end, `timeline-place` refuses an explicit `--placement-key` that no live
moment mints (`placement_key_not_live`) rather than writing a pin that is dead
on arrival.

**A minted question retires when its gap leaves the projection (v319).** A
timeline question is minted from one week's projection and lives in the bank
until something closes it, and until v319 the only thing that closed it was an
ANSWER. Under the spine-and-resolver loop (ADR 0037) that is no longer how a
keystone usually ends: the resolver reads a story against the spine, places the
moment itself, and the next publication simply does not carry that keystone,
that landmark opportunity or that work item any more — so the row stayed
pending and the person was asked *"When was move to Yucaipa?"* about moves the
vault had already placed (lifehug#368; 22 stale rows on the founder's vault).
Now every `timeline_candidates` build compares each pending row's
`timeline_probe:` identity — the `tl:`/`lo:` id, the `work_item:` marker, and
the anchor — against the identities the CURRENT projection still carries, and
checks off the ones that are gone with the reason beside them: `*(2026-09-19 —
retired: placed by the resolver (work item gone from the projection))*`. Nothing
is deleted, an answered row and the owner's own dismissals are never touched,
and a vault with no published projection retires nothing at all, because absence
of evidence is not evidence of absence. The pass runs where the bank is already
being read — `planner-queue` (before the mint, and the rebuilt
`state/question_queue.json` drops the rows it just retired) and the end of a
publication whose work-item set actually moved — and an operator can run it by
hand with `lifehug.py timeline-candidates --retire-stale`.

Weekly too, `arc-plan` reads `place_no_stories` off the same assembled
payload and plans a **place aside** onto a card whose gap slot the whisper
left empty (v200). Nothing is written: a place stops being a gap the moment a
moment lands in it, which is the recomputation `timeline_data()` already does
on every read.

## 6. Where it lives

The `system/timeline.py` rows below name the legacy projection; per the note at
the top (owner ruling R4, 2026-09-03) they move into the calculated projection
in Cuts 2–5 and this table is rewritten at Cut 7b.

| Concern | Location |
|---|---|
| The date primitive | `system/chronology.py` |
| The cross-dating pass | `system/cross_dating.py` (`derive`, `cross_date`, `derivable_moments`, `stamp_prior_spans`) |
| The placement score and the interval it counts | `system/timeline.py` (`placement_score`, `unknown_years`, `unknown_anchor`) |
| The model, bands, unknowns, leverage, keystones | `system/timeline.py` |
| The same leverage/resolves and keystone plan over the CALCULATED graph (v284) | `system/timeline_gain.py` |
| Landmark opportunities and sufficiency over that graph (v286, ADR 0032) | `system/landmark_opportunities.py` |
| Corroboration windows | `system/timeline_corroboration.py` |
| The elicitation | `interactions/timeline/`, `system/timeline_interaction.py` |
| The classifier's claim | `system/classify_story.py` (`events[].title`, `events[].date`) |
| The export and page frontmatter | `system/wiki_compile.py` (`compile_timeline`, `frontmatter(date_edtf=…)`) |
| The viewer | `system/serve_wiki.py` (`view_timeline`) |
| The write path | `lifehug.py timeline-place ... [--date] [--basis] [--anchor] [--placement-key]`, `system/jobs.py` |
| Placement identity (mint, join, repair) | `system/timeline.py` (`placement_key`, `legacy_title_key`, `resolve_placements`) |
| Plan a timeline Play | `lifehug.py arc-plan-target --timeline [--era <slug>]` |
| Durable state | `state/timeline_placements.json` |
| The claim substrate and its fold | `system/temporal_store.py` (`write_receipt`, `fold_active_index`, `rebuild_active_index`) |
| The fold that groups claims into nodes, and its rule version | `system/temporal_timeline.py` (`CALCULATION_RULE_VERSION`, `_group_claims`, `_births_by_subject`, `_identity_rekeys`, `_landmark_redraw_aliases`) |
| The projection's shape, its kinds and its work items | `system/temporal_projection.py` (`PROJECTION_SCHEMA_VERSION`, `WORK_ITEM_KINDS`, `WORK_ITEM_STATES`, `derive_node_id`) |
| What an answer to a card means | `system/answer_placement.py` (`ANSWERING_A_CARD_PLACES_ITS_MOMENT`, `AN_ANSWER_OUTLIVES_ITS_CARD`, `work_item_of_session`, `card_for_answer`, `closed_cards`, `answer_reading`, `NARRATOR_AGE_RE`, `aim_at_card`, `place_answers`); seats `classifier_claims.migrate_classifier_moments` and `landmark_recorder.file_claims`; verb `place-answers [--dry-run] [--source PATH]` |
| Whether a node is an episode, and what the draw does with a bad shape | `system/episode_fold.py` (`EpisodeIdentity.episode_of`, `AN_EPISODE_NODES_KIND_IS_THE_NODES_AND_NOT_ITS_FIRST_CLAIMS`), `system/temporal_timeline.py` (`_node_dict_or_finding`, `DIAGNOSTIC_EPISODE_NODE_REDRAWN`), `system/temporal_projection.py` (`EPISODE_BLOCK_ON_NON_EPISODE_NODE`) |
| Which card is worth minting | `system/temporal_work_items.py` (`date_card_changes_something`, `dangling_anchor_reason`) |
| Whose moments ride the owner's axis | `system/axis_membership.py` (`on_owner_axis`, `relationship_tier`, `IN_LAW_RE` re-exported from `identity_resolution`) |
| Which tellings are one event (the binder) and its rungs | `system/episode_binder.py` (`EXACT_IDENTITY_RULE_IDS` — `R2a`…`R2d`, `A_MERGE_NEVER_MOVES_A_DATED_MOMENT`, `A_COUPLE_IS_TWO_PEOPLE`, `NOTHING_TO_BIND_COSTS_NOTHING`) |
| The pure fold/merge/split decisions the binder and the fold call | `system/episode_fold_contract.py`, `system/episode_routing_contract.py`, `system/episode_fold.py` (`AN_ALIAS_NEVER_NAMES_A_NODE_THE_DRAWING_PUBLISHES`) |
| Who a mention names, and once-per-life/once-per-couple kinds | `system/identity_resolution.py` (`resolve_mention`, `roster_index`, `ONCE_PER_SUBJECT_EVENT_KINDS`, `ONCE_PER_COUPLE_EVENT_KINDS`, `couple_key`) |
| A relationship phrase that introduces a person | `system/roster_relations.py` (`AN_INTRODUCTION_NAMES_ONE_PERSON_IN_ONE_CLAUSE`, `A_RECORDED_RELATION_OUTRANKS_AN_INTRODUCED_ONE`); write seat `entity_roster.ensure_introduced_relatives`, verb `entity-roster --ensure-introduced` |
| What a landmark entry's date dates, and what is not a landmark | `system/landmark_projection.py` (`A_LANDMARK_IS_DRAWN_AS_WHAT_IT_IS`, `entry_date_event_kind`, `not_a_landmark`, `birth_landmark_not_owner`, `BIRTH_DOMAIN_WORDS`, `reinstate_domain`) |
| When a landmark entry stops standing, and the repair | `system/landmarks_interaction.py` (`A_STATED_ENTRY_IS_NEVER_RETIRED_BY_SHAPE`, `supersession_reason`, `collapsed_aggregate_fields`); verb `landmark-reinstate --domain <d> --apply` |
| The model that dates what is left, and its ledger | `system/resolver.py` (`spine`, `age_table`, `plan_items`, `file_envelope`), `state/resolver/resolutions.json`; verb `resolve [--execute\|--plan\|--from-response]` |
| What the fold reads, and what it skips re-reading | `system/temporal_store.py` (`fold_inputs`, `FOLD_CACHE_FILE` → `state/temporal_claims/fold-cache.json`) |
| What the standing publication was derived from | `system/temporal_publication.py` (`derivation_fingerprint`, `PUBLICATION_CACHE_FILE` → `state/temporal_claims/publication-cache.json`) |
| Whose timeline this is — the roster and the owner's own spellings every publish seat folds with (v328) | `system/temporal_publication.py` (`owner_identity_inputs`, `owner_names_from_profile`, `owner_name_variants`, `owner_identity_digest`) |
| Research basis | `system/research/chronology.md`, `system/research/chronology-vis.md`, `system/research.md` §4a |
| Guard tests | `tests/test_temporal_fold_cache.py`, `tests/test_chronology.py`, `tests/test_timeline_dates.py`, `tests/test_timeline_unknowns.py`, `tests/test_timeline_interaction.py`, `tests/test_timeline_evals.py`, `tests/test_cross_dating.py`, `tests/test_placement_score.py`, `tests/test_timeline_place_filing.py` |

### The fold on a large vault (v318)

Every step that draws your timeline — the active index, the telling manifest,
the published projection — is a pure function of the receipts and corrections
in your vault, and until v318 each one re-read all of them. On a vault with
nine thousand receipts that was about forty-six seconds per filing, four times
over the same unchanged files, and the hosted worker ran out of its budget
before it finished.

v318 changes the READING and nothing else. Three things now happen on every
call, and none of them is ever skipped: the receipts directory is walked with
the same no-follow guarantees as before, every file's size, inode and
modification time are collected fresh, and the fold's arithmetic runs over the
whole vault's inputs. What the framework no longer does is open, parse and
re-validate a receipt whose signature has not moved since the last fold — it
takes that receipt's contribution from the index it already published, and
from a small sidecar (`state/temporal_claims/fold-cache.json`) that records
what that index was folded from.

Since v322 that sidecar records the SHA-256 of each receipt's bytes rather
than the machine's inode and modification time, and it is committed with the
vault (`tracked: true`, like the index it describes). A fresh checkout — the
hosted worker starts one for every job — hashes each receipt once, which is
reading, not parsing or validating, and reuses everything whose bytes did not
move. Inside one process the stat signature still vouches first, so an
unchanged file is not even re-hashed. The publication cache beside it was
already keyed on content (the derivation fingerprint and the day) and travels
the same way.

So a filing that adds five receipts reads five receipts. The output is
byte-identical to a fold that read all nine thousand — that is a test
(`tests/test_temporal_fold_cache.py`), not a hope — and if the sidecar is
missing, stale, unreadable or describes a different index, the framework reads
everything and says nothing about it. Correctness never depends on the cache;
only the clock does.

`temporal_publication.publish` gained the same kind of shortcut one level up.
It already declined to mint a new generation when a republish would say
nothing new, but it had to derive the whole projection to find that out. It now
digests everything the derivation would be handed — the index, every fold
authority, the roster, the owner, the resolver's questions — and if that
digest matches what the standing generation was derived from AND the day has
not turned, it skips the derivation. The day matters because age frames are a
function of the calendar: cross midnight and the projection is derived again,
which is how a birthday still moves your timeline and an ordinary Tuesday
still does not.

Both files are declared state in `system/vault_contract.json`, both are
`tracked: false` (stat signatures name one machine's inodes; they must never
ride a shared vault), and both are safe to delete at any moment — it costs one
full read. The explicit repair paths never consult them: `python3
system/temporal_publication.py --rebuild`, `--check` (the rebuild oracle), and
`LIFEHUG_TEMPORAL_FOLD_CACHE=0` in the environment all fold from the receipts
themselves.

### One owner identity, every seat (v328)

Several acts republish the calculated projection — a landmark write
(`timeline.publish_calculated_timeline`), closing a Mirror row
(`mirror_work`), the frame-display command, `python3
system/temporal_publication.py`, and the upgrade seat in `update.py`. The fold
needs two host inputs none of the receipts carry: the `person` roster and the
owner's own spellings, so that a roster entity bearing the owner's name is the
owner (`timeline-rules:8`). Until v328 only the landmark seat supplied them, so a
Mirror republish quietly turned the owner's own moments into somebody else's,
and the file did not say which definition had folded it.

`temporal_publication.publish` now reads both itself when a caller does not name
them — `owner_identity_inputs(vault_root)`: the vault's own roster
(`entity_roster.load_roster("person", vault_root=…)`) and
`owner_names_from_profile`, the profile's whole `name` and `full_name` under the
vault's `config.yaml`, nothing tokenized (a middle name is not the owner). `None`
reads, an explicit value is used exactly, `()` is still "none" — the same
convention every other fold authority follows. Both are read from the vault being
published, never from the process binding, so roster and substrate cannot come
from two vaults. `resolver.spine` derives its `owner_names` from the same helper
and adds each spelling's first word (`owner_name_variants`) for its own
`subject_age_not_owner` refusal; that widening never reaches the fold. The
envelope carries `owner_identity_digest` — sha256 over the sorted spellings and
the roster refs they resolve to — so two seats that agree stamp the same digest
and a generation folded with no identity is visibly one. It is derived, so
`rebuild_signature` keeps it; `--check` on a pre-v328 file names it as the one
difference until the next publish. Guard: `tests/test_owner_identity_inputs.py`.

## 7. Decisions

- [ADR 0024 — Chronology with basis](../adr/0024-chronology-with-basis.md) — dates as intervals, asking anchor-first, contradictions that keep both claims, derived order, keystones, and the fifth child interaction (amended v196: the deferral state is deleted, and a keystone is asked as a whisper or a minted question).
- [ADR 0026 — Cross-dating](../adr/0026-cross-dating.md) — a resolved anchor places its dependent moments; leverage counts only what the pass can actually derive.
- [ADR 0027 — The placement score](../adr/0027-the-placement-score.md) — the level and its margin are one arithmetic; width never presence; a floor, a pair, and a band.
- [ADR 0037 — The spine and the resolver](../adr/0037-the-spine-and-the-resolver.md) — how the timeline places itself: the spine, the model, mechanical verification, the ledger, and every amendment through v350 (the two legs for hosts, what is not a landmark and not an event, revisits/aim/estimates, the birth landmark, a birthday is a birth, an introduction names one person in one clause, a stated entry is never retired by shape, one couple/one alias/one label).
- [The I0 fold contract](../contracts/event-identity-i0-fold.md) — fold semantics, id mapping, the merge/split routing table, and the five ways a node id moves.
- [Eras — the fold's contract version](eras.md#the-folds-contract-version) — what `timeline-rules:N` means and the bump-by-bump table from `:8` to `:17`.
- [The Timeline Interaction](interactions/timeline.md) — the conversation that places a memory.
- [The Landmarks Interaction](interactions/landmarks.md) — the universal dating set, its ladders, its recorder and its general listener.
- [ADR 0023](../adr/0023-arc-walking.md) — the sibling child whose stage and caller-fact shape this one copies.
