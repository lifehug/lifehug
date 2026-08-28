# Contract: eras-o-e3-era-record

Phase **E3** of the Eras / Timeline program, OSS half (`O-E3`). Platform
tracking: lifehug-platform **#686**. Controlling authority:
lifehug-platform `docs/design/eras.md` (v3.1) §2.3, §2.4, §4.1–§4.5, §5.4,
§7 and §9.1, plus ADR 0030 (this repo). Owner rulings there are closed and
are not reopened here. Stacked on `O-E1` (age frames,
`feat/eras-o-e1-age-frames`) and rebased onto `O-E2` (membership/display
receipts) when it lands — this contract does NOT define the membership
receipt; it consumes it through one named seam.

## Why

E1 gave the Timeline a permanent calculated coordinate system. It has no
writer for the thing people actually say: *"I think of 2007 through 2011 as
my College years."* Today that sentence has nowhere to land.

1. **An era has no identity.** The only "era" a vault holds is a roster
   period row whose NAME is its identity, dated from whatever keyword
   placement sorted into it. Renaming it loses everything attached; two rows
   spelled differently are two eras; a date it "has" is a side effect of
   membership, which is the exact defect that put College at 1990–1991
   before High School (design §1 item 1).
2. **An era has no atomic writer.** Creating, labelling, dating and scoping
   an era is one thing a person did in one sentence, and there is no verb
   that performs it once, all the way, replay-safe.
3. **A date said next to a name cannot reach the thing named.** The recorder
   and the general listener hear *"College ran 2007 to 2011"* and file a
   claim whose `event_kind` is `period_started`. Nothing links it to an era,
   because the model may not emit `event_ref` (ADR 0029) and there is no
   deterministic pass that does.
4. **Play has nowhere to open.** `?play=era:<era_id>` has no stage. The
   `timeline` interaction knows `open`/`place`/`close`/`work_item` and none
   of them is "let's talk about this stretch of your life".

## Binding facts (as of this branch's base, `origin/feat/eras-o-e1-age-frames`)

- `system/temporal_claims.py`
  - `CLAIM_TYPES` `:154` — `date range age duration relative_order identity`.
  - `EVENT_KIND_RE` `:215` — `^[a-z][a-z0-9_]{1,39}$`; `period_started` and
    `period_ended` both pass today (executed).
  - `CLAIM_IDENTITY_KEYS` `:1037` — FROZEN, six keys, `event_ref` explicitly
    excluded ("resolution happens after the claim exists").
  - `validate_temporal_claim` `:1157` builds a **whitelisted** `normalized`
    dict `:1290-1316`; a key it does not name is silently dropped. An
    `event_mention` that is not added there cannot survive filing.
  - `digest_id` `:489` — `<prefix>:<24 hex>` over canonical JSON, the ONE id
    derivation.
- `system/general_listener.py`
  - `CLAIM_PROMPT_KEYS` `:880-883` — the CLOSED key set a leaf may emit.
  - `CLAIM_DRAFT_KEYS` `:886-888` — the draft's stable field order.
  - `bind_claims` `:1002` — drafts + promoted `SourceRef` → validated claims.
    The claim id is derived here for the first time.
- `system/landmark_recorder.py`
  - `file_claims` `:427` — promote → receipt → publish, in that order.
  - `RecorderOutcome.claims` `:150` — the drafts the same completion emitted.
- `system/temporal_store.py`
  - `file_message_extraction` `:1539` — promote-then-receipt, both idempotent.
  - `_create_or_keep` `:369` — publish-new-immutable-file, reports creation.
  - `promote_conversational_source` `:465`, `file_ordering_constraint` `:1064`
    — the two existing "content-addressed source document" writers this
    module's era records copy verbatim in shape.
  - `FRONTMATTER_ORDER` `:168`, `format_frontmatter` `:289`,
    `split_frontmatter` `:307`, `payload_sha256` `:350`.
