# ADR 0033: Add Landmark — the `offer` mode of the Landmarks Interaction

Date: 2026-09-03
Status: proposed
Extends: ADR 0028 (the landmark recorder), ADR 0029 (the general
listener) and ADR 0032 (landmark sufficiency)
Controlling design: `lifehug-platform
docs/decisions/2026-09-03-timeline-unification/decision-record.md` — owner
rulings R3, R3a, R3b of 2026-09-03, §4.2 (weight tiers), §5 (how Add Landmark
works), Cut 6a of §7
Supersedes in part: ADR 0025 is retired (R4a); the deterministic block grammar
it shipped survived one release as an unreached internal extractor (v291,
R6) and Cut 6h (v293) deleted it — see the amendments below; nothing
user-facing ever named the product it came from (R4)

## Context

The Landmarks Interaction asks. The system chooses a domain, asks the next
rung, and the recorder files the answer. Everything about it assumes the
system started the conversation.

People do not only answer. They also arrive holding something — a whole run of
addresses, a work history, a paragraph about the year they moved — and want to
hand it over. Until now the only door for that was a paste page with a strict
`Key: value` grammar behind it, whose every failure, from a malformed date to
an expired token, arrived as one sentence: *"Could not parse that paste right
now."* The owner's judgment, 2026-09-03: *"A parser is probably too strict."*
And then, on a second pass: the product built around it *"never achieved its
goal or what it was intended to be. Rip it out. Add Landmark is what I
wanted."*

What the owner wants instead (R3): hand over information in ordinary text, have
a timeline-aware model say what it read, confirm it, and have it filed **with
the weight of a stated fact** and enter the loop — so that answering questions
gives real feedback rather than disappearing into a file.

Three things about that were not obvious and are settled here.

**It is not a new interaction.** (R3b.) The passes it needs already exist: a
listener that classifies an utterance with no domain in mind, a recorder that
turns words into one domain's structured entry with that domain's filed
entries in view, and a worker that speaks. An import model would be a fourth
extractor with its own prompt, its own evals and its own drift.

**It is not a parser.** (R3.) A deterministic grammar may run behind the
model, and does, but it is never the required user-facing format and a
document it cannot read is not refused — it goes to the listener.

**It is not permission to invent a date.** (§4.2.) A model's reading of the
person's words is a STATED fact; a model's guess beyond the words is an
inference and stays labelled as one. That distinction cannot be delegated to
the model that made the guess.

## Decision

**Add Landmark is a MODE — `offer` — of the `landmarks` interaction, and the
whole of its machinery is the machinery that was already there.**

### 1. The interaction gains a mode, not a kind

`interaction.yaml` declares `modes: collect|offer` and a third composition
slot, `composition.offer_turn: prompt/turn-instructions-offer.md`, beside the
two that already sit outside the conversation's load order
(`composition.recorder`, `composition.listener`). `interactions/registry.json`
is untouched: one interaction, one row, one lineage, and #609's single seam
resolves the mode like any other child asset.

The context manifest gains three deterministic blocks (§5.2): the ROSTER
(people, places, organizations, aliases), the EXISTING EPISODES AND ERAS with
their spans, and the AGE FRAMES with the birth origin they are counted from.
They are rendered by the caller from `landmarks_interaction.render_roster`,
`render_known_spans` and `render_age_frames` — pure functions beside
`render_known_entries`, for the same reason that one is pure. **The model
interprets; it does not fetch.**

### 2. Three passes, in order, none of them new — SUPERSEDED, v291

> This section described the ORIGINAL shape: a deterministic grammar first,
> then the general listener with no domain, then the focused recorder once
> per domain the listener named. **The "Amendment, 2026-09-04 (v291)"
> section below replaces it — R6 reverses the order entirely, to ONE model
> reading with no deterministic pass in front of it — and Cut 6h (v293)
> finished the reversal by deleting the grammar pass's own code
> (`grammar_units`, `_date_dict`, `_grammar_block_quote`) rather than merely
> leaving it uncalled.** Kept below for the record of what this ADR
> originally decided; see the v291 and v292 amendments for what actually
> ships.

1. ~~A **deterministic first pass** over text a block grammar fully matches
   (`landmark_offer.grammar_units`). Zero model calls; a thirty-block
   residence document proposes thirty units for the cost of a string split.
   A block with one line the grammar does not know is NOT half-parsed — it
   goes on to the listener whole, because half a parse is a guess.~~
2. ~~The **general listener** (ADR 0029) with no domain: what does this text
   touch at all.~~
3. ~~The **focused recorder** (ADR 0028) once per domain the listener named,
   with that domain's already-filed entries in view — which is why a second
   stay in a city the vault already knows becomes a second entry rather than
   a merge.~~

~~Model tiers are the ones already declared: `role.listener` and
`role.recorder` are Haiku-class, `role.worker` is Sonnet-class. There is no
separate format-repair prompt and deliberately no place for one — a paste the
grammar cannot read is not malformed input to be fixed before reading, it is
ordinary text, and the Haiku-class listener is what reads it.~~ **No model call
recalculates a date:** every interval that files is `chronology`'s, derived
from what the person wrote. (This sentence alone survives v291 unchanged —
see `landmark_offer.date_evidence` below.)

