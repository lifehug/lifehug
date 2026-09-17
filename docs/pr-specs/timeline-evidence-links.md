# Contract: Incremental, Source-Grounded Timeline Evidence Links

Generated with Codex. Owner authorized implementation 2026-09-17.

## Why

The archive was refreshed but ordinary-story facts cannot help other stories:
v306 excludes every classifier claim to prevent circular feedback. Retrieval
mostly matches exact roster names, `moment` facts are ineligible, and context
refresh re-extracts every event. A current null relation can still represent a
missed answer. Restore the timeline mission without undoing v306 safety.
Hosted design: lifehug-platform `docs/design/timeline-learning-loop.md`.

## Binding Boundaries

- Base v306, `809cd3f1686756db0d7cb2a6eb8edbfa3c995cf9`; this PR is v307.
- Source files are immutable authority, never fixtures from a private vault.
- Shared OSS behavior; no provider/model calls in pure compile/publication.
- Preserve recorder/human authority, manual moves, rejection and identity
  decisions; no inferred placement becomes independent candidate evidence.
- Reuse existing batch-plan/from-batch-response/refresh-targets protocol,
  one catalog per operation, atomic batch validation, and snapshot refusal.
  Keep outer batch/receipt schema version 1 and mode strings full/timeline.
- No new job subsystem or external vector database. At most one compact
  rebuildable index file, if persisted; register any new state path in the
  vault contract. A derived index is never source authority.

## Stable Extraction and Link Response Contract

Keep full extraction for new/changed/stale source content. A relationship
prompt version change alone must not force full extraction of current sources.
Keep extractor version unless its extraction semantics truly change.

For timeline mode, reuse stored events, supplying stable
`classifier_claims.event_key(event)` IDs and their source evidence. Output:

```json
{
  "_classification_mode": "timeline",
  "_classification_snapshot": {"source_revision":"...","context_digest":"...","prompt_version":"...","extractor_version":"..."},
  "events": [{
    "event_key": "existing event key",
    "source_grounding": null,
    "timeline_relation": null,
    "timeline_resolution": {
      "status": "missing_evidence",
      "candidate_ids": [],
      "reason": "No relevant independent fact supplied"
    }
  }]
}
```

Closed resolution statuses: linked, missing_evidence, ambiguous, incomplete,
not_temporal. Linked requires a validated relation; other states require null.
`candidate_ids` records the complete relevant supplied candidate IDs evaluated
for that event, including rejected alternatives, not arbitrary model IDs.
Reason is bounded model prose, never an operational log/error string.
Require exactly the existing event-key set, once each; reject unknown,
duplicate or omitted keys. Merge only grounding/relation/resolution fields into
the existing events, preserving title, description, subject, direct date,
places, all non-temporal fields, and event identity. Do not silently accept
the old event-replacement response as the new relationship contract.

Persist the normalized resolution with source revision, event key, prompt
version and relevant semantic input fingerprint. Use existing classification
files for per-event decisions, not a new file for every event. Full extraction
produces the same event-local grounding/resolution records. Legacy decisions
are explicitly unaudited until their one-time link/grounding pass succeeds.

## Independent Source Facts

`source_grounding`, when present, has the shape:

```json
{"quote":"exact event quotation","temporal_quote":"exact date or age words within quote","subject_quote":"exact subject words within quote","kind":"date"}
```

Kind is date or age. Framework computes exact unique quote offsets, effective
source revision and normalized temporal value; it does not trust model offsets
or model years. Use `chronology`'s existing date/age parsers to prove the
temporal words support the existing explicit `date.stated` or `date.age`.
Require the subject evidence to support the event subject. A relative's age
must never use the owner's birth. Ambiguous subject/date proof remains
unverified rather than being promoted. Corrections invalidate prior grounding.
Legacy description/when_hint summaries are not verbatim source quotations.

Build candidates from independent recorder/human evidence plus ONLY directly
grounded current source facts above. Include eligible dated moments and all
event roles, not only the current event-kind whitelist. Source-origin fact
identity must be stable across relation refresh and classification timestamps.
Exclude the target source's own facts from its candidate context. Do not admit
relative/contextual claims as independent facts; provenance retains the source
revision and exact evidence locator. Age arithmetic may depend on the real
subject's independently supported birth, never default another person to self.

Do not blindly restore classification claims into the fold. Construct the
independent input subset with verified direct facts before deriving candidates.
No classification title, context link or changing receipt ID may churn another
source's freshness unless relevant source-backed semantics actually changed.

