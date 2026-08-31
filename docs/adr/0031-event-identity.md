# ADR 0031 — Event identity: tellings, episodes, operations and bindings

**Status:** Accepted. Shipped in this repo: **I0** (records and
contracts, v265/v266), **I1** (the fold applies bindings, v267), **I2** (the
binder, v268, with v269's live-vault findings — one pair one row, one tally,
the fold's own age frames, the recorder's stem) and **I3** (the questions —
five answers, the split gesture, the listener leaf, v270). I4 (R3 model
proposals, deferred) is not built. Wiring I3's generation into the published
`work-items.json` loop, the owner-reviewed founder dry-run and the
all-tenant backfill runbook are I-P (platform), not this repo.
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
* **Question OUTPUTS, not questions — at I2.** Pairs were emitted as data
  keyed by C4's pair key with the inputs the existing work-item value scoring
  reads, and neither kind was registered in `temporal_projection.WORK_ITEM_KINDS`
  because nothing could file an answer yet. I3 is the phase that ends that.
* **`--dry-run` is the default and the scheduled step is dry by
  construction.** Rollout step 3 says no live bind before I3, so the weekly
  loop reports and the owner's `--apply` is the only door that writes — I3
  builds the confirmation/split/possible_overmerge flows that step needed,
  but the maintenance step ITSELF stays a dry run until the owner's reviewed
  founder dry-run (§8 step 1) authorizes a live one.

Three readings the design left to the phase, each named in code rather than
found in a diff: `CLUSTER_RULE_TEXT` (§4.2 names no envelope for a telling
joining an existing episode, so the deterministic act is one `create` over the
cluster, growth reuses §3.2's supersede-with-alias, and an adopted episode is
never moved); `NON_TRANSITIVE_RULE_TEXT` (Law 3 — a bind needs both sides to
choose each other and no third telling in the same run); and the containment
record, which lands as `proposed` because C2's validator pins the narrow
reading that a `deterministic` origin binds `same` and nothing else.

### What the first live run changed (I2, the founder's vault, 883 tellings)

The binder was run against a read-only clone of the founder's vault before
anything was applied — rollout step 1's own dry run — and it found four things
a nine-telling synthetic fixture structurally could not.

* **A pair was reported twice.** R1 has to judge both directions (four of its
  seven conditions are asymmetric), but a pair is one thing: 4 164 "pairs" were
  2 082. The dedupe is a reporting rule and changes no decision —
  `CANONICAL_DIRECTION_RULE` picks the direction a question is asked in, the
  surviving row carries what either direction refused, and §6.1's per-telling
  cap now counts a pair against **both** its units.
* **Two tallies of one word.** The summary counted `proposals` off the
  containment RECORDS and the verdict line counted `proposal` off the pair
  rows; live they printed `0` and `16` side by side. One tally now, and the
  fields are named for what they count (`proposal_pairs`, `part_of_records`).
* **`age_frames: 0` on a vault with a stated birthday.** Subjects resolve
  inside the fold (v221), so a raw claim carries `subject_ref: None` and the
  owner's own birthday arrives as `subject_mention: "birth"` — the binder's
  private owner-birth predicate matched nothing and the `bounds_in_frame`
  signal was dead on all 883 tellings. The binder no longer owns that
  question: `CalculatedTimeline.age_frames` hands back the frames the fold
  calculated (in-memory, published nowhere), and `FRAMES_COME_FROM_THE_FOLD`
  says why. **The fixture was wrong in the same way** and now files the
  owner's birth the way the vault does.
* **Every dated landmark row was unmatchable.** A recorder telling's subject
  IS the thing — `Etherfuse`, started, 2022-05 — so subtracting the cast from
  the label left a stem of `""`, and its act lives in `event_kind` rather than
  in prose. Both are fixed in `label_stem`: the cast is evidence beside the
  label and never instead of it, and the act is read from wherever a source
  kind keeps it. A shared participant that is only the label again is no
  longer counted as condition 4 evidence, which is strictly more conservative.

**Zero binds was, and remains, the honest verdict of the approved floor.** All
seventeen stem-matching pairs on the founder's vault carry at most ONE
independent non-label signal, so every one is a proposal or a question and
none is a bind. R1 is not mis-tuned there; it is refusing on purpose, and the
gap it exposes is named rather than papered over: the dated landmark and the
undated classifier occurrences of one company share only the entity's NAME, so
a **resolved-entity signal** (v221's own resolution, reused as retrieval
evidence) is the one change that would give those pairs a genuine second
signal. That is a design decision with the owner's name on it, not a threshold
to quietly lower.

## I3 — the questions (v270)

I3 registers `same_event` and `possible_overmerge` in
`temporal_projection.WORK_ITEM_KINDS`, gives both value-scoring defaults and
surfaces beside the five existing kinds, seats them in `WORK_ITEM_PRECEDENCE`
just below `contradiction`, and adds them to Mirror's allowlist (design §6.3:
every actionable Mirror row has Play now). `episode_binder.same_event_work_items`/
`possible_overmerge_work_items` are the pure functions that turn I2's pairwise
outputs into ordinary work items through the SAME scoring formula every other
kind uses — never a priority of their own (§4.1). A new module,
`identity_questions.py`, is the phase's own home:

* **`resolve_same_event_answer`** files Same (confirmed `same`, superseding a
  MACHINE-origin proposal only — a repeated human answer is plain
  create-or-keep idempotency, never a fresh supersession chain), Part of it
  (confirmed `part_of` — already admitted by `validate_event_identity` at
  confirmed/stated origin; only `deterministic` is pinned to `same`, so **no
  C2 validator amendment was needed**), Related (confirmed `related`),
  Different (confirmed `not_same`, pair-permanent), and Not sure (no binding
  at all — an epistemic state, §2.2, filed as a durable bookkeeping deferral
  under `state/`, never under `sources/identity/`). A prospective candidate's
  Same answer files an `authority: human` create — a legitimately different
  id than the `authority: deterministic` id the pair was keyed by, because R1
  already declined the bind.
* **`resolve_possible_overmerge_answer`** dispatches keep together (writes
  nothing — `FORBIDDEN_REAUDIT_ACTIONS` already refuses a system confirm),
  fix the date (writes nothing, names the correction path), part of
  (supersedes `same` with `part_of`), and split (`split_episode`).
* **`split_episode`** files one `split` envelope and calls C4's
  `split_routing` — proven end-to-end on all seven §5.5 reference kinds,
  including the Mirror-judgment residue row for a genuinely unattributable
  reference.
* **The cooldown** — `episode_routing_contract.defer_pair`/`cooldown_active`/
  `material_new_evidence` (`DEFERRAL_COOLDOWN_DAYS = 90`, §12 ruling 3), pure,
  home in C4 beside the pair-key/reaudit logic it sits next to.
* **The listener hears identity too** (§6.4, an ADR 0029 amendment — audit
  B4: ordinary conversation is a source too). `general_listener.Heard` gains a
  fourth typed list, `identity_assertions`, at the end — the v229 `claims`
  precedent, exactly. Hints are resolved against a candidate-context excerpt
  the HOST supplies; zero-or-two matches is a typed refusal, not a guess, and
  clears the backstop the same way `DROPPED_NON_FAMILY` does. A stated
  assertion files `origin: "stated"` through the same writers a directed
  answer uses `origin: "confirmed"` for.

Two new CLI verbs, `resolve-work-item` and `split-episode`, join
`DIRECT_MUTATION_COMMANDS` beside `bind-episodes` and never run inside
`compile` (swept the same way `episode_binder` itself is).

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
