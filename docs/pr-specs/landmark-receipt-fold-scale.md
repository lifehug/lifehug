# Landmark Receipt Fold Scale

Generated with Codex.

## Problem And Scope

Follow-up to v298 / PR339, consumed by lifehug-platform PR847. The owner
authorized fixing and exercising Add Landmark until a complete document
can be filed through staging, followed by a normal green merge. The v298
candidate's populated synthetic hosted gate passed, but the actual filing
still exhausted the unchanged 90-second package budget on both attempts.
There is no verified successful live receipt. Do not claim the incident is
resolved from CI alone.

Existing synthetic profiling provides a concrete remaining bottleneck:
76 unit writes still redraw landmarks eagerly, producing 78 active-index
folds and 81,216 receipt reads over a 1,000-moment archive. In the contended
local profile, receipt loading accounts for 250 of 307 seconds. Those wall
times are not stable performance promises, but repeated whole-archive work
is a structural problem independent of machine speed. v298 already batches
calculated publication once and caches parsed receipts with file validation.

Optimize the remaining repeated receipt traversal/fold work within the
existing confirmed filing act. First profile the remaining costs on a
disposable synthetic vault and state the chosen bounded mechanism in the
evidence. Prefer existing store/publication boundaries, not another writer
or a parallel projection implementation. New policy or durable-data format
changes are outside this repair.

The read-only follow-up profile narrows the implementation: a warm fold of
1,107 synthetic receipts / 1,260 claims takes 0.398 seconds unprofiled; one
profiled fold makes 28,808 stat calls and 4,430 directory scans. Receipt
loading occupies 91% of that profiled fold. Index serialization is only
0.038 seconds. Therefore extend the existing bounded receipt cache with a
contained directory inventory: discover once, refresh changed directory
listings before each fold, and check existing receipt signatures each fold.
Validate shared ancestors once per refresh using no-follow protections
instead of repeatedly checking the whole path for every cached receipt.
Keep the full authoritative fold, sequential landmark redraws, active-index
writes and calculated publication unchanged. Do not add an incremental or
landmark-only fold, or defer active-index writes, in this repair.

## Invariants

- The existing landmark writer remains authoritative. Every intermediate
  landmark result used for identity, repeated stays, alias binding, ordinals,
  supersession and subsequent writes must see the current filing state.
- Receipt/correction precedence, source revisions, evidence, immutable IDs,
  gains, opportunity retirement and final calculated output retain their
  semantics. A performance optimization must not discard unrelated claims.
- No stale-cache loophole: new, changed, deleted, corrupt or repaired receipt
  files and corrections must be observed or explicitly fail closed. Keep
  vault containment and symlink guards, including after scope entry. Do not
  weaken path validation to save time.
- Any transient cache or batching state is root-bound, nested-scope safe,
  closed on every exit and unavailable to escaped contexts or another vault.
  Mutable results must not let callers corrupt future cached results.
- Final publication precedes the success receipt. Failure cannot emit a
  success receipt; retry reaches the same durable result. A receipt replay
  performs no new filing, publication, alias work or model call.
- Do not increase any host execution budget, introduce a new model call,
  bypass the host lease/atomic commit, edit vendor code in the platform,
  or use private data as a fixture, benchmark or development target.

## Verification

Add focused structural and equivalence regressions that make the repeated
whole-archive cost visible without fragile wall-clock assertions. Compare
the optimized result against the existing eager/reference behavior using
synthetic receipts, corrections, re-extractions, repeated residence stays,
house aliases and grouped events. Cover changed/corrupt/repaired inputs,
root changes, nested scopes, escaped contexts, exceptions and immutable
replay. Run the affected store, landmark, publication and recorder suites.

Record a same-machine before/after synthetic profile with archive and unit
counts, the changed call counts and stage durations. Serialize expensive
local runs. Include a populated archive with at least 1,000 moments and
nontrivial evidence/corrections plus a grouped 76-unit filing with house
nicknames/addresses/map links; all names and URLs must be invented.
The platform must then exercise its real one-apply-under-90-seconds gate
using the exact immutable candidate. Passing this synthetic benchmark is
necessary, not sufficient: parent-owned authorized live UI filing remains
the final incident check.

