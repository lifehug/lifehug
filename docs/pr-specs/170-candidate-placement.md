# Contract: question-candidate interaction (issue #170, PR A of two)

## Why

Answer Now must remove the category modal between a question candidate and a
real conversation. Green **Promote** is the explicit direct-promotion action,
red **Decline** resolves the candidate without an answer, and **Play** opens
Home/Today in a new tab with the exact candidate id and question preloaded and
starts the substantive exchange immediately. Placement is an Interaction
responsibility, not setup the user must finish first: the model infers the
required category/focus association from the candidate and conversation and,
only when still necessary, asks naturally at an appropriate before/during/after
point. Before an answered candidate completes, its durable answer, placement,
and lifecycle outcome must all be resolved. Starting Play never promotes.

This is **PR A of two**. It ships the independently registered and auditable
Question Candidate Interaction, its generic Conversation-composition
mechanism, closed-roster schema/runtime, and eval authority. PR B separately
ships question-id allocation, idempotent promotion, provenance, Git commit,
and the structured promotion receipt.

## Binding facts

- The implementation base for this PR was `origin/main` at
  `886e96918e2da3c672e3aef73081c4453e2bf677` (v180). This PR takes v181 and
  ADR 0018. Rebase work must re-check live upstream without changing the
  architecture or silently reusing an occupied version/ADR number.
- “Build an interaction” means an independently registered package satisfying
  `interactions/README.md`. Question Candidate therefore lives at the
  canonical source path `interactions/question_candidate/`, uses the registry
  id `question_candidate`, and has its own README, manifest, prompt, context,
  router, overlays, evals, version, and role/seat surface. Source directories
  and ids use snake_case, matching `question_judgment` and `focus_curation`;
  user-facing names and handbook filenames use “Question Candidate” and
  `question-candidate`.
- Question Candidate **extends Conversation**. Conversation supplies general
  chat mechanics—identity/voice, response-before-ask, receipts, question
  craft, scope/deflection, closings, and other ordinary behavioral rules.
  Question Candidate supplies the exact candidate anchor, placement inference,
  before/during/after association timing, completion criteria, and lifecycle
  coordination. It is not a Conversation step, mode, alias, or pile of prompt
  fragments stored under `interactions/conversation/`.
- `interactions/registry.json` is the closed framework registry. Every
  Interaction package is listed exactly once. A package directory or manifest
  that is absent from the registry is not executable or seatable; a registry
  entry without a complete package fails the audit.
- `system/interaction_registry.py` is the stdlib-only registry/composition
  authority. It resolves a registered `extends` chain, rejects cycles and
  unregistered parents, verifies the child-declared parent version, and
  assembles declared assets deterministically. Composition policy is declared
  in the child's flat-scalar manifest, never selected ad hoc by a caller.
- Question Candidate's manifest declares `extends: conversation` and
  `extends.version: 1.0.0`. It appends parent then child for identity,
  behavior, examples, router, and deflection; it uses the child context recipe
  and child turn instructions as leaf authority. Provenance boundaries name
  every package and asset in assembled text. Duplicate, missing, overlapping,
  or unknown composition paths fail closed. Parent bytes are read directly at
  runtime; no copied Conversation prose is permitted in the child package.
- Ordinary Conversation is restored exactly to its v180 definition and
  behavior: manifest version 1.0.0, `modes: chat|conversation`, no candidate
  step/knobs/budget/prompt/eval assets, unchanged rules 1–13, and unchanged
  turn/router rendered bytes. Adding the generic registry does not cause an
  ordinary Conversation caller to compose or load Question Candidate.
- Question Candidate ships with no default concrete model. Its manifest names
  capability roles (`role.router`, `role.worker`, `role.planner`) and its own
  eval gates. A model passing Conversation does not automatically pass Question
  Candidate; seating requires the child harness, which includes inherited
  Conversation parity and candidate-specific gates.
- The model receives a caller-supplied exact candidate plus a **complete,
  closed, ordered** category roster. It may echo one exact roster id but cannot
  invent an id, focus mapping, revision, question id, path, write, promotion,
  or lifecycle transition. Roster size is 1–64; empty or larger rosters fail
  before prompting and are never truncated.
- Candidate/category/user strings are untrusted JSON data, not instructions.
  The model gets no tools. Runtime code rejects unknown keys, forged hashes,
  ambiguous types, duplicate ids, out-of-roster selections, prompt-injection
  attempts, and invalid lifecycle combinations.
