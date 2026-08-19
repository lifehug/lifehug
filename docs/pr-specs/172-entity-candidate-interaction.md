# Contract: entity-candidate-interaction

## Why

Issue [#172](https://github.com/lifehug/lifehug/issues/172) requires Entity
Candidate to be a real Interaction rather than a Conversation mode or an
entity-verdict shortcut. Version 183 already persists exact user-grounded
candidate research and cites it after an entity independently graduates, but
there is no registered conversational surface that decides what is still
missing for a useful first page. This PR adds that surface for person, place,
period, object, and theme candidates. It powers the later hosted Review
**Play** flow in
[lifehug-platform#517](https://github.com/lifehug/lifehug-platform/issues/517)
without adding an OSS viewer action, changing automatic graduation, or letting
research completion stand in for approval.

The feature is **In the Loop** only at the existing v183 boundary: confirmed
exact excerpts become canonical source material, and a later ordinary compile
may consume them after the roster has independently made the entity
page-eligible.

## Binding facts

### Base, release train, and authority

- This contract branch starts from annotated v183 / origin/main at
  ffcb6040a9846e1919808fe96c06cec3d36fb9b9.
- PR [#175](https://github.com/lifehug/lifehug/pull/175) is the in-flight Focus
  Candidate sibling. Its contract-first shape is precedent for independent
  Conversation composition, not semantic authority for Entity Candidate.
  Entity implementation MUST wait for #175 to merge, rebase this branch onto
  that exact landed release, and then land as **v185**. If #175 does not land as
  v184, amend this release fact before implementation; never guess or reuse a
  version.
- This contract is the first branch commit. Implementation later adds proposed
  ADR **docs/adr/0022-entity-candidate-interaction.md**. OSS convention does not
  require that ADR in the contract-only first commit.
- **system/candidate_research.py** v183 remains the sole subject, evidence,
  assessment, confirmation, source-rendering, marker, receipt, and completion
  authority. **system/exact_file_git.py** remains the sole writer/lease/Git
  authority. Entity Candidate adds no writer, lease, receipt ledger, source
  format, compiler route, or Git subprocess.
- **system/entity_roster.py** and **system/entity_verdict.py** remain the sole
  automatic and owner-directed entity lifecycle authorities. The Interaction
  never sets qualifies, maps_to_focus, page_eligible, or owner_verdict and
  never pauses, reserves, or suppresses monthly roster refresh or compile-time
  graduation.
- Files under interactions/conversation/, interactions/question_candidate/,
  and, after the dependency rebase, interactions/focus_candidate/ remain
  byte-identical to their landed parent release. Ordinary Conversation,
  Question Candidate, and Focus Candidate runtime/eval bytes remain unchanged.
  Registry, CLI, release manifest, documentation, and named guard tests receive
  only additive Entity Candidate entries.

### Independent package, composition, and seat

- Canonical package and registry identity are
  **interactions/entity_candidate/** and **entity_candidate**.
- Package version is 1.0.0. It exact-composes registered conversation version
  1.0.0 through system/interaction_registry.py. It imports or copies no
  Question Candidate or Focus Candidate prompt, runtime, fixture, lifecycle,
  or eval semantics.
- Identity, behavior, examples, router, and deflection append parent then child
  with deterministic registry provenance. Context manifest and turn
  instructions are child leaf authority. Every source byte is preserved apart
  from the registry's provenance/newline seams.
- The exact flat-scalar manifest is:

~~~yaml
interaction: entity_candidate
version: 1.0.0
extends: conversation
extends.version: 1.0.0
modes: research
load_order: identity|behavior|examples|candidate|type_rubric|research_state|conversation|turn_instructions
composition.append: prompt/identity.md|prompt/behavior.md|prompt/examples.md|router/router.md|router/deflection.md
composition.leaf: prompt/turn-instructions.md|context/manifest.md
role.router: haiku-class
role.worker: sonnet-class
role.planner: sonnet-class
knob.max_proposal_spans: 16
budget.identity: 800
budget.behavior: 2400
budget.examples: 1800
budget.candidate: 3200
budget.type_rubric: 2200
budget.research_state: 7200
budget.conversation: 1600
budget.turn_instructions: 1500
~~~

- Capability tiers are declarations, not concrete provider seats. Provider
  overlays begin with the standard empty-portability header. No production
  model becomes the default merely because recorded evals pass; a configured
  model must pass this package's live layer before seating.
- The package independently owns README, manifest, specialization prompts,
  context recipe, router/deflection, four provider overlays, lints, rubrics,
  goldens, personas, version, and eval command. A directory absent from
  interactions/registry.json is not executable or seatable.

### Candidate identity and lifecycle

- candidate_id is the only client-supplied anchor. It has exact v183 form
  entity:<person|place|period|object|theme>:<canonical-slug> and is never a
  filesystem path.
- Trusted runtime parses the closed type, reads only
  state/entity_rosters/<type>.json through vault_paths.vault_data_path() plus
  the no-follow strict-UTF-8 reader, validates roster version 1 and matching
  type, and requires exactly one entry whose freshly built v183 subject has
  that id.
- Missing files/rows, duplicate identities, malformed JSON, symlinks, special
  files, traversal, type/slug disagreement, or invalid identity/lifecycle
  fields fail closed.
- Runtime derives the subject only through
  candidate_research.build_entity_candidate_subject() and validates it with
  validate_candidate_research_subject(..., require_active=True). Browser,
  platform, projection, prompt, model, and caller-supplied label/type/slug/
  aliases/state/revision have no identity authority.
- Exact v183 lifecycle remains:
  - active: unmapped, page_eligible false, and no never/graduate verdict;
  - consumed: mapped, page-eligible, or verdict graduate;
  - tombstoned: verdict never, or a row missing at fresh resolution.
- Type, exact name, exact slug, ordered aliases, and state are revision-bound.
  Rename, alias/order change, slug/type change, mapping, verdict, eligibility,
  consumption, tombstone, or deletion invalidates prompt continuation,
  decision validation, and completion.
- Score, answer-count, and qualifies churn that leaves the exact v183 subject
  unchanged intentionally does not stale research. This Interaction may not
  broaden v183's subject revision.
- Starting/playing is zero-write. It may construct a prompt and return a first
  substantive turn, but writes no OSS session, source, roster, verdict, page,
  manifest, question, or receipt. Hosted durable session creation/resume is
  platform #517's transport concern.
- Research never reserves the candidate against automatic graduation. If a
  monthly refresh maps, qualifies, or graduates it, or an owner verdict changes
  it, while research is open, fresh resolution consumes or tombstones the
  subject and completion fails closed.
- Completion creates canonical source/readiness only. It leaves the roster
  pending and makes no approval/graduation claim. Later automatic eligibility
  or explicit entity-verdict graduate is still required. never and direct
  graduate actions bypass this Interaction and retain current behavior.

### Research basis

The rubric specializes system/research.md:

- The [Oral History Association's guidance](https://oralhistory.org/best-practices/)
  calls for open-ended guides, active-listening follow-ups for clarification,
  elaboration, and reflection, narrator-led relevance, and documented consent.
- McAdams's official
  [Life Story Interview II](https://sites.northwestern.edu/studyoflivesresearchgroup/instruments/)
  organizes useful material around chapters, significant scenes, participants,
  context, meaning, tensions, and future/open threads. His
  [agency/communion scene research](https://doi.org/10.1111/j.1467-6494.1996.tb00514.x)
  supports learning what an entity reveals through action and connection.
- Belli's
  [Event History Calendar research](https://doi.org/10.1080/741942610)
  supports sequential and parallel cueing across life domains. Ask for
  relative/landmark context and connections; never invent precision.
- Scannell and Gifford's
  [person-process-place framework](https://doi.org/10.1016/j.jenvp.2009.09.006)
  makes useful place material include the person-place bond, attachment
  process, and physical/social character.
- Belk's
  [possessions and extended-self research](https://doi.org/10.1086/209154)
  makes provenance/use plus symbolic meaning the object gate; a mundane prop
  is not useful merely because it was mentioned.
- [CIDOC CRM 7.1.3](https://cidoc-crm.org/sites/default/files/Documents/cidoc_crm_version_7.1.3.html)
  models historical knowledge through entities connected by events, people,
  places, and potentially fuzzy time-spans. Preserve uncertainty rather than
  inventing dates or links.

The worker receives a gap order, not a scripted interview. It receives/pays
back substance first, may gather several dimensions from one rich answer, and
asks only the highest-priority unsupported gap. It never exposes schema names,
marches through a checklist, repeats an answered question, leads the user,
demands conflict, or fabricates a missing fact. An exact user statement that
there is no known tension/open question is valid evidence of absence; the
model may not manufacture one.

### Closed usefulness rubric and v183 projection

The exact ordered Interaction roster is:

~~~python
ENTITY_DIMENSIONS = (
    "identity_disambiguation",
    "relationship_relevance_and_significance",
    "timeline_context",
    "connections",
    "tension_or_open_question",
    "type_specific_context",
    "grounded_evidence",
)

ENTITY_TO_RESEARCH_DIMENSION = {
    "identity_disambiguation": "identity_or_disambiguation",
    "relationship_relevance_and_significance": "relevance_or_relationship",
    "timeline_context": "history",
    "connections": "connections",
    "tension_or_open_question": "tension_or_open_question",
    "type_specific_context": "type_specific_context",
}
~~~

grounded_evidence is an independent Interaction gate, not a seventh key in
v183's closed six-key candidate_research.ENTITY_DIMENSIONS. A concrete span
must also support one mapped v183 dimension. A parity test pins both rosters,
the map, concrete kinds, and per-type span minima.

The dimensions mean:

1. **identity_disambiguation** — exact user material identifies which real
   entity this is, with enough role/name/location/boundary/object/theme detail
   to distinguish it from a homonym, generic role, neighboring place or
   period, interchangeable object, or adjacent theme. Roster fields are hints,
   not evidence.
2. **relationship_relevance_and_significance** — exact user material states the
   relationship/relevance to the author **and** why it matters now or then. A
   bare role such as “my coach” or “a town I lived in” is insufficient.
3. **timeline_context** — exact user material supplies a date, range, phase,
   sequence, transition, landmark anchor, or explicit uncertainty. Inferred
   dates, ages, order, duration, and contemporaries are forbidden.
4. **connections** — exact user material connects this entity to another
   person, place, period, object, theme, project, event, or relationship and
   says what the connection is.
5. **tension_or_open_question** — exact user material names a complication,
   ambiguity, competing meaning, change, unresolved question, or explicit
   absence. The model's question is never evidence.
6. **type_specific_context** — exact user material passes the current type rule
   below; naming the type does not pass.
7. **grounded_evidence** — at least one exact substantive concrete event or
   observation, which may also support another dimension.

The closed type rule is:

| Type | Required type-specific meaning |
|---|---|
| person | The person as a distinct human in action or observation: characteristic behavior, presence, priorities, voice, current inner world, or relationship change—not only title/kinship. |
| place | Physical/spatial/sensory or social character **and** how the author inhabited, used, belonged to, returned to, or experienced change there. |
| period | Life-structure or typical-day texture plus a transition/boundary relationship to before or after; prefer landmark anchors to guessed dates. |
| object | The specific item's provenance/use/custody **and** symbolic meaning in the author's life. A mundane prop fails even at high frequency. |
| theme | At least two distinct non-overlapping substantive spans show recurrence in separate episodes/domains, plus continuity, change, or contradiction in meaning. |

Theme type_specific_context requires at least two distinct evidence references;
every other type requires one. Evidence may support multiple dimensions,
subject to v183 overlap/duplicate rules.

Entity assessments allow 0–8 generated seed questions exactly as v183 does.
This Interaction proposes at most four per turn and normalizes each to
evidence:false. Generated questions never satisfy readiness, a dimension, the
type rule, or the open-question gate.

Ready is runtime-derived only when:

- all six mapped semantic dimensions pass;
- grounded_evidence is a concrete span also mapped to source;
- the type-specific reference-count/semantic rule passes;
- v183 recomputation passes two substantive spans for person/object or three
  for place/period/theme, plus a concrete span; and
- current subject and every exact turn/span/revision still validate.

No model-supplied ready, complete, count, revision, missing list, type result,
lifecycle fact, or source fact is trusted. Semantic false positives are the
recorded/live eval gate; structural readiness is recomputed in code.

### Deterministic next-gap policy

Exact per-type priorities are:

~~~python
ENTITY_GAP_PRIORITY = {
    "person": (
        "identity_disambiguation",
        "relationship_relevance_and_significance",
        "grounded_evidence",
        "timeline_context",
        "type_specific_context",
        "connections",
        "tension_or_open_question",
    ),
    "place": (
        "identity_disambiguation",
        "relationship_relevance_and_significance",
        "type_specific_context",
        "grounded_evidence",
        "timeline_context",
        "connections",
        "tension_or_open_question",
    ),
    "period": (
        "identity_disambiguation",
        "timeline_context",
        "type_specific_context",
        "grounded_evidence",
        "relationship_relevance_and_significance",
        "connections",
        "tension_or_open_question",
    ),
    "object": (
        "identity_disambiguation",
        "type_specific_context",
        "relationship_relevance_and_significance",
        "grounded_evidence",
        "timeline_context",
        "connections",
        "tension_or_open_question",
    ),
    "theme": (
        "identity_disambiguation",
        "relationship_relevance_and_significance",
        "grounded_evidence",
        "type_specific_context",
        "timeline_context",
        "connections",
        "tension_or_open_question",
    ),
}
~~~

After merging validated spans, runtime recomputes coverage and derives
expected_next_gap as the first missing entry. ask_gap is valid only when
next_gap equals it and reply has exactly one natural open question.
offer_confirmation is valid only when no gap remains and asks exactly one
plain-language yes/no durability question—the documented confirmation-seam
exception. Other substantive replies have no question. All actions pass the
single inherited Conversation lint authority plus authority-claim and
schema/checklist lints.

The model has no tool, filesystem, network, roster, verdict, compiler, Git,
source, session, or lifecycle authority. Candidate strings and turns are
bounded JSON under one final UNTRUSTED_DATA block. Delimiters aid readability;
exact-key parsing, fresh subjects, exact spans, revisions, and writer callbacks
are the security boundary. Instructions in names, aliases, turns, prior
questions, replies, or seed questions remain inert data.

### Exact evidence, confirmation, completion, and replay

- Authoritative turns use v183 build_authoritative_user_turn(). Exact Unicode
  code-point half-open slices from role=user turns are the only evidence.
- Roster/projected context, source snippets, assistant messages, detector
  evidence, classifier output, prompt text, model summaries/paraphrases,
  inferred facts, and generated questions are barred from evidence.
- Proposals contain offsets/kinds, never trusted quote/revision text. Runtime
  extracts exact slices, rejects invalid/non-substantive/overlapping/duplicate
  spans, maps only known indices, and rebuilds the canonical assessment.
- Readiness is not completion. Once ready, ask whether to preserve the user's
  **exact excerpts** as candidate research and say that this does not create or
  graduate a page.
- Completion requires a later/latest distinct user span matching the closed
  explicit-affirmation grammar, a previously ready current assessment, trusted
  UTC confirmed_at, and accept_confirmation. A request, implicit assent, model
  confidence, or overlapping evidence is not confirmation.
- accept_confirmation proposes no new evidence, mappings, questions, or gap.
  If the user confirms while correcting/adding substance, incorporate it,
  recompute, and ask again; never bind consent to stale material.
- Completion calls only
  candidate_research.resolve_candidate_research_source() with canonical
  assessment/turns, a root-aware fresh-subject loader, and canonical injected
  authority. That resolver revalidates after pull and any rejection rebase.
- Replay inherits v183: same bytes return changed:false plus the original
  introducing commit; different bytes/revision/path/marker/contender conflict.
  Crash adoption, manifest repair, unrelated-work preservation, two-device
  convergence, and lifecycle races use the one exact-file transaction.

The receipt is exactly:

~~~json
{
  "candidate_kind": "entity_candidate",
  "candidate_id": "entity:person:synthetic-alex-rivera",
  "subject_type": "person|place|period|object|theme",
  "source_id": "candidate-research:entity_candidate:<64hex>",
  "source_path": "sources/candidate-research/entity_candidate/<32hex>.md",
  "research_revision": "sha256:<64hex>",
  "content_sha256": "<64hex>",
  "changed": true,
  "commit_sha": "<40hex>"
}
~~~

There is no Entity-specific wrapper, session receipt, graduation flag, page
path, verdict, or approval field.

### Public runtime interfaces and schemas

**system/entity_candidate.py** is the sole runtime authority:

~~~python
ENTITY_DIMENSIONS: tuple[str, ...]
ENTITY_TO_RESEARCH_DIMENSION: dict[str, str]
ENTITY_GAP_PRIORITY: dict[str, tuple[str, ...]]
ENTITY_TYPE_SPECIFIC_MIN_REFS: dict[str, int]

load_entity_candidate_subject(
    candidate_id: str, *, vault_root: str | Path | None = None
) -> dict

build_entity_candidate_input(
    *,
    candidate_id: str,
    authoritative_turns: Sequence[dict],
    assessment: dict | None,
    latest_turn_id: str | None,
    previous_question: str | None,
    current_subject: dict,
) -> dict

validate_entity_candidate_input(
    value: object, *, current_subject: dict
) -> dict

build_entity_candidate_prompt(
    value: dict, *, current_subject: dict
) -> str

parse_entity_candidate_output(
    raw: object,
    *,
    payload: dict,
    current_subject: dict,
    confirmed_at: str | None = None,
) -> dict

validate_entity_candidate_decision(
    decision: object, *, payload: dict, current_subject: dict
) -> dict

resolve_entity_candidate_completion(
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
~~~

Prompt input is exact-keyed:

~~~json
{
  "schema_version": 1,
  "candidate_id": "entity:person:synthetic-alex-rivera",
  "subject_revision": "sha256:<64hex>",
  "authoritative_turns": ["<canonical v183 user-turn objects>"],
  "assessment": "<canonical v183 ResearchAssessment or null>",
  "latest_turn_id": "turn-id|null",
  "previous_question": "string|null"
}
~~~

Trusted runtime inserts subject_revision and compares it with the fresh
subject. Prompt assembly appends current subject, current type rubric/priority,
and input as bounded sorted JSON after composed assets. Caller retains the
complete transcript; prompt trimming never changes evidence or durability.

Model proposal is exact-keyed:

~~~json
{
  "reply": "string",
  "action": "ask_gap|offer_confirmation|accept_confirmation|continue",
  "next_gap": "identity_disambiguation|relationship_relevance_and_significance|timeline_context|connections|tension_or_open_question|type_specific_context|grounded_evidence|null",
  "evidence_spans": [
    {
      "turn_id": "turn-id",
      "start": 0,
      "end": 42,
      "evidence_kind": "statement|concrete_event|concrete_observation"
    }
  ],
  "dimension_evidence": {
    "identity_disambiguation": [],
    "relationship_relevance_and_significance": [],
    "timeline_context": [],
    "connections": [],
    "tension_or_open_question": [],
    "type_specific_context": [],
    "grounded_evidence": []
  },
  "seed_questions": ["string"],
  "confirmation_span": {"turn_id": "turn-id", "start": 0, "end": 3}
}
~~~

confirmation_span is null except on accept_confirmation. Dimension arrays index
only this proposal's spans; runtime projects canonical revisions into v183's
six arrays. seed_questions may be empty and is always non-evidence.

Normalized decision is exact-keyed:

~~~json
{
  "schema_version": 1,
  "status": "continue|awaiting_confirmation|complete|invalid",
  "action": "ask_gap|offer_confirmation|accept_confirmation|continue|null",
  "candidate_id": "entity:person:synthetic-alex-rivera",
  "subject_revision": "sha256:<64hex>",
  "reply": "string|null",
  "next_gap": "<closed gap|null>",
  "assessment": "<canonical v183 ResearchAssessment|null>",
  "ready": false,
  "complete": false,
  "decision_revision": "sha256:<64hex>"
}
~~~

Runtime derives every added field. invalid carries no new authority. ask_gap
requires the exact next gap/one question; offer_confirmation requires ready,
not complete, and one question; accept_confirmation requires prior readiness
and exact confirmation; continue carries no question/gap.

### CLI and independent eval surface

- lifehug.py entity-candidate-prompt --candidate-id ID reads closed JSON,
  freshly resolves roster subject, emits composed prompt, and is read-only.
- lifehug.py entity-candidate-complete --candidate-id ID [--no-push] --json
  reads canonical turns plus a complete assessment, reloads before and inside
  v183's transaction, and emits only the canonical receipt. It is the sole
  mutating CLI and never calls verdict or compile.
- lifehug.py entity-candidate-evals [--live] [--json] is independent of all
  sibling eval commands. Recorded mode is deterministic; live skips loudly
  without a provider and seats only after all Entity and inherited gates pass.
- Prompt/evals classify read-only in system/lifehug.py; completion is a direct
  canonical mutation.

## Scope

In scope: independent package/composition; root-aware roster resolution;
closed rubric/type rules/priority; pure input/prompt/proposal/decision runtime;
one v183 completion adapter; inherited lints; independent recorded/live evals;
three CLI registrations; synthetic all-type fixtures/walkthrough;
byte/isolation/authority guards; handbook/research docs; proposed ADR 0022; and
v185 metadata/manifest after rebase.

Out of scope: hosted Review/Today/BFF/session/deep-link work; OSS viewer/modal;
Conversation, Question Candidate, or Focus Candidate behavior; discovery,
scoring, roster resolution, graduation thresholds/cadence, entity-verdict,
Focus mapping, source/compiler/schema changes, generated summaries as source,
new durable session state, another writer/receipt, a production model choice,
issue closing, marking ready, merging, tagging, or manual CI dispatch.

## Implementation notes

- Rebase onto #175's exact merge before implementation. Resolve registry,
  handbook index, CLI, guard tests, and version manifest additively. Never copy
  Focus Candidate or edit its package/runtime/evals.
- New implementation files are:
  - docs/adr/0022-entity-candidate-interaction.md
  - docs/handbook/interactions/entity-candidate.md
  - required interactions/entity_candidate/ tree
  - system/entity_candidate.py
  - system/entity_candidate_evals.py
  - tests/test_entity_candidate.py
  - tests/test_entity_candidate_evals.py
  - tests/walkthrough_entity_candidate.py
- Expected additive edits are limited to interactions/registry.json,
  system/lifehug.py, system/version.json, CLAUDE.md, system/research.md,
  docs/handbook/entities.md, docs/handbook/interactions/index.md, and named
  registry/handbook/CLI/architecture tests.
- Any need to edit candidate_research, exact_file_git, wiki_compile, roster, or
  verdict behavior is a contract defect: stop and amend rather than fork.
- Use vault_data_path("entity_rosters", ...) then append validated <type>.json;
  use the no-follow reader. Preserve REPO_DIR's canonical type.
- Reuse interaction_registry.compose_interaction_asset() and canonical
  conversation_lints. Entity Candidate becomes an explicitly allowed
  registered child consumer; it does not reimplement lints.
- Model parse failures normalize to invalid; direct API/CLI/mutation failures
  remain explicit. Errors expose no private candidate, prompt, turn, or source
  content.
- Synthetic fixtures/disposable vaults only.
- Add all distributable files to framework_files and bump landed v184 to v185
  with a user-visible changelog. Do not bump this contract-only commit.

## Test plan

Add tests/test_entity_candidate.py and tests/test_entity_candidate_evals.py.
Extend only named registry, v183 source/compiler proof, handbook, CLI, and
architecture guards.

Required matrix:

- exact lineage/audit/composition/provenance/leaf/version rules and unchanged
  Conversation, Question Candidate, and Focus Candidate bytes;
- zero-write start for all five types; exact id/root/no-follow roster handling;
- full active/consumed/tombstoned and revision-churn matrix;
- injection strings remain data and errors remain metadata-only;
- Unicode spans, non-overlap/substance, and all non-user/non-exact sources
  structurally excluded from evidence;
- all seven gaps, v183 projection, concrete overlap, per-type 2/3 minima,
  theme's two refs, explicit absence, and no inferred timeline precision;
- exact next-gap priority, response-before-ask, one-question and inherited
  Conversation lints, no checklist/repeat/authority claims;
- positive and adversarial semantic goldens for all five type rules;
- ready-not-complete, request-not-confirmation, implicit assent rejection,
  distinct explicit confirmation, stale reassessment/reconfirmation;
- one canonical completion delegation, no writer/verdict import, pending
  lifecycle, exact receipt, replay/crash/concurrency/conflict/stale races;
- no page on completion; cited non-placeholder pages only after separate
  automatic eligibility or owner graduation for all five types; direct sparse
  graduation and current automatic thresholds unchanged;
- architecture guard rejects filesystem writes, exact_file_git, Git
  subprocess, lease, roster mutation, entity_verdict, compile, or
  focus_candidate imports in Entity runtime/evals;
- CLI/classification, framework manifest/version, handbook parity, and
  synthetic-only fixtures.

Recorded/live gates:

- inherited Conversation clauses: 1.0
- readiness false-positive rate: 0.0 overall and per type
- evidence grounding/identity safety: 1.0
- type-specific rubric precision: 1.0
- one-question lint: 1.0
- next-gap accuracy: >= 0.85 overall; no type below 0.80
- readiness recall: >= 0.90 overall; no type below 0.80
- graduation/source-boundary accuracy: 1.0

Exact implementation gates after rebasing onto landed v184:

~~~bash
python3 -m unittest tests.test_entity_candidate tests.test_entity_candidate_evals tests.test_interaction_registry tests.test_candidate_research tests.test_wiki_compile tests.test_handbook_parity tests.test_lifehug_wrapper tests.test_v120_vault_only.VaultContractTests tests.test_v150_conversation_store.NoBehaviorChangeGuardTests -v
python3 system/lifehug.py entity-candidate-evals --json
python3 tests/walkthrough_entity_candidate.py
python3 scripts/ci/check_framework_files.py
python3 scripts/ci/check_version_bump.py --base <LANDED_V184_SHA> --head HEAD
python3 -m compileall -q system tests
ruff check --select E4,E7,E9,F,I,UP,B --ignore E402,B905 system/entity_candidate.py system/entity_candidate_evals.py tests/test_entity_candidate.py tests/test_entity_candidate_evals.py tests/walkthrough_entity_candidate.py
ruff format --check system/entity_candidate.py system/entity_candidate_evals.py tests/test_entity_candidate.py tests/test_entity_candidate_evals.py tests/walkthrough_entity_candidate.py
git diff --check
git diff --stat <LANDED_V184_SHA>...
~~~

Do not run broad local discovery while sibling agents share the machine.
Focused gates plus exact-SHA GitHub Python 3.11/3.14 CI are authoritative.
Dispatch full CI once only after implementation/evidence is ready; this
contract-only stage does not dispatch it.

The implementing agent's compact evidence report must include:

1. base/rebased/final SHAs and v184 -> v185 check;
2. changed-file inventory and no-change digest for ordinary
   Conversation/Question/Focus authorities;
3. scoped test counts and each eval metric;
4. all-five-type walkthrough table;
5. write/replay/concurrency/crash/stale receipt facts;
6. pre-graduation absence and post-graduation cited-page proof;
7. manifest/static/privacy scans and synthetic-fixture attestation; and
8. confirmation that it did not touch labels/readiness/merge/tag/issues,
   platform wiring, verdicts, or extra CI dispatch.

## Launch-and-verify

No serve_wiki.py change; visual evidence is not required.

~~~bash
python3 tests/walkthrough_entity_candidate.py
~~~

The disposable-vault/local-Git walkthrough must prove:

1. Play/prompt for all five types creates no vault/Git change.
2. Natural turns cover ordered gaps; a type-specific near-miss stays not ready.
3. Ready remains unconfirmed; a distinct explicit latest user turn completes.
4. First completion is changed:true without lifecycle change; replay is
   changed:false with the same path/revision/introducing commit.
5. Completion alone compiles no page. Separate canonical automatic eligibility
   or owner graduation then yields a cited non-placeholder page for every type.
6. Injection is inert; concurrent rename/graduate/never/delete fails before
   write; same-revision contention converges; different bytes conflict.

It prints compact JSON and exits nonzero unless every row passes. It never uses
a private vault, real remote, production verdict, viewer, or screenshots.

## Definition of done

- [ ] Contract remains first commit; implementation follows on this draft only
      after #175 merges and this branch rebases to v184.
- [ ] entity_candidate is independently registered, auditable, versioned,
      evaluable, seatable, and exact-composes Conversation 1.0.0.
- [ ] Play/start is zero-write; completion uses only v183's source/Git authority
      and never graduates or approves.
- [ ] Seven-gap rubric, five type rules, exact grounding, explicit confirmation,
      and lifecycle/revision/injection/replay/concurrency boundaries pass.
- [ ] Automatic graduation/direct verdict behavior and ordinary
      Conversation/Question/Focus bytes are unchanged from v184.
- [ ] Scoped gates/walkthrough and exact-SHA GitHub CI pass.
- [ ] system/version.json is v185 with complete manifest/changelog; ADR 0022,
      handbook, CLAUDE, and research methodology are current.
- [ ] Exact-SHA evidence and Owner closeout are posted. Implementer does not
      touch labels, mark ready, merge, tag, close #172/#517, or wire platform.

## Owner closeout template

### Look

1. Read docs/handbook/interactions/entity-candidate.md.
2. Run python3 tests/walkthrough_entity_candidate.py and confirm zero-write
   starts, five type paths, explicit confirmation, replay, pending lifecycle,
   stale refusal, and pages only after separate graduation.
3. Run python3 system/lifehug.py entity-candidate-evals --json and confirm every
   gate, including per-type false-positive rate 0.0.

### Judge

1. **Seven-gap usefulness — yes/no?** Yes ratifies identity/disambiguation;
   relationship/relevance/significance; timeline; connections; tension/open
   question; type context; and concrete evidence as useful day-one material.
2. **Five type rules — yes/no?** Yes ratifies the type meanings and theme's
   two-manifestation minimum.
3. **Exact-excerpt confirmation — yes/no?** Yes requires a distinct user act
   before immutable source completion.
4. **Research separate from graduation — yes/no?** Yes preserves the automatic
   floor and owner graduate/never accelerator/veto unchanged.

### Done when

Owner approval queues this draft after exact-SHA CI. Merge publishes v185
through normal release flow; it does not tag from an agent or wire hosted
Review. Platform #517 must pin exact v185/SHA and add its own transport/evidence.

🤖 Generated with GPT-5.6-Sol via Codex