### 3. Stated versus inferred is decided from the bytes

`landmark_offer.date_evidence` re-reads every bound of every proposed date
against the person's own text: the year must be there in full (`1990`) or in
the two-digit form people write (`'91`), and a finer grain must have its month
named too. A bound the text carries files with `basis: stated`; a bound it
does not carries `confidence: inferred` and a verbatim `inferred` provenance
clause, whatever the completion declared. A model that emits
`"basis": "stated"` over a year nobody typed is answered here, not believed.

The unit's own summary `basis` is `stated` only when every bound it carries is
carried by the words. The per-bound truth is not lost by that summary: it
rides on the record, and the record is what files.

### 4. Filing is the road an answer already takes

A confirmed unit files through `timeline.save_landmark` — the one landmark
writer — so a confirmed offer and an answered question are indistinguishable
downstream. That is R3a's *"same unit, same landmark recorder, same value
calculation"*, and it is why the filed unit counts toward sufficiency and can
retire the matching opportunity.

Identity is content-addressed and it is deliberately not an ordinal:

| Identity | What it is | Why |
|---|---|---|
| `unit_id` | digest of domain, kind, subject, dates, quote | two readings of one text propose the same units; a unit whose date or evidence changed is a different unit |
| `proposal_id` | digest of submitted text, vault generation and, since v297, reading revision | a changed timeline or reading contract permits a new reading; old IDs and applied receipts remain valid |
| filing digest | `(proposal_id, unit_id)` through `save_landmark`'s existing `digest_override` seam | a retry files nothing twice, and the identity does not move under a retry as earlier units land |
| `receipt_id` | digest of the proposal and exactly which units | applying the same units twice reads the standing receipt back rather than claiming a second gain |

The submitted text is promoted once as an ordinary vault source when anything
is filed from it, so no filed claim's only citation is a proposal file.

### 5. Evidence is durable before confirmation

R3 narrows the audit's *"nothing durable until confirmed"*: the input is
retained from the moment it is submitted. `propose` writes exactly one file,
`state/landmarks/offers/<proposal_id>.json`, carrying the text, the units, the
stories, the spans nothing recognized, and the open questions — and it writes
it on failure too, so the input is never the thing that gets lost. **No
landmark is filed until a person names the units.**

### 6. Nothing is dropped, and nothing is refused

Every span of a submission ends up under exactly one of a unit's quote,
`stories`, or `unrecognized`, and a lint asserts the three cover the text
between them. Non-landmark text is accepted and routed as a story, and the
worker says so (R3a) — *"I could not use that"* is the one sentence the offer
turn may never contain.

### 7. Undo marks; it never deletes

`retract` files a `temporal_store.retract_claims` correction over exactly the
claims the filed units stand on — found by the promoted SOURCE each unit
wrote, so undoing the second stay at an address never touches the first — and
republishes through the one writer. The promoted sources, their receipts and
the offer's own receipt all stay on disk; the retraction is a new immutable
file beside the receipt, never an edit of it.

### 8. Failures are typed

`LandmarkOfferError.code` is one of `content_ambiguity`,
`unsupported_input`, `model_failure`, `service_unavailable`, `write_failure`
(§5.3 state 6), and `landmark_offer.OFFER_STATES` names all six states of §5.3
once, so the OSS module and the platform surface cannot end up with two
vocabularies for the same screen.

## Consequences

**What this buys.** A person can hand the system a paragraph or a document and
watch it become dated anchors, with the sentence each one came from beside it,
and undo any of it. The landmark question that unit answers stops being asked.
Nothing files behind their back.

**What it costs.** ~~One listener completion plus one recorder completion per
domain the listener named, at Haiku-class, per submission — the same shape and
the same tier as a landmark answer's cost, paid once per paste rather than
once per turn. Text a grammar fully matches costs nothing at all.~~
SUPERSEDED, v291: ONE reading completion per submission, Sonnet-class
(`role.reading`) — see the v291 amendment below. There is no grammar pass any
more to cost nothing.

