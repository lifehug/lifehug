# Contract: Preserve A Structured Landmark's Atomic Subject

Status: approved narrow policy qualification, 2026-09-15; implementation pending.
Covering issue: lifehug/lifehug#328.

## Why

A confirmed residence labelled `Harbor City, ST` fails during filing with
`write_failure` wrapping `aggregate_subject_mention`. A synthetic real-package
propose/apply reproduction fails with that label, succeeds without its comma,
and succeeds for a comma-free grouped reading containing 76 units and 30 events.
The failure is not proposal size or a missing group. The deterministic landmark
converter discards the question domain's existing `identity_kind` before the
temporal claim validator applies its people-enumeration heuristic.

## Binding Facts

- Base: OSS `85807cdbadab47af776c8d9c54b1f2bb545c662b`, version 295.
  This PR ships version 296.
- `system/landmarks_interaction.py` owns the domain rows and `identity_kind`:
  person, organization, place, relationship_edge, episode. Collection cardinality
  is a different field and must not be changed or inferred from punctuation.
- `system/landmark_projection.py:entry_claims` is the deterministic converter for
  both `legacy-entry-import/rule:1` and `landmark-record/rule:1`.
- `system/temporal_claims.py:split_subject_enumeration` intentionally accepts
  conjunction false positives to protect one-person-per-claim. Its regex and
  word limits stay unchanged. A nonempty `subject_ref` is not proof of identity.
- Raw labels, raw subject mentions, source text, claim identity inputs, date
  semantics, and the first-standing-proposal policy stay unchanged.

## Scope And Policy Qualification

This is an **explicit narrow qualification** of the unconditional enumeration
refusal, not a global relaxation: a deterministic landmark import can preserve
its declared `landmark_domain` as optional claim metadata. Validation derives
the domain's identity kind from the existing framework question set. Only a
declared place or organization is an atomic named non-person for this purpose.
Person, relationship_edge, episode, unknown, and unannotated claims keep the
existing enumeration refusal, including the four-children case.

**Accepted cardinality limitation:** a place/organization type
does not itself prove that a record names only one entity. For example, a
malformed residence record naming `Harbor City and Pine City` would also pass
this qualified temporal guard. The upstream reading still asks for one unit
per residence/school/job, but that is not an independent deterministic proof
that a model never collapsed two into one. Do not describe the type annotation
as that proof or claim that every multi-place/multi-company enumeration remains
refused. The owner explicitly approved this narrow qualification after this
tradeoff was explained. This does not authorize an unrelated relaxation for
people or a claim that a multi-entity reading is valid.

The metadata is accepted only on landmark import claims with the landmark
source identity (`source_ref.source_id` beginning `landmark:entry-`) and one of
the two existing deterministic landmark extractor
versions. It is not model-authorable listener output, a roster resolution, or
permission for a free-text claim to declare itself exempt. A forged ref or
resolution annotation alone never bypasses the guard. The converter derives
metadata from the domain argument, never from a field in the proposed record.
The exact optional field is `landmark_domain: str`, populated only for domain
rows whose `identity_kind` is `place` or `organization`. Invalid annotated
provenance/domain is a typed refusal, not a silent fallback or sanitization.
All existing entry/propose/apply signatures remain unchanged; sibling reading
fixes need not generate or pass this field. The landmark converter owns it.

This adds optional schema-1 annotation, outside claim identity. The annotation
must survive claim dataclass and receipt round trips and active-set readback.
Old unannotated claims retain their behavior. No new roster entries are created
solely to evade punctuation validation. No existing source or receipt is edited.

Out: host comma sanitizing, placeholder grammar, person-list acceptance, new
model prompts, nickname/link interpretation, UI error-state changes, live
replays/applies, private vault fixtures, and platform pin changes. A subsequent
platform pin must consume the exported framework change; behavior is OSS-owned.

## Implementation Notes

Carry `landmark_domain` from `entry_claims` to both identity and date claims;
validate and retain it in the temporal substrate, including `TemporalClaim` and
`claim_from_dict`. Use the existing question-domain authority, not a duplicate
domain allowlist. Keep extractor identity definitions shared with the converter
or add a parity guard so the trusted provenance gate cannot drift silently.
Document the exception as an ADR 0033 amendment and in operating guidance.

## Test Plan

Add focused synthetic regressions in `tests/test_landmark_atomic_subject.py`:

- comma-bearing place and conjunction-bearing organization file successfully;
  their raw labels and mentions survive receipt readback and projection;
- raw people enumeration, person/relationship/episode domain records, unknown
  domains, fake refs, foreign source/extractor metadata, and listener-injected
  metadata retain refusal;
- claim IDs and old unannotated claims are unchanged;
- real package offer apply succeeds for a grouped mixed reading including
  punctuated atomic subjects, and a repeat apply is idempotent;
- the domain decision is derived from the question set and date claims receive
  the same annotation as identity claims.

Exact local command (macOS requires real `/private/tmp`):

```sh
TMPDIR=/private/tmp python3 -m unittest tests.test_landmark_atomic_subject tests.test_temporal_claims tests.test_landmark_projection tests.test_landmark_offer tests.test_identity_resolution tests.test_general_listener
python3 scripts/ci/check_framework_files.py
git diff --check
```

No full suite locally: parent owns the full CI matrix and all PR lifecycle
actions. No viewer code changes, so no browser walkthrough is required.

## Definition Of Done

- Contract committed and pushed before implementation; parent receives boundary.
- Focused tests, docs, version 296, and manifest checks pass with synthetic data.
- Covering issue and draft PR carry reproducible evidence and attribution.
- Parent receives exact implementation SHA and exported file closure for pinning.

Attribution: 🤖 Generated with Codex
