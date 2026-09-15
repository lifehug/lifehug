# Contract: deterministic quality ladder fixture clock

Machine authorship: Generated with Codex.
Covering issue: lifehug/lifehug#333.

## Measured cause

On main `a6a1feed0e79c5ff9b2de4ba6b2295af8e0c9cee`, all nine
`AutoPromoteLadderTests` pass with `question_candidates.datetime.now`
set to `2026-09-14T23:59:59Z`. At `2026-09-15T00:00:01Z`, the same
synthetic class produces six failures and one error. Its candidates were
created on August 1, so the real 45-day expiry pass now removes them from
promotion before quality scoring. The stamping test's `now_utc` override
does not control the separate `datetime.now` used to calculate age.

## Scope

- Freeze the test class's age and timestamp clocks at its existing August
  14 fixture date, using `unittest.mock` with cleanup.
- Preserve the stamping test's advancing timestamps and every existing
  quality, promotion, dry-run and resurfacing assertion.
- Exercise the class under explicit September 15 and later wall clocks;
  separately retain the real expiry boundary at 45 days.
- Release as version 295 with a test-only changelog entry.
- No production expiry, scoring, framework behavior, vault data, UI,
  platform pin, CI policy, merge or deployment changes.

## Verification

```sh
TMPDIR=/private/tmp PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p 'test_unified_quality_score.py' -v
python3 -B scripts/ci/check_framework_files.py
python3 -B scripts/ci/check_version_bump.py --base a6a1feed0e79c5ff9b2de4ba6b2295af8e0c9cee --head HEAD
git diff --check
```

Use synthetic temporary files only. Run focused adjacent candidate tests,
not the full local suite. Push the contract before implementation. The
parent owns exact-SHA CI review and merge; this worker creates the PR but
does not label, mark ready, merge, deploy or poll CI. No viewer walkthrough
or cross-medium feature twin is needed for a test-clock repair.

## Local evidence

Verified with Python 3.12.14 and `TMPDIR=/private/tmp`:

- Original class at September 14 23:59:59 UTC: nine tests pass. The same
  class at September 15 00:00:01 UTC: six failures and one error, matching
  the hosted current-contract failure exactly.
- Repaired `test_unified_quality_score.py`: 18 tests pass (0.102s). The
  future-clock regression also executes all nine ladder tests under each
  of September 15, 2026 and January 1, 2030. Cleanup restores the outer
  clock after every nested test. The separate expiry test verifies the
  exact 45-day boundary and the following second without changing policy.
- Adjacent focused command: 86 tests pass (24.855s):

```sh
TMPDIR=/private/tmp PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests \
  python3 -B -m unittest test_unified_quality_score test_v68_loop \
  test_v69_signal test_candidate_promotion
```

- Framework manifest: all 540 entries exist. `git diff --check` passes.
- Only the contract, one test file and release metadata change. Production
  modules and every pre-existing assertion remain unchanged. No full local
  suite, live calls, vault changes, CI polling, or platform edits.
