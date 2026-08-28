# Contract: eras-o-e2-memberships

Phase **E2** of the Eras / Timeline program, OSS half (`O-E2`).
Platform tracking: lifehug-platform **#686**. Controlling authority:
lifehug-platform `docs/design/eras.md` (v3.1) §2.2–2.6, §5.1–5.3, §5.6,
§7 rows "Membership" / "Display role", §9.1 (T-M-01…10, T-SC-12/13, T-PL,
T-CV) and §13.2–13.4. Owner rulings there are closed and are not reopened
here.

Stacked on `docs/pr-specs/eras-o-e1-age-frames.md` (`O-E1`): the frames,
`PROJECTION_SCHEMA_VERSION = 2`, `CalculatedMembership`, `LIFE_VIEWS` and
`cross_dating.age_frames`/`frame_for` land there. **E2 fills the rows E1
declared.** It does not re-derive a frame, does not re-mint a node id, and
does not own the schema constants it extends.

## Why

Four separate mechanisms currently decide what is "inside" an era, and none of
them is a fact anybody stated:

1. **Source membership** (`timeline.heuristic_slot` rung 2, `:1057-1082`): if a
   long answer is cited on ONE era's wiki page, *every* moment the classifier
   extracted from that answer becomes a member of that era. This is the single
   mechanism behind the founder's *"College 1990–1991 before High School"* and
   *"My Teens 2007–2027"*: the kids' moments and the owner's own age statements
   entered eras by page citation, the eras were then dated from their members
   (`cross_dating.moment_envelope`), and the spine was sorted on those dates
   (design §1 item 1, reproduced to the year).
2. **`learned_era_vocabulary`** (`timeline.py:615-643`): each era silently
   acquires the token vocabulary of whatever the classifier said about its
   member sources, filtered for distinctiveness, and then places moments on
   ≥ 2 shared tokens. It is a model-authored keyword index derived from a
   membership rule that is itself wrong, and its inputs are the same
   classifications rung 2 already misread.
3. **`_PERIOD_KEYWORDS`** (`:592-600`): seven hardcoded English slugs. A vault
   whose roster names its eras anything else gets zero keyword slotting, and a
   vault whose roster happens to name one `my-40s` gets `"present"`,
   `"today"`, `"current"` mapped into it forever.
4. **A date is not consulted at all.** A moment dated 1995 placed by source
   membership into `Childhood (1981–1990)` stays there; `sort_period_events`
   only orders it *within* the era it was already wrongly given.

And nothing anywhere asks the question that actually matters for other
people's events: **whose life did this happen in, and why is it on the
owner's axis?** Charlee's 2022 Father's-Day letter sits in the owner's
Childhood; a classifier moment about a grandmother's age is dated off the
owner's birthday; a moment naming a roster person as its subject is placed on
the owner's timeline with no stated relationship at all.

E2 replaces all four mechanisms with two kinds of fact:

- **a membership is a receipt** — `sources/eras/memberships/<hex>.md` — or it
  is frame arithmetic, and there is no third source;
- **owner relevance is evidence** — a stated relationship *plus* an
  owner-relevant occurrence, each citing the record that says so.

## Binding facts (as of this branch's base, `origin/feat/eras-o-e1-age-frames` `9c34ddb`)

### The substrate E1 left for E2 to fill

- `system/temporal_projection.py`
  - `CalculatedMembership(membership_id, member_node_id, era_node_id, relation,
    evidence_refs, basis, confidence, display_role, input_fingerprint,
    schema_version)` with `validate_calculated_membership` /
    `membership_from_dict`; `derive_membership_id(member_node_id, era_node_id,
    relation)` → `membership:<24 hex>`. **`evidence_refs` is refused empty**
    (`membership_without_evidence`) — the schema already enforces "date overlap
    alone is not a membership".
  - `MEMBERSHIP_RELATIONS = ("within","overlaps","starts_in","associated_with")`,
    `MEMBERSHIP_DISPLAY_ROLES = ("primary","secondary","none")`,
    `PERIOD_EVENT_KINDS = ("age_frame","named_era")`, `LIFE_VIEWS =
    ("lived","future_plan")` with an explicit note that E2 extends it,
    `PROJECTION_SCHEMA_VERSION = 2`, `ORIGIN_BASES`.
  - `NODE_IDENTITY_KEYS` FROZEN; `validate_calculated_timeline_node` keeps
    unknown keys OUT of the normalized node, so a v2 field only exists once
    this contract adds it by name.