## Search and Selective Invalidation

Create shared deterministic lookup indexes over entity IDs/aliases, event
labels/roles and temporal reference terms, including UNMATCHED references.
Reuse roster/identity/index utilities. Lookup aids recall; it is not permission
to fuzzy-merge identities. Consider all relevant competing stays/roles, including
founding versus employment and visits versus residence. The model resolves
meaning from source quotes and supplied candidates, not unique entity count.

Replace blanket global truncation refusal with per-reference completeness.
Relevant matches beyond the old first-64 catalog slice must be discoverable.
Partition candidate context by event/reference where necessary; if a relevant
set still exceeds a safe input bound, persist incomplete with diagnostics and
never turn it into a missing-date question. Unrelated entries cannot invalidate
a complete relevant set. Do not silently truncate human decisions.

Preserve the relation shape (`relation`, `candidate_id`, `entity_refs`, exact
`evidence.quote`) but validate complete relevant alternatives and a uniquely
located source quote instead of requiring a globally unique entity ref. A
model assertion that two same-named stays differ is insufficient without source
disambiguation. No guessed calendar year or arbitrary 'early marriage' window.

Freshness fingerprints are per source/reference and include relevant candidate
identity/role/grounding and human decisions; adding an unrelated fact is a no-op.
Known anchor bound-only edits propagate through existing relations without AI
when identity/meaning is unchanged. Aliases/new competitors/withdrawn facts
invalidate affected positive and negative resolutions. Re-read prior unmatched
references on relevant new evidence, not just already-linked dependents.
Allow the cheap full deterministic fold as correctness oracle/publication.

Do not emit a new date question for a known resolved reference, processing
failure, incomplete search or non-event. Preserve a genuine partial order even
without a finite interval. Questions/gain use the same canonical relationships
as propagation; resolved raw handles must not survive as parallel repair debt.

## Scope / Hosts

Primary modules: classifier_context, classify_story, classifier_claims,
temporal_timeline and a focused helper module if it reduces complexity.
Hook normal local answer/story/session-close/maintenance scheduling through
existing refresh selection, without adding a second writer or making compile
call a model. Hosted integration consumes the same protocol in its own PR.
Parent is auditing host bindings; raise interface questions before changing
the outer protocol. This PR may not claim hosted deployment by itself.

## Test and Verification Contract

Synthetic fixtures only. Add a focused test suite and reproducible offline
report/benchmark command. Cover:

1. Different wording for founding Northstar connects to a grounded ordinary
   answer; an employment start/idea is not substituted.
2. River House alias plus dated residence updates an old story; two stays
   remain ambiguous unless source evidence distinguishes them.
3. Early marriage is related using supplied bounds, not guessed precision.
4. Ordinary source date/age grounding, foreign-subject age, invalid/non-unique
   quotes, altered source, corrections, retraction and circular-support refusal.
5. Relevant candidate beyond 64; per-reference incomplete status; no false
   missing-date question or unrelated global poison.
6. Unrelated new facts leave interpretation/model calls unchanged. Date-only
   anchor correction propagates with zero AI. Relevant aliases/competitors
   invalidate old positive and negative outcomes.
7. Timeline refresh preserves exact stored events/non-temporal fields, rejects
   changed event IDs/omissions, and filing/publication reaches a zero-call no-op.
8. Stop/resume and stale batch snapshots refuse results without losing saved
   evidence or accepted work; existing v306 no-feedback tests stay meaningful.
9. Assert exact older node IDs acquire the correct intervals, repair questions
   retire and manual moves/rejections survive, not just total counts/generation.

Run focused suites first; full unittest matrix remains merge gate. Update
affected tests deliberately, never delete safety tests to make them green.
Report retrieval coverage separately from validated linking accuracy; replay
responses prove plumbing, not live model quality. Keep a held-out synthetic
paraphrase/conflict evaluation runnable against configured AI without requiring
secrets in CI. No provider call on private data during development.

## Delivery

Builder reads AGENTS.md, CLAUDE.md, docs/BUILDING.md. Add ADR amendment for
source-grounded authority/extraction-versus-link separation, update relevant
methodology/user docs, version/changelog/framework manifest in this PR.
Commit/push only this branch with accurate model/surface attribution. No
merge or unrelated branch edits; parent reviews and owns merge/deployment.
Launch-and-verify: committed synthetic test/report entry point demonstrates
before/new-evidence/after/unchanged states and stage timings. UI is separate.
Owner closeout names commands/results, remaining risks and linked hosted PR.
