# Stable Independent Classifier Context

## Why

Owner-authorized v306 follow-up to OSS v305, based on confirmed remote main
`fa92abe91a6509e2957fb3b9efedfb62fcc9fd49`. The classifier currently excludes
purely classifier-derived timeline nodes but accepts mixed episodes using their
published metadata. Filing a new reading and retiring older classifier claims
can change such an episode's kind, subjects or bounds without new independent
evidence. Shared fallback candidates then invalidate other paid classifications.
A synthetic v305 filing/migration/publication walkthrough reproduces zero pending
after filing becoming two pending after publication with unchanged source text,
roster, human decisions, candidate IDs and dates.

Covering issue: https://github.com/lifehug/lifehug/issues/348.

## Binding Facts

- `system/classifier_context.py` owns every host's candidate context and freshness.
  Keep `load_context_catalog`, `build_context_snapshot_from_catalog`, ordinary
  single-source selection and batch filing on that same definition.
- Context candidates must derive from independent active claims and explicit
  identity authority through the existing canonical temporal fold. Filter the
  classifier evidence before derivation, never reinterpret mixed published rows
  with a second temporal engine. Candidate metadata cannot borrow classifier
  subjects, labels, kind, date support or conflict state.
- Preserve the canonical identity/binding, correction, ambiguity, negative
  dependency, provenance, supersession and path-safety rules. Never weaken
  `assert_one_event_identity`, receipt validation or stale-response rejection.
- Retain the four snapshot keys and semantic hashing of candidate identity,
  canonical roster terms, bounds, basis, conflicts and completeness. No global
  prompt/extractor bump merely to force new model calls. No dropping meaningful
  fields from the digest to hide a dependency change.
- Build the independent fold once per catalog, not once per source. Batch filing
  may load a second catalog for race validation; both use the same authority.
- No mutation or model call is allowed while deriving classifier context.
- Machine prior identities/rekeys are prompt history only: they cannot select
  candidates or make human decisions applicable. Source-specific human decisions
  use their explicit telling references and immutable receipt provenance.

## Scope And Compatibility

Implement the shared independent context catalog, focused canonical regressions,
documentation and v306 release/manifest checks. No platform edits, UI, new planner,
backend, durable family or temporal engine. No private data, live operations,
budget changes, model purchases, archive reruns or operational scripts.

The existing snapshot/plan/envelope APIs remain stable. Where independently
derived candidate semantics differ from a stored v305 snapshot, the current
four-key contract may correctly report `context_changed`. This PR does not
declare those old results reusable, overwrite their metadata or restamp them.
The parent separately owns saved-reading compatibility proof and authorization;
new catalog/snapshot output supplies canonical semantics for that analysis.
All hosts consume the OSS definition by pinning it, without a platform fork.
Legacy hashes are not rewritten. An unchanged semantic digest remains reusable;
an old paid response whose equivalence cannot be proved may need a fresh reading.
Existing retrieval, including the 64-candidate fallback, is unchanged: genuine
new independent context can affect many fallback sources. This fix prevents
self-generated churn, not all broad invalidation from genuine authority changes.

## Test Plan

Add real synthetic receipt/identity fixtures and executable regression coverage:

1. The three-source v305 regression remains zero pending after filing, migration,
   actual no-model compilation and repeated publication, while source/roster/
   human-decision bytes are unchanged.
2. A mixed four-claim episode loses two classifier claims through canonical
   reclassification supersession, leaving two independent claims. Candidate
   identity metadata remains based on independent authority before and after.
   Cover sparse independent identity/start evidence, not only date changes.
3. Relevant added/changed/removed landmarks, source corrections, canonical aliases,
   human identity decisions and independent dates still refresh affected sources.
   Unrelated matched-source contexts remain current; fallback contexts retain
   their genuine dependencies. Saved responses to changed inputs refuse.
4. Bulk snapshots use one independent fold/catalog, with no per-source fold;
   source-specific retrieval/caps and exact exclusions remain bounded.
5. Retired/disputed identity guards, immutable history, receipt validation and
   existing single/batch host parity remain intact.

Use the bundled Python before CLT git on PATH, `TMPDIR=/private/tmp` and
`PYTHONDONTWRITEBYTECODE=1`:

```sh
python3 -m unittest discover -s tests -p 'test_classifier_context*.py'
python3 -m unittest discover -s tests -p 'test_archive_classification_batch.py'
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/ci/check_framework_files.py
git diff --check
```

Synthetic data and recorded model responses only. No viewer change; screenshots
are not applicable. Report exact commands, counts, limitations, changed files,
immutable candidate SHA and tree. Parent opens/reviews the PR and owns CI verdict,
merge and downstream pinning; builder never watches CI, merges or changes labels.

## Definition Of Done

- [x] Shared context derives only from independent authority via the canonical fold.
- [x] Both self-invalidation regressions and legitimate-change controls pass.
- [x] One catalog fold serves all source snapshots (per-source retrieval still scales).
- [ ] Focused and full local suites plus manifest/version gates pass.
- [ ] v306, docs and final immutable candidate evidence are pushed.

## Local Evidence

Focused verification: 46 classifier-context tests, 30 archive-batch tests,
34 ordinary-classifier tests and 278 temporal tests pass. The real three-source
and sparse four-to-two retirement regressions retain zero pending after repeated
migration/publication and actual `wiki_compile.py --no-ai`. Read-only catalog
loading preserves the entire synthetic vault's file bytes. Indirect classifier
date support via ordering is excluded; clock advancement, machine manifest rekeys
and ordinary publication cannot alter freshness. Real date, roster and human
authority changes still invalidate dependent contexts.

A separate real 500-independent-claim/500-source measurement took 0.974 seconds
for the catalog and 0.325 seconds for all snapshots; fallback remains truncated
at 64. The committed call-count regression proves one active-index fold and one
temporal derivation for 500 snapshots, not a wall-clock SLA. The existing archive
walkthrough also passes all four real add/change/remove context transitions.
Its 500-source filing timing still uses an explicitly labeled context stub.

The full suite is running; the exact candidate's final outcome and release-gate
results will be posted as PR evidence, without changing the head merely to
replace this checkpoint. No CI verdict is claimed here.

Generated with Codex.