- `system/temporal_timeline.py`
  - `CalculatedTimeline.memberships` exists and is `()`;
    `structural_signature` and `temporal_publication.projection_payload`
    already carry it, so the projected `memberships` key needs no new plumbing.
  - `CALCULATION_RULE_VERSION = "timeline-rules:2"`.
  - `_node_dict(...)` builds every event/episode node; `_age_frame_nodes(...)`
    builds the frames; `as_of_day(now)` is the one `as_of`; `_life_view(best,
    as_of)` returns `lived`/`future_plan`.
  - `derive_calculated_timeline(active_index, *, resolution_records,
    roster_snapshot, constraints, birth_date, owner_ref, projection_generation,
    now, clock)` — pure, and every durable input arrives as a parameter.
- `system/cross_dating.py`
  - `age_frames(birth, *, as_of, death)` → `tuple[AgeFrame, ...]`;
    `frames_touching(frames, record)` → `((band, "within"|"overlaps"), …)`;
    `frame_for(frames, record)` → the one containing band or `None`.
    `FRAME_RELATIONS = ("within","overlaps")`. **A fuzzy interval keeps every
    overlap and nothing picks a winner.**
  - `age_frame_band_of(name_or_slug)` → band or `None`;
    `age_frame_legacy_slugs()` → `{band: (slug, …)}`.
  - `AGE_STATEMENT_RES` `:463-472` — five patterns. Patterns 1–2 require
    `i`/`we`; **patterns 3–5 have no subject at all** (`"30 years old"`,
    `"at the age of 30"`, `"at 19"`), so `from_age_statement` `:498-514`
    dates *any* such fragment off the OWNER's birthday. There is no
    third-person veto: `_BIRTH_OTHER_RE` `:248-254` vetoes somebody else's
    *birth* and nothing vetoes somebody else's *age*.
- `system/timeline.py` — the legacy pass
  - `_PERIOD_KEYWORDS` `:592-600`, `_ERA_STOPWORDS` `:603-607`, `_era_tokens`
    `:610-612`, `learned_era_vocabulary` `:615-643`, `_keyword_slot`
    `:1049-1054`, `heuristic_slot` `:1057-1082`, `place_events` `:1087-1136`,
    `retire_redundant_placements` `:1152-1191` (a second `learned_era_vocabulary`
    caller), `compute_gaps` `:1194-1226`, `era_gaps` `:1233-1268`,
    `UNKNOWN_KINDS` `:1394-1408`, `unknown_key` `:1424-1439`,
    `unknown_years` `:1569`, `_scored_things` `:2101-2145`.
  - `legacy_period_ref(ref)` `:170-192` (E1) is the one alias map.
- `system/classify_story.py` — **`is_current` and
  `current_classification_files` are `O-C`'s** (`feat/eras-o-c-stale-first`,
  v237) and `timeline.load_events` already reads through them there. E2
  duplicates none of it (see *Transitional dependencies*).

### The relationship evidence that exists today

- `landmark_projection.load_landmark_sources(vault_root)` `:654-698` →
  `[{"source_id","relative_path","domain","entry_key","ordinal","record"}, …]`
  — **the landmark DOMAIN of a promoted entry, keyed by the `source_id` every
  claim from that entry cites.**
- `landmark_projection.entry_claims` `:373-460` mints one `identity` claim plus
  a `date` claim per date/bound at `date_event_kind(row)` /
  `started` / `ended`. `date_event_kind` `:244-260`: one non-span semantic →
  that semantic (`children` → `birth`, `losses` → `death`), several →
  `transition` (so **a partnership's date claim is `transition`**, never
  `married`).
- `landmarks_interaction` domain rows carry `date_semantics` and the identity
  rung: `children.who`, `losses.who`, `family.who`, `partnerships.who`.
