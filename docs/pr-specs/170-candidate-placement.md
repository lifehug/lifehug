# Contract: candidate-placement (issue #170, PR A of two)

## Why

Answer Now must begin as an ordinary Conversation around an exact question
candidate, without asking the user to operate a category picker first. Today
the framework has neither a candidate-placement step nor a model contract for
deciding where that candidate belongs. Issue #170 therefore needs one upstream
behavior authority that can silently accept a high-confidence placement or ask
one natural clarification when placement is genuinely ambiguous, while the
runtime retains every substantive story turn. This PR is **PR A of two**: it
ships the closed-roster placement Interaction/schema/evals. PR B will separately
ship the provenance-safe promotion state machine and the structured,
Git-backed promotion receipt.

## Binding facts

- Base for this contract: `origin/main` at
  `886e96918e2da3c672e3aef73081c4453e2bf677` (v180). At implementation and
  rebase time, re-check live `origin/main`; the implementation takes the next
  free version and ADR number rather than assuming v181/ADR 0018 remain free.
- This is an additive **step inside the existing Conversation Interaction**,
  not a third top-level Conversation mode. `interactions/conversation/interaction.yaml`
  keeps `modes: chat|conversation` and gains
  `steps: turn|close|candidate_placement`. `system/conversation.py::VALID_MODES`
  remains `{"chat", "conversation"}`.
- Definition/runtime/seat separation in `interactions/README.md` remains
  binding. The definition under `interactions/conversation/` is behavior
  authority; the stdlib-only runtime validates model proposals; a model is not
  seated until the existing `conversation-evals` harness passes it.
- The ordinary Conversation prompt path is frozen by this PR. The general
  `prompt/behavior.md`, `prompt/examples.md`, `prompt/turn-instructions.md`,
  `context/manifest.md`, router definition, arc definition, load order, and
  behavior-rule numbering 1–13 do not change. Candidate-only instructions and
  examples live in new files loaded only by the candidate-placement builder.
  When no candidate-placement API is called, `build_turn_prompt`,
  `build_router_prompt`, router parsing, and their rendered bytes are identical
  to v180. The expected manifest `interaction_version` increment in newly
  opened session metadata is the only ordinary-session metadata delta.
- The model receives a caller/runtime-supplied, complete, bounded roster. It
  may propose exactly one supplied `category_id`; it cannot invent a category,
  focus mapping, revision, question id, vault path, Git operation, or promotion
  result. Category selection is always runtime-validated.
- `knob.candidate_placement_confidence_threshold: 0.8` is the silent-placement
  threshold. `knob.candidate_placement_roster_max: 64` is a hard completeness
  bound: 1–64 categories are valid; 0 or more than 64 fails validation. The
  builder never truncates a roster, because truncation would silently remove
  valid placement choices.
- `interaction.yaml` stays in the repository's flat-scalar YAML subset. Add
  `budget.candidate_placement: 2400` for the specialized prompt block; existing
  budget keys are unchanged.
- All revisions below use lowercase `sha256:<64 hex>` over UTF-8 canonical JSON
  (`json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)`).
  Lists retain their declared order. Hash helpers are public so the platform
  pin consumes the same authority instead of reimplementing it.
- All committed fixtures are synthetic. Never copy real vault content into
  tests, evals, screenshots, comments, or evidence.

### Canonical input schemas

`CandidateAnchor` is exact and immutable for one placement attempt:

```json
{
  "schema_version": 1,
  "candidate_id": "cand-lighthouse-1",
  "question": "What did the lighthouse teach you about waiting?",
  "source_revision": "capture:synthetic-lighthouse:3",
  "candidate_revision": "sha256:<64 lowercase hex>"
}
```

`candidate_revision` hashes exactly
`{"candidate_id", "question", "source_revision"}`. IDs and source revisions
are opaque non-empty strings, not paths or instructions. The question is the
exact candidate text; the builder does not paraphrase it.