- `system/temporal_timeline.py`
  - `_group_claims` `:713` — the grouping key is `claim["event_ref"]` when
    present, else the derived node id. **This is the seat event resolution
    must reach.**
  - `_resolution_index` `:454` / `_resolve_subjects` `:477` — the existing
    resolution-record seam, subjects only.
  - `_node_kind_for` `:399` reads `tp.PERIOD_EVENT_KINDS`, which already
    declares `named_era` (E1 landed it).
  - `_build_edges` `:915`, `_bound_from_edge` `:1043` — `within` currently
    yields BOUNDS through `chronology.from_anchor(anchor, "during")`.
  - `derive_calculated_timeline` `:1647`.
- `system/temporal_projection.py`
  - `PERIOD_EVENT_KINDS` `:97` = `("age_frame", "named_era")`.
  - `PROJECTION_SCHEMA_VERSION` `:177` = 2; `NODE_IDENTITY_KEYS` `:180`.
- `system/temporal_publication.py`
  - `publish` `:388` — `constraints=None` means "read them from the vault",
    `()` means none. `resolution_records` defaults to `()` and **no caller
    has ever read one off disk.**
- `system/timeline_interaction.py`
  - `WORK_ITEM_STAGE` `:393`, `VALID_TIMELINE_STAGES` `:395`.
  - `build_timeline_plan` `:1539` — already accepts `era=`, and filters
    unknown rows by the legacy `period` slug. No ladder, no era identity.
- `interactions/timeline/prompt/turn-instructions.md`
  - `:12` names the four stages; `:35` is
    `## When \`{timeline_stage}\` is \`work_item\`` — **lifehug#253**: the
    host substitutes `{timeline_stage}` inside the heading, so an ordinary
    placement turn reads `## When place is work_item`.
- `interactions/landmarks/prompt/recorder.md` `:94-141` — the `claims`
  section, the only place a leaf is taught the claim vocabulary.
- `system/vault_contract.json` — `identity.content_digest` is checked at
  import (`vault_paths.py:117-121`); adding a data path REQUIRES recomputing
  it and bumping `identity.revision`.

## Scope

### S1 — Era identity, label and kind records (`system/era_identity.py`, NEW)

Three immutable source documents on one opaque id, in the shape
`promote_conversational_source` and `file_ordering_constraint` already use
(frontmatter + prose body + `content_sha256`, published through
`_create_or_keep`, so replay writes nothing).

```
era_id = digest_id("era", {"creation_operation_id": <operation id>})
```

The operation id is the **mutation/idempotency key of the creating act**
(design §2.3): `era_identity.turn_operation_id(session_ref, turn_ref)` →
`"<session_ref>#<turn_ref>"`, or
`era_identity.migration_operation_id(batch, legacy_slug)` →
`"migration:<batch>:<legacy_slug>"`. **No mutable label is inside identity.**

| Record | Path | Frontmatter | Identity |
|---|---|---|---|
| identity | `sources/eras/era-<24hex>.md` | `type: era_identity`, `era_id`, `origin`, `era_kind`, `legacy_slug?`, `created_at` | the operation id |
| label | `sources/eras/era-<24hex>/labels/<24hex>.md` | `type: era_label`, `era_id`, `label`, `aliases`, `supersedes?` | `digest(era_id, label, aliases, supersedes)` |
| kind | `sources/eras/era-<24hex>/kind/<24hex>.md` | `type: era_kind`, `era_id`, `era_kind`, `supersedes?` | `digest(era_id, era_kind, supersedes)` |

**Path deviation, stated:** design §2.3 writes `sources/eras/<era_id>.md`.
An `era_id` is `era:<24hex>` and a `:` is not a safe path component (the
platform's own Firestore ids ban `/` for the same class of reason, #612's
lesson), so the file stem is `era-<24hex>` — exactly the convention
`sources/corrections/temporal-<24hex>.md` already uses for
`temporal_correction:<24hex>`. The id inside the file is the full `era_id`.

