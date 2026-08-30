# Contract — event identity I0 records: C1 (the telling manifest) · C2 (operations and bindings)

**Controlling design:** lifehug-platform `docs/design/event-identity.md` **v4**
— §3.1 for C1, §3.2–§3.3 for C2, with §5.1's era-composition pin, §5.8's
lifecycle matrix and §13.1's promises. Tracking: lifehug-platform#781,
lifehug#295. ADR: [`docs/adr/0031-event-identity.md`](../adr/0031-event-identity.md).

**What I0 is, and is not.** I0 is the executable half of the contracts the
auditor demanded before implementation: record-layer modules and exhaustive
fixtures. It changes **no fold**, adds **no binder**, wires **no CLI verb**,
and groups nothing. Nothing in this contract can change a drawing. The
grouping half is I1; the binder is I2; the questions are I3.

**Delivered by this PR:** contracts **C1** and **C2**, both in
`system/event_identity.py`. C3 (episode/node/era reference semantics and fold
precedence) and C4 (merge/split downstream-reference rules) landed first, as
lifehug#296 / v265 — [`event-identity-i0-fold.md`](event-identity-i0-fold.md),
`system/episode_fold_contract.py`, `system/episode_routing_contract.py`.

**One home for the shared vocabulary (ADR 0021).** `IDENTITY_RULE_VERSION`,
`RELATIONS`, `ORIGINS`, `GROUPING_RELATION` and `GROUPING_ORIGINS` belong to
C3's `episode_fold_contract` and are **imported** here, never restated;
#296's one-home sweep is widened by this PR from `IDENTITY_RULE_VERSION` alone
to all five, scoped to the three modules of this program (`chronology.RELATIONS`
is a different word about a different thing). The record layer adds exactly one
value the fold's four world-assertions do not carry —
`SPLIT_DEPARTURE_RELATION = "none"`, the relation a split leaves behind — and
names it separately rather than growing C3's tuple, so
`BINDING_RELATIONS = RELATIONS + ("none",)` is derived and cannot drift.

---

## C1 — the telling manifest (design §3.1)

### The unit

A **telling** is one source-local account of one event. Three mints, one per
source kind, and a fourth source kind would need its own row here before it
could mint anything:

| Source kind | `telling_ref` | Function |
|---|---|---|
| classifier | `classification:{stem}#{event_key}` | `classifier_telling_ref` (bound to `classifier_claims.event_source_id`, never re-derived) |
| landmark | `landmark:{entry_id}` | `landmark_telling_ref` |
| promoted conversation | `{promoted source id}#{event_key}` | `conversation_telling_ref` |

`TemporalClaim` gains **no field** (design §9 holds). A claim reaches its
telling through what it already carries: the receipt's own declaration
(`extractor[TELLING_KEYS_FIELD]`, durable because a receipt is immutable),
else its `source_ref.source_id` — which for the classifier already *is* the
telling ref.

### The projection

`build_telling_manifest(vault_root)` → `state/temporal_claims/telling_manifest.json`.

Inputs, **all durable**: extraction receipts (immutable, never deleted, so both
the old wording and the new one remain on disk), the corrections that retired
claims, and the identity bindings — whose optional `telling_aliases`
annotation carries a confirmed re-key even if this file is deleted. **Not an
input: the clock.** Nothing in the output is a timestamp, which is why
"delete it and rebuild it byte-identically" is arithmetic and not a hope.

Row keys are frozen as `TELLING_ROW_KEYS`; every row carries every key.

### The re-key transition table

In code as `TELLING_TRANSITIONS` (a tuple of `TellingTransition` rows), read by
the tests rather than restated by them. **Cardinality alone never re-keys.**
Evidence is one of:

* **(a)** an unchanged source locator/span recorded in **both** receipts —
  spans and turn refs, never the evidence *quote*, which is the model's
  transcription and moves when the model does;
* **(b)** a durable recorder-minted event id;
* **(c)** exact agreement on **≥ `MIN_SIGNATURE_AGREEMENT` (= 2)** independent
  components of `SIGNATURE_COMPONENTS` with **zero** contradicting components.