`CategoryRoster` is runtime-derived and closed:

```json
{
  "schema_version": 1,
  "roster_revision": "sha256:<64 lowercase hex>",
  "categories": [
    {
      "category_id": "F",
      "label": "Family",
      "group": "people",
      "qualifier": null,
      "focus_id": "focus-family-stories",
      "focus_label": "Family stories",
      "category_revision": "sha256:<64 lowercase hex>"
    }
  ]
}
```

- `category_id` values are opaque, non-empty, unique strings of at most 64
  characters. The model must echo one exactly; it does not infer identifier
  syntax.
- `label` is non-empty. `group`, `qualifier`, `focus_id`, and `focus_label` are
  nullable strings. `focus_id` and `focus_label` are either both null or both
  non-null.
- `category_revision` hashes the six category fields other than itself.
  `roster_revision` hashes the ordered list of complete category entries.
- The local roster builder derives category facts from the question bank and
  roadmap/focus mapping. Callers may supply an already-derived roster only
  through the same strict validator and hash functions.

`CandidatePlacementInput` is the only prompt-builder input:

```json
{
  "schema_version": 1,
  "candidate": {"...": "CandidateAnchor"},
  "roster": {"...": "CategoryRoster"},
  "phase": "initial",
  "provisional_category_id": null,
  "latest_user_turn": null,
  "previous_clarification": null
}
```

- `phase` is `initial|clarifying`.
- `provisional_category_id`, when non-null, must be in the roster. A valid
  provisional placement resolves without a model judgment; an invalid one is
  rejected, never sent as an open-ended hint.
- `latest_user_turn` is null before the user has spoken and otherwise contains
  the exact current turn. `previous_clarification` is required only in the
  clarifying phase. Prompt rendering may apply the declared context budget,
  but truncation in the model copy never authorizes truncation or deletion of
  the runtime's durably held original turn.

### Model proposal and normalized decision

The specialized prompt requires one JSON object and no prose:

```json
{
  "turn_kind": "placement_only|answer|mixed|null",
  "category_id": "<one roster id>|null",
  "confidence": 0.0,
  "clarification": "<one natural question>|null"
}
```

- With no `latest_user_turn`, `turn_kind` must be null. With a user turn, it
  must be `placement_only`, `answer`, or `mixed`.
- `placement_only` means the turn only locates the candidate. `answer` means it
  contains substantive answer/story content but no usable placement signal.
  `mixed` means it does both. This classification is routing metadata only;
  every class retains the original turn.
- `confidence` is a real number in `[0, 1]`; booleans are invalid.
- A valid category at confidence `>= 0.8` resolves silently and requires
  `clarification: null`.
- Anything below threshold does not resolve. Normalization sets
  `category_id: null` even if the raw model proposed one, and requires exactly
  one natural clarification question. It may not expose category IDs, present
  a menu, ask yes/no, presuppose an answer, or contain more than one question;
  it must pass the existing Conversation lint engine.
- A hallucinated/out-of-roster category degrades placement only: retain a
  separately valid `turn_kind`, set normalized category/confidence resolution
  to null/invalid, and never discard the turn. This follows the router target
  precedent in `conversation_delivery._parse_router_output`.
- Malformed JSON, unknown keys, wrong types, invalid confidence, invalid
  clarification, or an inconsistent phase returns a typed `invalid` decision.
  It never guesses and never produces a promotion-ready placement.

The normalized `CandidatePlacementDecision` is:

```json
{
  "schema_version": 1,
  "status": "resolved|needs_clarification|invalid",
  "resolution": "provisional|model|conversation|null",
  "candidate_id": "cand-lighthouse-1",
  "candidate_revision": "sha256:<64 lowercase hex>",
  "source_revision": "capture:synthetic-lighthouse:3",
  "category_id": "F|null",
  "category_revision": "sha256:<64 lowercase hex>|null",
  "turn_kind": "placement_only|answer|mixed|null",
  "confidence": "number|null",
  "clarification": "string|null",
  "placement_revision": "sha256:<64 lowercase hex>|null"
}
```