**What is deliberately not decided.** Auto-filing. The policy exists
(`auto_file_eligible` on every unit, computed from the evidence and never from
a model's confidence), and this module never exercises it: `apply` files what
a person named and nothing else. The owner expects the proposal step for
landmark-grade input and has not asked for auto-file (decision record §11).

**How the matching question retires.** By CLOSING THE GAP, not by setting a
flag. Cut 5a (ADR 0032) derives its opportunities from the calculated graph on
every publish, so a stay that now has both bounds simply stops generating
`span_open_end`. `apply` reads the published `landmark_opportunities` block
either side of the filing and reports on the receipt which of the unit's
candidate ids actually closed — a retirement measured against the two
generations rather than asserted by the thing that did the filing.
`landmark_offer.landmark_opportunity_id` is a named door onto
`landmark_opportunities.opportunity_id`, never a second digest.

**What is left open.** Transports beyond paste and plain text (§5.5) — PDF,
DOCX, CSV, OCR — do not block this cut and are the owner's call per cut. Cut
5b's queue candidates are not touched here: an opportunity that leaves the
published block leaves the queue with it, by the same derivation.

## Alternatives rejected

**A bespoke import model.** A fourth extractor with its own prompt, evals and
lints, drifting from the recorder it duplicates. Rejected by R3b.

**A new interaction kind.** Same objection, plus a second registry row and a
second lineage for one unit of meaning. `timeline-eras.md` §16 already ruled
against it and R3b confirms it.

**Keeping the grammar as the user-facing format.** It is the thing that
failed. R4 forbade anything user-facing naming the product it came from; R6
(v291) took it off the offer path entirely, and Cut 6h (v293) deleted the
extractor itself rather than leaving it as dead code.

**Trusting the completion's `basis`.** The model that guessed the year is the
last thing that should grade the guess. §4.2's dividing line is a question
about bytes and is answered as one.

**Filing on submit.** Rejected by R3's proposal step: landmark-grade input
gets a confirmation screen. Evidence is durable at submit; landmarks are not.

## Amendment (2026-09-03, Cut 6c): the host-run extraction protocol

On staging, `landmark-offer --propose` ran inside the platform's package
sandbox — which, by design, carries no AI provider: a frozen env allowlist,
no keys. The listener call failed `{"class": "service_unavailable", ...}`,
the CLI exited 1, the platform retried three times and parked the job, and
the owner saw a 503. The pattern the platform already keeps for the
landmark RECORDER on a conversation answer — the package composes prompts in
a sandboxed snippet, the host makes every model call through its own router
with budgets, and the parsed result is handed back for the package to file
(`services/api/app/delivery/landmark_recorder.py`,
`conversation_prompt.py::build_recorder_prompt`/`build_listener_prompt`) —
had not been extended to Add Landmark. `propose`'s `call(prompt, model) ->
str` injection (ADR 0033, above) already made this possible in principle;
what was missing was the CLI/host protocol that lets a host in ANOTHER
PROCESS drive it.

**Three steps, none of them a second extraction — the same leaves, the same
substitutions, the same passes `propose` always runs, just not in this
process:**

1. `landmark-offer --propose --prompts` (stdin text; optional `--context
   FILE` of `{landmarks, roster, generation}`, so a host already holding
   vault context need not have this process read the vault a second time) →
   `{"listener": {"prompt", "model", "prompt_version"}}` on stdout. Calls no
   model; writes nothing.
2. `landmark-offer --propose --prompts --listener-completion FILE` → the
   per-domain recorder prompts the listener's completion implies:
   `{"recorders": {"<domain>": {"prompt", "model", "prompt_version"}, ...}}`.
   Empty where the listener named no domain, and a host proceeds straight to
   step 3. Calls no model; writes nothing.
3. `landmark-offer --propose --completions FILE` (stdin text; `FILE =
   {"listener": <completion>, "recorders": {"<domain>": <completion>}}` —
   exactly the shape `tests/test_landmark_offer.py`'s `ScriptedCall` and
   `landmarks_evals.py`'s `_RecordedCall` already read, a completion either
   the raw text or its parsed object) → runs `propose(..., call=...)` and
   WRITES the proposal file, precisely as a package-driven `--propose`
   always has.

**The exit-code rule, everywhere `--propose` can write a document: exit 0
whenever a proposal document was written, whatever its `state` — a `failed`
one included — and exit 1 only when no document could be produced at all**
(unreadable input, an unbound vault, a write failure — the cases that already
raise `LandmarkOfferError`). R3 makes the submitted text durable the moment
it is submitted; a nonzero exit on a `state: failed` proposal that IS on disk
would tell a retrying host to treat durable evidence as lost, which is
exactly the defect this amendment closes. This also corrects the
package-side `--propose` (a live model call in-process): it now exits 0 on a
written `failed` proposal too, for the identical reason — the CLI-only path
and the host-run path make the same promise.

**Determinism.** `propose_from_completions` — the function `--completions`
runs — builds its `call` from the completions file with the same
domain-header dispatch `ScriptedCall`/`_RecordedCall` use, so the proposal it
writes is byte-identical (modulo `created_at`) to
`propose(call=ScriptedCall(...))`'s in-process one over the same
completions. `tests/test_landmark_offer_host.py` pins this against all five
`offer_fixtures.json` goldens, both ways, and pins each `--prompts` string
against the prompt an in-process `call` actually received, and each row's
`prompt_version` against the written proposal's own `extractors[]`.

**What is deliberately unchanged.** The three passes, the grammar-first
extractor, the stated/inferred rule, filing, undo and the failure classes are
exactly ADR 0033's. This amendment adds a way to DRIVE the same `propose`
from outside this process; it is not a fourth pass and it composes no prompt
of its own.

---

## Amendment, 2026-09-04 (v291) — one reading replaces the three passes

Owner rulings **R6–R9**, recorded in `lifehug-platform
docs/decisions/2026-09-03-timeline-unification/add-landmark-reading-plan.md`
§2. This amendment supersedes the decision record's §5.6 "extraction" order and
everything above that describes three passes.

### What the first real use showed

On 2026-09-04 the owner pasted a thirty-stay residence history into Add
Landmark on staging and did not accept the proposal. Five defects, each
verified against the shipped code:

| # | Defect | Where | What the owner saw |
|---|---|---|---|
| D1 | The prompts teach `"date": "1974"`; the shared reader accepted only `{"best": …}`. | `conversation_delivery._parse_landmark_date` | Every model-read unit "no dates yet" — fixed on its own in v290. |
| D2 | The block grammar read first; the model then re-read the whole document blind to what the grammar had taken. | `grammar_units` → `propose` | Eight stays labelled by their city rather than the nickname beside it; a street name read as a second, dateless residence; every school and job dateless; labels invented by joining two unrelated names. |
| D3 | The grammar read `[Jun 1986]` as approximate; the offer path overwrote it to certain. | `_date_dict` | 17 of 30 estimated starts shown "as you said it". |
| D4 | A block with any parenthetical was refused by the grammar and split line-by-line into stories. | `grammar_units` | Four stays "kept as a story". |
| D5 | A unit with no date at all was summarised `basis: inferred`. | `rebase_record` | "inferred" shown where nothing was read. |

The root cause is architectural, not the model's: this ADR put a deterministic
reader in FRONT of the interaction and hid its work from it.

### The rulings

- **R6 — the interaction reads; the system validates and files.** Add Landmark
  is one model pass with full context, reading any free text into a structured
  *reading*. No deterministic reader touches the person's text before the
  model. The deterministic layer validates the model's output (evidence,
  duplicates, conflicts), files what the person confirms, and nothing else.
  *"Users don't need to know how a parser works; the model must know how to use
  the system."*
- **R7 — a span is the unit of relation.** Anything named inside a stay, a
  tenure or a schooling belongs to it and inherits its dates as a stated
  inference. Dated events inside it file as claims tied to it; undated events
  file as moments contained by it.
- **R8 — estimation is the interaction's convention, `approximate` is the
  system's word.** Brackets, "about", "?", "sometime" are read by the
  interaction and mapped to one bound's confidence. The system never sees the
  convention.
- **R9 — one reading per submission.** A long paste is one model reading. The
  page says it is reading; it does not split, sample or time out early.

### What replaced what

| Was | Is |
|---|---|
| `grammar_units` (block grammar, first) | nothing — it survived uncalled at v291; Cut 6h (v293) deleted it |
| `landmark_recorder.listen_to_answer` on the offer path | `landmark_reading.build_reading_prompt` + `parse_reading` |
| `landmark_recorder.record_answer`, once per domain | — |
| `prompt/listener.md` + `prompt/recorder.md` on the offer path | `prompt/reading.md`, slot `composition.reading`, role `role.reading` (sonnet-class) |
| `host_listener_prompt` / `host_recorder_prompts` | `host_reading_prompt` |
| `--prompts [--listener-completion FILE]` | `--prompts` (one prompt) |
| `--completions {listener, recorders}` | `--completions {reading}` |
| three `extractors[]` rows | one, `landmark_reading` |

**`collect` mode is untouched.** The daily listener and the focused recorder
are exactly what ADR 0028 and ADR 0029 describe; only the offer path changed.

### The reading contract

`parse_reading` is **lenient in shape and strict in substance**. Lenient: a
missing list is an empty one, an unknown key is dropped with a finding, and a
completion that is not JSON at all is an EMPTY reading with a finding — never
an exception, because a person's words must not be lost to a model's bad JSON.
Strict, in this order:

1. Every `quote` must LOCATE in the submitted text (`landmark_offer.locate`);
   an item whose quote does not is dropped with a finding.
2. A `dates` bound is `stated` only if `date_evidence` finds its year — and its
   month at that grain — in the person's own bytes. A bound the text does not
   carry is **DROPPED with a finding, never rewritten** (this is D5's fix, and
   the reversal of the old "demote it to inferred" behaviour).
3. `*_estimated: true` ⇒ `confidence: approximate` on that bound (R8).
4. A unit with no dates whose `within` target HAS dates inherits them:
   `basis: anchor` and `confidence: inferred` on the record's bounds, the
   verbatim provenance clause *"from the dates of the &lt;subject&gt; stay |
   tenure | schooling"*, and `dates.basis: "inferred"` with `inherited_from` on
   the unit. A child domain that records ONE DATE rather than a stretch
   (a birth, a child, a loss) never inherits: a stay's span is not a person's
   birthday.
5. A unit with no dates and no dated parent is `dates.basis: "none"`, renders
   "no date read", and earns the domain's own opening question. It never says
   "inferred".
6. `names` (nickname · city · address · place_ref · link) map onto the record's
   E-L2c fields, per domain, and the accepted set is PROBED out of
   `validate_landmark` rather than declared.
7. Dated events carry `filing: "claim"`; undated ones carry `filing: "moment"`.
   Cut 6g files them; v291 reads and carries them.
8. `within` cycles and dangling refs are findings, never crashes. A cycle is
   cut where it is found and nowhere else.
9. Every span of the text is accounted for by a unit quote, an EVENT quote, a
   story or an unrecognized span.

### The proposal's keys (§3.2 — the platform transports these verbatim)

A unit gains `within` (the parent's `unit_id`, or `null`) and `names`. Its
`dates` block is `{start, end, precision, basis, confidence, estimated:
{start, end}, inherited_from, clause}` where `basis` is one of
`stated | inferred | none`. The proposal gains `events[]` —
`{event_id, text, kind, subject_mention, date, within, quote, filing}` — and
`stories[]` gain `within`. The `unrecognized` key keeps its name. Nothing
existing is renamed.

### Lints

`OFFER_LINT_CLASSES` grows from four to six. `no_fabricated_date` widens from
stated bounds to EVERY bound (an inherited year is still a year the document
carries somewhere). Two are new: `quotes_locate` — every unit and every event
carries a quotation located in the text; and `honest_basis` — no `inferred`
without a provenance clause (D5), and no `stated` bound shown certain that the
reading marked estimated (D3, R8).

### Two shared-root fixes this found

`date_evidence` matched a month only by its full name, so a date written the
way v290's own reader parses it (`Jun 1986`) was dropped as unevidenced; it now
reads the 3-letter abbreviation too, from `chronology.MONTH_NAMES` rather than
a fourth private copy. And `locate` now honours its `hint` on the
whitespace-tolerant path, so a document that repeats itself — the same employer
on three consecutive blocks — locates three quotes instead of three copies of
the first.

### Status

Accepted for the offer path at v291. Cut 6g added filing for relations, names
and events; Cut 6h (v293) deleted `grammar_units`, `_date_dict` and the
`go_dig_writer.plan_import` import — see "Amendment 3" below.

## Amendment 2, 2026-09-04 (v292) — R7's filing: relations, names and what a stay holds

Controlling record: `lifehug-platform
docs/decisions/2026-09-03-timeline-unification/add-landmark-reading-plan.md`
§2 (R7), §3.2 and §4's "6g". v291 READ relations, names and events and carried
them on the proposal. This amendment FILES them.

### R7, as the system does it

> "Any information with a span should be connected to that time span."

- **The proposal is grouped.** `groups[]` is `[{unit_id, members: [{kind, id}]}]`
  — one entry per unit with `within: null`, in text order, whose `members` are
  the units, events and stories whose `within` resolves to it **transitively**
  (a school inside a stay brings its own events), plus a trailing
  `{unit_id: null}` entry for what belongs to nothing. `landmark_offer.build_groups`
  computes it; `render_proposal` renders one head per group with its members
  indented; the five offer goldens pin it. Stories gained `story_id`
  (`derive_story_id`, content-addressed on the span they are) because a member
  is named by an id and a story had none.
- **`apply` files a group, not a list of units.** Confirming a stay files what
  is on its card. A group whose head unit the person did not confirm files
  nothing: an event rides its stay.
- **Names file through the E-L2c road.** The reading's `names` are already on
  the record (`landmark_reading._record_for`), so the one writer files them:
  `city` mints or finds the roster place, `nickname` becomes an ALIAS decision
  on that place (`go_dig_writer.record_unit` → `roster_relations.alias_decision`,
  the trailing parenthetical moved to the entry's note), `address` and `link`
  are the entry's own fields. Without the alias, "the Orchard House" in a later
  story joins to nothing — the place join is provable source overlap with the
  roster place (`timeline._place_for_event`), never a keyword.
- **An inherited unit files with its provenance intact.** Every bound carries
  `basis: anchor`, `confidence: inferred` and the verbatim clause; the writer
  keeps them (`chronology.normalized_date` preserves `provenance` and
  `landmarks_interaction.validate_landmark` passes it through). A unit with
  `basis: "none"` files with no dates at all.
- **One promoted slice per group.** The whole submission is still promoted (R3:
  the words are evidence on submit). The group's own words — the head unit's
  quote extended to cover its members' — are promoted SEPARATELY, and the
  events, moments and stories that group holds cite that. A source that is the
  whole document overlaps with every place in it; a slice overlaps with one
  stay. The slice carries the head unit's `unit_id` as its `turn_ref`, which is
  what keeps it its own utterance when a submission IS one stay.
- **Dated events file as claims, undated ones as moments.** A dated event is a
  `date` claim; an undated one is `temporal_claims.OCCURRENCE_CLAIM_TYPE` — the
  type that asserts a thing happened and asserts nothing about when. That
  choice is the SYSTEM's, made from the bytes: `occurrence` is withheld from
  every model-facing vocabulary (`MODEL_CLAIM_TYPES`) and the reading leaf names
  no claim type at all, exactly as `classifier_claims.temporal_reading` decides
  the same thing over a classification it did not make. Both go through
  `general_listener.bind_claims` and `temporal_store.write_receipt` — the same
  road every other claim in this vault takes.
- **An event's date is evidenced like a unit's.** `_event_row` re-reads it with
  `date_evidence`; a year the submission does not carry is dropped and the event
  files as a moment. `filing` therefore says what will actually happen to it,
  which is the only thing that makes it safe for `apply` to act on.

### Two decisions §3.1 did not settle

1. **The stay rides on `place_mentions`, not on `event_mention`.** §3.1 rule 7
   says an event's `event_mention` is the `within` unit's subject.
   `temporal_timeline._node_what` publishes the longest `event_mention` as the
   node's own human text ("what a person would call this thing"), so obeying the
   letter labels *"Dad started at the mill"* as *"the blue house"* on the
   person's own timeline — D2's class of defect. The rule's intent is the JOIN,
   and `place_mentions` is the field the join reads (`event_identity`'s entity
   signal, `temporal_timeline._group_place_mentions`), so the stay's names go
   there and the event keeps its own words.
2. **An inherited stretch is a stretch, but never a container.**
   `episode_containers.span_from_claims` read a stretch only out of bounds the
   person STATED, which is right for deciding what a container is (a container
   is opened in the person's own words) and wrong for drawing a node: a
   schooling with two inherited ends was published as a point at its start. It
   gains `require_stated`, defaulting to today's behaviour;
   `_apply_participation_span` asks for the stretch whatever its basis, and the
   record carries the inherited basis rather than being stamped `stated`.

### Containment: what the graph can hold, and what it cannot (§6 open item 1)

Verified against the code, not assumed. The calculated projection's relation
block (`containments` / `related` / `proposed_links`, keyed
`temporal_projection.IDENTITY_LINK_KEYS`, relations
`episode_fold_contract.RELATIONS`) is built by
`episode_fold.EpisodeIdentity.node_block` out of a node's TELLINGS. It is a
telling→episode relation. **There is no episode→episode edge**, so a
school-inside-a-stay is a DATE INHERITANCE and not a rendered containment —
6g does not fake one.

What a stay CAN contain is a telling, and that road is deterministic: the
group's promoted slice carries `question_context` = the stay's own telling ref
(`temporal_store.QUESTION_CONTEXT_KEY`, `episode_binder.QUESTION_CONTEXT_SEAM`,
event-identity §12b ruling 5 — "the session records which container its
question targeted", a fact about what was told and not an inference from it).
`episode_binder`'s deterministic containment rung turns that stamp into a
`part_of` binding, and the fold then gives the undated moment the stay's bounds
as its `possible_temporal_value` with the provenance *"sometime during …"*.

Filing that binding is the BINDER's act, never `apply`'s.
`event_identity.file_event_identity` is reachable only from
`bind-episodes --apply` (owner-reviewed, per I2b's rollout gate) and from a
person's own answer in `identity_questions`; calling it from `apply` would put
a second writer on the identity substrate. `apply` stamps; the binder files.

### Undo

`retract` takes back everything the apply filed: the units' claims (unchanged),
the events' and moments' claims under the `landmarks/events` scope
(`landmark_offer.EVENTS_SCOPE`), and the roster ALIAS — but only one this apply
actually CHANGED, because a nickname the place already answered to was not this
act's to file and is not this act's to remove (`roster_relations.retract_alias`).
The promoted sources — the submission and every slice — stay on disk. Nothing
immutable is deleted.

### Status

Accepted at v292. Cut 6h (v293) deleted `grammar_units`, `_date_dict` and the
`go_dig_writer.plan_import` import; 6j renders `groups` on the page.

## Amendment 3, 2026-09-04 (v293) — the grammar leaves the path

Controlling record: `lifehug-platform
docs/decisions/2026-09-03-timeline-unification/add-landmark-reading-plan.md`
§2 (R6–R9) and §4 "6h". v291 stopped the offer path from CALLING the block
grammar; this cut stops it from being ABLE to. `grammar_units`, `_date_dict`
and `_grammar_block_quote` are deleted from `landmark_offer.py`, along with
the `go_dig_writer.plan_import` import that was `grammar_units`'s only
reason to exist. Nothing else in the module changed: `propose` already read
one way, and `apply` still files through `go_dig_writer.record_unit`, the
one remaining — and now the ONLY — `go_dig_writer` name this module carries,
confined to `apply` and to `unit_filing_digest`, the pre-existing (Cut 6a)
filing-identity helper `apply`'s own receipt calls.

`tests/test_landmark_offer.py::NoSecondCopyTests` is the guard: an AST
import-sweep (the discipline `tests/test_go_dig.py::NoModelCallTest` already
uses) proves neither `landmark_offer` nor `landmark_reading` can import
`go_dig_grammar` by any route, and a source-scope check proves `go_dig_writer`
is never named outside `apply` and `unit_filing_digest` — in particular,
never again inside `propose` or anything it composes. `go_dig_grammar.py` and
`go_dig_writer.py` themselves are untouched; nothing on the offer's READ path
reaches them any more, and Cut 7b is where they are deleted for good.

The host-run protocol (Amendment, Cut 6c, as replaced by the v291 amendment)
is unchanged and reconfirmed as the one-reading shape: `--propose --prompts`
→ `{"reading": {"prompt", "model", "prompt_version"}}`; `--propose
--completions FILE` with `FILE = {"reading": <completion>}` → the written
proposal. `docs/handbook/interactions/landmarks.md` and
`interactions/landmarks/README.md` carry the exact CLI sequence a host runs.

### Status

Accepted and shipped at v293.

## Amendment 4, 2026-09-15 (v296): Punctuated Atomic Landmark Names

Issue #328: `Pell & Sons` and a residence labelled `Harbor City, ST` reach
the real landmark writer but fail as `aggregate_subject_mention`. The converter
knows the domain's `identity_kind`; the temporal claim previously lost it.

The converter now preserves optional `landmark_identity_kind` on identity and
date claims only for place/organization domains and only when the raw mention
would otherwise trip the enumeration heuristic. It derives this from the
framework question set, never a proposed record's extra fields. The pure
temporal validator accepts this annotation only with `source_kind: import`,
a `landmark:entry-` source identity, and the shared existing deterministic
`legacy-entry-import/rule:1` or `landmark-record/rule:1` extractor identity.
The listener's closed draft shape cannot supply it. These are internal producer
provenance checks, not cryptographic proof of an entity's real-world identity.
A free `subject_ref` or resolution annotation is not an exemption.

The owner authorized the narrow typed place/company qualification. Its
engineering limitation is explicit: this type alone cannot distinguish one
punctuated name from several places/companies collapsed into one malformed
record. The reading still owes one unit per subject; this is not permission to
aggregate units. Person, relationship, episode, unknown-domain and ordinary
untyped mentions keep the exact previous enumeration refusal. No regex, word
limit, human label, raw mention, date, or claim identity input changes.

This is additive schema-1 metadata, retained through claim and receipt readback.
No existing source/receipt is rewritten. Ordinary claims omit it so retrying
against an older immutable receipt is byte-compatible. Receipt conflict checks
remain strict. No new roster entry is minted merely to evade the guard.
The package owns this behavior; hosts consume it by pin, not by punctuation
sanitization or admission shortcuts.

## Amendment 5, 2026-09-15 (v297): Attribute Evidence and House Identity

Issues #335/#336 are different failures after a correct model reading: the
source partition counted only the short unit quote, and the writer aliased a
house nickname onto the containing city. One model pass remains authoritative.

### Coverage and Reading Compatibility

Optional `name_evidence` on each reading unit maps name fields to exact value
quotes and explicit one-based occurrences in the whole source. A repeated
value without an occurrence is not evidence. The quote must equal the value
the semantic recorder accepted, so a dropped link or nickname parenthetical
cannot conceal its source. Validated offsets persist on the proposal. Two
units claiming overlapping evidence both lose that evidence, not their facts.
Coverage subtracts exact intervals; touching a sentence never covers all of it.

Formatting is separate and bounded: literal line-start field labels (optionally
bulleted), empty Markdown bullets, and `[URL](URL)` whose label exactly equals
the accepted URL. A meaningful different link label, arbitrary trailing prose,
or a whole attribute assertion is not covered as a value. No keyword blacklist,
second interpretation grammar, Maps resolution or model change is introduced.

`PROPOSAL_READING_REVISION = 2` participates in `derive_proposal_id` and is
persisted as `reading_revision`. Missing metadata means legacy revision 1.
This allows a new proposal at unchanged text and generation 32 without replacing
the first successful legacy file. Old IDs remain explicitly readable/applyable.
Existing applied receipts short-circuit before writes, including after undo;
upgrading the package is not permission to migrate an already completed act.
Explicitly applying an unchanged unit from a newer reading of that same text
returns `content_ambiguity` before any writes, naming the earlier receipt.
This intentionally refuses rather than minting duplicate import sources or
migrating the old city association. Matching uses the same unit ID or exact
validated record, not speculative equivalence. New, previously unapplied units
remain fileable. Corrections with changed facts are a distinct confirmed act;
this does not attempt general cross-document duplicate resolution.
After a matching full undo, a fresh current reading may be explicitly applied
as a new act. The guard requires the matching retraction receipt plus durable
source claims fully marked retracted under its correction coverage; a marker
alone, missing evidence or partial scopes remain conservatively refused.
The original applied receipt and undo remain immutable and cannot be revived
by replaying the old proposal. Malformed non-string proposal states are never
eligible for reuse and cannot abort a batch of otherwise valid proposals.

Hosts must use `reading_request_key(text)` as their opaque revision-aware
mutation AND model-key input, composing their existing attempt policy with it.
`proposal_matches_current_reading(proposal, text, generation=None)` validates
exact source, current revision and package-derived ID independently of state;
it permits displaying a current failed reading but rejects unknown/non-string
states using the package's `PROPOSAL_STATES`. `is_current_proposal` adds
successful-state eligibility for bypassing the model and adopting a commit.
`proposal_reading_rank` orders compatible exact-text matches by generation then
revision; invalid explicit metadata ranks below valid. A new proposal ID alone
cannot prevent an old host immutable mutation or pre-model lookup from reusing
the old reading. Platform #846 owns that integration, not a second hash policy.

### The House and Its Stays

The existing roster/recorder path now creates an individual house from exact
supplied address and city, independent of nickname and dates. It records
`place_kind: residence`, `residence_identity`, and `located_in` its city.
An established individual ref wins; a ref naming that CITY does not suppress
address evidence. A nickname-only house can be established without a date;
its name is not silently treated as an alias of the city. No address-equivalence
guess or automatic rewrite of historical city aliases occurs.
If a nickname-only stay identifies several existing houses, or stored exact
residence identity matches multiple refs, resolution refuses before minting.
It never creates a third house to bypass ambiguity. Add Landmark reports this
as `content_ambiguity`; an explicit individual ref can disambiguate.

Two homes in one city have different refs. Repeated stays at one house share
the place but remain separate episodes. The existing identity resolver and
episode binder can place a later undated story at one uniquely named house;
multiple stays there remain `place_ambiguous` without a stated date. Refusing
that stay choice does not lose the known house identity.

Owned alias decisions carry telling-ref ownership in the same roster, not a
parallel identity store. A collision is persisted as discoverable candidates
and an explicit `applied: false`, `identity_uncertain` receipt, never a first
match. Existing city aliases stay untouched. Undo removes one owner's claim,
retains aliases needed by other stays, and removes a newly created alias after
its last owner; preexisting curated aliases remain. Old unapplied proposals
derive this behavior from their validated record without new name evidence.

The canonical `entity_roster.apply_previous_decisions`/`normalize` path retains
settled house refs, parent hierarchy and owned aliases through empty or
colliding refresh output. Raw model output cannot supply identity metadata or
the in-process preservation marker. This is reachable through the monthly
roster refresh, not an out-of-loop repair job. Existing ordinary roster behavior
is unchanged outside these explicit place decisions.

## Amendment 6, 2026-09-15 (v298): One Publication Per Confirmed Apply

A synthetic populated vault with 1,000 classifier moments showed the 76-unit /
30-event apply taking 186.812 seconds on v297: 77 calculated publications and
154 active-index rebuilds. The same input on a small fixture took 14.126 seconds.
The input size alone was not an adequate performance test. The controlling
contract is `docs/pr-specs/landmark-apply-publication-batch.md`; platform #847
consumes the package change without increasing time budgets.

The package batches only calculated publication, not landmark truth. Every
`save_landmark` still folds and writes the landmark drawing before returning,
so the next unit sees earlier merges, supersession and repeated stays. Groups
still file their source slices and event claims in the same order. The outer
successful dirty batch then calls the canonical calculated publisher once,
before computing gain, retiring opportunities and writing the apply receipt.
An empty batch does nothing; an unchanged final projection retains its generation.
Standalone calls keep immediate publication. Proposal, claim, source, telling
and receipt identities, CLI arguments and reading revision are unchanged.

Repeated guarded receipt loads were the remaining dominant cost, so the same
apply scope permits `temporal_store.receipt_read_batch` to reuse validated
immutable inputs. Every load still lists current paths; every reuse checks
containment, symlinks and file identity/change metadata (device, inode, mode,
size, nanosecond mtime and ctime). A cache fill checks identity on both sides
of the canonical read. New or changed receipts read normally; unreadable or
missing files are never cached. Corrections and active-index folds remain
fresh. Cached objects are copied before returning to callers. Immutable write
conflict checks are untouched. This is not a persistent cache or a second fold.

Both scopes are context-local, vault-bound and closed on exit; an escaped
copied context cannot later reuse the cache or silently defer a publication.
Nested same-vault publication scopes flush only at the outer boundary.
Cross-vault bindings fail before writing another vault. A failed nested scope
cannot be swallowed into a successful outer flush.

Failure is not rollback: evidence and landmark drawings already filed remain
durable, and the preceding calculated projection may remain until retry/repair.
Neither a failed unit/group nor a failed final publication writes a successful
apply receipt. Retry reuses immutable source/claim identities and publishes
the complete result. Previously successful receipts still short-circuit before
the scopes, including receipts subsequently undone; no historical receipt,
projection-gain receipt, source or proposal is rewritten by this upgrade.

## Amendment 7, 2026-09-15 (v299): Validated Receipt Directory Inventory

The follow-up contract is `docs/pr-specs/landmark-receipt-fold-scale.md`.
v298 still performs 78 full index folds for a 76-unit grouped filing. A
warm synthetic fold of 1,107 receipts made 28,808 stat calls and 4,430
directory scans; its unprofiled 0.398 seconds outweighed index serialization
at 0.038 seconds. The actual hosted filing still timed out despite the
previous synthetic gate. This amendment addresses traversal, not an assumed
need to defer writes or calculate a landmark-only index.

Within the existing `receipt_read_batch`, `vault_paths.VaultDirectoryInventory`
retains only directory signatures and names. A refresh opens the bound root
and receipt subtree without following symlinks, rejects root identity drift,
and visits every child with fresh metadata. Unchanged directories reuse their
names; membership changes force enumeration. Existing-file signatures are
checked independently of parent timestamps, so edits, corruption and repair
remain observable. Changed/new inputs still use the canonical receipt reader.
Directory identity and membership are checked around each visit, with root
and subtree bindings checked again before the result is returned. Symlinks,
special files and concurrent tree changes fail closed rather than licensing
stale cached results. All descriptors close on success or exception.

Parsed receipt copies remain isolated from callers. Directory and receipt
caches close with their vault-bound scope, including nested exceptions and
escaped contexts. Corrections are still loaded afresh; the full authoritative
fold and every active-index write are unchanged. Standalone receipt readers,
immutable write validation, sequential landmark merge/supersession, final
publication ordering and applied-receipt replay retain their existing paths.
No durable format, identity formula, model request or host budget changes.
