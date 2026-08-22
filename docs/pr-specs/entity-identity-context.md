# Contract: entity-identity-context

## Why

Platform contract `review-loop/57` ("Entity Play is graduation + identity, in
the background") applies to ENTITY candidates what `review-loop/54` applied to
FOCUS candidates and `review-loop/45` applied to question candidates: Play is
not a typed research session that holds a decision until some state machine
resolves — it graduates, commits in the background, and opens an ordinary
conversation.

An entity is not a focus. Graduating one is cheap (`entity-verdict <type>
<slug> graduate`, one roster mutation, one commit), there is nothing to
scaffold, and there are no questions to seed. So the conversation that opens
has a different job from the focus one: **establish WHO or WHAT this is** —
the names they go by, how they are related, whether they are living, and
whether the roster already has a page for this same person under a different
name (the four Jameses). That is identity, not scope.

Three facts make this an OSS change rather than a platform one.

1. **This Interaction's premise is retired.** `interactions/entity_candidate/`
   was designed against ADR 0022's "Play/start is read-only … Completion
   delegates to the canonical candidate-research source authority and leaves
   the entity roster pending." Under review-loop/57 Play *is* graduation: the
   `entity-verdict … graduate` job runs at Play, and the conversation that
   opens is identity onboarding, not research toward a later approval. The
   child's README says "Play is read-only"; that sentence is now false.
2. **The roster has no way to be told an identity fact.** `entity-verdict`
   takes exactly `<type> <slug> graduate|never|clear` — there is no door for
   "she also goes by Jo", "she's my mother", "she died in 2019", or "this is
   really the Jim Reynolds page you already have". Every one of those is
   something the person says in the first two minutes of the conversation Play
   opens, and today the package would drop all of it on the floor.
3. **The entity → focus hand-off has no seam.** Owner ruling 4 forbids the
   entity conversation from ever creating a focus, but permits it to OFFER
   one. A yes has to reach the existing focus mechanics without inventing new
   ones — and the only thing those mechanics consume is a row in
   `state/focus_recommendations.json`. There is no package verb that writes
   one for an entity.

This PR is the smallest change that fixes all three: one repurposed prompt
leaf, exactly one additive turn-output field, five pure helpers, seven lints,
eight goldens, four new flags on one existing verb, and one new verb whose
entire job is appending a recommendation row.

## Rulings (owner, 2026-08-22 — verbatim, binding)

1. **Play = graduate + start the identity conversation.**
2. **✓ = graduate, nothing asked; ✗ = never, unchanged.**
3. **First reply**: the aside *"I've added **{name}** as a {type} in your
   story — tell me if that's the wrong name or the wrong person"* + **at most
   ONE identity question** (person → relationship/living; any type → "is this
   the same as \<existing page\>?" only when a likely duplicate exists);
   **afterwards identity changes only when the USER signals.**
4. **Entity Play NEVER creates a focus automatically**; the conversation MAY
   offer one, **at most once per session**, only for offer-worthy entities
   (person/place/period/theme — **the package decides**); a yes is recorded as
   `start_focus: true` and the PLATFORM hands off to its existing focus
   mechanics.
5. **No platform placement**: the platform substitutes stage/name/type/
   duplicates into the package's leaf and records the output.

## Binding facts

As of `origin/main` `6c84eafe`, `system/version.json` version **189**,
released 2026-08-22.

**The precedent this PR copies, line for line.**

- `docs/pr-specs/focus-onboarding-context.md` (v189) — the contract shape, the
  "exactly one additive output field" discipline, the two-layer validation
  split, the transcript-derived stage, the lint table, the golden list, the
  platform-twin table.
- `system/focus_candidate.py:481` `opening_question`, `:500`
  `focus_stage_for_session`, `:534` `validate_focus_setup`, `:576`
  `normalize_onboarding_context`, `:660` `lint_focus_setup_reply`, `:52`
  `FOCUS_RELATIONSHIPS`, `:77` `VALID_FOCUS_STAGES`, `:365`
  `_research_output_contract_block`.
- `system/conversation_delivery.py:151` `TurnShape` (`:177`
  `focus_stage: str | None = None`), `:300` `_output_contract_block` (the
  `focus_setup_line`/`focus_setup_note` gating), `:418` `parse_turn_output`,
  `:503` `_parse_focus_setup` (the structural layer that owns no vocabulary
  and never raises).
- `system/focus_candidate_evals.py:16–58` (a SECOND, independent golden pair
  beside the frozen ADR-0022-era one), `:85–250` (loaders, fixture validation,
  `score_onboarding_goldens`), `:395–420` (both pairs, one `check_gates` call).

**The entity side as it stands.**

- `interactions/entity_candidate/README.md:8` — "Play is read-only."
- `interactions/entity_candidate/prompt/turn-instructions.md` — today it
  declares the RESEARCH-mode output object (`reply/action/next_gap/
  evidence_spans/dimension_evidence/seed_questions/confirmation_span`). That
  declaration is what `parse_entity_candidate_output`
  (`entity_candidate.py:666`) parses on the standalone
  `entity-candidate-prompt` path.
- `system/entity_candidate.py:410` `build_entity_candidate_prompt`, `:460`
  `lint_entity_candidate_reply`, `:20` `ENTITY_DIMENSIONS`, `:37`
  `ENTITY_TYPE_SPECIFIC_MIN_REFS`.
- `system/entity_verdict.py:62` `VERDICTS`, `:71` `apply_verdict` (refuses
  `graduate` on an entity whose `maps_to_focus` is set — "it already has a
  home there"), `:120` `main`.
- `system/entity_roster.py:56` `ENTITY_TYPES = person|place|period|object|
  theme`, `:271` `_entity_keys` (the roster's OWN alias/match-key logic, built
  on `lifehug_core.normalized_focus_key`), `:330` `apply_previous_decisions`
  (the settled-fact carry-forward, including the `keywords` precedent this PR
  copies for `relationship`/`living`), `:571` `base_page_eligible`, `:588`
  `apply_owner_verdict`, `:612` `normalize`, `:713` `load_roster`.
- `system/focus_dupes.py:52` `_tokens` / `:57` `_token_subset_pairs` — the
  repo's existing likely-duplicate shape ("Betty Jo" vs "Grandma Betty Jo"),
  reused here rather than re-derived.
- `system/recommend_focuses.py:49` `FOCUS_RECOMMENDATION_TYPES`, `:655`
  `load_recommendation_state`, `:766–786` the recommendation row literal,
  `:879` `approve_recommendation` (**unchanged by this PR**).
- `system/jobs.py:352` `_build_entity_verdict`, `:709` the `entity-verdict`
  `CommandSpec` — the platform's only path to the verb.
- `system/wiki_compile.py:353` `frontmatter(...)` — has **no**
  relationship/living parameter; `:714` `plan_entities` matches sources by
  `[name] + aliases`.

**Handbook / manifest discipline.**

- `tests/test_handbook_parity.py` `EmbedParityTests` — `docs/handbook/
  interactions/entity-candidate.md` embeds `interactions/entity_candidate/
  prompt/behavior.md` byte-for-byte. **`behavior.md` is unchanged by this PR**,
  so the embed does not move; the page's prose around it does.
- `tests/test_entity_candidate.py:211` and `tests/test_focus_candidate.py:211`
  digest `interactions/conversation/` and `interactions/question_candidate/`
  only — this PR touches neither, so those digests do not move.
- `system/version.json` `framework_files` ships every
  `interactions/entity_candidate/**` file; the two new golden files are added
  in the same bump.

## Scope

**In:** the child README/prompt correction to the ADR-0020/review-loop-57
model; the `entity_setup` turn-output field (structural parse + closed
validation); the `opening_question`, `entity_stage_for_session`,
`possible_duplicates`, `is_offer_worthy` and `lint_entity_setup_reply`
helpers; seven `entity_setup_gates.*` lints; eight identity goldens wired into
`entity-candidate-evals`; `entity-verdict --alias/--relationship/--living|
--not-living/--maps-to` and the roster carry-forward that makes those facts
survive a refresh; `recommendation_for_entity` + `focus-recommend-from-entity`;
the ADR 0022 amendment and the ADR 0018 third-instance row; the handbook
refresh; the version bump.

**Out (deliberate, named):**

- Retiring `parse_entity_candidate_output`,
  `validate_entity_candidate_decision`,
  `resolve_entity_candidate_completion`, the `action`/`next_gap` machinery,
  the research goldens, or the `research_gates.*` rows. The standalone
  `entity-candidate-prompt` / `entity-candidate-complete` CLI path still uses
  every one of them; they are marked **superseded for the Play path** and left
  in place. Deleting them is a separate PR, if ever.
- **Carrying `relationship`/`living` into wiki page frontmatter.**
  `wiki_compile.frontmatter()` has no such fields and the entity page's
  frontmatter is regenerated from `plan_entities` on every compile; adding two
  new frontmatter keys is a compiler change with its own migration surface.
  The facts are stored on the roster entry (`entity_roster.normalize` and
  `apply_previous_decisions` carry them forward exactly as they already carry
  `keywords`) and are readable there by anything that wants them. Filed as a
  follow-up, not smuggled in here.
- **Splitting a wrongly-merged entity.** `--maps-to` heals a duplicate; the
  inverse still requires hand-editing `state/entity_rosters/<type>.json`,
  exactly as `apply_previous_decisions`' docstring already documents.
- Any change to ordinary Conversation prompt bytes, to `approve_recommendation`,
  to `focus_play`/focus scaffolding, to the registry, or to the composition
  policy.
- Entity graduation thresholds (`THRESHOLDS`, `base_page_eligible`) and the
  `>= 1 real mention` floor on owner-graduated pages (ADR 0013) — untouched.

## Design

### A. The child stops being read-only research and becomes identity onboarding

**A1. `interactions/entity_candidate/README.md`.** "Play is read-only.
Confirmed completion delegates to the canonical candidate-research source
authority and leaves the entity roster pending. Only independent entity
eligibility or an owner graduation can create a page." is false under platform
ADR 0020 + review-loop/57. Replaced with: Play graduates the entity in a
background job and opens this conversation immediately; this Interaction is
that conversation, and its job is establishing identity. The research-mode
assets stay for the standalone CLI path and are marked superseded for the Play
path — not deleted.

**A2. `prompt/turn-instructions.md` becomes the stage-keyed leaf.** Exactly the
shape `focus_candidate`'s leaf took at v189. The child no longer declares its
own output object; it declares the PARENT's contract plus one optional field,
and the rules for this turn. Placeholders, substituted by the caller and
nothing else (ruling 5):

| placeholder | value |
|---|---|
| `{entity_stage}` | `establish` \| `settled` — `entity_candidate.entity_stage_for_session` |
| `{entity_name}` | the roster entry's `name` |
| `{entity_type}` | one of `ENTITY_TYPES` |
| `{possible_duplicates}` | comma-separated existing page names, or the literal `none` — `entity_candidate.possible_duplicates` |

- `establish` — receive the answer as any Conversation turn would, then append
  ONE sentence: *"I've added **{entity_name}** as a {entity_type} in your
  story — tell me if that's the wrong name or the wrong person."* Not a
  question, said once, never again. Then ask AT MOST ONE identity question:
  when `{possible_duplicates}` is not `none`, whether this is the same as that
  existing page (a duplicate outranks a relationship); otherwise, for a
  `person`, how they are related or whether they are living. Ask nothing when
  the answer already said.
- `settled` — say nothing about who this is, what to call them, or whether
  they are someone we already have. Only when the USER's own message changes
  one does the turn receive it in a clause and carry it in `entity_setup`.
- **The offer** — at most once per session, only when `{entity_type}` is
  `person`, `place`, `period`, or `theme` (ruling 4's list, which is exactly
  `recommend_focuses.FOCUS_RECOMMENDATION_TYPES`), and only if the transcript
  shows no earlier offer: one sentence, *"If they're someone you want to build
  out, say so and I'll start a focus."* The model never says a focus WAS
  started; a yes is recorded as `entity_setup.start_focus`, and the platform
  does the rest.

**A3. The research output contract moves from the leaf to the runtime.** Same
reasoning and same mechanism as v189's §A.3: the research JSON object cannot
stay in a leaf that the platform appends to an ordinary Conversation prompt —
two competing "return exactly one JSON object with exactly these keys"
contracts is a defect, not a composition. It moves into
`entity_candidate._research_output_contract_block()` and is appended by
`build_entity_candidate_prompt`, byte-for-byte what the leaf carried. A
required test proves the standalone prompt still contains every research key
it contained at v189.

**A4. `opening_question(name, entity_type)`** — a pure helper returning the
first thing the person sees when Play opens the tab (the platform's
`question_text`; review-loop/57 §A). One short, natural line, type-aware, no
machinery:

| type | line |
|---|---|
| `person` | `Tell me about {name} — who are they to you?` |
| `place` | `Tell me about {name} — what happened there that makes it matter?` |
| `period` | `Tell me about {name} — what was that stretch of your life like?` |
| `object` | `Tell me about {name} — what makes it worth keeping?` |
| `theme` | `Tell me about {name} — where does that show up in your life?` |
| unknown/blank | `Tell me about {name} — what should I know about it?` |

A blank `name` raises, because an opener with no subject is a caller bug, not a
degradation.

### B. The `entity_setup` field — schema and where it is validated

Exactly one new key in the structured turn output, additive and optional:

```json
"entity_setup": {"aliases": ["Jo"], "relationship": "parent", "living": false,
                 "type": "person", "maps_to": "jim-reynolds", "start_focus": true}
```

`null` or absent on every ordinary turn, and on every identity turn where the
user said nothing about who this is. All six inner keys are optional; a turn
carries only what the user actually supplied.

Two validation layers, the same split as `placement` (v188) and `focus_setup`
(v189):

1. **Structural** — `conversation_delivery._parse_entity_setup`, called from
   `parse_turn_output`. Accept only an object whose keys are a subset of
   `{aliases, relationship, living, type, maps_to, start_focus}`. Each string
   value is `.strip()`ed and must be non-empty and ≤ 500 characters; `aliases`
   must be a list, each entry a non-empty trimmed string ≤ 500 characters,
   with at most 32 entries surviving; `living` and `start_focus` must be real
   `bool`s (never `0`/`1`/`"yes"`). Individually invalid values are dropped;
   an object that is not a dict, carries an unknown key, or ends up empty →
   `None`. Never raises. `conversation_delivery` owns no vocabulary and
   performs no membership check.
2. **Closed** — `entity_candidate.validate_entity_setup(value, *,
   roster_slugs)`:
   - `type` ∈ `entity_roster.ENTITY_TYPES` — `person, place, period, object,
     theme` — exact match, no case-fold, no fuzzy.
   - `relationship` ∈ `focus_candidate.FOCUS_RELATIONSHIPS` — imported, never
     re-listed (recurring-defect doctrine; the two lanes ask the same question
     and must not drift).
   - `living`, `start_focus` — `bool` only.
   - `aliases` — trimmed, non-empty, deduplicated case-insensitively while
     preserving order, each ≤ `MAX_ENTITY_ALIAS_CHARS` (80), at most
     `MAX_ENTITY_ALIASES` (8). An empty result drops the key.
   - `maps_to` — must be a member of the caller-supplied `roster_slugs`. The
     package refuses to invent a merge target: a slug nobody has heard of
     drops the key rather than producing a dangling map.

   An invalid value drops that key; no valid key remaining → `None`.

`Turn.entity_setup` is recorded additively by the caller (the platform's
`Turn` model; there is no OSS turn record to change), guarded by that side's
stored-shape test.

### C. The stage and the duplicates need no new state

`entity_stage_for_session(session)` is `focus_stage_for_session`'s twin: the
aside and the one identity question both live on the FIRST assistant reply, so
"have we onboarded?" is exactly "does this session have an assistant turn?".

```python
def entity_stage_for_session(session: dict) -> str:
    return "settled" if any(t.get("role") == "lifehug" for t in session["turns"]) else "establish"
```

`possible_duplicates(entity_type, name, roster) -> list[str]` **reuses the
roster's own matchers and adds none**:

- `entity_roster._entity_keys` — the roster's alias/match-key logic (name +
  slug + aliases, lowercased, slugified, `normalized_focus_key`ed,
  `"the "`-stripped), itself the single authoritative normalization every
  Focus-creation door already shares. Any roster entry whose key set
  intersects the subject's is a duplicate candidate.
- `focus_dupes._token_subset_pairs` — the repo's existing near-name shape
  (one label's token set a PROPER subset of another's: "Jim" vs "Jim
  Reynolds"). Only pairs involving the subject are kept.

Entries carrying `owner_verdict == "never"` and the subject's own row are
excluded; the result preserves roster order, then near-name order, and is
capped at `MAX_POSSIBLE_DUPLICATES` (5) so the leaf stays bounded.

`is_offer_worthy(entity_type, roster_entry) -> bool` — `True` when the type is
in `recommend_focuses.FOCUS_RECOMMENDATION_TYPES` (person/place/period/theme —
ruling 4's list, read from the one module that can actually express a
recommendation of that type, not re-typed here) AND the entry is neither
owner-vetoed (`owner_verdict == "never"`) nor already mapped
(`maps_to_focus`). An entity that already has a focus does not need an offer.

### D. Lints

New gate class `entity_setup_gates.*` in
`interactions/entity_candidate/evals/lints.yaml`, produced by a new pure
function `entity_candidate.lint_entity_setup_reply(text, *, stage,
user_signaled=False, offered_before=False)` whose findings share
`conversation_lints.lint_turn`'s shape. An unrecognized stage is treated as
`settled` (fail toward the strictest rule).

| lint id | rule | applies on |
|---|---|---|
| `entity_setup.aside_single_sentence` | the aside appears exactly once and is exactly one sentence | `establish` |
| `entity_setup.aside_not_a_question` | the aside sentence contains no `?` | `establish` |
| `entity_setup.aside_never_repeated` | no aside sentence at all | `settled` |
| `entity_setup.one_identity_question` | the reply contains at most one `?` | every turn |
| `entity_setup.settled_silence` | no identity talk unless `user_signaled` | `settled` |
| `entity_setup.offer_at_most_once` | no focus OFFER sentence when `offered_before` | every turn |
| `entity_setup.no_mechanism_talk` | no "I'll create", "wiki page", "the roster", "the system will", "I've started a focus" | every turn |

The aside's invariant anchor — what every aside lint locates — is
`added … in your story` (ruling 3's wording; the model varies the connective
tissue, never the move). The offer's anchor is a sentence containing both a
conditional (`if`/`want`/`would you`) and `start a focus`: the lint locates the
OFFER shape, so a reply that merely records a yes ("Jo, then.") is not an
offer, and a reply that CLAIMS a focus was started is caught by
`no_mechanism_talk` instead.

An `entity_setup` lint failure is a lint failure exactly as an inherited
Conversation lint failure is; the documented degradation is one retry WITHOUT
the aside before degrading further (the recipe v188 and v189 both prescribe).

### E. The verb: `entity-verdict` learns identity

**Chosen: extend `entity-verdict`, not a new `entity-set`.** The platform
already has the endpoint, the authz row, and the `jobs.py` builder for
`entity-verdict`; a second verb would mean two writers for one roster file and
two doors for one settled fact — precisely the shape the recurring-defect
doctrine exists to prevent. Graduation and identity arrive from the SAME
background job in review-loop/57 §A, so they belong in the same call.

```
entity-verdict <type> <slug> graduate|never|clear
    [--alias A]... [--relationship R] [--living|--not-living] [--maps-to SLUG] [--json]
```

- `--alias A` (repeatable) — unioned into the entry's `aliases`, trimmed,
  deduplicated case-insensitively, capped at `MAX_ENTITY_ALIASES`. The
  compiler already matches sources against `[name] + aliases`
  (`wiki_compile.plan_entities`), so an alias is the fact that makes the page
  find its own material.
- `--relationship R` — must be in `focus_candidate.FOCUS_RELATIONSHIPS`;
  refused otherwise, before any write.
- `--living` / `--not-living` — mutually exclusive; stores a real bool.
- `--maps-to SLUG` — the merge. SLUG must be either another entity's slug in
  the SAME roster or a known focus slug (`entity_roster._focus_map()`); a
  self-map or an unknown slug is refused before any write.

**`--maps-to` precedence: maps-to wins.** When `--maps-to` is supplied
together with the `graduate` verdict, the mapping is applied and the
`graduate` verdict is **not** — a mapped entity already has a home, which is
exactly the rationale of the pre-existing refusal at
`entity_verdict.py:110`. Nothing raises, because review-loop/57's `:identity`
job is a single background call that always carries the graduation and
whatever identity it learned; making that call fail would strand the identity.
The CLI says so on stdout and the `--json` output carries the resulting record
(whose `maps_to_focus` is set and whose `page_eligible` is `False`). Without
`--maps-to`, `graduate` on an already-mapped entity keeps raising exactly as
it does today — that refusal and its test are untouched.

**When SLUG names another entity in the same roster**, the candidate's `name`
and every alias are additionally unioned into THAT entry's `aliases`. This is
not an invention: `plan_entities` matches by `[name] + aliases` and
`apply_previous_decisions` folds by `_entity_keys` (which reads aliases), so
folding the loser's names onto the survivor is how "this is really that page"
is expressed in this system — and it is what makes the merge survive the next
roster refresh even after the loser's own row stops being proposed.

**Idempotent.** Re-running the identical command converges to the identical
roster bytes: the alias union deduplicates, `relationship`/`living`/
`maps_to_focus` are assignments, and the verdict path is unchanged.

**Roster carry-forward.** `relationship` and `living` are settled facts, so
they must survive a roster refresh the way `keywords` and `owner_verdict`
already do:

- `entity_roster.normalize()` copies a validated `relationship` (non-empty
  string) and `living` (real bool) from the raw entry onto the normalized
  entry.
- `entity_roster.apply_previous_decisions()` carries a previous entry's
  `relationship`/`living` onto the folded slot when this refresh's raw entry
  does not supply them — the exact `keywords` recipe one block above it.
- The empty-refresh survivor filter and the no-raw-match survivor loop widen
  from `owner_verdict` to `_has_settled_identity(entry)` — `owner_verdict` OR
  a stored `relationship` OR a stored `living`. An entity the owner has told
  us about is a settled fact, not a re-derivable one. Entities carrying none
  of the three are dropped by an empty refresh exactly as they are today.

### F. The hand-off seam: one row, no focus

`recommend_focuses.recommendation_for_entity(roster_entry, *, now=None) ->
dict` — a pure helper (pure given a clock) producing a row shaped EXACTLY like
the ones `recommend()` emits:

```python
{"id": "rec-<slug>", "entity": name, "type": entity_type, "score": …,
 "evidence_strength": …, "mention_count": …, "unique_answers": …,
 "cross_categories": [], "emotional_weight": 0.0, "evidence": [],
 "reason": "owner asked during entity onboarding", "status": "pending",
 "created_at": now, "ready_to_start": False}
```

`reason` is ruling 4's own words, verbatim and constant
(`ENTITY_ONBOARDING_REASON`). `ready_to_start` is `False`: the row exists to be
approved by the hand-off the owner already asked for, not to be advertised as a
suggestion. The type must be in `FOCUS_RECOMMENDATION_TYPES`; `object` is not
offer-worthy and raises. The row-key parity with `recommend()`'s literal is
pinned by an AST test (`RECOMMENDATION_ROW_KEYS`), so a future key added to one
and not the other fails the build.

`recommend_focuses.append_entity_recommendation(entity_type, slug, *,
now=None) -> dict` loads the roster, builds the row, and appends it to
`state/focus_recommendations.json` **idempotently**: an existing row with the
same id short-circuits with `{"created": False, "recommendation": <existing>}`
and writes nothing at all. It **creates no focus** — no `focus_new`, no
`approve_recommendation`, no category. A required test asserts the roadmap is
byte-identical across the call.

The verb: `focus-recommend-from-entity <type> <slug> [--json]` (also
`recommend_focuses.py --from-entity TYPE SLUG`), classified as a direct
mutation command and registered in `jobs.py` so the platform can enqueue it.
**This is the only seam the platform uses for `start_focus`.**

A previously-dismissed `rec-<slug>` is still appended: the owner just asked
for it out loud, which outranks an earlier automatic dismissal. Documented, not
silent.

## Required tests

`python3 -m unittest discover -s tests` (and `python3 -m pytest -q`) green.

**`tests/test_entity_identity_context.py`** (new — one file for the whole
contract, including the delivery-engine layer, so the v190 surface reads as one
thing rather than being scattered across five existing files)
- `test_output_contract_block_byte_identical_without_entity_stage` — a
  `TurnShape` with no `entity_stage` produces the exact pre-v190 appendix.
- `test_entity_setup_line_and_note_present_when_staged` — both stages.
- `test_entity_setup_absent_is_none`.
- `test_entity_setup_malformed_degrades_never_raises` — non-dict, unknown key,
  empty object, blank string, 501-char value, `living: 1`, `aliases: "Jo"`,
  `aliases: [""]` → `None` or the key dropped, never an error.
- `test_entity_setup_partial_object_survives` — a lone `{"start_focus": true}`.
- `test_all_three_additive_fields_coexist_in_a_stable_order` — placement,
  focus_setup, entity_setup, rolling_summary.
- `test_opening_question_is_type_aware_and_one_line` / unknown-type fallback /
  blank-name raise.
- `test_entity_stage_for_session_derived_from_transcript`.
- `test_possible_duplicates_finds_alias_and_near_name_matches`, excludes the
  subject itself and `never`-vetoed rows, caps at five, reuses the roster's
  matcher (a monkeypatch on `_entity_keys` changes the result — the pin that
  no second matcher exists).
- `test_validate_entity_setup_closed_vocabularies` + rejects unknown type,
  unknown relationship, unknown `maps_to`, non-bool `living`/`start_focus`,
  over-long/over-many aliases; drops only the invalid key.
- `test_entity_setup_keys_match_the_structural_layer`.
- `test_relationships_are_the_focus_lane_list` (recurring-defect parity).
- `test_is_offer_worthy_matches_focus_recommendation_types` +
  vetoed/mapped are not offer-worthy.
- `test_entity_setup_lint_*` — one per §D row, passing and failing reply each;
  unknown stage fails toward `settled`; findings share the inherited shape.
- `test_leaf_is_stage_keyed_and_placeholder_bearing`.
- `test_research_output_contract_survives_the_leaf_move`.
- `entity-verdict`: aliases union + dedupe + cap; relationship refused
  off-vocabulary; `--living/--not-living`; `--maps-to` to an entity folds the
  loser's names into the survivor and sets `maps_to_focus`; `--maps-to` to a
  focus slug; self-map and unknown slug refused with the roster byte-identical;
  maps-to beats graduate in one call without raising; `graduate` on a mapped
  entity STILL raises without `--maps-to`; idempotence across two identical
  runs; CLI surface + `--json`; `jobs.py` builder shapes a valid argv and
  rejects bad payloads.
- roster carry-forward: `normalize` keeps a validated relationship/living and
  drops invalid ones; `apply_previous_decisions` carries them onto the folded
  slot and survives an empty refresh; an entity with none of the three settled
  facts is still dropped by an empty refresh.
- `recommendation_for_entity`: row keys equal `RECOMMENDATION_ROW_KEYS` (and
  the AST pin against `recommend()`'s literal); `object` raises; the reason is
  the ruling's constant; `append_entity_recommendation` is idempotent, writes
  nothing on the second call, and creates no focus.

**`tests/test_entity_candidate_evals.py`** — the eight identity goldens load,
validate, score, and gate; a deliberately-bad prediction fails its own class
only.

**Goldens** — `interactions/entity_candidate/evals/goldens/identity_fixtures.json`
+ `identity_sample_predictions.json`:

1. `identity-establish-aside-and-one-question` — aside once, then one question.
2. `identity-establish-duplicate-asks-same-as` — a likely duplicate exists; the
   single question asks whether it is the same page (not the relationship).
3. `identity-establish-answer-already-told-asks-nothing` — the opener already
   said; aside, NO question, `entity_setup` carries relationship + living.
4. `identity-establish-offer-worthy-appends-offer` — person; aside, one
   question, and the offer sentence; `offered_before` false.
5. `identity-settled-silent` — an ordinary later turn: no identity talk, null.
6. `identity-settled-user-signals-emits-setup` — "call her Jo too, and yes,
   start a focus" → `{"aliases": ["Jo"], "start_focus": true}`, one-clause
   receipt, no confirmation question, no mechanism talk.
7. `identity-settled-offer-not-repeated` — `offered_before` true; the reply
   carries no offer sentence and no setup. (The pin for ruling 4's cap.)
8. `identity-unknown-relationship-rejected` — a reply naming
   `"grandmother-in-law"` normalizes to no relationship without failing the
   turn.

**Harness** — `python3 system/lifehug.py entity-candidate-evals` passes with
the new pair scored into `entity_setup_gates.*` beside the existing
`research_gates.*`, one `check_gates` call; `focus-candidate-evals` and
`question-candidate-evals` are untouched and pass.

## Version bump

`system/version.json`: **189 → 190**, `released` set to the merge date, a full
changelog paragraph, and the two new golden files added to `framework_files`
in the same bump.

## ADR amendments

**`docs/adr/0022-entity-candidate-interaction.md`** — Status `proposed` →
`amended 2026-08-22 by docs/pr-specs/entity-identity-context.md`.

| Location in 0022 | Change |
|---|---|
| Decision, "It does not own approval or Git writes." | Unchanged as to the MODEL, but the surrounding premise moves: the platform graduates at Play, in a background job; this Interaction is the identity conversation that follows, not research toward a later graduation. |
| Consequences, "Play/start is read-only." | **Reversed.** Play is graduation + start (platform ADR 0020, review-loop/57). The model still writes nothing and claims nothing; the *platform* has already graduated. |
| Consequences, "Platform Play may deep-link into this Interaction after pinning v185, but must resolve the anchor server-side and must not approve on entry/completion." | Superseded: Play graduates on entry by design; the platform's only model-facing job is substituting the four placeholders into the leaf and recording `entity_setup`. |
| Decision, the seven-dimension research rubric and completion delegation | **Superseded for the Play path, retained for the standalone CLI path.** `entity-candidate-prompt` / `entity-candidate-complete` and their evals are unchanged. |
| Decision, "the recommendation remains pending until the existing automatic eligibility or owner verdict authority acts." | Narrowed to the standalone path. On the Play path the owner-verdict authority acts FIRST (that is what Play is), and the conversation supplies identity to the same authority through `entity-verdict`'s new flags. |

**`docs/adr/0018-candidate-placement.md`** — one amendment row: the additive-
field discipline now has a THIRD instance, `entity_setup`, with the same
two-layer split and the same "absent or malformed degrades, never errors" rule.
No decision in 0018 changes.

**No new ADR.** The decision that made this necessary is platform ADR 0020 +
review-loop/57; this contract records behavior changes inside two existing
decisions' scope.

## Platform twin

Everything the platform reads from the package, by exact name:

| What | Where |
|---|---|
| The tab's framing line | `entity_candidate.opening_question(name, entity_type) -> str` |
| The stage | `entity_candidate.entity_stage_for_session(session) -> "establish" \| "settled"` |
| The duplicate list to substitute | `entity_candidate.possible_duplicates(entity_type, name, roster) -> list[str]` (join with `", "`, or the literal `"none"` when empty) |
| Whether the offer is allowed | `entity_candidate.is_offer_worthy(entity_type, roster_entry) -> bool` |
| Closed validation of the turn's field | `entity_candidate.validate_entity_setup(value, *, roster_slugs) -> dict \| None` |
| The lints | `entity_candidate.lint_entity_setup_reply(text, *, stage, user_signaled=False, offered_before=False) -> list[dict]` |
| The prompt leaf to REPLAY verbatim | `interactions/entity_candidate/prompt/turn-instructions.md`, via `interaction_registry.compose_interaction_asset("entity_candidate", "prompt/turn-instructions.md")`, substituting `{entity_stage}`, `{entity_name}`, `{entity_type}`, `{possible_duplicates}` |
| Structural parse of the turn output | `conversation_delivery.parse_turn_output(raw)["entity_setup"]`, enabled by `TurnShape(entity_stage=…)` |
| Closed vocabularies | `entity_roster.ENTITY_TYPES`, `focus_candidate.FOCUS_RELATIONSHIPS`, `entity_candidate.ENTITY_SETUP_KEYS`, `entity_candidate.VALID_ENTITY_STAGES` |
| Graduation + identity in ONE call | `entity-verdict <type> <slug> graduate\|never\|clear [--alias A]... [--relationship R] [--living\|--not-living] [--maps-to SLUG] [--json]` |
| … enqueued | `jobs.py` command `entity-verdict`, payload `{type, slug, verdict, aliases?, relationship?, living?, maps_to?}` |
| The focus hand-off seam (the ONLY one) | `focus-recommend-from-entity <type> <slug> [--json]`; `jobs.py` command `focus-recommend-from-entity`, payload `{type, slug}`; pure helper `recommend_focuses.recommendation_for_entity(roster_entry, *, now=None) -> dict` |
| The offer-worthy type list | `recommend_focuses.FOCUS_RECOMMENDATION_TYPES` |

The platform's `:identity` job precedence (review-loop/57 §A) is entirely
platform-side: newest non-null `Turn.entity_setup` wins per key. The package
neither knows nor cares which turn it came from.

## Acceptance checklist

- [ ] Exactly one new turn-output field exists (`entity_setup`); no new
      session field, lifecycle status, model purpose, or state machine.
- [ ] `_output_contract_block` is byte-identical when `entity_stage` is None.
- [ ] A malformed or absent `entity_setup` never errors a turn.
- [ ] The aside appears on the first reply, is one sentence, is not a
      question, and never appears again — goldens 1, 5, 7.
- [ ] At most one identity question, the duplicate question outranks the
      relationship one, and none when the answer already said — goldens 1, 2, 3.
- [ ] The offer appears at most once and only for offer-worthy types —
      goldens 4 and 7.
- [ ] A user-signaled change emits `entity_setup`; nothing else ever does —
      goldens 6 and 5.
- [ ] `entity-verdict` applies graduation + aliases + relationship + living +
      maps_to in ONE idempotent call; `--maps-to` wins over `graduate`.
- [ ] Nothing in this PR creates a focus; `focus-recommend-from-entity`
      appends one pending row and nothing else.
- [ ] `entity-candidate-evals`, `focus-candidate-evals` and
      `question-candidate-evals` all pass.
- [ ] CI green (`test` on 3.11/3.14, `framework-manifest`, `version-bump`);
      handbook embed parity green.
- [ ] `system/version.json` at 190 with the two new goldens in
      `framework_files`.
- [ ] ADR 0022 amended per the table; ADR 0018 gains the third-instance row;
      the child README's "Play is read-only" corrected.

## Owner closeout

**Look.** The transcript the goldens replay (no provider required):

- *Screen 1*: `Tell me about Ada — who are they to you?` and nothing else.
- *Turn 1*: they answer about the mill → the reply receives it, then: "I've
  added **Ada** as a person in your story — tell me if that's the wrong name or
  the wrong person." Then one question — "Is she your mother, or someone you
  think of that way?" — or, if the roster already holds an "Ada Whitfield",
  "Is this the same Ada as the page you already have?" instead. And, once,
  "If she's someone you want to build out, say so and I'll start a focus."
- *Turn 2*: an ordinary exchange. Nothing about who she is.
- *Turn 3*: "she goes by Jo too, and yes, start a focus" → a one-clause
  receipt, no confirmation question. Field: `{"aliases": ["Jo"],
  "start_focus": true}`.
- Then `entity-verdict person ada graduate --alias Jo --relationship parent
  --not-living` and `focus-recommend-from-entity person ada` — one roster
  commit and one pending recommendation row, and no focus anywhere.

**Judge.**

1. **The aside wording.** "I've added **{name}** as a {type} in your story —
   tell me if that's the wrong name or the wrong person." Yes = this exact
   sentence ships as the prompt's literal instruction and the lints pin its
   shape.
2. **The duplicate question outranks the relationship question.** Yes = when
   the roster shows a likely same-page, that is the one thing asked, and the
   relationship waits for another day.
3. **`--maps-to` beats `graduate` silently rather than failing the call.**
   Yes = a background job that carries both applies the merge, skips the
   graduation, and reports it — instead of erroring and stranding the identity.
4. **`focus-recommend-from-entity` as the only hand-off.** Yes = a yes to the
   offer writes one pending recommendation row and the platform's existing
   focus mechanics take it from there; the package never creates a focus.

**Done when.** Implementation PR green on CI → v190 tagged on merge →
platform review-loop/57 pins v190 and consumes the names in the Platform twin
table.

🤖 Generated with Claude Opus via Claude Code
