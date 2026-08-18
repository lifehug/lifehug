# Contract: generic candidate-research source authority (issue #172)

## Why

Issue #172 adds `focus_candidate` and `entity_candidate` as independently
registered Interactions, but both need the same durable boundary before either
prompt package is safe to build: exact user-grounded evidence must become one
immutable, compiler-recognized source without letting a model summary become
evidence, letting candidate churn redirect the source, or creating another Git
writer beside issue #170 PR B. This PR supplies that generic source authority
first. It is **In the Loop**: a completed research exchange becomes citable
source material that the compiler consumes after the candidate is separately
approved or graduated.

## Binding facts

### Dependency train and release

- The branch starts from the v181 annotated tag / merge
  `bb7ff387624bc9624acdbecff287bfd4c68bf1b2`.
- PR #173 is the v182 dependency. Its checked-in contract owns the first
  canonical writer-lease, pull/rebase, exact-path commit, push, and Git-tree
  adoption authority for candidate promotion. This PR must rebase onto the
  merged v182 release and lands as v183.
- Until v182 lands, this branch implements and verifies the dependency-free
  evidence, assessment, rendering, marker, manifest, compiler, and adoption
  validation surfaces. It does **not** copy PR #173's private Git/lease helpers,
  acquire a second/nested writer, or claim the final mutation gate is green.
- The contract-first and dependency-free implementation SHAs intentionally
  remain red only on the version-bump/dependency gate: `system/version.json`
  stays v181 until the v182 rebase. A synthetic v183 bump before that rebase
  would hide the dependency and is forbidden.
- After the v182 rebase, the final implementation wires the exact adapter in
  this contract to the canonical Git authority, bumps v182 to v183, adds ADR
  0020, and runs the full scoped gates against the rebased SHA.
- `interactions/focus_candidate/` and `interactions/entity_candidate/`, their
  prompts, manifests, registration, runtime binding, routers, model evals, and
  seat decisions are out of scope. This PR gives them one frozen source API to
  consume later.
- Conversation and Question Candidate are behavioral dependencies, not edit
  surfaces. All files under `interactions/conversation/` and
  `interactions/question_candidate/`, plus `system/conversation.py`,
  `system/conversation_lints.py`, `system/question_candidate.py`, and
  `system/question_candidate_evals.py`, remain byte-identical to v181.

### Closed subject authority

`system/candidate_research.py` is the one schema, recomputation, renderer,
marker, and receipt authority. It recognizes exactly two research kinds:

```text
focus_candidate
entity_candidate
```

The closed subject-type roster is:

```text
focus_candidate:  person | place | period | theme
entity_candidate: person | place | period | object | theme
```

Relationship edges, projects, the primary life story, arbitrary strings, and
unknown future values fail closed until this contract is deliberately revised.

`CandidateResearchSubject` is exact-keyed:

```json
{
  "schema_version": 1,
  "candidate_kind": "focus_candidate",
  "candidate_id": "rec-synthetic-harbor",
  "subject_type": "place",
  "subject_label": "Synthetic Harbor",
  "subject_slug": "synthetic-harbor",
  "subject_aliases": [],
  "candidate_state": "active",
  "identity_revision": "sha256:<64 lowercase hex>",
  "subject_revision": "sha256:<64 lowercase hex>"
}
```

- `identity_revision` hashes exactly candidate kind/id, subject type, exact
  label, exact slug, and ordered aliases using
  `question_candidate.canonical_revision`.
- `subject_revision` hashes the identity revision plus the canonical candidate
  state facts that determine whether the row is still researchable. Score-only
  refreshes do not stale research; rename, alias, type, mapping, verdict, or
  lifecycle churn does.
- `candidate_id` is an opaque non-empty identifier, never a path component.
  Focus rows use their exact recommendation id. Entity rows use the exact
  deterministic id `entity:<type>:<slug>`.
- `build_focus_candidate_subject(recommendation)` accepts the current closed
  recommendation shape. Only `status: pending` is `active`; approved is
  `consumed`; dismissed/expired is `tombstoned`.
- `build_entity_candidate_subject(entity_type, roster_entry)` accepts one
  current settled-roster entry. It is `active` only while it is unmapped,
  not page-eligible, and has no `never`/`graduate` owner verdict. A `never`
  verdict is `tombstoned`; page eligibility, mapping, or `graduate` is
  `consumed`.
