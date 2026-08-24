---
title: Reading Room
parent: The Interaction Pattern
nav_order: 9
---

# Reading Room Interaction

## 1. What it does

**The user's case.** *"I have my mother's photo albums in a box in the closet.
I know roughly nothing about when any of it happened. And there are mysteries
about my grandmother I could resolve if I asked my uncle, who is still living,
today."*

The Reading Room is the session that answers both halves of that. It is a
sitting of tens of minutes, chosen deliberately, where the person has actual
evidence to hand and the system turns what the paper says into dated facts.
It is not a daily question, not a notification, not a nudge, and not a streak
— §2.4 of the research is the methodological reason as well as the owner's
preference: conversational flexibility earns nothing on easy cases and
everything on hard ones, and every case here is hard.

The name is literal. An **archive's reading room** is where you consult
materials that never leave the building: you sit down with what you have, and
nothing is taken from you. Nothing is uploaded, nothing is scanned, nothing is
ingested — the person reads the document aloud and the system records the
derived date. That satisfies data-minimisation by construction, and holding
documents stays a separate question. The button verb is **Go Deep**.

Three moves make it a session rather than a question:

1. **It opens with the room, not the memory.** A shoebox of prints, one report
   card, a parent on speakerphone, and nothing at all are four different
   sessions. And when they name a photograph, the follow-up is what is *near*
   it — the date is on the envelope, and the envelope is what people throw
   away.
2. **It arrives with a plan and says so once**, each item stated as what it
   would unlock: *"if we can place this, nine other things fall into place."*
3. **It recomputes after every placement** and says what just got placed.
   That is the one structural difference from every other interaction in the
   system.

## 2. The nouns

- A **Reading Room** session is the deliberate, opt-in sitting described
  above. A **whisper** is the *ambient* way the loop asks about time; a
  **keystone** is the gap that makes either worth asking. Making a Reading
  Room ambient would turn it into the interrogation whispers exist to avoid.
- A **witness** is someone living who was there. Derived from roster facts the
  person already gave — `relationship` and `living` — joined on an edge
  `timeline.dependency_index` already walks. No new state.
- A **dig list** is one witness's homework: short, plain, never a form,
  re-derived on every compile and rendered into that person's existing
  `## Open Questions` wiki section. **A page, not a queue.**
- The **precision grade** is the grade of detail an ask reaches for, because
  some grades unlock derivations and coarser ones do not.
- The three **evidence bases** — `document`, `photo`, `relative` — are how a
  date arrived at in this session says what its warrant was.

## 3. The mechanism

**The plan.** `timeline.dig_plan(data, roster, k)` runs the same
greedy-over-the-residual loop `timeline.keystones` runs — literally the same
function, `timeline._greedy_plan` — extended to `k` picks. Ranking is on a
**continuous width-sum** with the count displayed, because a threshold metric
("how many become month-precise") is not submodular and greedy stalls on it.
An unknown with no bounds weighs 1.0, so on today's vaults the ranking
degenerates exactly to marginal coverage.

**The grade.** Each pick names a `precision_target` from a closed vocabulary
and the clause that justifies it. A school is a name until you have its
address; then it is a district, and a district keeps records with exact years
in them. A birthday guessed to the year dates nothing to the day.

**The witness partition runs LAST, over what the plan does not reach.** That
ordering is deliberate. Running it first — taking every unknown a living
relative shares an era with off the table before the session starts — empties
the Reading Room of exactly the work it exists to do, because a parent shares
an era with the whole of a childhood. What the greedy plan surfaces is the
unknown *no anchor in the graph reaches at all*, and that is precisely §6's
case: better probing will never place it; one question to a relative will.

**The recompute.** `reading_room.recompute_plan` re-runs the plan against the
graph as it now stands, subtracting anything filed this session that the read
model has not caught up with yet. Pure, and persisted nowhere.

**The bases.** `chronology.BASES` gains `document`, `photo` and `relative`,
weighted flat:

<!-- parity: chronology.CONSILIENCE_WEIGHT = 0.5 -->

