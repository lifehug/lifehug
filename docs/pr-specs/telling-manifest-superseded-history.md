# Contract: Telling Manifest Superseded History

## Why

Classifier re-reading can keep an event's title and description while correcting
its subject interpretation. Its telling ref stays stable, but its derived event
ref changes. Migration explicitly supersedes the earlier claims. The manifest
currently checks all historical claims together and raises
`telling_spans_two_events`, blocking publication despite only one current event
identity. The failure is reproduced with synthetic source data only.

## Binding Facts

- Base: OSS `43b8d08`, v304. This change ships as v305.
- ADR 0031 and the platform event-identity design sections 3.1, 5.4 and 13.1
  control stable tellings, durable lineage, bindings and one-event safety.
- `event_identity.assert_one_event_identity` remains unchanged. Two current
  event refs are still a refusal, never a partial bind or a chosen winner.
- Only an explicitly `superseded` claim is historical for this distinction.
  Disputed, missing-status and unknown-status claims do not get silently removed
  from the one-event guard.
- Receipts, source judgments, claim IDs, telling refs, bindings and their
  authority are immutable inputs. The manifest remains a derived projection.

## Scope And Behavior

1. For a telling with non-superseded claims, validate the standing identity and
   derive its event/era refs, signature, locator and era eligibility from those
   claims. Preserve every historical claim ID and provenance field in the row.
   Active IDs retain their existing exact `active` predicate.
2. A fully superseded telling with one historical event identity retains its
   existing retired-row and evidence-based re-key behavior.
3. A fully superseded telling with multiple historical event identities stays
   visible as a retired row, including all claim IDs and historical refs. Mark
   it ineligible with an explicit diagnostic and do not automatically re-key
   from that ambiguous historical aggregate. Existing explicit durable aliases
   and human binding records remain authoritative and unchanged.
4. Preserve the existing rules for actual event splits, collisions, source
   corrections and evidence-supported re-keying. No global validator relaxation,
   identity merge, receipt rewrite or guessed latest historical identity.

Only the confirmed historical-identity manifest defect is in scope. Duplicate
event receipt collisions, model prompts, classification schemas, logging,
platform changes, private data and live operations are excluded.

## Implementation Notes

The bounded change belongs in `event_identity._telling_row`, manifest
diagnostics and `_apply_rekeys`. The public one-event validator stays strict.
No new durable record family or runtime dependency is needed.

## Verification

- Real classifier migration: same words, revised subject, supersession, one
  current identity, publication succeeds, old receipt bytes remain unchanged.
- Human binding filed before reclassification remains present and associated
  with the stable telling; no synthesized aliases or replacement decisions.
- Re-run migration and delete/rebuild the manifest: idempotent derived output
  and preserved receipt/history bytes.
- Two active identities still refuse; active plus disputed different identity
  still refuses; missing/unknown status is not treated as supersession.
- Fully retired singular history keeps existing re-key behavior; mixed retired
  history remains diagnostic and cannot transfer a binding automatically.
- Existing identity/re-key/split/collision and classifier suites remain green.
- Full OSS unittest suite, framework manifest and version-bump gates pass.

Commands use `TMPDIR=/private/tmp PYTHONDONTWRITEBYTECODE=1 python3 -B`:

```sh
python3 -B -m unittest discover -s tests -p 'test_event_identity*.py'
python3 -B -m unittest discover -s tests -p 'test_classifier*.py'
python3 -B -m unittest discover -s tests -p 'test_*.py'
python3 -B scripts/ci/check_framework_files.py
python3 -B scripts/ci/check_version_bump.py --base origin/main --head HEAD
```

## Definition Of Done

- [x] Narrow implementation and synthetic regressions complete.
- [ ] Focused and full local suites plus version/manifest gates pass.
- [x] Version, changelog and identity documentation updated together.
- [ ] Immutable candidate pushed with exact command/result evidence.

Parent owns CI dispatch, readiness, merge, platform pin and live verification.

Generated with Codex.
