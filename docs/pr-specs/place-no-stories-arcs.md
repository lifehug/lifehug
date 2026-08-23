# Contract: place-no-stories-arcs

## Why

v199 (landmarks, PR #204) produced the gap only a landmark set can reveal:
`timeline.timeline_data()["place_no_stories"]` — a residence with a known span
and **no moments attached**. It deliberately left CONSUMPTION as a follow-up,
so today the rows are computed, displayed on the Timeline, and asked about by
nobody.

The owner's ruling (lifehug/lifehug-platform#590, and the #581 comments) is
that this is not a display curiosity — it is *new information the system could
not see without the landmark*, and therefore a gap the loop should ask about:

> "I lived in Costa Mesa" but nothing in the vault happened there is itself a
> gap the loop should ask about.

A place the person named is the strongest possible invitation: they already
told us it mattered enough to name, and we have nothing from it. This PR makes
the weekly arc planner consume those rows exactly the way v196 made it consume
timeline gaps — as an arc-card intent riding into an ordinary conversation,
never as a nag, never as a queue entry.

## Binding facts

State as of `60b5f9a` (v199), the commit this contract ships against.

- **The rows already exist.** `landmarks_interaction.places_without_stories(
  landmarks, event_places=())` returns unknown-shaped rows
  `{kind, key, label, witnesses, probe}` where `kind ==
  landmarks_interaction.PLACE_NO_STORIES_KIND == "place_no_stories"` and `key`
  is `place_no_stories:<residences-slug>`. `timeline.timeline_data()` exposes
  them at `data["place_no_stories"]`, guarded (a landmark problem degrades to
  `[]`, never an exception — `tests/test_landmarks.py::TimelineStaysUpTests`).
- **A row exists only for a DATED residence.** An undated residence is v196's
  `place_span` unknown — the dating gap — and this kind never competes with
  it. `places_without_stories` already enforces this
  (`if _entry_date(entry) is None: continue`).
- **`place_no_stories` is NOT a `timeline.UNKNOWN_KINDS` / `LEDGER_GAP_KINDS`
  member** and must not become one (pinned by
  `test_the_kind_does_not_collide_with_the_existing_unknown_kinds`). It is a
  STORY gap; the unknown ledger counts DATING unknowns.
- **The intent vocabulary is closed and this is a schema bump.**
  `conversation.ARC_INTENT_KINDS` (`system/conversation.py:833`) is the single
  definition; ADR 0002's arc-card amendment says adding a kind is a schema
  bump, not an additive change. It goes from six kinds to **seven**. The
  surfaces that state the number are: `system/conversation.py:830` (the
  comment), `docs/adr/0002-interaction-pattern.md:98`,
  `docs/handbook/interactions/conversation.md:53`, and
  `interactions/conversation/plan/arc-templates.md` (the model-read definition
  file). The platform inherits the vocabulary at pin-bump time — this is a
  flagged closed-vocabulary reconciliation surface, same as issue #168's five
  new property ids.
- **The gap budget is one number.** `arc_planner.DEFAULT_GAP_MAX = 3`
  (`system/arc_planner.py:100`) caps timeline whispers across the week, and the
  per-card rule is at most one. This PR does NOT add a second budget: a
  `place_no_stories` intent is counted within the SAME `DEFAULT_GAP_MAX`, and
  the per-card gap slot stays at one — `timeline_gap` is ranked first and
  `place_no_stories` fills the slot only on a card that got no whisper. Two
  question-carrying intents on one card would compete for the same turn.
- **The rendering precedent is v196's whisper.** `timeline_interaction.
  render_whisper` is the ONE rendering of a timeline item;
  `conversation.timeline_whisper` / `render_timeline_whisper` put it in the
  prompt (`_assemble_session_block`, `_current_intent_label`). The whisper gate
  requires a non-empty `probe`, which is exactly why a bare
  `{"kind": "timeline_gap"}` still renders as the plain label — the byte-
  identity test `test_every_other_intent_kind_renders_byte_for_byte_as_v195`
  iterates `ARC_INTENT_KINDS - {"timeline_gap"}` and must keep passing with
  the seventh kind in the set. The new rendering therefore uses the same
  probe-present gate.
- **Never propose a date** (`timeline_interaction.proposes_a_date`, the ONE
  definition shared by the timeline and landmarks lanes, go-deep.md §4.3 /
  Lindsay et al. 2004) applies here too: the rendered line may REPORT the span
  the person gave us ("you lived there around 1990–1993"), and may never name
  a date and invite agreement.
- **`arc_planner.BANNED_PHRASE = "what year"`** is unchanged and the new probe
  never contains it (it asks WHAT, not WHEN).
- **The arc-yield pass is already kind-agnostic.**
  `question_judgment.arc_yield()` (`system/question_judgment.py:339`) walks the
  kinds each session's arc card actually carries — `place_no_stories` is scored
  like every other kind with **no new state and no code change**; this PR pins
  that with a test rather than adding a branch.
- Lands as **v200**.

## Scope

**In**

1. `landmarks_interaction.places_without_stories` gains three ADDITIVE fields
   per row — `span` (the person's own span, rendered), `landmark` (the
   residence landmark ref the row came from) and `anchor` (the same key
   `anchors_from_landmarks` mints for that residence, so a host can join the
   two without re-deriving the slug). Existing fields and existing tests are
   untouched.
2. `landmarks_interaction.render_place_no_stories(item)` — the ONE rendering
   of a place-with-no-stories intent, the sibling of
   `timeline_interaction.render_whisper`.
3. `conversation.ARC_INTENT_KINDS` gains `place_no_stories` (seven kinds), and
   `conversation.place_no_stories_aside(session)` /
   `render_place_no_stories_aside(intent)` put the rendered line in the prompt
   — a `Place with no stories:` line in the session block, and the
   `{arc_card_current_intent}` slot when there is no unraised timeline whisper.
4. `arc_planner.collect_places_without_stories(payload=...)` +
   `_place_no_stories_intent(item, material, used)`, wired into
   `plan_deterministic`'s HARD intents directly after `_timeline_gap_intent`,
   sharing its budget and its one-slot-per-card rule; and a
   `PLACES WITH NO STORIES` block in `build_plan_prompt`, emitted only when
   there is at least one row.
5. One new golden property id, `place_no_stories_asked_openly`, and one
   committed golden that exercises it.
6. Docs: the handbook's The Loop and Timeline pages, the glossary line under
   Landmarks, ADR 0002's amendment, `arc-templates.md`, and
   `docs/handbook/interactions/conversation.md`.

**Out**

- **No new state.** No ledger, no "asked already" marker, no side file. A
  place stops being a gap when a moment lands in it, which is the same
  recomputation `timeline_data()` already does on every read.
- **No bank question.** `place_no_stories` never mints a bank row the way a
  keystone does. It is an arc-card intent only — a whisper-shaped ask, not a
  queue entry (the owner's landmark ruling: an open landmark is a resting
  state, not a debt).
- **No new budget dial.** It rides `DEFAULT_GAP_MAX`.
- **Ranking beyond the residence chain's own order is out.** Rows are offered
  in the person's own chronology (the order the residences are filed in),
  first unused first. A leverage number for story gaps would be an invented
  score — v196's `leverage` counts what a DATE would place, and this kind
  places nothing.

## Implementation notes

- `system/landmarks_interaction.py:755–800` — `places_without_stories` already
  computes `_entry_date(entry)`; render it with
  `chronology.display_date(record, with_basis=False)` for `span`. The row's
  `anchor` is `_anchor_key("residences", label, position)` with the SAME
  `enumerate(..., start=1)` the function already uses, so it matches
  `anchors_from_landmarks`.
- `render_place_no_stories` mirrors `timeline_interaction.render_whisper`:
  degrade to the bare kind name when there is no probe, name the place and the
  span, phrase the ask as "if it fits", and append the witnesses when the
  residence ladder's `household` rung supplied any.
- `system/conversation.py:850–905` — `place_no_stories_aside` is the whisper's
  sibling but has NO "already raised" counter to consult (there is no side
  state to count off, by design); the structural once-per-card cap is the
  planner's. Order in `_current_intent_label` is whisper first, then the aside.
- `system/arc_planner.py:786–795` — `_place_no_stories_intent` reads `used`
  (`gaps`, `gap_max`, and a new `place_keys` set for week-scope dedupe), and
  returns `[]` when the card already took a whisper this call.
  `plan_deterministic` builds `hard` in one expression; the new call goes last
  in it.
- `build_plan_prompt` appends its block only when the material list is
  non-empty, so a vault with no such places produces a byte-identical prompt.

## Test plan

New file `tests/test_place_no_stories_arcs.py`, covering:

- `RowShapeTests` — `span`, `landmark`, `anchor` present and correct; `anchor`
  equals the key `anchors_from_landmarks` mints for the same residence; an
  undated residence still yields nothing.
- `RenderingTests` — the rendered line names the place and the span, carries
  the witnesses when there are any, never trips
  `timeline_interaction.proposes_a_date`, never contains
  `arc_planner.BANNED_PHRASE`, and degrades to `"place_no_stories"` without a
  probe.
- `PromptTests` — the aside renders in `_assemble_session_block` and wins
  `{arc_card_current_intent}`; an unraised timeline whisper still wins over it;
  a bare `{"kind": "place_no_stories"}` intent renders byte-identically to
  every other kind (the v196 golden still passes with seven kinds).
- `PlannerTests` — a card gets at most one; a card that took a whisper takes
  no aside; the shared `DEFAULT_GAP_MAX` caps both kinds together; the same
  place is never offered twice in one week.
- `ByteIdentityTests` — **the golden this contract requires**: with no such
  places, `plan_deterministic` and `build_plan_prompt` are byte-identical to
  material that has no `places_without_stories` key at all (i.e. v199).
- `ArcYieldTests` — `question_judgment.arc_yield()` scores the new kind exactly
  like the others, with no new state.
- `VocabularyTests` — the kind is in `ARC_INTENT_KINDS`, the vocabulary has
  seven members, and `arc_walk.intent_note` accepts a card whose first intent
  is the new kind.

Existing files touched: `tests/test_landmarks.py` (row-shape assertions stay
green untouched — the fields are additive), and
`tests/test_interaction_evals.py` gains coverage of the new property id via the
committed golden (Layer 3 requires every `PROPERTY_IDS` member to be exercised
by at least one golden).

Golden: `interactions/conversation/evals/goldens/chat-costa-mesa-place-no-stories.json`.

    python3 -m unittest discover -s tests -p "test_*.py"
    python3 -m unittest tests.test_place_no_stories_arcs -v

## Launch-and-verify

Not required — this PR does not touch `serve_wiki.py`'s visible surface. The
planner path is provable from the CLI:

    python3 system/lifehug.py arc-plan --dry-run

## Definition of done

- [ ] Code + tests pass locally (`python3 -m unittest discover -s tests`)
- [ ] `system/version.json` bumped to 200 (version, released, changelog,
      framework_files for the new test + golden)
- [ ] ADR 0002's arc-card amendment updated (six → seven kinds), since the
      closed vocabulary is a decision future work must honor
- [ ] Handbook: The Loop, Timeline, the conversation interaction page, and the
      glossary line under Landmarks
- [ ] Covering issue (lifehug/lifehug-platform#590) commented with the result
