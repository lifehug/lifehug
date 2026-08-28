# Contract: eras-o-e1-age-frames

Phase **E1** of the Eras / Timeline program, OSS half (`O-E1`).
Platform tracking: lifehug-platform **#686**. Controlling authority:
lifehug-platform `docs/design/eras.md` (v3.1) §2.1–2.2, §3.3–3.5, §7 row
"Age frame node", §7.8, §9.1 (T-AF-01…16) and §13.1 — owner rulings there are
closed and are not reopened here. Stacked on
`docs/pr-specs/eras-o-e0-immediate-defects.md` (`O-E0`): the owner's birth
binds to `self` there, and this contract builds on that one owner birth node.

## Why

Age frames — childhood, the teens, every reached decade — are the permanent,
calculated coordinate system of a person's Timeline. Today the package has no
such thing. What it has instead:

1. **Frames are roster rows.** *"My 20s"* exists because a monthly model pass
   put it in `state/entity_rosters/period.json`, and it is dated — when it is
   dated at all — by `cross_dating.age_band_span`, a stateless read-time
   derivation keyed on the string the model happened to write. Delete the
   roster row and the person's twenties stop existing.
2. **Frame order is opinion.** `derive_chrono` sorts periods by whatever
   `date.earliest` the band ladder produced, which is why the founder's
   Timeline showed College 1990–1991 before High School (design §1 item 1).
3. **The substrate cannot express a frame.** `temporal_projection.NODE_KINDS`
   declares `"period"` and `temporal_timeline._node_kind_for` never mints it;
   there is no `add_years` in `chronology` (there is `from_age_band`, which
   discards the birth day and month), so nothing in the package can say where
   a twentieth birthday falls.
4. **Every publication mints a generation.** `publish()` rewrites both files
   and advances the counter on every call, so "the frames moved" and "somebody
   published again" are the same event and neither is detectable.

E1 makes the frames calculated facts of the substrate: derived from the birth
origin, published as `period` nodes of the calculated projection, addressed by
a readable identity the legacy slugs alias into, and republished only when
they actually change.

## Binding facts (as of this branch's base, `origin/feat/eras-o-e0-immediate-defects`)