- `knob.placement_confidence_threshold: 0.8` is the silent-placement threshold;
  `knob.category_roster_max: 64` is the completeness bound. Placement may be
  deferred while substantive conversation continues. If the model asks now,
  it asks exactly one natural, open, Conversation-shaped question embedded in
  the user-visible reply—not a modal, menu, id list, or yes/no presupposition.
- All revisions are lowercase `sha256:<64 hex>` over canonical UTF-8 JSON via
  `json.dumps(value, sort_keys=True, separators=(",", ":"),
  ensure_ascii=False)`. Ordered lists retain order. Exported hash helpers are
  the platform authority; downstream code must not recreate them.
- All fixtures are synthetic. Never access or reference a private user repo or
  copy real vault data into tests, prompts, logs, evidence, or screenshots.

### Registration and composition interfaces

`interactions/registry.json` has this exact top-level shape and these entries:

```json
{
  "schema_version": 1,
  "interactions": [
    {"id": "conversation", "package": "conversation"},
    {"id": "focus_curation", "package": "focus_curation"},
    {"id": "question_judgment", "package": "question_judgment"},
    {"id": "question_candidate", "package": "question_candidate"}
  ]
}
```

`system/interaction_registry.py` exposes:

```python
load_interaction_registry(*, framework_root: str | Path | None = None) -> dict
load_interaction_manifest(interaction_id: str, *, framework_root=None) -> dict
resolve_interaction_lineage(interaction_id: str, *, framework_root=None) -> tuple[str, ...]
compose_interaction_asset(interaction_id: str, relative_path: str, *, framework_root=None) -> str
audit_interaction_package(interaction_id: str, *, framework_root=None) -> list[str]
```

- `resolve_interaction_lineage("question_candidate")` is exactly
  `("conversation", "question_candidate")`; Conversation resolves only to
  itself. Each manifest's `interaction` must match the registered id.
- Child manifest keys `composition.append` and `composition.leaf` are
  pipe-delimited relative paths. The sets are non-empty, disjoint, reject
  absolute/parent-traversal paths, and may name only required package assets.
- `compose_interaction_asset` uses the declared policy. `append` emits each
  lineage asset in parent-to-child order with deterministic provenance markers;
  `leaf` emits only the child asset with its provenance marker. An undeclared
  asset is rejected. Text is UTF-8 and newline-normalized only at the
  provenance seam; source bytes are otherwise unchanged.
- The audit requires README, manifest, four prompt files, context manifest,
  four provider overlays, lints, rubrics, goldens README, and personas README;
  it also verifies every declared asset and exact parent version. Router files
  are required because this Interaction receives free-form answers.

### Canonical domain schemas

`CandidateAnchor` is immutable for one Question Candidate run:

```json
{
  "schema_version": 1,
  "candidate_id": "cand-lighthouse-1",
  "question": "What did the lighthouse teach you about waiting?",
  "source_revision": "capture:synthetic-lighthouse:3",
  "candidate_revision": "sha256:<64 lowercase hex>"
}
```

`candidate_revision` hashes exactly `candidate_id`, `question`, and
`source_revision`. These values are opaque data; the exact question is retained
and never paraphrased by the builder.

`CategoryRoster` remains ordered and closed:

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

- Category ids are unique opaque non-empty strings of at most 64 characters.
  Runtime selection uses exact membership—no case folding, fuzzy matching,
  label lookup, or closest-category fallback.
- `label` is non-empty. `group`, `qualifier`, `focus_id`, and `focus_label` are
  nullable; focus id/label are both null or both non-null.
- `category_revision` hashes the six source fields; `roster_revision` hashes
  the complete ordered category entries.

`QuestionCandidateInput` is the prompt/runtime input:

```json
{
  "schema_version": 1,
  "candidate": {"...": "CandidateAnchor"},
  "roster": {"...": "CategoryRoster"},
  "association_stage": "before_answer",
  "provisional_category_id": null,
  "latest_user_turn": null,
  "previous_placement_question": null,
  "answer_status": "none",
  "requested_outcome": "engage"
}
```

- `association_stage` is `before_answer|during_answer|after_answer`.
  Before/during/after records when this placement judgment occurs; it does not
  force a question at that time.
- `provisional_category_id`, when present, must be one exact roster id and
  resolves placement without a model guess.
- `latest_user_turn` is null before speech and otherwise the exact current
  turn. `previous_placement_question` is nullable conversational context. The
  runtime retains the original turn independently of any classification or
  prompt budget.
- `answer_status` is caller-attested `none|held|durable`. Only the coordinator
  that durably stores an answer may say `durable`; model output can never
  upgrade it.
