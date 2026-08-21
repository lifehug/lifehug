# Contract: question-candidate-placement-aside

## Why

Platform ADR 0020 (`lifehug-platform/docs/adr/0020-play-is-a-deep-link.md`)
retired the machine this Interaction was designed against: Play is no longer a
typed session that holds an answer until placement resolves — it is a deep link
that starts the package `promote` immediately, and platform contract
review-loop/45 ("Play is a background promotion") moves that promotion into a
worker job so the conversation never waits on the vault. Between them, the
premise behind ADR 0018's `placement_action: resolved|ask_now|defer` triple is
gone: by the time the first assistant reply is composed, the question is
already being placed in the inferred category, in the background, and the
platform captures carry `candidate_id` until the qid is stamped. Placement is
therefore no longer a gate to pass before answering — it is a fact to mention
once and a correction to accept when the user offers one. Issue #170's PR A
shipped the composed child (v181) and PR B shipped idempotent promotion
receipts (`system/candidate_promotion.py`, v187); this PR is the behavior
change that reconciles the child's prompt and output contract with the model
the platform actually runs, and it is deliberately the smallest one that can:
exactly one new turn-output field, no new lifecycle states, no placement model
purpose, and no new platform mechanism.

## Rulings (owner, 2026-08-21 — verbatim, binding)

1. The first thing the user sees is the question. Nothing else.
2. The FIRST assistant reply does its ordinary Conversation job (receive the
   answer, offer the next thread) and APPENDS the placement as a natural aside:
   "By the way, I've put this with <focus> — tell me if that's wrong."
   Placement is a footnote, never the opening act.
3. Silence is affirmation. No gate, no parsing of "yes". The platform has
   already promoted into the inferred category in the background; the aside is
   simply true when said.
