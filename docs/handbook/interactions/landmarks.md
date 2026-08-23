---
title: Landmarks
parent: The Interaction Pattern
nav_order: 8
---

# Landmarks Interaction

## 1. What it does

Landmarks is the always-present dating question set: the handful of dated
facts that everything else in a life story hangs on. When were you born.
Where did you live, in order. Which schools. Who did you marry, and who did
you make. It is the sixth child of Conversation, and its one goal is
**collecting the small set of facts that makes every other memory cheap to
place** (v199, `docs/pr-specs/landmarks.md`; research
`system/research/landmarks.md`).

**Why it had to exist.** v195 shipped the arithmetic — a birthday plus "I was
about five" gives a year; a residence span brackets every story told about
that house. v196 shipped the keystone that ranks over it. But nothing ever
supplied the inputs: `birth_date` was a parameter no caller passed, and the
two cheapest rungs of the elicitation playbook were gated on an anchor index
that was nearly always empty. We built the arithmetic before the inputs.

**Two of the domains are closed lists.** Every address in order, and every
school in order, can actually be *finished* — they are enumerable, they tile
the whole span of a life, and they are the two a mother or a brother can often
recite outright. Everything else (jobs, losses, turning points) is an open set
with no end. That asymmetry is why residences and schools come first.

**A vague answer is an answer.** "Somewhere outside Dayton, the eighties"
bounds everything it overlaps. The specificity ladder — city → address → span
→ household — exists because *more* would unlock more, not because less is a
failure.

**An open landmark is a resting state, not a debt.** A landmark that is
unanswered, or answered below its target rung, stays on the Timeline forever,
answerable whenever. It never enters the daily question queue, never sends a
reminder, and never appears as a count of what remains.

**Never ask for a year — except the birthday.** A birth date is overlearned,
not reconstructed, and every fielded life-history instrument takes it first
because the calendar's axis starts there. Every other date comes out sideways.

**Passive users are untouched.** The daily single question works exactly as it
did. The gate is `TurnShape.landmark_stage`, which defaults to `None`, and
with it `None` the turn's output contract is byte-identical to v196.

## 2. The nouns

