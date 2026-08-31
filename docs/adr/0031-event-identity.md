# ADR 0031 — Event identity: tellings, episodes, operations and bindings

**Status:** Accepted. Shipped in this repo: **I0** (records and
contracts, v265/v266), **I1** (the fold applies bindings, v267) and **I2** (the
binder, v268). I3 (the probe, the five answers, split) and I4 (R3 model
proposals, deferred) are not built.
**Date:** 2026-08-30.
**Controlling design:** lifehug-platform `docs/design/event-identity.md` **v4**
— that document is authoritative; this ADR records the model in this repo's
own vocabulary and says what each phase actually shipped.
**Tracking:** lifehug-platform#781, lifehug#295. Predecessors: #751,
Timeline Fix 05, ADR 0030 (eras), ADR 0024 (chronology with basis).

## Context

The founder's own vault, executed at `5690d37e`: **881 nodes, 703 unplaced**,
and Etherfuse alone is **six of them** — `Etherfuse · 2022-05` from a
work-history landmark, `the idea for Etherfuse · 2021` from a conversation, and
four undated classifier occurrences. Needs-placing is inflated with facts the
person already dated somewhere else, and Play can ask *"when did you start
Etherfuse?"* after they said May 2022.

The cause is structural and is not a bug in any one module. Claim identity is
**by source** (`temporal_claims.CLAIM_IDENTITY_KEYS`); the fold groups by
`event_ref` and then by a derived node id (`temporal_timeline`), and it
deliberately refuses to guess further. Only people are resolved across sources
(v221). Nothing in the substrate says *these two accounts are about one
event* — as the owner put it: *"If I talk about the same thing in five
different ways and I provide facts for them, it doesn't correlate them with
the same thing… we need a system that cross-references things to create a
graph of facts."*

## Decision

Adopt genealogy's **evidence → conclusion** split, with the conclusion layer
free to undo.

1. **A telling is the bound unit**, not a claim. One source-local account of
   one event, which may carry several `TemporalClaim`s. Three mints, one per
   source kind. `TemporalClaim` gains no field.
2. **An episode is an opaque identity**, minted by an explicit
   `episode_operation` receipt and holding no content — the `era_id` pattern
   from ADR 0030, for the same reason: a thing whose identity is its name has
   no identity at all.
3. **Tellings attach to episodes through small, reversible, source-backed
   `event_identity` bindings** — `same` / `part_of` / `related` / `not_same`,
   with origin `stated` / `confirmed` / `deterministic` / `proposed`. `unknown`
   is an epistemic state about a *pair*, lives on the work item, and is
   deliberately not a relation.
4. **Active bindings are the sole grouping authority.** An operation is an
   atomic transaction-and-audit envelope naming, by id, every binding it
   installs and retires; its `members` list is an audit copy and a drifted one
   is a write-time refusal. Two truths about membership is the defect this
   decision exists to prevent.
5. **Deterministic identity digests semantic inputs only** — no invocation id,
   no wall clock — so deleting every deterministic record and re-running on
   identical durable inputs reproduces the same operation ids, episode ids and
   aliases. The **first** human record referencing a deterministic episode
   *adopts* it into `sources/identity/`, after which no state deletion or rule
   change can orphan what the person acted on.
6. **Human decisions are sources; the deterministic layer is state.** Origin
   and authority decide the directory. Deleting `state/` removes what a rule
   can re-derive and keeps every decision a person made.
7. **A miss is cheap; a wrong link is not.** Cardinality is never re-key
   evidence. Deterministic binding is narrow. Ambiguity is a question naming
   the candidates, never a pick.

## What I0 shipped (this ADR's executable half)

`system/event_identity.py` and two test modules (contracts **C1** and **C2**;
C3 and C4 landed first as lifehug#296 / v265 in `episode_fold_contract.py` and
`episode_routing_contract.py`, whose shared vocabulary this module imports
rather than restates): the telling mints, the telling
manifest as a pure projection with a byte-identical rebuild, the four-case
re-key transition table with the evidence rungs, the one-event-per-telling
refusal with era composition, the operation envelope with its deterministic
digest and its completeness refusal, and the binding record with its frozen
identity keys, storage split, canonical-bytes create-or-keep and
origin-transition rule.