- New assessment/source completion requires `candidate_state: active` and an
  exact match to a freshly rebuilt subject. A missing row is a tombstone and
  fails closed. An already-committed exact source remains immutable source
  truth after later candidate deletion/consumption; candidate cleanup never
  deletes it. Retraction/correction uses the existing additive source contract.

### Authoritative user turns and exact evidence

The runtime may give this module only authoritative raw user turns, never an
assistant message, transcript summary, classifier synthesis, or generated
context block:

```json
{
  "schema_version": 1,
  "turn_id": "turn-synthetic-2",
  "role": "user",
  "text": "I went back to the harbor after the storm.",
  "turn_revision": "sha256:<64 lowercase hex>"
}
```

- `turn_revision` hashes exact `turn_id`, literal `role: user`, and exact UTF-8
  text. No trimming, Unicode normalization, whitespace folding, or paraphrase
  is allowed.
- Turn ids are bounded portable ids (`[A-Za-z0-9._:-]`, 1–256 characters).
  Text is non-empty and at most 100,000 Unicode code points.
- Assistant/model turns are rejected, not silently skipped. A caller that has
  only a summary has no evidence and therefore cannot complete research.

`ResearchEvidenceSpan` is exact-keyed:

```json
{
  "schema_version": 1,
  "turn_id": "turn-synthetic-2",
  "turn_revision": "sha256:<64 lowercase hex>",
  "start": 0,
  "end": 42,
  "quote": "I went back to the harbor after the storm.",
  "evidence_kind": "concrete_event",
  "evidence_revision": "sha256:<64 lowercase hex>"
}
```

- Offsets are zero-based Python/Unicode-code-point half-open offsets `[start,
  end)`. Booleans are not integers. `quote` must equal the exact slice of the
  exact revision-matched raw user turn.
- `evidence_kind` is one of `statement|concrete_event|
  concrete_observation|confirmation`. Confirmation spans are separate from
  substantive evidence and cannot satisfy a research dimension or minimum.
- `evidence_revision` hashes the other six span facts exactly. No span may be
  empty, duplicated, or overlap another evidence span from the same turn.
- A substantive span has at least 24 non-whitespace characters and at least
  four Unicode word tokens. This mechanical threshold is only the floor;
  later Interaction evals must still prove semantic evidence correctness.
- `extract_research_evidence_span(turn, start, end, evidence_kind)` is the
  builder. `validate_research_evidence_span(span, authoritative_turns)`
  always recomputes the slice and revision.

### Assessment and readiness recomputation

`ResearchAssessment` is a strict object containing:

```json
{
  "schema_version": 1,
  "subject": {"...": "CandidateResearchSubject"},
  "evidence": [{"...": "ResearchEvidenceSpan"}],
  "dimension_evidence": {"identity": ["sha256:..."]},
  "seed_questions": [
    {"question": "What changed the next time you returned?", "evidence": false}
  ],
  "readiness": {
    "ready": false,
    "missing": ["dimension:why_it_matters"],
    "substantive_evidence_count": 2,
    "concrete_evidence_count": 1,
    "seed_question_count": 1
  },
  "assessment_revision": "sha256:<64 lowercase hex>",
  "confirmation": null,
  "complete": false,
  "research_revision": "sha256:<64 lowercase hex>"
}
```

Focus research has exactly these dimension keys:

```text
identity | why_it_matters | scope_boundary | present_state_or_direction |
relationships | tensions | open_questions
```

Entity research has exactly these dimension keys:

```text
identity_or_disambiguation | relevance_or_relationship | history |
connections | tension_or_open_question | type_specific_context
```

- Every dimension value is a non-empty ordered list of evidence revisions.
  Every reference must name an exact validated substantive span. Every
  substantive span must support at least one dimension. Unknown/missing
  dimensions or references fail closed.
- Focus readiness requires all seven dimensions, at least three distinct
  non-overlapping substantive spans, at least one
  `concrete_event|concrete_observation`, and at least two seed questions.
- Entity readiness requires all six dimensions, one concrete event/observation,
  and at least two substantive spans for person/object or three for
  place/period/theme.
- Seed questions are exact objects with non-empty question text (at most 1,000
  characters) and the literal boolean `evidence: false`. Focus assessments
  require 2–8. Entity assessments permit 0–8. They are rendered under an
  explicit **Generated seed questions — not evidence** heading and never enter
  evidence counts, dimensions, or citable claim blocks.
