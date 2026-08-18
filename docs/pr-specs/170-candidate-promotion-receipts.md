# Contract: candidate promotion receipts (issue #170, PR B of two)

## Why

Question Candidate PR A (v181, ADR 0018) made candidate answering and placement
an independent Interaction, but deliberately left promotion on the legacy
write path. That path returns display text, allocates a question id from a
projected read, and has three separate mutation implementations (manual,
weekly auto-promotion, and neighborhood promotion). Hosted Answer Now cannot
safely file a pending answer through that seam: a Git mutation may already be
durable while the candidates or question-bank projections are stale. PR B
closes lifehug/lifehug#170 and supplies the upstream receipt authority required
by lifehug/lifehug-platform#469 and #510.

This is **In the Loop**. Every candidate-to-question transition, including the
weekly autonomous path, must cross this authority before the question can
enter planning or answer filing.

## Binding facts

### Release and boundaries

- Base is the v181 annotated tag / merge
  `bb7ff387624bc9624acdbecff287bfd4c68bf1b2`.
- This PR lands as v182 and adds ADR 0019.
- `system/candidate_promotion.py` is the one canonical promotion mutation and
  receipt authority. `system/question_candidates.py` retains scoring, review,
  and candidate-store compatibility helpers, but manual promotion,
  `auto_promote_candidates()`, and `promote_neighborhood()` may not allocate,
  render, write, commit, or adopt promoted questions independently.
- The v181 `interactions/question_candidate/` package, registry, schemas,
  prompts, and eval contract remain independent and byte-identical. Ordinary
  Conversation definition/rendered bytes remain v180-identical. PR B adds no
  model capability and gives no model a Git or vault-write tool.
- No platform code, Firestore state, pending-answer filing, UI, projection
  polling, or release pin is in scope. The platform consumes the v182 contract
  after merge/tag.
- Fixtures use disposable synthetic vaults only. Tests and evidence must never
  access or name a private user vault.

### Canonical request

The exact `CandidatePromotionRequest` schema is a dict with no unknown or
missing keys:

```json
{
  "schema_version": 1,
  "candidate_id": "cand-synthetic-1",
  "category_id": "A",
  "source_revision": "sha256:<64 lowercase hex>",
  "candidate_revision": "sha256:<64 lowercase hex>",
  "category_revision": "sha256:<64 lowercase hex>",
  "placement_revision": "sha256:<64 lowercase hex>",
  "proposal_revision": null,
  "decision_revision": null
}
```

- Revisions use `question_candidate.canonical_revision`: canonical UTF-8 JSON,
  sorted keys, compact separators, Unicode preserved.
- `source_revision` binds the candidate's immutable source provenance fields;
  `candidate_revision` binds candidate id, exact question text, and that source
  revision using the v181 `CandidateAnchor` contract.
- `category_revision` binds the exact current question-bank category entry
  `{category_id,label,group,qualifier,focus_id,focus_label}`. The local bank has
  null focus fields when it carries no separate focus mapping.
- `placement_revision` binds candidate revision, category id, and category
  revision exactly as v181 placement does.
- `proposal_revision` and `decision_revision` are nullable canonical hashes.
  Manual, weekly-auto, and neighborhood promotion use null because no Question
  Candidate proposal/decision occurred. Answer Now supplies hashes of the
  exact untrusted proposal and validated decision; full conversation text is
  never written into the bank marker.
- A supplied Question Candidate decision must revalidate against the current
  candidate/category roster, be `complete`/`answered`, have a durable answer,
  and name this exact category. A model proposal alone never authorizes a
  mutation.
- The public builder computes this request from current candidate and bank
  authority. The resolver accepts a caller-held request and compares every
  revision to fresh state under the writer lease before a new mutation.

### Canonical marker and provenance

Each newly promoted bank question is immediately followed by exactly one
marker:

```text
  <!-- lifehug:candidate-promotion:v1 <standard-base64 canonical JSON> -->
```

The decoded marker payload has exact keys:

```json
{
  "schema_version": 1,
  "candidate_id": "cand-synthetic-1",
  "category_id": "A",
  "question_id": "A3",
  "question_revision": "sha256:<64 lowercase hex>",
  "promoted_at": "UTC RFC3339 seconds",
  "candidate_provenance": {
    "source_revision": "sha256:<64 lowercase hex>",
    "candidate_revision": "sha256:<64 lowercase hex>",
    "category_revision": "sha256:<64 lowercase hex>",
    "placement_revision": "sha256:<64 lowercase hex>",
    "proposal_revision": null,
    "decision_revision": null,
    "request_revision": "sha256:<64 lowercase hex>"
  }
}
```

