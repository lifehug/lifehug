# Contract: Classifier Context Eligibility And Safe Diagnostics

Generated with Codex.

## Why

An operational review found structurally valid classifier JSON containing an
optional timeline relation with empty entity references. Canonical validation
already rejects it, but the prompt does not spell out every prerequisite and
the failure metadata identifies only the exception class. This in-the-Loop
repair clarifies the existing contract and makes refusals distinguishable
without exposing private source, context, model output, or exception text.
All examples, tests, and public evidence are synthetic.

## Binding Facts

- Base: OSS main 3c586439, framework v301. Target framework v302 unless main
  advances. Work is isolated from platform branches and private vaults.
- `system/classifier_context.py:validate_response` and
  `_locate_unique_exact_quote` own the existing 15 rejection sites. Their
  conditions and validation order remain unchanged.
- `system/classify_story.py:build_prompt` supplies the canonical snapshot and
  optional per-event `timeline_relation`. `classify_file` rebuilds the current
  snapshot and validates before persisting classifications or candidates.
- `system/ai_provider.py:failure_metadata` already emits bounded provider,
  operation, failure-class and status metadata without exception text.
- Keep `PROMPT_VERSION = contextual-timeline:1`,
  `EXTRACTOR_VERSION = story-classifier:2`, and context schema version 1.
  This is clarification of already-enforced eligibility, not a new output
  contract or inference rule. Accepted v1 results remain accepted/current;
  invalid ones remain refused. Do not invalidate existing readings or durable
  in-flight responses merely for this wording repair.

## Scope

1. Spell out all existing relation prerequisites in the classifier prompt:
   supplied candidate ID; complete context and candidate set; no unresolved
   or ambiguous candidate identity; nonempty event-local references all
   allowlisted on that candidate, with at least one reference unique across
   supplied candidates; and one exact, uniquely occurring Story Text quote.
   If any prerequisite is unsupported, emit the WHOLE `timeline_relation`
   as null. Preserve the event and independently stated dates/ages.
2. Give each existing context rejection a bounded, typed allowlisted code
   owned by `classifier_context`, surfaced as the existing
   `failure_metadata` status. Retain `ClassifierContextError` and its
   `ValueError` compatibility; reuse `AIResponseError`'s metadata mechanism.
   No exception-text matching, dynamic payload values, or generic arbitrary
   diagnostic-string passthrough. Codes are operational metadata only.
3. Test every rejection site and relevant empty/null/missing field variant;
   distinguish stale snapshots from invalid relations. Prove diagnostic
   privacy with synthetic canaries and preserve the fail-closed write path.
4. Update release notes and current classifier guidance. No new distributable
   module is required; existing files are already in the framework manifest.

Out of scope: relaxing validation, silently removing invalid relations,
repairing model responses, model/provider changes, inference/retrieval/perf
changes, retries, queues, budgets, private fixtures, platform edits, pinning,
operational replay, merge, or deployment. Hosted delivery follows through a
normal immutable package pin owned by the parent; no separate hosted policy.

## Test Plan

- Extend `tests/test_classifier_context.py` with synthetic parameterized
  failures, exact diagnostic assertions, canary redaction, prompt eligibility,
  null-relation/direct-date preservation, unchanged v1 freshness, and pre-write
  refusal preserving an existing reading and candidate store.
- Run `python3 -m unittest tests.test_classifier_context` and neighboring
  classifier/provider/privacy tests, then serialized full
  `python3 -m unittest discover -s tests -p 'test_*.py'`.
- Run `scripts/ci/check_framework_files.py` and
  `scripts/ci/check_version_bump.py --base origin/main --head HEAD`.
- Draft PR triggers the standard Python 3.11/3.14 CI plus manifest/version
  checks. Builder reports the exact candidate; parent watches CI and owns
  merge/rollout. No agent CI polling or merge.

## Evidence And Done

No viewer changes, so no screenshots or walkthrough are required. Publish
synthetic test results and SHA-pinned code/contract links plus an Owner
closeout comment. Local test success is not live model-quality verification.
Release remains conditional on exact-head CI green and owner review. No
private operational identifiers or payloads enter the issue, PR, or fixtures.