| basis | weight | why |
|---|---|---|
| `document` | 7.0 | a printed date is not a reconstruction |
| `stated` | 6.0 | unchanged |
| `relative` | 5.5 | proxy report supplements the index report, never replaces it |
| `age` | 5.0 | unchanged |
| `photo` | 4.5 | a contextual date **bounds** rather than names |

There is no era-conditional term. The research's "relatives beat self for
childhood" nuance stays a research note, not a mechanism.

## 4. The algorithm, worked

The research's own synthetic vault: eight undated moments in one era, three in
another, one undated moment no anchor reaches, twelve concrete unknowns.

Ordering independently by leverage stars `period:childhood-yucaipa` (8) and
`entity:mom` (7), which reads like fifteen unknowns of value. It is eight:
Mom's resolve set is a strict **subset** of the era's, so the second star's
marginal gain is exactly **zero**.

The greedy plan over the residual instead:

| # | ask | places | of |
|---|---|---|---|
| 1 | `period:childhood-yucaipa` | 8 | 12 still open |
| 2 | `period:mesa` | 3 | 4 still open |

**Two questions, 11 of 12 unknowns placed, against the leverage list's 8** —
and the one unknown left, `moment::funeral`, is the one no anchor reaches. It
routes to Uncle Ray's dig list rather than being asked again, better, of a
person who cannot answer it.

`tests/test_reading_room.py` runs this example as data and pins the subset
regression by name: an anchor whose marginal gain is zero is never picked,
however large its leverage.

## 5. In the loop

**Loop-adjacent by design, and deliberately so.** Nothing about the Reading
Room is scheduled. There is no send, no notification, and no daily question —
the row is always present on the Timeline and re-derived, and the person
chooses it. `timeline.timeline_data()["reading_room"]` is an additive block a
host renders; the two witness lines under the row are capped at two.

The one place it touches a scheduled surface is the compile: each witness's
dig list is re-derived and rendered into their own wiki page's
`## Open Questions`. Because those rows are addressed to somebody *else*,
`question_candidates.harvest_wiki_questions` skips them — harvesting one would
put "what year did we move?" into the owner's own daily queue, the single
question they cannot answer.

## 6. The behavior authority

The file below IS the prompt. It is embedded here verbatim, and a test fails
if the two ever drift.

<!-- embed: interactions/reading_room/prompt/behavior.md -->
# Behavior — Reading Room extension

These amend Conversation's rules. Conversation's numbering is frozen; nothing
here renumbers it.

## Open by asking what is in the room

The first reply asks what they have in front of them — an album, a box of
prints, a folder of paperwork, a parent on the phone, or nothing at all. Four
different sessions follow from those four answers, and you cannot pick the
cheap questions until you know which one you are in.

When they name a photograph, the follow-up is **what is near it**. The date is
rarely on the picture. It is on the envelope, the back, the folder, the card
that came with it — and the envelope is the thing people throw away.

## The artifact carries the burden, not their memory

"What does the back of it say?" · "Read me everything printed on the border,
exactly as it appears." · "What's the issue date inside the passport?" Those
are the questions. "Do you remember when that was?" is not, and neither is
"what's your best guess" or "how many years ago was that".

This is not fussiness. A dating probe backed by the person's own photographs
is the precise configuration that manufactures false memories in about two
thirds of people. You elicit readings. They supply what the paper says.

## Say the plan once, then let it go

You arrive with two or three things worth asking, each stated as what it would
unlock — "if we can place this, nine other things fall into place." Say that
once, at the top, in one warm sentence. Never read the list aloud, never count
what is left, never mention a plan again. If they go somewhere else, go with
them; the plan is a map, not a script.

## Ask for the grade that unlocks the rest

Some answers are worth far more at one grade than another, and you say which
grade you want and why in the same breath.

- A school is a name until you have its **address**. An address is a district,
  a district keeps records, and records give exact years.
- A birthday is worth having **to the day**, because every "I was about five"
  turns into a real window afterwards.
- A residence wants **both ends** — when you moved in and when you left.
- A move, a job, a service period: the **month**, if the paper gives it.