- Standard base64 is used so arbitrary candidate/source strings can never
  terminate an HTML comment. The decoded JSON is the structured audit record;
  the bank never trusts or executes it.
- `request_revision` hashes the exact request. `question_revision` binds the
  allocated id and exact inserted question text. Adoption verifies the marker,
  its immediately preceding unchecked bank line, category/id relationship,
  and both revisions before returning anything.
- One candidate id may have one canonical marker. A marker for the same exact
  request is replay; any different category, question bytes, or request facts
  is a conflict. Existing equal text without this provenance is never adopted.

### Receipt

The exact `CandidatePromotionReceipt` schema is:

```json
{
  "candidate_id": "cand-synthetic-1",
  "category_id": "A",
  "question_id": "A3",
  "changed": true,
  "commit_sha": "<40 lowercase Git hex>",
  "candidate_provenance": {
    "source_revision": "sha256:<64 lowercase hex>",
    "candidate_revision": "sha256:<64 lowercase hex>",
    "category_revision": "sha256:<64 lowercase hex>",
    "placement_revision": "sha256:<64 lowercase hex>",
    "proposal_revision": null,
    "decision_revision": null,
    "request_revision": "sha256:<64 lowercase hex>"
  }
}
```

- First durable mutation returns `changed: true`. Replay/adoption returns
  `changed: false`; every other receipt field is identical. JSON output uses
  sorted keys and compact separators for deterministic bytes.
- `commit_sha` is the reachable Git commit that first introduced the exact
  marker, found from canonical Git tree/history rather than
  `state/question_candidates.json` or any projected read model. A later commit
  or projection refresh does not replace it.
- The receipt is returned only after the commit exists and, when `push=True`,
  its current rebased form is pushed successfully. A local-only/test run uses
  `push=False` but still creates and returns a real commit SHA.
- No separate receipt ledger is authoritative. The bank line + marker + Git
  history are sufficient to reconstruct the receipt after a crash following
  file write, commit, rebase, or push.

### Mutation and concurrency semantics

- The authority uses the existing vault-root/path contract and the same
  kernel-backed writer lease as every canonical mutator. If the caller already
  holds a live writer token, it does not nest the lease; direct module/CLI use
  acquires it itself.
- With `push=True`, pull/rebase happens before reading decision state. A pull,
  rebase, commit, history-resolution, or push ambiguity fails closed and never
  fabricates a receipt. Push rejection may pull/rebase and retry only after the
  exact marker/request/question are revalidated.
- Two same-request contenders serialize: one writes; the other adopts and
  returns `changed:false`. Two different candidates in one category allocate
  distinct ids. Same candidate with changed text/category/revisions conflicts.
- Writes to the bank and candidate projection use atomic file replacement
  under the lease. The Git commit names only the bank and candidate-store
  paths (`git commit --only -- ...`), so unrelated staged/unstaged vault work
  is neither swallowed nor erased.
- The candidate-store row is a projection of the canonical marker. New manual
  and neighborhood rows retain status `promoted`; weekly rows retain
  `auto_promoted`, score, reason, and `promoted_by:auto`. Every row records the
  canonical question id, category, promotion time, and request revision.
  The row cannot contain the commit that writes itself; commit SHA is derived
  from Git history for the receipt. Adoption does not require that projection
  to exist or be fresh.
- A crash after the bank write but before projection/commit completes the same
  marker transaction on replay. A crash after commit or push adopts the exact
  marker and reconstructs the original receipt without inserting a duplicate.
- Existing legacy `promote_candidate_record()` remains only as a pure
  compatibility wrapper over the canonical planner for tests/importers. A
  static recurring-defect guard rejects question-id allocation, promotion
  marker rendering, and promotion-state writes outside
  `candidate_promotion.py`.

### Public APIs and CLI

`system/candidate_promotion.py` exposes:

