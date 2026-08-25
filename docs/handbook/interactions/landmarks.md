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

**"That never happened" is a finished answer.** Four of the nine domains —
`partnerships`, `children`, `military`, `losses` — open with a yes/no, and
*no* completes them outright. A person with no military service is DONE with
military: the row leaves the open list and is never offered again. This is the
mirror of the rule above, and it is the difference between an instrument and a
form (owner ruling 6, 2026-08-24; `landmarks.md` §5.2). `family` is *not* one
of the four — its ladder opens at `who`, and "no siblings" does not mean there
was no family. An enumeration domain is finished the way every chain is.

**Recording is not replying** (v212, ADR 0028). Until v209 one model
completion did two jobs on a landmark turn — be good company, and file a fact
— and when the two competed, company won. The way it failed was never
coldness: someone says *"I never served, but I did spend two years abroad on a
mission"*, the turn takes up the mission, and the plain answer sitting next to
it goes unwritten. The instruction telling the model to record it was already
there. So the recording became its own pass: the conversation writes the
reply, and the **recorder** reads the person's own message afterwards and
files the record. One recorder, two triggers — the live turn and the
historical sweep — with `landmark_gates.answer_must_record` (the lane's only
BLOCKING lint) and exactly one regeneration as its backstop. Detection is
deliberately narrow (`answer_shape`): a skip wins outright, a negative counts
only where a none terminal exists, and "substantive" means the reply echoed a
name or a year the person supplied in that same message. An answer with
neither is invisible to the class on purpose — the class blocks a send, so
ambiguity must never punish a good turn.

**One answer, many records** (v214, ADR 0028 amendment). The next failure in
the same class arrived a day later, and it was not about tone at all: someone
answers *"what work have you done"* with a whole working life, or names four
children with four birthdays, and one record comes back. Most of these domains
are multi-entry by construction — four are declared `chain: true` and two more
enumerate people — so the recorder now emits a LIST, each record is validated
on its own so a bad one never costs a good one, and a second, RETRYABLE lint
(`landmark_gates.record_every_entry`) spends the same single regeneration when
the person plainly stated more entries than came back. That branch never
withholds: it files what it has, because a partial record is worth more than
none. Each record lands as its own entry in the store, and the only prior
entries a new one retires are a standing terminal and the collapsed aggregate
— an entry carrying a field its own ladder has no rung for.

**Never ask for a year — except a person's birthday.** A birth date is
overlearned, not reconstructed, and every fielded life-history instrument takes
it first because the calendar's axis starts there. v202 draws out the
consequence: the carve-out is about the KIND of fact, not whose fact it is, so
"what year was Jackie born?" is legitimate for a sibling or a child exactly as
it is for the person themselves (`landmarks_interaction.YEAR_OPENER_DOMAINS`;
research §2.9). Every other date comes out sideways.

**Passive users are untouched.** The daily single question works exactly as it
did. The gate is `TurnShape.landmark_stage`, which defaults to `None`, and
with it `None` the turn's output contract is byte-identical to v196.

## 2. The nouns

