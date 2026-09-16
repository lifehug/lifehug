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
   an explicit bounded source list. Optional `--exclude-items-json PATH` accepts
   the closed document `{schema_version: 1, items: [{source_path, snapshot}]}`,
   where every snapshot has exactly the existing four identity keys. It skips
   selection only when both canonical path and snapshot still match; path-only
   exclusions are invalid and changed source/context becomes eligible again.
   The document is private transport data, not
   a logging artifact. Target selection remains canonical, includes all source
   kinds accepted by current classification, excludes corrections themselves,
   rejects paths escaping the vault/symlinks, and shares one loaded catalog.
2. `--from-batch-response PATH` consumes `{schema_version: 1, batch_id: SLUG,
   skip_candidates: BOOLEAN,
   items: [{source_path: STRING, mode: 'full'|'timeline', response_text: STRING}]}`.
   Maximum 500 items with explicit size/path validation and no duplicate source
   targets. The framework alone parses and validates model bytes. Validate all
   items against one shared fresh catalog, then reload that catalog once as a
   race gate before applying valid items; refusal of one
   item is reported separately and must not erase valid siblings or old data.
3. Return a content-free structured batch report with source paths, accepted /
   refused / already-current statuses, typed refusal codes, and counts. No
   prompts, quotes, model bodies, or dates in the report. Preserve a durable,
   deterministic receipt at an appropriate existing report location or explicitly
   contracted state location so an adopted host commit can recover its exact
   per-source outcomes. Receipts live at
   `state/classification_batches/<batch_id>.json`, schema version 1:
   `{schema_version, batch_id, skip_candidates, input_digest, receipt_path,
   items: [{source_path, mode, input_digest, status, refusal_code}], counts}`.
4. A repeat of a previously accepted identical batch is a semantic no-op.
   Changed bodies under an existing batch identity must fail closed, not adopt
   the wrong report. Batch receipt binds all input identities/digests. Replay
   after source/context changes must not overwrite newer interpretations.

Plan shape: `{schema_version: 1, skip_candidates, inventory_scope,
eligible_count, ineligible_count, ineligible_items, excluded_count,
selected_count, pending_count, remaining_count,
items: [{source_path, reason, mode, snapshot, prompt}]}`. `snapshot` retains the
existing four keys. `pending_count` covers the whole eligible inventory before
exclusions. `excluded_count` counts exact matching pending identities, and
`remaining_count = pending_count - excluded_count - selected_count` reports
unseen selectable work. Excluded refusals remain pending: selected zero with
pending greater than zero is an unresolved run, never completion.
`inventory_scope` says `all` or `explicit`; an explicit source
file scopes every count to that bounded list. Ineligible rows carry only source
path and typed refusal code, and are never silently omitted. Archive completion
requires both `pending_count == 0` and `ineligible_count == 0`.
`remaining_count` is not a claim of full archive completion.
Before changing these interface names, notify the parent; platform builds against
them. No hosted behavior belongs in this repository.

The snapshot's existing `source_revision` key binds the effective authoritative
classifier input. With no active correction it remains the historical hash of
raw source bytes. When corrections exist it hashes that raw revision together
with the ordered active correction bodies selected by the canonical
`source_integrity` supersession graph. Adding or superseding a correction is
therefore a full source change, including when it happens during a model call;
unrelated corrections do not invalidate the source.

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

Full batch mode suppresses new question candidates only through the explicit
`--skip-candidates` option on both planner and filer. The required envelope
boolean is bound into receipt identity. It defaults false, so ordinary new-story
work retains normal candidate generation. When true, the prompt omits candidate
instructions, judgment context, and question categories; filing preserves every
prior candidate ID and creates none. Never generate candidates and discard them.

Ordinary single-source prompt/from-response and local maintenance must use the
same mode selection and validation definitions, so future contextual additions
benefit without a special operator pass. Changing known anchor bounds with
unchanged valid relationships should use deterministic recalculation wherever
provable. Do not remove fields from fingerprints blindly: new competing stays,
new aliases, unresolved references, date-dependent bindings, and retractions
must still be reconsidered. Safe no-model anchor reuse requires a separately
versioned dependency contract and is not part of v303. Exact-current sources are
no-ops and accepted claims still recalculate through the canonical projection.
Do not fabricate a model's echo or claim the old model saw new context.

## Validation and Atomicity

- Preserve existing exact evidence quotes, unique occurrence, canonical ID,
  source revision, incomplete-context, ambiguous identity, and human-override
  checks. No guessed calendar years; supported ranges count as placement.
- Context freshness binds canonical roster identity/name/alias terms supplied
  with selected candidates plus the exact roster refs and terms matched in the
  source. Relevant alias additions, removals, and ambiguities refresh the
  reading even when candidate IDs do not change. Unrelated roster aliases and
  projection-provided machine telling aliases do not invalidate it.
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
Its deterministic context-provider stub may isolate batching overhead, but must
say so. In the same executable, use real synthetic roster, landmark, temporal
claim/publication, context-catalog, snapshot and identity records to prove that
adding, changing and removing a competing anchor refreshes only the related
source while preserving an unrelated current classification, owner identity
decisions and all non-temporal fields. Recorded model responses are acceptable;
do not label either fixture a live provider performance result.

Update behavior docs, ADR for durable interfaces, CLI help, version/release and
framework manifest in the same PR. Version target v303 unless main advances.
Run scoped tests and the full OSS suite, manifest guard and CI. Parent handles
merge and platform pin; implementer only commits/pushes its branch and evidence.
