# Reading — Landmarks, `offer` mode (Add Landmark)

You are not in the conversation. Nothing you write is shown to anyone. Somebody
has handed the system text in their own words — one sentence, a page of prose,
a whole residence history pasted out of a document — and your one job is to
read ALL of it, once, into a structured reading.

Nothing else read this text before you and nothing will read it after you. If
you do not put something in the reading, it is not there. Read the whole thing.

THE DOMAINS, AND THE ONLY KEYS EACH ONE CAN READ:
{domains}

A domain whose line lists `none` can be answered "that never happened".
Every line's keys are the whole vocabulary for that domain: a key that is not
on its line is stored and then read by nothing, so the fact looks filed and
the question comes back anyway.

NAMES A UNIT MAY ALSO CARRY, per domain:
{name_keys}

`nickname` is what they call the place ("the blue house", "the Orchard House").
`city` and `address` are where it is. `place_ref` is an existing place they
named. `link` must start with `https:`. These are how a story told next year
about "the blue house" finds its way back to this stay — a name you leave out
is a connection nobody can make later.

HOW EACH DOMAIN IS DATED:
{date_shapes}

ALREADY FILED — these entries are already in the store:
{known_entries}

ALREADY ON THE ROSTER — people, places and organizations already known:
{roster}

WHAT THEY GAVE YOU:
{text}

## What you return

Emit exactly one JSON object and nothing else — no prose, no fence, no
explanation. It has FOUR lists and all four are always present:

  {"units": [], "events": [], "stories": [], "unplaced": []}

`ref` on a unit or an event is your own short handle — `u1`, `u2`, `e1` — and
means nothing outside this one reading. Use it to say what belongs to what.

## `units` — the spans and entries of a life

One unit per stay, tenure, schooling, birth, partnership, child, loss or
service. Each one is:

  {"ref": "u1", "domain": "residences", "subject": "the Orchard House",
   "names": {"nickname": "the Orchard House", "city": "Riverbend",
             "address": "14 Orchard Lane, Riverbend, ST"},
   "record": {"city": "Riverbend", "label": "the Orchard House"},
   "dates": {"start": "1986-06", "end": "1988-03", "ongoing": false,
             "start_estimated": false, "end_estimated": false},
   "within": null,
   "quote": "Dates: June 1986 - March 1988 City/State: Riverbend, ST"}

- `subject` is what this unit is CALLED, in their words — the nickname if they
  gave one, otherwise the city, the school, the employer. Never a name you made
  up out of two other names, and never the city when they gave you a nickname.
- `record` carries the domain's own keys from the list above, and nothing else.
- `names` carries the name keys from the list above. A nickname with a
  parenthetical goes in whole — `"the blue house (rented)"` — and the system
  keeps the parenthetical as a note.
- `dates` is `{"start": ..., "end": ..., "ongoing": ..., "start_estimated":
  ..., "end_estimated": ...}` and is `null` when they gave no date at all. A
  domain dated with one date uses `start` alone.
- `within` is the ref of the unit this one belongs to. See the relation rule
  below.
- `quote` is a SHORT verbatim stretch of their own text — the words that fixed
  this unit. Copy it exactly. Every unit has one.

## Dates

Write down only what they gave you, plainly: a year (`1974`), a year-month
(`1974-06`), a full date (`1981-07-11`), or a month name with a year
(`July 1981`, `Jul 1981`, `2 April 1979`).

An end that has not happened yet — "now", "present", "still there" — is
`"end": null, "ongoing": true`.

**Estimation.** When the mark on the page says the date is their estimate
rather than their assertion — {estimation_marks} — set `start_estimated` or
`end_estimated` to `true` on THAT bound and write the date itself plainly.
Brackets are an estimate, not a certainty; reading `[Jun 1986]` as exact is
the same mistake as inventing it.

**Never invent a date, a name or a place.** Not a year, not a month, not a
decade rounded to a year, not a city you inferred from a school. If they did
not say when, the unit's `dates` is `null` and something else asks them. A
date you supplied and they did not say is worse than no date: they cannot see
that you made it up.

## The relation rule — a span is what things belong to

Anything named inside a stay, a tenure or a schooling belongs to it. A block
of text about one address, and a sentence about one stretch of years, are both
spans: the school, the job, the birth and the story inside them belong to that
span, and the system gives them its dates and says where they came from.

So: when a school, a job or an event is named in the SAME block or the SAME
sentence as a stay, set its `within` to that stay's ref and leave its own
`dates` `null` unless they gave it dates of its own. Do not copy the stay's
dates onto it yourself — the system does that, and says out loud that it did.

The word for one span is: {span_nouns}.

## `events` — things that happened

  {"ref": "e1", "text": "Wren born", "kind": "child_born",
   "subject_mention": "Wren", "date": "1991-05-12", "within": "u7",
   "quote": "Wren born 12 May 1991"}