```python
build_candidate_promotion_request(
    candidate: dict,
    question_bank_text: str,
    category_id: str,
    *,
    proposal: object | None = None,
    decision: dict | None = None,
) -> dict

validate_candidate_promotion_request(
    request: dict,
    candidate: dict,
    question_bank_text: str,
    *,
    decision: dict | None = None,
) -> dict

resolve_candidate_promotion(
    request: dict,
    *,
    vault_root: str | Path | None = None,
    promotion_mode: str = "manual",
    push: bool = True,
    failpoint: Callable[[str], None] | None = None,
) -> dict

resolve_candidate_promotions(
    requests: list[dict],
    *,
    vault_root: str | Path | None = None,
    promotion_mode: str = "neighborhood",
    push: bool = True,
) -> list[dict]
```

The final resolver door is:

```text
python3 system/lifehug.py candidates-promotion-receipt \
  <candidate-id> --category <id> \
  --candidate-revision <sha256:...> \
  --category-revision <sha256:...> \
  --placement-revision <sha256:...> \
  [--source-revision <sha256:...>] \
  [--proposal-revision <sha256:...>] \
  [--decision-revision <sha256:...>] --json
```

- The CLI builds an exact closed request, requires JSON mode, runs the resolver,
  and prints exactly one compact receipt object to stdout. Diagnostics go to
  stderr. `--no-push` exists only on `system/candidate_promotion.py`'s direct
  test/development CLI, not the stable `lifehug.py` door.
- `source_revision` may be omitted only for backward-compatible local callers;
  the resolver then requires it to equal the fresh canonical candidate source
  revision and fills it before request hashing. All other three placement
  revisions are mandatory at the final receipt door.
- Existing `candidates-promote <id> --category <id>` remains backward
  compatible and delegates after building a fresh exact request. Its human
  output includes the canonical qid and commit SHA. Jobs route it through the
  idempotent authority and `candidate-promote` becomes retry-safe.
- Auto and neighborhood commands retain their current summaries and dry-run
  semantics. Dry-run performs zero writes, commits, pulls, or pushes.

## Scope

In scope:

- Canonical request/marker/receipt schemas and runtime validation.
- One authority for manual, viewer/job, weekly-auto, and neighborhood paths.
- Writer serialization, Git commit/push/rebase/adoption, crash recovery, and
  provenance-only dedupe.
- v182 version/manifest/changelog, ADR 0019, candidate handbook and operator
  docs, wrapper/job registration, and focused gates.

Out of scope:

- Platform coordinator/session/pending-capture/file-answer implementation.
- Changing Question Candidate placement behavior or seating.
- Promoting merely because Play/Answer Now started; promotion occurs only when
  an authorized caller invokes this resolver with current facts.
- Rewriting legacy markers or guessing receipts for legacy promotions.
- A durable receipt projection/ledger; the Git tree is authority.
- Viewer changes or screenshots/walkthroughs (no `serve_wiki.py` change).

## Implementation notes

- Move/reuse category existence, next-id, duplicate, insertion, and candidate
  projection logic behind `candidate_promotion.py`; do not leave a second
  renderer in `question_candidates.py`.
- Use `question_candidate.canonical_revision`, `build_candidate_anchor`,
  `build_category_roster`, and decision revalidation rather than recreating
  v181 hash/placement rules.
- Category discovery remains `lifehug_core.parse_categories`; question parsing
  remains `parse_questions`. Question ids retain the existing category-letter
  allocation rules and `format_frameworks` compatibility.
- The marker parser is closed, size-bounded, strict base64/UTF-8/JSON, and
  rejects duplicate markers, unknown keys, invalid revisions, non-canonical
  encoding, or line/marker mismatch.
- Git subprocesses use argument arrays, the selected vault as `cwd`, bounded
  captured output, no shell, no force push, and no destructive reset/checkout.
  A rebase begun by this command is aborted on its own conflict before erroring.
- The failpoint seam names at least `after_bank_write`,
  `after_projection_write`, `after_commit`, and `after_push`; production passes
  none. Tests use it only in disposable repos.

## Test plan

Add `tests/test_candidate_promotion.py` with named state-machine cases:

- exact request/revision schema; malformed/unknown fields and stale candidate,
  category, placement, proposal, and decision facts fail closed;
- complete Question Candidate decision accepted; incomplete/wrong-category
  decision refused;
- canonical marker round-trip, comment-injection resistance, strict parsing,
  exact line/question revision, and legacy equal-text non-adoption;
- first mutation receipt, second replay `changed:false`, all other receipt
  fields identical, one bank question, and one marker;
