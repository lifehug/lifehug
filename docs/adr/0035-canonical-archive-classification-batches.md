# ADR 0035: Canonical Archive Classification Batches

Date: 2026-09-16
Status: ratified (owner, 2026-09-16)

## Context

Building the timeline from an existing archive previously meant buying and
filing one complete classification at a time. Each source rebuilt canonical
context and each hosted filing required its own transaction. Context-only
timeline changes also regenerated themes, insights, sensitivity, and follow-up
questions that the changed landmark could not legitimately alter. The binding
contract is `docs/pr-specs/archive-timeline-batch.md`; hosted orchestration is
contracted separately in lifehug-platform PR 858.

## Decision

`classify-story --batch-plan` is the one archive planner. It loads one canonical
context catalog, reports the whole pending inventory, and emits at most 50 items
by default or 500 explicitly. Each item binds a four-key snapshot and chooses
`full` unless an unchanged, compatible base classification proves that only its
context digest changed; that narrow case uses `timeline`.

Finite callers may supply `--exclude-items-json` with exact canonical source
path plus four-key snapshot identities already attempted. Pending counts remain
pre-exclusion truth; only an unchanged identity is omitted from selection, so a
source or context change immediately makes it eligible again. Path-only skipping
is invalid, and excluded refusals remain pending unresolved work.

The existing `source_revision` snapshot key represents the effective
authoritative classifier input. It remains the raw-byte hash when no active
correction exists; otherwise it binds that hash plus the ordered active
correction bodies chosen by `source_integrity`'s supersession graph. The
context digest separately binds canonical roster terms supplied with candidates
and exact roster refs/terms matched in the source. Machine telling aliases stay
excluded. Thus correction and source-relevant alias changes cannot reuse an old
model response even when selected candidate IDs happen to remain unchanged.

`classify-story --from-batch-response` validates up to 500 raw response strings
against one fresh shared catalog, reloads it once as a race gate, and only then
writes valid siblings. Timeline mode
may replace only events plus classification metadata; every other extracted
field and candidate ID is copied from the compatible base. A malformed or stale
item is refused without erasing that base or blocking valid siblings.

Every filed envelope has a deterministic, content-free receipt at
`state/classification_batches/<batch_id>.json`. The receipt binds canonical
paths, modes, raw-response digests, the required `skip_candidates` policy, and
per-item outcomes in envelope order. The public pure
`validate_batch_receipt(envelope, receipt)` function is the sole validator for
both exact local replay and host adoption. It requires closed receipt shapes and
binds schema, batch ID, candidate policy, top digest, ordered source/mode/item
digests, counts, statuses, and refusal-code consistency to the exact envelope.
Identical replay is a no-op; reuse of a batch ID with changed input fails closed.
The archive-only `--skip-candidates` option omits question generation from full
prompts and preserves existing candidate IDs. It defaults false everywhere.

Every successful full reading records its actual policy as
`classification_skip_candidates`; timeline refresh copies that metadata with
the rest of the non-temporal base. Missing legacy metadata keeps the historical
behavior. A caller handling one newly ingested source may explicitly combine
`--batch-plan --sources-json <one-source-file> --require-candidates` with the
default `skip_candidates=false`. Only that bounded plan treats an otherwise
current skip-true reading as `candidate_generation_needed` and selects a full
pass. Default archive, weekly and all-source planning ignore this policy marker.
A full skip-false response already in flight may also file over an exact-current
skip-true reading; a timeline response never takes that override and stays a
timeline refresh. This closes the archive/new-ingest race without a force flag,
fabricated metadata, or repeated ordinary model work.

This validation proves input binding and internal content consistency, not the
historical authenticity of an outcome. The receipt has no signature or separate
trusted outcome digest, so a self-consistent rewrite of status, refusal code and
counts cannot be distinguished from the originally filed result. Callers must
obtain the receipt from their trusted transaction or commit boundary; they must
not describe validation alone as proof that those outcomes happened.

No-model anchor-bound reuse is deferred. It becomes valid only after a separate
versioned dependency contract can prove that source/extractor, relation evidence,
canonical IDs, aliases, competing candidates, identity decisions, and
retractions are unchanged. Existing exact-current no-op and deterministic
projection recalculation are the only no-model reuse in this version.

## Consequences

- Hosted and local callers consume the same planner, mode, validation, filing,
  report, and receipt definitions; hosted transactions and scheduling remain
  outside this repository.
- Receipts are durable tracked vault data but contain no prompts, quotes,
  response bodies, or extracted dates.
- Exact replay revalidates the entire receipt rather than trusting its top input
  digest, and new receipts are validated before their atomic write.
- Planner and ordinary refresh reports share one eligibility pass. Empty or
  unsafe sources are typed ineligible outcomes; completion requires zero pending
  and zero ineligible rows. Explicit source lists scope all reported counts.
- Unexpected I/O fails the batch and publishes no receipt. A host uses its
  disposable transaction to discard such uncommitted writes.
- Ordinary single-source and maintenance paths use the same mode selection and
  converge to `already_current` without another model call.
- Candidate generation skipped for an archive can be repaired once at the
  actual-ingest boundary without turning unchanged archive rows into weekly
  refresh work.
- Future deterministic contextual reuse must supersede this explicit dependency
  boundary instead of weakening the context fingerprint.