- `recompute_research_assessment(...)` derives readiness and sorted missing
  codes from exact subject/evidence/dimension/question facts. A supplied
  readiness object must equal recomputation byte-for-byte.
- `assessment_revision` hashes subject, evidence, dimension mapping, seed
  questions, and recomputed readiness. A model cannot assert readiness.

User confirmation is a separate exact-keyed object:

```json
{
  "status": "confirmed",
  "assessment_revision": "sha256:<64 lowercase hex>",
  "evidence": {"...": "ResearchEvidenceSpan(kind=confirmation)"},
  "confirmed_at": "UTC RFC3339 seconds",
  "confirmation_revision": "sha256:<64 lowercase hex>"
}
```

- Confirmation must bind this exact ready assessment revision and an exact
  `confirmation` span from a later or same authoritative user turn. The caller
  supplies the explicit `confirmed` action; neither a model proposal nor
  positive sentiment can manufacture it.
- `confirmation_revision` hashes status, assessment revision, exact span, and
  timestamp. `complete` is true only when recomputed readiness is true and the
  confirmation is valid.
- `research_revision` hashes the exact assessment revision plus the exact
  confirmation object (or null). The writer accepts only complete research.
  Any turn, evidence, dimension, question, subject, or confirmation change
  produces a different deterministic revision.

### Immutable source bytes and marker

`build_candidate_research_source(assessment)` accepts only a freshly validated,
complete assessment and returns a strict `CandidateResearchSourcePlan` with
exact `source_path`, `source_id`, UTF-8 `source_bytes`, metadata, manifest
fields, marker line, and research revision.

The path is derived from identity, never untrusted text:

```text
sources/candidate-research/<focus_candidate|entity_candidate>/
  <first-32-hex-of-sha256(candidate_kind NUL candidate_id)>.md
```

Absolute paths, traversal, normalization aliases, symlinks, unexpected
directories, alternate extensions, and caller-selected paths are rejected.
One candidate identity has one stable source path even if its label later
changes; reusing an id for different bytes is a conflict, not a second source.

Frontmatter uses source schema v1 and includes the normal required source
fields plus these typed fields:

```text
type: candidate_research
source_trust: user_attested_primary
authority: first_person_memory
candidate_kind
candidate_id
subject_type
subject_label
subject_slug
subject_aliases
identity_revision
subject_revision
assessment_revision
research_revision
user_confirmed: true
evidence_span_count
generated_seed_questions_evidence: false
```

`source_id` is
`candidate-research:<candidate_kind>:<64-hex-identity-digest>`. `captured_at`
is the confirmation timestamp. `visibility: owner_only`, `status: raw`, and
`immutable: true` are fixed. `content_sha256` is the existing
`source_integrity.payload_sha256()` of the exact rendered body.

The body begins with exactly one closed, standard-base64 marker:

```text
<!-- lifehug:candidate-research:v1 <standard-base64 canonical JSON> -->
```

The decoded payload has exact keys:

```json
{
  "schema_version": 1,
  "candidate_kind": "focus_candidate",
  "candidate_id": "rec-synthetic-harbor",
  "identity_revision": "sha256:...",
  "subject_revision": "sha256:...",
  "assessment_revision": "sha256:...",
  "research_revision": "sha256:...",
  "source_id": "candidate-research:focus_candidate:<digest>",
  "source_path": "sources/candidate-research/focus_candidate/<digest32>.md"
}
```

Standard base64 prevents comment termination by user text. Parsing is strict,
size-bounded, canonical, and rejects unknown keys, duplicate markers, malformed
UTF-8/JSON/base64, non-canonical encoding, path mismatch, or revision mismatch.
The body contains only exact evidence quotes in indented literal blocks plus
generated seed questions in the explicitly non-evidence section. It contains
no model-authored summary, inferred fact, approval claim, graduation claim, or
candidate status mutation.

### Typed manifest and source integrity

- Add `candidate_research_sources` at `sources/candidate-research` to
  `system/vault_contract.json` as a tracked schema-v1 Markdown family.
- `source_integrity.source_record()` and `sync_manifest()` retain the typed
  candidate-research fields above in `state/source_manifest.json` rather than
  reducing the record to generic title/type fields.