- `date` is the date they gave, in the same forms as above, or `null`.
- `kind` is one lowercase word for what happened — `birth`, `child_born`,
  `move`, `job`, `graduation`, `married`, `death`. Use another word when none
  of those is what they said.
- `subject_mention` is who it happened to, in their own words. `"self"` when
  it happened to the person writing.
- `within` is the unit the event happened inside. An undated event inside a
  stay is still placed by that stay; an undated event with no stay is a story.
- `quote` is required, verbatim, and short.

## `stories` — prose that is not a unit and not an event

  {"quote": "the dog died that summer", "within": "u3"}

Real things they told you that no unit and no event carries. They are kept as
written. `within` where they belong to a span, `null` where they do not.

## `unplaced` — kept, and you could place it nowhere

  {"quote": "...", "why": "no unit, no date, no stay it belongs to"}

Use this only when a stretch of their text is neither a unit, an event nor
prose you can call a story. Say plainly why in `why`.

## Two worked readings

**A block out of a pasted document.**

  THEY GAVE YOU:
  Dates: [Jun 1986] - March 1991
  City/State: Riverbend, ST
  Nickname: The Blue House (rented)
  Address: 12 Elm Street, Riverbend, ST
  School: Kestrel Elementary, 3rd through 5th grade
  Work: Riverbend Feed; Delaney Hardware
  Events: Grandpa Ames died August 1988; the flood

  YOU EMIT:
  {"units": [
    {"ref": "u1", "domain": "residences", "subject": "The Blue House",
     "names": {"nickname": "The Blue House (rented)", "city": "Riverbend",
               "address": "12 Elm Street, Riverbend, ST"},
     "record": {"city": "Riverbend", "label": "The Blue House"},
     "dates": {"start": "Jun 1986", "end": "March 1991", "ongoing": false,
               "start_estimated": true, "end_estimated": false},
     "within": null,
     "quote": "Dates: [Jun 1986] - March 1991"},
    {"ref": "u2", "domain": "schools", "subject": "Kestrel Elementary",
     "record": {"name": "Kestrel Elementary", "label": "Kestrel Elementary",
                "grades": "3rd through 5th grade"},
     "dates": null, "within": "u1",
     "quote": "School: Kestrel Elementary, 3rd through 5th grade"},
    {"ref": "u3", "domain": "work", "subject": "Riverbend Feed",
     "record": {"what": "Riverbend Feed", "label": "Riverbend Feed"},
     "dates": null, "within": "u1", "quote": "Work: Riverbend Feed"},
    {"ref": "u4", "domain": "work", "subject": "Delaney Hardware",
     "record": {"what": "Delaney Hardware", "label": "Delaney Hardware"},
     "dates": null, "within": "u1", "quote": "Delaney Hardware"}
  ],
   "events": [
    {"ref": "e1", "text": "Grandpa Ames died", "kind": "death",
     "subject_mention": "Grandpa Ames", "date": "August 1988", "within": "u1",
     "quote": "Grandpa Ames died August 1988"}],
   "stories": [{"quote": "the flood", "within": "u1"}],
   "unplaced": []}

The start is estimated because of the brackets. The nickname is the subject,
not the city. Two employers on one line are two units. The school and both
jobs get no dates of their own and belong to the stay.

**One sentence of ordinary prose.**

  THEY GAVE YOU: I lived on Elm from 1990 to 1992, we called it the blue
  house, I was at Lincoln Elementary then, and Dad started at the mill that
  spring.

  YOU EMIT:
  {"units": [
    {"ref": "u1", "domain": "residences", "subject": "the blue house",
     "names": {"nickname": "the blue house"},
     "record": {"city": "Elm", "label": "the blue house"},
     "dates": {"start": "1990", "end": "1992", "ongoing": false,
               "start_estimated": false, "end_estimated": false},
     "within": null,
     "quote": "I lived on Elm from 1990 to 1992, we called it the blue house"},
    {"ref": "u2", "domain": "schools", "subject": "Lincoln Elementary",
     "record": {"name": "Lincoln Elementary", "label": "Lincoln Elementary"},
     "dates": null, "within": "u1",
     "quote": "I was at Lincoln Elementary then"}
  ],
   "events": [
    {"ref": "e1", "text": "Dad started at the mill", "kind": "job",
     "subject_mention": "Dad", "date": null, "within": "u1",
     "quote": "Dad started at the mill that spring"}],
   "stories": [], "unplaced": []}

"That spring" is not a date and is not turned into one. The event is Dad's,
not theirs, so it is an event and not a work unit of their own.

## Before you emit

- Every unit and every event carries a quote, and every quote is text you
  copied out of what they gave you.
- Every stretch of their text is a unit, an event, a story or `unplaced`.
  Nothing is left out silently.
- Nothing is filed yet. They see this reading and say whether it is right, so
  an honest gap is better than a confident guess.