- `requested_outcome` is `engage|decline|defer`. Play supplies `engage`.
  Decline/defer are explicit caller actions, not semantic guesses by the model.
  Direct Promote does not enter this Interaction.

### Model proposal and normalized decision

For an engaged turn the composed prompt requests one JSON object and no prose:

```json
{
  "reply": "<Conversation-shaped user-visible turn>|null",
  "turn_kind": "placement_only|answer|mixed|null",
  "placement_action": "resolved|ask_now|defer",
  "category_id": "<one roster id>|null",
  "confidence": 0.0,
  "placement_question": "<one natural question>|null"
}
```

- With no latest user turn, `reply` and `turn_kind` are null. Initial Play may
  silently resolve placement from candidate context or defer it, but may not
  block substantive answering behind an initial placement question.
- With a user turn, `reply` is a non-empty Conversation-shaped response and
  `turn_kind` is `placement_only|answer|mixed`. Classification is metadata;
  every class retains the exact original turn.
- `resolved` requires an exact roster id, confidence `>= 0.8`, and null
  placement question. `defer` has null category/question and lets the
  substantive exchange proceed. `ask_now` has null category, confidence below
  threshold, and exactly one open placement question. That same question must
  appear verbatim as the sole question in `reply`, after a receipt where the
  user supplied substantive content.
- Confidence is a real number in `[0, 1]`; booleans are invalid. Category ids
  below threshold are cleared. Out-of-roster ids invalidate placement but do
  not discard a separately valid turn kind or caller-held answer.
- Placement questions pass the Conversation lints and may not expose ids,
  offer a menu, ask yes/no, presuppose a category, contain multiple questions,
  or repeat a question the user already answered.

The normalized `QuestionCandidateDecision` is:

```json
{
  "schema_version": 1,
  "status": "active|needs_clarification|complete|declined|deferred|invalid",
  "candidate_outcome": "engaged|answered|declined|deferred|null",
  "candidate_id": "cand-lighthouse-1",
  "candidate_revision": "sha256:<64 lowercase hex>",
  "source_revision": "capture:synthetic-lighthouse:3",
  "association_stage": "before_answer|during_answer|after_answer",
  "category_id": "F|null",
  "category_revision": "sha256:<64 lowercase hex>|null",
  "placement_revision": "sha256:<64 lowercase hex>|null",
  "answer_status": "none|held|durable",
  "turn_kind": "placement_only|answer|mixed|null",
  "reply": "string|null",
  "placement_question": "string|null",
  "completion": {
    "answer_durable": false,
    "placement_resolved": false,
    "outcome_resolved": true,
    "complete": false
  }
}
```

- Play starts/continues `candidate_outcome: engaged`. This is not accepted,
  promoted, or promotion-ready state.
- An engaged answer becomes `complete`/`answered` only when the caller attests
  `answer_status: durable` and an exact revision-valid placement is resolved.
  If the answer is durable first, status stays `active` or
  `needs_clarification`; if placement resolves first, status stays `active`.
- Explicit decline/defer yields terminal `declined`/`deferred` without a model
  call and without requiring an answer or placement. Those outcomes are
  resolved but `completion.complete` is false because they are not answered
  completion.
- `placement_revision` hashes exactly candidate revision, category id, and
  selected category revision. Candidate or selected-category churn invalidates
  it; unrelated roster churn does not.
- The decision describes portable coordination facts. PR A performs no
  candidate/session/vault/Git mutation. A consuming coordinator revalidates the
  decision against current revisions before any durable transition.

### Public runtime and CLI

`system/question_candidate.py` owns schema, hashes, prompt construction,
normalization, completion, and staleness validation:

```python
build_candidate_anchor(candidate_id: str, question: str, source_revision: str) -> dict
build_category_roster(categories: list[dict]) -> dict
build_question_candidate_prompt(payload: dict) -> str
parse_question_candidate_output(raw: object, *, payload: dict) -> dict
validate_question_candidate_decision(decision: dict, *, current_candidate: dict, current_roster: dict) -> dict
```

The prompt builder uses `compose_interaction_asset("question_candidate", ...)`
for inherited behavior; it never imports or copies Conversation prompt text.
`system/lifehug.py question-candidate-prompt` reads exact input JSON on stdin,
prints the composed prompt, and is classified read-only.

`system/question_candidate_evals.py` is the independent harness and CLI
`question-candidate-evals`. It reuses generic gate arithmetic from a shared
module rather than importing candidate logic into `conversation-evals`.
Ordinary `conversation-evals` returns to its pre-PR-A surface.

