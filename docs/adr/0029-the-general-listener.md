# ADR 0029: The general listener — the system hears time

Date: 2026-08-25
Status: proposed
Extends: ADR 0028 (the landmark recorder) and its v214 / v216 amendments
Issue: the audited date-capture design, "one recorder, three triggers" (wave 2)

## Context

ADR 0028 settled how a fact gets filed: **recording is its own pass**, with
its own prompt, its own model call and its own blocking backstop, because one
completion doing two jobs — be good company, and file a fact — loses the
second one when they compete. Its v214 amendment made the pass speak in record
SETS, and its v216 amendment showed it what it already knows.

Every one of those triggers is FOCUSED. The recorder is handed a domain, shown
that domain's ladder and that domain's filed entries, and asked to record the
answer to the question that was asked. The 2026-08-25 adversarial audit of
this wave's design proposed repealing that restriction — letting a focused
landmark session record off-domain facts too — and **the repeal was rejected.**
It is rejected here as well, in the strongest terms the code can state it:
*"Something else in the same breath never excuses the domain's own answer"* is
the sentence that stops a two-year mission abroad being filed as military
service, and a focused session that starts collecting whatever floats past
loses it. **The focus rules of landmark sessions are untouched by this ADR.**

But people say datable things when nobody asked them a landmark question.

> *"We moved to Dayton the summer after Mom died."*

That is a residence, an anchor-relative date, and a death year, said in a
conversation about a house. Nothing in the package listened. Every date the
system holds came in through a landmark question, a `timeline-place`, or the
classifier's own claim on a story — three doors, all of which require somebody
to have gone looking.

## Decision

**The general listener is a second TRIGGER on the recorder's one loop, not a
second recorder.**

1. **No-focus mode.** `landmark_recorder.record_answer(domain=None, ...)` —
   with `landmark_recorder.listen_to_answer(...)` as its named door — runs
   the SAME attempt/lint/retry body as the focused mode. `MAX_ATTEMPTS` is
   the same 2, the single retry is the same single retry, and
   `STATUS_WITHHELD` is the same terminal. Three things are swapped and
   nothing else is: the leaf (`interactions/landmarks/prompt/listener.md`),
   the parse (`general_listener.parse_listener_output`), and the backstop
   (`general_listener.listener_heard_nothing`). **There is no second loop**,
   and a proposal that adds one is this ADR being undone.

2. **Typed lists, never a heterogeneous records list.** The output is
   `{"landmarks": [...], "people": [...]}`.

   * `landmarks` are ordinary landmark records of ANY domain, each through
     BOTH pinned validators (`conversation_delivery._parse_landmark` then
     `landmarks_interaction.validate_landmark`) ALONE, exactly as v214 runs
     them. The restriction to the asked domain was always a property of
     FOCUSED mode, never of the vocabulary — nothing about what a landmark
     IS changes here.
   * `people` are person DATES — `{name, relation, born|died, basis}` — and
     they file through v217's roster seam, `entity-verdict --born/--died`,
     via `general_listener.person_invocations`. Not a second store, not a
     second date reader: `entity_verdict.parse_person_date` is the one door,
     and it is `chronology.parse_edtf` + `chronology.normalized_date`, which
     is what `landmark-record --date` has always been.

   There is deliberately **no `placements` list**. Deciding WHICH sentence of
   somebody's prose a date belongs to is moment identity, it is a different
   and harder problem, and it is phase 2. It is named here rather than
   half-built.

3. **Person dates are FAMILY ONLY (owner ruling).** A `people` record whose
   `relation` is absent, or is not a family relation, is **dropped at
   validation with a named finding** (`person_relation_not_family`) and never
   filed. The leaf is taught the rule; the guard does not depend on the leaf
   obeying it, which is ADR 0028's whole lesson. A non-family person's date
   is not lost information — it is anchor evidence for the timeline, and it
   is simply not a roster row.

   The set is DERIVED, not listed: `landmarks_interaction.person_date_relations()`
   is the roster's own closed vocabulary (`focus_candidate.FOCUS_RELATIONSHIPS`)
   minus `NON_FAMILY_RELATIONS` = {friend, colleague, mentor, other}. The
   exclusion is named rather than the inclusion so that a relationship added
   to that vocabulary lands on the FAMILY side and a test has to say
   otherwise — the failure that matters is a stranger's birthday reaching the
   roster, and defaulting the other way would make that failure the silent
   one.