- `entity_roster` person rows carry `relationship`, `born`, `died`
  (`PERSON_DATE_FIELDS` `:353`, `_SETTLED_IDENTITY_FIELDS` `:348`);
  `landmarks_interaction.anchors_from_people` mints `person:<slug>:born|died`
  and `_family_anchor_key` mints `family:<relation>-<name>:birth`.
- **A defect found while reading this**: `landmark_projection._evidence_for`
  `:296-311` mints `{"quote", "locator"}` and
  `temporal_claims.EvidenceSpan` `:704-730` has **no `locator` field**, so
  `validate_evidence_span` silently discards it. The landmark domain therefore
  reaches a claim only inside the free-text `quote`. E2 does **not** parse a
  quote for identity; it takes the domain from `load_landmark_sources` as a
  pure parameter (below), and files the dropped field upstream.

## Scope

### O-E2a — the two receipt types (`system/era_memberships.py`, new)

One new module, so `O-E3`'s era identity / label / kind records land beside it
without a merge conflict in either.

| | Membership assertion | Display decision |
|---|---|---|
| path | `sources/eras/memberships/<24 hex>.md` | `sources/eras/display/<24 hex>.md` |
| `type` | `era_membership` | `era_display` |
| identity | `assertion_id = digest(member_node_id, era_node_id, relation, source_ref)` → `assertion:<24 hex>` | `decision_id = digest(member_node_id, primary_container_id, supersedes)` → `display:<24 hex>` |
| relations | `within` \| `associated_with` (design §2.3) | — |
| correction | retraction of **that** receipt (`file_temporal_correction(kind="retract", scope="era_membership")`) | supersession by a newer decision naming its predecessor |
| writer | `file_era_membership` | `file_era_display` |
| readers | `load_era_memberships` (status folded) → `active_era_memberships` | `load_era_displays` → `active_era_displays` |

Both are written with `temporal_store._create_or_keep`, `format_frontmatter`
and `payload_sha256`, exactly as `file_ordering_constraint` `:1064-1192` is,
and both validate the record the file *would* carry before a byte lands.
`source_ref` is inside the assertion digest **on purpose**: two independent
pieces of evidence for the same containment are two receipts and one
calculated membership (design §2.3, T-M-09/10).

Status folding is `load_ordering_constraints`' algorithm and not a second one:
marks over an unordered set, `STATUS_BY_CORRECTION_KIND`, `_strongest`, no
clock, no mtime. A display decision additionally marks its `supersedes`
target, so `active_era_displays` is at most one decision per member.

Registration: `system/vault_contract.json` gains `era_membership_sources` and
`era_display_sources` (`kind: directory`, `required: false`, `tracked: true`,
markdown_family schema 1), the `identity.revision` moves to
`vault-contract-v12` and `content_digest` is recomputed;
`lifehug_core._data()` gains `ERA_MEMBERSHIP_SOURCES_DIR` and
`ERA_DISPLAY_SOURCES_DIR`; `tests/test_v120_vault_only.py::EXPECTED_DATA_PATHS`
gains both names. **The contract test derives one side from the other**, so a
row without a `_data()` binding (or the reverse) fails the build — `O-C` hit
exactly this.

### O-E2b — the fold derives `memberships`

`derive_calculated_timeline` gains three pure parameters, in the shape
`roster_snapshot` and `constraints` already established:

```
membership_assertions = ()   # era_memberships.active_era_memberships(root)
display_decisions     = ()   # era_memberships.active_era_displays(root)
landmark_entries      = ()   # landmark_projection.load_landmark_sources(root)
```

`temporal_publication.publish` reads all three from the vault when the caller
passes nothing (`None` = "read them", a sequence = "use exactly these", `()` =
"none"), which is `constraints`' own convention.

**Frame membership is arithmetic.** For every non-period node with a
`best_temporal_value`, `cross_dating.frames_touching(frames, best)` yields the
relation per touched frame; a single containing frame is `within`, everything
else is `overlaps`, and a fuzzy interval keeps every overlap. Evidence is the
node's own input claim refs plus the rule name `rule:age-frame-arithmetic:1` —
never empty, and never a date-overlap-only citation for a *named* era.