The one-candidate condition is then a **uniqueness gate on top of evidence**,
never evidence itself; and a candidate that co-existed with the retired telling
in the same extraction is excluded (`_cohort_refs`) because it is not what
replaced it.

<!-- parity: event_identity.MIN_SIGNATURE_AGREEMENT = 2 -->
<!-- parity: event_identity.IDENTITY_RULE_VERSION = event-identity:1 -->
<!-- parity: event_identity.MANIFEST_SCHEMA_VERSION = 1 -->

| Case | Trigger | Outcome | Bindings | Diagnostic |
|---|---|---|---|---|
| 1 `extractor_remint` | new extractor version, unchanged words | `same_ref` | untouched | — |
| 2 `reworded` (evident) | one candidate at an unchanged document revision **with** stable evidence | `rekeyed` | carried | — |
| 2 `reworded` (bare) | the same, **without** evidence | `preserve_both` | left on the retired row; the pair becomes a question | `telling_rekey` |
| 3 `fragmented` | one telling becomes two, or two become one, inside one extraction | `retired` | **never** transferred | `telling_fragmented` |
| 4 `source_corrected` | the underlying document's own revision moved | `retired` | follow the superseded claims out | `telling_source_corrected` |
| — `undeclared_document_revision` | no extractor declared the document revision | `preserve_both` | left on the retired row | `telling_document_revision_undeclared` |
| — `durable_alias` | a binding carries the old ref in `telling_aliases` | `rekeyed` | already durable | — |
| — `no_successor` | every claim inactive, nothing replaced it | `retired` | dormant; reported, never an error | — |

### One telling, one event identity

`assert_one_event_identity` refuses a telling whose active claims carry **two
distinct non-era `event_ref` values** (`telling_spans_two_events`) — design
§13.1's *"never a partial bind"*. Era composition is claim-precise per §5.1:

* a claim whose `event_ref` names an **era** is a membership, not a second
  event, and does not cost the telling its eligibility;
