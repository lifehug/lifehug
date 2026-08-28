# Contract: eras-o-bo-birth-origin

**Phase E-BO of the eras program.** Stacked on `feat/eras-o-e1-age-frames`
(lifehug#259), which is itself stacked on `feat/eras-o-e0-immediate-defects`.
Platform tracking issue: lifehug-platform#686.

Controlling design: `~/Desktop/Timeline/02-controlling-design.md` §3.2
(calculated origin), §3.3 (frame arithmetic and grain), §9.1 (test ids
`T-BO-02…09`); the alternative auditor's handoff §5.1 (closed owner rulings)
and §11.1 (release-blocking acceptance); platform `docs/design/eras.md` §13.1
promises tagged **(E-BO)**.

Author of this contract and of the implementation: Claude Opus 5 via Claude Code.

---

## Why

An age frame is only a coordinate system if it has an origin. §3.1 (landed in
O-E0/O-E1) binds the origin to the owner's *explicit* birth claim. But the
founder's own vault, and most vaults at any moment, hold age statements long
before they hold a birthday: *"I was 30 when I started at Etherfuse"*, *"I was
about twelve when we left the farm"*. Today those statements produce
`age_without_birth_anchor` diagnostics, one `missing_anchor birth_date` work
item, and **no scaffold at all** — the Timeline has no axis until someone types
a date, even though the person has already said enough to bound one.

The owner's rulings (handoff §5.1) are unambiguous about what may and may not
be done with that evidence:

- a calculated birth interval **may** seed a visibly provisional scaffold;
- calculated origin is **inside** the commissioned program, not a future idea;
- compatible independent constraints **intersect**; they are **never averaged
  into false precision**;
- disjoint constraints **remain alternatives** and create Mirror work when
  material — *"do not select an arbitrary exact-looking winner"*;
- the explicit-birthday work item **remains open** even when a provisional
  origin exists.

This PR is those five sentences, made mechanical.

## Binding facts (as of this branch's base, `origin/feat/eras-o-e1-age-frames` @ `9c34ddb`)

1. `chronology.add_years(record, years)` exists (O-E1a), takes **negative**
   offsets, preserves grain, and clamps 29 February to the 28th in a target
   year that has none — recording rule `age-frame:1` in provenance.
   `chronology.day_before(iso_day)` exists. There is **no** `day_after`.
2. `chronology.intersect(*records)` returns the tightest bounds all inputs
   allow and **`None` when the inputs are disjoint** — "contradictions belong
   to `reconcile`, which never picks a winner silently". This is the whole
   compatibility test; nothing else needs writing.
3. `chronology.from_age_band(birth, low, high, approximate=…)` is the forward
   arithmetic (birthday + age → interval) and works off `year_of(birth)` only.
   `_age_band(low, high)` is the shared domain guard: whole years, `0..120`,
   low end first, else `None`.
4. `temporal_claims.TemporalQuantity` is `{kind, low, high, unit, approximate,
   text}`; `QUANTITY_UNITS = ("years","months","weeks","days")`.
5. The fold groups claims by (subject, event_kind) — an `age` claim therefore
   lives **in the group of the event it is about**, beside that event's own
   `date`/`range` claims (`_group_claims`). `_record_for_age_claim` returns
   `(None, "age_without_birth_anchor")` when there is no birth anchor, so with
   no explicit birthday the group's reconciled value is derived from its
   **dated claims only** — there is no circularity to break.
6. `temporal_timeline._owner_birth(...)` (O-E1) returns
   `(node_id, {"group":…, "best":…})` or `None`, and `derive_calculated_timeline`
   calls it in the `age_frames` phase, **after** the nodes are built and
   **before** `_derive_work_items`. That single `None` is the hook.
7. `_age_frame_nodes` derives `origin_basis` from
   `temporal_claims.CLAIM_BASIS_BY_DATE_BASIS[record.basis]`, and
   `CLAIM_BASIS_BY_DATE_BASIS["age"] == "calculated"`. A record whose basis is
   `age` therefore publishes `origin_basis: calculated` **with no new
   mapping** — the substrate already knows this.
8. `temporal_projection.validate_calculated_timeline_node` refuses
   `node_without_inputs`: every node, frame included, must cite claims.
   `alternate_values` with `conflict_state: "none"` is refused as
   `node_hides_alternatives`. `best_temporal_value` may be `None`.
9. The projection schema constant is
   `temporal_projection.PROJECTION_SCHEMA_VERSION` (= 2), **not**
   `temporal_claims.SCHEMA_VERSION`.
10. Mirror rows are rendered from `contradiction` work items
    (`mirror_work.row_for`). `derive_row_state` keeps a contradiction **open**
    whenever any active cited claim is undated — and an `age` claim's
    `temporal_value` is a quantity, which `chronology.from_dict` reads as
    undated. `_describe_contradiction`'s `view is None` branch is the one that
    reads correctly for a row whose sides are *derived* readings.
11. The `missing_anchor birth_date` work item is minted from the
    `age_without_birth_anchor` **diagnostics**, not from the absence of a birth
    node. O-E6 is canonicalizing work-item ids concurrently; this PR asserts
    the item by `(kind, requested_field)`, never by a literal id.

## Scope

### O-BO-a — `chronology.birth_origin_from_age(event, age)` (the pure math)

The inverse of `from_age_band`, at full grain. Exact age `a` at an event whose
instant range is `[t0, t1]` puts the birth in `(t0 − (a+1)y, t1 − a·y]`.

- The band comes from the stored quantity through the same `_age_band` domain
  guard `from_age_band` uses; `approximate` widens the band by one year each
  side (Huttenlocher rounding), exactly as `from_age_band` widens its output.
  A unit other than `years` returns `None` — a birth origin from *"about eight
  months"* is a precision this function has no honest way to express.
- The lower bound is **exclusive** and is stored inclusively as the following
  day (`chronology.day_after`, added here beside `day_before` for the same
  reason `day_before` lives there).
- **Rule `birth-origin:1`, the 29 February widening.** The `age-frame:1` clamp
  means a 29 February birthday has its anniversary on the 28th in a non-leap
  year, so it *ages up a day early* and the exact endpoints become
  calendar-dependent. Both endpoints therefore widen by one day around the
  end of February — the upper bound extends from a leap year's 28 February to
  the 29th, and the lower exclusive bound landing on 28/29 February is kept
  rather than advanced. Widening can only over-include a candidate birthday;
  narrowing could exclude the true one. The rule is named in provenance.
- **Grain.** The result's edges are rounded **outward** to the event's own
  grain: a day-grain event gives day edges, a month/season-grain event gives
  month edges, and a year/range/era-grain event gives year edges — *"about
  1980–1981"*. Outward rounding can only widen.
- `confidence = at_most(event.confidence, "inferred")` — §3.2's "confidence ≤
  inferred", through the module's one weakening rule. `basis = "age"`, which
  is what makes `origin_basis` read `calculated` (binding fact 7). The event's
  provenance rides through so `claim_score` still counts distinct sources, and
  one entry naming the age phrase and rule `birth-origin:1` is appended.
- Returns `None` for anything it cannot bound: an unusable event, an
  unrepresentable band, a non-year unit, an event with no bounds at all.

### O-BO-b — `system/birth_origin.py` (the provisional origin)

A NEW module — the fold's `temporal_timeline.py` is being edited by four
sibling branches this session, so everything but the hook lives here.

1. **Gather.** For every group whose subject key is the owner's, that holds at
   least one `age` claim and whose reconciled value is dated, pair the age
   claim with that value and call `birth_origin_from_age`. Both ends therefore
   resolve to `self` by construction — a group is keyed on its subject.
2. **Third-person veto.** An age claim whose stored phrase matches
   `general_listener.THIRD_PERSON_AGE_RES` and does not match
   `cross_dating.AGE_STATEMENT_RES` (which is first-person by construction) is
   skipped even inside an owner group. *"Grandma was 30 in 1951"* never seeds
   the owner, and the guard is deterministic rather than a trust in whoever
   assigned the subject.
3. **Deterministic evidence order.** Constraints sort by: tighter interval
   first (span in days) → finer event grain → stated before approximate →
   higher `chronology.claim_score` → claim id. Total and stable.
4. **Intersect, never average.** `chronology.intersect` over the whole set. A
   non-`None` result is the origin: one interval every piece of evidence
   allows. Two compatible constraints therefore **tighten**; nothing is ever
   averaged, and there is no midpoint anywhere in this module.
5. **Dominance.** §3.2 publishes frames with `origin_basis: calculated` "only
   when one interval strictly dominates by the deterministic evidence order".
   The intersection of a mutually-compatible set IS that one interval — it is
   the unique reading, so it dominates trivially. When the set is disjoint no
   reading dominates: readings are partitioned into maximal compatible
   clusters greedily in evidence order (the tightest evidence first, then
   everything that still agrees with the running intersection), and each
   cluster's intersection is an alternative.
6. **Node emission.** The provisional origin is emitted as the OWNER'S BIRTH
   NODE — `_mint_node_id(event_kind="birth", subject=owner)` — not a second
   identity. That is what makes "an explicit birthday later tightens/replaces
   the view" a value change on **one** node rather than two nodes competing
   for the axis, and it is why nothing has to be deleted when the birthday
   arrives. Fields: `basis: "calculated"`, `origin_basis: "calculated"`,
   `input_claim_refs` = every age and dated claim it was calculated from (so
   the node passes `node_without_inputs`, and so the platform can show its
   working), `alternate_values`, `conflict_state`, `temporal_state`,
   `provenance_summary` = *"Calculated from “I was 30 in June 2011” — no
   birthday on file yet"*.
7. **Disjoint evidence.** `best_temporal_value` is `None` — no winner is
   picked — every cluster reading goes into `alternate_values`,
   `conflict_state: "contradicted"`, `temporal_state: "contradictory"`, frames
   are **withheld**, and one `contradiction` work item is minted citing the
   age claims (binding fact 10: citing the age claims is what makes both
   `derive_row_state` keep the row open and `_describe_contradiction` write
   the sentence that is true — *"Two things you've said about your birthday
   can't both be true"*).
8. **The explicit-birthday work item is untouched.** The provisional origin is
   computed in the `age_frames` phase, long after reconciliation; the age
   claims never got a birth anchor, so `age_without_birth_anchor` is still on
   the diagnostics list and `_derive_work_items` still mints
   `missing_anchor`/`birth_date`. Nothing suppresses it — this is a property of
   *where* the hook is, and it is pinned by a test rather than left to reading.

### O-BO-c — `temporal_state` on a calculated node (additive)

§2.2 lists `temporal_state: unplaced | partial | placed | contradictory` on
`CalculatedTimelineNode`, and O-E1 landed `life_view` (where a node sits
against the life clip) without it. This PR adds the field additively:
`TEMPORAL_STATES`, error code `unknown_temporal_state`, optional and absent
unless set. E-BO sets exactly one value, `contradictory`, on a provisional
origin with disjoint evidence. E2 assigns the other three.

### O-BO-d — the hook (three edits in `temporal_timeline.py`)

```python
origin = _owner_birth(groups, calculated, placed, owner, diagnostics)
provisional = bo.provisional_origin(...) if origin is None else None   # hook
```
plus appending `provisional.node` / taking `provisional.origin`, one line
choosing the frames' provenance sentence, and three lines in
`_derive_work_items` minting the contradiction from the diagnostic
`birth_origin_contradicted`. The bodies of all four live in `birth_origin.py`.

### O-BO-e — `mirror_work` label by requested field

`_label` names a contradiction from the first cited claim's mention and event
kind, which is right for a row whose sides are two dates for one event and
wrong for a row whose sides are two *derived readings* of a different event —
it would read *"about I — graduation"*. A one-entry table keyed on the item's
own `requested_field` (`{"birth_date": "your birthday"}`) fixes it. No existing
row is affected: no existing work item sets `requested_field: birth_date`
except the birth `missing_anchor`, which Mirror does not render (its surfaces
are `timeline`/`whisper`/`daily_question`).

### Out of scope

The birthday-first onboarding conversation (ruled skippable, and this program
does not create a chronology wizard); `named_era` and memberships (E2/E3);
`occurrence_subject_scope` / `owner_timeline_relation` (E2); work-item aliases
and answer-once closure across surfaces (E6); the platform's provisional chip
and its rendering (lifehug-platform#686); `system/version.json` — the release
slot is assigned at green by the coordinator, so this PR deliberately does not
bump it.

## Eight-part answers (design §7 discipline)

| Output | 1 input record | 2 canonical writer | 3 identity / idempotency | 4 correction | 5 fold derivation | 6 aliases / migration | 7 failing-then-passing test | 8 rollout / rollback |
|---|---|---|---|---|---|---|---|---|
| Provisional origin node | the owner's `age` `TemporalClaim`s joined to the dated events they sit on — no new record type, no new file | nobody; the FOLD derives it, and it is deletable with the rest of the projection | the OWNER'S BIRTH node id, `_mint_node_id(birth, self)`; `input_fingerprint` over the cited claims + `CALCULATION_RULE_VERSION` | filing an explicit birth claim replaces the value on the SAME node (the calculated evidence stays in `input_claim_refs` + provenance); correcting an age claim is an ordinary supersede/retract and the fold re-derives | §3.2, in `birth_origin.provisional_origin`, called from the one `_owner_birth is None` hook | none — the node id is the one an explicit birthday already mints, so no alias is needed | T-BO-04, T-BO-06, T-BO-08 | additive nodes/fields; rollback = revert (no receipts written, nothing to migrate) |
| `birth_origin_from_age` | a `DateRecord` + a stored quantity | pure function, no writer | deterministic; rule `birth-origin:1` recorded in provenance | n/a | n/a | n/a | T-BO-02, T-BO-03, T-BO-09 | pure; rollback = revert |
| Origin contradiction (Mirror) | ≥2 disjoint derived readings | the fold, via diagnostic `birth_origin_contradicted` → `_mint_work_item` | `derive_work_item_id` over (kind, subject, event, requested_field) as every other item; re-derivation is idempotent | resolves the moment the age claims stop disagreeing (a supersede, a retract, or an explicit birthday) — `derive_row_state` reads the claims, never the row | §3.2 "disjoint constraints → alternatives + a material Mirror contradiction" | n/a | T-BO-05, T-BO-07 | additive work item; rollback = revert |
| `temporal_state` | n/a (a calculated field) | `validate_calculated_timeline_node` | n/a | n/a | E-BO sets `contradictory`; E2 sets the rest | absent = unchanged, on every v1 and v2 node written so far | T-BO-05 | additive optional field; rollback = revert |

## Test plan — `tests/test_eras_e_bo.py` (every negative SEEN failing first)

Ids are design §9.1's `T-BO` series (`T-BO-01` and `T-BO-01b` belong to O-E0).

- **T-BO-02** exact age at a **day-grain** event: *"I was 30"* on `2011-06-15`
  → birth in `(1980-06-15, 1981-06-15]`, stored `1980-06-16/1981-06-15`, basis
  `age`, confidence `inferred`.
- **T-BO-03** the same age at a **year-grain** event (`2011`) widens to
  `1980/1981` at year edges — *"about 1980–1981"* — and at a **month-grain**
  event (`2011-06`) to `1980-06/1981-06`.
- **T-BO-03b** `approximate` widens by a year each side, and the widened band
  is the same band `from_age_band` would have widened.
- **T-BO-03c** a non-`years` unit, an out-of-domain band, and an unbounded
  event each return `None` — never an invented interval.
- **T-BO-04** two **compatible** constraints TIGHTEN through
  `chronology.intersect`: the intersection is a strict subset of each, and is
  not the midpoint of anything. **Negative half:** assert the result is not
  either input and not an averaged point.
- **T-BO-05** two **disjoint** constraints: `best_temporal_value is None`,
  both readings in `alternate_values`, `conflict_state == "contradicted"`,
  `temporal_state == "contradictory"`, **no `age_frame` node in the
  projection**, and one `contradiction` work item whose Mirror row is `open`
  and whose description is the *"can't both be true"* sentence.
- **T-BO-06** *"Grandma was 30 in 1951"* — a third-person age phrase, and a
  non-owner group — seeds nothing: no provisional origin, no frames.
- **T-BO-07** the explicit-birthday work item (`missing_anchor` /
  `birth_date`) is **OPEN** with a provisional origin, and **ABSENT** once an
  explicit birth claim is filed.
- **T-BO-08** an explicit birth claim ⇒ the provisional path never runs:
  `origin_basis == "explicit"`, the birth node's value is the stated one, and
  the age claims still appear in the node's `input_claim_refs` / provenance —
  the calculated evidence stays.
- **T-BO-09** leap-day edges: a 29 February event, and an upper bound landing
  on 28 February of a leap year, both widen per rule `birth-origin:1`; the
  rule name is in provenance.
- **T-BO-10** determinism: two folds over the same claims in shuffled input
  order produce byte-identical projections (`structural_signature`).

## Launch-and-verify

```
cd ~/Workspace/lifehug
python -m pytest tests/test_eras_e_bo.py -q
python -m pytest tests/test_chronology.py tests/test_cross_dating.py \
  tests/test_temporal_timeline.py tests/test_temporal_projection.py \
  tests/test_mirror_work.py tests/test_handbook_parity.py -q
```

No CLI surface changes, so there is no viewer step: the observable output is
the calculated projection, which the platform reads
(lifehug-platform#686 renders the provisional chip).

## Definition of done

- Every §13.1 promise tagged **(E-BO)** has a named test above.
- Nothing averages. Nothing picks a winner among disjoint readings.
- The explicit-birthday work item stays open with a provisional origin.
- `system/version.json` untouched; the release slot is assigned at green.