- `system/chronology.py`
  - `GRANULARITIES = ("day","month","season","year","range","era")` `:46`;
    `DateRecord(best, earliest, latest, granularity, confidence, basis, anchors, provenance)` `:130-159`.
  - `_ordinal(value, end)` `:571-595` fills a bare year to 1 Jan / 31 Dec, a
    month to the 1st / its last day (`_month_last_day` `:598-601`, real
    calendar arithmetic — the module's only leap awareness), a season code to
    its month span. `year_of(record, end=False)` `:604-611`.
  - `from_age_band(birth, low, high)` `:739-784` works in WHOLE YEARS off
    `year_of(birth)` — the birth's day and month are discarded, and
    `latest = birth_year + max_age + 1` as an inclusive year bound. It is the
    right rule for *"when I was about five"* and the wrong one for a frame
    edge. **There is no `add_years` and no anniversary helper.**
- `system/cross_dating.py`
  - `AGE_BAND_AGES` `:696-710` — the legacy age-label table
    (`teens (13,20)`, `20s (20,30)` … `90s (90,100)`); no childhood row.
    `age_band_span(name, birth_date)` `:722-747` builds a whole-year range and
    inherits the birthday's confidence (`_inherited_confidence`).
  - `BAND_RULES_THAT_BOUND = ("age_label",)` `:150` — the age label is the one
    band rule that bounds rather than floors.
  - The module imports `chronology` and nothing else. It is pure.
- `system/temporal_projection.py`
  - `NODE_KINDS = ("event", "period", "episode")` `:91` — `period` already
    declared, never minted. `NODE_IDENTITY_KEYS` `:137` frozen.
  - `derive_input_fingerprint(claim_ids, constraint_ids, calculation_rule_version)`
    `:236-261` digests a three-key payload; `digest_id` `:489` is canonical
    JSON, so ADDING a key changes every existing fingerprint.
  - `validate_calculated_timeline_node` `:341-436` refuses
    `node_without_inputs` — **a node with no `input_claim_refs` is a
    fabrication**.
  - `SCHEMA_VERSION` here is `temporal_claims.SCHEMA_VERSION` (imported
    `:72`), which also stamps every claim, constraint, receipt and the active
    index (`temporal_store.py:511, :1157, :1476`).
- `system/temporal_timeline.py`
  - `CALCULATION_RULE_VERSION = "timeline-rules:1"` `:123`.
  - `_node_kind_for` `:390-400` returns `episode` or `event`, never `period`.
  - Birth seeding `:1451-1466` (rewritten by `O-E0b` on this branch's base).
  - `structural_signature` `:310` names the runtime exclusions.
- `system/temporal_publication.py`
  - `next_generation` `:242-244`; `publish` `:363-445` **always** derives,
    renders and writes both files. No unchanged short-circuit exists.
  - `rebuild_signature` `:313-346` drops `EXCLUDED_ENVELOPE_KEYS` `:130-138`
    (which includes `projection_generation`, `published_at`, `timings`,
    `input_digest`), `EXCLUDED_NODE_KEYS = ("projection_generation",)` and
    `EXCLUDED_WORK_ITEM_KEYS`. **Every other envelope key is inside the
    signature by construction.**
  - `calculated_view` `:490-519` is the read model `timeline_data()["calculated"]`
    exposes.
- `system/timeline.py`
  - `_scored_things` `:2065-2105` enumerates the scored population from
    `data["event_lineup"]`, `data["unplaced_events"]`, `data["periods"]` and
    `data["bands"]` — the LEGACY layer only. `data["calculated"]` `:3327-3335`
    is appended and read by nothing in the score.
- Version slot: **assigned at green by readiness** (the v219→v234 train's
  rule). Neither the contract commit nor the implementation commits bump
  `system/version.json`; the slot is taken when the branch is green and named
  in the PR body.

## Scope

### O-E1a — `chronology.add_years` (grain-preserving anniversary arithmetic)

`add_years(record, years) -> DateRecord | None`. One definition; the whole
package's answer to *"the same date, n years later"*.

- **Grain is preserved.** `1981-07-11 + 20 → 2001-07-11` (day);
  `1981-07 + 20 → 2001-07` (month); `1981-22 + 20 → 2001-22` (season, bounds
  shifted with it); `1981 + 20 → 2001` (year).
- **Feb 29 clamps to Feb 28** in a non-leap target year — rule
  **`age-frame:1`**, appended to the returned record's `provenance` as
  `{"claim": "29 February falls on 28 February in a year that has no 29th",
    "basis": <the record's basis>, "source": "age-frame:1"}`. The clamp is
  visible on the record or it did not happen.
- **A record that cannot keep its grain widens honestly.** A decade
  (`granularity: era`, `197X` = 1970–1979) shifted by an amount that is not a
  multiple of ten cannot be written as a decade: both BOUNDS shift
  (`1983`/`1992`), `best` becomes `1983/1992` and the granularity becomes
  `range`. The result is decade-WIDE, which is the honest reading of a
  decade-grain origin; it is never re-rendered as a decade it is not.
- Confidence, basis, anchors and the incoming provenance ride through
  unchanged. `None` in → `None` out; an unparseable record → `None`.

### O-E1b — `cross_dating.age_frames` (the one frame definition)

`age_frames(birth, *, as_of, death=None) -> tuple[AgeFrame, ...]`, pure.

Bands, from §3.3 — `childhood [0,13)`, `teens [13,20)`, then `[10k, 10k+10)`
for every **reached** k ≥ 2, **no maximum**:

| band key | ages | display |
|---|---|---|
| `childhood` | 0–12 | "Childhood" |
| `teens` | 13–19 | "Teen years" |
| `20s`, `30s`, … `100s`, … | 10k … 10k+9 | "My 20s", "My 30s", … |

- `start_k = add_years(birth, low)`; `end_k = add_years(birth, high)`,
  **exclusive**.
- **Reached** means `start ≤ as_of` (and `start ≤ death` when a death is
  given). A frame the person has not reached does not exist; there is no
  maximum band.
- `AgeFrame` (frozen dataclass): `band, label, low, high, start, end, value,
  current, life_clip_end, provenance`.
- `value` — what becomes `best_temporal_value` — is the **definition span at
  the birth's grain**, closed: at day grain the exclusive end minus one day
  (`2001-07-11/2011-07-10`, so `year_of(end=True) == 2011`); at every coarser
  grain the end token itself (`2001/2011` at year grain), because the boundary
  unit genuinely belongs to both frames. It is **never** `start`, and never
  anything touched by `as_of`.
- `life_clip_end` is `"present"` for the frame containing `as_of`, the death's
  ISO date for the frame containing a given death, and the frame's own
  exclusive end for a frame wholly in the past. `"present"` is a view token
  resolved at read time; `as_of` itself is never carried on the frame.
- `basis: "anchor"`, `anchors: ("birth",)`, confidence inherited from the
  birth record (`cross_dating._inherited_confidence` — an age frame is a
  definitional join, §3.3), provenance `"from your birthday"` plus any
  `age-frame:1` entry `add_years` produced.
- Companion arithmetic, one body two names:
  `frames_touching(frames, record) -> tuple[(band, relation)]` gives `within`
  when a record lies inside exactly one frame and `overlaps` for every frame a
  wider or boundary-straddling record touches; `frame_for(frames, record)`
  is the `within` band or `None`. **Nothing picks a winner** among overlaps —
  that is E2's display role, not this arithmetic.
- Band-table parity: every band `age_frames` shares a name with in
  `AGE_BAND_AGES` must agree with it on the ages, pinned by a test, so the
  legacy label ladder and the frame ladder can never drift (recurring-defect
  doctrine).

`age_frames` does **not** compute `origin_basis`. `explicit` vs `calculated`
is a *claim* basis, and `temporal_claims.CLAIM_BASIS_BY_DATE_BASIS` is already
its one mapping; putting it here would import the substrate into a pure
arithmetic module and mint a second copy of that table. The fold applies it
(O-E1c).

### O-E1c — the fold mints period nodes

In `derive_calculated_timeline`:

- `_node_kind_for` learns `period`: an `age_frame` (and, from E3, a
  `named_era`) is a `period`. One predicate, read by the minter and by the
  node payload, exactly as `episode` already is.
- The owner's birth group is located once (`event_kind == "birth"` with the
  resolved subject equal to the owner — post-`O-E0b` that is subject `self`
  under either receipt spelling). Exactly one such group mints frames; zero or
  more than one mints none, and says so in `diagnostics`
  (`age_frames_without_birth_anchor` / `age_frames_ambiguous_birth`).
- **A frame cites the birth's claims.** `input_claim_refs` is the birth
  group's claim ids — the validator refuses a node without inputs, and it is
  right to: a frame is calculated from the birthday and from nothing else. A
  `birth_date` handed to the fold with no receipts behind it therefore mints
  no frames. That is not a gap; it is the substrate declining to publish a
  node it cannot explain.
- Each frame node:

```
node_id            "age:self:<band>"          # readable; ?play=frame:<node_id>
node_kind          "period"
event_kind         "age_frame"
subject_refs       ("self",)
label              "My 20s"
best_temporal_value  <AgeFrame.value>          # the definition span, birth's grain
definition_span    {"start": <DateRecord dict>, "end": <DateRecord dict>}   # end EXCLUSIVE
life_clip_end      "present" | "<ISO date>"
origin_basis       "explicit" | "calculated"   # CLAIM_BASIS_BY_DATE_BASIS of the birth record
legacy_refs        ("period:my-20s", "tl:my-20s", "band:my-20s")
input_claim_refs   <the birth group's claim ids>
input_fingerprint  fp:… with the reached-frame epoch inside it
basis / confidence / provenance_summary / conflict_state   as every other node
```

- **The epoch is inside the fingerprint.** `derive_input_fingerprint` gains an
  OPTIONAL `epoch` argument that adds a payload key **only when supplied**, so
  every existing fingerprint in every published vault stays byte-identical.
  Frames pass `age-frame-epoch:<count>:<current band>`; a boundary crossing
  therefore changes every frame's fingerprint on unchanged claims, which is
  exactly what a fingerprint is for.
- **`life_view`.** Every node gains `life_view ∈ ("lived", "future_plan")`: a
  node whose best value starts strictly after `as_of` is `future_plan`, never
  lived history inside a frame (§2.6, §13.1). `as_of` is the fold's `now`.
  E2 extends the vocabulary with `contradictory`/`unresolved`, which need the
  subject machinery this phase does not have; E1 assigns exactly two values
  and a test names that.
- **Frames are not work.** `_derive_work_items` walks claim GROUPS; frames are
  not groups, so no frame ever mints a `precision_gap`, appears in
  `diagnostics["unplaced"]`, or competes in `reach`. A test pins it rather
  than leaving it to the shape.
- `CALCULATION_RULE_VERSION` → **`timeline-rules:2`**.

### O-E1d — schema v2, additively

- New `temporal_projection.PROJECTION_SCHEMA_VERSION = 2` — the version of the
  CALCULATED PROJECTION's node contract. It is **not**
  `temporal_claims.SCHEMA_VERSION`, which stamps every claim, constraint,
  receipt and the active index; moving that one would restamp the whole
  receipt store for a node-shape change, which is the opposite of additive.
  (Design §2.2 says "`SCHEMA_VERSION` 1 → 2"; §7.8 names
  `PROJECTION_SCHEMA_VERSION` for the same bump. §7.8 is the buildable one.)
  Nodes carry `schema_version: 2`; claims, constraints and work items keep 1
  because their shape did not move.
- New optional node fields, every one absent-means-unchanged:
  `definition_span`, `life_clip_end`, `origin_basis`, `legacy_refs`,
  `life_view`.
- New `CalculatedMembership` contract (schema only; **E2 writes them**):
  `membership_id = digest_id("membership", {member_node_id, era_node_id,
  relation})`, `relation ∈ ("within","overlaps","starts_in","associated_with")`,
  `display_role ∈ ("primary","secondary","none")`, `basis`, `confidence`,
  `evidence_refs` (≥1 — `membership_without_evidence` otherwise),
  `input_fingerprint`. `CalculatedTimeline.memberships` is `()` in E1 and rides
  the published projection as an empty list, so E2 adds rows and not a key.
- **Readers are tolerant.** `calculated_view` reads a v1 payload and a v2
  payload identically and reports `schema_version` so a host can branch;
  `calculated_timeline_node_from_dict` keeps a node written by either version.
  Rollback is the platform's flag (§7.8 step 3); nothing here deletes a
  receipt, an identity source, an assertion or a decision.

### O-E1e — publication is a semantic no-op when nothing moved

`publish()` derives, renders both payloads, and **writes neither and mints no
generation** when all four hold:

1. both files are present and readable,
2. they carry the SAME generation (a torn publication is never a no-op — the
   tear is what `published_generation`'s max exists to repair),
3. `rebuild_signature(fresh projection) == rebuild_signature(published projection)`,
4. `rebuild_signature(fresh work items) == rebuild_signature(published work items)`.

The summary gains `"unchanged": true|false`; every other key keeps its meaning
(`generation` is the standing generation on a no-op). The **reached-frame
epoch** rides the published envelope as `reached_frame_epoch: {"count": n,
"current": "<band>"|null}`, which puts it inside `rebuild_signature` by that
function's existing rule — one comparison, not a second definition beside it.
`as_of` is never written to either file.

Consequence, stated rather than discovered: three tests in
`tests/test_projection_publication.py` pin today's "publish always mints"
behaviour and are rewritten by this PR —
`test_every_node_carries_the_generation_it_was_published_in`,
`test_generation_starts_at_one_and_never_repeats` and
`test_the_counter_reads_the_max_across_both_files`. The properties they
protect survive: a generation number is still never re-used, and the torn-file
case still publishes above both. What changes is that an unchanged republish
is no longer an event.

### O-E1f — `timeline.legacy_period_ref` (the one alias map)

`legacy_period_ref(ref) -> node_id | None`, the single map §3.5 requires so
`?play=` keys, the zoom keys (`lifehug.timeline.certainty.view:<vault>`,
`lifehug.timeline.expanded:<vault>`), `TimelinePlan.unknowns[].period` /
`moments[].period` and pins all resolve the same way (the platform re-exports
it):

- `period:my-20s`, `tl:my-20s`, `band:my-20s`, and the bare slug `my-20s`, all
  → `age:self:20s`; `childhood` → `age:self:childhood`; `my-teens` /
  `my-teenage-years` → `age:self:teens`; the alias spellings come from
  `AGE_BAND_AGES`' own keys, not a second list.
- A ref naming anything else (`period:college`, `band:the-mission`) → `None`.
  A named era is E3's identity, and guessing one here would be the wrong join
  ADR 0026 ranks above a miss.
- **Roster rows named like a band contribute aliases only.** A
  `state/entity_rosters/period.json` row whose name or alias is a canonical
  band name adds its slug to that frame's `legacy_refs`; it never creates,
  dates, renames or orders a frame. A test pins that a roster carrying
  "My Twenties" changes exactly one thing: the alias set.

### Out of scope

The calculated birth origin (`E-BO`); memberships as data (`E2` — this PR
adds the schema and writes none); named eras, `era-record`, the `era` stage
and event binding (`E3`); the legacy placement pass, band rendering and
`era_gap`'s retirement (`E2`); gestures (`E5`); `work_item_aliases` (`E6`).

## Eight-part answers (design §7 discipline)

| Output | 1 input record | 2 canonical writer | 3 identity / idempotency | 4 correction | 5 fold derivation | 6 aliases / migration | 7 failing-then-passing test | 8 rollout / rollback |
|---|---|---|---|---|---|---|---|---|
| Age frame node | the owner's birth `TemporalClaim`s (explicit); the provisional origin (calculated, E-BO) | nobody — never model-authored, never hand-written; the FOLD derives it | `age:self:<band>`, a pure function of (subject, band); the reached-frame epoch is inside `input_fingerprint`; two folds over one substrate at one `as_of` are byte-identical | nothing corrects a frame; correcting the BIRTH claim (supersede/retract) moves every frame at once | §3.3 arithmetic through `cross_dating.age_frames` over the reconciled owner birth node | `legacy_refs` on the node + `timeline.legacy_period_ref`; roster band rows contribute aliases only | T-AF-01…16 | tolerant readers first, `PROJECTION_SCHEMA_VERSION = 2` writer, platform flag off = rollback; receipts untouched |
| `add_years` | a `DateRecord` + an integer | pure function, no writer | deterministic; grain-preserving; clamp rule `age-frame:1` recorded in provenance | n/a | n/a | n/a | T-AF-05, T-AF-13 | pure; rollback = revert |
| `CalculatedMembership` (schema) | E2's assertions, constraints and frame arithmetic | E2's `era-member` / recorder / drag | `digest(member_node_id, era_node_id, relation)` | retraction of the receipt; the membership survives while another active receipt supports it (E2) | E2 | E2 | T-AF-15 (shape + tolerant read) | additive empty list; E2 adds rows, not a key |
| Publication no-op | the two published files + the fresh render | `publish()` | signature + epoch equality, both files, same generation | a torn pair always publishes | n/a | n/a | T-AF-08, T-AF-09 | additive `unchanged` key; rollback = revert (the counter never went backwards) |
| `legacy_period_ref` | a legacy slug or prefixed ref | pure function | table-driven off `AGE_BAND_AGES` + the frame band list | n/a | n/a | it IS the alias map | T-AF-12 | pure; rollback = revert |

## Test plan (every negative test is SEEN failing before the code exists)

New `tests/test_eras_e1.py` (unittest), plus the three rewritten publication
tests named in O-E1e. Ids are design §9.1's.

- **T-AF-01** exact birthday → half-open frames: an event on `2001-07-11` is
  in My 20s and an event on `2011-07-11` is in My 30s; the start is inclusive
  and the end exclusive.
- **T-AF-02** March and December of the same year around a July birthday land
  in different frames when the birthday boundary lies between them.
- **T-AF-03** a year-only birthday renders plain year ranges (`2001/2011`) and
  an event in the boundary year overlaps BOTH adjacent frames, never one.
- **T-AF-04** a fuzzy interval touching several frames keeps every overlap;
  `frames_touching` picks no winner and `frame_for` returns `None`.
- **T-AF-05** a 29 February birthday clamps to 28 February in non-leap target
  years, and rule `age-frame:1` is on the record's provenance; a leap target
  year keeps the 29th and files no clamp entry.
- **T-AF-06** no maximum: every reached decade exists and no unreached decade
  does, at ages 8, 19, 44 and 101; with a death, no frame starts after it.
- **T-AF-07** the current frame carries a finite `definition_span` and
  `life_clip_end: "present"`; a past frame carries its own end; the string of
  `as_of` appears nowhere in either published file.
- **T-AF-08** two publishes inside one epoch: same generation, `unchanged:
  true`, both files byte-identical (content AND mtime).
- **T-AF-09** crossing a boundary (`as_of` moved past a frame start)
  publishes exactly once: one new generation, then no-op again.
- **T-AF-10** an event dated after `as_of` is `life_view: future_plan`; one
  dated before is `lived`.
- **T-AF-11** age frames are excluded from the placement score: adding frame
  nodes to `data["calculated"]` moves neither `placement_score` nor
  `_scored_things`; the guard is proved sensitive by showing the score DOES
  move when a frame is injected into `data["periods"]`.
- **T-AF-12** `legacy_period_ref` resolves `period:my-20s`, `tl:my-20s`,
  `band:my-20s`, `my-20s`, `childhood`, `my-teens` → the right frame id;
  `period:college` → `None`; a roster carrying "My Twenties" changes exactly
  the alias set and nothing else.
- **T-AF-13** `best_temporal_value` is the definition span at the birth's
  grain — day, month, season, year and decade birthdays each checked — and is
  never `start` and never `as_of`.
- **T-AF-14** the frame node declares `node_kind: period`, `event_kind:
  age_frame`, `origin_basis: explicit`, `subject_refs: ("self",)` and its
  `legacy_refs`; `_node_kind_for("age_frame") == "period"`; the id is
  `age:self:20s`.
- **T-AF-15** schema v2 is additive: a node carries `schema_version: 2` while
  claims stay 1; `calculated_view` reads a v1 payload and a v2 payload;
  `memberships` is present and empty; `validate_calculated_membership` refuses
  `membership_without_evidence`.
- **T-AF-16** `CALCULATION_RULE_VERSION == "timeline-rules:2"`; a frame's
  fingerprint changes when the epoch changes on unchanged claims; a NON-frame
  node's fingerprint is byte-identical to the one v1 minted (a pinned literal).

Plus the guards: `age_frames` and `AGE_BAND_AGES` agree wherever they share a
band name; the frame node never appears in `work_items`, `reach` or
`diagnostics["unplaced"]`; two folds at one fixed `as_of` are byte-identical
(the existing rebuild-identity tests stay green).

Run: `python3 -m unittest tests.test_eras_e1 -v`, plus
`tests.test_chronology tests.test_cross_dating tests.test_temporal_projection
tests.test_temporal_timeline tests.test_projection_publication
tests.test_timeline_dates tests.test_timeline_unknowns
tests.test_handbook_parity`. Temp vaults via `tempfile`/`tmp_path` — never a
literal `/private/tmp` path.

## Launch-and-verify

No viewer surface changes in this PR: E1 puts the frames in the calculated
projection, and E2 renders them. Reviewer command, against any vault with a
birth landmark:

```bash
python3 system/temporal_publication.py --vault-root . \
  && python3 -c 'import json,sys; d=json.load(open("state/temporal_claims/calculated-timeline.json")); \
     print([(n["node_id"], n["best_temporal_value"]["best"], n.get("life_clip_end")) \
            for n in d["nodes"] if n.get("event_kind")=="age_frame"])'
```

Then run the same publish a second time: it prints the SAME generation and
writes nothing.

## Definition of done

- [ ] Code + the scoped suites pass locally; CI is the full-suite arbiter
- [ ] Every negative test seen failing first, evidence in the PR body
- [ ] `system/version.json` bumped to the NEXT FREE slot at green (not in any
      contract or implementation commit here); named in the PR body
- [ ] The v2 field list handed to the platform (`P-E1` needs it for the
      tolerant readers §7.8 step 1 requires BEFORE this writer ships)
- [ ] ADR 0030 referenced; no new ADR
- [ ] lifehug-platform #686 commented with the release number so `P-E1` can pin it

🤖 Generated with Claude Opus 5 via Claude Code
