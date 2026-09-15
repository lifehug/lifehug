# Contract: Contextual Timeline Placement

Generated with Codex.

## Why

The September 15 owner review found supported date ranges treated as unknown,
generic requests for a year on already placed events, and older story events
disconnected from newly supplied residence/school/work landmarks. Platform
lifehug-platform#850 implements the compact presentation; this PR owns the
canonical interpretation and placement policy. Real private records informed
the diagnosis but are never fixtures, test targets, or public examples.

## Binding Facts

- Base 0785df36d436535aecd75f9dd84af13ca89d833b, v300; target v301 unless
  main advances. Every PR bumps version and distributes new framework files.
- classify_story.build_prompt includes the source, corrections and question
  guidance, but no canonical landmark timeline. Its event schema has no
  validated per-event canonical relationship. classifier_claims currently
  carries document-wide places into every event and chooses one date reading.
- Existing uploaded episodes can be correctly dated while an older event is
  still unplaced. Publication freshness does not imply extraction freshness.
- temporal_timeline._wants_precision compares granularity with a target;
  ranges and containment windows therefore produce unnecessary year prompts.
  Canonical unplaced diagnostics test best value only, while rendering can
  recognize possible_temporal_value. ask may retain old queued questions.
- Existing relative_order/within claims, provenance, correction authority,
  identity manifests, migration, publication and classify jobs are the seams.
  Reuse them. No second temporal graph, autonomous calendar guesses, or
  platform-side inference. No name-substring/date/title parsing to bind events.

## Scope And Policy

### 1. Usable Placement

Define once, in the canonical package, what supported placement means. An
accepted stated/calculated/inferred best value, including an approximate
date/range, or an accepted evidence-backed containment window is placed.
An ungrounded lifetime/viewport fallback is not placement. Numeric width
alone is not evidence. A genuinely source-supported lifelong interval is
still supported. Ambiguous candidate containers are not an accepted window.

Apply the same predicate to generic precision question generation, unplaced
diagnostics/counts and existing queued-question eligibility. Obsolete generic
date requests become system-resolved/ineligible, never user-answered; a later
evidence retraction can restore eligibility. Preserve genuine missing-anchor,
identity-ambiguity and conflict work. A placed-but-conflicted event should not
receive a generic year request. Counts use distinct node IDs and a declared
cohort; uncertainty-width scores remain a different metric.

### 2. Source-Grounded Contextual Reading

Extend the existing classifier, not a separate AI date-repair service:

- Supply a bounded canonical landmark/episode context with canonical IDs,
  names/aliases, supported bounds and basis, alternatives, applicable human
  decisions and existing event identities for this source. Include relevant
  inherited school/work episodes, not only explicitly dated residences.
- Select context through canonical references/dependencies or the existing
  retrieval facilities. A bounded complete episode inventory is acceptable
  for small vaults. Never use event-title substring matching as a binding
  rule. Include repeated stays/competing episodes together. Explicitly state
  truncation/absence; missing context must lead to abstention, not guesses.
- Add optional, validated per-event relationship output selecting supplied
  IDs, with exact supporting source quotes/locators and event-local entity
  references. Document-wide places can inform retrieval, never silently
  replace explicit event-local evidence. Reject unknown IDs, unsupported
  relation kinds, invalid locators and overconfident bindings on incomplete
  context before filing. Quotes are source evidence, not instructions.
- Use existing before/after/within relations. For this repair, a move inside
  the supported residence window is enough; do not add at_start calendar
  semantics, automatic same-event merging, or new generalized identity rules.
- Permit both a source's independent direct date/age and a supported
  contextual relation to survive. Preserve conflicts and manual corrections.
  A relation to an employment episode does not assert same-event identity.
- Preserve exact ages versus explicit decade expressions. Cover chronology's
  age-band parser with source-grounded synthetic tests. A title mentioning
  decades cannot expand a stored ambiguous age claim without source evidence;
  a missing birth date cannot produce a fabricated calendar date.

### 3. Refresh Without Losing History

Use source revision + extractor/prompt version + stable relevant context
digest to determine refresh need. Exclude timestamps/projection generations
from that digest. New/corrected/retracted relevant landmark or identity
evidence must make affected readings eligible for refresh, including placed
events with conflicting evidence. Legacy readings lacking trustworthy
references need a bounded discovery/reread path, not pretend completeness.

Pending/failed context refresh is NOT source retraction and must retain the
prior usable claims. Success replaces only the appropriate derived extractor
family, including a changed extractor on unchanged source bytes; preserve
human corrections, other evidence and identity decisions. Reuse existing
event manifest/rekey mechanisms to preserve telling identities across model
rewording; ambiguous correspondence must not silently merge or lose manual
references. Replay must be deterministic and no-op when already current.

Expose the shared freshness/target calculation to normal local maintenance
and hosted classification successors. No new independent worker, scheduler,
unbounded all-history model loop, or private repair script. Honor existing
batch/call budgets and idempotent job mechanisms. The hosted twin must wire
context-refresh targets through existing classification -> migration ->
canonical publication, and supply parity tests against this definition.
Publication alone is not evidence that rereading happened.

## Verification

Synthetic-only regressions must include:

1. Approximate/ranged best and accepted containment window versus identical
   lifetime fallback; no precision nag on supported values; real unknowns
   remain; conflicts/ambiguity preserved; duplicate memberships count once.
2. Already queued date request suppressed when resolved by context, without
   marking a user answer; evidence retraction makes it eligible again.
3. Multi-location story selects the supported event-local stay; uniquely
   supported move obtains rough residence window; repeated stays abstain;
   inherited job/school context is included; unrelated same-name events do
   not merge. Direct and contextual conflicting dates remain inspectable.
4. Invalid IDs, quote/locator mismatch, incomplete context and missing source
   cannot file a confident relationship; unrelated/other-person facts do not
   move onto the owner's axis.
5. Exact ages, explicit decades, ambiguous age alternatives and missing birth
   evidence are distinct. Broad life periods do not prompt for a single year.
6. Same-source updated extractor/context reprocesses, same fingerprint no-ops,
   removed context invalidates, failed refresh preserves old evidence,
   successful reread supersedes only its own family, stable telling identity
   and existing manual references survive. No projection-generation loop.
7. Normal maintenance/host targets and publication demonstrate the complete
   chain, not only isolated helper tests. Report the hosted integration API
   precisely to the parent for the platform twin.

Run focused unittest modules, then python3 -m unittest discover -s tests
with temporary synthetic vaults only. Serialize heavy local work. CI on
Python 3.11/3.14 plus manifest/version guards must pass before delivery.
No visible OSS viewer change required; the platform's runnable /timeline
walkthrough supplies two viewports and interaction evidence.

## Definition Of Done

Code, focused/full tests, version/release/manifest, current behavior docs and
ADR amendment ship together. Update described precision and classifier
context rules; historic contracts remain history. PR evidence states exact
commands, limits and any unresolved risks, never claims live verification
from synthetic tests. Parent owns release/merge and operational replay.
Builder changes/pushes only this isolated branch and reports touched paths.