## Scope

In:

1. Revise this contract and ADR 0018 before code so the independent
   Interaction/audit/composition boundary is reviewable.
2. Add the closed registry and generic registry/composition/audit runtime; add
   all existing Interactions plus Question Candidate.
3. Add the complete `interactions/question_candidate/` package, own manifest
   version 1.0.0, child prompts/context/router/overlays/evals, and empty seat.
4. Add the pure runtime and read-only CLI above, including explicit
   engage/decline/defer outcomes and answered-completion criteria.
5. Add synthetic fixtures covering initial direct-to-conversation, placement
   before/during/after, silent resolution, deferred association, natural
   clarification, placement-only/answer/mixed turns, lifecycle actions,
   prompt injection, malformed output, threshold edge, and revision churn.
6. Add independent candidate gates for category accuracy, turn-kind accuracy,
   closed-roster compliance, question validity, timing/defer validity,
   completion validity, and stale-revision rejection. Add composition parity,
   registration isolation, and no-copy-drift tests.
7. Restore every candidate-specific modification under Conversation and prove
   ordinary manifest/source/prompt/eval byte identity against v180 hashes.
8. Update Interaction docs, generated handbook parity, ADR, changelog, and
   v181 `framework_files` for every new/renamed/deleted distributable file.
9. Evidence must enumerate the downstream pin surface and explicitly hand off
   the modal-free Play route to platform #469.

Out:

- Direct Promote implementation; question-id allocation; question-bank writes;
  candidate persistence; idempotency keys; provenance markers; Git commits;
  `commit_sha`; or a promotion receipt. These are PR B.
- Platform code, platform pin bump, Home/Today UI, new-tab routing, modal
  deletion, web evidence, or platform coordinator storage. Platform #469
  consumes this release contract but implementation remains downstream.
- A category picker, required placement before the first substantive turn, or
  model-authorized candidate transitions.
- Provider-specific behavior or a default model seat.
- New vault paths or changes to `system/vault_contract.json`.

## Implementation notes

- The registry is framework-scoped (`system/lifehug_core.py::INTERACTIONS_DIR`),
  never vault-scoped. Resolve and validate paths before reading; registry and
  manifest strings cannot escape `interactions/`.
- Use the repo's flat scalar YAML parser. Composition lists are pipe-delimited
  scalar values; do not add PyYAML or nested syntax.
- Render all caller strings inside a bounded JSON `UNTRUSTED_DATA` block after
  the composed instruction authority. The candidate, roster, and user text
  cannot alter roles, output schema, lifecycle facts, or tool access.
- Runtime determines status/completion from strict input plus normalized model
  proposal. The model never receives fields that authorize writes and never
  supplies `answer_status`, `requested_outcome`, revisions, or completion.
- Extract/reuse generic threshold gate arithmetic if candidate evals otherwise
  duplicate Conversation's checker. Keep harness ownership separate.
- The platform should pin the final PR B release, not v181 alone. PR A still
  provides an exact reconciliation checklist so the eventual bump cannot miss
  the registry, composition, schema, prompt, eval, or lifecycle surface.

## Test plan

Add or revise focused tests:

- `tests/test_interaction_registry.py`: exact registry, complete audit,
  lineage/version/cycle/traversal rejection, append/leaf provenance, direct
  parent-byte parity, unregistered package isolation, no copied Conversation
  clauses, and ordinary Conversation self-lineage.
- `tests/test_question_candidate.py`: strict anchors/rosters/revisions,
  before/during/after prompt data, initial Play no modal/no promotion,
  resolved/defer/ask-now consistency, reply/turn retention, injection boundary,
  threshold typing, decline/defer bypass, all completion permutations,
  staleness, read-only CLI, and ordinary Conversation v180 byte hashes.
- `tests/test_question_candidate_evals.py`: independent fixture schemas,
  scorer math/gate boundaries, timing/completion/lifecycle cases, inherited
  Conversation lint parity, and loud provider skips.
- Restore `tests/test_interaction_evals.py` to ordinary Conversation coverage.

Scoped local gates (no broad full suite while sibling agents share the host):

```bash
python3 -m unittest \
  tests.test_interaction_registry \
  tests.test_question_candidate \
  tests.test_question_candidate_evals \
  tests.test_interaction_evals -v
python3 system/lifehug.py conversation-evals
python3 system/lifehug.py question-candidate-evals
python3 scripts/ci/check_framework_files.py
python3 scripts/check_version_bump.py
python3 -m compileall -q system tests
git diff --check
```