- crash after bank write, projection write, commit, and push each recover the
  same qid/provenance/commit without duplication or projection dependency;
- conflicting question bytes, category, candidate/category/placement revision,
  proposal revision, and decision revision fail closed;
- concurrent same-request race produces one question/commit identity; two
  distinct candidates in one category produce distinct qids;
- unrelated staged/unstaged files survive and are absent from the promotion
  commit; push rejection/rebase revalidates or fails closed;
- compact final CLI receipt and error-channel behavior;
- all manual/auto/neighborhood paths use the authority, preserve their status
  and summaries, and the recurring-defect source scan finds no bypass.

Update scoped compatibility tests in:

- `tests/test_ingest_and_planner.py`
- `tests/test_unified_quality_score.py`
- `tests/test_lifehug_wrapper.py`
- `tests/test_v101_actions.py`
- `tests/test_v119_jobs.py`

Exact local gates (no broad full suite while sibling agents share the host):

```bash
python3 -m unittest \
  tests.test_candidate_promotion \
  tests.test_ingest_and_planner \
  tests.test_unified_quality_score \
  tests.test_lifehug_wrapper \
  tests.test_v16_focus_skill \
  tests.test_v101_actions \
  tests.test_v119_jobs \
  tests.test_question_candidate \
  tests.test_question_candidate_evals \
  tests.test_interaction_registry \
  tests.test_v150_conversation_store.NoBehaviorChangeGuardTests -v
python3 system/lifehug.py question-candidate-evals
python3 system/lifehug.py conversation-evals
python3 scripts/ci/check_framework_files.py
python3 scripts/ci/check_version_bump.py --base bb7ff387 --head HEAD
python3 -m compileall -q system tests
ruff check --select E4,E7,E9,F,I,UP,B --ignore E402 \
  system/candidate_promotion.py system/question_candidates.py system/lifehug.py \
  system/jobs.py system/roadmap.py tests/test_candidate_promotion.py
# Legacy modules predate the formatter baseline; format only new v182 files.
ruff format --check system/candidate_promotion.py tests/test_candidate_promotion.py
git diff --check
```

GitHub CI is authoritative for the full Python 3.11/3.14 matrix.

## Launch-and-verify

Not required: PR B does not change `serve_wiki.py` or another visible viewer
surface. The executable review surface is the synthetic-vault CLI test and the
compact receipt command above.

## Owner closeout template

### Look

1. Run the synthetic first-promotion CLI fixture and inspect the compact receipt
   plus the decoded bank marker.
2. Replay the exact request and confirm `changed:false`, the same qid/commit/
   provenance, and one bank entry.
3. Run the crash-adoption and concurrency subtests and inspect their explicit
   one-question assertions.

### Judge

1. **Git tree as receipt authority — yes/no?** Yes ratifies bank marker + Git
   history instead of a projected receipt ledger.
2. **One commit per promotion resolver transaction — yes/no?** Yes ratifies the
   crash-recovery boundary for manual, auto, and neighborhood paths.
3. **Hash-only proposal/decision binding — yes/no?** Yes keeps private answer
   text out of the question bank while binding the exact objects.
4. **Legacy non-adoption — yes/no?** Yes refuses text-matched guesses for
   pre-v182 promotions without the structured marker.

### Done when

Approval merges PR B, triggers the normal v182 tag, and unblocks the platform
pin/parity PR. It does not close platform #469/#510 or implement their saga.

## Definition of done

- [ ] Contract is the first commit on the PR B branch and the draft PR exists
      before implementation commits.
- [ ] Canonical authority, all callsite rewiring, schemas, marker, receipt,
      concurrency, Git recovery, and bypass guard are implemented.
- [ ] Scoped gates above and exact-SHA GitHub CI are green.
- [ ] `system/version.json` is v182 with a user-visible changelog and every new
      distributable file in `framework_files`.
- [ ] ADR 0019, CLAUDE.md, `system/research.md`, and
      `docs/handbook/question-candidates.md` describe the shipped authority.
- [ ] PR evidence and the self-contained Owner closeout are current.
- [ ] Issue #170 receives implementation evidence but is not closed by the
      implementing agent.
- [ ] PR remains draft; implementing agent does not touch labels, readiness,
      merge, or tags.

🤖 Generated with GPT-5.6-Sol via Codex