4. **The prescreen is deterministic, table-driven, and derived from the
   repo's own tables.** `general_listener.may_contain_datable(text) ->
   Verdict` answers one question — *could there be a datable fact in here?* —
   and never decides what the date IS. It exists so the backstop has
   something to compare a silent listener against.

   Before v218 the package held five overlapping ways of noticing time and
   the four-digit-year pattern existed **three times over**. A sixth parallel
   list is exactly the recurring defect (docs/BUILDING.md §7), so v218
   promotes the shared tables to one home each and the prescreen reads them
   by name:

   | evidence | table | home |
   |---|---|---|
   | years, decades | `YEAR_RE` (promoted; the three private copies now read it), `DECADE_RE` | `chronology` |
   | month names | `MONTH_NAMES` (promoted from `_MONTH_NAMES`) | `chronology` |
   | ages | `AGE_STATEMENT_RES` (promoted), with its own exclusions — `at N%`, `at N:MM`, `at N Elm Street`, `at Nth` are NOT ages and that judgment is not re-typed | `cross_dating` |
   | number words | `NUMBER_WORDS` | `chronology` |
   | life stages | `TIME_PERIOD_PATTERNS`, `AGE_BAND_AGES` | `recommend_focuses`, `cross_dating` |

   Four shapes had no reader anywhere and are this module's own, exported and
   eval-pinned: **duration** ("three years back" — `back` beside `ago`),
   **becoming** ("turning forty"), **third-person age** ("until she was
   nine" — every borrowed age table is first-person, because every existing
   caller was dating the subject's own moment), and **anchor-relative** ("the
   summer after we moved", "when Ivo was born"), which the owner's
   relative-dates ruling makes evidence in its own right.

   One shared mechanic makes the borrowing work: `_sentence_normalized` folds
   each sentence's OPENING capital down before the borrowed tables run.
   Those tables were written for prose read mid-sentence — `cross_dating`'s
   "at 19" rung is case-sensitive precisely because it is guarding against
   "at 19 Elm Street" — and a message can open with "At 19 I shipped out".
   Normalizing the text rather than re-typing the patterns keeps every
   exclusion they carry: "At 19 Elm Street" is still correctly refused. It is
   `_echo_terms`' own doctrine read the other way round.

   `May` gets its own rule: it fires only capitalized and adjacent to a day
   number or a year, because it is a modal verb eleven months are not.

5. **The backstop is the non-negotiable, and it is `answer_must_record`'s
   shape exactly.** When the prescreen fired and the listener returned zero
   records, that is a blocking lint —
   `landmark_gates.listener_heard_nothing` — with ONE bounded retry carrying
   `listening_reminder` (which names what the prescreen saw and forbids
   inventing anything to satisfy it, in the same breath), and then
   `STATUS_WITHHELD` carrying the lint id. **Never silence, never a
   fabricated record.** The withheld status is distinguishable from the
   focused mode's by its lint id, so a host sweep can retry exactly this
   class (v216+ semantics).

   The no-focus mode ships ONLY with this. ADR 0028's Finding 2 is that the
   instruction was already in the leaf when the founder's answer was
   swallowed, so prompt prose alone cannot be certified — and a mode with a
   nine-domain surface and no deterministic floor would be the same bet,
   larger.

6. **Three things clear the lint, and each is a decision rather than a miss.**
   A DECLINE, through `answer_shape`'s own skip rules — one definition of
   "not now", never a second list of hedges. A `person_relation_not_family`
   finding, and ONLY that one: the listener heard a dated person and the
   owner's rule refused the record, so regenerating would ask the model to
   break the rule it just obeyed (`person_record_has_no_date` clears nothing;
   a malformed object is not a thing heard). And a **restatement**: when
   every fragment the prescreen saw is already in the store word for word
   (`store_terms`, rendered by v216's own two readers — `entry_name` and
   `chronology.display_date`), "nothing came back" is the right answer. That
   is v216's dedupe carried into the no-focus mode, and it is the one place
   where "was this fragment consumed?" is decidable, because the store
   answers it.

7. **The prompt is a compact digest, and the size is pinned honestly.** The
   leaf carries the nine domains as nine lines of `domain: key | key | key`
   — `landmark_recorder.recordable_keys`, the SAME derivation the focused
   leaf renders as *THE ONLY KEYS THIS DOMAIN CAN READ*, which is the ladder
   already walked through both validators. Nine of those lines is ~780
   characters; nine full ladders with their rung texts would have been an
   order of magnitude more than the pass they belong to. A `none` key
   appearing on a line is how that line says the domain can be answered
   *never happened*.

   **Measured: 5514 characters with an empty store**, pinned under 5700
   (`test_the_measured_size_is_pinned`). Still no identity, no behavior, no
   examples and no transcript, which is the property the pin exists to hold.
   v216's known-entries block renders for EVERY domain here and is capped
   TWICE — at most `KNOWN_PER_DOMAIN = 3` lines from any one domain and
   `KNOWN_TOTAL = 21` in all, domains walked in `questions.yaml` order so the
   surviving set is stable rather than whichever domain grew fastest — and
   the block says how many it hid.

8. **`date_record` is a SECOND purpose name, never a rename.**
   `general_listener.DATE_RECORD_PURPOSE` is `"date_record"` and
   `LANDMARK_RECORD_PURPOSE` (aliased as `landmark_recorder.RECORDER_PURPOSE`)
   is `"landmark_record"`. Two prompts, two outputs, two backstops: a host
   budgets, routes and audits them apart, and collapsing them would make the
   listener's cost invisible inside the recorder's.

## The cost, stated honestly

**What it costs.** One haiku-class completion per message the host chooses to
listen to. Which messages those are is the HOST's decision and is not made
here — this ADR ships the pass, not the trigger policy. The prescreen exists
partly so a host can decline to spend the call at all on a message with no
time in it, which is the cheapest possible gate and is pure.

**Why the budget is liberal (owner ruling).** The tables over-fire on purpose.
A false positive costs at most one extra regeneration on a message the
listener honestly found nothing in, and it can never drop, alter or withhold
a record that was made. A false negative is a date nobody ever hears. That
asymmetry is why every ambiguity resolves toward firing, and why the
prescreen is not, and must never become, an extractor.

**What we refused.** Repealing the focused mode's domain restriction, which
was the audit's own proposal and the audit's own rejection. A heterogeneous
`records` list carrying landmarks and people together. A `placements` list
built on a moment-identity problem this wave has not solved. And shipping the
no-focus mode on prompt prose alone, which is the exact bet ADR 0028 was
written because we lost.

## Consequences

- **Platform twin.** Not in this PR, by design — this is package-side only.
  The engine will invoke the listener from wherever it decides to listen, and
  file `outcome.records` through the durable landmark path it already uses
  and `general_listener.person_invocations(outcome.people)` through the
  entity-verdict path v217 added. The withheld status carries its own lint id
  so a host sweep can find and re-run exactly this class.
- **The purposes are two rows, not one.** The platform registers
  `landmark_record` and `date_record` separately in its own `LLM_PURPOSES`
  (`services/api/app/llm/interfaces.py`), which today holds neither.
- **Pin-bump reconciliation.** The promoted tables are the surface to watch:
  `chronology.YEAR_RE` / `MONTH_NAMES` and `cross_dating.AGE_STATEMENT_RES`
  now have callers outside their own modules, and the private names remain as
  aliases so nothing that vendored the old bytes breaks.
- **Phase 2, named and deliberately not done here.** Moment identity for
  prose (the `placements` list). The host-side trigger policy — which
  messages get listened to, and when. And the arithmetic that turns an
  anchor-relative phrase into a date once its anchor lands, which is
  `cross_dating`'s pass and already exists; the listener's job is only to
  notice the phrase was said.
- **Goldens.**
  `interactions/landmarks/evals/goldens/listener-general-01.json` pins the
  founder-shaped cases end to end: three datable facts across three domains,
  a dateless message the prescreen did not fire on, a family sibling year
  becoming a roster row, a non-family person's date dropped by name, a pure
  restatement filing nothing in one attempt, one invalid record among many
  dropping alone, and the backstop withholding rather than dropping.
  `listener-prescreen-01.json` pins the measurement itself — every required
  shape, and the negative cases (`marry`, `marching`, the modal `may`,
  `at 19%`, `at 19:30`, `at 19 Elm Street`) that are the load-bearing half.
