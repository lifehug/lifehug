# Contract: Landmark attribute coverage and individual house identity

## Why

Fix #335 and #336 together without confusing the two defects. Add Landmark
already extracts residence nicknames and location links, but its source
partition only accounts for a short unit quote. Separately, filing a house
nickname currently aliases the containing city. The required result is honest
source coverage and a house that later stories can name independently of its
city and of the separate stays at that house.

## Binding facts

- Base: origin/main 85807cdbadab47af776c8d9c54b1f2bb545c662b, package v295.
  PR337 owns v296; this branch targets v297 after rebasing onto its merge.
  The parent coordinates any change to that merge/version order.
- One model reading remains authoritative. No second interpretation grammar,
  keyword blacklist, global value matching, or model-driven mutation pass.
- The existing name vocabulary is nickname/city/address/place_ref/link.
  Existing valid proposals must remain readable and fileable without another
  model call. Link values remain opaque HTTPS references; no resolution or
  network access is part of this feature.
- Coverage evidence belongs to one unit and one field occurrence. Accepted
  source intervals must be validated against the source and the accepted
  attribute. Partial overlap never covers an entire sentence or paragraph.
- A house is a place; a residence is a stay at that place. House identity does
  not incorporate dates. Repeated stays at the same identified house share a
  place identity but keep separate landmark/episode identities.
- Identity evidence is explicit place_ref, or exact supplied address/city,
  or a uniquely established house name when no address is supplied. No
  geocoding, guessed equivalence, or automatic destructive migration.
- temporal_claims.py and landmark_projection.py belong to the other builder
  and MUST NOT be edited on this branch. Report any required interface change
  to the parent. Existing PRs #330, #252 and #142 are outside this work.
- PR337 adds optional TemporalClaim.landmark_domain, derived only by
  landmark_projection.entry_claims. This branch keeps that call unchanged.

## Scope

In: landmark_offer.py, landmark_reading.py, the reading prompt and additive
schema, the existing go_dig_writer/roster_relations identity path as necessary,
focused tests, version/changelog and behavioral documentation/ADR.

Out: platform changes/pins, maintenance, delivery, atomic-punctuation work,
viewer layout, model changes, live user-data repairs, CI lifecycle and merge.
The parent owns platform parity/pinning, CI dispatch, labels, merge and deploy.

## Implementation notes

### Coverage

Add optional per-attribute evidence to a reading unit. Each evidence item names
the owning field and an exact occurrence, not all occurrences of its value.
The parser validates field survival and source provenance before making that
interval count as recognized. Old readings without evidence remain accepted;
their existing conservative coverage is not silently reinterpreted. Persist
validated evidence on the proposal and use exact interval subtraction for
residuals. Evidence for a dropped/unsafe value must not hide its source text.

Add an explicit reading revision to newly derived proposal identities, keeping
the public derive_proposal_id(text, generation) call shape. A new reading at
the SAME source text and SAME timeline generation must not reuse the old
nonfailed proposal that _save_proposal intentionally retains forever. Old IDs
remain valid for reading/apply/reapply; old documents and applied receipts are
not rewritten. The explicit reading revision is persisted as provenance and
changes only when a reading-contract change requires a fresh proposal, not on
every unrelated framework release. Test this against a saved legacy proposal
at generation 32, with no forced timeline generation change. Hosted current-ID
derivation already delegates to the pinned function and must remain so.

### House identity and compatibility

Reuse the existing place roster, alias authority, located_in relation, and
one-unit recorder. An address-backed house gets stable identity independently
of its nickname and stay dates, and is located in its containing city. Retain
the supplied nickname as its human name/alias. Preserve existing individual
place references and make collisions explicit rather than selecting a first
match. A city-only residence continues to name the city.

Derive this from the validated record at apply time, including old proposals.
Do not rewrite already-filed landmarks or delete/reassign existing city
aliases. Conflicting historical associations must remain conservative and
auditable, never silently merge two homes or manufacture a date. Undo removes
only aliases owned by that apply and must not damage another surviving stay
at the same house. Re-applying an existing receipt remains idempotent.

## Test plan

Synthetic inputs only, real temporary filing/reload and binder where relevant.

- Short date quote with separate nickname/address/link evidence is recognized.
- Repeated values in different units and unrelated prose remain occurrence-
  scoped; partially recognized lines retain their unexplained fragments.
- Invalid evidence, unknown fields and rejected links preserve source text.
- Legacy reading/proposal compatibility, host-completion parity, and source
  coverage conservation across the new evidence shape; same-text/same-gen32
  re-propose makes a current proposal while the legacy proposal and any applied
  receipt remain byte-identical and replayable.
- Actual apply/reload: two houses in one city have distinct place references;
  undated stories naming either house bind only to its stay, without a date.
- Two stays at the same house share the house but retain separate episodes;
  undated story remains stay-ambiguous, and a stated date disambiguates.
- Existing individual references, nickname/address collisions, preexisting
  city aliases, old proposal apply, repeated apply and retraction ownership.

Focused command (new modules added to this invocation as implementation lands):

```sh
TMPDIR=/private/tmp PYTHONPATH=system:tests python3 -m unittest \
  test_landmark_reading test_landmark_offer test_go_dig \
  test_roster_relations test_place_containment test_event_identity_i2b_containers
python3 scripts/ci/check_framework_files.py
python3 scripts/ci/check_version_bump.py --help
git diff --check
```

No full local suite. Parent runs the authoritative remote matrix per SHA.
No serve_wiki.py visual change is planned; no browser walkthrough is required.

## Definition of done

- [ ] Focused coverage, identity, compatibility and semantic tests pass.
- [ ] Version/released/changelog and required docs/ADR updated together.
- [ ] Manifest, diff and policy gates pass; protected files untouched.
- [ ] Branch pushed and self-contained evidence posted on the draft PR.
- [ ] Parent receives exact head, commands/counts and any limits; no agent
  labels, ready/merge/deploy operations, or CI polling.

Generated with Codex.
