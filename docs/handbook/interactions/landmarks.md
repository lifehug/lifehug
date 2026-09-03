---
title: Landmarks
parent: The Interaction Pattern
nav_order: 8
---

# Landmarks Interaction

## 1. What it does

Landmarks is the universal dating question set: the handful of dated
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
answerable whenever. It may enter the daily queue or a whisper when it passes
the shared value threshold (owner ruling R2, 2026-09-03,
`lifehug-platform docs/decisions/2026-09-03-timeline-unification/decision-record.md`;
lands in Cut 5b, tracking #573/#586); it is never a reminder, never nags, and
never appears as a count of what remains.

**Landed v286 (Cut 5a, ADR 0032): a domain leaves the surface on VALUE, not on
completion.** `system/landmark_opportunities.py` derives the gaps the
calculated graph can name — an episode with an open or missing bound, a
missing birth origin, a person the ladder enumerates with no dated anchor, an
ambiguous episode — each with Cut 3a's own `leverage`/`resolves` and a
question generated from the actual gap ("When did you move out of the Mesa
house?"), and publishes `landmark_opportunities` / `landmark_sufficiency` in
the projection. A domain whose best remaining opportunity is below the
QUEUE's dial (`timeline_leverage_per_story` in
`question_planner.DEFAULT_LANE_POLICY`, read and never copied) is `sufficient` and publishes nothing, so a
host's surface collapses on its own instead of announcing that everything is
filled in. The `status`/`complete_at` ladder below is unchanged and still
drives the collect mode; what changed is who may say a domain is *done*.

**"That never happened" is a finished answer.** Four of the nine domains —
`partnerships`, `children`, `military`, `losses` — open with a yes/no, and
*no* completes them outright. A person with no military service is DONE with
military: the row leaves the open list and is never offered again. This is the
mirror of the rule above, and it is the difference between an instrument and a
form (owner ruling 6, 2026-08-24; `landmarks.md` §5.2). `family` is *not* one
of the four — its ladder opens at `who`, and "no siblings" does not mean there
was no family. A `user_completable` list is finished by the person saying
so, which is a different fact from never having happened.

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
are multi-entry by construction — v219 declares eight of the nine
`collection: set` or `collection: sequence` — so the recorder now emits a LIST, each record is validated
on its own so a bad one never costs a good one, and a second, RETRYABLE lint
(`landmark_gates.record_every_entry`) spends the same single regeneration when
the person plainly stated more entries than came back. That branch never
withholds: it files what it has, because a partial record is worth more than
none. Each record lands as its own entry in the store, and the only prior
entries a new one retires are a standing terminal and the collapsed aggregate
— an entry carrying a field its own ladder has no rung for.

**The recorder knows what it already knows** (v216, ADR 0028 amendment). The
same class again, from the other end: the recorder's prompt has told it
*never record these again* since v212 over a block that named domain
STATUSES — `- children: partial (4)` — so it could not obey, and the names
already in the store never reached the lints either. A person going back over
their own life therefore re-emitted facts already filed, and their own filed
names came back in the reply and read as fresh evidence. The prompt now
carries the ENTRIES of the domain being asked about, one line each with its
name and its date, and the same entries supply the `known_labels` both
recording lints take. A pure restatement now files nothing in one completion;
a listed entry is recorded again only for a name it lacks or a finer date than
the one shown. The store stays the backstop — `merge_landmark_entry` is
idempotent and filing keys on the entry's own identity — so this saves a
completion and a wrong file, not a correctness invariant.

**The general listener** (v218, ADR 0029). Every trigger above is FOCUSED —
handed a domain, asked for the answer to the question that was asked. That
restriction is load-bearing and it stays: it is what keeps a mission abroad
from being filed as military service, and the design audit that proposed
repealing it rejected its own proposal. But nobody has to ask a landmark
question for someone to say a datable thing. *"We moved to Dayton the summer
after Mom died"* is a residence, a relative date and a death year, said in a
conversation about a house. So the recorder gained a SECOND TRIGGER — the
same loop with no domain — that listens to one message and returns typed
lists: landmark records of any domain, person DATES, and — from v229 —
temporal CLAIMS. Person dates are **family only**, by owner ruling, and the
rule is enforced at validation rather than in the prompt, because ADR 0028's
whole lesson is that prompt prose alone cannot be certified. For the same
reason the mode ships with its own deterministic floor: a table-driven
prescreen decides whether there could be time in the message at all, and a
listener that comes back empty when there was is a blocking lint, one
regeneration, and then a WITHHELD record a sweep can re-run. Never silence.

**Claims — every fact, one record, one receipt** (v229, the audited timeline
build plan §2.1/§6.1/§6.4 and owner amendment 2). Both passes — the focused
recorder and the listener — now also emit TEMPORAL CLAIMS in
`temporal_claims`' own vocabulary, beside the landmark records and never
instead of them. The reason is that a landmark record is a ladder row: it
belongs to a domain and carries at most one date, so *"we moved when James was
two"* had no shape and *"my neighbour's boy was born in 2019"* had no home,
and the listener leaf used to say so out loud — leave the record undated and
the arithmetic will reach it later. The arithmetic never reached it. A claim
carries a raw `subject_mention`, an `event_kind`, one temporal value (a date,
a length, or an order against another moment) and a bounded quotation without
which it is refused; one claim per independently asserted fact, so four
children are four `identity` claims and four `child_born` dated claims and
never one aggregate. The message that produced them is promoted to
`sources/conversations/` first and the claims are filed as ONE immutable
receipt over it, so no claim's only citation is a session row. The focused
recorder's LANDMARK list is still locked to the asked domain; its CLAIMS list
hears the whole message, because a focused turn has one canonical recorder and
one semantic write set.

Note how this sits beside v225's flip. That wave made the landmark ENTRY a
promoted source (`sources/landmarks/`) converted to claims by a deterministic
rule; this one makes the MESSAGE a promoted source (`sources/conversations/`)
read by a model. Two roads into one active index, and a fact said in a focused
landmark turn can travel both. They cannot collide — different source,
different revision, different extractor version, therefore different claim id
— and two claims that agree corroborate a placement rather than contend for
it, which is exactly what reconciliation at draw time is for.

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
| **Status** | `open` (nothing filed) · `partial` (filed, below target) · `complete` (at target, and — where `closure` is `user_completable` — the person said the list is finished) |
| **Entailment** | `happened` is the one rung nobody states outright. It is satisfied by anything else the entry carries (`landmarks_interaction.asserts_happened`) — you cannot name your children without having children. Without it the first rung of all four yes/no domains was unreachable, and a fully answered domain read as if nothing had been said |
| **Identity rung** (v211) | the rung whose answer IS what the entry is called — `who` for the people domains, `city`/`name`/`what`/`branch` for the rest, and nothing at all for `birth`. DERIVED as the first rung that is neither `happened` nor a date grain (`landmarks_interaction.identity_rung`), and satisfied by the name the writer files under `label` (`identity_named`). The turn contract tells the model to put "the school in `label`", so before lifehug#219 **seven of the nine domains re-asked their own opening question after a perfect answer** — the founder's four labelled children were asked "What are their names?" forever. Same class as the `span` fallback (v199) and the date grains (lifehug#207): the ladder could not read what the writer writes |
| **None terminal** | `{"domain": …, "none": true}` — the answer "that never happened". Reports the domain's `complete_at` rung, so the domain is `complete` by the same definition every other answer uses. Available only where the ladder opens at `happened` (`landmarks_interaction.domain_accepts_none`), so `partnerships`/`children`/`military`/`losses` and nothing else: `{"domain": "birth", "none": true}` would complete the axis with no date, and `family` is an enumeration, not a yes/no |
| **Cardinality block** (v219) | five fields where one boolean stood. `collection` (`singleton` · `set` · `sequence`) says HOW MANY entries and whether their order is part of the fact; `closure` (`open` · `user_completable`) says what ends the GROUP, which `complete_at` never said — it ends one ENTRY; `identity_kind` says what one entry IS (`person` · `organization` · `place` · `relationship_edge` · `episode`); `date_semantics` says which EVENTS it dates; `per_entry_ladder` says the rungs below identity are walked once per entry. The retired `chain: true` meant multiplicity, order and closure at once, so `children`, `partnerships`, `losses` and `military` — multi-entry but not walked lists — were declared `chain: false` and every consumer asking the multiplicity question got the closure answer |
| **Enumeration domain** | `landmarks_interaction.enumerates_subjects` — a domain holding many named entries, each walking its own ladder. Eight of the nine; `birth` is the singleton axis. These are the domains whose half-filled subjects each become their own unknown (v202), and v219 is what finally makes that true of the four the flag hid |
| **Anchor** | what a dated landmark becomes: a row in `timeline.anchor_index` that every later probe resolves through |
| **Keystone** | the ★ — the landmark domain that would supply the current highest-leverage anchor. With no birthday filed the star is always `birth`, because with no axis the arithmetic cannot run at all |
| **Cross-dating** | the name of the mechanic (ADR 0026): dating an undated sequence by matching it against an already-dated one. The landmarks are the dated sequence |
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
`partial` (still, because the list has not been declared finished —
`residences` is `closure: user_completable`).

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
always-open row, and a landmark question may also reach the daily queue or a
whisper by value (owner ruling R2, 2026-09-03; Cut 5b). `lifehug.py
arc-plan-target --landmarks` walks the open ones as an episode, keystone
first, then by ladder cost, with sensitive domains last.

## 5a. Add Landmark — the `offer` mode (v287, ADR 0033)

Owner rulings R3, R3a and R3b, 2026-09-03 (`lifehug-platform
docs/decisions/2026-09-03-timeline-unification/decision-record.md` §5).
`interaction.yaml` declares `modes: collect|offer`. The `collect` mode asks;
the `offer` mode is the same interaction read backwards — **the person hands
over ordinary text and the system says what it read before anything is
filed.**

```bash
echo "I lived in Mesa from 1990 to 1992." | \
    python3 system/lifehug.py landmark-offer --propose
python3 system/lifehug.py landmark-offer --apply lmo:… --all
python3 system/lifehug.py landmark-offer --retract lmr:…
```

`--propose` files no landmark. It writes ONE file,
`state/landmarks/offers/<proposal_id>.json`, which carries the submitted text
from the moment it is submitted — evidence is durable before confirmation
(R3), landmarks are not — plus the units, the stories, the spans nothing
recognized, and the open questions. It writes that file on failure too, so a
provider outage never costs the person their words.

**Three passes, none of them new.** A deterministic block grammar runs first
over text it fully matches (zero model calls, so a thirty-block residence
document costs nothing); then the general listener (§7, ADR 0029) with no
domain; then the focused recorder (§6, ADR 0028) once per domain the listener
named, with `{known_entries}` in view — which is what makes a second stay in a
city the vault already knows a second entry rather than a merge.

**Stated versus inferred is decided from the bytes**, not from the completion
(decision record §4.2). `landmark_offer.date_evidence` re-reads every bound of
every proposed date against the person's own text — the year in full
(`1990`) or in the two-digit form people write (`'91`), and a finer grain with
its month named. A bound the text carries files `basis: stated`; a bound it
does not carries `confidence: inferred` and a verbatim inferred provenance
clause, whatever the model declared.

**Filing is the road an answer already takes.** A confirmed unit files through
`timeline.save_landmark`, so an offer and an answer are indistinguishable
downstream. Identity is `(proposal_id, unit_id)` through the existing
`digest_override` seam — never a filing ordinal — so `--apply` twice files
nothing twice and reads the standing receipt back. The receipt carries Cut
4c's realized-gain sentence and says which Cut 5a opportunities closed.
`--retract` files a durable retraction over exactly the claims the filed units
stand on and republishes; the evidence, the receipts and the proposal all stay
on disk.

**Nothing is dropped and nothing is refused.** Every span of a submission is a
unit's quote, a story, or an explicitly unrecognized span, and a lint asserts
the three cover the text between them. Non-landmark text is routed as a story
and the worker says so (R3a).

The manifest gains three deterministic blocks (§5.2): the roster with its
aliases, the published projection's episodes and eras with their spans, and
the age frames with the birth origin they are counted from —
`landmarks_interaction.render_roster` / `render_known_spans` /
`render_age_frames`. The model interprets; it does not fetch.

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
| The recorder (v212; v216 known entries) | `system/landmark_recorder.py` — `build_recorder_prompt`, `parse_recorder_output`, `record_answer`, `recordable_keys`; leaf `interactions/landmarks/prompt/recorder.md`. The already-filed block and the lints' names: `landmarks_interaction.render_known_entries`, `known_entry_labels`, `landmark_entries`, `render_entry`, `entry_name` |
| Its blocking backstop (v212) | `landmarks_interaction.ANSWER_MUST_RECORD_LINT`, `answer_must_record`, `answer_shape`, `recording_reminder` |
| Its retryable one (v214) | `landmarks_interaction.RECORD_EVERY_ENTRY_LINT`, `records_missing_entries`, `many_records_reminder`; filing `landmark_entry_key`, `entry_superseded_by`, `unreadable_fields`, `landmark_invocations` |
| The warrant a date carries (v222) | `chronology.date_argv` / `date_from_argv`, `WARRANT_FIELDS`, `date_flag_names`; `lifehug.py landmark-record --basis/--granularity/--confidence/--anchor/--provenance`, and the same five under `--start-` and `--end-` |
| Two stays at one address (v277) | `landmarks_interaction.same_landmark_stay`, `entry_stay_interval`, `SEQUENCE_ENTRY_ABUT_MONTHS`; applied in the fold by `landmark_projection.stay_slots`, so the frontmatter key never moves and no promoted source is rewritten. `chronology.overlap_months` / `gap_months` are the one arithmetic behind it and behind `temporal_timeline`'s `residence_overlap` |
| One home at a time (v277) | `temporal_timeline.RESIDENCE_MOVE_TOLERANCE_MONTHS`, `_residence_overlaps`, `compose_residence_overlap_question`; the work-item kind `residence_overlap`; retiring ONE stay is `landmark_projection.retire_entry(slot=…)` |
| Two dates for one entry (v222) | `merge_landmark_entry` → `chronology.reconcile`; `landmarks_interaction.DATE_ALTERNATES_KEY`, `SPAN_ALTERNATES_KEY`, `landmark_date`; `chronology.merge_claims`, `conflict_strength` |
| The general listener (v218) | `landmark_recorder.listen_to_answer` = `record_answer(domain=None, …)`; `system/general_listener.py` — `build_listener_prompt`, `parse_listener_output`, `render_domain_digest`, `render_all_known_entries`; leaf `interactions/landmarks/prompt/listener.md` |
| Its prescreen (v218) | `general_listener.may_contain_datable` over `PRESCREEN_TABLES` — `chronology.YEAR_RE`/`MONTH_NAMES`/`NUMBER_WORDS`, `cross_dating.AGE_STATEMENT_RES`/`AGE_BAND_AGES`, `recommend_focuses.TIME_PERIOD_PATTERNS`, plus `DECADE_RE`, `DURATION_RES`, `BECOMING_RES`, `THIRD_PERSON_AGE_RES`, `ANCHOR_RELATIVE_RES` |
| Its backstop (v218) | `general_listener.LISTENER_HEARD_NOTHING_LINT`, `listener_heard_nothing`, `listening_reminder`, `store_terms` |
| Its person dates (v218) | `general_listener.validate_person_record`, `person_invocations`; `landmarks_interaction.person_date_relations`, `NON_FAMILY_RELATIONS`, `person_slug`, `date_flags` |
| Claims, both passes (v229) | `general_listener.CLAIM_PROMPT_KEYS`, `validate_claim_draft`, `parse_claims`, `bind_claims`, `render_event_kinds`, `claim_refused`; `landmark_recorder.parse_recorder_claims`, `RecorderOutcome.claims`. The contract is `system/temporal_claims.py` — one door, one vocabulary |
| Their retryable lint (v229) | `general_listener.CLAIMS_MISSING_SUBJECTS_LINT`, `claims_missing_subjects`, `every_claim_reminder` — a BINDING of v214's `_name_groups`/`_record_terms`, never a second copy |
| Their write path (v229) | `landmark_recorder.file_claims` over `temporal_store.file_message_extraction`; the extractor's identity is `recorder_extractor`/`listener_extractor` + `general_listener.leaf_prompt_version`, so editing a leaf is a NEW extractor and a new receipt |
| The `offer` mode (v287, ADR 0033) | `system/landmark_offer.py`: `propose(text, vault_root, call=…)` → the proposal (units with `unit_id`, `domain`, `kind`, `subject`, `entity_candidates`, `dates`, `quote`, `duplicates`, `conflicts`, `questions`, `auto_file_eligible`, `record`; plus `stories`, `unrecognized`, `questions`) · `apply(proposal_id, unit_ids, vault_root)` → the receipt, idempotent on `(proposal_id, unit_id)` through `timeline.save_landmark`'s `digest_override` · `retract(receipt_id, vault_root)` through `temporal_store.retract_claims` · `date_evidence` (the stated/inferred rule, read off the bytes) · `lint_offer_proposal` / `lint_offer_reply` / `OFFER_LINT_CLASSES` · `build_offer_turn` / `render_proposal` / `render_open_questions` for the leaf's `{proposed_units}` and `{open_questions}` · `offer_context` for the three manifest blocks · `OFFER_STATES`, `FAILURE_CLASSES`. Leaf: `prompt/turn-instructions-offer.md`; slot: `composition.offer_turn`; role: `role.worker`. Data: `state/landmarks/offers/` |
| Its internal extractors (v287) | `system/go_dig_grammar.py` (the deterministic block grammar; no model) and `go_dig_writer.plan_import`/`record_unit`, reached ONLY through `landmark_offer` — retained under owner ruling R4 as extractors, with nothing user-facing naming the product they came from |
| The verbs | `lifehug.py landmark-record`, `lifehug.py landmark-offer --propose\|--apply\|--retract` (v287), `lifehug.py arc-plan-target --landmarks`, `lifehug.py landmarks-evals` |
| Tests | `tests/test_landmarks.py`, `tests/test_general_listener.py`, `tests/test_extraction_claims.py`, `tests/test_landmark_offer.py` (v287), `tests/test_go_dig.py` |

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
- **A person's OWN two dates are settled identity facts too** (v217).
  `entity-verdict --born/--died` writes them, and they join
  `_SETTLED_IDENTITY_FIELDS`, so a roster refresh cannot drop them. The join
  now emits them: a family member's stated birth year rides along as
  `--born`, and the people named in `losses` reach the roster at all for the
  first time, carrying `--died` and `--not-living`. The rows are still never
  page-eligible on creation — nothing about a loss is published by this join.
- **One anchor per person per fact** (v217). A family landmark's birth date
  and the roster's `born` are the same fact in two stores, so
  `anchors_from_people` skips the roster copy whenever the landmark store
  already anchors it: the landmark store is the source of truth, the roster
  row is its derived copy, and there is no reconciler because there is
  nothing to reconcile.
- **`landmark_subject` and `residence_gap` ARE `UNKNOWN_KINDS` members** (v202)
  — unlike `place_no_stories`, which is a story gap. These two are dating
  gaps, one subject each, and they are exactly what the *unknowns are
  concrete* principle asks for: a domain row carries ONE `next`, so every
  half-filled person or place inside it becomes its own named question.
- Contracts: `docs/pr-specs/landmarks.md` (v199),
  `docs/pr-specs/family-landmark.md` (v202). Research:
  `system/research/landmarks.md` (§2.9 for the family constellation).
