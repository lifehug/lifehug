# Archive Timeline Batch and Incremental Refresh

Generated with Codex. Owner-authorized 2026-09-16.

## Outcome

Build the best evidence-backed timeline from the whole existing source archive
in one logical pass, then update quickly when stories or landmark evidence
change. The hosted target is under one hour for approximately 500 sources,
including durable filing and publication. This is a benchmark target, not a
claim established by a pure-calculation benchmark.

The framework already calculates 1,591 synthetic timeline nodes in about 0.4s.
Keep that engine, interval semantics, identities, provenance, and owner authority.
The expensive work to reduce is repeated model interpretation and per-source
hosted transactions. No private data in fixtures or tests.

## Binding Facts

- Base v302, main a6dc7482475ddfb97221be3fb5e8cb2708fe1007.
- `classifier_context` tracks source/version/relevant-context freshness and
  excludes classifier-only nodes from independently grounded landmark context.
  Preserve those guarantees; do not invent an all-history invalidation loop.
- `classify_file` and `--from-response` own validation/persistence. Batch and
  single-source modes must share their preparation/application logic.
- Current classification emits themes, insights, and questions even for a
  context-only timeline refresh. Preserve existing non-temporal results when
  their source/version remains current; do not regenerate or erase them merely
  to update events.
- Raw sources are immutable. Use existing correction, identity manifest,
  migration, temporal claims, and publication mechanisms.

## Required Canonical Interface

Extend `classify-story`, with the same flags exposed by `system/lifehug.py`:

1. `--batch-plan` prints ONE JSON object, no prose, holding the bounded set of
   sources needing work, their canonical snapshot, `mode`, and emitted prompt.
   Default limit 50, explicit maximum 500; optional `--sources-json PATH` selects
   an explicit bounded source list. The document is private transport data, not
   a logging artifact. Target selection remains canonical, includes all source
   kinds accepted by current classification, excludes corrections themselves,
   rejects paths escaping the vault/symlinks, and shares one loaded catalog.
2. `--from-batch-response PATH` consumes `{schema_version: 1, batch_id: SLUG,
   items: [{source_path: STRING, mode: 'full'|'timeline', response_text: STRING}]}`.
   Maximum 500 items with explicit size/path validation and no duplicate source
   targets. The framework alone parses and validates model bytes. Validate all
   items against ONE fresh catalog before applying valid items; refusal of one
   item is reported separately and must not erase valid siblings or old data.
3. Return a content-free structured batch report with source paths, accepted /
   refused / already-current statuses, typed refusal codes, and counts. No
   prompts, quotes, model bodies, or dates in the report. Preserve a durable,
   deterministic receipt at an appropriate existing report location or explicitly
   contracted state location so an adopted host commit can recover its exact
   per-source outcomes. Decide and document the exact path before host wiring.
4. A repeat of a previously accepted identical batch is a semantic no-op.
   Changed bodies under an existing batch identity must fail closed, not adopt
   the wrong report. Batch receipt binds all input identities/digests. Replay
   after source/context changes must not overwrite newer interpretations.

Plan shape: `{schema_version: 1, selected_count, pending_count, remaining_count,
items: [{source_path, reason, mode, snapshot, prompt}]}`. `snapshot` retains the
existing four keys. Pending covers the whole eligible inventory, not only the
selected slice. `remaining_count` is not a claim of full archive completion.
Before changing these interface names, notify the parent; platform builds against
them. No hosted behavior belongs in this repository.

## Timeline-Only Refresh

Use `mode: timeline` only when an existing non-stale classification is proven
to belong to unchanged source bytes and a compatible extraction contract. If
that cannot be proven (including legacy records without trustworthy snapshots),
select `full`. Prompt and response modes must be explicitly bound and validated.

Timeline mode asks for event evidence and relationships, not new follow-up
questions, themes, insights, or sensitivity guesses. It rereads source evidence
and relevant canonical context, preserves all other classification fields and
candidate IDs, and retains the existing human decisions and event identity
mechanisms. Filing refuses a changed base classification/source rather than
merging into an unrelated newer reading. It must not make a content-stale
classification readable again merely by refreshing its dates.

Full batch mode may suppress new question candidates through an explicit option,
but do not erase prior candidates or silently change normal new-story behavior.
Thread the actual prompt omission as well as storage suppression; spending the
model tokens and throwing the questions away is not the optimization.

Ordinary single-source prompt/from-response and local maintenance must use the
same mode selection and validation definitions, so future contextual additions
benefit without a special operator pass. Changing known anchor bounds with
unchanged valid relationships should use deterministic recalculation wherever
provable. Do not remove fields from fingerprints blindly: new competing stays,
new aliases, unresolved references, date-dependent bindings, and retractions
must still be reconsidered. If safe no-model reuse needs a separately versioned
dependency contract, document that explicitly; do not fabricate a model's echo
or claim the old model saw new context.

## Validation and Atomicity

- Preserve existing exact evidence quotes, unique occurrence, canonical ID,
  source revision, incomplete-context, ambiguous identity, and human-override
  checks. No guessed calendar years; supported ranges count as placement.
- Each item's candidate normalization and all possible validation happen before
  writes. Unexpected I/O failure fails the batch; the host disposable transaction
  discards uncommitted changes. Local batch application must not leave a receipt
  claiming writes that did not happen; use existing atomic write patterns.
- A source that changed after planning is refused, not silently filed against
  the new source. A context-only failure retains previously usable claims.
- Reports distinguish a successfully processed opinion with zero events from a
  failed source. No work is silently omitted or called successful because the
  planner selected its last page.

## Tests and Delivery

Synthetic tests: shared single/batch parity; multi-source one catalog; partial
refusal with good siblings; exact replay; conflicting batch ID; path traversal,
symlink, oversized and duplicate inputs; source/context race; empty output;
timeline refresh preserves all non-temporal fields and candidates; legacy/full
fallback; opinion no-event success; new/removed/ambiguous landmark evidence;
manual decisions and event identities; repeated current pass creates no changes.

Provide a runnable 500-source synthetic batch walkthrough that measures planning,
validation, application and projection separately and counts model work needed
on first build, no-change rerun, added story, and changed relevant landmark.
Do not label recorded model speed a live provider performance result.

Update behavior docs, ADR for durable interfaces, CLI help, version/release and
framework manifest in the same PR. Version target v303 unless main advances.
Run scoped tests and the full OSS suite, manifest guard and CI. Parent handles
merge and platform pin; implementer only commits/pushes its branch and evidence.
