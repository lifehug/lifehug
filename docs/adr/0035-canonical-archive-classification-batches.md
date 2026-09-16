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
per-item outcomes. Identical replay is a no-op; reuse of a batch ID with changed
input fails closed. The archive-only `--skip-candidates` option omits question
generation from full prompts and preserves existing candidate IDs. It defaults
false everywhere.

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
- Planner and ordinary refresh reports share one eligibility pass. Empty or
  unsafe sources are typed ineligible outcomes; completion requires zero pending
  and zero ineligible rows. Explicit source lists scope all reported counts.
- Unexpected I/O fails the batch and publishes no receipt. A host uses its
  disposable transaction to discard such uncommitted writes.
- Ordinary single-source and maintenance paths use the same mode selection and
  converge to `already_current` without another model call.
- Future deterministic contextual reuse must supersede this explicit dependency
  boundary instead of weakening the context fingerprint.