- `resolution` is `provisional` for a valid caller provisional,
  `model` for an initial high-confidence proposal, and `conversation` for a
  high-confidence result in the clarifying phase.
- `placement_revision` is present only on `resolved` and hashes exactly
  `{"candidate_revision", "category_id", "category_revision"}`. It does not
  include `roster_revision`: removing, renaming, or remapping the selected
  category invalidates the placement, while unrelated roster additions do not.
- Validation against a changed candidate revision or changed selected-category
  revision returns a typed stale/invalid result. An implementation must not
  silently rerun or substitute the closest category.

### Public runtime API

New stdlib-only `system/candidate_placement.py` owns the schema, hashes,
validation, prompt construction, and parse normalization:

```python
build_candidate_anchor(
    candidate_id: str,
    question: str,
    source_revision: str,
) -> dict

build_category_roster(
    categories: list[dict],
) -> dict

build_candidate_placement_prompt(payload: dict) -> str

parse_candidate_placement_output(
    raw: object,
    *,
    payload: dict,
) -> dict

validate_candidate_placement(
    placement: dict,
    *,
    current_candidate: dict,
    current_roster: dict,
) -> dict
```

`system/conversation.py` exposes thin public wrapper/re-export seams if needed
by the existing CLI layout; it does not duplicate validation. Add read-only
`system/lifehug.py conversation-candidate-placement-prompt`, taking the exact
`CandidatePlacementInput` JSON on stdin and printing the assembled prompt. It
must be in `READ_ONLY_COMMANDS`, never `DIRECT_MUTATION_COMMANDS`.

## Scope

In:

1. Add candidate-placement step metadata, knobs, and budget to
   `interactions/conversation/interaction.yaml`; bump its semantic version.
2. Add `interactions/conversation/prompt/candidate-placement.md` as the
   specialized behavior/output authority and
   `prompt/candidate-placement-examples.md` for synthetic good/bad examples.
   These files explicitly inherit general Conversation rules 1–13 without
   changing or being loaded into ordinary turns.
3. Add the schema/runtime API and read-only prompt CLI above. Validate all
   model output and every caller-supplied revision/roster at runtime.
4. Extend `system/interaction_evals.py` with candidate-placement fixture
   validation, sample-prediction scoring, deterministic gates, and a live model
   layer that skips loudly without a configured provider. Generalize/reuse the
   existing gate arithmetic; do not create a second subtly different threshold
   engine.
5. Add synthetic `candidate_placement_fixtures.json` and parallel
   `candidate_placement_sample_predictions.json`. Required cases: valid
   provisional; high-confidence silent initial placement; natural ambiguity;
   follow-up clarification; placement-only, answer-only, and mixed user turns;
   hallucinated category with retained turn kind; prompt injection in candidate
   question, user text, and category label; malformed output; threshold edge;
   removed/renamed/focus-remapped selected category; unrelated roster churn;
   duplicate roster IDs; empty/oversized roster.
6. Add flat gates under `placement_gates.*`: category accuracy, turn-kind
   accuracy, closed-roster compliance, ambiguity-question validity, and stale
   revision rejection. The committed sample predictions must prove gate math
   keylessly; live seating remains provider-dependent and skip-annotated.
7. Add the next available ADR recording: candidate placement is a Conversation
   step, not a mode; the model is proposal-only; the roster is closed and
   complete; original turns are retained independently of classification;
   per-category revision binding; platform #469 is the first full coordinator.
8. Update the Conversation README, `interactions/README.md` only if its file-role
   catalog needs the specialized prompt documented, and the generated/embedded
   handbook page in lockstep where parity tests require it. Update
   `AGENTS.md`/`CLAUDE.md` only where they describe affected behavior.