`ERA_KINDS = ("stretch", "thread")`. `ERA_ORIGINS = ("person",
"legacy_roster", "recommendation")`.

Readers: `load_era_identities`, `load_era_labels`, `load_era_kinds`,
`era_views(vault_root)` → `{era_id: view}` where a view carries the
**newest active** label and kind after walking the `supersedes` chain, plus
`aliases`, `origin`, `legacy_slug` and `retired`. `label_index(views)` →
`{normalized label or alias: (era_id, …)}` — the binder's input, and the
place two eras sharing an alias becomes visible as a two-element tuple.

Retirement is a `retract` correction on the identity claim (design §2.3);
this contract files the record and reads it, and does not add a merge verb
(§2.3's `merged_into` decision is E4's).

### S2 — Migration of legacy roster periods

`migrate_legacy_periods(vault_root, *, roster_snapshot, batch, dry_run)`:
one identity + one label record per `page_eligible` **non-age** roster
period row (`cross_dating.age_frame_band_of(name) is None`), with
`origin: legacy_roster` and `legacy_slug`. **No roster `chrono`,
`approximate_dates` or source list is imported as authority** — a legacy
date is REPORTED as unsupported, never filed. Period wiki page paths are
untouched. The dry-run report names: `mapped` (slug → era_id), `aliases`,
`orphans` (a period row with no slug), `duplicates` (two rows normalizing
to one label), `unsupported_legacy_dates`.

### S3 — `event_mention`, the binder, and the resolution record

1. **`temporal_claims`**: additive optional field `event_mention` on
   `TemporalClaim`, normalized in `validate_temporal_claim`, bounded by
   `MAX_SUBJECT_MENTION_CHARS`, **refused on an `identity` claim** for the
   same reason `event_ref` is, and **absent from `CLAIM_IDENTITY_KEYS`**
   (design §2.3: "`CLAIM_IDENTITY_KEYS` unchanged"). A mention is what was
   said; the link is a separate record.
2. **`general_listener`**: `event_mention` joins `CLAIM_PROMPT_KEYS` and
   `CLAIM_DRAFT_KEYS` (ADR 0029 amendment). The model still may NOT emit
   `event_ref` or `subject_ref` — the two remain absent from the prompt key
   set, and that is asserted.
3. **`system/event_binding.py` (NEW)** — the deterministic binder.
   `bind_event_mention(mention, *, index, target_era_id=None)` →
   `(event_ref | None, bound_by, candidates)`:
   - exact **case-folded whole-label** match against (i) the session's
     visible target era's own label/aliases → `bound_by="target"`,
     (ii) every era's active label/alias records → `bound_by="alias"`;
   - two eras sharing the mention → **no bind**, `bound_by="none"`,
     `candidates=(era_a, era_b)`, and the caller mints an
     `identity_uncertain` work item naming BOTH;
   - no match → no bind and a `claim_event_unbound` diagnostic. **A miss,
     never a wrong link.**
4. **Resolution record**:
   `state/temporal_claims/resolutions/<24hex>.json`,
   `{type: "event_resolution", claim_id, event_mention, event_ref,
   rule_version, bound_by, supersedes?, created_at, schema_version}`,
   identity `digest(claim_id, event_mention, rule_version, supersedes)`.
   `RESOLUTION_RULE_VERSION = "event-binding:1"`. Filing is
   `_create_or_keep`-shaped: replay writes nothing.
5. **The fold** reads active event resolutions and applies them BEFORE
   `_group_claims`, as an overlay on a copy — never an edit of the receipt.
   `resolve_events(claims, records)` takes the **newest active resolution
   per claim** (`created_at`, ties by `event_ref` so order cannot decide),
   and a **second active record for one claim with no `supersedes`** raises
   `event_resolution_ambiguous` — a LOUD fold refusal (T-B-03).
   `derive_calculated_timeline` gains
   `event_resolution_records: object = ()`; it also harvests
   `event_resolution`-typed rows out of the existing `resolution_records`
   ledger, so "the existing seam extended from subjects to events" is
   literally one ledger for a caller that keeps one.
   `temporal_publication.publish` gains
   `event_resolution_records: object = None`, where `None` means "read this
   vault's filed resolutions" — the `constraints` pattern, verbatim.