* a telling whose claims are **about an era itself** (the tell is an
  `era:<hex>` subject, which only `era_identity`'s own identity claim mints) is
  `episode_eligible: false`, reason `telling_is_about_an_era`.

### Named gap, carried forward to I1

`DOCUMENT_REVISION_FIELD` is **not declared by any extractor today**. The
classifier's claims cite the *classification's* revision, which moves whenever
the model rewords — so without a declared document revision a rewording (case
2) and a human correction (case 4) are indistinguishable. The manifest
therefore takes the **conservative** reading: it re-keys nothing and emits
`telling_document_revision_undeclared`. `declare_tellings()` is the one call
I1 wires into `classifier_claims` and `landmark_recorder`.

---

## C2 — episode operations and the binding lifecycle (design §3.2–§3.3)

### The envelope

`validate_episode_operation` implements §3.2's JSON exactly: `authority`, `op`
(`create | merge | split | adopt | retitle`), `episode_id`, `members`,
`creates_binding_ids`, `supersedes_binding_ids`, `destinations`,
`absorbed_episode_id`, `aliases_created`, `canonical_inputs`,
`canonical_event_kind`, `status`, `supersedes`, `source_ref`, `created_at`.

**Deterministic identity (audit G1).** `OPERATION_IDENTITY_KEYS` is frozen:

```
operation_id = digest("eop", {authority, op, rule_version,
                              member_refs_sorted, acted_on_episode_ids})
episode_id   = digest("episode", {creation_operation_id: operation_id})
```

No invocation id. No wall clock. `episode_id_at_rule_version()` recomputes the
id an **older** rule version would have minted, which is what lets a rule bump
list the old id in `aliases_created` with no stored state to consult.

**One membership authority (audit F2).** Active bindings are the sole grouping
authority; `members` is an audit copy and a drifted one is a **write-time
refusal** (`identity_members_disagree`).

**Transaction semantics (audit G4).** One-commit atomicity belongs to the vault
mutation seat. What this module owns is the ordering that makes a crash inside
the seat recoverable — `file_operation_envelope` writes bindings **first** and
the operation **last**, so a half-run leaves inert bindings nobody has been
told about rather than an operation promising records the vault does not hold —
and the loud refusal for the case the seat could not save:
`load_operation_envelope` raises `identity_envelope_incomplete`, never applies
a partial episode.

### The binding

`IDENTITY_IDENTITY_KEYS = ("telling_ref", "episode_id", "relation",
"rule_version", "supersedes")` — frozen, golden-tested. Everything outside it
(`created_at`, `evidence`, `candidates`, `confidence`) is annotation written
once at create: `file_event_identity` is **create-or-keep**, so meeting an
existing record with the same digest keeps the existing bytes and reports.

**Storage split.** Origin decides the directory, and the directory is CERT-11's
whole promise:

| Origin | Directory |
|---|---|
| `stated`, `confirmed` | `sources/identity/bindings/` |
| `deterministic`, `proposed` | `state/temporal_claims/identities/bindings/` |

Operations split by `authority` the same way. A `deterministic` binding may
only assert `same` (§4.2's narrow floor); anything else is
`identity_deterministic_relation_unsupported`.

**Origin transition.** `proposed → confirmed` files the sources-side record
**with `supersedes`** naming the state-side proposal. `validate_identity_set`
refuses an unsuperseded semantic twin across directories
(`identity_unsuperseded_twin`) and two active grouping bindings for one telling
(`identity_conflict`) — never a recency contest, the same reasoning
`event_binding.event_resolution_index` already uses.

### Lifecycle matrix rows proved here (record level, no fold)

| §5.8 row | Test |
|---|---|
| 1 — two standalone tellings create an episode; replay is a no-op | `CreateEnvelopeTests` |
| 2 — a proposal becomes confirmed (the record half) | `test_row_2_a_proposal_becomes_confirmed_by_superseding_it` |
| 3 — a human adopts a deterministic episode | `AdoptionTests` |
| 4 — an extractor re-mints claims without rewording | `test_case_1_an_extractor_remint_leaves_the_ref_and_the_bindings_alone` |
| 7 — a rule version changes over one adopted and one unadopted episode | `RuleVersionTests` |
| 10 — deterministic state and the manifest are deleted and rebuilt | `DeleteAndRerunTests`, `test_deleting_the_manifest_and_rebuilding_is_byte_identical` |

---

## Fixtures

`tests/test_event_identity_i0_tellings.py`

| Fixture | Proves |
|---|---|
| `fixture_remint` | §3.1 case 1 |
| `fixture_reworded_evident` | §3.1 case 2, re-key |
| `fixture_reworded_bare` | §3.1 case 2, refusal — **cardinality alone never re-keys** |
| `fixture_stable_sibling` | the cohort rule: an untouched sibling is not a successor |
| `fixture_fragmented` | §3.1 case 3, one → two |
| `fixture_merged` | §3.1 case 3, two → one |
| `fixture_corrected` | §3.1 case 4 |
| `fixture_undeclared` | the named gap above |
| `fixture_two_events` | §13.1's manifest-build refusal |
| `fixture_era_composition` | §5.1, within an era vs about an era |
| `fixture_landmark` | the landmark mint and its durable recorder event id |

`tests/test_event_identity_i0_operations.py`

| Fixture | Proves |
|---|---|
| `fixture_create` | matrix row 1 |
| `fixture_adopt` | matrix row 3 |
| `fixture_proposal` | matrix row 2's record half |
| `fixture_split` | §3.2's per-telling destinations |
| `fixture_merge` | §3.2's absorbed id and its alias |
| `fixture_incomplete` (inline) | §3.2/G4's loud refusal |

**Every negative test was run against a build with its guard removed and seen
failing before the guard was written.** The **eighteen** mutations and the
tests each one broke are tabulated in the PR body.

---

## Out of scope, by name

No fold input, no `node_aliases`/`episode_aliases` publication, no containment
edge, no entailment, no retrieval, no R1, no `bind-episodes`, no work-item
kind, no listener leaf, no `CALCULATION_RULE_VERSION` move, no platform pin.
`CLAIM_IDENTITY_KEYS`, `NODE_IDENTITY_KEYS` and `WORK_ITEM_IDENTITY_KEYS` are
byte-identical to v264 and this PR does not read them.