- Lint validates the exact path family, marker/frontmatter parity, fixed trust,
  authority, immutable/status/visibility values, payload hash, evidence count,
  confirmation, and research revision. A candidate-research source without its
  typed manifest fields is an error; safe `--fix` may rebuild the manifest but
  never rewrite research body/frontmatter.
- Existing correction/retraction machinery applies. A later correction is a
  separate source; the candidate-research file remains byte-immutable.

### Compiler consumption contract

`wiki_compile.read_manual_sources()` retains the typed research metadata and
routes sources by metadata, never by model summary or path guessing.

- A completed `focus_candidate` research source attaches to a later Focus only
  when its typed subject slug/label/aliases exactly match that Focus through
  the existing normalized identity authority. It is primary/citable source
  material. A Focus with no dedicated answers but with this research source
  may not render the current "no source material yet" placeholder.
- A completed `entity_candidate` research source attaches to the matching
  settled roster identity by exact type and subject slug/name/alias. Once that
  entity separately becomes page-eligible, the research source satisfies the
  real-material floor and is cited for every supported type: person, place,
  period, object, and theme. It never sets `page_eligible`, writes an owner
  verdict, changes `qualifies`, maps to a Focus, or bypasses roster identity.
- Typed research association is additive to ordinary real mentions. It does
  not change automatic graduation thresholds for candidates that lack a
  completed source.
- Corrections/retractions are applied through the existing compiler layer.
  A fully retracted research source cannot prevent a placeholder or satisfy an
  entity's material floor.

### Canonical mutation adapter and receipt

The dependency-free module freezes this protocol for v182 wiring:

```python
class CandidateResearchGitAuthority(Protocol):
    def resolve_exact_source(
        self,
        plan: dict,
        *,
        vault_root: str | Path | None = None,
        push: bool = True,
        failpoint: Callable[[str], None] | None = None,
    ) -> dict: ...
```

The adapter result is exact-keyed:

```json
{
  "source_path": "sources/candidate-research/focus_candidate/<digest32>.md",
  "changed": true,
  "commit_sha": "<40 lowercase Git hex>"
}
```

The final `resolve_candidate_research_source(...)` validates the plan, calls
only this canonical adapter, and returns:

```json
{
  "candidate_kind": "focus_candidate",
  "candidate_id": "rec-synthetic-harbor",
  "subject_type": "place",
  "source_id": "candidate-research:focus_candidate:<digest>",
  "source_path": "sources/candidate-research/focus_candidate/<digest32>.md",
  "research_revision": "sha256:<64 lowercase hex>",
  "content_sha256": "<64 lowercase hex>",
  "changed": true,
  "commit_sha": "<40 lowercase Git hex>"
}
```

- The adapter owns the one existing writer token/lease, pre-decision pull,
  atomic source+manifest writes, `git commit --only`, first-introducing-commit
  lookup, push/rebase retry, post-rebase revalidation, and failpoints. The
  research module may not acquire or nest a lease and may not shell out to Git.
- A same-path exact-byte replay adopts the marker/source from the canonical Git
  tree and returns `changed:false` with the original introducing commit. The
  manifest/projection may be missing or stale and is repaired from the source;
  it is never the adoption authority.
- The same candidate marker at another path, another marker at the canonical
  path, same marker with different bytes, different research revision, changed
  subject facts, or an unmarked equal-text file is a hard conflict. There is no
  label/text fuzzy adoption.
- A crash after source write but before commit completes the exact source+
  manifest transaction on replay. A crash after commit or push adopts from the
  canonical Git tree/marker and never duplicates the source.
- When `push=True`, no receipt exists until the exact current commit is pushed
  successfully. `push=False` is test/development-only but still returns a real
  commit SHA.
- If v182 does not expose this exact generic adapter after merge, v183 extracts
  it once into one shared authority used by both promotion and research. It
  must not leave two copies of writer, Git, rebase, or adoption logic.

## Scope

In scope:

- Strict subject, user-turn, evidence-span, assessment, confirmation,
  readiness, revision, source-plan, marker, manifest, and receipt schemas.
- Pure evidence extraction/revalidation and deterministic assessment
  recomputation.
- Immutable candidate-research rendering with generated questions visibly and
  structurally non-evidence.
- Safe path derivation, source-integrity/vault-contract integration, and typed
  manifest validation.