6. **Alias changes affect only future unresolved mentions**: a filed
   resolution is never rewritten, and re-running the binder over a claim
   that already has an active resolution is a no-op.

### S4 — `within(frame)` yields a possibility, not a bound

`temporal_projection`: additive node field `possible_temporal_value`.
For a `named_era` node whose own claims date it not at all and whose only
placement came from `within` edges, the fold publishes
`best_temporal_value: None` + `possible_temporal_value` (basis
`calculated`, confidence ≤ `inferred`) and `temporal_state` stays
`unplaced`; with ONE bound claim it is `partial`. Design §4.2: a `within`
is never a bound.

### S5 — `era-record`, the atomic writer (`system/era_record.py`, NEW + CLI)

ONE JSON payload on stdin, ONE invocation, ONE vault-mutation job:

```json
{"era_id": "era:…",            // absent = create
 "label": "College Years",
 "aliases": ["College"],
 "era_kind": "stretch",
 "claims": [ {claim draft}, … ],   // general_listener draft shape
 "within": "age:self:20s",         // frame node id or era node id
 "memberships": [ {member_node_id, relation, source_ref?}, … ],
 "session_ref": "…", "turn_ref": "…", "message_text": "…"}
```

Steps, in order, each idempotent, each a no-op on replay:

1. **ensure identity** — content-addressed by the operation id
   (`session_ref#turn_ref`, or an explicit `operation_id`).
2. **label/kind records** if given (a rename is a new label record naming
   its predecessor; `era_id` is untouched).
3. **bind + file claims** — every draft's `event_mention` runs the binder,
   then `temporal_store.file_message_extraction` promotes the message once
   and files ONE receipt with N claims, then the resolutions are filed
   against the minted claim ids. Order matters: a claim id exists only after
   binding to the source, and a resolution names a claim id.
4. **`within` constraint** — `temporal_store.file_ordering_constraint`,
   relation `within`.
5. **membership assertions** — through the E2 seam
   (`era_record.MEMBERSHIP_WRITER`); until O-E2 lands this is a declared,
   loudly-named seam that refuses rather than half-writes, and the
   `memberships` leg of the payload is reported as `deferred`.
6. **publish** — `temporal_publication.publish`, the ONE publisher.

Replay is a no-op at every step. A job that dies mid-way and is retried
under the same mutation id completes without duplicates (T-W-02/03) — proved
by running the writer with each step number as a crash point and then
re-running it whole.

CLI: `lifehug.py era-record` (payload on stdin, `--json` summary), in
`DIRECT_MUTATION_COMMANDS` — the same single-transaction family as
`timeline-move`.

### S6 — The `era` stage

- `VALID_TIMELINE_STAGES` gains `ERA_STAGE = "era"`.
  `timeline_stage_for_session(..., era=…)` selects it the way `work_item`
  does, and every close rule still wins in the same order.
- `interactions/timeline/prompt/turn-instructions.md`: a new
  **token-free** section heading, and **lifehug#253 fixed in the same
  breath** — the `work_item` heading loses its `{timeline_stage}` token
  too, because it is the same defect and the recurring-defect doctrine says
  fix the class. A guard test asserts no heading in the leaf contains any
  `{…}` token.
- `era_plan(data, *, era_id, views, limit)` in `timeline_interaction` — the
  era-scoped plan with **the ladder made explicit** (design §5.4):
  1. bounds (a `stretch` with an unbounded end),
  2. the residence chain inside the era,
  3. the highest-leverage undated moment inside,
  4. precision, and only while cheap — era → year → season → month, stopping
     at the first rung held without hedging.
