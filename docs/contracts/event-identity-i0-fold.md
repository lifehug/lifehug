# I0-C3 + I0-C4 — fold semantics, id mapping, and the merge/split rules

**Phase I0 of the event-identity program.** Controlling design:
lifehug-platform `docs/design/event-identity.md` **v4** — §3.5, §5.1–§5.4 and
§5.6 for C3; §5.5, §5.6 and the §5.8 lifecycle matrix rows 8, 9, 11 and 12
for C4. Tracking: lifehug#295, lifehug-platform#781. Predecessors: #751,
Timeline Fix 05, ADR 0030.

## What an I0 contract document is

I0 is the phase the independent auditor demanded before any implementation
begins: the four decisions the binder and the fold will make, written as
**pure functions with exhaustive fixtures**, so that I1 wires an
already-proven contract rather than deciding authority, identity and recovery
semantics inside a 4 000-line fold. A contract document in this directory
therefore:

1. names its design sections and does not restate them — the design is the
   authority and a second copy of it would drift;
2. lists the **module** it specifies, the **fixture** file that drives it, and
   the **test** file that proves it, so a reader can go from a promise in §13
   to the assertion that keeps it in two hops;
3. records what the design's wording could NOT be expressed as a pure
   contract, by name, rather than papering over it (the "Where the wording
   needed pinning" section below);
4. states what is deliberately absent, so a later reader does not read a gap
   as an oversight.

Sibling contracts: `event-identity-i0-telling.md` (C1 — telling identity, the
manifest, the four re-key cases) and `event-identity-i0-operations.md` (C2 —
operation envelopes, binding lifecycle, the storage split). C1 and C2 land on
their own branch.

## What this contract delivers

| Piece | Where |
|---|---|
| C3 — the pure fold decisions | `system/episode_fold_contract.py` |
| C4 — the pure merge/split routing | `system/episode_routing_contract.py` |
| C3 fixtures | `tests/goldens/event_identity_i0_fold.json` |
| C4 fixtures | `tests/goldens/event_identity_i0_routing.json` |
| C3 tests | `tests/test_event_identity_i0_fold.py` |
| C4 tests | `tests/test_event_identity_i0_routing.py` |

**Nothing live moves.** `temporal_timeline` is not touched, no claim gains a
field, no record is written anywhere, and `CALCULATION_RULE_VERSION` stays
`timeline-rules:4` — `timeline-rules:5` belongs to I1, where grouping actually
changes and every fingerprint moves with it. A test asserts that, so an I1
branch cannot quietly borrow it early.

> **I1 has since taken it** (`system/episode_fold.py`, v267). The test moved
> with the promise rather than being deleted — it now reads `timeline-rules:5`
> and the next phase that changes the fold's arithmetic takes `:6`. Everything
> else in this document is unchanged: I1 CALLS these functions and
> re-implements none of them.

`IDENTITY_RULE_VERSION = "event-identity:1"` (design §7) is introduced here
and has **exactly one home**, `episode_fold_contract`. Every other module —
C1's manifest, C2's operations and bindings, I1's fold, the platform's own
vocabulary — imports it. `test_identity_rule_version_is_defined_exactly_once`
sweeps `system/*.py` and fails the build on a second assignment; that failure
is the intended outcome, not an accident, and the fix is one import.

## C3 — fold semantics and id mapping

### Grouping (§5.1)

`grouping_key(claim, manifest, active_bindings) -> GroupingKey`, with the rule
written down in the module as `GROUPING_RULE_TEXT` rather than described.
Six closed reasons (`GROUPING_REASONS`), every one reached by a fixture:

| Reason | Fixture case | Design |
|---|---|---|
| `episode_binding` | `bound_telling_groups_under_the_episode_node` | §5.1, §3.5 |
| `episode_binding_composes` | `a_recorder_episode_ref_and_a_binding_compose` | §5.1 last clause |
| `no_binding` | `unbound_telling_keeps_the_existing_key` | §5.1 |
| `no_telling` | `claim_with_no_manifest_row_keeps_the_existing_key` | §3.1 |
| `era_claim_not_groupable` | `a_telling_about_the_era_itself_is_refused_as_a_binding_target` | §5.1, §5.4 |
| `proposal_not_applied` | `a_proposed_binding_groups_nothing` | §2.3 |

The two era cases the audit's F-pin 1 demanded are **both** fixtures and are
asserted beside each other, because the difference between them is the whole
contract: a telling whose claim carries an `era:` ref is about the era itself
(its boundary, its naming) and is refused as a binding target; a telling that
carries no era ref keeps FULL episode eligibility however many era
memberships its node holds, because a membership is a receipt about a node
computed by frame arithmetic after grouping, never a reason to discard a
binding. A telling whose claims disagree about which of the two they are is
`telling_mixes_event_identities` — a refusal, never a partial bind (§13.1).

`kind="existing"` is the contract standing aside: the v264 fold's own key
applies unchanged. I0 deliberately does **not** reimplement
`temporal_timeline._mint_node_id`; a second implementation of the key the
whole substrate is identified by is the defect class this program exists to
remove.

### Ids (§3.5)

`episode_node_id()` is `temporal_projection.derive_node_id` with
`node_kind="episode"` (already in `NODE_KINDS`), the episode's
`canonical_event_kind`, its `subject_keys`, and the `episode_id` as the
**discriminator** — which is what a discriminator is for. `NODE_IDENTITY_KEYS`
does not move, so no existing node id moves;
`episode_node_identity()` exposes the exact digest input so a test pins the
tuple and a human debugging a collision can read it.

`identity_mapping()` publishes `episode_id ↔ node_id` **both ways**:
two identifiers with a durable published mapping, never one identifier
wearing two names. `node_aliases()` publishes every former key of every bound
telling (Law 5) and `episode_aliases()` derives the absorbed-id table from the
operations' own `aliases_created`, so the table cannot drift from the act that
created it.

### Entailment (§2.2)

`entailed_not_same()` computes `same(A,E) ∧ not_same(B,E) ⇒ not_same(A,B)` and
returns it. Nothing is stored, and the reason is a test:
`test_retracting_a_premise_removes_the_entailed_pair` — a persisted closure
would outlive its premise as a phantom negative nobody can find.

### Refusals (§5.4)

`identity_conflict` is raised, for `event_binding.event_resolution_ambiguous`'s
reason: the later record is not more right, it is just later. A dormant
binding is reported and ignored. Bindings found on era-bound claims are
reported at fold time and refused at write time by C2. `FOLD_FINDINGS` is the
closed vocabulary.

### Containment (§5.3)

`possible_outer_range()` mirrors `temporal_timeline._colocation_record`'s
discipline exactly, which is why it is written against
`chronology.DateRecord` and not against a shape of its own. Every clause is
structural rather than checked afterwards: the bounds are the episode's own
bounds copied (never narrower); the function reads `member_value is None` and
nothing else (never overrides, and "discarded the moment the node gains a
value" is free); `anchors` is `()` (never an anchor); the episode's provenance
is dropped and one clause naming the episode takes its place (never
attributes to the person a sentence they did not say); and
`containment_probe()` exists, which is the promise that the member's precision
question survives — better anchored, not suppressed. No new basis is minted:
`order` already publishes as `inferred`.

### Determinism (§5.6)

Two properties, and only two.

1. **Fixed receipts fold byte-identically under any application order.**
   `test_fixed_receipts_fold_identically_under_permuted_orders` permutes
   claims × bindings × manifest rows and compares one
   `grouping_fingerprint`.
2. **Incremental arrival converges; it is not order-independent.** There is
   deliberately **no partition-equality test in this repository**, because v2
   promised it, audit F4 showed the incremental binder cannot deliver it, and
   v4 deleted the promise. `test_two_arrival_orders_can_produce_different_partitions`
   demonstrates the divergence instead of denying it, and
   `test_arrival_order_divergence_is_surfaced_not_resolved` reproduces audit
   G3's own E1-then-E2 case and proves the re-audit NAMES the pair. There is
   likewise no "never an over-merge" claim anywhere.

## C4 — merge and split downstream rules

### The split table (§5.5)

`SPLIT_REFERENCE_RULES` is the table as data — rule, reason and design
reference per row — and `split_routing()` applies it. One test per row, driven
by `tests/goldens/event_identity_i0_routing.json`:

| Reference kind | Destination | Design |
|---|---|---|
| `ordering_constraint` | the side carrying the anchor claim | §5.5 |
| `ordering_constraint` with no anchor | one Mirror judgment row | §5.5 last clause |
| `era_membership` | the surviving episode id; the departing telling gets none | §5.5 |
| `display_decision` | the surviving episode id | §5.5 |
| `episode_label` | the surviving episode id | §5.5, §3.4 |
| `work_item` | re-keys through `work_item_aliases` | §5.5, matrix 12 |
| `open_session` | keeps its target through `node_aliases` | §5.5, matrix 12 |
| `other_decision` | one Mirror judgment row | §5.5 |
| anything unenumerated | one Mirror judgment row | §5.5 |

The governing clause is tested over the whole table at once, not row by row:
`test_no_reference_ever_reaches_two_destinations`. **No post-merge decision is
ever copied to both sides**; an unattributable one becomes one inspectable
`identity_split_unattributable` row naming both candidates.

### Merge (§5.8 row 8)

`merge_routing()` decides nothing — a merge is always human authority in v1 —
and instead proves the envelope moved everything: every active `same` binding
on the absorbed episode must appear in `supersedes_binding_ids`, and the
absorbed id must appear in `aliases_created`. Either omission is
`merge_envelope_incomplete`, because a member keeping a live binding to an id
that no longer draws is exactly the half-applied episode G4 forbids.

### Aliases and the delayed answer (§5.8 row 12)

`resolve_episode_alias()` is written the way
`temporal_work_items.resolve_work_item_id` is — unchanged for an unknown id,
chains followed, cycles terminated — and `resolve_pair()` resolves both halves
of a `(telling, candidate episode)` pair through that one lookup.
`route_delayed_pair_answer()` has exactly three outcomes
(`DELAYED_ANSWER_OUTCOMES`) and the third is the one the matrix exists to pin:
a pair whose **telling** re-keyed away is *acknowledged and dropped with a
note*, never re-pointed at whatever telling now occupies that source, because
§3.1 case 3 says bindings never transfer automatically on a re-key and an
answer is a binding.

### The re-audit (§5.6, audit G3)

`reaudit()` returns `mint_possible_overmerge` or `no_action`, and nothing
else. `FORBIDDEN_REAUDIT_ACTIONS` names `move`, `split`, `keep`, `confirm`,
`rebind` and `drop` so a test can sweep every trigger and every neighbouring
state and assert none of them is reachable. All nine enumerated triggers have
a fixture (`new_telling`, `new_date_evidence`, `new_place_evidence`,
`new_participant_evidence`, `entity_resolution_change`, `telling_rekey`,
`rule_version_change`, `episode_merge`, `maintenance_sweep`); an unknown
trigger is refused rather than accepted, so the enumeration cannot rot. The
item id is keyed on the pair and **not** on the trigger — seven triggers
noticing one ambiguity are one question.

Three no-action cases, each a promise rather than an optimisation: the
candidate is the bound episode; the pair carries an active `not_same` or an
answered record (§13.4 — *a pair answered Different is never proposed or asked
again*); the same item is already open (the dedupe).

## Every negative is proven to fire

The program's bar is that a guard is run against the state where it SHOULD
fail, seen failing, and only then trusted. Two things carry it here. In the
tests, each refusal is asserted in **both** directions — the state that trips
it and the neighbouring state that must not. Outside the tests, the branch was
swept with eighteen deliberate one-line mutations of the two contract modules
(pick the later of two `same` bindings; make era-bound claims groupable; let
proposals group; let a containment override a value, become an anchor, or
inherit the episode's provenance; let an anchorless constraint quietly follow
the survivor; let a merge leave a membership live or forget its alias; let a
split name no destinations; file a re-keyed telling's answer anyway; let the
re-audit keep a bind; stop following alias chains; unsort the pair key; give
`IDENTITY_RULE_VERSION` a second home; …). **All eighteen turned the suite
red.** The sweep is a one-off verification, not a committed harness — a
committed mutation runner would be a second test system to maintain.

## Where the design's wording needed pinning

Recorded rather than papered over, per this directory's rule 3.

1. **§5.4's "two active bindings for one telling without `supersedes`"**,
   read literally, also refuses the five-answer model §6.1 requires: a telling
   legitimately carries `same` to one episode and `not_same` to every episode
   the person has already rejected. The contract pins the narrower reading —
   the conflict is two `same` bindings naming different episodes, or one
   `(telling, episode)` pair decided twice with different relations — and
   `test_same_plus_negatives_on_other_episodes_is_legal` is the case that
   proves the narrower reading is the necessary one.
2. **"the telling is about the era itself" needed a decidable predicate.**
   The design distinguishes the two era cases by intent. The substrate can
   only see evidence, so the contract makes the claim's own `event_ref` prefix
   the predicate: an `era:` ref reaches a claim only through `event_binding`,
   which mints one when the person NAMED that stretch of life in that very
   utterance. A telling about an event within an era carries no era ref at
   all. If a later phase gives the recorder a way to mint an era ref for
   containment, this predicate must move with it — C1's manifest row is where
   the role would then be recorded.
3. **§6.1's pair `event_key` says both `"{telling_ref}|{candidate_episode_id}"`
   and "sorted components".** The contract sorts, because a positional key
   silently depends on which side the caller named first; for the ids in play
   the two spellings coincide, so nothing observable turns on it.
4. **§5.5 does not say where an ordering constraint goes when its anchor
   claim is not a party to the split** (the anchor stayed with the survivor,
   or names a telling neither side holds). The contract routes an anchor that
   stayed to the survivor, and an anchorLESS constraint to a Mirror judgment —
   never a default to the survivor, which would be the "quiet keep" the rule's
   last clause forbids.

## Deliberately absent

* No binder. Retrieval, the plausibility filter and R1's seven conditions are
  I2 (§4.1–§4.2).
* No records, no validators, no writers. Operation envelopes, binding
  lifecycle and the storage split are C2; the telling manifest is C1.
* No work-item kinds. `same_event` and `possible_overmerge` join
  `WORK_ITEM_KINDS` in I3; C4 only names the kind string the re-audit mints
  and the pair key it would carry.
* No `CALCULATION_RULE_VERSION` bump and no `DERIVE_VERSION` conversation —
  I1 and I-P respectively.
