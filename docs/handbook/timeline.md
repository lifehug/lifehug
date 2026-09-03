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

**How the three timeline words relate.** Landmarks are the universal
skeleton; **keystones** are the per-person gaps that skeleton leaves — the one
date that would place the most moments, computed from the dependency graph;
and **whispers** and **keystone questions** are the two ways the loop asks.

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
title. The timeline is recomputed on every read and written to
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
| Research basis | `system/research/chronology.md`, `system/research/chronology-vis.md`, `system/research.md` §4a |
| Guard tests | `tests/test_chronology.py`, `tests/test_timeline_dates.py`, `tests/test_timeline_unknowns.py`, `tests/test_timeline_interaction.py`, `tests/test_timeline_evals.py`, `tests/test_cross_dating.py`, `tests/test_placement_score.py`, `tests/test_timeline_place_filing.py` |

## 7. Decisions

- [ADR 0024 — Chronology with basis](../adr/0024-chronology-with-basis.md) — dates as intervals, asking anchor-first, contradictions that keep both claims, derived order, keystones, and the fifth child interaction (amended v196: the deferral state is deleted, and a keystone is asked as a whisper or a minted question).
- [ADR 0026 — Cross-dating](../adr/0026-cross-dating.md) — a resolved anchor places its dependent moments; leverage counts only what the pass can actually derive.
- [ADR 0027 — The placement score](../adr/0027-the-placement-score.md) — the level and its margin are one arithmetic; width never presence; a floor, a pair, and a band.
- [The Timeline Interaction](interactions/timeline.md) — the conversation that places a memory.
- [ADR 0023](../adr/0023-arc-walking.md) — the sibling child whose stage and caller-fact shape this one copies.
