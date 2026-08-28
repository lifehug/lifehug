# Contract: eras-o-e6-work-items

Phase **E6-core** of the Eras / Timeline program, OSS half (`O-E6`). Stacked
on `feat/eras-o-e0-immediate-defects`. Platform tracking: lifehug-platform
**#686**; platform sibling `P-E6` (hosted weekly proof, whisper suppression by
id, `questions/today.work_item_id` on the API surface). Controlling authority:
lifehug-platform `docs/design/eras.md` (v3.1) §3.2, §5.4, §7 row *Work item
(birth origin)*, §10, and ADR 0030 (this repo). The auditor's handoff §7.7 is
binding on identity: *birth/anchor questions from the keystone path and the
substrate path converge on ONE canonical requested-field vocabulary and ONE
work id; stored references resolve through an explicit alias map; node aliases
are not assumed to alias work ids.*

## Why

Three defects, all executed against this checkout before a line was changed.

1. **Two work ids for one birth gap.** The substrate mints the owner's missing
   birthday as `missing_anchor / self / birth_date`; the keystone lane mints
   the same question as `missing_anchor / <anchor> / temporal_anchor`. Probed
   on unmodified `feat/eras-o-e0-immediate-defects`:

   ```
   substrate   work:c7f235f83e306d76b64fd4ce
   keystone    work:5b18d0f7579cf7dfd0cab911
   SAME?       False
   ```

   Answer-once closure is by id. Two ids means the person can answer their own
   birthday on Timeline and still be asked for it by the daily question, and
   the whisper lane cannot suppress the item the day is already asking.

2. **The birth-origin item only exists when something already tripped over
   it.** `_derive_work_items` mints the `birth_date` ask *only* when the
   diagnostics carry an `age_without_birth_anchor` finding. A vault with no
   birthday and no age statements mints nothing — probed: `birth items: 0` —
   so the coordinate system the whole Eras design rests on (`eras.md` §3, age
   frames derived from the birth origin) has no question asking for it.

3. **Its value is stated as reach alone.** `system_value = min(1.0,
   age_claims / REACH_SATURATION)` is zero when nothing has been dated by age
   yet, so the one item that unlocks the coordinate system scores below
   `work_item_queue_threshold` (0.45) on exactly the vault that needs it most.

## Binding facts (as of `feat/eras-o-e0-immediate-defects`, `19dfa4f`, v234 + E0)

- `system/temporal_projection.py`
  - `WORK_ITEM_IDENTITY_KEYS = ("kind", "subject_key", "event_key",
    "requested_field")` `:140` — FROZEN for schema version 1. `event_kind` is
    **not** in the digest, so `subject_ref` and `requested_field` carry the
    whole identity of a subject-only ask.
  - `derive_work_item_id` `:212-233`; `validate_temporal_work_item` `:555-645`
    drops unknown keys, which is why a per-item score rule needs a declared
    field rather than a passenger key.
- `system/temporal_timeline.py`
  - `REACH_SATURATION = 5` `:149`; `DEFAULT_OWNER_REF = "self"` `:223`.
  - `SCORE_FORMULA_VERSION = "temporal-score:1"` `:130`.
  - `_derive_work_items` `:1568-1830`; the birth rung `:1646-1676` gated on
    `age_without_birth_anchor`.
  - `tc.CLAIM_BASIS_BY_DATE_BASIS` `:1185-1186` is the ONE mapping from a
    `chronology` date basis to the `explicit | calculated | inferred` class a
    node publishes.
- `system/question_planner.py`
  - `TIMELINE_REQUESTED_FIELD = "temporal_anchor"` `:1113`;
    `timeline_work_item_id` `:1142-1173`; `work_item_from_keystone`
    `:1176-1207`.
  - `bank_work_items` `:1427-1460` — the answer-once ledger, keyed by the
    `work_item:` marker in the bank's provenance comment, falling back to the
    anchor-derived id for a pre-wave-F row.
  - `_published_work_items` `:1284-1293` reads `state/temporal_claims/
    work-items.json`.
- `system/timeline.py` — `keystones` `:1906-1951`; `unknown_anchor`
  `:1715-1754`; the `anchors` index keys the owner's birth as `"birth"`
  `:3038`.
- `system/mirror_work.py` — `resolve_mirror_item` `:951-1060` files a
  correction (and optionally a replacement receipt) and **returns without
  publishing**. Verified by reading: no `temporal_publication` import exists
  in the module at this revision.
