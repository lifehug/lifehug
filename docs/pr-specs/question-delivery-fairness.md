# Contract: Delivery-Aware Question Selection

## Why

The daily selector records deliveries but does not use them when choosing an
unanswered question. A synthetic bank containing `A7a: update` and ordinary
questions repeatedly selects that short stub after the weekly queue expires.
Successful `ask.py --confirm-sent` increments its count without answering it,
so repeated sends do not change the decision. The silence-triggered selector
has the same defect: the shortest light question wins every day.

This is an In-the-Loop fix to the shared framework, not a host-side filter or
a repair of anyone's vault. The platform's separate maintenance recovery and
subsequent framework pin remain the parent investigation's responsibility.

## Binding Facts

- Base: `origin/main` at `1452cf8384653c96cdffcfa45983d434bda7581d`, version 293.
- Implementation: `system/ask.py`, the authority used by the local daily
  shell, adaptive follow-ups, and the platform's vendored selector.
- Existing state: `rotation.delivery_counts`, `rotation.last_question_id`,
  and each bank row's `answered` flag. No new durable fields or migration.
- `--confirm-sent` records delivery, not an answer. Never check off, rewrite,
  delete, or permanently exclude a question because it was delivered.
- `question_candidates.check_quality` is a soft candidate score, not a
  bank-entry validity gate (ADR 0008). Its short/vague warnings do not justify
  rejecting already-approved short prompts. There is no existing general
  hard placeholder predicate to reuse. Do not add a minimum-word,
  question-mark, or one-off `update` blacklist as a substitute.
- Proposed release: version 294, reallocated at merge if another PR lands.
- Covering issue: https://github.com/lifehug/lifehug/issues/331.

## Scope And Policy

1. Normal delivery still honors the first valid unanswered entry in a healthy
   planned queue. Queue ordering is authoritative, even for a prior delivery.
2. Re-engagement still starts after the configured silent interval, with the
   existing light/non-focus preference. Within that eligible pool, avoid
   `last_question_id` when an alternative exists, then prefer least-delivered
   questions before shortest wording. Retain deterministic existing ordering
   for remaining ties.
3. Without a usable queue, avoid the last unanswered question when an
   unanswered alternative exists, then use the least-delivered cohort before
   applying the existing category coverage/group/focus rotation. Thus a
   low-coverage category containing a repeatedly delivered row cannot
   monopolize fallback.
4. Missing or malformed count metadata has a nonnegative zero default. Counts
   do not make a question ineligible forever. One remaining unanswered
   question remains selectable, regardless of its delivery count.
5. Empty/all-answered banks retain pass-completion behavior. Selection stays
   read-only, model-free, and network-free. Only confirmed sends advance the
   existing delivery bookkeeping.

No bank-content mutation, model calls, provider changes, maintenance changes,
viewer work, private-vault fixtures, or platform edits are in this branch.
Correcting malformed source entries is a separate explicit data decision.

Contract refinement after the first implementation: an executable counterexample
with counts 1 and 100 proved that a last-question tie-break alone still permits
long consecutive repeat streaks. The recency preference therefore comes before
counts, within the existing eligible pool. It lasts only one confirmed delivery,
introduces no clock or cooldown state, and never exhausts a sole question.

## Implementation Notes

- Reuse one delivery-history preference helper between fallback and
  re-engagement; preserve `pick_reengagement_question`'s existing callers by
  making the new rotation input optional.
- Keep `mark_question_sent` semantics and the `ask.py --dry-run` output shape
  unchanged. A platform pin should transport the authority, not mirror it.
- Update the daily-operation docs, research guidance, relevant skill wording,
  and version changelog to describe the bounded policy.

## Test Plan

Use only invented questions and isolated temporary state. Add
`tests/test_question_delivery_fairness.py` and keep the existing v68 controls.
Cases: repeated re-engagement, expired queue fallback with existing counts,
healthy queue authority, silent override of a healthy queue, cross-category
fallback fairness, uneven-history repeat avoidance, deterministic equal-count
ties, missing/malformed counts,
a sole remaining valid question, answered exclusion, empty/all-answered bank,
and actual repeated `--dry-run` / `--confirm-sent` subprocesses proving bank
bytes are unchanged and only confirmation advances counts.

Focused local commands (set `PYTHON` to a working Python 3.11+ executable and
`TMPDIR=/private/tmp` on macOS):

```sh
"$PYTHON" -m unittest discover -s tests -p 'test_question_delivery_fairness.py'
"$PYTHON" -m unittest discover -s tests -p 'test_v68_loop.py'
"$PYTHON" -m unittest discover -s tests -p 'test_ingest_and_planner.py'
"$PYTHON" -m unittest discover -s tests -p 'test_lifehug_wrapper.py'
"$PYTHON" -m unittest discover -s tests -p 'test_pass_transition.py'
"$PYTHON" -m unittest discover -s tests -p 'test_handbook_parity.py'
"$PYTHON" scripts/ci/check_framework_files.py
"$PYTHON" scripts/ci/check_version_bump.py --base origin/main --head HEAD
git diff --check
```

No local full-suite run while sibling agents share the machine. The full
Python matrix in `.github/workflows/ci.yml` is the merge gate; parent owns
draft/ready state, CI monitoring, merge, and the subsequent platform pin.

## Definition Of Done

- [x] Focused regression and compatibility tests pass with no real sends.
- [x] Version, release date, changelog, and affected docs are updated.
- [ ] Covering issue carries synthetic reproduction and verification.
- [ ] Parent receives branch/SHA, exact commands/results, and limitations.
- [ ] Parent verifies the full CI matrix on the implementation SHA.

No viewer surface changes; a visual walkthrough is not applicable. This is
a narrow repair of existing adaptive selection using existing telemetry, not
a new durable-data architecture or a new question-validity policy.

## Local Verification And Pin Boundary

On Python 3.12.14 with an empty temporary HOME, stripped environment,
`TMPDIR=/private/tmp`, and bytecode disabled: fairness 20, v68 27,
ingest/planner 22, wrapper 17, pass transition 1, handbook parity 9 tests
passed (96 total). The manifest check passed for all 540 entries; there are
no manifest additions. New-test Ruff checks pass. The optional Ruff scan of
`ask.py` reports the same seven pre-existing DTZ005/DTZ011 findings as the
base revision; changing time semantics is out of scope.

Red-before-green evidence: repeated confirmed CLI selection kept the stub
dominant before the fix; an additional counts-1-versus-100 unit test failed
in both selectors before the recency refinement. The final regression suite
also verifies healthy queue authority, missing-count confirmation from 1 to
3 for a sole valid question, unchanged bank bytes, and pass completion.

For the subsequent platform pin, the changed overlay closure is exactly
`system/ask.py`, `system/research.md`, and `system/version.json`. There are no
new imports, exported output fields, CLI flags, durable fields, or migrations.
The additional `pick_reengagement_question(..., rotation=None)` input is
optional. The full git export also carries the operating docs, handbook,
maintenance skill, this contract, and the synthetic regression file. A host
must take the shared selector through its normal pin, not copy the policy.

CI source: PR #332, `.github/workflows/ci.yml`, on the final implementation
SHA. The parent checks the full Python 3.11/3.14 matrix and manages PR state;
these local results do not claim a CI verdict or a deployment.

Authorship: Generated with Codex.