**Named-era membership comes only from active assertions.** The fold reads
`membership_assertions`, groups them by
`(member_node_id, era_node_id, relation)`, and emits ONE
`CalculatedMembership` per group with every supporting `assertion_id` in
`evidence_refs`. It never reads a claim's `event_ref` to infer membership: an
era's own bounds claims carry the era's `event_ref`, an event's claim carries
the event's, and *"graduated in 2011 during college"* is one date claim plus
one membership assertion. Retracting one of two receipts leaves the membership
standing with one evidence ref (T-M-10); retracting the last one removes it.

**`display_role`** is the design's rule, in order: an active display decision
naming this container → `primary`; else an explicit legacy user placement →
direct event-level assertion → highest-supported membership (`confidence`,
then evidence count) → most-specific era (narrowest `best_temporal_value`) →
stable `era_node_id` tie-break. Exactly one `primary` per member; every other
membership of that member is `secondary`. Rendering only — it never changes a
date, an order or a relation.

**`observed_envelope`** is computed for every `named_era` period node as the
coverage of its explicit members' intervals (`chronology.span_from_dated`'s
own arithmetic through `cross_dating.span_from_dated`), stamped
`basis: "order"`, and it is **never** written to `best_temporal_value`,
`definition_span` or `possible_temporal_value`. No `named_era` node exists
until `O-E3`, so today it is exercised as a pure function and yields nothing
in an end-to-end fold — stated, not hidden.

### O-E2c — occurrence scope and owner relevance

New v2 node fields, additive, absent meaning unchanged:

```
occurrence_subject_scope: "owner" | "other_person" | "unresolved"
owner_timeline_relation:  "participated" | "lived_effect" | "contextual_only"
                          | "none" | "unresolved"
relation_evidence_refs:   tuple[str, ...]
observed_envelope:        dict | None
```

`temporal_projection` gains `OCCURRENCE_SUBJECT_SCOPES`,
`OWNER_TIMELINE_RELATIONS`, the four fields on `CalculatedTimelineNode`, their
normalization and the error codes `unknown_occurrence_subject_scope` /
`unknown_owner_timeline_relation`; `LIFE_VIEWS` gains `contradictory` and
`unresolved`, which E1's own docstring reserved for this phase.

Derivation, in the fold, per node:

1. the subject resolves to the owner → `owner` / `participated`, no evidence
   needed (it is the owner's own axis);
2. the subject is an unresolved mention → `unresolved` / `unresolved`. **Never
   `self` by default** — the existing `identity_uncertain` work item already
   carries this to Mirror, and no new work-item kind is introduced;
3. otherwise `other_person`, and the relation is decided by
   **the specific landmark entry behind the claim**, never by the domain name
   alone and never by the relationship alone:

   ```
   OWNER_RELEVANCE_BY_DOMAIN = {
       "children":     "lived_effect",
       "losses":       "lived_effect",
       "family":       "lived_effect",
       "partnerships": "participated",
   }
   ```

   and the entry supports **only the event kinds its own `date_semantics`
   mints** — `landmark_projection.date_event_kind(row)` plus `started`/`ended`
   for a span domain. So a `children` entry supports that child's `birth`; a
   `losses` entry supports that person's `death`; a `partnerships` entry
   supports its `transition`; and the same entry supports *nothing else about
   that person*. A node whose claims cite no such entry is
   `contextual_only`.
4. an occurrence wholly before the owner's supported birth interval is
   `contextual_only` whatever the table says (a grandparent's birth), and an
   OWNER-subject occurrence wholly before it is `life_view: contradictory`
   with a `before_owner_birth` diagnostic naming the birth node.

`relation_evidence_refs` cites the landmark entry's `source_id`
(`landmark:entry-<hex>`) and the identity claim id that named the person. A
relation of `participated` or `lived_effect` (or an `owner` scope) is what
**gates membership**: a `contextual_only` or `unresolved` node gets no frame
membership and therefore never lands on the axis — design §2.5's *"Not placed
yet · about someone else"*. The occurrence subject is **never rewritten to
`self`**.

### O-E2d — the legacy placement pass, rewritten (design §5.1)

`heuristic_slot(event, periods, *, frames=(), eras=(), anchors=None,
birth_date=None)` returns `(slug | None, placement_reason)`. Four rungs, and
the two removed mechanisms do not come back:

- **rung 0 — manual pin.** `place_events` keeps the pin as the overlay that
  always wins. New: **a pin is validated against the frames at filing**
  (`save_placement`) — a pin whose own date cannot be inside the frame its
  period maps to is refused with `placement_outside_frame`. A pin onto a
  non-frame period is unaffected.
- **rung 1 — dated.** `cross_dating.frame_for(frames, event["date"])` → band →
  the roster slug that aliases onto that band
  (`cross_dating.age_frame_legacy_slugs`). ONE definition, shared with the
  fold, parity-tested (`O-E2f`). `placement_reason.frame_by = "date"`.
- **rung 2 — named-era membership.** Whole-word (`\b…\b`) match of an active
  era label or alias against the event's OWN language (`when_hint`, then the
  classifier `eras`), with the subject veto; or a pin. Per-subject age
  arithmetic goes through the family anchors (`family:<relation>-<name>:birth`,
  `person:<slug>:born`), never the owner's birthday.
  `placement_reason.era_by = "event_language" | "pin"`.
- **rung 3 — undated.** Era-text keyword with the veto.
  `placement_reason.era_by = "era_text"`.
- **removed**: source membership (`event["source"] in period["sources"]`) and
  `learned_era_vocabulary` / `_era_tokens` / `_ERA_STOPWORDS`. A guard test
  fails the build if either name reappears anywhere in `system/`.
- `_PERIOD_KEYWORDS` survives as rung 3's table only, with its `my-20s`
  `"mission"` / `my-40s` `"present","today","current"` rows deleted: they are
  era *names* and *deixis*, not era language, and they are two of the founder's
  own mis-placements.

**The subject veto** is one new definition in `cross_dating`:

```
THIRD_PERSON_AGE_RES        # possessive / relation + age, e.g. "grandma was 30 years old"
age_statement_is_third_person(text) -> bool
```

built from `_BIRTH_OTHER_RE`'s own relation vocabulary (promoted, not
re-typed — the recurring-defect doctrine) and applied in
`from_age_statement`, so *"Grandma was 30 years old in 1951"* stops being
dated off the owner's birthday. `E-BO`'s `birth_origin_from_age` calls the
same predicate; it is exported for that.

**`placement_reason`** rides every legacy row:
`{rung, evidence, frame_by, era_by, subject_check, stale_excluded?}`, plus
`provenance_summary` — one sentence for the expanded card / eye pane.
`data["counts"]["stale_classifications_withheld"]` reports `O-C`'s withheld
set.

### O-E2e — bands (design §5.2)

- `era_gap` is retired from `UNKNOWN_KINDS`; `era_gaps()` and
  `MIN_ERA_GAP_YEARS` are deleted, `compute_gaps` no longer extends with them,
  `unknown_key`'s `era_gap` branch and `unknown_years`' `era_gap` row go with
  them, and `dependency_index`'s era-gap reach goes with them. **`residence_gap`
  stays** — the tiling chain is `landmarks_interaction.residence_gaps`' and is
  not touched.
- `_scored_things` excludes age frames: a frame is not a thing whose placement
  is in question, and scoring it would drop the placement level by counting
  the coordinate system as unplaced.

### O-E2f — the parity test, legacy ≡ fold (design §5.6)

Every rule shared between the legacy pass and the fold is asserted equal on
the same inputs:

- `timeline.heuristic_slot` rung 1's band ≡ `cross_dating.frame_for` on the
  same record — over a generated matrix of grains (day/month/year/decade),
  boundary years and open bounds;
- the subject veto ≡ the fold's `occurrence_subject_scope` on the same text;
- an event the fold gives no membership (`contextual_only`) is an event the
  legacy pass leaves off the axis.

Certification fails when they disagree on one event.

### Transitional dependencies (named, not hidden)

