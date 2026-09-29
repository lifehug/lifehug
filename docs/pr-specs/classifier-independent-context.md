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

## Amendment 2026-09-29 — a re-key is not a change to a life

Owner ruling, 2026-09-29, in his words:

> "A software re-key is not a change to my life; carry links over."

This spec already binds, in its Local Evidence, that "clock advancement, machine
manifest rekeys and ordinary publication cannot alter freshness. Real date,
roster and human authority changes still invalidate dependent contexts." Until
v375 the digest honoured that sentence for the telling manifest and not for node
ids. A node id is a machine key too: `temporal_projection.derive_node_id` hashes
kind, subject WORDS and discriminator, so a rule move that re-mints ids (v350's
identity re-key, a roster word that newly resolves, a landmark redraw) changed
`candidate_ids` and every candidate's `candidate_id` inside `input_fingerprint`,
and `refresh_reason` returned `context_changed` for stories whose words,
candidates and meaning had not moved (Sep 27-28: ~800 model calls, ~40M tokens;
56% of the rewrites changed no status and no link).

v375 (`classifier_context.A_RE_KEY_IS_NOT_A_CHANGE_TO_A_LIFE`) makes the digest
honour the sentence for node ids too.

**What the digest now keys a candidate by.** Its identity, written in the id
space its classification was filed in:

1. a candidate whose node id the stored reading filed (in an event's
   `timeline_resolution.candidate_ids` or its link) keeps that id;
2. a candidate whose id is new stands for a filed id that vanished from the
   catalog when that id is provably the same thing: the projection's own
   `node_aliases` walks to it, or, when no other candidate of the event shares
   its node kind, event kind and entities, the vanished id recomputes as
   `derive_node_id(node_kind, event_kind, [a word its entities are known by],
   a discriminator it carries)` (v373's proof). The pairing must be one-to-one;
3. anything else keeps its own id, and the change is honest.

The identity tuple is therefore node kind, event kind, the entity refs the
candidate is about (plus the roster place a landmark stay is), and the
discriminators its minters use (episode id, stated start, promoted landmark
source id). With no filed id vanished, the digest input is the v374 input byte
for byte, so `CONTEXT_SCHEMA_VERSION` stays 1 and no stored snapshot becomes
`legacy_snapshot`. The prompt still reads today's ids; only the digest names.

**What still invalidates.** Every other field stays in the digest exactly as
before: canonical roster terms, entity refs, unresolved mentions and
ambiguities, basis, conflict state, alternatives, reference keys, grounding
identity, completeness and remaining counts, human identity decisions and
source roster authority. New or removed candidates, source edits, corrections,
prompt/extractor versions and human decisions invalidate exactly as they did.
(Recorded, not changed: `supported_bounds` has not been part of the event
fingerprint since 7f4d748, 2026-09-17, by ADR 0036's design that a date-only
correction flows through an existing link without another model call.)

**Links.** A stored link whose node id vanished follows the same redirect at
read time: the fold follows this generation's `node_aliases` for an anchor that
names a re-keyed node (`temporal_timeline.A_LINK_FOLLOWS_ITS_NODE_THROUGH_A_RE_KEY`,
`timeline-rules:26`). A link the drawing neither draws nor redirects is pending
with the new reason `link_orphaned` (ranked after `classifier_changed` and before
`relationship_changed`/`context_changed`), a timeline-mode refresh: settled by
rule when v373's remap proves one target, by the model otherwise. It is never a
silent `anchor_unresolved`.

**Known risk.** A rename that also changes meaning. When a digested field moves
together with the id (a new entity ref, basis, conflict state), the digest
changes and the story refreshes, as it should. When two candidates share kind
and entities, only a discriminator separates them, and a re-key that re-orders
discriminators would make recomputation prove the wrong stay; such candidates
are therefore never paired by recomputation (only by the projection's redirect),
and v373's rule remap refuses them too, so the link goes to the model as
`link_orphaned`. A projection redirect that is itself wrong would carry a link
to the wrong node; that is the fold's contract (`episode_fold`,
`AN_IDENTITY_RE_KEY_IS_A_WAY_A_NODE_ID_MOVES`), not this digest's. ADR 0039.