- Compiler attachment for later Focuses and all five entity types without
  changing approval/graduation state.
- Frozen v182 Git adapter plus final post-rebase integration, idempotency,
  conflict, crash-adoption, and concurrency gates.
- ADR 0020; source/Focus/entity handbook and central research methodology
  updates; v183 version/manifest/changelog.

Out of scope:

- `focus_candidate` or `entity_candidate` Interaction packages, prompts,
  context, routers, runtimes, live evals, model seats, or platform transport.
- Starting/resuming candidate conversations or storing their mutable session
  state.
- Focus approval, category scaffolding, starter-question promotion, entity
  `graduate|never` verdicts, page eligibility, or automatic roster mutation.
- Treating model summaries, assistant replies, classifier text, recommendation
  evidence snippets, or generated seed questions as evidence.
- Rewriting or deleting raw user turns; completed source corrections remain
  additive.
- Viewer/UI changes or screenshots. The later Interaction PRs own their visible
  review/play surfaces.

## Implementation notes

- Reuse `question_candidate.canonical_revision` rather than inventing another
  canonical JSON hash. Reuse `source_integrity.format_frontmatter`,
  `payload_sha256`, and the vault-path containment/no-follow authority.
- Keep `candidate_research.py` dependency-free beyond stdlib and existing
  framework modules. Runtime validation never imports prompt packages.
- Compiler identity matching must reuse the existing normalized Focus/entity
  identity authority; do not add another lowercase/slug/alias guess.
- Keep the source renderer pure: the same assessment produces byte-identical
  output on every machine and date. No `now()`, model call, filesystem read, or
  Git call occurs during render.
- Source-path and marker parsers accept only forward-slash repository-relative
  paths in the exact family above. All content size/count bounds are enforced
  before JSON/base64 allocation grows unbounded.
- The final adapter commits only the exact source and manifest paths. Unrelated
  staged/unstaged vault work survives and is absent from the commit.
- Synthetic fixtures only. Never read or name a private user vault.

## Test plan

Add `tests/test_candidate_research.py` with named cases for:

- closed focus/entity subject kinds/types, identity/state revision stability,
  score-only non-churn, rename/alias/type/status/mapping/verdict churn, missing
  row/tombstone/consumed refusal;
- exact user-turn revisions, Unicode code-point slicing, whitespace and Unicode
  non-normalization, assistant/summary rejection, overlap/duplicate/bounds and
  forged quote/revision rejection;
- strict dimension rosters/references, substantive thresholds, Focus 3-span /
  concrete / 2-question minimum, per-entity-type 2/3-span minima, deterministic
  missing codes, forged readiness and stale assessment rejection;
- exact confirmation binding, non-user/model confirmation refusal, completion
  boundary, deterministic assessment/confirmation/research revisions;
- deterministic safe path/source bytes, strict marker round-trip, comment/path
  injection resistance, exact frontmatter/payload hash, literal evidence, and
  generated-question non-evidence labeling;
- same-byte replay, different-byte/path/revision conflict, unmarked equal-text
  non-adoption, stale/missing manifest adoption, crash after write/commit/push,
  and same-subject two-contender convergence through a synthetic canonical
  adapter;
- final v182-backed disposable-Git integration after rebase, including one
  introducing commit, real commit SHA, unrelated-work preservation, lease
  reuse/no nesting, push/rebase revalidation, and first-commit adoption.

Extend:

- `tests/test_source_integrity.py`: typed manifest retention/lint, path/marker/
  hash parity, safe manifest repair, correction/retraction compatibility.
- `tests/test_wiki_compile.py`: completed Focus research replaces the empty
  placeholder; entity research becomes cited material for person/place/period/
  object/theme only after independent eligibility; wrong kind/type/identity and
  retracted research do not attach.
- `tests/test_vault_contract.py`: candidate-research path family and schema.
- `tests/test_v150_conversation_store.py`: v181 Conversation and Question
  Candidate byte-parity/no-behavior-change guard.
- `tests/test_handbook_parity.py`: closed types, evidence minima, and typed
  compiler/source constants where scalar parity annotations apply.

Exact dependency-free gates before the v182 rebase:

```bash
python3 -m unittest \
  tests.test_candidate_research \
  tests.test_source_integrity \
  tests.test_wiki_compile \
  tests.test_vault_contract \
  tests.test_handbook_parity \
  tests.test_question_candidate \
  tests.test_v150_conversation_store.NoBehaviorChangeGuardTests -v
python3 tests/walkthrough_candidate_research.py
python3 scripts/ci/check_framework_files.py
python3 -m compileall -q system tests
ruff check --select E4,E7,E9,F,I,UP,B --ignore E402 \
  system/candidate_research.py system/source_integrity.py system/wiki_compile.py \
  tests/test_candidate_research.py tests/walkthrough_candidate_research.py
ruff format --check \
  system/candidate_research.py tests/test_candidate_research.py \
  tests/walkthrough_candidate_research.py
git diff --check
```

The version-bump check is expected to fail before the dependency rebase and is
reported as such, never called green. After v182 merges, rebase and add:

```bash
python3 scripts/ci/check_version_bump.py --base <v182-merge-sha> --head HEAD
python3 -m unittest tests.test_candidate_promotion tests.test_candidate_research -v
```

GitHub CI is authoritative for the broad Python 3.11/3.14 matrix on the final
rebased v183 SHA.

## Launch-and-verify

No viewer code changes; screenshots/motion are not required. The committed
synthetic walkthrough is:

```bash
python3 tests/walkthrough_candidate_research.py
```

It creates only a disposable synthetic vault, builds a Focus assessment from
exact user spans, demonstrates not-ready then ready-but-unconfirmed then
confirmed completion, renders/registers the immutable source through the
synthetic canonical adapter, replays it with `changed:false`, compiles a later
synthetic Focus without an empty placeholder, then repeats entity consumption
for all five supported types. It prints a compact JSON results table and exits
nonzero unless every assertion passes. After the v182 rebase it also runs the
real local-only Git adapter in the disposable repo and asserts one introducing
commit/adopted receipt.

## Owner closeout template

### Look

1. Run `python3 tests/walkthrough_candidate_research.py`.
2. Inspect its one rendered synthetic source: all citable body text must be an
   exact user quote; generated seed questions must be under the non-evidence
   heading.
3. Confirm the first receipt says `changed:true`, replay says `changed:false`,
   both name the same path/research revision/commit, and the compiled Focus plus
   all five eligible entity types cite the source.

### Judge

1. **Exact spans, no summaries — yes/no?** Yes makes raw revision-bound user
   turn slices the only evidence and excludes every model-authored summary.
2. **User confirmation after readiness — yes/no?** Yes requires an explicit
   user-grounded confirmation bound to the exact ready assessment before any
   source write.
3. **One immutable source per candidate identity — yes/no?** Yes makes changed
   bytes/path/revision a hard conflict and keeps corrections additive.
4. **Research informs but never approves/graduates — yes/no?** Yes lets the
   compiler cite completed research only after the existing independent Focus
   or entity lifecycle reaches its normal downstream state.
5. **One shared Git authority with v182 — yes/no?** Yes forbids a second writer
   and ratifies Git tree + source marker, not projections, as receipt authority.

### Done when

Approval after the v182 rebase merges v183 and triggers the normal tag. That
unblocks the two separate Interaction implementation PRs, which must consume
this exact source contract and run their own prompt/eval/seat review. It does
not approve a Focus, graduate an entity, or close the hosted platform twin.

## Definition of done

- [ ] This contract is the first commit; the draft PR exists before code.
- [ ] Dependency-free schemas, validation, rendering, marker, source integrity,
      typed manifest, compiler consumption, synthetic adapter, and walkthrough
      are implemented and pass their scoped gates on v181.
- [ ] PR #173/v182 is merged; this branch is rebased; one shared writer/Git
      authority is wired without copied/nested lease logic.
- [ ] Final idempotency/conflict/crash/concurrency Git gates pass on the rebased
      SHA; exact-SHA GitHub CI is green.
- [ ] `system/version.json` is v183 with a user-visible changelog and every new
      framework file included after the v182 rebase, not before.
- [ ] ADR 0020, `system/research.md`, `system/source_contract.md`, CLAUDE.md,
      `docs/handbook/focuses.md`, and `docs/handbook/entities.md` describe the
      shipped boundary.
- [ ] Issue #172 receives exact-SHA evidence and the PR has a current Owner
      closeout; the implementing agent does not close the issue, mark ready,
      touch labels, merge, or tag.

🤖 Generated with GPT-5.6-Sol via Codex
