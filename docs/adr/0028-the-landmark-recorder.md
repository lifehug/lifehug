# ADR 0028: The landmark recorder — recording is not replying

Date: 2026-08-25
Status: proposed
Issue: lifehug#221 (the emission defect); certification audit
lifehug/lifehug-platform#586

## Context

On 2026-08-25 the owner read two of his own landmark sessions back and found
the same failure twice, on the same leaf.

Asked whether he had served, he answered: *"I have not served in the military.
It's not military service, but I did serve a two-year mission for my church as
a Mormon missionary. I served that in Zurich, Switzerland, when I was 19."*
The reply took up the mission warmly. `landmark` came back `null`. The
domain's own answer — a plain `{"domain": "military", "none": true}` — was
never filed, so the row stayed open and the question will be asked again.

Asked about losses, he named the people he had lost. The reply named them
back. `landmark` came back `null` again.

The certification audit that followed (platform #586, 2026-08-25) executed the
whole chain against v209 and the founder's real store and returned three
findings. Two of them are somebody else's to fix. The third is this one, and
it is the reason a purely textual fix cannot be certified:

> **The emission failure happened WITH the instruction present.** The
> "mission abroad → still a none" example has been in the vendored leaf since
> v203 and was live when the founder answered; the model ignored it. Emission
> is *unreliable*, and prompt prose alone is not certifiable. Only a
> deterministic backstop is.

And the recovery path that existed could not heal it either: the platform's
landmark re-harvest re-composes the **identical** prompt and one-shots it, with
no lint and no retry. Re-running the prompt that already failed is hope, not a
fix.

The structural reading is simple. One model completion was doing two jobs —
be good company, and file a fact — and when the two competed, company won.
That is not a model defect to be scolded out with stronger wording. It is a
seam that should never have carried both.

## Decision

**Recording is its own pass, with its own prompt, its own model call, and its
own blocking backstop.** The conversation writes the reply for the person; the
**recorder** reads the person's own message afterwards and files the record.

1. **The recorder leaf** is `interactions/landmarks/prompt/recorder.md`,
   composed by `interaction.yaml`'s `composition.recorder` — a composition of
   its own, never part of the conversation's `load_order`. It carries no
   identity, no behavior, no examples and no transcript: only the domain, its
   ladder, whether the domain can be answered *never happened*, what is
   already known, the question that was asked, what the person said, and what
   they were told back. It has no voice and it is told so in its first line.
   Its whole output is one JSON object: `{"landmark": {...}}` or
   `{"landmark": null}`.

2. **One recorder, two triggers.** `landmark_recorder.record_answer(...)` is
   the entire contract. The live landmark turn calls it immediately after the
   reply is generated. A historical sweep — the platform's landmark
   re-harvest — calls the SAME function over answers people already gave. The
   sweep therefore inherits the lint and the retry for free, which is the
   only thing that makes re-running a historical answer a fix rather than a
   second roll of the same dice.

3. **The backstop is a blocking lint and exactly one retry.**
   `landmarks_interaction.ANSWER_MUST_RECORD_LINT`
   (`landmark_gates.answer_must_record`) fires when the recorder returns
   nothing and the person's own message shows they answered. The recorder
   then regenerates ONCE with `recording_reminder(domain)` appended and
   emits. A second empty pass is `STATUS_WITHHELD` carrying the lint id — a
   thing a host can try again later, never a silent drop and never a
   fabricated record. `MAX_ATTEMPTS = 2`, and there is no third rung.

4. **The detection boundary is documented, narrow, and fails toward skip.**
   `landmarks_interaction.answer_shape(user_message, reply, …)` is the one
   definition. A SKIP wins outright, and every "I don't remember" hedge is
   deliberately swept in there. A NEGATIVE counts only where the domain can
   carry a none terminal, so "no brothers or sisters" never lints `family`.
   SUBSTANTIVE means the reply echoed a proper noun or a year the person
   supplied in that same message, minus anything already in LANDMARKS — the
   model's own acknowledgment shape, which is the exact failure observed. A
   real answer carrying neither a name nor a year is invisible to the class,
   on purpose: the class blocks, so ambiguity must never punish a good turn.

5. **The two validation layers are unchanged.**
   `landmark_recorder.parse_recorder_output` runs
   `conversation_delivery._parse_landmark` then
   `landmarks_interaction.validate_landmark`, exactly as the live turn's
   additive field does. The recorder introduces no second vocabulary for what
   a landmark is, and no second filing path.

6. **The recorder is told only the keys its domain can READ, and the
   derivation is v211's own.** `landmark_recorder.recordable_keys(row)` walks
   `landmarks_interaction.rung_satisfiers` over the ladder — the SAME list
   lifehug#219/#220's ladder-consistency guard walks on the read side — and
   intersects it with what both validation layers actually keep for that
   domain (`_survives`, probing the exact path `parse_recorder_output`
   runs). One declaration of what a domain reads, used on both sides, bound
   by `test_recordable_keys_are_exactly_the_ladders_satisfiers`. The leaf
   carries the result as a line: *THE ONLY KEYS THIS DOMAIN CAN READ*.

   The two halves catch different things, and both are live shapes:

   * the ladder half excludes v211's `DOMAIN_AGNOSTIC_FIELDS` — `span` on
     `children`, whose ladder has no span, and `label` on `birth`, whose
     ladder names no subject;
   * the validator half excludes `name` on `children` (a satisfier on read,
     dropped on write, because `validate_landmark` stores a rung key only
     for that domain's own rung) and `birth` on `family` (its own ladder
     rung, absent from `conversation_delivery._LANDMARK_KEYS`, so emitting it
     degrades the WHOLE record to `None` — a sibling's birth year reaches the
     ladder through `date`).

7. **The reply keeps its own `landmark` field.** Nothing is removed; a host
   that has not wired the recorder yet behaves exactly as it did at v209, and
   `answer_must_record` is reachable from `lint_landmark_reply` for that host
   through the same single definition. What changes is where the burden
   lives: once the recorder runs, a warm reply can no longer swallow a fact,
   and — the case the audit cared about most — a turn whose reply generation
   FAILED still records, because the recorder never needed the reply.

## The cost, stated honestly

This is a second model invocation, and it should be named as one rather than
buried.

**What it costs.** One extra completion per landmark ANSWER. Not per
conversation turn, not on the daily question, not on any session that is not a
landmark session — `TurnShape.landmark_stage` is `None` everywhere else and
the recorder is not reached. On a turn where the person skipped or said
nothing about the domain, the recorder still runs once; that is the price of
not deciding "did they answer?" with a regex before asking.

**Why it is small.** The recorder's prompt is the leaf plus six short
substitutions — roughly a few hundred tokens, with no identity block, no
behavior block, no examples and no transcript. The conversation prompt it sits
beside carries all four. `role.recorder` is `haiku-class` against the lane's
`sonnet-class` worker. The second call is therefore roughly an order of
magnitude cheaper than the first, and the retry — which only fires on the
failure shape — is the same size again.

**What it buys.** The failure it removes is not a cosmetic one. A landmark
that is not filed is a question the person will be asked a second time after
answering it, which is the exact behavior the whole lane exists to prevent,
and — for `none` domains especially — it is the difference between a life
recorded as unfinished and one recorded as finished. Weighed against a
haiku-class call on the turns where somebody actually answered a landmark
question, that is not a close call.

**What we refused.** A cheaper design was available: keep one completion and
lint the reply. It is what this branch started as. The audit's Finding 2
retired it — the instruction was already there when the failure happened, so
strengthening the instruction cannot be certified, and a lint on the reply
still leaves the recording competing with the conversation for the same
completion. Doing both jobs in one call is what failed; making the call try
harder is not a fix.

## Consequences

- **Platform twin.** The engine invokes the recorder after the turn is
  generated, from the same registry row that resolves the landmark stage, and
  files through the durable filing path the live turn already uses. The
  re-harvest calls the same function instead of re-composing the live turn
  prompt — the "no second machine" rule it was written to honor is better
  served by one recorder with two triggers than by one prompt with two
  meanings.
- **Latency.** The recorder is off the person's critical path by
  construction: the reply is already written when it runs. A host may file it
  in the background; nothing about the person's turn waits on it.
- **The lint is the lane's only blocking one.** Every other
  `landmark_gates.*` class is advisory, scored over the goldens. Those six
  describe how a turn should sound, and a turn that sounds slightly wrong is
  still worth sending. A turn that loses the answer is not.
- **Goldens.** Both live failures are pinned verbatim (surnames synthesized)
  in `interactions/landmarks/evals/goldens/landmark-answer-not-recorded-bad-01.json`
  as the recorder's acceptance: the empty extraction lints, the reminder is
  appended, the regeneration emits. An ambiguous answer that records nothing
  and must NOT lint is pinned beside them.

---

## Amendment (v214, 2026-08-25): one answer, MANY records

Issue: lifehug#227. Status: proposed, extending the decision above rather
than replacing any part of it.

### Context

One day after the recorder shipped, the founder's own vault produced two more
failures of the same shape — and the shape is not *replying instead of
recording* this time. It is **one answer carrying many entries, and a
recorder that could file one**.

> Asked what work he had done, he answered with about twelve jobs. The
> recorder's canonical output was `{"landmark": {...}}` — exactly one record.
> Both attempts degraded to nothing and the whole answer was **withheld**.

> Asked about his children, he named four of them with four exact birth
> dates. They were collapsed into ONE aggregate entry carrying a `span`
> across all four birthdays — a field `children`'s ladder
> (`happened | who | year | month`) has no rung for at all, so every rung
> below `who` read nothing and the question kept coming back.

The losses golden that shipped WITH v212 says the same thing out loud: its
person names three people and its expected turn field carries one, because
one is all a turn field can carry.

`children`, `work`, `residences`, `family`, `partnerships` and `losses` are
all **multi-entry domains** by construction — four of them are declared
`chain: true` and the other two enumerate people. One answer routinely
carries many entries. Filing one of them is losing the rest, and the ladder
reads per ENTRY, so a collapsed aggregate is not merely lossy: it re-asks a
question the person already answered.

### Decision

1. **The recorder speaks in record SETS.** The canonical output is
   `{"landmarks": [<record>, ...]}`. v212's `{"landmark": {...}}` is still
   accepted and normalizes to a one-element set, and `{"landmark": null}` and
   `{"landmarks": []}` say the same thing — no flag day for any prompt, host
   or stored completion.

2. **Both pinned layers run PER RECORD.**
   `landmark_recorder.parse_recorder_output` returns a `tuple[dict, ...]` and
   puts each record through `conversation_delivery._parse_landmark` then
   `landmarks_interaction.validate_landmark` **alone**. An invalid record
   drops by itself and never takes a sibling with it — the twelve-job answer
   must not be lost because the eleventh job named a key `work` cannot read.
   A malformed envelope degrades to an EMPTY tuple, never an error.

3. **`RECORDED` means at least one record validated.**
   `RecorderOutcome.records` is the outcome; `.record` remains as its first
   entry so every v212 caller keeps working. `answer_must_record` is
   unchanged in spirit — its question is *was anything recorded at all* — and
   zero valid records against an answer that plainly asserts facts is still
   ONE regeneration and then `STATUS_WITHHELD`.

4. **A second, RETRYABLE lint: `landmark_gates.record_every_entry`.** The
   certification audit's finding stands — prose alone is ignorable — so the
   leaf's new worked multi-entry example is backed by a deterministic class.
   `landmarks_interaction.records_missing_entries` fires on exactly two
   decidable shapes and nothing else:

   * **unrecorded names** — proper-noun groups in the person's own message
     whose head word appears in no record that came back. Two of them
     normally, because one uncovered group is the ordinary shape of a
     qualifier ("Dayton, Ohio" recorded as Dayton); one is enough once the
     answer is already known to be plural (two or more records came back);
   * **unrecorded years** — on a domain that dates each entry SEPARATELY (a
     date grain and no `span` rung, derived not listed), the person stated
     two or more distinct years and fewer records than that carry a date.
     Four birthdates, one dated record.

   It never fires where the answer cannot be plural: a record set carrying
   the none or skip terminal (which answers the whole domain), or a domain
   with no identity rung (`birth` — one person, one birthday).

   On a finding the recorder regenerates ONCE with `many_records_reminder`,
   which asks for the list and forbids padding it in the same breath, and
   then **files what it has either way**. `MAX_ATTEMPTS` is still 2 across
   both triggers. This branch can never withhold: a partial record is worth
   more than none, and the person already said it once.

   The class is deliberately **not** in `LANDMARK_LINT_CLASSES`. That is the
   closed set `lint_landmark_reply` scores over the reply goldens, and the
   turn's own additive `landmark` field is singular by the pinned turn
   contract — a turn that records one entry of three is obeying the only
   contract it has, and failing it for that would punish correct behavior.
   The plural output belongs to the recorder, so the class that reads it
   does too.

5. **Filing is per entry, and only two shapes are ever superseded.**
   `timeline.save_landmark` keyed entries on `label` alone, which collapses a
   whole multi-entry answer the moment the writer files names under the
   domain's own rung instead: four children filed as `who` all keyed on `""`.
   It now keys on `landmarks_interaction.landmark_entry_key` — the READ
   side's own identity order, `label` then `name` then the domain's
   `identity_rung`, case-folded. `entry_superseded_by` states the three
   cross-entry rules:

   * a **none** retires its whole domain (`merge_landmark_entry` has always
     said a none *replaces whatever was there*; per-domain is what that
     sentence means once a domain holds many entries);
   * a **substantive** record clears a standing none or skip — the same rule
     read the other way;
   * a **clean** record retires an entry carrying a field no rung of its
     domain can read (`unreadable_fields`) — exactly the `span`-on-`children`
     aggregate. The test is the SHAPE, never the content: an entry whose
     every field its own ladder can read is an entry somebody stated, and
     nothing here touches it.

   `timeline.save_landmarks` and `landmarks_interaction.landmark_invocations`
   are the batch forms: one entry per record, one `landmark-record`
   invocation per entry, no aggregate form anywhere.

6. **`unreadable_fields` is one definition, two callers.** The
   ladder-consistency guard derived that sentence inline to pin
   `DOMAIN_AGNOSTIC_FIELDS`; the store needs the same sentence to recognize a
   machine-written shape. It now lives on the module and both read it
   (recurring-defect doctrine, docs/BUILDING.md §7).

### The boundary, stated honestly

"How many entries is this answer?" is **not** decidable from a string, and
this amendment does not pretend otherwise. The two shapes above are the
decidable subset; everything else answers `None` and never lints. The
under-detection is deliberate and the over-detection is cheap by
construction: a false positive costs exactly one haiku-class regeneration and
can never drop, withhold or alter a record. That asymmetry is why the name
floor drops to one once the answer is already plural, and why the reminder
spends a whole sentence forbidding invention.

### Consequences

- **Platform twin.** The engine files `outcome.records`, not
  `outcome.record` — one durable entry per record, through the same filing
  path — and the landmark re-harvest inherits the new trigger for free, which
  is what makes re-running the founder's withheld work answer a fix.
- **Vaults heal on write.** No migration: the `span`-carrying children
  aggregate is retired the first time a clean `children` record is filed, and
  entries the person named are never touched.
- **Goldens.**
  `interactions/landmarks/evals/goldens/landmark-many-records-01.json` pins
  both live failures (names synthesized) plus the three cases that must NOT
  change: a single-fact answer, a none answer, and one invalid record among
  many dropping alone.
