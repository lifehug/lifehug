---
title: The Timeline & Chronology
parent: Handbook
nav_order: 11
---

# The Timeline & Chronology

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
  before/after), `order` (sequence only), `public_event`, `connector`.
- **Anchor** — a landmark of the person's own that other dates hang off: their
  birthday, a residence with a span, an era with a span, a dated moment.
  Collectively they are the life-history calendar, and every probe above the
  second rung is cheap because they exist.
- **Band** — a row of the timeline. The person's own life **chapter** is the
  band wherever a dated chapter covers the stretch; the system's **period** is
  the band everywhere else. Inside a band, the **places** lived nest, and the
  **events** sit under their place.
- **Unknown** — a gap made answerable: `{kind, key, label, probe}`, where the
  probe is the cheapest question the playbook has for that kind.
  `era_gap` — a dated hole between two dated eras — is the kind that could not
  exist before dates did.
- **Leverage** — how many unknowns one anchor would resolve. **Keystones** are
  the top two, starred. <!-- parity: timeline.KEYSTONE_CAP = 2 -->
- **Deferred** — "I'll find out". A real state beside declined: quiet for
  `DEFERRED_QUIET_DAYS`, still starred, never counted as outstanding, never
  re-asked. <!-- parity: timeline.DEFERRED_QUIET_DAYS = 45 -->

## 3. How it works

**Where a date comes from.** The classifier records only what the author
explicitly said: a year they actually named, their age in their own words, or
a landmark plus a before/after. It never converts and never guesses — that
rule is unchanged, just restated as *"do not invent; do record what was
said"*. Then `chronology` does the arithmetic: `from_age` turns a birthday and
"about five" into `1984~` with basis `age`; `from_anchor` turns "before we
moved" into `../1984`; `intersect` combines several claims into the tightest
interval they all allow.

**What happens when accounts disagree.** Nothing is overwritten.
`chronology.reconcile` scores every claim by its basis, its confidence, and
how many independent sources corroborate it, and returns the best-supported
one *plus every alternate*. The page renders the best-supported interval and
links the others. A disagreement is data about how you have made meaning of
your past, not a bug to fix.

**How the spine gets its order.** Dated eras anchor at their earliest year;
undated eras are interpolated between their nearest dated neighbours in the
old order; the result is dense-ranked into `chrono`. With nothing dated, the
order is exactly what it was before v195.

**How a hole becomes a question.** Every gap the timeline computes becomes an
unknown with a probe. Press Play on one and the `timeline` interaction opens:
it asks about the moment, then where you were living, then what work you were
doing — climbing the ladder only while it stays cheap, offering bounds rather
than demanding points, and stopping the moment the answer is good enough for
that unknown's slot. If you say you will find out, it says the unknown will
keep, and means it.

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

**Leverage.** Anchor candidates are a period's start/end, a dated landmark
event, and an entity's arrival. A period anchor resolves that period's own
unknowns, every `era_gap` touching it, and every undated moment or entity in
it; a landmark event resolves the undated moments it would bound; an entity
arrival resolves the moments sharing its sources. Leverage is the size of that
set, keystones are the top two by leverage then by how cheap their probe is,
and `leverage_boost` (1.2) lifts keystone-adjacent questions in the weekly
queue.

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
immediately. Weekly, `timeline-retire` retires display pins the classifier has
caught up with, and `planner-queue` applies `leverage_boost` through a guarded
read that degrades to "no keystones" rather than ever breaking the queue.
Playing an unknown writes through the path that already existed —
`timeline-place` files a dated correction source into the archive and saves
the display pin — so a placement teaches the loop exactly as it always did,
on demand instead of at three whispers a week.

## 6. Where it lives

| Concern | Location |
|---|---|
| The date primitive | `system/chronology.py` |
| The model, bands, unknowns, leverage, deferred | `system/timeline.py` |
| Corroboration windows | `system/timeline_corroboration.py` |
| The elicitation | `interactions/timeline/`, `system/timeline_interaction.py` |
| The classifier's claim | `system/classify_story.py` (`events[].title`, `events[].date`) |
| The export and page frontmatter | `system/wiki_compile.py` (`compile_timeline`, `frontmatter(date_edtf=…)`) |
| The viewer | `system/serve_wiki.py` (`view_timeline`) |
| The write path | `lifehug.py timeline-place ... [--date] [--basis] [--anchor]`, `system/jobs.py` |
| Plan a timeline Play | `lifehug.py arc-plan-target --timeline [--era <slug>]` |
| Durable state | `state/timeline_placements.json`, `state/timeline_deferred.json` |
| Research basis | `system/research/chronology.md`, `system/research.md` §4a |
| Guard tests | `tests/test_chronology.py`, `tests/test_timeline_dates.py`, `tests/test_timeline_unknowns.py`, `tests/test_timeline_interaction.py`, `tests/test_timeline_evals.py` |

## 7. Decisions

- [ADR 0024 — Chronology with basis](../adr/0024-chronology-with-basis.md) — dates as intervals, asking anchor-first, contradictions that keep both claims, derived order, keystones, the deferred memory, and the fifth child interaction.
- [The Timeline Interaction](interactions/timeline.md) — the conversation that places a memory.
- [ADR 0023](../adr/0023-arc-walking.md) — the sibling child whose stage and caller-fact shape this one copies.