- `system/timeline_interaction.py` — `work_item_target` `:614-700` reads
  `work_item_id` / `ref` off a stored target verbatim.

## The eight-part answer (design §7 discipline)

Output under contract: **the birth-origin work item**, plus the identity
vocabulary and alias map every other work item now shares.

| # | | |
|---|---|---|
| 1 | **Authoritative input record** | The **absence** of an owner birth node whose published class is `explicit`. Not a record of its own: the item is a pure function of the fold, so nothing has to be written to open it and nothing has to be written to close it. |
| 2 | **Canonical writer** | The fold — `temporal_timeline._derive_work_items`. No other module mints it. The keystone lane ADAPTS (`question_planner.work_item_from_keystone`) and must land on the same id. |
| 3 | **Identity / idempotency** | `WORK_ITEM_IDENTITY_KEYS` over the **canonical** tuple `("missing_anchor", "self", None, "birth_date")` — `temporal_work_items.birth_origin_work_item_id()`. Deriving it twice, from either lane, is the same 24 hex. |
| 4 | **Correction** | The item closes when an owner birth claim exists and the node it folds to publishes `basis: explicit`. A **provisional (calculated) origin does not close it** (`eras.md` §3.2: *"the explicit-birthday work item stays open"*) — the predicate is the basis class, not the presence of a node, so E-BO's provisional origin needs no new flag to keep the item open. Answering closes it by making the fold stop minting it; the bank row ticks through the existing `work_item:` marker. |
| 5 | **Fold derivation** | `system_value = clamp(SCAFFOLD_VALUE + min(REACH_CEILING, age_claims / REACH_SATURATION), 0, 1)` with `SCAFFOLD_VALUE = 0.6`, `REACH_CEILING = 0.4`, `REACH_SATURATION = 5`, under rule id **`temporal-score:2`**, recorded on the item itself as `score_rule` and on the projection envelope as `SCORE_FORMULA_VERSION`. The scaffold term is the honest statement that the birth origin is the coordinate system, not one more gap; the reach term is the ordinary evidence. |
| 6 | **Aliases / migration** | A derived `work_item_aliases: {legacy_id: canonical_id}` map, published in the SAME generation as the items it describes (`work-items.json`, atomic publish). Derived by re-minting every canonical item under the legacy `requested_field` vocabulary (`temporal_anchor`) and, for the birth origin only, under every legacy birth-anchor SUBJECT spelling. `resolve_work_item_id(ref, aliases=…)` is the ONE lookup; a legacy id NEVER crosses `kind` (a `precision_gap` on a known-but-coarse birthday is a different question and is not aliased to the `missing_anchor`). Two canonical items claiming one legacy id drop the alias rather than guess. |
| 7 | **Failing-then-passing test** | T-Q-01…07 below. Every negative is run against unmodified code and seen failing first. |
| 8 | **Rollout / rollback** | `work_item_aliases` and `score_rule` are ADDITIVE keys with defaults; readers that do not know them are unaffected, and rollback simply ignores them. `SCORE_FORMULA_VERSION` moving to `temporal-score:2` is the declared signal that a queue built earlier is not comparable — it is never silently comparable. |

## What changes

