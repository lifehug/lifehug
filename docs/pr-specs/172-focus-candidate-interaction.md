# Contract: focus-candidate-interaction

## Why

Issue #172 requires a Focus Candidate to be a real Interaction rather than a
mode hidden inside Conversation or Focus Curation. Today a pending Focus can be
approved sparsely, and v183 can persist already-collected candidate research,
but there is no independently registered conversational surface that gathers
enough exact, user-grounded material before approval. This PR adds that surface
without changing ordinary Conversation, Question Candidate, Entity Candidate,
or the existing approval policy.

## Binding facts

- Base and dependency: annotated `v183` and `origin/main` dereference to
  `ffcb6040a9846e1919808fe96c06cec3d36fb9b9`. Version becomes **v184**.
- Canonical package and registry identity are
  `interactions/focus_candidate/` and `focus_candidate`. The package pins and
  exact-composes `conversation` version `1.0.0` through
  `system/interaction_registry.py`; it copies no Conversation authority.
- The child appends identity, behavior, examples, router, and deflection. Its
  context manifest and turn instructions are leaf authority. Composition must
  preserve every parent/child source byte, adding only the registry's
  provenance/newline seams.
- Starting/playing is read-only. It does not approve a recommendation, call
  `roadmap.focus_new()`, create a Focus/category/question, write candidate
  research, or claim any durable result. Completion also leaves the
  recommendation pending: approval remains exclusively
  `recommend_focuses.approve_recommendation()` and direct approval retains its
  current sparse behavior.
- `candidate_id` is the only client-supplied anchor. Runtime resolves the exact
  recommendation from `state/focus_recommendations.json`, rejects duplicate or
  missing ids, and derives the closed v183 subject with
  `candidate_research.build_focus_candidate_subject()`. Candidate contents,
  model output, and user turns are untrusted. A supplied subject, identity
  revision, subject revision, candidate state, source path, source id, or Git
  result is never accepted as authority.
- Only one current `pending` recommendation is active. `approved` is consumed;
  `dismissed` and `expired` are tombstoned. Missing, duplicated, consumed,
  tombstoned, identity-changed, or revision-changed candidates fail closed at
  prompt construction, decision validation, and again after the v183 writer's
  pull/rebase callback.
- Authoritative turns use v183
  `candidate_research.build_authoritative_user_turn()` and exact Unicode code
  point offsets. Only exact `role=user` slices are evidence. Model prose,
  summaries, candidate text, existing recommendation evidence, prompts, and
  generated seed questions are never evidence.
- The Interaction's frozen usefulness rubric has these **eight** dimensions,
  in this order:
  `focus_identity`, `why_it_matters`, `scope_boundary`,
  `present_state_direction`, `relationships`, `grounded_evidence`, `tensions`,
  `open_questions`.
- Seven dimensions map to v183 source dimensions as follows:
  `focus_identity -> identity`, `why_it_matters -> why_it_matters`,
  `scope_boundary -> scope_boundary`,
  `present_state_direction -> present_state_or_direction`,
  `relationships -> relationships`, `tensions -> tensions`, and
  `open_questions -> open_questions`. `grounded_evidence` is an independent
  Interaction gate satisfied only by at least one exact span whose v183
  `evidence_kind` is `concrete_event` or `concrete_observation`; that span also
  supports at least one mapped v183 dimension. It is not emitted as an eighth
  key into v183's closed seven-key `dimension_evidence` schema. A parity test
  pins this mapping and v183 constants so either contract must change
  deliberately.
- Ready means all eight dimensions are supported, at least three non-overlapping
  substantive exact user spans pass v183's thresholds, at least one span is a
  concrete event/observation, and at least two distinct worthwhile generated
  seed questions exist. Seed questions are always `evidence=false`.
- Readiness and completeness are deterministic runtime results, never trusted
  booleans from the model. Completion additionally requires a distinct exact
  user confirmation span bound to the current assessment revision. Evidence
  and confirmation may not overlap. A request to confirm is not confirmation.
- Conversation is natural, not a checklist. On each turn the worker selects
  the highest-value unsupported dimension; it may ask before, during, or after
  other substantive exchange. It asks at most one open question, obeys all
  inherited Conversation lints, does not expose dimension/schema names, and
  does not repeat a semantically answered gap. Once ready it asks one natural
  confirmation question. A later explicit affirmative turn may complete.