- **`classify_story.is_current`** is `O-C`'s and gates staleness inside
  `timeline.load_events`, upstream of this pass. E2 adds no second gate; the
  placement pass never sees a stale row by construction, and a guard test
  asserts the pass does not re-glob `CLASSIFICATIONS_DIR`. The
  `stale_classifications_withheld` counter reads
  `classify_story.withheld_stale()` **through one `getattr` shim marked
  `TRANSITIONAL`**, which is deleted the moment `O-C` and `O-E2` are both on
  `main`.
- **`named_era` nodes** are `O-E3`'s. Every named-era code path here is
  exercised through fixtures and pure functions and yields nothing
  end-to-end until E3 lands.

### Out of scope

`era-record` / `era-member` / `era-display` CLI verbs and era identity /
label / kind records (`O-E3`); the drag gestures that *file* these receipts
(`E5`); `birth_origin_from_age` (`E-BO`); rendering frames as bands and Play
on eras (`E3`/`E5`); `state/landmarks.json`; `system/version.json` — **the
version slot is taken at green**.

## Eight-part answers (design §7 discipline)

| Output | 1 input record | 2 writer | 3 identity | 4 correction | 5 fold | 6 aliases | 7 test | 8 rollout |
|---|---|---|---|---|---|---|---|---|
| Membership (named era) | `era_membership` receipt | `file_era_membership` (E5 drag / E3 recorder call it) | `digest(member, era, relation, source_ref)` → `assertion:<hex>` | retraction of that receipt | union of active receipts, one membership with N evidence refs | pins are not memberships — legacy overlay only | T-M-01…10 | additive `memberships` key; rollback ignores it, receipts never deleted |
| Membership (frame) | the member node's own claims | the fold | `derive_membership_id(member, `age:self:<band>`, relation)` | correcting the date corrects the membership | `cross_dating.frames_touching` | `legacy_period_ref` | T-M-01…04, T-PL | recalculated every publish; nothing durable |
| Display role | `era_display` decision | `file_era_display` | `digest(member, container, supersedes)` → `display:<hex>` | supersession | active decision else the §2.4 rule | — | T-M-08 | rendering only; absent = rule |
| Occurrence scope / owner relation | the landmark entry + the claim's subject resolution | the fold | node field, no id | correcting the entry or the resolution | §O-E2c 1–4 | — | T-SC-12/13 | additive v2 fields; absent = unchanged |
| `observed_envelope` | the era's explicit members | the fold | node field | member changes recompute it | coverage of members, `basis: order` | — | T-M-05 | additive; never a bound |
| Legacy `placement_reason` | the event + the frames + active era labels | `timeline.heuristic_slot` | row field | — | — | — | T-PL, T-CV | additive row key |

## Test plan (every negative test is SEEN failing before the code exists)

`tests/test_eras_e2.py` (own file — `tests/test_eras_e0.py` and
`tests/test_eras_e1.py` belong to the parent branches).

**Receipts**
- T-M-01 a membership assertion is content-addressed: filing the same
  `(member, era, relation, source_ref)` twice writes ONE file and returns the
  same `assertion_id`; a different `source_ref` writes a second.
- T-M-02 the receipt round-trips through `read_era_membership` with the
  `source_ref` rebuilt from the file's own bytes.
- T-M-03 an assertion whose relation is not `within`/`associated_with` is
  refused at filing; a `member`/`era` that is empty is refused.
- T-M-09 two assertions for one containment → ONE `CalculatedMembership` with
  two `evidence_refs`. **Negative first**: with the union rule absent, two
  memberships appear.
- T-M-10 retracting ONE of the two leaves the membership standing with one
  evidence ref; retracting the last removes it. **Negative first**: with
  retraction unread, the membership survives with two refs.
- T-M-08 a display decision makes exactly one membership `primary`; a
  superseding decision moves it; the rule applies with no decision at all.

**The fold**
- T-M-04 a day-grain event inside one frame is `within`; a year-grain event on
  a frame boundary `overlaps` both; a decade-grain event overlaps every frame
  it touches and NOTHING picks a winner.
- T-M-05 `observed_envelope` covers the members and is never copied into
  `best_temporal_value` / `definition_span`.
