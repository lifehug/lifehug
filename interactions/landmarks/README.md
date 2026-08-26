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

**Recording is not replying** (v212, ADR 0028, lifehug#221). Two live
sessions came back warm, engaged, and empty: a plain *"I have not served"*
answered with a mission story and no `none` filed, and the names of people
lost said back and never recorded. The certification audit found the decisive
fact — the instruction telling the model to record was ALREADY in that leaf
when it happened. Prose cannot be certified; only a deterministic pass can.

So the recording is its own pass. The conversation writes the reply; the
**recorder** (`system/landmark_recorder.py`, leaf
`prompt/recorder.md`, `role.recorder`) reads the person's own message
afterwards and files the record. It has no voice, no transcript, no identity
block and no examples — only the domain, its ladder, what was asked, what they
said, and what they were told back. **One recorder, two triggers:**
`record_answer(...)` is what a live landmark turn calls after its reply is
generated, and what a historical sweep calls over answers people already gave,
so the sweep inherits the backstop instead of re-rolling the same dice.

**The recorder knows what it already knows** (v216, lifehug#230). Its prompt
carries the entries ALREADY FILED for the domain being asked about — one line
each, name and date (`render_known_entries`) — because the heading it has
carried since v212 said *never record these again* over a block that named
only domain STATUSES, and a model cannot decline to re-file four children it
has never been shown. The same entries supply `known_labels`
(`known_entry_labels`), which both recording lints take precisely so a name
the model was handed is not read back as the person's own fresh evidence. A
person going back over their own life now costs ONE completion and files
nothing; before, it cost two and came back withheld.

Its backstop is `landmark_gates.answer_must_record` — the lane's ONE blocking
lint — plus exactly one regeneration carrying `recording_reminder()`. A second
empty pass is a WITHHELD record a host can retry, never a silent drop and
never a fabricated one. Detection is deliberately narrow: a skip wins
outright, a negative counts only where a none can be recorded, and
"substantive" means the reply echoed a name or a year the person supplied in
that same message. An answer with neither is invisible to the class on
purpose — the class blocks, so ambiguity fails toward skip
(`landmarks_interaction.answer_shape`). Because the recorder never needed the
reply, a turn whose reply generation FAILED still records.

**One answer, many records** (v214, ADR 0028 amendment, lifehug#227). One day
later the same vault produced the next failure in the class: a work answer
naming about twelve jobs was WITHHELD, because the recorder's output could
carry one record; and four children with four exact birth dates were
collapsed into one aggregate entry carrying a `span` the `children` ladder has
no rung for. Children, work, residences, family, partnerships and losses are
all multi-entry domains. So the canonical output is
`{"landmarks": [ ... ]}` — v212's `{"landmark": {...}}` still parses to a
one-element set — each record runs BOTH validation layers alone so an invalid
one drops without its siblings, and `RECORDED` means at least one validated.
The second, RETRYABLE class `landmark_gates.record_every_entry`
(`records_missing_entries`) fires on two decidable shapes only — unrecorded
proper-noun groups, and unrecorded years on a domain that dates each entry
separately — never on a terminal and never on `birth`. It spends the SAME one
regeneration and then files what it has: it can never withhold, because a
partial record is worth more than none. Filing is per entry
(`timeline.save_landmarks`, `landmark_invocations`), keyed on
`landmark_entry_key`, and `entry_superseded_by` retires only a standing
terminal or an entry carrying a field its own ladder cannot read
(`unreadable_fields`).

**The general listener** (v218, ADR 0029). Every trigger above is FOCUSED —
handed a domain, asked for the answer to the question that was asked — and
that restriction stays exactly where it is: *"something else in the same
breath never excuses the domain's own answer"* is what stops a two-year
mission abroad being filed as military service, and the 2026-08-25 audit
rejected its own proposal to repeal it. But people say datable things when
nobody asked. So `record_answer(domain=None, ...)` — named
`listen_to_answer` — is a SECOND TRIGGER on the SAME loop, with a leaf
(`prompt/listener.md`, `role.listener`), a parse and a backstop swapped and
nothing else. There is no second loop. Its output is TYPED LISTS —
`{"landmarks": [...], "people": [...]}`: landmark records of ANY domain
through both pinned validators alone, and person DATES filing through v217's
roster seam. **Person dates are FAMILY ONLY** (owner ruling): a record whose
relation is absent or not family is dropped at validation with a named
finding, never filed, and the guard does not depend on the leaf obeying the
rule. Its backstop is `landmark_gates.listener_heard_nothing` — the
deterministic prescreen `general_listener.may_contain_datable` saw time in the
message and nothing came back — with the SAME one regeneration and then a
WITHHELD record a host sweep can re-run. There is deliberately no
`placements` list: moment identity for prose is phase 2.

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
| The conversation's `{landmarks}` block | `landmarks_interaction.render_landmarks(rows)` — one line per DOMAIN, status only |
| The recorder's `{known_entries}` block (v216) | `landmarks_interaction.render_known_entries(landmarks, domain)` — one line per filed ENTRY of the domain being asked about, from `landmark_entries` through `render_entry` (`entry_name` + the ladder's own date), bounded by `KNOWN_ENTRIES_LIMIT`. A status line is the right thing to show someone deciding what to ASK and the wrong thing to show a machine deciding what to FILE |
| The names both lints must already know (v216) | `landmarks_interaction.known_entry_labels(landmarks, domain, extra=…)` — ONE derivation for the block, `answer_must_record`/`answer_shape` and `records_missing_entries`; `record_answer` derives it from the store it was given instead of taking it hand-passed (which is to say empty) |
| The one additive turn-output field | `conversation_delivery.parse_turn_output(...)["landmark"]`, enabled by `TurnShape(landmark_stage=…)` |
| Closed validation of that field | `landmarks_interaction.validate_landmark(value)` |
| The seven landmark lints | `landmarks_interaction.lint_landmark_reply(text, stage=…, domain=…, sensitive=…, domains_named=…, landmark=…, user_message=…, known_labels=…)`; `landmarks_interaction.LANDMARK_LINT_CLASSES`. The sixth, `never_proposes_a_date`, is SHARED — its one definition is `timeline_interaction.proposes_a_date`, run by both lanes |
| The recorder (v212, ADR 0028; v214 many-records; v216 known entries) | `landmark_recorder.build_recorder_prompt(domain=…, question_asked=…, answer=…, reply=…, landmarks=…, reminder=…)` — `landmarks` is the LANDMARKS store (or the domain's own entries) and fills the ALREADY-FILED block · `parse_recorder_output(raw)` → `tuple[dict, ...]` (BOTH pinned validation layers, PER RECORD) · `record_answer(…, call=…)` — the whole loop, with the model injected · `recordable_keys(row)` — the only keys this domain can READ, walked from v211's own `landmarks_interaction.rung_satisfiers` and intersected with what both validation layers keep (the writer-side half of #219/#220: no `span` on `children`, no `label` on `birth`, no `name` on `children`, no `birth` key on `family`). Leaf: `prompt/recorder.md`; role: `role.recorder`. **Platform wiring:** the engine calls the recorder AFTER the reply is generated and files through the same durable path the live turn files through; the landmark re-harvest calls the SAME function instead of re-composing the live turn prompt |
| The one BLOCKING lint, and its retry (v212) | `landmarks_interaction.ANSWER_MUST_RECORD_LINT`, raised from `answer_must_record(user_message, record, reply=…, domain=…, known_labels=…)` — ONE definition, run by the recorder as its backstop and by `lint_landmark_reply` for a host still reading the reply's own field. On a finding, regenerate ONCE with `recording_reminder(domain)` appended (`landmark_recorder.MAX_ATTEMPTS = 2`), then emit or withhold |
| The general listener (v218, ADR 0029) | `landmark_recorder.listen_to_answer(answer=…, reply=…, landmarks=…, call=…)` — `record_answer(domain=None, …)`, the SAME loop · `general_listener.build_listener_prompt` / `parse_listener_output` → `Heard(landmarks, people, findings)` · `render_domain_digest()` — the nine domains as nine `domain: key | key` lines, from `landmark_recorder.recordable_keys`, never nine pasted ladders · `render_all_known_entries(landmarks)` — v216's block for EVERY domain, capped at `KNOWN_PER_DOMAIN` per domain and `KNOWN_TOTAL` in all. Leaf: `prompt/listener.md`; role: `role.listener`. Purpose: `DATE_RECORD_PURPOSE` (`"date_record"`), a SECOND name beside `LANDMARK_RECORD_PURPOSE` |
| The listener's prescreen (v218) | `general_listener.may_contain_datable(text) -> Verdict(fired, reasons, terms)` — deterministic and table-driven, DERIVED: `chronology.YEAR_RE`/`MONTH_NAMES`/`NUMBER_WORDS`, `cross_dating.AGE_STATEMENT_RES`/`AGE_BAND_AGES`, `recommend_focuses.TIME_PERIOD_PATTERNS`, plus this module's own four (`DURATION_RES`, `BECOMING_RES`, `THIRD_PERSON_AGE_RES`, `ANCHOR_RELATIVE_RES`, `DECADE_RE`). `_sentence_normalized` lets the borrowed case-sensitive tables read a whole message without being re-typed |
| The listener's backstop (v218) | `general_listener.LISTENER_HEARD_NOTHING_LINT` from `listener_heard_nothing(user_message, records, people, findings=…, landmarks=…, verdict=…)`, its regeneration `listening_reminder(verdict)`. Cleared by a decline (`answer_shape`), by a `DROPPED_NON_FAMILY` finding, or by a restatement (`store_terms`, v216's dedupe in the no-focus mode) |
| Person dates from the listener (v218) | `general_listener.validate_person_record(value) -> (record, finding)` — FAMILY ONLY against `landmarks_interaction.person_date_relations()` (the roster vocabulary minus `NON_FAMILY_RELATIONS`), dates through `entity_verdict.parse_person_date` · `person_invocations(people)` → `lifehug.py entity-verdict … --born/--died`, with `landmarks_interaction.date_flags` and `person_slug` shared with v217's own roster join |
| One answer, many records (v214) | Output `{"landmarks": [ ... ]}`; `RecorderOutcome.records` (`.record` = the first, for v212 callers). The RETRYABLE class `landmarks_interaction.RECORD_EVERY_ENTRY_LINT` from `records_missing_entries(user_message, records, reply=…, domain=…, known_labels=…)`, its regeneration `many_records_reminder(domain, count)` — the SAME single retry, and it files what it has either way. Filing: `landmark_entry_key`, `entry_superseded_by`, `unreadable_fields`, `landmark_invocations` → `timeline.save_landmarks` |
| Filing an accepted landmark | `landmarks_interaction.landmark_invocation(record)` → `lifehug.py landmark-record` |
| The warrant that travels with a date (v220) | `chronology.date_argv(record, value_flag=…, meta_prefix=…)` / `date_from_argv(…)` — exact inverses, and the ONE definition of how a `DateRecord` crosses a process boundary. `WARRANT_FIELDS` names the five an EDTF expression cannot carry (`basis`, `granularity`, `confidence`, `anchors`, `provenance`); `date_flag_names(prefix)` names the flags. Each of `--date` / `--start` / `--end` carries its own under its own prefix, because the two ends of a span are two separate claims |
| Two dates for one entry (v220) | `merge_landmark_entry` sends `date`, `span.start` and `span.end` through `chronology.reconcile`; the claims it does not pick are kept under `DATE_ALTERNATES_KEY` / `SPAN_ALTERNATES_KEY` and read back by `landmarks_interaction.landmark_date(entry, bound=…)`. The entry-level dict merge and the none terminal are unchanged |
| The durable store | `timeline.load_landmarks()`, `timeline.save_landmark(domain, record)`, `timeline.landmark_birth_date()` |
| The anchors they become | `landmarks_interaction.anchors_from_landmarks(landmarks)`; `anchors_from_people(people, landmarks)` (v217 — a roster person's `born`/`died` as `person:<slug>:born|died`, skipping any fact the landmark store already anchors, which is the whole `entity_date` unlock); `timeline_interaction.anchors_for_person(landmarks=…, people=…)` |
| The gap they reveal | `landmarks_interaction.places_without_stories(landmarks, event_places=…)`, `PLACE_NO_STORIES_KIND`; `timeline.timeline_data()["place_no_stories"]` |
| The gaps the SET reveals (v202) | `landmarks_interaction.incomplete_subjects(landmarks)` → `LANDMARK_SUBJECT_KIND`, one NAMED unknown per half-filled subject in an ENUMERATION domain (v219: `landmarks_interaction.enumerates_subjects` — `collection` is `set`/`sequence`, the ladder is `per_entry_ladder`, and the domain names its subjects; eight of the nine); `residence_gaps(landmarks)` → `RESIDENCE_GAP_KIND`, one per interior hole between two dated residence spans. Both reach `timeline.unknowns()` carrying the ladder's own subject-named question |
| The roster join and the witnesses (v202; v217 person dates) | `landmarks_interaction.family_members`, `lost_people(landmarks)`, `person_roster_invocations(landmarks)` (pre-v217 name `family_roster_invocations`, the same function) → `lifehug.py entity-verdict person <slug> clear [--relationship …] [--living|--not-living] [--born <edtf> --born-basis …] [--died <edtf> --died-basis …] --ensure`. The family tiers carry their STATED BIRTH YEAR (`--born`) and the `losses` people finally reach the roster at all, carrying `--died` and `--not-living`; `witness_candidates(landmarks)`, `timeline.timeline_data()["witnesses"]` |
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