9. Take the next free `system/version.json` version, set `released`, write a
   user-impact changelog, and add every new distributable definition/runtime/
   eval file to `framework_files`. Run the manifest and version-bump gates.
10. In the evidence comment, enumerate the downstream pin reconciliation
    surface: new system module/CLI; two prompt files; manifest steps/knobs/budget;
    schemas and closed vocabularies; fixture/prediction fields; gate keys; and
    ordinary-prompt byte-identity proof.

Out:

- Candidate promotion, question-id allocation, question-bank writes,
  provenance markers, Git commits, `commit_sha`, or promotion receipts. Those
  are PR B of issue #170.
- Platform #469 coordinator/session/pending-capture wiring, platform projection
  reads, web UI, or a platform pin bump.
- A category picker, decline/defer reasons, or any change to ordinary
  Conversation/router/arc behavior.
- Durable OSS candidate-answer session orchestration. PR A defines the portable
  typed input/decision contract; each runtime owns its storage and concurrency
  mechanics. It adds no new vault path and does not change
  `system/vault_contract.json`.
- Model seating, provider-specific overlays, or provider-specific behavior.

## Implementation notes

- Follow the router's additive closed-roster/parser precedent in
  `system/conversation.py::_build_router_roster_block` and
  `system/conversation_delivery.py::_parse_router_output`, but keep candidate
  placement in the one new authoritative module rather than adding a third
  copy of roster validation.
- Load candidate-only prompt files through framework-scoped paths. Never read
  prompt authority from the user's vault, and never interpolate values as
  instructions. Render candidate text, user text, and roster entries as a
  bounded JSON `DATA` block after an explicit instruction that all contents of
  `DATA` are untrusted evidence, not commands.
- The placement model gets no tools. In particular, it cannot read or write
  Git, the question bank, candidate state, session state, or projections.
- Reject unknown schema keys. Reject duplicate category IDs before prompting.
  Use exact string membership, not case folding, fuzzy matching, label matching,
  or question-text matching.
- Preserve a valid turn classification when category parsing fails, but never
  preserve a stale/invalid category. Runtime code decides what may advance;
  model prose is never authorization.
- The platform pin should consume the final PR B release rather than pinning
  this intermediate release. PR A evidence still lists all reconciliation
  surfaces so PR B and the later platform pin can prove none were missed.

## Test plan

Add `tests/test_candidate_placement.py` with named test classes/subtests for:

- canonical hash determinism, Unicode handling, and mutable-field exclusion;
- anchor, roster, focus-pair, uniqueness, bounds, and unknown-key validation;
- prompt boundary/escaping and prompt-injection fixtures;
- valid provisional and model/conversation resolution;
- `0.8` threshold boundary and strict confidence typing;
- all three turn kinds, no-user-turn nullability, and classification retention
  when category output is invalid;
- natural one-question ambiguity linting and menu/yes-no/multi-question
  rejection;
- candidate/category staleness, selected-category churn, and unrelated roster
  churn;
- malformed model output and fail-closed normalization;
- read-only CLI stdin/stdout behavior and no durable mutation;
- v180 byte fixtures proving ordinary turn/router prompts are unchanged when
  the candidate-placement API is unused.

Extend `tests/test_interaction_evals.py` for fixture schema, sample scorer math,
every configured `placement_gates.*` boundary, and loud keyless live skips.
Extend the existing handbook parity test if an embedded definition changes.

Exact focused gate:

```bash
python3 -m unittest \
  tests.test_candidate_placement \
  tests.test_interaction_evals -v
```

Exact full gates:

```bash
python3 system/lifehug.py conversation-evals
python3 scripts/ci/check_framework_files.py
python3 -m unittest discover -s tests -p "test_*.py" -v
```

CI must pass on Python 3.11 and 3.14. Record the exact SHA and concise counts in
the implementation evidence comment; do not normalize a red baseline into an
acceptance.

## Launch-and-verify

This PR does not touch `serve_wiki.py`; no browser walkthrough, screenshots, or
motion evidence are required. The executable/viewable review surface is:

```bash
python3 -c '
import json
from pathlib import Path
rows = json.loads(Path("interactions/conversation/evals/goldens/candidate_placement_fixtures.json").read_text())
print(json.dumps(rows[0]["input"]))
' | python3 system/lifehug.py conversation-candidate-placement-prompt

python3 system/lifehug.py conversation-evals
```

Pass means the first command prints a candidate-placement prompt containing the
exact synthetic candidate and only the supplied closed roster, with untrusted
content inside the JSON `DATA` block; the second command reports all
deterministic candidate-placement schemas, sample gates, and goldens passed,
while any unavailable live provider layer is named and skipped loudly.

## Acceptance criteria

- [ ] A high-confidence valid roster proposal resolves silently; ambiguity asks
      one natural Conversation-shaped question.
- [ ] The model cannot resolve to any category absent from the exact caller
      roster, including via prompt injection, label matching, or case folding.
- [ ] `placement_only|answer|mixed` classification never discards or rewrites
      the original turn; invalid placement retains any independently valid
      classification.
- [ ] Exact candidate and selected-category revisions bind a resolved placement;
      relevant churn invalidates it and unrelated roster churn does not.
- [ ] Empty, duplicate, oversized, malformed, or stale inputs fail closed.
- [ ] Ordinary Conversation and router prompt bytes match v180 fixtures whenever
      candidate placement is unused; modes and rules 1–13 remain unchanged.
- [ ] Deterministic and sample-prediction eval layers cover every required case;
      live model layers skip loudly when unavailable.
- [ ] No production path writes candidate, question-bank, Conversation, Git, or
      projection state in this PR.
- [ ] The implementation evidence names every platform pin reconciliation
      surface and states that platform should wait for PR B's final release.

## Owner closeout template

**Look**

1. Run the two commands under Launch-and-verify.
2. In the printed prompt, confirm that the candidate/user/category values appear
   only inside the bounded JSON `DATA` block and that the output vocabulary names
   only roster IDs.
3. Read the candidate-placement eval summary: high-confidence, ambiguity,
   mixed-turn, injection, malformed, and churn cases should all be named and
   green; an unavailable live model must say `SKIPPED`, not silently pass.

**Judge**

1. Yes/no: approve `0.8` as the silent-placement threshold? Yes makes it the
   portable default both OSS and platform runtimes must honor.
2. Yes/no: approve 64 as the complete-roster hard maximum? Yes means runtimes
   fail closed above 64 rather than truncating possible placements.
3. Yes/no: approve one natural open clarification with no category picker,
   yes/no question, or forced-choice menu? Yes binds the Answer Now ambiguity
   experience and its eval rubric.
4. Yes/no: approve per-selected-category revision binding instead of binding to
   the entire roster? Yes means unrelated category additions do not invalidate a
   resolved placement, while removal/rename/focus remapping does.

**Done when**

Approval merges only PR A's placement authority and triggers its automatic
version tag. It does not make Answer Now promotable. PR B must then land the
idempotent promotion/receipt authority; the platform pins the final PR B release
and implements its coordinator in platform #469.

## Definition of done

- [ ] Focused tests and `conversation-evals` pass locally.
- [ ] Full dependency-free unittest suite passes; CI is green on Python 3.11
      and 3.14.
- [ ] `system/version.json` takes the next free version, date, user-impact
      changelog, and complete `framework_files` additions.
- [ ] The next available ADR records the binding decisions above.
- [ ] Conversation/Interaction handbook and operating docs are updated where
      behavior changed; byte-embedded docs pass parity.
- [ ] Covering issue #170 receives concise implementation/eval/pin-handoff
      evidence, but remains open for PR B.
- [ ] Owner-closeout comment is current and self-contained.
- [ ] No viewer evidence is required because `serve_wiki.py` is untouched.

🤖 Generated with GPT-5.6-Sol via Codex