Run the normal OSS CI matrix and manifest/version checks. Bump the next
version (299 unless main changes), update release notes and affected docs
in the same implementation. No visible OSS UI change is intended; the
viewable surface is the platform staging timeline consuming this package.

## Delivery

Worktree: `/private/tmp/lifehug-landmark-receipt-fold-scale`, branch
`codex/landmark-receipt-fold-scale`, based on merged v298 main. The builder
may edit the relevant package modules, focused tests and matching docs and
version metadata; unrelated refactors are excluded. Record honest evidence
and push only this branch. The parent owns PR readiness, release holds,
the hosted pin, full-CI dispatches, deployment and normal merges. Never
push main directly or merge around a failed gate.

Look: synthetic profile and executable regression tests, then staging
Add Landmark with the exact reviewed immutable package.
Judge: no new product policy or interpretation of the user's source.
Done when: exact-head CI is green, the host budget gate passes, the actual
filing is verified durably, and both repositories complete normal merges
with staging back on full-CI-green main. If live evidence exposes another
cause, continue diagnosis instead of declaring success.

## Implementation Evidence (2026-09-15)

Run from the candidate checkout, optionally passing an older OSS checkout to
`--framework` for a reference comparison:

```bash
python3 -B tests/benchmark_landmark_receipt_fold.py --moments 1000
python3 -B tests/benchmark_landmark_receipt_fold.py --moments 1000 --framework /path/to/v298
```

The script uses the platform temporary directory and resolves it before
creating a disposable synthetic vault. On macOS the repo test convention is
`TMPDIR=/private/tmp`. On Linux the benchmark pins its own process to one CPU
from its allowed affinity set; no system-wide setting is changed. On macOS
affinity is unavailable and the output says so. No private fixture or live
model call is used.

Serialized same-machine Python 3.12 / macOS runs compared v298
`1aca370f8ce304a4d4b18867e7c81bcb55706c3b` with this implementation. Both
started with 1,000 moments, 37 landmark sources, 1,087 receipts, 1,160 claims
and 50 corrections; the calculated projection was 2,382,270 bytes. The
filing contained 76 residence units with invented house addresses, nicknames
and map links, plus 10 grouped events. Both produced 76 filed names and the
same complete active-index fold oracle, then replayed without changing any
vault bytes.

| Measurement | v298 | v299 candidate |
| --- | ---: | ---: |
| Apply wall seconds | 51.430 | 27.677 |
| Apply process CPU seconds | 49.974 | 27.127 |
| Directory enumerations | 336,558 | 2,789 |
| `os.stat` calls | 2,443,917 | 608,639 |
| `os.fstat` calls | 16,368 | 521,914 |
| `os.open` calls | 79,765 | 253,833 |
| Ordinary receipt reader calls | 87,884 | 1,173 |
| Receipt loading seconds (inclusive) | 34.797 | 11.206 |
| Full fold seconds (inclusive) | 39.548 | 16.172 |
| Active-index write seconds | 4.051 | 3.926 |
| Full folds / index writes | 78 / 78 | 78 / 78 |
| Landmark redraws / calculated publications | 77 / 1 | 77 / 1 |

The descriptor checks intentionally increase `fstat` and `open` counts while
removing repeated directory enumeration and full-path validation. Inclusive
phase durations overlap and must not be summed. A subsequent small smoke
used the portable temp-directory command and additionally asserted every
one of the 76 alias operations was applied. That assertion was added after
the large comparison had started; it was not part of those recorded runs.

Local affected-suite verification passed on Python 3.12: 36 focused inventory
and publication/cache tests; 275 temporal tests; 664 landmark tests (four
existing skips); and 89 vault-only, roster and extraction/recorder tests.
The landmark suite also reran the original populated-archive regression.
The 36 focused tests overlap the landmark suite. Manifest validation found
all 543 distributed files, and `git diff --check` was clean.

These are single-threaded local measurements, not a Cloud Run performance
verdict. The exact immutable candidate still requires full OSS CI, the
hosted one-attempt 90-second gate, and parent-owned durable live UI filing
verification. No execution budget was increased.
