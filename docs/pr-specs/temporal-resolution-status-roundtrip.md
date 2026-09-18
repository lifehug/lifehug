# Preserve Timeline Resolution Status Through Storage

Generated with Codex.

## Why

Issue #357. Base main `74645fb0bc7474f4471400f8a5f0e4ea41ac00e0`, v310.
`validate_temporal_claim` retains the optional, closed-vocabulary
`timeline_resolution_status`, but `TemporalClaim` and `claim_from_dict` omit
it. Receipt reads therefore drop the field before the active-index fold and
calculated timeline can use the existing resolution semantics.

## Binding Scope

- Append an optional field at the END of `TemporalClaim` for positional
  compatibility; thread it through `claim_from_dict` and `to_dict`.
- Reuse the existing canonical validator and vocabulary. Preserve absent-field
  bytes, claim IDs, source/event identities and immutable receipt bytes.
- Do not change identity rules, schemas, prompts, context/freshness versions,
  resolution policy, corrections, authority or provider behavior.
- Verify the receipt and projection typed paths for this same field only;
  avoid general serialization refactors. No core/host repair machinery.
- Synthetic tests only. No private data, cloud, provider or operational runs.

## Verification

Extend `tests/test_temporal_claims.py` and add
`tests/test_temporal_resolution_roundtrip.py`. Exercise actual receipt writes,
receipt reads, `fold_active_index`, `derive_calculated_timeline` and publication.
All canonical statuses must survive. A usable linked event must retain bounds
and avoid redundant raw-anchor/date debt; incomplete and not_temporal must
retain their existing suppression; missing_evidence must retain its question.
Legacy absent-field serialization and IDs stay identical. Repeated filing,
folding and publication must preserve original receipts and no-op bytes.

Commands (bundled Python, `TMPDIR=/private/tmp`, no bytecode):

```sh
python3 -m unittest tests.test_temporal_claims tests.test_temporal_resolution_roundtrip tests.test_temporal_store tests.test_classifier_receipt_identity
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/ci/check_framework_files.py
git diff --check
```

Ship v311 with release date, changelog, framework manifest and a scoped
behavior-document amendment. Push only this branch and report exact-head
evidence; parent owns green-CI merge and host pin. Do not watch CI, label, mark
ready or merge.

- [x] Contract precedes implementation and draft PR.
- [x] Typed round-trip fix and focused storage/publication regressions pass.
- [ ] Full local suite, manifest and diff checks reported.
- [ ] v311, scoped documentation and exact-head PR evidence published.
- [ ] Parent verifies exact-head CI and decides merge/pin.