4. Disagreement is a MOVE: when the user names a different place ("no, that's
   Boatworks"), the turn's structured output carries
   `placement: {category: "<letter>"}` (closed roster, validated); the platform
   applies the move in the background. The model may emit a placement change on
   ANY later turn when the USER signals one — it never raises placement itself
   after the first reply (owner: "it may admit a placement change if I sign
   on"; re-litigating each turn was rejected as noise).
5. No confident category (no `target_category`, or below
   `placement_confidence_threshold`) → the first reply ASKS once, naturally
   ("Where does this belong — your childhood, or Boatworks?") instead of
   asserting; the user's next turn yields `placement` or nothing; nothing → the
   platform's generic fallback after its timeout. Asking happens at most once
   per session.
6. This is Question Candidate interaction design — the child of Conversation —
   not a platform mechanism. The platform's only job: read an optional
   `placement` from turn outputs before/after promotion and call the existing
   package verb. Exactly one new output field; no new states; no placement
   model purpose.

## Binding facts

As of `origin/main` `2631fd0` (PR #180), `system/version.json` version **187**,
released 2026-08-20.

**Parent Conversation turn contract (the shape the platform actually runs).**
The played session is an ordinary `mode="chat"` session (platform
review-loop/45 §B), so the model output the platform parses is the parent's,
not the child's ADR-0018 shape:

- `system/conversation_delivery.py:284` `_output_contract_block(shape: TurnShape) -> str`
  — the runtime OUTPUT FORMAT appendix appended to every turn prompt.
- `:317–343` the literal JSON block and its per-field notes; `:324` the
  `"held_question_id"` line and `:335` its note are the exact precedent this
  PR follows for an additive field.
- `system/conversation_delivery.py:366` `parse_turn_output(raw) -> dict | None`
  — tolerates a ```json fence, rejects nothing else; `:393–394` is the
  additive-degradation pattern (absent or wrong-typed → `None`, never an
  error, per ADR 0016's closing rule) and `:400` its place in the returned
  dict.
- `system/conversation_delivery.py:1043` `run_post_answer_turn(...)` — the turn
  engine; `:1209–1211` reads `held_question_id` out of the parsed turn.
- `system/conversation_delivery.py:714`
  `_detect_declined_held_question(session, user_turn_index)` and
  `system/conversation.py:465` `record_declined_questions(...)` — the
  precedent for a deterministic, non-model-authored session fact. Placement
  does **not** get one (see Design §D).
- `system/conversation.py:327` `append_turn(...)`, `:272` `"turns": []` — the
  transcript the "asked once" fact is read from.
- `interactions/conversation/prompt/turn-instructions.md` — leaf turn template.
  **Not modified by this PR.** ADR 0018 promised ordinary Conversation stays
  byte- and behavior-identical to v180; that promise holds.

**The child (composition).**

- `interactions/question_candidate/interaction.yaml` — `extends: conversation`,
  `extends.version: 1.0.0`; `:14` `knob.placement_confidence_threshold: 0.8`;
  `composition.leaf: prompt/turn-instructions.md|context/manifest.md`.
- `system/interaction_registry.py:168` `resolve_interaction_lineage`, `:224`
  `compose_interaction_asset`, `:265` `audit_interaction_package` — the
  composition authority. Append assets (`prompt/identity.md`,
  `prompt/behavior.md`, `prompt/examples.md`, `router/*`) inherit; the two
  leaf assets are child-owned. This PR edits leaf and append-child files only;
  it adds no asset and changes no composition policy.
- `interactions/question_candidate/context/manifest.md` — the per-turn assembly
  recipe (items 4–6 are the untrusted JSON block, item 7 the child turn
  instructions last).

**The validator (pure, no writes).**

- `system/question_candidate.py:27` `VALID_TURN_KINDS`, `:28`
  `VALID_PLACEMENT_ACTIONS`, `:245` `validate_question_candidate_input`,
  `:343` `_category(roster, category_id)` (exact, closed-roster lookup —
  no fuzzy/case-fold), `:441` `lint_inherited_reply`, `:452`
  `_question_is_valid`, `:460` `parse_question_candidate_output`, `:504` the
  placement-action branch, `:514` the threshold read, `:570`
  `validate_question_candidate_decision`.
- `interactions/question_candidate/evals/lints.yaml` — `cap.reply_chars: 2200`
  plus the seven `placement_gates.*` gate classes.

**Goldens / eval harness.**

- `interactions/question_candidate/evals/goldens/fixtures.json` (synthetic
  inputs + model proposals + expected normalized facts),
  `sample_predictions.json` (parallel, scorer arithmetic without a provider),
  `evals/goldens/README.md`, `evals/rubrics.md`.
- `system/question_candidate_evals.py:29` `load_fixtures`, `:59`
  `validate_fixture`, `:149` `score_predictions`, `:220` `check_gates`, `:226`
  `inherited_lint_action_failures`, `:302` `run()` — four layers; layer 4 skips
  loudly with no provider. Entry point:
  `python3 system/lifehug.py question-candidate-evals`.
- Parent conversation goldens live one file per case at
  `interactions/conversation/evals/goldens/*.json` (see
  `chat-cabin-hatch-honored.json` for the annotation shape:
  `turns[].annotations.{kind,topic,seam_ok,held_question_id,user_invited_question,properties}`).
- Tests: `tests/test_question_candidate.py`,
  `tests/test_question_candidate_evals.py`,
  `tests/test_conversation_delivery.py`.

**The bank's category invariant (load-bearing for the platform twin).**

- `system/lifehug_core.py:681` `parse_questions` — `:691` sets
  `"category": qid[0]`. A question's category **is** the first character of its
  id.
- `system/question_candidates.py:343` `next_question_id(bank, category)`,
  `:356` `ensure_category_exists`, `:370` `insert_question`, `:399`
  `promote_candidate_record`, `:437` `update_candidate` (writes candidate
  metadata `target_category` only — never the bank), `:727` `_infer_category`.
- `system/candidate_promotion.py:453` — the promotion marker validator enforces
  `question_id.startswith(category_id)`.
- Consequence, stated once so nobody re-derives it: **moving a promoted
  question between categories necessarily re-ids it.** Before promotion,
  applying a placement is free (it is just the category argument). See
  Platform twin §3.

## Scope

**In:** the `placement` turn-output field (structural parse + closed-roster
validation), the child's behavior/turn-instruction/example prompt deltas, the
placement lints, goldens for the six cases below, the ADR 0018 amendment, the
child README correction, the version bump.

**Out (deliberate, named):**

- The `question-move` package verb (Platform twin §3) — a separate OSS PR;
  file it in this session.
- Retiring `parse_question_candidate_output`'s remaining callers. This PR marks
  the `resolved|ask_now|defer` triple superseded for the Play path and stops
  the prompt from asking for it; the function and
  `validate_question_candidate_decision` stay for the standalone
  `question-candidate-prompt` CLI path until a follow-up removes them.
- Any change to ordinary Conversation prompt bytes, to the registry, or to the
  composition policy.

## Design

### A. The `placement` field — schema and where it is validated

Exactly one new key in the structured turn output, additive and optional:

```json
"placement": {"category": "B"}
```

`null` or absent on every ordinary turn, and on every candidate turn that has
nothing to say about placement.

Two validation layers, deliberately split so neither module grows a
responsibility it does not have:

1. **Structural** — `system/conversation_delivery.py:366` `parse_turn_output`.
   Accept only an object with exactly the key `category` whose value is a
   non-empty string of ≤ 8 characters after `.strip()`; uppercase it. Anything
   else (missing, `null`, a bare string, extra keys, wrong type) → `None`.
   Never raise: a malformed `placement` degrades to "no placement", exactly as
   `held_question_id` degrades at `:393–394`. Returned as
   `"placement": {"category": "<UPPER>"} | None`.
   `conversation_delivery` does not own the roster and performs no membership
   check.
2. **Closed-roster** — `system/question_candidate.py`, new pure function:

   ```python
   def validate_placement(value: object, *, roster: dict) -> dict | None:
       """Return {"category_id", "label", "focus_id", "focus_label",
       "category_revision"} for an exact roster member, else None."""
   ```

   Implemented on `_category(roster, category_id)` (`:343`) — exact match
   only; no fuzzy, no case-fold, no label→id derivation, no id invented from
   prose. Unknown letter → `None`. Returns the roster entry so the caller can
   render the **focus label** (never the id) and bind a `placement_revision`
   with the existing recipe at `:354`.

The threshold knob is unchanged: `knob.placement_confidence_threshold: 0.8`
(`interaction.yaml:14`, read via `_manifest_number` at `:514`). It now gates
only rule 5's assert-vs-ask decision, and it is evaluated by the **caller**
against the candidate's `target_category` confidence before the turn is
composed — the model is not asked for a confidence number any more.

### B. When the aside appears, and when the ask does

The placement sentence is a property of **the first assistant reply of the
session** and of no other turn.

| Session state at the first reply | First reply | `placement` field |
|---|---|---|
| Candidate has a `target_category` at ≥ threshold | ordinary Conversation reply, then ONE appended aside: *"By the way, I've put this with <focus label> — tell me if that's wrong."* | `null` (the platform already promoted there — nothing to apply) |
| No `target_category`, or below threshold | ordinary Conversation reply, whose SOLE question is the natural placement ask: *"Where does this belong — your childhood, or Boatworks?"* | `null` |
| Any later turn, user says nothing about placement | ordinary Conversation reply | `null` |
| Any later turn, the user names a place ("no, that's Boatworks") | ordinary Conversation reply, receipting the correction in one clause at most | `{"category": "<exact roster letter>"}` |

Never both an aside and an ask. Never an aside on a turn that is not the first.
Never a placement sentence the model raised on its own after turn one.

**Re-evaluation rule (ruling 4).** The model re-evaluates placement only on a
user signal. A user turn that names a place, corrects the aside, or answers the
rule-5 ask yields `placement`; everything else yields `null`. The model never
re-opens the topic, never asks a second time, never confirms a correction with
a question, and never narrates the mechanism ("I'll move that", "updating the
category") — it simply receives, and the field carries the fact.

**Rule 5's fallback.** If the ask goes unanswered, nothing happens here: the
turn output stays `null` and the platform's own timeout applies its generic
fallback (platform ADR 0020: the vault's primary generic category). The model
does not re-ask and does not manufacture a category.

### C. Prompt deltas — exact

**C1. `system/conversation_delivery.py:284` `_output_contract_block`.**
Add a `category_roster` (or equivalently a `placement_stage`) field to
`TurnShape`, default `None`. When it is `None` the returned string must be
**byte-identical to today's** — this is a required test. When it is present,
insert one line into the JSON block after `:324`'s `held_question_id` line:

```
  "placement": {"category": "the exact roster letter"} | null,
```

and one note after `:335`'s:

```
- "placement" is null on every turn except one where the USER named where
  this belongs; then it is the exact roster letter from CATEGORY_ROSTER and
  nothing else. Never invent a letter, never guess, never fill it to look
  decisive.
```

**C2. `interactions/question_candidate/prompt/turn-instructions.md`** — replace
lines 6–24 (the ADR-0018 JSON object and its four sentences). The child no
longer declares its own output shape; it declares the parent's shape plus the
one field, and the placement rules for this turn:

```markdown
Reply under the inherited Conversation output contract (see the runtime's own
OUTPUT FORMAT appendix). This extension adds exactly one optional field,
`placement`, and the rules below.

## Placement on this turn

- **`{placement_stage}`** is one of `assert`, `ask`, or `settled`.
- `assert` (first reply, category known): answer the person first — receive
  what they said, offer the next thread — then append ONE sentence:
  "By the way, I've put this with {focus_label} — tell me if that's wrong."
  It is the last sentence of the message, it is not a question, and it is the
  only time you will mention placement. Set `placement` to null.
- `ask` (first reply, category unknown): answer the person first, then make
  the placement question the message's SINGLE question, in their own words —
  "Where does this belong — your childhood, or Boatworks?" Never list ids,
  never offer a menu, never ask yes/no. Set `placement` to null.
- `settled` (every later turn): say nothing about placement. If — and only
  if — this turn's user message names where it belongs, receive that in a
  clause and set `placement` to `{"category": "<exact roster letter>"}`.
  Otherwise `placement` is null.
- You never raise placement yourself after the first reply, never ask twice,
  never confirm a correction with a question, and never describe what the
  system will do with the answer.
```

**C3. `interactions/question_candidate/prompt/behavior.md`** — rules 1–9 keep
their numbering (the frozen-numbering discipline of ADR 0016). Deltas:

- **Rule 1** — retitle to *"The question is the first thing, and the only
  thing."* Body: Play opens on the exact candidate; the person sees the
  question and nothing else. Never a category selection, modal, menu,
  preamble, or placement question before they have answered.
- **Rule 4** — retitle to *"State placement once, as a footnote."* Body: when
  the category is known, the first reply appends one plain sentence naming the
  focus in the person's own vocabulary. It is an aside, not an act — the
  placement has already happened. Silence is affirmation; never ask them to
  confirm it, never wait on it, never repeat it.
- **Rule 5** — replace *"Defer when asking would interrupt"* with *"Ask once,
  or not at all."* Body: with no confident category, the first reply's single
  question is the placement question, asked naturally. One session, one ask.
  If it goes unanswered, let it go.
- **Rule 6** — replace the `ask_now` mechanics with the correction rule: a
  placement change is the person's move, never yours. When they name a
  different place, receive it in a clause and carry the exact roster letter in
  `placement`. Never announce the move, never re-litigate, never bring
  placement up again.
- **Rule 9** — keep *"Fail toward bounded uncertainty"*; drop `defer` from its
  vocabulary (`placement` null IS the uncertainty).
- **Completion doctrine** — delete the three-fact `answered` completion
  paragraph. Placement is no longer a completion precondition; the platform
  promotes first (platform ADR 0020). Replace with two sentences: the caller
  alone owns lifecycle facts; the model never claims promotion, a question id,
  a commit, or a receipt (rule 8, unchanged).

**C4. `interactions/question_candidate/prompt/examples.md`** — three worked
examples, replacing any that show the ADR-0018 triple:

1. *assert* — user answers the lighthouse question at length; reply receipts a
   concrete detail, offers the next thread, and ends "By the way, I've put this
   with Places that shaped me — tell me if that's wrong." `placement: null`.
2. *ask* — same opening, no confident category; reply receipts, then asks
   "Where does this belong — your childhood, or Boatworks?" as its only
   question. `placement: null`.
3. *correction* — turn three, user says "that's not childhood, that's
   Boatworks." Reply: "Boatworks it is — and the part about the winter
   haul-out is the piece I'd want more of." `placement: {"category": "W"}`.
   Note explicitly: no confirmation question, no "I'll move it", no second
   mention.

**C5. `interactions/question_candidate/README.md:10`** — the sentence "Starting
Play never promotes." is false under platform ADR 0020. Replace with: "Play
promotes in the background with the inferred category (platform ADR 0020); this
Interaction states that placement once, as an aside, and accepts a correction
as a move." Also correct the "Product actions" bullet that says "**Promote**
does not enter this Interaction. PR B of issue #170 owns that explicit
idempotent write and receipt." — PR B shipped
(`system/candidate_promotion.py`, v187); Play now triggers it.

### D. The "asked once" fact needs no new state

It is already in the transcript. The aside and the ask both live on the FIRST
assistant reply, so "have we asked?" is exactly "does this session have an
assistant turn?" — `session["turns"]` (`system/conversation.py:272`, appended
at `:327`). The caller computes `placement_stage` from that plus the
candidate's `target_category`:

```
placement_stage = "settled"  if any assistant turn exists
                  else "assert" if target_category at >= threshold
                  else "ask"
```

No new session field, no `declined_question_ids`-style ledger
(`conversation.py:465`), no new lifecycle status, no new model purpose. This
is what ruling 6's "no new states" means concretely.

### E. Lints

New gate class `placement_lints.*` in
`interactions/question_candidate/evals/lints.yaml`, enforced alongside the
inherited Conversation lints via `lint_inherited_reply`
(`system/question_candidate.py:441`). A reply failing any of these is a lint
failure exactly as a Conversation lint failure is — the existing degradation
path applies, and a placement sentence is never worth losing a reply over, so
a placement-lint failure retries the turn once **without** the placement
sentence before it degrades further.

| lint id | rule |
|---|---|
| `placement.aside_single_sentence` | in `assert`, the placement sentence is exactly one sentence and is the message's last |
| `placement.aside_not_a_question` | in `assert`, the placement sentence contains no `?` |
| `placement.ask_is_sole_question` | in `ask`, the reply contains exactly one `?` and it terminates the placement question (reuse `_question_is_valid`, `:452`) |
| `placement.never_repeated` | in `settled`, the reply contains no placement sentence at all |
| `placement.no_roster_ids` | no reply ever renders a roster id; only the focus label |
| `placement.no_gate_language` | no "confirm", "is that right?", "let me know if that's okay", "reply yes" — silence is affirmation (ruling 3) |
| `placement.no_mechanism_talk` | no "I'll move it", "updating the category", "filed under", "the system will" |

Gate values: all `1.0` (compliance classes), added under `placement_gates.*`
alongside the existing seven so `check_gates`
(`system/question_candidate_evals.py:220`) picks them up with no scorer change.

## Required tests

`python3 -m unittest discover -s tests` must pass; the named files:

**`tests/test_conversation_delivery.py`**
- `test_output_contract_block_byte_identical_without_roster` — the ordinary
  block is byte-for-byte what it is today when `TurnShape` carries no roster
  (the ADR 0018 "Conversation stays v180-identical" promise, mechanized).
- `test_parse_turn_output_placement_absent_is_none` — no key, `null`, and a
  legacy generation all yield `placement: None`, no error.
- `test_parse_turn_output_placement_malformed_degrades` — bare string, list,
  extra keys, empty string, 9-char value, non-string value → `None`.
- `test_parse_turn_output_placement_uppercased` — `{"category": "w"}` → `{"category": "W"}`.

**`tests/test_question_candidate.py`**
- `test_validate_placement_exact_roster_member` — returns the roster entry with
  label/focus/revision.
- `test_validate_placement_rejects_unknown_letter` — a letter not in the
  supplied roster → `None` (ruling 4's "closed roster, validated").
- `test_validate_placement_rejects_fuzzy_and_label_derived` — `"places"`,
  `"P "`, `"p"`-when-`P`-absent, and a label string all → `None`.
- `test_placement_stage_derived_from_transcript` — the §D derivation: empty
  turns + confident category → `assert`; empty turns + none → `ask`; any
  assistant turn → `settled`.
- `test_placement_lints_*` — one per row of the §E table, each with a passing
  and a failing reply.

**Goldens** — new files under
`interactions/question_candidate/evals/goldens/` plus their parallel entries in
`sample_predictions.json`, and matching cases in
`tests/test_question_candidate_evals.py`:

1. `placement-assert-first-reply` — confident category; the first reply carries
   the aside **exactly once**, as its last sentence, question-free.
2. `placement-assert-never-repeated` — the same session's turns 2 and 3 carry
   no placement sentence and `placement: null`. (The pin for "never again".)
3. `placement-ask-once-no-category` — no `target_category`; the first reply's
   sole question is the placement ask; `placement: null`.
4. `placement-ask-unanswered-not-repeated` — the user's next turn ignores the
   ask; turn 2 does not re-ask and emits `placement: null`.
5. `placement-user-disagrees-emits-move` — "no, that's Boatworks" on turn 3 →
   `placement: {"category": "W"}` with a one-clause receipt, no confirmation
   question, no mechanism talk.
6. `placement-unprompted-later-turn-null` — a long, placement-silent turn 4
   emits `placement: null`. (The pin for ruling 4's "never raises placement
   itself".)
7. `placement-unknown-letter-rejected` — a proposal naming `"Z"` against a
   roster without `Z` normalizes to no placement and does not fail the turn.

**Harness** — `python3 system/lifehug.py question-candidate-evals` passes all
four layers (registration/composition audit, fixture validation, sample gates
including the new `placement_gates.*` rows, inherited Conversation lints), and
skips layer 4 loudly with no provider seated.

## Version bump

`system/version.json`: **187 → 188**, `released` set to the merge date. This
changes behavior the user notices, so it gets a full changelog paragraph naming
what they will see: the played question is the first and only thing on screen;
the first reply now ends with a one-sentence note about where the question was
filed, or asks once where it belongs when that is not clear; saying "no, that's
Boatworks" moves it, with no confirmation step and no further mention. No new
`framework_files` entries unless a new golden file is added under
`interactions/question_candidate/evals/goldens/` — if it is, add each one in
the same bump (`system/update.py` only ships what the manifest lists).

## ADR amendment

**`docs/adr/0018-candidate-placement.md`** — Status `proposed` → `amended
2026-08-21 by docs/pr-specs/question-candidate-placement-aside.md`, with an
`## Amendment (2026-08-21)` section. Sentences that change:

| Location in 0018 | Change |
|---|---|
| Decision, "Play supplies lifecycle action `engage`. It may resolve placement silently or defer it… initial Play never requires a placement question." | Replaced: Play promotes in the background with the inferred category (platform ADR 0020); the first reply states that placement once as an aside, or asks once when there is no confident category. |
| Decision, the three-bullet `resolved` / `defer` / `ask_now` block | Superseded for the Play path. One optional output field `placement: {category}` replaces the triple; `defer` is expressed as `placement: null`; `ask_now` becomes a first-reply-only property, not an action; `resolved`'s confidence number moves to the caller, which evaluates `target_category` against `knob.placement_confidence_threshold` before composing the turn. |
| Decision, "Play alone remains engaged and has no promotion meaning." | Reversed: Play is approval; promotion starts immediately in the background. |
| Decision, "An answered candidate becomes complete only when durable answer, revision-valid placement, and answered outcome are all resolved." | Placement is no longer a completion precondition (the question is already placed). Completion is durable answer + answered outcome. |
| Consequences, "Category association can finish before, during, or after answer content. A partial durable answer is retained while placement remains unresolved." | Replaced: category association is settled at promotion time; a later correction is a move, not a resolution. There is no held answer (platform ADR 0020). |
| Consequences, "Platform #469 must route Play directly to Home/Today… and persist progress only after revalidating runtime decisions." | Superseded by platform ADR 0020 + review-loop/45: Play is a deep link, promotion is a background worker job, and every message files through the ordinary capture path. |
| Consequences, "v181 is an intermediate upstream release. The platform waits for PR B's final release…" | Historical; PR B shipped (`system/candidate_promotion.py`, v187). |
| Pin-bump reconciliation surfaces, "closed stage, turn-kind, placement-action, status…" | `placement-action` leaves the vocabulary list; `placement` joins the turn-output shape row. |

**`docs/adr/0016-asking-supply.md` and `docs/adr/0017-router-thread-binding.md`
— unchanged.** Naming them here because the commissioning brief expected
"0016–0018 re candidates": in *this* repo 0016 is asking-supply and 0017 is
router thread binding; only 0018 is the candidate ADR. The candidate ADRs
numbered 0016–0019 live in `lifehug-platform/docs/adr/` and were superseded
there by platform ADR 0020 — nothing in this PR re-decides them. The single
carry-over from 0016 that this PR *honors* (and must not break) is its
additive-field discipline: a new turn-output key is optional, degrades to the
pre-existing behavior when absent or malformed, and never errors a turn.

**No new ADR.** This contract records a behavior change inside an existing
decision's scope; the decision that made it necessary is platform ADR 0020.

## Platform twin

The platform's entire share of this is reading one field and calling one verb.

**1. Read `placement` from the session's turn outputs.**
`services/worker/app/runtime/programs.py`'s `play_promotion` program (platform
contract review-loop/45 §C) and the turn-completion path both already hold the
session document. Take the **newest non-null** `placement.category` across the
session's turn outputs. Nothing else changes: no new job, no new state, no new
model purpose.

**2. Before promotion → it is just the category argument.**
In `play_promotion` step 1, the promote category is, in order:
`placement.category` (if any turn produced one) → the candidate's
`target_category` → the vault's primary generic category (the #534 fallback).
That is the whole change on this side — roughly ten lines, no new surface,
because the package verb already takes a category:
`candidates-promote <cid> --category <LETTER>`
(`system/question_candidates.py:399` `promote_candidate_record`, receipt from
`system/candidate_promotion.py`).

**3. After promotion → a `question-move` verb must be added OSS-first.**
No such verb exists today, and it cannot be faked from the ones that do:
`candidates-update --target-category` (`question_candidates.py:437`) writes
candidate metadata only and never touches the bank; `focus-merge` merges
focuses, not questions. It is also not a one-line write, because a question's
category **is** the first character of its id (`lifehug_core.py:691`;
enforced again at `candidate_promotion.py:453`), so a move re-ids.

Minimal specification for that separate PR:

```
python3 system/lifehug.py question-move <QID> --to <CATEGORY> [--json]
```

- Refuse unknown `<QID>`; refuse an absent target (`ensure_category_exists`,
  `question_candidates.py:356`).
- No-op (returning the current id) when the question is already in the target —
  idempotent by `(qid, target)`, so a replayed job is safe.
- Mint `next_question_id(bank, target)` (`:343`); move the bank line into the
  target section preserving its checked/unchecked state and its provenance
  comment (`insert_question`, `:370`); append
  `<!-- moved-from: <old_qid>; moved: <iso8601> -->`.
- Write `state/question_aliases.json` `{"<old_qid>": "<new_qid>"}` and resolve
  reads through it, so already-filed answers, compiled wiki links, arc cards,
  perennials, rotation state, `question_candidates.json.promoted_question_id`,
  and platform captures keyed by the old id all keep resolving. An alias map is
  the cheap half of the job; rewriting every keyed artifact is the expensive
  half and is what the alias exists to avoid.
- One commit, one receipt: `{old_question_id, new_question_id, category,
  commit_sha}` — the same shape family as `candidate_promotion`'s receipts.

Until that verb exists, the platform's after-promotion branch **records the
placement on the decision record and does nothing else**. A partial move (bank
row moved, ids not aliased) is worse than a deferred one, and the failure mode
this whole ADR-0020 line exists to avoid is exactly that class of half-applied
saga.

**Twin issue** to file on `lifehug/lifehug-platform`: *"Worker reads
`placement` from question-candidate turn outputs"*, listing (1) and (2) above
as the ~20-line change, and linking this PR plus the `question-move` follow-up
as the blocker for (3).

## Acceptance checklist

- [ ] Exactly one new turn-output field exists (`placement`); no new session
      field, lifecycle status, model purpose, or state machine anywhere in the
      diff.
- [ ] `_output_contract_block` is byte-identical for ordinary Conversation
      turns; the byte-identity test proves it.
- [ ] A malformed or absent `placement` never errors a turn.
- [ ] Closed-roster validation lives in `system/question_candidate.py` and
      admits exact roster members only.
- [ ] The aside appears on the first reply, is one sentence, is not a question,
      and never appears again — goldens 1, 2 and 6 pin all three.
- [ ] The ask appears at most once per session, as the reply's sole question —
      goldens 3 and 4.
- [ ] A user-named correction emits `placement`; nothing else ever does —
      goldens 5 and 6.
- [ ] `python3 system/lifehug.py question-candidate-evals` passes all runnable
      layers.
- [ ] `python3 -m unittest discover -s tests` green; CI green
      (`test`, `framework-manifest`, `version-bump`).
- [ ] `system/version.json` at 188 with a full changelog paragraph; any new
      golden file listed in `framework_files`.
- [ ] ADR 0018 amended per the table; the child README's "Starting Play never
      promotes" corrected.
- [ ] Platform twin issue filed and linked; `question-move` follow-up issue
      filed.

## Owner closeout

**Look.** A demo transcript, printed by the golden replay (no provider
required) — paste it into the PR comment:

- *Screen 1*: the question alone. Nothing above it, nothing beside it.
- *Turn 1*: the person's answer → the reply receipts a concrete detail, offers
  the next thread, and ends: "By the way, I've put this with Places that shaped
  me — tell me if that's wrong."
- *Turn 2*: an ordinary exchange. No placement sentence anywhere.
- *Turn 3*: "no, that's Boatworks" → "Boatworks it is — and the part about the
  winter haul-out is the piece I'd want more of." Field: `{"category": "W"}`.
  No confirmation, no "I'll move it".
- *Second transcript, no confident category*: turn 1 receipts, then asks
  "Where does this belong — your childhood, or Boatworks?" and nothing after
  that turn ever mentions placement again.

**Judge.**

1. **The aside wording.** "By the way, I've put this with <focus> — tell me if
   that's wrong." Yes = this exact sentence ships as the prompt's literal
   example and the goldens pin its shape (one sentence, last, question-free);
   the model varies the connective tissue around it but not the move.
2. **The ask wording.** "Where does this belong — your childhood, or
   Boatworks?" Yes = the ask is always in the person's own vocabulary with two
   concrete alternates, never a menu and never a yes/no.
3. **Silence is affirmation.** Yes = there is no confirmation turn, no parse of
   "yes", and `placement.no_gate_language` makes asking for one a lint failure.

**Done when.** Contract merged → implementation PR green on CI (`test`,
`framework-manifest`, `version-bump`) → v188 tagged on merge → the platform
twin issue's ~20-line worker change lands and pins v188 → the `question-move`
follow-up is filed and remains the only open piece of this design.

🤖 Generated with Claude Opus via Claude Code