- Recorder leaf `interactions/timeline/prompt/recorder.md`, on the ADR 0028
  loop, purpose `date_record` **reused** — no new purpose, no denominator
  move (owner decision 21).
- **A moment with no era**: `no_era_moment_target(row)` opens the era stage
  with the moment as visible context and **no era target**; the recorder's
  first move is the open `parallel_domain` question, never "before or after
  you were born" (T-CV-13).

### S7 — Stretch vs thread

`era_kind_from_words(text)` decides at creation from the person's own
words: a stated interval / begin-end language / a `within` → `stretch`;
recurring-presence language → `thread`; ambiguous → `None`, which is ONE
scope question and never a default. `flip_era_kind(vault_root, era_id,
era_kind)` files the kind decision, **retires the open span work item and
mints a Focus candidate** on the flip to `thread` (and re-mints the work
item flipping back). Identity, memberships, links and sessions are
untouched (T-NE-16).

### Out of scope, named

- The membership receipt itself and `era-member`/`era-display` (O-E2).
- `observed_envelope` (E2's coverage field).
- Era discovery / recommendation acceptance (E4).
- `merged_into` and the merge verb (§2.3, later).
- `system/version.json` is **not** bumped here: the version train assigns
  slots by READINESS at green (08-26/27 lesson).

## Eight-part answers (design §7 discipline)

| Output | 1 authoritative input | 2 canonical writer | 3 identity/idempotency | 4 correction | 5 fold derivation | 6 aliases/migration | 7 test | 8 rollout/rollback |
|---|---|---|---|---|---|---|---|---|
| Era identity | the creating act's own operation id | `era_identity.file_era_identity` via `era-record` / migration | `digest_id("era", {creation_operation_id})`; `_create_or_keep` | `retract` correction on the identity claim | identity → a `named_era` period node | `legacy_slug`, period page paths kept | T-NE-01/02, T-NE-17, T-W-01 | additive files; rollback = stop reading `sources/eras/` |
| Era label | the person's words (or the roster row's name) | `era_identity.file_era_label` | `digest(era_id, label, aliases, supersedes)` | a newer label record naming its predecessor | newest active label per era | aliases index; roster name becomes the initial label | T-NE-17, T-B-04 | same |
| Era kind | the person's words at creation | `era_identity.file_era_kind` | `digest(era_id, era_kind, supersedes)` | supersession | newest active kind | — | T-NE-16 | same |
| Era date claim | an ordinary `TemporalClaim` (`period_started`/`period_ended`) | recorder/listener → `era-record` | `CLAIM_IDENTITY_KEYS` **unchanged** | `temporal_correction` supersede/retract | grouped onto the era node by its resolution | — | T-NE-01, T-B-05 | same |
| Event resolution | the claim's `event_mention` + the active label index | the binder, in `era-record` and `bind_claims` | `digest(claim_id, event_mention, rule_version, supersedes)` | a superseding resolution record, **never** an edit of the claim | newest active per claim; a second active without `supersedes` = loud refusal | alias changes affect FUTURE unresolved mentions only | T-B-01…05 | ignore the directory = pre-E3 behavior |
| `within` possibility | an `OrderingConstraint` (`within`) | `era-record`, `timeline-move` | `CONSTRAINT_IDENTITY_KEYS` | `retract_ordering_constraint` | `possible_temporal_value`, never a bound | frame node ids are `age:self:<band>` | T-NE-09 | additive node key |

## Test plan (every negative test is SEEN failing before the code exists)

New file `tests/test_eras_e3.py`. Founder-shaped, executed:

- **T-NE-01** *"I think of 2007 through 2011 as my College years"* → ONE
  identity, ONE label record, TWO bound claims (`period_started` 2007,
  `period_ended` 2011) both resolving to that `era_id`, one node.
- **T-W-01/02/03** replay of the same `era-record` payload writes no second
  identity, label, claim, resolution, constraint or receipt; and the writer
  interrupted after each of steps 1–4 and re-run whole converges on exactly
  the same file set as the uninterrupted run.