- Model output has no tool, filesystem, Git, lifecycle, approval, or source
  authority. Parsed replies for every action pass inherited Conversation lints.
  Runtime rejects extra keys, invalid enums/types/bounds, non-exact spans,
  overlap, missing/repeated questions, fabricated readiness, stale revisions,
  and durability/approval claims.
- Completion delegates to
  `candidate_research.resolve_candidate_research_source()` with a fresh,
  root-aware subject loader. It inherits v183's single exact-file Git writer,
  immutable source, structured receipt, idempotent replay (`changed=false` and
  the first introducing `commit_sha`), crash adoption, contender discovery,
  manifest repair, and post-pull/rebase revalidation. No second writer exists.
- The completion receipt is exactly the canonical v183 receipt:

  ```json
  {
    "candidate_kind": "focus_candidate",
    "candidate_id": "rec-synthetic",
    "subject_type": "person|place|period|theme",
    "source_id": "candidate-research:focus_candidate:<sha256>",
    "source_path": "sources/candidate-research/focus_candidate/<32hex>.md",
    "research_revision": "<sha256>",
    "content_sha256": "<sha256>",
    "changed": true,
    "commit_sha": "<40hex>"
  }
  ```

- After a separate later approval, the existing compiler must attach that
  exact source by typed identity and render a cited, non-placeholder Focus
  page. Before approval the source must not create or compile a Focus. Direct
  approval without research continues to render the existing sparse result.
- No fixture, test, log, or command may access `~/Workspace/dave` or any other
  private vault. All examples use temporary synthetic vaults.

### Public runtime interfaces

`system/focus_candidate.py` is the sole Interaction runtime authority and
exports:

```python
FOCUS_DIMENSIONS: tuple[str, ...]
FOCUS_TO_RESEARCH_DIMENSION: dict[str, str]

load_focus_candidate_subject(
    candidate_id: str, *, vault_root: str | Path | None = None
) -> dict

validate_focus_candidate_input(
    value: object, *, current_subject: dict
) -> dict

build_focus_candidate_prompt(
    value: dict, *, current_subject: dict
) -> str

parse_focus_candidate_output(
    raw: object,
    *,
    payload: dict,
    current_subject: dict,
    confirmed_at: str | None = None,
) -> dict

validate_focus_candidate_decision(
    decision: object,
    *,
    payload: dict,
    current_subject: dict,
) -> dict

resolve_focus_candidate_completion(
    assessment: dict,
    *,
    authoritative_turns: Sequence[dict],
    candidate_id: str,
    current_subject_loader: Callable[[], dict],
    authority: candidate_research.CandidateResearchGitAuthority =
        candidate_research.EXACT_FILE_GIT_AUTHORITY,
    vault_root: str | Path | None = None,
    push: bool = True,
    failpoint: Callable[[str], None] | None = None,
) -> dict
```

The prompt/decision payload is a closed object:

```json
{
  "schema_version": 1,
  "candidate_id": "rec-synthetic",
  "subject_revision": "<runtime-resolved sha256>",
  "authoritative_turns": ["<canonical v183 user-turn objects>"],
  "assessment": "<canonical v183 assessment or null>",
  "latest_turn_id": "turn-id|null",
  "previous_question": "string|null"
}
```

`subject_revision` is emitted by trusted runtime into the assembled payload,
not accepted from a browser as identity authority. Validation always compares
it to `current_subject`. `assessment`, when present, is fully revalidated
against the exact turns and current subject.

The model proposal is exactly:

```json
{
  "reply": "string",
  "action": "ask_gap|offer_confirmation|accept_confirmation|continue",
  "next_gap": "<one of eight dimensions>|null",
  "evidence_spans": [
    {"turn_id":"turn-id","start":0,"end":42,"evidence_kind":"statement|concrete_event|concrete_observation"}
  ],
  "dimension_evidence": {
    "focus_identity": [0],
    "why_it_matters": [0],
    "scope_boundary": [],
    "present_state_direction": [],
    "relationships": [],
    "grounded_evidence": [],
    "tensions": [],
    "open_questions": []
  },
  "seed_questions": ["string"],
  "confirmation_span": {"turn_id":"turn-id","start":0,"end":3}|null
}
```

