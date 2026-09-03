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
it shipped survives as an internal extractor and nothing user-facing names the
product it came from (R4)

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

### 2. Three passes, in order, none of them new

1. A **deterministic first pass** over text a block grammar fully matches
   (`landmark_offer.grammar_units`). Zero model calls; a thirty-block
   residence document proposes thirty units for the cost of a string split.
   A block with one line the grammar does not know is NOT half-parsed — it
   goes on to the listener whole, because half a parse is a guess.
2. The **general listener** (ADR 0029) with no domain: what does this text
   touch at all.
3. The **focused recorder** (ADR 0028) once per domain the listener named,
   with that domain's already-filed entries in view — which is why a second
   stay in a city the vault already knows becomes a second entry rather than
   a merge.

Model tiers are the ones already declared: `role.listener` and
`role.recorder` are Haiku-class, `role.worker` is Sonnet-class. There is no
separate format-repair prompt and deliberately no place for one — a paste the
grammar cannot read is not malformed input to be fixed before reading, it is
ordinary text, and the Haiku-class listener is what reads it. **No model call
recalculates a date:** every interval that files is `chronology`'s, derived
from what the person wrote.

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
| `proposal_id` | digest of the submitted text and the vault generation it was read against | the same paragraph offered after the timeline moved is a NEW reading, because the known entries the recorder saw are different |
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

**What it costs.** One listener completion plus one recorder completion per
domain the listener named, at Haiku-class, per submission — the same shape and
the same tier as a landmark answer's cost, paid once per paste rather than
once per turn. Text a grammar fully matches costs nothing at all.

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
failed. It survives as an extractor for text it matches, and R4 forbids
anything user-facing naming the product it came from.

**Trusting the completion's `basis`.** The model that guessed the year is the
last thing that should grade the guess. §4.2's dividing line is a question
about bytes and is answered as one.

**Filing on submit.** Rejected by R3's proposal step: landmark-grade input
gets a confirmation screen. Evidence is durable at submit; landmarks are not.