- **T-NE-17** rename `College Years` → `Finding My Direction`: `era_id`,
  memberships, work items, links and open sessions unchanged; both labels
  readable; the new one active.
- **T-B-05** *"I graduated in 2011 during College"* → a `date` claim whose
  resolution binds the GRADUATION (its own `event_ref`) and a SEPARATE
  membership assertion linking it to College. The era's own bounds are not
  moved by it.
- **T-B-01** exact whole-label bind; **T-B-02** target era wins on its own
  exact label; **T-B-03** two active resolutions for one claim with no
  `supersedes` → loud fold refusal; **T-B-04** an alias added later does
  not rewrite a historical binding.
- **two eras aliased "the Mission"** → NO bind, `bound_by="none"`, an
  `identity_uncertain` work item naming BOTH.
- **no match** → `claim_event_unbound` diagnostic and no resolution file.
- **T-NE-09** `within(age:self:20s)` on an undated era →
  `possible_temporal_value` set, `best_temporal_value` None,
  `temporal_state` `unplaced`, basis `calculated`.
- **T-NE-16** stretch↔thread flip preserves identity/memberships/history and
  only swaps the span work item for a Focus candidate.
- **T-CV-13** a no-era moment: the stage opens with the moment as context,
  no era target, and the first probe is the open `parallel_domain` question;
  a date said files on that moment's own `event_ref`.
- **migration** — a `page_eligible` non-age roster period yields one
  identity + one label with `origin: legacy_roster`; an age-band-named row
  yields nothing; a legacy `chrono` is reported and NOT filed; the dry run
  writes zero bytes.
- **stage guards** — `era` in `VALID_TIMELINE_STAGES`;
  `timeline_stage_for_session` returns it for an era target and keeps every
  close rule; no leaf heading carries a `{…}` token (closes lifehug#253).
- **contract guards** — `event_mention` in `CLAIM_PROMPT_KEYS`;
  `subject_ref`/`event_ref` still absent from it; `CLAIM_IDENTITY_KEYS`
  unchanged; an `identity` claim carrying `event_mention` is refused.

## Launch-and-verify

```bash
cd ~/Workspace/lifehug
V=$(mktemp -d) && python3 system/lifehug.py --help >/dev/null   # sanity

# create an era from one sentence, in one act
echo '{"label":"College Years","aliases":["College"],"era_kind":"stretch",
 "session_ref":"s1","turn_ref":"t1",
 "message_text":"I think of 2007 through 2011 as my College years.",
 "claims":[{"claim_type":"date","subject_mention":"me","event_kind":"period_started",
            "event_mention":"College","temporal_value":"2007",
            "evidence":"2007 through 2011 as my College years"},
           {"claim_type":"date","subject_mention":"me","event_kind":"period_ended",
            "event_mention":"College","temporal_value":"2011",
            "evidence":"2007 through 2011 as my College years"}]}' \
  | python3 system/lifehug.py era-record --json

# replay: no second anything
… | python3 system/lifehug.py era-record --json   # "created": false everywhere

python3 system/lifehug.py era-record --list       # the era, its label, its aliases
python3 -m pytest tests/test_eras_e3.py -q
```

## Definition of done

1. `tests/test_eras_e3.py` green, every negative seen failing first.
2. Scoped suites green: `tests/test_temporal_*.py
   tests/test_landmark_recorder*.py tests/test_general_listener*.py
   tests/test_timeline_interaction*.py tests/test_eras_e0.py
   tests/test_eras_e1.py tests/test_extraction_claims.py
   tests/test_handbook_parity.py tests/test_interaction_evals.py`.
3. `vault_contract.json` digest recomputed, revision bumped, and importable.
4. Every regenerated golden diff READ and described in the PR body.
5. `system/version.json` untouched; the slot is assigned at green.

🤖 Generated with Claude Opus 5 via Claude Code