Indices refer only to this proposal's `evidence_spans`; runtime converts them
to canonical v183 evidence revisions, merges them with the prior canonical
assessment without duplicates/overlap, and recomputes every dimension and
counter. `grounded_evidence` indices must name concrete spans. The normalized
decision adds canonical `subject`, `assessment`, `ready`, `complete`,
`decision_revision`, and `status` (`continue|awaiting_confirmation|complete`),
all runtime-derived. `accept_confirmation` is valid only when the supplied
prior assessment was already ready before the latest turn, adds no
evidence/dimensions/seed questions, and `confirmation_span` is an exact distinct
`evidence_kind=confirmation` user slice; other actions require it to be null.
`offer_confirmation` is valid only when ready. `ask_gap` requires exactly one
question, a currently unsupported `next_gap`, and no checklist/schema wording.
All other actions require `next_gap=null`; replies on every action pass the
same inherited Conversation lint engine. `accept_confirmation` additionally
requires caller-supplied trusted UTC-seconds `confirmed_at`; model output never
authors a timestamp, and retries reuse the original event timestamp.

### CLI and seat surface

- `lifehug.py focus-candidate-prompt --candidate-id ID` reads one closed JSON
  payload from stdin, resolves the candidate from the selected vault, and emits
  the prompt. It is read-only.
- `lifehug.py focus-candidate-complete --candidate-id ID [--no-push] --json`
  reads canonical turns plus a completed assessment from stdin, reloads the
  recommendation before and inside the writer decision, delegates to the v183
  resolver, and emits only the structured receipt. It is the only mutating
  Focus Candidate CLI and never approves.
- `lifehug.py focus-candidate-evals [--live] [--json]` is independent of the
  Conversation and Question Candidate eval commands. Recorded mode is
  deterministic. Live mode skips loudly unless a provider is configured and
  may seat the package only when all configured gates pass.
- The package owns its `role.router`, `role.worker`, and `role.planner` tier
  declarations. Provider overlays describe portability only; no concrete model
  is silently made the production seat.

## Scope

In scope: the registered package, exact composition, pure runtime/parser,
root-aware recommendation resolution, completion adapter over v183, independent
eval harness and synthetic fixtures, CLI registration, handbook entry, ADR,
compiler/source integration proofs, walkthrough, v184 metadata, and manifest.

Out of scope: Entity Candidate; hosted platform/deep-link wiring; UI/modal
changes; recommendation generation/scoring; Focus approval/autopilot; entity
verdict/graduation; question promotion; a new Git writer; changing v183 source
bytes/schema; changing ordinary Conversation, Question Candidate, or Entity
Candidate assets; choosing a production provider seat; tagging, merging, or
closing #172.

## Implementation notes

- Register in `interactions/registry.json`; place all owned assets below
  `interactions/focus_candidate/`. Extend the existing general composition
  mechanism only if needed; do not special-case Focus Candidate composition.
- Reuse `conversation_lints` for every reply action and
  `interaction_registry.compose_interaction_asset()` for prompt assembly.
- Reuse the v183 `candidate_research` builders, validators, readiness,
  confirmation, resolver, source format, and Git authority. The Interaction
  layer may translate the eight-dimension rubric but must not fork those
  primitives or write files directly.
- Resolve recommendations through `recommend_focuses.load_recommendation_state`
  or one root-aware equivalent that is safe for injected synthetic vaults. Do
  not mutate module globals in production code.
- Update `system/lifehug.py` command classification: prompt/evals are read-only;
  completion is direct mutation. Preserve the existing command behavior.
- Document the interaction at
  `docs/handbook/interactions/focus-candidate.md`, link it from the Interaction
  index and Focus handbook, and record the durable boundary in
  `docs/adr/0021-focus-candidate-interaction.md`.
- Add every distributable file to `system/version.json.framework_files`, bump
  the version/changelog to v184, and regenerate `README.md` only through the
  repository's documented README generation/check path if required.

## Test plan

Add `tests/test_focus_candidate.py` and
`tests/test_focus_candidate_evals.py`; extend
`tests/test_interaction_registry.py`, `tests/test_candidate_research.py`,
`tests/test_wiki_compile.py`, `tests/test_handbook_parity.py`, and
`tests/test_lifehug_wrapper.py` only at the named seams.

Required regression matrix:

- exact registry lineage, package audit, parent-before-child composition,
  source-byte parity including trailing whitespace, leaf isolation, unregistered
  rejection, and unchanged bytes for every pre-v184 Conversation, Question
  Candidate, and Entity Candidate asset;
- start is zero-write; candidate resolution rejects missing, duplicate,
  approved, dismissed, expired, forged, and stale identities/revisions;
- prompt injection in candidate/turn/model strings has no authority;
- exact user slicing, Unicode offsets, substantive threshold, non-overlap,
  concrete evidence, all eight dimensions, two worthwhile/distinct seed
  questions, and generated text never becoming evidence;