**No fold change, no binder, no verb, no work-item kind.** Nothing here can
change a drawing. That is deliberate: the auditor's condition was that
authority, identity, migration and recovery semantics be settled in executable
contracts *before* the phases that consume them.

## What I2 shipped (the binder)

`system/episode_binder.py`, the `bind-episodes` verb and a weekly maintenance
step. This is the first phase that DECIDES a binding rather than applying one:

* **Retrieval** over §4.1's six blocking signals and a zero-model plausibility
  score — one point per independent signal — below which a candidate is
  dropped **silently**, because absence is not a decision.
* **R1**, the deterministic floor, as §4.2's seven conditions in §4.2's order,
  each with its own reason: a kind-family table in code, repeatable protection
  (an undated telling is never auto-bound to a `job`-class episode), exact
  label stems over a fixed event-verb table, two independent non-label
  non-owner signals, one surviving candidate, no active or entailed
  `not_same`, and never joining two episodes that each hold two or more
  tellings. A label-only match is a **proposal**; ambiguity is one question
  naming both candidates.
* **The safeguards ship with it, not after it**: the disjoint-bounds
  over-merge audit, the operation-graph bridge diagnostic, and time-decay (a
  wide-gap place mismatch is `part_of`-suggestive, never a veto). Every §5.6
  re-audit trigger runs through C4's `reaudit`, whose only two outcomes are
  *mint one item* and *do nothing*.
* **Question OUTPUTS, not questions.** Pairs are emitted as data keyed by C4's
  pair key with the inputs the existing work-item value scoring reads. Neither
  `same_event` nor `possible_overmerge` is registered in
  `temporal_projection.WORK_ITEM_KINDS`: I3 owns the probe, the five answers
  and the filing, and a kind whose answer nothing can file is the silent
  under-delivery ADR 0021 refuses.
* **`--dry-run` is the default and the scheduled step is dry by
  construction.** Rollout step 3 says no live bind before I3, so the weekly
  loop reports and the owner's `--apply` is the only door that writes.

Three readings the design left to the phase, each named in code rather than
found in a diff: `CLUSTER_RULE_TEXT` (§4.2 names no envelope for a telling
joining an existing episode, so the deterministic act is one `create` over the
cluster, growth reuses §3.2's supersede-with-alias, and an adopted episode is
never moved); `NON_TRANSITIVE_RULE_TEXT` (Law 3 — a bind needs both sides to
choose each other and no third telling in the same run); and the containment
record, which lands as `proposed` because C2's validator pins the narrow
reading that a `deterministic` origin binds `same` and nothing else.

## Consequences

* Two new record families and two new directories; one module. No new store
  engine, loop, interaction, awaiting state, claim type, claim field,
  dependency or LLM purpose.
* `event_ref` keeps its v247 era meaning untouched. Episode resolution gets its
  own fold input in I1; it does not overwrite an existing slot.
* The three frozen key lists (`CLAIM_IDENTITY_KEYS`, `NODE_IDENTITY_KEYS`,
  `WORK_ITEM_IDENTITY_KEYS`) are unchanged and unread by this phase.
* One honest gap is carried forward rather than papered over: no extractor
  declares a document revision yet, so the manifest cannot distinguish a model
  rewording from a human correction and **refuses to re-key at all** until I1
  wires `declare_tellings()`. Failing toward "ask" is the whole ranking of
  decision 7.
* Rejected alternatives, each for a stated reason: routing episode identity
  through `event_ref` (occupied, and a telling can legitimately need both
  facts); an operations-only model with no bindings (then a split cannot name a
  destination without rewriting history); transitive closure over similarity
  (the canonical disaster of the collective-ER literature); and any promise
  that arrival order can only under-merge (the incremental algorithm does not
  establish it, so the claim is deleted rather than asserted).