| Noun | What it is |
|---|---|
| **Domain** | one landmark family — `birth`, `family`, `residences`, `schools`, `partnerships`, `children`, `work`, `military`, `losses` |
| **Ladder** | the specificity rungs inside a domain, coarse to fine (residence: city → address → span → household) |
| **Rung** | one step on a ladder, and the one question that asks for it |
| **Status** | `open` (nothing filed) · `partial` (filed, below target) · `complete` (at target, and for a chain, the person said it's finished) |
| **Entailment** | `happened` is the one rung nobody states outright. It is satisfied by anything else the entry carries (`landmarks_interaction.asserts_happened`) — you cannot name your children without having children. Without it the first rung of all four yes/no domains was unreachable, and a fully answered domain read as if nothing had been said |
| **Identity rung** (v211) | the rung whose answer IS what the entry is called — `who` for the people domains, `city`/`name`/`what`/`branch` for the rest, and nothing at all for `birth`. DERIVED as the first rung that is neither `happened` nor a date grain (`landmarks_interaction.identity_rung`), and satisfied by the name the writer files under `label` (`identity_named`). The turn contract tells the model to put "the school in `label`", so before lifehug#219 **seven of the nine domains re-asked their own opening question after a perfect answer** — the founder's four labelled children were asked "What are their names?" forever. Same class as the `span` fallback (v199) and the date grains (lifehug#207): the ladder could not read what the writer writes |
| **None terminal** | `{"domain": …, "none": true}` — the answer "that never happened". Reports the domain's `complete_at` rung, so the domain is `complete` by the same definition every other answer uses. Available only where the ladder opens at `happened` (`landmarks_interaction.domain_accepts_none`), so `partnerships`/`children`/`military`/`losses` and nothing else: `{"domain": "birth", "none": true}` would complete the axis with no date, and `family` is an enumeration, not a yes/no |
| **Chain** | a domain that is a LIST walked to the present — family, residences, schools, work. `chain: true` is also what "an **enumeration domain**" means, the domains whose half-filled subjects each become their own unknown (v202) |
| **Anchor** | what a dated landmark becomes: a row in `timeline.anchor_index` that every later probe resolves through |
| **Keystone** | the ★ — the landmark domain that would supply the current highest-leverage anchor. With no birthday filed the star is always `birth`, because with no axis the arithmetic cannot run at all |
| **Cross-dating** | the name of the mechanic (`go-deep.md` §7): dating an undated sequence by matching it against an already-dated one. The landmarks are the dated sequence |
| **Witness** | someone living who was there. Learned two ways: the residence ladder's `household` rung — carried on a `place_no_stories` row, because the people who were in the house are exactly the people who can answer about it — and, since v202, the **family** domain's `living` rung (`witness_candidates`, `timeline_data()["witnesses"]`) |
| **Family** (v202) | the ninth domain and the constellation you came from: siblings, parents, grandparents, one entry per PERSON, ladder `who → relation → birth → living`. Siblings' birth years anchor *childhood*, which is where age arithmetic has least to work with; the elders are the witnesses. The people themselves go to the **entity roster** as PERSON entries carrying the relationship fact — there is no parallel family store |
| **Landmark subject** (v202) | one half-filled subject inside an enumeration domain, as its own unknown, named: "What year was Jackie born?" A domain row carries ONE `next`; every incomplete person or place gets its own |
| **Residence gap** (v202) | a hole between two dated residence spans, as its own unknown: "Where did you live between Mesa and Yucaipa, around 1992–1995?" A partial list is accepted whole; the holes persist; nothing nags |

## 3. The mechanism

The question set is **data**, not prose: `interactions/landmarks/questions.yaml`,
read by `landmarks_interaction.load_questions()`. A host asks
`landmark_rows(landmarks, keystone_domains=…)` for every domain's status and
its next question, renders only the rows that are not `complete`, and REPLAYs
`prompt/turn-instructions.md` with four substitutions: `{landmark_stage}`,
`{landmarks}`, `{next_question}`, and — v207 — `{filing_gain}`: on the turn
that actually FILED a landmark, what it just placed, said once
(`cross_dating.gain_sentence_for_record` → `render_filing_gain`). The count is
the cross-dating pass run over the current payload with the new record folded
in, so the reply can only claim what the next derivation delivers; on every
other turn it is the empty string and the prompt is byte-identical to v205's.

An answer comes back as one additive turn-output field, `landmark`, through
two validation layers — `conversation_delivery._parse_landmark` (structural,
closed key set) then `landmarks_interaction.validate_landmark` (semantic,
closed domain set, and every date normalized through
`chronology.parse_edtf` so its bounds are filled). It files through
`lifehug.py landmark-record`, which merges into the same entry by label,
because the ladder revisits the same subject over many conversations. HOW two
records combine is one function, `landmarks_interaction.merge_landmark_entry`:
normally a merge, so later rungs land on the same entry; a `none` **replaces**
what was there, and any substantive answer **clears** a standing `none`. That
is what "actually I did serve, briefly" does — the none is superseded, not
fought, and the domain reopens at the rung the new answer reaches.

A **skip** and a **none** are not the same thing and do not file the same way.
A skip is "not now": it records nothing (`landmark_invocation` returns `None`)
and the domain stays open. A none is "there is nothing here": it files
(`landmark-record <domain> --none`) because it is the answer.

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

Now the same person is asked "did you serve?" and says they never did:

```
landmark-record military --none
```

`military`'s ladder is `happened → branch → span` and its `complete_at` is
`span`, so before v203 that answer had no rung to reach and the row stayed
open forever. `rung_reached` now reports `span` for a none entry, which is the
only place the rule lives: `status_for_domain` returns `complete`, `next_rung`
returns `None`, `open_landmarks` drops the row, and a host that renders "only
the rows that are not complete" hides it without knowing the rule exists.
`anchors_from_landmarks` yields nothing for it — there is no date, so there is
nothing to anchor, and nothing is invented.

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

## Replying is not recording

Every turn here does two things, and they are not the same thing. The reply is
how it sounds. The **record** is what the turn was for. When someone answers
the domain you asked about — a fact, a name, or a plain *no* — that turn
carries a landmark, and the reply is written around it.

The way this fails is never coldness. It is warmth: they say something worth
following, you follow it, and the plain answer sitting next to it goes
unwritten. *"I never served — but I did spend two years abroad on a mission"*
is a `none` for the domain **and** a story worth taking up; the story does not
excuse the record. Neither does grief: when they name the people they have
lost, naming them back is not filing them.

If you find yourself with nothing to record on a turn where they clearly told
you something, you have mistaken the conversation for the job.

## One at a time

Ask about **one landmark domain per turn**. A turn that asks about the house
and the school and the job at once reads as an intake form and gets a shrug.

## The family you came from

The family domain is a constellation, and a constellation is made of **people**
— so they get named, never counted. "Four or five" is a fine answer and the
names can arrive one at a time; you take what comes and you keep the names you
were given. Walk it in tiers: brothers and sisters, then parents, then
grandparents. Never ask for a tier you already have.

A sibling's birth year you may ask for outright — see below. Anything else
about them comes out the same sideways way everything else does.

If someone has died, you receive it and you carry on. You do not turn the turn
into condolence, you do not ask when, and you do not treat the death as a
dating opportunity. Whether someone is still living is a thing you *learn*
from what they say, never a status question you put to them.

## Never ask for a year

The one exception in this whole system is **a person's birthday** — theirs, a
brother's, a child's. A birth date is overlearned, not reconstructed, and
asking for it directly is fine: "what year was Jackie born?" is a legitimate
question. Every other date comes out sideways — "when did you move in", "which
grades were you there", "was that before or after". If you catch yourself
typing "what year was" about anything that is not a *birth*, you are asking the
wrong question.

## Take the skip

"I don't know", "not now", "skip that one", silence on the topic — all of
these end that landmark for this conversation. You say something ordinary and
move on or stop. You never ask twice, never say "are you sure", never explain
what they are missing out on.

## "No" is an answer, and it ends the domain

Some of these questions have a real answer of *no*. Never served. No children.
Never married. That is not a gap and not a skip — it is the finished answer,
and you record it as one. Say something ordinary, and never raise that domain
again.

A skip and a no are different, and you must not confuse them. "Let's leave
that" is a skip: it ends the topic for today. "There's nothing there" is a no:
it ends the topic for good. If you cannot tell which one you heard, treat it
as a skip — a domain asked once more is a small cost; a life recorded as
childless because someone changed the subject is not.

If they later say the opposite — "actually I did serve, briefly" — take it
without comment and without pointing out that they told you otherwise. They
are the authority on their own life.

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
often complete in a witness's head and nowhere else. You learn who the
witnesses are two ways: the household rung, and the family constellation —
the parents and grandparents who were there for all of it. If the person says
they are not sure, it is right to say the list is the kind of thing a parent or
a sibling often has cold. Say it once, lightly, as an option — never as an instruction, and never
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
| The store | `timeline.load_landmarks`, `timeline.save_landmark`, `timeline.save_landmarks` (v214), `timeline.landmark_birth_date` |
| The ledger a host renders | `timeline.timeline_data()["landmarks"]`, `timeline.landmark_rows_for` |
| The gap it reveals | `timeline.timeline_data()["place_no_stories"]` |
| The gaps the SET reveals (v202) | `landmarks_interaction.incomplete_subjects` (kind `landmark_subject`), `residence_gaps` (kind `residence_gap`) → `timeline.unknowns` |
| The roster join and the witnesses (v202) | `landmarks_interaction.family_members`, `family_roster_invocations` → `lifehug.py entity-verdict … --ensure`; `witness_candidates` → `timeline.timeline_data()["witnesses"]` |
| Who asks about it (v200) | `arc_planner.collect_places_without_stories` → the `place_no_stories` arc-card intent → `landmarks_interaction.render_place_no_stories` |
| The additive output field | `conversation_delivery.TurnShape.landmark_stage`, `_parse_landmark` |
| The recorder (v212) | `system/landmark_recorder.py` — `build_recorder_prompt`, `parse_recorder_output`, `record_answer`, `recordable_keys`; leaf `interactions/landmarks/prompt/recorder.md` |
| Its blocking backstop (v212) | `landmarks_interaction.ANSWER_MUST_RECORD_LINT`, `answer_must_record`, `answer_shape`, `recording_reminder` |
| Its retryable one (v214) | `landmarks_interaction.RECORD_EVERY_ENTRY_LINT`, `records_missing_entries`, `many_records_reminder`; filing `landmark_entry_key`, `entry_superseded_by`, `unreadable_fields`, `landmark_invocations` |
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
- **A none is a first-class terminal, not a status value** (v203). It is a
  RECORD (`{"domain": …, "none": true}`) that reports the domain's own
  `complete_at` rung, so `status` keeps its three values and every host that
  already renders "not `complete`" hides the row with no change. Modeling it
  as a fourth status would have made every renderer, on every medium, learn a
  new word for "done".
- **A rung is satisfied by whatever the WRITER files it under, not only by
  a key of its own name** (v211, lifehug#219). Four rungs now read a
  neighbouring field — `span` from `date` (v199), the date grains from
  `date` (lifehug#207), `happened` from any answer at all (v203), and the
  identity rung from `label` (v211) — and all four were the same defect
  arriving in a different domain. `rung_satisfiers` is that list as data
  and the ladder-consistency guard walks it for every rung of every
  domain, so the fifth instance fails the build instead of a real vault.
  Every fix is READ-SIDE: vaults already written heal on the next read,
  and there is no migration.
- **Recording is its own pass, and its lint is the lane's only blocking one**
  (v212, ADR 0028, lifehug#221). The alternative was cheaper and is what the
  branch started as: keep one completion and lint the reply. The certification
  audit retired it — the emission instruction was already present when the
  failure happened, so strengthening the instruction cannot be certified, and
  a lint on the reply still leaves recording competing with conversing for one
  completion. The cost is named rather than buried: ONE extra `haiku-class`
  completion per landmark ANSWER, on a prompt with no identity, no behavior,
  no examples and no transcript — never on the daily question and never on a
  session that is not a landmark session. Every other `landmark_gates.*` class
  stays advisory: they describe how a turn should SOUND, and a turn that
  sounds slightly wrong is still worth sending. A turn that loses the answer
  is not.
- **The birth date lives in the landmark store**, not `profile.yaml` — one
  writer, one read path.
- **The family constellation's PEOPLE live on the entity roster, not in a
  second store** (v202). The landmark set files the *dates*; the roster holds
  the *people*, through `entity_verdict`'s existing `--relationship` /
  `--living` identity facts (ADR 0013) — which are already defined as "the
  settled facts a roster entry can carry that are NOT re-derivable from a
  refresh". `--ensure` creates the row for a relative with no answer mentions
  yet, and creates it **never page-eligible**, because ADR 0013's ≥1-mention
  floor on pages still holds: an identity fact is not a page.
- **`landmark_subject` and `residence_gap` ARE `UNKNOWN_KINDS` members** (v202)
  — unlike `place_no_stories`, which is a story gap. These two are dating
  gaps, one subject each, and they are exactly what the *unknowns are
  concrete* principle asks for: a domain row carries ONE `next`, so every
  half-filled person or place inside it becomes its own named question.
- Contracts: `docs/pr-specs/landmarks.md` (v199),
  `docs/pr-specs/family-landmark.md` (v202). Research:
  `system/research/landmarks.md` (§2.9 for the family constellation).