- action matrix for one-question and all inherited Conversation lints;
  highest-value missing-gap routing without schema/checklist language;
- request-for-confirmation versus distinct explicit confirmation, stale
  assessment confirmation, and readiness/completion recomputation;
- completion delegates to the canonical resolver, never approves, is
  idempotent, adopts crash-after-commit/push, and rejects concurrent lifecycle,
  identity, revision, path, bytes, manifest, or contender changes;
- before approval no Focus appears; after canonical approval+compile, research
  yields a cited non-placeholder Focus page; direct sparse approval remains
  unchanged;
- recurring-defect guard rejects any Focus Candidate filesystem/Git writer or
  approval call outside the one completion delegation seam;
- CLI JSON success/failure, command classification, manifest completeness,
  version/changelog, handbook embeds/parity, and synthetic-only fixtures.

Recorded and live eval gates are exact:

- inherited Conversation deterministic clauses: `1.0`;
- readiness false-positive rate: `0.0`;
- evidence grounding/identity safety: `1.0`;
- one-question lint: `1.0`;
- next-gap accuracy: at least `0.85`;
- readiness recall: at least `0.90`.

Execute from repository root:

```bash
python3 -m unittest \
  tests.test_interaction_registry \
  tests.test_focus_candidate \
  tests.test_focus_candidate_evals \
  tests.test_candidate_research \
  tests.test_wiki_compile \
  tests.test_handbook_parity \
  tests.test_lifehug_wrapper
python3 system/lifehug.py focus-candidate-evals --json
python3 tests/walkthrough_focus_candidate.py
python3 system/format_frameworks.py --check
python3 system/update.py --check-manifest
python3 system/update.py --check-version
git diff --check
git diff --stat origin/main...
```

Do not run the broad full suite while sibling agents share the machine; GitHub
CI is the full-matrix authority for the exact pushed SHA.

## Launch-and-verify

This PR does not change `serve_wiki.py`; visual evidence is not required.
`python3 tests/walkthrough_focus_candidate.py` is a committed synthetic CLI/API
walkthrough. It must prove: start makes no files; three natural user turns
produce exact grounded spans and all eight dimensions; readiness alone does not
complete; a distinct exact confirmation completes; the first completion emits
a canonical changed receipt without approving; replay returns `changed=false`
with the same commit; a stale/dismissed concurrent candidate fails; later
canonical approval+compile emits a cited non-placeholder Focus page.

## Definition of done

- [ ] Contract is the first branch commit and the implementation remains on
      the same draft PR.
- [ ] Package is independently registered, auditable, seatable, and exact-
      composes Conversation without copied authority.
- [ ] Play/start is read-only; completion writes only the v183 immutable source
      and returns its canonical receipt; approval stays separate.
- [ ] Eight-dimension usefulness, exact grounding, explicit confirmation,
      lifecycle/revision/concurrency boundaries, and one-question behavior are
      regression-tested.
- [ ] Recorded eval gates pass; live seating cannot pass without a configured
      provider and all thresholds.
- [ ] Scoped commands above pass locally and full GitHub CI is green for the
      exact final SHA.
- [ ] `system/version.json` is v184 with complete manifest/changelog; docs and
      ADR are current.
- [ ] Synthetic walkthrough and evidence comment include exact SHA and results.
- [ ] Draft PR remains draft; implementing agent does not label, mark ready,
      merge, tag, or close #172.

## Owner closeout

**Look:** Read the package handbook page and the synthetic walkthrough output.
Confirm that Play begins a natural research conversation, readiness leads to a
separate confirmation, completion emits a source receipt, and the candidate is
still pending until later approval.

**Judge:**

1. Yes/no: Does the eight-dimension rubric capture the minimum useful Focus
   context while allowing questions to occur naturally rather than in order?
   Yes ratifies the rubric and its v183 mapping.
2. Yes/no: Is a distinct explicit confirmation the right boundary before exact
   user excerpts become an immutable candidate-research source? Yes ratifies
   ADR 0021's evidence/durability boundary.
3. Yes/no: Is keeping completion separate from Focus approval correct? Yes
   preserves current approval/autopilot policy and lets researched candidates
   remain candidates.

**Done when:** Owner approval queues this draft for the merge train after exact-
SHA full CI is green. Merge publishes no tag and performs no hosted-platform
wiring; the platform twin must later pin v184 and implement the Play deep link.

🤖 Generated with GPT-5.6-Sol via Codex
