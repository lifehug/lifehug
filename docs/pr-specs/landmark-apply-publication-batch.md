# Contract: Landmark Apply Publication Batch

## Why

The v297 hosted File all act timed out on a populated vault despite the same
76-unit / 30-event shape completing on a small synthetic fixture. The package
calls `go_dig_writer.record_unit` -> `timeline.save_landmark` ->
`timeline.redraw_landmarks` for each unit, then redraws after filing group
events. Each redraw also rebuilds the entire calculated timeline. Synthetic
v297 evidence: 76 units / 30 events produced 77 calculated publications,
154 active-index rebuilds and 6,218 receipt reads in 14.13 seconds on a small
fixture. A populated fixture with 1,000 existing moments is under measurement.
The hosted counterpart is lifehug/lifehug-platform#847.

## Binding Facts

- Base: v297, `411a43c9caa02b12c2020e8aeccdfd46b11bad35`; release: v298.
- `landmark_offer.apply` remains the authority for confirmation and receipt
  identity. No public propose/apply/CLI argument, schema, reading revision,
  source identity, claim identity, or receipt identity changes.
- `timeline.redraw_landmarks` remains the only landmark-store writer.
  Every unit still records evidence, applies supersession and redraws that
  store in sequence. Later units must see earlier writes, including returned
  merged entries, aliases, telling refs and separate repeated stays.
- `temporal_publication.publish` remains the only calculated publisher.
  No incremental projection, alternative writer, model call, host-side
  publication policy, increased budget or persistent cache is added.
- Existing receipts/proposals remain immutable. Applied receipt replay returns
  before entering the batch and performs no writes or publication.

## Scope And Boundary

Add a package-owned, execution-context-local, vault-bound publication batch
around the existing apply writes. A successful dirty batch publishes the final
calculated timeline exactly once, after units AND group events/slices are filed
and before gain/retirement calculation and the success receipt. Landmark-store
redraws remain eager. A batch with no redraw is a no-op. Direct standalone
save/redraw calls retain their current immediate publication and signatures.

The outermost batch owns the flush. Nested same-vault batches must not flush
early. Cross-vault nesting or a rebound landmark-store path must fail before
the other vault is written; all context state must unwind on any exception.
A failed batch must not publish a success receipt or flush an incomplete batch
as success. Evidence and landmark draws already filed remain durable for retry;
there is no new rollback claim. The calculated projection may still be the
previous successful generation until retry/repair. A final publication failure
must propagate, clean up batching state, and remain retryable without duplicate
evidence. Atomic per-file projection semantics are unchanged.

This is a manual capture surface feeding the Loop through the canonical
substrate, not a new cron or background maintenance job. Historic migration,
live-vault writes, host timeout/client work and broader I/O optimizations are
out of scope. Platform #847 consumes the exact package pin and owns host work.

## Tests And Evidence

Use synthetic vaults only, no private data and no model calls. Add
`tests/test_landmark_apply_publication_batch.py` with:

- 76 units / 30 events on 1,000 published moments: exactly one calculated
  publication, eager redraw count unchanged; complete receipt and projection.
- Sequential merge/supersession, none/substantive replacement, repeated stays,
  name/telling/alias behavior and group claims preserved.
- Same receipt replay has zero publication and byte-identical files; already
  retracted receipt replay remains a no-op. Old proposal reading/CLI works.
- Empty batch, nested same-vault, cross-vault refusal, changed store binding,
  exception cleanup, mid-unit failure, final publication failure and retry.
- Standalone calls still publish immediately; unrelated execution contexts do
  not inherit a stale batch. A semantic no-change final publish does not mint
  a generation. Historical receipt bytes are unchanged.

Run the new tests plus landmark offer, house identity, atomic subject, Go Dig,
projection/publication, temporal store and receipt suites. Run the full suite
with `TMPDIR=/private/tmp python3 -m unittest discover -s tests -p 'test_*.py'`.
Record unprofiled before/after wall time AND deterministic call counts, not a
flaky CI timing threshold. Profile real calls to distinguish avoided full
publication from the deliberately retained sequential substrate work.

## Done

Code, tests, measured synthetic evidence, v298 changelog, CLAUDE operating note
and ADR 0033 amendment ship together. No visible viewer layout change. Draft
PR and exact candidate SHA go to the owner for full CI/pin/merge coordination;
the implementing agent does not merge or watch CI.
