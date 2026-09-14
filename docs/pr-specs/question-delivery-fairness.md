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

## Scope And Policy

1. Normal delivery still honors the first valid unanswered entry in a healthy
   planned queue. Queue ordering is authoritative, even for a prior delivery.
2. Re-engagement still starts after the configured silent interval, with the
   existing light/non-focus preference. Within that eligible pool, prefer
   least-delivered questions before shortest wording. Use `last_question_id`
   to break equally-delivered ties away from an immediate repeat; retain
   deterministic existing ordering for remaining ties.
3. Without a usable queue, use the least-delivered unanswered cohort before
   applying the existing category coverage/group/focus rotation. Avoid the
   last question when that cohort contains alternatives. Thus a low-coverage
   category containing a repeatedly delivered row cannot monopolize fallback.
4. Missing or malformed count metadata has a nonnegative zero default. Counts
   do not make a question ineligible forever. One remaining unanswered
   question remains selectable, regardless of its delivery count.
5. Empty/all-answered banks retain pass-completion behavior. Selection stays
   read-only, model-free, and network-free. Only confirmed sends advance the
   existing delivery bookkeeping.

No bank-content mutation, model calls, provider changes, maintenance changes,
viewer work, private-vault fixtures, or platform edits are in this branch.
Correcting malformed source entries is a separate explicit data decision.

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
fallback fairness, deterministic equal-count ties, missing/malformed counts,
a sole remaining valid question, answered exclusion, empty/all-answered bank,
and actual repeated `--dry-run` / `--confirm-sent` subprocesses proving bank
bytes are unchanged and only confirmation advances counts.

Focused local commands (set `PYTHON` to a working Python 3.11+ executable and
`TMPDIR=/private/tmp` on macOS):

```sh
"$PYTHON" -m unittest discover -s tests -p 'test_question_delivery_fairness.py'
"$PYTHON" -m unittest discover -s tests -p 'test_v68_loop.py'
"$PYTHON" -m unittest discover -s tests -p 'test_handbook_parity.py'
"$PYTHON" scripts/ci/check_framework_files.py
"$PYTHON" scripts/ci/check_version_bump.py --base origin/main
git diff --check
```

No local full-suite run while sibling agents share the machine. The full
Python matrix in `.github/workflows/ci.yml` is the merge gate; parent owns
draft/ready state, CI monitoring, merge, and the subsequent platform pin.

## Definition Of Done

- [ ] Focused regression and compatibility tests pass with no real sends.
- [ ] Version, release date, changelog, and affected docs are updated.
- [ ] Covering issue carries synthetic reproduction and verification.
- [ ] Parent receives branch/SHA, exact commands/results, and limitations.
- [ ] Parent verifies the full CI matrix on the implementation SHA.

No viewer surface changes; a visual walkthrough is not applicable. This is
a narrow repair of existing adaptive selection using existing telemetry, not
a new durable-data architecture or a new question-validity policy.

Authorship: Generated with Codex.