1. **`system/temporal_work_items.py` (new).** The vocabulary and the arithmetic,
   in one module so the fold's merge surface stays one function wide:
   - `CANONICAL_REQUESTED_FIELDS = ("birth_date", "date", "start_date",
     "order")` — the substrate's vocabulary, which wins; `LEGACY_REQUESTED_FIELD
     = "temporal_anchor"` is the keystone lane's single old spelling and is
     the ONLY place that string may appear in `system/`.
   - `canonical_requested_field`, `canonical_ask`, `canonical_work_item_id`,
     `birth_origin_work_item_id`, `is_birth_anchor`.
   - `birth_origin_system_value`, `BIRTH_ORIGIN_SCORE_RULE`, `REACH_SATURATION`
     (moved here as its single definition; `temporal_timeline` re-exports it),
     `OWNER_SUBJECT_REF` (likewise for `DEFAULT_OWNER_REF`).
   - `node_claim_basis(record)` — the `explicit | calculated | inferred` class
     of a date record, extracted from the fold's node builder so the closure
     predicate and the published node cannot disagree.
   - `legacy_work_item_ids`, `work_item_aliases`, `resolve_work_item_id`.
2. **`temporal_timeline._derive_work_items`** — the birth rung mints whenever
   no EXPLICIT owner birth node exists (not only when an age claim tripped
   over it), scores under `temporal-score:2`, and stamps `score_rule`. The
   result carries `work_item_aliases`.
3. **`temporal_projection`** — `score_rule` becomes a declared optional field
   on `TemporalWorkItem` so the rule survives the validator.
4. **`temporal_publication`** — `work_items_payload` carries
   `work_item_aliases`; `structural_signature` covers it (it is derived, so a
   rebuild reproduces it exactly).
5. **`question_planner`** — `timeline_work_item_id` and
   `work_item_from_keystone` canonicalize; `bank_work_items`,
   `work_item_states_from_bank`, `close_answered_work_items`,
   `queue_candidates`, `mint_queue_questions`, `current_timeline_probes`
   resolve stored ids through the published map.
6. **`timeline.keystones`** — each row carries its canonical `work_item_id`,
   which is what lets the platform put `work_item_id` on `questions/today`
   beside the existing `tl:<slug>`.
7. **`timeline_interaction.work_item_target`** — resolves the target's stored
   id through the map, so a session opened under a legacy id keeps opening.
8. **`mirror_work.resolve_mirror_item`** — publishes after the correction is
   durable (design §10). Failure is LOUD (`resolution_publish_failed`, naming
   the correction id) — never a silent stale projection, and never a lost
   correction, since every write on this path is content-keyed and a retry is
   a no-op.

## Tests — T-Q-01…07 (every negative seen failing first)

| id | statement | where |
|---|---|---|
| **T-Q-01** | The birth-origin item exists on a birthless vault with NO age claims, and scores above `work_item_queue_threshold` without any priority class. | `tests/test_temporal_timeline.py`, `tests/test_work_item_queue.py` |
| **T-Q-02** | Its `system_value` is `0.6` with no age claims and saturates at `1.0`; the rule id `temporal-score:2` is on the item and on the envelope. | `tests/test_temporal_timeline.py` |
| **T-Q-03** | **One id, keystone ≡ substrate.** `timeline_work_item_id(anchor="birth")`, `work_item_from_keystone`, and the fold's own item are the same `work:` id. Seen failing first (probe above). | `tests/test_work_item_aliases.py` |
| **T-Q-04** | **Answer-once across surfaces.** A bank row minted under the LEGACY id ticks the CANONICAL item: it is `answered`, is not re-minted, and is not whispered. `keystones()` rows carry the id `questions/today` needs. | `tests/test_work_item_aliases.py`, `tests/test_work_item_queue.py` |
| **T-Q-05** | An explicit birth claim closes the item; a **calculated** origin does not. | `tests/test_temporal_timeline.py` |
| **T-Q-06** | `resolve_mirror_item` publishes: the generation advances and the resolved row is gone from the published items on the next read. A publish failure is raised by name with the correction id, and the correction survives it. | `tests/test_mirror_work.py` |
| **T-Q-07** | **Old and new ids cannot mint two questions for one subject.** The alias map is published in the same generation; `resolve_work_item_id` is the one lookup; every declared reference door canonicalizes; the legacy spelling appears in exactly one module; an ambiguous alias is dropped, never guessed. | `tests/test_work_item_aliases.py` |

## Launch and verify

```bash
cd ~/Workspace/lifehug
python3 -m pytest -q tests/test_temporal_timeline.py tests/test_temporal_projection.py \
  tests/test_projection_publication.py tests/test_work_item_queue.py \
  tests/test_work_item_aliases.py tests/test_mirror_work.py \
  tests/test_timeline_work_item.py tests/test_timeline_whispers.py
```

Then, on any vault with claims and no birthday:

```bash
python3 system/lifehug.py timeline-publish   # or the fold's own entry point
python3 -c "import json,pathlib; \
  d=json.loads(pathlib.Path('state/temporal_claims/work-items.json').read_text()); \
  print(len(d['work_items']), len(d['work_item_aliases']))"
```

The birth-origin item is present, `score_rule` reads `temporal-score:2`, and
`work_item_aliases` maps the legacy keystone id onto it.

## Non-goals

- The provisional (calculated) origin itself — that is E-BO. This contract
  only guarantees it will not close the explicit-birthday item when it lands.
- Wave F calibration of the other components; only the birth origin's
  `system_value` moves, and it moves under a named rule.
- The platform half: `questions/today.work_item_id` on the API, hosted weekly
  proof, whisper suppression on the hosted surface. `P-E6`.
- `system/version.json` is deliberately NOT bumped here; the version train
  assigns a slot by readiness at green.

🤖 Generated with Claude Opus 5 via Claude Code
