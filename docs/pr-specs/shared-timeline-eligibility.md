# Contract: Shared Timeline Candidate Eligibility

Generated with Codex.

## Why

Issue #352: incremental classification omits candidate eligibility instructions
that full extraction already receives. The canonical validator correctly refuses
these unsupported links; both prompts must teach the same requirements.

## Binding Facts

- Base: main v308, `fca3452c8622f1335f89e26f5c40e62eea3554a6`; ship v309.
- One shared instruction block in `system/classify_story.py` is included
  verbatim once in both full and timeline prompts.
- Timeline resolution copies exactly
  `event_contexts[event_key].candidate_ids`, including alternatives and
  ineligible candidates. It never recomputes or filters that list. A relation
  may select only an eligible member of that event-local set.
- Selected candidates have empty `unresolved_entity_mentions` and
  `entity_ref_ambiguities`; refs are nonempty exact candidate refs; evidence
  is an exact unique source quote that distinguishes competing candidates.
- Expose a sorted `identity_blocked_candidate_ids` list in both rendered
  canonical contexts. Derive it from the same pure
  `classifier_context.candidate_identity_is_resolved(candidate)` predicate
  called by validation, preserving the existing truthiness check exactly.
  This is presentation of existing facts, not a snapshot/schema field: do not
  mutate stored snapshots, candidate membership, fingerprints, or digests.
  Blocked IDs remain in resolution lists but cannot be selected for links.
- Resolution follows the existing closed status contract and event-local
  completeness. A complete empty set is missing evidence, not incomplete.
- Source grounding is null when the immutable direct date/age lacks an exact
  same-subject proof. A valid relative link is independently allowed.
- Validator policy, runtime selection/filing/folding, outer schemas, context/prompt
  and extractor versions remain unchanged. Valid cached results stay current.

## Scope

Prompt composition and pure identity-predicate extraction, synthetic prompt
parity and negative tests, the existing
timeline evidence evaluation harness and fixtures, docs and framework version.
No private vault reads, writes, copied excerpts, or tests. No retry or repair
system. Hosted parity uses the same package prompt; the parent owns its pin.

## Test Plan

Run `python3 -m unittest tests.test_classifier_context
tests.test_archive_classification_batch tests.test_timeline_evidence_evals` and
the full OSS suite. Assert the shared block occurs verbatim in both prompts;
ineligible candidates cannot be linked; all supplied event-local IDs survive
abstention; source grounding and relative linking remain independent.
Assert rendered blocked-ID parity, clean-candidate eligibility, unchanged
snapshots/metadata, and the exact original validator identity predicate.

Extend `system/timeline_evidence_evals.py` with synthetic unresolved/ambiguous
candidate scenarios. Run both full and timeline recorded evaluation, separating
plumbing from quality. When the established safe credential mechanism is
available, run synthetic live cases using hosted `claude-sonnet-5`, thinking
disabled, 16384 output tokens; report actual policy, outcomes and limitations.

## Delivery

Commit and push only this isolated branch, open a draft PR, post commands and
results on the PR and issue, and dispatch normal CI. Do not label, mark ready,
merge, or access the private archive. No visible UI changes require a walkthrough.