- T-M-06 a named-era membership is never derived from a claim's `event_ref`:
  a date claim carrying an era's `event_ref` yields no membership.
- T-M-07 the fold refuses to emit a membership with empty `evidence_refs`
  (E1's own `membership_without_evidence`), asserted through the fold.

**Owner relevance (founder-shaped, synthetic identities)**
- T-SC-12 a `children` entry's birth claim for `Cricket` (2010-12-21) enters
  as `occurrence_subject_scope: other_person`,
  `owner_timeline_relation: lived_effect`, `relation_evidence_refs` citing the
  `children` entry's `source_id`; a `losses` entry's death claim likewise.
- T-SC-13 a dated event about the same child that is NOT her birth (a
  `graduation` claim, subject `Cricket`) is `contextual_only`, gets **no frame
  membership**, and is off the axis. **Negative first**: without the gate it
  lands in a frame.
- **Charlee's letter** (synthetic `Cricket`, 2022-05, owner born 1981-07-11):
  positioned in the owner's 40s **by date**, `other_person` / `lived_effect`
  citing the `children` entry, and **no Childhood membership anywhere** — not
  from an assertion, not from the frame arithmetic, not from the legacy pass.
  **Negative first**: with source membership still present it is in
  Childhood.
- **"Grandma was 30 years old in 1951"** never seeds the owner's axis and
  never places: `from_age_statement` returns `None` under the third-person
  veto, and the moment carries `placement_reason.subject_check:
  "third_person_age"`. **Negative first**: without `THIRD_PERSON_AGE_RES` the
  moment is dated 1951 off the owner's birthday.
- an unresolved mention is `unresolved`/`unresolved`, never `owner`.
- an owner-subject occurrence before the supported birth interval is
  `life_view: contradictory` with the `before_owner_birth` diagnostic.

**The legacy pass**
- T-PL rung order: a pin beats a date, a date beats era language, era language
  beats era text; each row's `placement_reason` names the rung that fired.
- source membership is gone: an event whose ONLY signal is that its source is
  cited on an era page is **unplaced**. **Negative first.**
- `learned_era_vocabulary`, `_era_tokens` and `_ERA_STOPWORDS` do not exist
  anywhere in `system/` (AST/grep guard, seen failing before the deletion).
- a pin whose date cannot be inside its period's frame is refused at filing.
- `era_gap` is absent from `UNKNOWN_KINDS`, from `unknown_key`, from
  `unknown_years` and from `dependency_index`; `residence_gap` still works.
- `_scored_things` contains no `age_frame` row.
- T-CV a moment with no era stays a row with `placement_reason` and its
  correction path intact.

**Parity (design §5.6)**
- legacy rung 1 ≡ `cross_dating.frame_for` over a grain × boundary matrix.
- the legacy subject veto ≡ the fold's `occurrence_subject_scope`.

## Launch-and-verify

```
cd ~/Workspace/lifehug
python3 -m pytest -q tests/test_eras_e2.py
python3 -m pytest -q tests/test_eras_e0.py tests/test_eras_e1.py \
  tests/test_timeline.py tests/test_projection_publication.py \
  tests/test_cross_dating.py tests/test_v103_placement_loop.py \
  tests/test_v120_vault_only.py tests/test_handbook_parity.py
python3 -c "import sys; sys.path.insert(0,'system'); import vault_paths; print(vault_paths.VAULT_CONTRACT['identity'])"
```

## Definition of done

1. Two receipt types exist, are content-addressed, registered in the vault
   contract *and* in `lifehug_core`, retractable / supersedable, and replay to
   one file.
2. `memberships` is populated: the union of active receipts for named eras and
   pure arithmetic for frames, with `display_role` decided once.
3. Every node says whose occurrence it is and why it is on the owner's axis,
   citing the record that says so — and a node that cannot say so is off the
   axis rather than silently on it.
4. Source membership and `learned_era_vocabulary` are gone, guarded against
   return; `era_gap` is retired; every legacy row explains itself.
5. Legacy ≡ fold on every shared rule, asserted.
6. Scoped suites green; `system/version.json` untouched (slot taken at green).

🤖 Generated with Claude Opus 5 via Claude Code