CI is the authoritative broad suite and must pass on Python 3.11 and 3.14 for
the exact pushed SHA. Report failing test names and fixes; do not normalize a
red baseline.

## Launch-and-verify

No viewer code changes; screenshots/motion are not required. The executable
review surface is:

```bash
python3 -c '
import json
from pathlib import Path
rows = json.loads(Path("interactions/question_candidate/evals/goldens/fixtures.json").read_text())
print(json.dumps(rows[0]["input"]))
' | python3 system/lifehug.py question-candidate-prompt

python3 system/lifehug.py question-candidate-evals
```

Pass means the first command shows inherited Conversation authority followed by
Question Candidate authority and one bounded `UNTRUSTED_DATA` block containing
the exact synthetic candidate/closed roster; it does not present a category
menu or claim promotion. The second command names all deterministic layers as
green and marks any unavailable live provider step `SKIPPED` loudly.

## Acceptance criteria

- [ ] Question Candidate is independently registered, auditable, versioned,
      seatable, and eval-gated; it is not a Conversation step or mode.
- [ ] The child composes current Conversation assets with deterministic
      provenance and version binding; no parent prose is copied into the child.
- [ ] Ordinary Conversation definition, behavior, prompts, router, and eval
      surface retain v180 bytes and semantics.
- [ ] Play can open directly on the exact candidate and begin substantive
      conversation without a modal or required initial placement question.
- [ ] Placement may resolve or be asked naturally before/during/after; deferred
      placement never causes an answer turn to be discarded.
- [ ] Answered completion requires a durable answer, revision-valid category,
      and answered outcome. Starting Play is engaged, never promoted.
- [ ] Direct Promote is outside this Interaction; explicit Decline and defer
      are runtime-authored outcomes and never model authorization.
- [ ] Empty/duplicate/oversized/malformed/forged/stale inputs fail closed; model
      output cannot escape the exact roster or prompt/data boundary.
- [ ] Independent deterministic/sample eval gates pass; live seating skips
      loudly without credentials.
- [ ] No PR A path writes candidate, question bank, session, vault, Git, or
      projection state.
- [ ] Evidence names all platform handoff changes and says to wait for PR B's
      final version before pinning.

## Owner closeout template

**Look**

1. Run both Launch-and-verify commands.
2. Confirm the prompt names `conversation` then `question_candidate` at the
   provenance seams, keeps candidate/user/category strings only in
   `UNTRUSTED_DATA`, and never shows a picker or promotion claim.
3. Confirm the eval summary separately names composition, initial Play,
   before/during/after placement, lifecycle, injection, malformed, and stale
   cases; unavailable live seating says `SKIPPED`.

**Judge**

1. Yes/no: approve an independently registered Question Candidate Interaction
   that composes Conversation chat mechanics? Yes ratifies the audit boundary
   and rejects storing candidate behavior inside Conversation.
2. Yes/no: approve `0.8` silent placement and a complete 64-entry hard bound?
   Yes makes those portable OSS/platform defaults; above 64 fails closed.
3. Yes/no: approve letting placement resolve before/during/after, with one
   natural question only when appropriate? Yes rejects the pre-conversation
   modal and forced initial category choice.
4. Yes/no: approve answered completion only after durable answer + current
   placement + answered outcome? Yes makes Play engagement non-promoting and
   makes partial progress explicitly non-terminal.
5. Yes/no: approve per-selected-category revision binding? Yes lets unrelated
   roster additions survive while selected-category removal/remapping fails.

**Done when**

Approval merges PR A's independent Interaction/composition authority and
triggers its normal version tag. It does not promote candidates. PR B must land
the idempotent structured promotion receipt; platform #469 then pins the final
PR B release and implements green Promote, red Decline, and modal-free Play.

## Definition of done

- [ ] Contract and ADR record the independent Interaction/audit architecture
      before implementation commits.
- [ ] Scoped local gates pass; exact pushed SHA is green on both CI matrices.
- [ ] v181 version, release date, changelog, and framework manifest exactly
      reflect the registered package and runtime/eval surfaces.
- [ ] Interaction README/handbook and operating docs are updated where the
      architecture changed; parity checks pass.
- [ ] PR #171 has substantive exact-SHA evidence plus current Owner closeout;
      issue #170 remains open for PR B.
- [ ] No viewer evidence is required because `serve_wiki.py` is untouched.

🤖 Generated with GPT-5.6-Sol via Codex