Ask for the exact thing, say plainly what the exact thing buys, and take
whatever comes. One grade coarser is still an answer.

## One thing at a time

Someone holding a photograph can answer one question. A turn that asks two
gets neither. At most ONE question per reply.

## Say what just got placed

When something lands and nine other moments fall into place behind it, say so
— short, concrete, in their terms. "That dates nine moments." That is the only
progress feedback that belongs here. Counts of what remains, percentages,
"X of Y", and any sentence with the word *required* in it do not.

## A window is a finding

"Not before October 1983, because of the ZIP+4" is real information and it is
worth saying out loud. So is "that puts it between '84 and '90". A photograph
gives a window, not a day, by construction — say so rather than quietly
rounding it to a year.

## Never propose a date

You may report what the arithmetic gives you. You may never name a date and
ask them to agree with it. "Was it 1984?", "shall we say '86?", "does that
sound about right?" — all forbidden, in every domain, on every basis, however
good the evidence.

## When evidence and memory disagree, attribute it to the source

"The report card says June — you'd remembered the spring." Both claims are
kept; neither person is corrected. The disagreement is data.

## "I'll find out" is a complete answer

Some things are not theirs to answer. When they say they will ask someone,
that is the end of it: no reminder, no follow-up, no "let me know when", no
adding it to a list. There is no queue here and there must never be one.

## The witness

A **witness** is someone living who was there. When an unknown belongs to
someone else's memory, name them plainly and say what one question to them
would unlock — once, lightly, as an option. Ask about **events**, never
processes: "what year did we move" survives thirty years intact; "when did I
start reading" drifts, and always later.

Never invoke anybody's mortality. Not once, not gently, not as a reason.

## Nothing leaves the room

They read the document out; you record what it gives. Nothing is uploaded,
nothing is scanned, nothing is stored but the date and where it came from. Ask
for the date first and the type of paper second — it is both the private
answer and the shorter exchange.
<!-- /embed -->

## 7. Code map

| What | Where |
|---|---|
| The bases and their weights | `system/chronology.py` — `BASES`, `EVIDENCE_BASES`, `BASIS_WEIGHT` |
| The witness on a record | `system/chronology.py` — `witness_provenance`, `witness_slug`, `witness_name` |
| The plan | `system/timeline.py` — `dig_plan`, `_scored_anchors`, `_greedy_plan`, `unknown_width` |
| The grade | `system/timeline.py` — `PRECISION_TARGETS`, `PRECISION_UNLOCKS`, `precision_target_for`, `precision_ask` |
| The witness join | `system/timeline.py` — `witness_for`, `WITNESS_GENERATION_ORDER` |
| The dig list | `system/timeline.py` — `render_dig_list`, `DIG_LIST_MARKER`, `DIG_LIST_FOOTER`; `system/wiki_compile.py` — `dig_lists_by_slug`, `apply_dig_lists` |
| The harvest guard | `system/question_candidates.py` — `_is_dig_list_line` |
| The interaction | `system/reading_room.py`; `interactions/reading_room/` |
| The seat gate | `system/reading_room_evals.py`; `python3 system/lifehug.py reading-room-evals --json` |
| The read-only plan verb | `python3 system/lifehug.py reading-room-plan [--json]` |
| The tests | `tests/test_reading_room.py` |

## 8. Decisions

- **ADR 0025** — the Reading Room: three evidence bases, the dig plan, the
  witness, and the child interaction.
- **Owner rulings, 2026-08-24** — the name is the Reading Room ("Go Deep"
  stays the verb); the row is the head of the Unknowns section; dig lists
  render into the person page's `## Open Questions`; `k = 3` asks and at most
  2 witness lines; flat basis weights with no era-conditional term. And the
  emphasis this whole lane turns on: **rank by marginal coverage AND ask for
  the precision grade that unlocks the derivations.**
- **ADR 0024** — chronology with basis, which this extends rather than
  amends: an interval is a finding, not a failure, and a date is never
  proposed for agreement.
