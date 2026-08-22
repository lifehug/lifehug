# Contract: focus-onboarding-context

## Why

Platform contract review-loop/54 ("Focus Play is approval + onboarding, in the
background") applies to FOCUS candidates everything review-loop/45 and ADR 0020
established for question candidates: Play is not a typed research session that
holds a decision until some state machine resolves — it approves, scaffolds in
the background, and opens an ordinary conversation. A focus is not one question;
it is a whole new set, so the conversation Play opens has a job the question
path never had: **establish what the focus is about, well enough that the seeded
questions are worth asking.**

Two facts make this an OSS change rather than a platform one.

1. **This Interaction's premise is retired.** `interactions/focus_candidate/`
   was designed against ADR 0021's "Play/start is read-only … Completion may
   request the canonical research-source operation but never claims approval,
   Focus creation …". Under review-loop/54 Play *is* approval: the scaffold job
   runs at Play, and the conversation that opens is onboarding, not research
   toward a later approval decision. The child's README says "Play is
   read-only"; that sentence is now false.
2. **The seed generator cannot hear the conversation.** `research_expand.py`'s
   parser (`:1361–1425`) takes `--topic/--type/--output/--prompt/--from-response/
   --dry-run/--model/--force` and nothing else. `objective` is stored on the
   roadmap record by `focus_new` (`roadmap.py:495–548`) and feeds NOTHING
   generative — `_generate_and_promote` (`roadmap.py:459–491`) shells out with
   `--topic/--type/--output/--force` only. So today, whatever the person says
   in the onboarding conversation cannot reach the questions that conversation
   exists to improve. `approve_recommendation` (`recommend_focuses.py:879–932`)
   passing `objective = reason[:120]` is therefore a record, not an input.

This PR is deliberately the smallest change that fixes both: one repurposed
prompt leaf, exactly one additive turn-output field, one pure opening-line
helper, one deterministic stage derivation, six lints, seven goldens, and one
new CLI flag that carries onboarding context into the seed prompt.

## Rulings (owner, 2026-08-22 — verbatim, binding)

1. **Play = approve + start**; the onboarding conversation establishes what the
   focus is about and its scope.
2. **Onboarding = the seeded questions themselves** / the first few that
   establish basic understanding; the daily/weekly/monthly scripts improve from
   there.
3. **✓ = scaffold + seed, nothing asked now.**
4. **The first reply appends the aside** "I've started a **{label}** focus —
   tell me if the name or scope is off" **and asks at most ONE onboarding
   question the package deems most valuable** (person → relationship / living;
   otherwise scope); **after that, setup changes only when the USER signals**
   (never re-litigate).
5. **No platform model placement**: the platform only substitutes
   stage/label/type into the package's own prompt leaf and records the
   structured output.
6. **Play with no answers**: seeds still generate from the recommendation's own
   evidence (today's behaviour) — **the package must not require onboarding
   context.**

## Binding facts

As of `origin/main` `43635c9a`, `system/version.json` version **188**, released
2026-08-21.

**The precedent this PR copies, line for line.**

- `docs/pr-specs/question-candidate-placement-aside.md` (v188) — contract shape,
  the "exactly one additive output field" discipline, the two-layer validation
  split, the transcript-derived stage, the lint table, the golden list.
- `system/conversation_delivery.py:152` `TurnShape` (`:166`
  `placement_stage: str | None = None`), `:292` `_output_contract_block` (the
  `placement_line`/`placement_note` gating at `:329–341`), `:394`
  `parse_turn_output` (`:429` the `placement` key), `:439` `_parse_placement`
  (the structural layer that owns no roster and never raises).
- `system/question_candidate.py:364` `validate_placement` (closed layer),
  `:390` `placement_stage_for_session` (transcript-only derivation), `:518`
  `VALID_PLACEMENT_STAGES`, `:555` `lint_placement_reply` (seven pure gate
  classes sharing `conversation_lints.lint_turn`'s finding shape).
- `system/question_candidate_evals.py:32–65` (a SECOND, independent golden pair
  beside the frozen ADR-0018 one), `:86–212` (loaders, fixture validation,
  `score_placement_goldens`), `:489–503` (both pairs, one `check_gates` call).

**The child as it stands.**

- `interactions/focus_candidate/interaction.yaml` — `extends: conversation`,
  `extends.version: 1.0.0`, `modes: research`,
  `composition.leaf: prompt/turn-instructions.md|context/manifest.md`,
  `budget.turn_instructions: 1300`.
- `interactions/focus_candidate/prompt/turn-instructions.md` — today it declares
  the RESEARCH-mode output object (`reply/action/next_gap/evidence_spans/
  dimension_evidence/seed_questions/confirmation_span`). That declaration is
  what `parse_focus_candidate_output` (`focus_candidate.py:418`) parses on the
  standalone `focus-candidate-prompt` path.
- `interactions/focus_candidate/README.md:8` — "Play is read-only."
- `system/focus_candidate.py:290` `build_focus_candidate_prompt` composes
  identity/behavior/examples/turn-instructions and appends the untrusted block;
  `:340` `lint_focus_candidate_reply`; `:19` `FOCUS_DIMENSIONS`.
- `system/focus_candidate_evals.py` — four-part harness
  (`load_fixtures`/`validate_fixtures`/`score_predictions`/`check_gates`), gate
  prefix `research_gates.`, entry point
  `python3 system/lifehug.py focus-candidate-evals`.
- `interactions/focus_candidate/evals/lints.yaml` — `cap.reply_chars: 2200` +
  seven `research_gates.*` rows.

**The seed path.**

- `system/research_expand.py:660` `build_expansion_prompt(...)` — keyword-only,
  already carries five optional context inputs (`research_notes`,
  `decision_context`, `self_signals`, …); `:1115` `_run_expansion` builds it;
  `:1361` `build_parser`; `:186–216` `INTERVIEW_BANKS` (keys `parent`,
  `grandparent`, `spouse`, `child`, `sibling`, `mentor`, `cofounder`, `friend`,
  `remembering`) and `:218` `build_interview_pack`.
- `system/roadmap.py:325` `_USER_FIELDS` (including `living` and `relationship`
  with the comment that names their meaning), `:459` `_generate_and_promote`,
  `:495` `focus_new`, `:589` the `set` subparser, `:689` its handler, `:605`
  the `new` subparser's `--type` choices (the roadmap type authority, inline).
- `system/lifehug.py:879` `cmd_focus_set`, `:898` `cmd_focus_new`, `:1449`
  `cmd_research_expand`, `:2157` / `:2403` / `:2424` their parsers.
- `system/recommend_focuses.py:879` `approve_recommendation` — `objective =
  reason[:120]`. **Unchanged by this PR (ruling 6).**

**Handbook / manifest discipline.**

- `tests/test_handbook_parity.py` `EmbedParityTests` — `docs/handbook/
  interactions/focus-candidate.md` embeds `interactions/focus_candidate/prompt/
  behavior.md` byte-for-byte.
- `tests/test_focus_candidate.py:208` and `tests/test_entity_candidate.py:208`
  digest `interactions/conversation/` and `interactions/question_candidate/`
  only — this PR touches neither, so those digests do not move.
- `system/version.json` `framework_files` ships every
  `interactions/focus_candidate/**` file; new goldens must be added there in
  the same bump.

## Scope

**In:** the child README/prompt correction to the ADR-0020 model; the
`focus_setup` turn-output field (structural parse + closed validation); the
`opening_question` and `focus_stage_for_session` helpers; six
`focus_setup_gates.*` lints; seven onboarding goldens wired into
`focus-candidate-evals`; `research-expand --context-file` and its threading
through `focus_new` / `_generate_and_promote`; `focus-set --label/--type/
--relationship/--living|--not-living`; the ADR 0018 + ADR 0021 amendments; the
handbook embed refresh; the version bump.

**Out (deliberate, named):**

- Retiring `parse_focus_candidate_output`, `validate_focus_candidate_decision`,
  `resolve_focus_candidate_completion`, the `action`/`next_gap` machinery, the
  research goldens, or the `research_gates.*` rows. The standalone
  `focus-candidate-prompt` / `focus-candidate-complete` CLI path still uses
  every one of them; they are marked **superseded for the Play path** and left
  in place. Deleting them is a separate PR, if ever.
- Re-seeding an existing focus when its `type` changes after seeding. The seed
  job records the change; regeneration is a follow-up issue.
- Re-iding a focus on a `label` change. `focus-set --label` changes the display
  label; the focus id and its category letter are stable identifiers, exactly
  as a promoted question's id is (`lifehug_core.py:691`). Same reasoning as the
  `question-move` deferral in v188's contract: a half-applied rename is worse
  than a deferred one.
- Any change to ordinary Conversation prompt bytes, to `approve_recommendation`,
  to the registry, or to the composition policy.

## Design

### A. The child stops being read-only research and becomes onboarding

**A1. `interactions/focus_candidate/README.md`.** "Play is read-only.
Confirmed completion delegates to the canonical candidate-research source
authority and leaves the recommendation pending. Only the existing
approval/autopilot path creates a Focus." is false under platform ADR 0020 +
review-loop/54. Replaced with: Play approves and scaffolds the focus in the
background; this Interaction is the onboarding conversation that establishes
what the focus is about, and the seeded questions come out of it. The
research-mode assets (`action`/`next_gap`/`dimension_evidence`/completion) stay
for the standalone `focus-candidate-prompt` CLI path and are marked superseded
for the Play path — not deleted.

**A2. `prompt/turn-instructions.md` becomes the stage-keyed leaf.** Exactly the
shape `question_candidate`'s placement leaf took at v188: the child no longer
declares its own output object; it declares the PARENT's contract plus one
optional field, and the rules for this turn. Placeholders `{focus_stage}`
(∈ `establish|settled`), `{focus_label}`, `{focus_type}` — the platform REPLAYs
the leaf verbatim via `interaction_registry.compose_interaction_asset` and
substitutes them (ruling 5: substitution is the platform's ONLY job here).

- `establish` — receive the answer as any Conversation turn would, then append
  ONE sentence: *"I've started a **{focus_label}** focus — tell me if the name
  or scope is off."* Not a question, said once, never again. Then ask AT MOST
  ONE onboarding question: for a person, how they are related to the author or
  whether they are still living; for anything else, what the focus should cover
  and leave out. Ask nothing when the answer already said.
- `settled` — say nothing about name, type, or scope. Only when the USER's own
  message changes one does the turn receive it in a clause and carry it in
  `focus_setup`.

**A3. The research output contract moves from the leaf to the runtime.** The
research JSON object the leaf used to declare cannot stay in a leaf the platform
appends to an ordinary Conversation prompt — two competing "return exactly one
JSON object with exactly these keys" contracts is a defect, not a composition.
It moves into `focus_candidate._research_output_contract_block()` and is
appended by `build_focus_candidate_prompt`, byte-for-byte what the leaf carried.

This is the parent's own pattern, not an invention: `conversation_delivery.
_output_contract_block` (`:292`) exists precisely because "the merged Wave-1
builder … does not (and should not) pin a machine-readable output shape" — the
ENGINE appends structure, the leaf holds behavior. A required test proves the
standalone prompt still contains every research key it contained at v188, so
the `focus-candidate-prompt` path is not regressed (unlike v188, which left
`question_candidate`'s standalone path prompt-less by design).

**A4. `opening_question(entity, focus_type)`** — a pure helper in
`system/focus_candidate.py` returning the first thing the user sees when Play
opens the tab (the platform's `question_text`; review-loop/54 §A.2). One short,
natural line, type-aware, no machinery:

| type | line |
|---|---|
| `person`, `relationship` | `Tell me about {entity} — who are they to you?` |
| `place` | `Tell me about {entity} — what happened there that makes it matter?` |
| `period` | `Tell me about {entity} — what was that stretch of your life like?` |
| `event` | `Tell me about {entity} — what happened, and what has it meant since?` |
| `project`, `lifes_work` | `Tell me about {entity} — what are you making, and what is it for?` |
| `self` | `Tell me about {entity} — what do you want to understand about yourself here?` |
| anything else (`theme`, unknown) | `Tell me about {entity} — what should this focus be about?` |

Unknown/blank type falls to the theme line; a blank entity raises, because an
opener with no subject is a caller bug, not a degradation.

### B. The `focus_setup` field — schema and where it is validated

Exactly one new key in the structured turn output, additive and optional:

```json
"focus_setup": {"objective": "his working years at the mill", "relationship": "parent", "living": false}
```

`null` or absent on every ordinary turn, and on every onboarding turn where the
user said nothing about the focus's setup. All five inner keys are optional; a
turn carries only what the user actually supplied.

Two validation layers, the same split as `placement`:

1. **Structural** — `system/conversation_delivery.py` `_parse_focus_setup`,
   called from `parse_turn_output`. Accept only an object whose keys are a
   subset of `{objective, type, relationship, living, label}`. Each string value
   is `.strip()`ed and must be non-empty and ≤ 500 characters; `living` must be
   a real `bool` (never `0`/`1`/`"yes"`). Individually invalid values are
   dropped; an object that is not a dict, carries an unknown key, or ends up
   empty → `None`. Never raises — a malformed `focus_setup` degrades to "no
   setup change", exactly as `held_question_id` and `placement` degrade.
   `conversation_delivery` owns no vocabulary and performs no membership check.
2. **Closed** — `system/focus_candidate.py`:

   ```python
   def validate_focus_setup(value: object) -> dict | None:
       """Return the subset of {objective,type,relationship,living,label}
       that is valid against the package's closed vocabularies, or None."""
   ```

   - `type` ∈ `roadmap.FOCUS_TYPES` — `person, place, period, project, theme,
     event, lifes_work, self, relationship` — exact match, no case-fold, no
     fuzzy, no derivation from prose. **Imported from `system/roadmap.py`**,
     which is promoted to the single authority for that list and uses the same
     constant for its own `--type` argparse choices (recurring-defect doctrine:
     the list is currently duplicated inline in `roadmap.py` and `lifehug.py`).
   - `relationship` ∈ `FOCUS_RELATIONSHIPS` — `parent, grandparent, child,
     sibling, spouse, partner, friend, colleague, mentor, other`.
   - `living` — `bool` only.
   - `objective` — trimmed, ≤ 200 characters (matching the platform's
     `_FREE_TEXT` cap in `review_pin.py` and today's `reason[:120]` being well
     inside it).
   - `label` — trimmed, ≤ 80 characters (matching `_LABEL`).

   An invalid value drops that key; no valid key remaining → `None`.

**`Turn.focus_setup`** is recorded additively by the caller (the platform's
`Turn` model; there is no OSS turn record to change), guarded by that side's
stored-shape test.

### C. The stage needs no new state

It is already in the transcript, exactly as `placement_stage` is
(`question_candidate.py:390`). The aside and the one onboarding question both
live on the FIRST assistant reply, so "have we onboarded?" is exactly "does this
session have an assistant turn?":

```python
def focus_stage_for_session(session: dict) -> str:
    return "settled" if any(t.get("role") == "lifehug" for t in session["turns"]) else "establish"
```

No new session field, no ledger, no lifecycle status, no model purpose.

### D. Lints

New gate class `focus_setup_gates.*` in
`interactions/focus_candidate/evals/lints.yaml`, produced by a new pure function
`focus_candidate.lint_focus_setup_reply(text, *, stage, user_signaled=False)`
whose findings share `conversation_lints.lint_turn`'s shape so a caller can
merge them with `lint_focus_candidate_reply`'s output uniformly. An unrecognized
stage is treated as `settled` (fail toward the strictest rule).

| lint id | rule | applies on |
|---|---|---|
| `focus_setup.aside_single_sentence` | the aside appears exactly once and is exactly one sentence | `establish` |
| `focus_setup.aside_not_a_question` | the aside sentence contains no `?` | `establish` |
| `focus_setup.aside_never_repeated` | no aside sentence at all | `settled` |
| `focus_setup.one_setup_question` | the reply contains at most one `?` | every turn |
| `focus_setup.settled_silence` | no name/type/scope talk unless `user_signaled` | `settled` |
| `focus_setup.no_mechanism_talk` | no "I'll create", "scaffolding", "setting up", "adding a category", "seeding questions", "the system will" | every turn |

The aside's invariant anchor — what every aside lint locates — is
`started (a|an|the) … focus` (ruling 4's wording; the model varies the
connective tissue, never the move).

A `focus_setup` lint failure is a lint failure exactly as an inherited
Conversation lint failure is, and an aside is never worth losing a reply over:
the documented degradation is one retry WITHOUT the aside before degrading
further (the same recipe v188 prescribes for placement).

### E. Seed generation finally hears the conversation

**E1. `research-expand --context-file <PATH>`** (chosen spelling; `--context-stdin`
rejected because the platform already materializes mutation attachments as files
outside the vault tree — `review_pin.SEED_ATTACHMENT_NAME` is the precedent, and
a path composes with `--from-response` without fighting for stdin, which
`--from-response`'s sibling flags already avoid).

The file holds ONE JSON object, every key optional:

```json
{"objective": "his working years at the mill", "type": "person",
 "relationship": "parent", "living": false, "label": "Dad",
 "first_answer": "He ran the second shift for thirty-one years …"}
```

Normalized by `focus_candidate.normalize_onboarding_context` (built on
`validate_focus_setup`; `first_answer` trimmed and capped at 1200 characters).
A missing file or unparseable JSON is a hard error (`return 1`) — the caller
asked for context explicitly. An object that normalizes to nothing is not an
error: generation proceeds exactly as it does today (**ruling 6**).

**E2. `build_expansion_prompt(..., onboarding_context: dict | None = None)`.**
`None` (the default) produces a byte-identical prompt to v188 — a required test.
When present it emits, immediately after `## YOUR TASK`, so it frames the whole
generation:

```
## FOCUS ONBOARDING CONTEXT
The author just started this focus in conversation. This is what they said it
is for — ground every question in it, and prefer it over generic arc coverage
wherever the two pull apart.
  Objective: his working years at the mill
  Focus name: Dad
  Relationship to the author: parent
  Living: no — write questions that REMEMBER them; never write a question that
    asks them something directly.
Their first words about this focus, verbatim:
  "He ran the second shift for thirty-one years …"
```

and, for a `person`/`relationship` topic with a `relationship` value, the
matching `INTERVIEW_BANKS` entry as `## INTERVIEW BANK FOR THIS RELATIONSHIP`.
Bank selection: `remembering` whenever `living is False` (the bank that exists
for exactly that case — `_USER_FIELDS`' own comment: "living: false on a person
Focus = deceased … you can't ask"), else the relationship's own bank, else
`friend`. `partner`→`spouse`, `colleague`→`cofounder`, `other`→`friend` are the
only mappings; `parent/grandparent/child/sibling/spouse/mentor/friend` are
banks already.

**E3. Threading.** `roadmap._generate_and_promote(..., context_path=None)` adds
`--context-file <path>` to its `research_expand.py` argv when given;
`roadmap.focus_new(..., context_path=None)` passes it through; `roadmap.py new`
and `lifehug.py focus-new` gain `--context-file`; `lifehug.py research-expand`
gains the passthrough. Every default is `None`, so every existing call site is
byte-identical.

**E4. `focus-set` gains the fields the onboarding conversation can change** —
`--label`, `--type`, `--relationship`, `--living/--not-living` — in both
`roadmap.py`'s `set` subcommand and `lifehug.py`'s wrapper. `--label` sets
`focus["label"]` and refreshes `wiki_node`; it does not re-id (Scope, "Out").
All four are `_USER_FIELDS` already, so they survive `derive_roadmap`
re-derivation with no other change.

**E5. `approve_recommendation` is untouched** (ruling 6). Play with no answers
seeds from the recommendation's own evidence exactly as it does today.

## Required tests

`python3 -m unittest discover -s tests` (and `python3 -m pytest -q`) green.

**`tests/test_conversation_delivery.py`**
- `test_output_contract_block_byte_identical_without_focus_stage` — a `TurnShape`
  with no `focus_stage` produces the exact pre-#183 appendix, byte for byte.
- `test_focus_setup_line_and_note_present_when_staged` — both stages.
- `test_parse_turn_output_focus_setup_absent_is_none`.
- `test_parse_turn_output_focus_setup_malformed_degrades` — non-dict, unknown
  key, empty object, blank string value, 501-char value, `living: 1` → `None`
  or the key dropped, never an error.
- `test_parse_turn_output_focus_setup_partial_object` — a lone `{"living": false}`
  survives.

**`tests/test_focus_candidate.py`**
- `test_opening_question_is_type_aware_and_one_line` — every roadmap type, plus
  the unknown-type fallback and the blank-entity raise.
- `test_validate_focus_setup_closed_vocabularies` — valid full object round-trips.
- `test_validate_focus_setup_rejects_unknown_type_and_relationship` — including
  case-folded and fuzzy forms.
- `test_validate_focus_setup_caps_and_trims`.
- `test_focus_stage_for_session_derived_from_transcript`.
- `test_focus_setup_lints_*` — one per §D row, passing and failing reply each.
- `test_research_output_contract_survives_the_leaf_move` — the standalone
  `build_focus_candidate_prompt` still contains every research output key.
- `test_focus_types_match_roadmap_argparse_choices` — the recurring-defect
  parity test: the constant and the CLI's choices are the same list.

**`tests/test_focus_candidate_evals.py`** — the seven goldens load, validate,
score, and gate; a deliberately-bad prediction fails its own class only.

**`tests/test_research_expand_context.py`** (new)
- `test_prompt_byte_identical_without_onboarding_context`.
- `test_context_block_renders_objective_first_answer_and_living`.
- `test_person_with_relationship_gets_its_interview_bank`, and
  `living=False` gets `remembering`.
- `test_normalize_onboarding_context_drops_invalid_and_caps_first_answer`.
- `test_context_file_missing_or_unparseable_is_an_error`.
- `test_focus_new_threads_context_path_into_research_expand_argv` (spy on
  `subprocess.run`).

**Goldens** — `interactions/focus_candidate/evals/goldens/onboarding_fixtures.json`
+ `onboarding_sample_predictions.json`:

1. `onboarding-establish-aside-and-one-question` — aside once, then one question.
2. `onboarding-establish-person-asks-relationship` — a person focus; the single
   question asks how they're related.
3. `onboarding-establish-answer-already-told-asks-nothing` — the opener already
   named the scope; the reply carries the aside and NO question, and
   `focus_setup` carries the objective.
4. `onboarding-settled-silent` — an ordinary later turn: no setup talk, null.
5. `onboarding-settled-user-renames-emits-setup` — "call it Dad, and it's really
   about his work years" → `{"label": "Dad", "objective": "…"}`, one-clause
   receipt, no confirmation question, no mechanism talk.
6. `onboarding-settled-unprompted-null` — a long, setup-silent turn stays null.
   (The pin for ruling 4's "never re-litigate".)
7. `onboarding-unknown-relationship-rejected` — a proposal naming
   `"grandmother-in-law"` normalizes to no relationship without failing the turn.

**Harness** — `python3 system/lifehug.py focus-candidate-evals` passes with the
new pair scored into `focus_setup_gates.*` beside the existing
`research_gates.*`, one `check_gates` call, no scorer-checking change; and
`python3 system/lifehug.py question-candidate-evals` is untouched and passes.

## Version bump

`system/version.json`: **188 → 189**, `released` set to the merge date, a full
changelog paragraph (this changes what the user sees), and the two new golden
files added to `framework_files` in the same bump.

## ADR amendments

**`docs/adr/0021-focus-candidate-interaction.md`** — Status `proposed` →
`amended 2026-08-22 by docs/pr-specs/focus-onboarding-context.md`.

| Location in 0021 | Change |
|---|---|
| Decision, "It does not own approval or Git writes." | Unchanged as to the MODEL, but the surrounding premise moves: the platform approves and scaffolds at Play, in a background job; this Interaction is the onboarding conversation that follows, not research toward a later approval. |
| Consequences, "Play/start is read-only." | **Reversed.** Play is approval + start (platform ADR 0020, review-loop/54). The model still writes nothing and claims nothing; the *platform* has already scaffolded. |
| Consequences, "Platform Play may deep-link into this Interaction after pinning v184, but must resolve the anchor server-side and must not approve on entry/completion." | Superseded: Play approves on entry by design; the platform's only model-facing job is substituting `{focus_stage}`/`{focus_label}`/`{focus_type}` into the leaf and recording `focus_setup`. |
| Decision, the eight-dimension research rubric and completion delegation | **Superseded for the Play path, retained for the standalone CLI path.** `focus-candidate-prompt` / `focus-candidate-complete` and their evals are unchanged. |

**`docs/adr/0018-candidate-placement.md`** — one amendment row: the additive-
field discipline the 2026-08-21 amendment established for `placement` now has a
second instance, `focus_setup`, with the same two-layer split and the same
"absent or malformed degrades, never errors" rule. No decision in 0018 changes.

**No new ADR.** The decision that made this necessary is platform ADR 0020 +
review-loop/54; this contract records behavior changes inside two existing
decisions' scope.

## Platform twin

Everything the platform reads from the package, by exact name:

| What | Where |
|---|---|
| The tab's framing line | `focus_candidate.opening_question(entity, focus_type) -> str` |
| The stage | `focus_candidate.focus_stage_for_session(session) -> "establish" \| "settled"` |
| Closed validation of the turn's field | `focus_candidate.validate_focus_setup(value) -> dict \| None` |
| The lints | `focus_candidate.lint_focus_setup_reply(text, *, stage, user_signaled=False) -> list[dict]` |
| The prompt leaf to REPLAY verbatim | `interactions/focus_candidate/prompt/turn-instructions.md`, via `interaction_registry.compose_interaction_asset("focus_candidate", "prompt/turn-instructions.md")`, substituting `{focus_stage}`, `{focus_label}`, `{focus_type}` |
| Structural parse of the turn output | `conversation_delivery.parse_turn_output(raw)["focus_setup"]`, enabled by `TurnShape(focus_stage=…)` |
| The seed context flag | `research-expand --context-file <PATH>`, JSON `{objective?, type?, relationship?, living?, label?, first_answer?}` |
| Closed vocabularies | `roadmap.FOCUS_TYPES`, `focus_candidate.FOCUS_RELATIONSHIPS` |
| Setup changes applied to a scaffolded focus | `focus-set <id> [--label L] [--type T] [--relationship R] [--living\|--not-living]` |

The `:seed` program's context precedence (review-loop/54 §D) is entirely
platform-side: newest non-null `Turn.focus_setup.objective` → the user's first
turn text → `reason[:120]`. The package neither knows nor cares which one it
receives; it only requires that the file, when supplied, parses.

## Acceptance checklist

- [ ] Exactly one new turn-output field exists (`focus_setup`); no new session
      field, lifecycle status, model purpose, or state machine in the diff.
- [ ] `_output_contract_block` is byte-identical when `focus_stage` is None.
- [ ] `build_expansion_prompt` is byte-identical when `onboarding_context` is
      None.
- [ ] A malformed or absent `focus_setup` never errors a turn.
- [ ] The aside appears on the first reply, is one sentence, is not a question,
      and never appears again — goldens 1, 4 and 6.
- [ ] At most one onboarding question, and none when the answer already said —
      goldens 1, 2, 3.
- [ ] A user-signaled change emits `focus_setup`; nothing else ever does —
      goldens 5 and 6.
- [ ] Seeds generate from the recommendation's evidence with no context file
      (ruling 6) — every existing call site unchanged by default.
- [ ] `focus-candidate-evals` and `question-candidate-evals` both pass.
- [ ] CI green (`test` on 3.11/3.14, `framework-manifest`, `version-bump`);
      handbook embed parity green.
- [ ] `system/version.json` at 189 with the two new goldens in
      `framework_files`.
- [ ] ADR 0021 amended per the table; ADR 0018 gains the second-instance row;
      the child README's "Play is read-only" corrected.

## Owner closeout

**Look.** The transcript the goldens replay (no provider required):

- *Screen 1*: `Tell me about Dad — who are they to you?` and nothing else.
- *Turn 1*: the person answers about the mill → the reply receives it, then:
  "I've started a **Dad** focus — tell me if the name or scope is off." Then one
  question: "Is he your father, or someone you think of that way?"
- *Turn 2*: an ordinary exchange. Nothing about the focus's name or scope.
- *Turn 3*: "actually just call it Dad, and it's really about his work years" →
  a one-clause receipt, no confirmation question. Field: `{"label": "Dad",
  "objective": "his working years at the mill"}`.
- Then the seed prompt for that focus, printed with `--context-file`: the
  objective and his verbatim first words at the top, and — because he is no
  longer living — the `remembering` interview bank instead of the `parent` one.

**Judge.**

1. **The aside wording.** "I've started a **{label}** focus — tell me if the
   name or scope is off." Yes = this exact sentence ships as the prompt's
   literal instruction and the lints pin its shape (one sentence, not a
   question, said once).
2. **One question, chosen by the package.** Yes = the package decides what to
   ask (person → relationship/living; otherwise scope), the platform never does
   (ruling 5), and asking nothing is a legitimate answer when the opener already
   told us.
3. **`--context-file` as the spelling.** Yes = the platform writes the
   onboarding context to a file outside the vault tree and passes the path,
   matching how it already ships `seed_response.json`.

**Done when.** Contract merged → implementation PR green on CI → v189 tagged on
merge → platform review-loop/56 pins v189 and review-loop/54 consumes the eight
names in the Platform twin table.

🤖 Generated with Claude Opus via Claude Code