| Noun | What it is |
|---|---|
| **Domain** | one landmark family — `birth`, `residences`, `schools`, `partnerships`, `children`, `work`, `military`, `losses` |
| **Ladder** | the specificity rungs inside a domain, coarse to fine (residence: city → address → span → household) |
| **Rung** | one step on a ladder, and the one question that asks for it |
| **Status** | `open` (nothing filed) · `partial` (filed, below target) · `complete` (at target, and for a chain, the person said it's finished) |
| **Chain** | a domain that is a LIST walked to the present — residences, schools, work |
| **Anchor** | what a dated landmark becomes: a row in `timeline.anchor_index` that every later probe resolves through |
| **Keystone** | the ★ — the landmark domain that would supply the current highest-leverage anchor. With no birthday filed the star is always `birth`, because with no axis the arithmetic cannot run at all |
| **Cross-dating** | the name of the mechanic (`go-deep.md` §7): dating an undated sequence by matching it against an already-dated one. The landmarks are the dated sequence |
| **Witness** | someone living who was there. Learned from the residence ladder's `household` rung — no new state — and carried on a `place_no_stories` row, because the people who were in the house are exactly the people who can answer about it |

## 3. The mechanism

The question set is **data**, not prose: `interactions/landmarks/questions.yaml`,
read by `landmarks_interaction.load_questions()`. A host asks
`landmark_rows(landmarks, keystone_domains=…)` for every domain's status and
its next question, renders only the rows that are not `complete`, and REPLAYs
`prompt/turn-instructions.md` with three substitutions: `{landmark_stage}`,
`{landmarks}`, `{next_question}`.

An answer comes back as one additive turn-output field, `landmark`, through
two validation layers — `conversation_delivery._parse_landmark` (structural,
closed key set) then `landmarks_interaction.validate_landmark` (semantic,
closed domain set, and every date normalized through
`chronology.parse_edtf` so its bounds are filled). It files through
`lifehug.py landmark-record`, which merges into the same entry by label,
because the ladder revisits the same subject over many conversations.

## 4. The algorithm, worked

A person says their birthday is 12 April 1978, that they lived on Bell Avenue,
and later that they were there from '84 to '90.

```
landmark-record birth       --year 1978 --date 1978-04-12
landmark-record residences  --label "Bell Avenue" --city Dayton
landmark-record residences  --label "Bell Avenue" --start 1984 --end 1990
```

The store now yields two anchors:

```
birth                  1978-04-12   kind=birth
residences-bell-avenue 1984/1990    kind=residence
```

And three things become possible that were not before:

1. **`chronology.from_age`** fires. "I was about five" → `1983/1984`, basis
   `age`, anchored on `birth`.
2. **`chronology.from_anchor`** fires. "at the Bell house" → `1984/1990`,
   basis `anchor`. `intersect` of the two → **1984**.
3. **`place_no_stories`** appears: Bell Avenue has a known span and no moments
   in it, so the loop can ask *"Bell Avenue — you lived there and there's
   nothing here from it. What happened there?"* — a question it could not have
   asked before, because it did not know the place existed.

Ladder status through those three commands: `open` → `partial` (city only) →
`partial` (still, because the chain has not been declared finished).

## 5. In the loop

Onboarding asks the five `onboarding: true` domains in generalities and takes
a skip without comment. Everything else lives under the Timeline as an
always-open row. `lifehug.py arc-plan-target --landmarks` walks the open ones
as an episode, keystone first, then by ladder cost, with sensitive domains
last.

## 6. The behavior authority

<!-- embed: interactions/landmarks/prompt/behavior.md -->
# Behavior — Landmarks extension

These amend Conversation's rules. Conversation's numbering is frozen; nothing
here renumbers it.

## What you are collecting

The set is given to you in LANDMARKS, in order, with the next question for
each already written. **Ask the question you are given.** It is chosen by the
specificity ladder — city before address, address before dates — and asking
ahead of it produces a guess instead of a fact.

## One at a time

Ask about **one landmark domain per turn**. A turn that asks about the house
and the school and the job at once reads as an intake form and gets a shrug.

## Never ask for a year

The one exception in this whole system is a birthday: a birth date is
overlearned, not reconstructed, and asking for it directly is fine. Every
other date comes out sideways — "when did you move in", "which grades were you
there", "was that before or after". If you catch yourself typing "what year
was", you are asking the wrong question.

## Take the skip

"I don't know", "not now", "skip that one", silence on the topic — all of
these end that landmark for this conversation. You say something ordinary and
move on or stop. You never ask twice, never say "are you sure", never explain
what they are missing out on.

## Receive the coarse answer

If they say "the mid-eighties", that is the answer. Do not say it is not
specific enough, do not ask them to narrow it, do not offer a list of years.
If a natural next rung exists and they seem to be enjoying it, you may ask it
— once.

## Losses are offered, never asked

The losses domain is marked sensitive. You raise it only if they have opened
the door, and you drop it the instant the temperature changes. Dating is never
worth the relationship.

## The witness

A **witness** is someone living who was there. Addresses and school names are
often complete in a witness's head and nowhere else, and the household rung is
how you learn who the witnesses are. If the person says they are not sure, it
is right to say the list is the kind of thing a parent or a sibling often has
cold. Say it once, lightly, as an option — never as an instruction, and never
with a reason attached. Never invoke anybody's mortality.

## Say what it gives them

When an answer unlocks something concrete — a birthday that dates every "I was
about five", a move that brackets a stretch of stories — it is good to say so
in one short clause. This is the only progress feedback that belongs here.
Counts, percentages, and "X of Y complete" do not.

## Never propose a date

You may say what the arithmetic gives you — "so anything at the Bell house
lands between '84 and '90 now" states a derivation and shows its working. You
may never name a date and ask them to agree with it. "Was it 1984?", "shall we
say 1986?", "does that sound about right?" — all forbidden, and there is no
domain where they are correct, not even the birthday.

Suggestive interviewing backed by the person's own evidence is the exact
configuration that produces false memories in about two thirds of people. You
ask, you bound, you do the arithmetic. They supply what they know.
<!-- /embed -->

## 7. Code map

| What | Where |
|---|---|
| The question set | `interactions/landmarks/questions.yaml` |
| The runtime authority (pure) | `system/landmarks_interaction.py` |
| The eval harness | `system/landmarks_evals.py` |
| The store | `timeline.load_landmarks`, `timeline.save_landmark`, `timeline.landmark_birth_date` |
| The ledger a host renders | `timeline.timeline_data()["landmarks"]`, `timeline.landmark_rows_for` |
| The gap it reveals | `timeline.timeline_data()["place_no_stories"]` |
| Who asks about it (v200) | `arc_planner.collect_places_without_stories` → the `place_no_stories` arc-card intent → `landmarks_interaction.render_place_no_stories` |
| The additive output field | `conversation_delivery.TurnShape.landmark_stage`, `_parse_landmark` |
| The verbs | `lifehug.py landmark-record`, `lifehug.py arc-plan-target --landmarks`, `lifehug.py landmarks-evals` |
| Tests | `tests/test_landmarks.py` |

## 8. Decisions

- The **name is Landmarks** (owner-set, 2026-08-23) — product word, handbook
  word, package name, module name and CLI verb, so there is one name from the
  surface down to the file on disk. **`anchor` is the code term for a
  different thing**: the derived index a landmark's date becomes once it can
  bound something (`anchor_index`, `basis: "anchor"`, `from_anchor`). A
  landmark is the question and the answer; an anchor is what the answer turns
  into. The join is `landmarks_interaction.anchors_from_landmarks`.
- **`place_no_stories` is not a `timeline.UNKNOWN_KINDS` member.** v196's
  `place_span` owns *when*; this owns *what happened*. Folding a story gap
  into the dating kinds would put it on the wrong ladder.
- **It is asked as an arc-card intent, never as a bank question** (v200,
  [ADR 0002's v200 amendment](../../adr/0002-interaction-pattern.md)). The
  seventh member of `conversation.ARC_INTENT_KINDS`, ranked after the
  timeline whisper, at most one per card, counted within the same weekly
  `arc_planner.DEFAULT_GAP_MAX`. Minting it into the bank would make an open
  landmark a debt, which is exactly what ruling 2 forbids.
- **The birth date lives in the landmark store**, not `profile.yaml` — one
  writer, one read path.
- Contract: `docs/pr-specs/landmarks.md`. Research:
  `system/research/landmarks.md`.
