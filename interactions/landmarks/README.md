# Landmarks Interaction

`landmarks` is an independently registered, auditable Interaction for the
**always-present dating question set**. It exact-composes Conversation by
reference and owns only the one goal Conversation cannot carry: **collect the
small set of dated facts that makes every other memory cheap to place.**

**We built the arithmetic before the inputs.** v195 shipped
`chronology.from_age`, `from_anchor` and `intersect`; v196 shipped the
keystone that ranks over them. But `birth_date` was a parameter no production
caller ever passed, `profile.yaml` had no birth field, and the two cheapest
rungs of the elicitation playbook (`sequence`, `landmark`) are marked
`needs_anchor` over an index that was nearly always empty. This Interaction is
the missing input (`system/research/landmarks.md` §3.7).

**Three of these domains are closed lists.** Every address in order, every
school in order, and — since v202 — every member of the family you came from,
are enumerable, finite, verifiable and *finishable*. The first two tile the
whole timeline and are the coarse containers every finer interval propagates
inside (Allen 1983's "reference intervals"); the third is the one made of
**people**, so its members go to the entity roster as PERSON entries with the
relationship fact rather than into a parallel store. All three are domains a
living relative can supply outright — and the family domain is where we learn
**who those relatives are**. Everything else is an open set. That asymmetry is
why family, residences and schools come first (`landmarks.md` §2.7 + §2.9).

**A vague answer is an answer.** "Somewhere outside Dayton, the eighties"
bounds everything it overlaps. The **specificity ladder** — city → address →
span → household — exists because *more* would unlock more, not because less
is a failure. SHARELIFE says it plainly for residences: "If cannot estimate,
ask for the decade and enter the mid year."

**An open landmark is a resting state, not a debt** (owner ruling 2). A
landmark that is unanswered or below its target rung stays open on the
Timeline forever, answerable at any time, and never enters the daily question
queue. No reminders. No counts in prose. The `landmark_gates.no_form_voice`
lint is the mechanical form of that rule.

**Never ask for a year — except a person's birthday.** A birth date is
overlearned semantic knowledge, not a reconstruction, and every fielded
life-history instrument takes it first because the calendar's axis starts there
(SHARELIFE ST006/ST007, NLSY97's "month the respondent turned 14"). Every other
date comes out sideways. v202 draws out the consequence the carve-out always
had: it is about the KIND of fact, not whose fact it is, so "what year was
Jackie born?" is legitimate for a sibling or a child too.
`landmark_gates.no_year_demand` suspends for exactly
`landmarks_interaction.YEAR_OPENER_DOMAINS` — `birth`, `family`, `children`
(`landmarks.md` §2.1 + §2.9).

**Never propose a date.** Reporting the arithmetic is right — "anything at
the Bell house lands between '84 and '90 now" states a derivation and shows its
working. Naming a date and asking for agreement is forbidden in every domain,
including the birthday: true photographs plus suggestive interviewing produce
false memories in about two thirds of participants, and a dating probe backed
by the person's own evidence is that configuration exactly
(`system/research/go-deep.md` §4.3, Lindsay et al. 2004). The lint is shared
with the timeline lane from one definition.

**The mechanic has a name: cross-dating** — dating an undated sequence by
matching it against an already-dated one. The landmarks are the dated
sequence. And a **witness** is someone living who was there: learned from the
residence ladder's own `household` rung, so no new state, and carried on every
`place_no_stories` row, because the people who were in the house are exactly
the people who can answer about it.

**The gap only a landmark can reveal.** v196's `place_span` unknown asks *when*
you lived somewhere. Nothing could ask what *happened* there, because nothing
knew the place existed. A residence with a known span and no moments attached
is a `place_no_stories` row — a story gap, not a dating gap, and the second
payoff of the whole set.

**Passive users are untouched.** The daily single question keeps working
exactly as it did; this Interaction runs only when a landmark is Played.
Mechanically: `TurnShape.landmark_stage` defaults to `None` and the output
contract is then byte-identical to v196.

**Platform twin.** A host REPLAYs this package and reads exactly these —
nothing else is a contract (the shared shape: `interactions/README.md`
§ "The child-interaction paradigm"):

| What | Where |
|---|---|
| The question set, as data | `interactions/landmarks/questions.yaml`; `landmarks_interaction.load_questions()`, `domain_row`, `onboarding_domains` |
| The specificity ladder | `landmarks_interaction.rung_reached`, `next_rung`, `RUNG_TEXTS`, `LADDER_COST` |
| The ledger a host renders | `landmarks_interaction.landmark_rows(landmarks, keystone_domains=…)`, `open_landmarks(rows)`; `timeline.timeline_data()["landmarks"]` |
| The `{landmark_stage}` this turn is in | `landmarks_interaction.landmark_stage_for_session(session, user_leaving=…, all_settled=…, skip_streak=…)` |
| The `{landmarks}` block | `landmarks_interaction.render_landmarks(rows)` |
| The one additive turn-output field | `conversation_delivery.parse_turn_output(...)["landmark"]`, enabled by `TurnShape(landmark_stage=…)` |
| Closed validation of that field | `landmarks_interaction.validate_landmark(value)` |
| The six landmark lints | `landmarks_interaction.lint_landmark_reply(text, stage=…, domain=…, sensitive=…, domains_named=…)`; `landmarks_interaction.LANDMARK_LINT_CLASSES`. The sixth, `never_proposes_a_date`, is SHARED — its one definition is `timeline_interaction.proposes_a_date`, run by both lanes |
| Filing an accepted landmark | `landmarks_interaction.landmark_invocation(record)` → `lifehug.py landmark-record` |
| The durable store | `timeline.load_landmarks()`, `timeline.save_landmark(domain, record)`, `timeline.landmark_birth_date()` |
| The anchors they become | `landmarks_interaction.anchors_from_landmarks(landmarks)`; `timeline_interaction.anchors_for_person(landmarks=…)` |
| The gap they reveal | `landmarks_interaction.places_without_stories(landmarks, event_places=…)`, `PLACE_NO_STORIES_KIND`; `timeline.timeline_data()["place_no_stories"]` |
| The gaps the SET reveals (v202) | `landmarks_interaction.incomplete_subjects(landmarks)` → `LANDMARK_SUBJECT_KIND`, one NAMED unknown per half-filled subject in a `chain: true` domain; `residence_gaps(landmarks)` → `RESIDENCE_GAP_KIND`, one per interior hole between two dated residence spans. Both reach `timeline.unknowns()` carrying the ladder's own subject-named question |
| The roster join and the witnesses (v202) | `landmarks_interaction.family_members`, `family_roster_invocations(landmarks)` → `lifehug.py entity-verdict person <slug> clear --relationship … [--living|--not-living] --ensure`; `witness_candidates(landmarks)`, `timeline.timeline_data()["witnesses"]` |
| The filing beat's one sentence (v207) | `cross_dating.gain_sentence_for_record(record, timeline_payload)` → `cross_dating.render_filing_gain(sentence)` for the `{filing_gain}` slot; the moment clause is `cross_dating.moment_clause`, the SAME definition `reading_room.placement_gain_sentence` says. **Platform wiring:** the engine fills the kwarg AFTER it files the turn's record, from the timeline payload it already holds, and passes `""` (or omits it) on every other turn — the substitution is additive and the prompt is byte-identical without it. |
| The leaf the caller REPLAYs verbatim | `prompt/turn-instructions.md`, substituting `{landmark_stage}`, `{landmarks}`, `{next_question}`, `{filing_gain}` |
| The read-only plan verb | `lifehug.py arc-plan-target --landmarks [--json]` |
| The write verb | `lifehug.py landmark-record <domain> [--label …] [--date <edtf>] [--start <edtf>] [--end <edtf>] [--city …] [--address …] [--relation …] [--birth-order …] [--living\|--not-living] [--complete] [--none]` |

The FILING of a landmark is entirely host-side: the package names it, the host
writes it.

Run the deterministic seat gate with:

```bash
python3 system/lifehug.py landmarks-evals --json
```

See `docs/pr-specs/landmarks.md` (v199) and `system/research/landmarks.md`.
