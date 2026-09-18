# Contract: Classifier Receipt Identity

Generated with Codex.

## Why

[Issue #355](https://github.com/lifehug/lifehug/issues/355) repairs a confirmed
publication blocker without weakening immutable receipts. The historical rule-2
producer placed an event's direct and contextual readings in one receipt. The
v307 producer split those readings into distinct source-reference groups but
kept rule 2. For an unchanged historical classification, its direct receipt can
therefore reuse the old receipt identity while asserting only one of the old
two claims. The retained claim is identical; the assertion set is not.
`temporal_store.write_receipt` correctly raises `receipt_immutable_conflict`.

The exact shape is reproduced using wholly synthetic input and the actual
producer code from v306 and v309. No private paths, identities, text, receipts,
or derived private fixtures belong in this repository or its tests.

## Binding Facts

- Base: merged v309 `b00947dbed57e7106524463ea3902f62d3ce4437`.
  Target release: v310. Branch: `codex/classifier-receipt-identity-v310`.
- `e306135ddbcb6fd6c8d5eedd9726ac85c9f64b05` introduced the grouped readings
  and bumped the producer from rule 1 to rule 2. Main v306
  `809cd3f1686756db0d7cb2a6eb8edbfa3c995cf9` retains that producer.
- `7f4d74811d78773eee0c01b1f39061f304f11fd1`, released in v307 merge
  `f3f851c33d640479617ad4c0ede4135b4db905ae`, added `:link` source IDs,
  contextual revisions, and grouping by source reference without changing
  rule 2. v308 and v309 retain that identity mismatch.
- The single producer generation authority is
  `timeline_evidence.CLASSIFIER_CLAIMS_RULE_VERSION`, consumed by
  `classifier_claims` and the current-classifier predicate. This fix moves it
  to `3`, not the model extractor or classifier prompt version.
- `temporal_claims.CLAIM_IDENTITY_KEYS`, temporal schema versions, receipt
  identity rules, `write_receipt`, and its assertion comparison remain
  unchanged. No added annotation exemption, overwrite, subset acceptance,
  existing-receipt skip, or special recovery branch is permitted.
- Existing `_superseded_by_reclassification` retires obsolete classifier
  claims by classification stem. Old receipt bytes remain history; new rule-3
  receipts and ordinary supersession corrections are appended.
- `timeline_resolution_status` remains asserted when currently emitted.
  Do not remove it, change projection meaning, or add a resolution store.

## Identity Decision

Normalize each emitted reading through the canonical temporal-claim validator.
Derive its producer reading revision from that normalized assertion and the
existing source provenance, excluding generated claim IDs, generated revision
self-reference, timestamps, and extractor declarations. Revalidate after
assigning the final source-reference revision so the canonical claim-ID
derivation remains the sole authority. Do not introduce a second handwritten
list of temporal assertion fields or exclude arbitrary asserted data.

Use the existing grounding/source-resolution provenance and bounded legacy
classification-revision fallback. No new source revision authority, filesystem
reader, or freshness policy is introduced. Grounded direct identity must not
depend on unrelated contextual relations, candidate fingerprints, or outer
classification timestamps. Do not extend timestamp-stability promises to
ungrounded legacy classifications beyond their existing contract.

Every asserted field participates, including evidence, event kind, subject,
temporal value, event reference, place mentions, and resolution status when
present. Contextual readings must account for their emitted role even when
that role depends on grounding. Canonical normalized semantics, not incidental
model formatting, decide whether an interpretation changed.

The binding invariants are:

1. Equal normalized assertions and equal applicable source provenance produce
   equal interpretation identity. Unchanged compile and replay remain no-ops.
2. A genuinely changed assertion at the same document revision gets a new
   interpretation receipt and ordinary supersession, never an in-place edit.
3. The same produced receipt path implies the same immutable assertion, apart
   from the store's already-declared timestamp/extractor annotations.
4. User-facing `event_key`, `event_ref`, telling identity, manual Move/Undo,
   binding decisions, and correction/retraction authority remain stable.

### Explicit Prior-Promise Amendment

This decision narrowly amends `timeline-evidence-links.md`'s unconditional
source-fact claim-ID stability wording and the corresponding ADR 0030 prose.
A direct claim ID remains stable when its own assertion and applicable source
provenance are identical despite a link/context refresh. If asserted status,
evidence, kind, or another assertion changes, a new interpretation ID is correct;
the event does not become a different event, and the prior interpretation stays
in history. Retain status rather than pretending a changed assertion is equal.

### Equivalent Correction Authority

Approved implementation addendum: a producer-generation change must not revive
an identical assertion explicitly retracted, disputed or superseded. Migration
uses folded explicit correction records, not derived status or re-extraction
marks, and compares the raw validated receipt claim's complete normalized
assertion. Only generated IDs/clocks, producer version and revision are removed;
only the known terminal `:link` source-identity marker is normalized. Resolution
status and every other asserted field remain part of equality.

Require matching nonempty declared document revisions. An undeclared legacy
receipt may instead prove equality by its exact source-reference revision
matching the current classification revision or verified grounding source
revision; no heuristic matching is allowed. A changed assertion, evidence,
document, or unproven provenance does not imply inherited rejection. This is
not a general correction policy for changed interpretations.

Append through `file_temporal_correction`, preserving kind/scope and attributing
the original correction ID and reason, authored by the migration rather than
impersonating a new owner action. Exclude automatic classifier supersession and
Move scopes. Never edit the original receipt/correction. Equivalent disputes
remain disputes; they are not suppressed as retractions. Replay adds no bytes.

`test_grounded_direct_fact_identity_survives_link_refresh` currently checks only
claim identity while also changing asserted status. It misses the conflicting
receipt write. Replace that expectation explicitly with an unchanged-direct-
assertion link-refresh case and separate changed-status/evidence cases proving
new receipts, preserved history, publication, stable event identity, and manual
authority. Do not delete meaningful coverage or silently weaken the test.

## Scope

Implementation is bounded to the classifier receipt producer and generation
authority, focused synthetic tests, v310 metadata/manifest/changelog, and docs
that describe the changed identity promise, including ADR 0030 and the older
timeline-evidence contract. Reuse existing validators, receipt filing,
supersession, migration, and publication paths.

No host implementation, diagnostics feature, model/prompt tuning, schema or
freshness-policy change, new model calls, repair engine, scheduler, private-data
inspection, live migration, or cloud run. Do not edit platform #871 or #873.
Parent owns the later #871 pin to the merged core release and its exact-head
combined integration/CI. Current hosted CI is baseline evidence only.

`timeline_evidence._candidate_semantics` deliberately excludes receipt IDs,
source revisions and raw dates from selective freshness. Do not change it or
context selection/independent-grounded-source exclusion to accommodate new
receipt identities. No cache, classifier prompt/extractor, or freshness-policy
version bump and no blanket reclassification/model pass is permitted. A genuine
change to candidate meaning must be identified separately from receipt re-keying.

## Test Plan

Add `tests/test_classifier_receipt_identity.py` and a small frozen synthetic
historical receipt fixture under `tests/goldens/`, generated from the actual
v306 producer named above. Record its producer provenance. CI must not need
Git history, network access, a model, or private data to run the regression.
Extend `tests/test_timeline_evidence_links.py` and existing migration tests
without discarding their negative assertions.

Required cases:

- `legacy_grouped_rule2`: two distinct relative-order claims in one historical
  receipt. Prove the pre-fix same-path one-claim subset collision, then execute
  ordinary rule-3 migration and publication on a disposable synthetic vault.
  Both old claims retire, old bytes remain unchanged, the new readings remain
  usable, and event/telling/node identities are preserved.
- `already_split_rule2`: migrate v307-v309 direct/contextual receipts through
  the same route, without a separate conversion branch.
- `unchanged_direct_assertion`: change only unrelated link target/evidence,
  fingerprint, or classification timestamp while keeping the direct assertion
  and grounding provenance equal. Compare normalized receipts, not only IDs.
- `changed_assertion`: status transitions, alternative valid exact grounding
  quotations/offsets, temporal interpretation, subject, place, and grounded role
  changes move identity when they change emitted assertions. Cover contextual
  roles that change with grounding. Same-path/different-assertion must never
  occur within rule 3.
- `append_publish_replay`: actual filing, active-index supersession, telling
  manifest, publication and replay; a second unchanged migration preserves
  durable bytes and projection generation. Check counts and exact outcomes,
  not merely that the command returns zero.
- `manual_authority`: Move and Undo plus correction/retraction and binding
  guards survive migration and later assertion changes. No manual receipt or
  decision is rewritten, revived, or silently detached by claim re-identification.
  Cover explicit retract/dispute/supersede carry, excluded automatic scopes,
  raw asserted resolution status, changed semantics/evidence/document and exact
  undeclared legacy provenance boundaries, with byte-identical replay.
- Preserve recorder dedupe, current/stale classification gates, mixed-source
  self-exclusion, no-feedback candidate policy, selective freshness, and exact
  incomplete/missing/linked outcome coverage through real publication.
- `post_migration_noop_plan`: where the existing settled fixture has unchanged
  candidate meaning, normal planning after migration remains empty/no-op and
  needs no model call. Receipt ID churn alone cannot invalidate its cache;
  distinguish any genuine contextual semantic change explicitly.

Focused command from the new worktree (use the bundled Python interpreter;
set `TMPDIR=/private/tmp` and `PYTHONDONTWRITEBYTECODE=1` on this machine):

```sh
PYTHONPATH=tests python3 -m unittest tests.test_classifier_receipt_identity tests.test_classifier_claims tests.test_timeline_evidence_links tests.test_classifier_context tests.test_classifier_context_independent tests.test_projection_publication tests.test_temporal_timeline
python3 scripts/ci/check_framework_files.py
git diff --check
```

Then, when no other full local suite is running:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
```

No viewer layout changes are planned, so no visual walkthrough is required.
The synthetic migration/publication tests are the executable verification;
their results are not live archive-recovery evidence.

## Delivery And Review

This contract is the first commit and the only initial draft-PR change. Post
its path, issue, PR, and exact head to the parent, then await contract review
before implementation. Do not push implementation before parent review.
Only push this branch; no labels, readiness changes, merge, or CI watching.
No operational replay is authorized by this contract.

- [x] Parent approves the contract before implementation (550ad32b).
- [ ] Historical and future identity regressions pass with immutable history.
- [ ] Manual authority and published outcomes pass synthetic integration.
- [ ] v310 version, released date, changelog, and framework manifest updated.
- [ ] Earlier identity promise and ADR 0030 explicitly amended.
- [ ] Focused/full OSS tests and exact-head Python 3.11/3.14 CI green.
- [ ] Evidence posted with honest remaining limits; parent owns merge/pin.
