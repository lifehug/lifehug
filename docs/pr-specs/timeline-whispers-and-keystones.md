# Contract: timeline-whispers-and-keystones

> Owner rulings: lifehug/lifehug-platform#586 (2026-08-23 design session,
> comment "Owner rulings"). They supersede that issue body's option-B-only
> design and this repo's v195 `leverage_boost` adjacency nudge.
> Decision: ADR 0024 (amended by this PR). Version: 195 → 196.

## Why

v195 gave the timeline dates, unknowns, leverage and keystones — and no way
for the person to ever be **asked**. `timeline.keystones()` computes "one
answer would place 23 moments"; the arc-card `timeline_gap` intent reaches
the turn model as the bare token `timeline_gap` (`conversation._intent_label`
returns the kind string; `period`/`note` are written to
`state/arc_cards.json` and read by nothing at prompt time); `parse_turn_output`
parses `placed` and **every caller drops it**; nothing ever sets
`TurnShape.timeline_stage`, so the `placed` key is never even in the output
contract; and `place_invocation` / `lifehug.py timeline-place` have no caller.

Meanwhile `leverage_boost` (1.2) lifted BANK questions whose focus or category
merely *matched a keystone slug* — adjacency, not identity. That is the direct
cause of platform #586: the Today ★ appeared on "What do you think your kids
have taught you…", a question that never asks for a date.

This PR makes the ask real in two places and deletes the side-state:

* **Whispers** — the week's arc card carries the real probe and the person's
  own anchors; the conversation raises it only where it fits, at most once,
  accepts any precision, never presses, never opens with a year.
* **Keystone questions** — a keystone that clears one knob is **minted as a
  real bank question** in a `timeline` group and competes for a slot in the
  ordinary queue. Asked = answered = never re-asked, by the existing bank
  mechanism.
* **Any `placed` output files through `timeline-place`**; the next compile
  re-derives and the Timeline adjusts on its own.
* **The deferral machine is deleted.** "I'll find out" is an ordinary answer.
* **The loop learns about arcs** the way it learns about questions.

## Rulings (owner-set)

**2026-08-23, design session** (lifehug/lifehug-platform#586, comment "Owner
rulings"): 1. keep the queue simple and tunable — no preference management, no
frequency counters, no deferral state. 2. **whispers** carry the real probe and
the anchors; raised only where they fit, ≤1 per conversation, any precision
accepted, never pressed, never "what year", and never penalized. 3. **keystones
in the queue** are minted as real bank questions in a `timeline` group (existing
group cap 1), scored by leverage through ONE knob. 4. "I'll find out" is just
the answer; delete `timeline_deferred.json`. 5. any `placed` files through
`timeline-place` and the next compile re-derives. 6. the loop learns about arcs
like it learns about questions. 7. the host's ★ means "a keystone is waiting in
this conversation" or "today's question is a keystone".

**2026-08-23, staging — "Unknowns are concrete"** (owner-set, same issue). The
owner opened `/timeline` and found an Unknown row reading *"UNPLACED EVENTS —
116 moment(s) I can't place in any period"* whose probe was *"Tell me what
happened — just the moment itself, however it comes."* Playing it opened a
conversation asking exactly that. Owner: *"I have no idea what that means or
what we're talking about. My expectation would be that the question is about
some time period that can help place 116 events. **I need a question.**"*
Binding consequences:

1. `timeline.unknowns()` **never emits an aggregate row.** Every unknown is ONE
   concrete subject with a human label: a specific undated moment (its title),
   a specific era's missing bounds, a specific place's span, a dated hole
   between two named bands, a specific contradiction. The aggregate kinds
   (`unplaced_events`, `no_chrono`, `no_events`, `all_undated`, `thin_lineup`,
   `unplaced_entities`) become COUNTS on `unknown_ledger`, never questions.
2. `choose_probe` produces a question that **names the subject** and uses the
   person's own anchors. The bare "tell me what happened" probe survives for
   exactly one case: a single moment with no anchors at all.
3. `keystones()` rows carry a **real question about the anchor**
   (`keystone_probe`) — "Childhood — one answer would place 23 more things" is
   not something a person can answer.
4. Unknowns are **capped per page** (leverage-ordered, `UNKNOWNS_PAGE_CAP` 30)
   with the ledger carrying the totals.
5. A golden per unknown kind's probe, bare and anchored.

**2026-08-23, nomenclature** (owner-set). *"I really like the whisper
nomenclature… a whisper is information woven into a conversation that fits
naturally from an arc that's developed and solves some other agenda."*
**Whisper** is therefore a GENERAL term — information woven into a
conversation that fits naturally, drawn from a developed arc, serving a second
agenda beyond the conversation's primary one — and the **timeline whisper** is
its first kind, not its definition. Recorded in `docs/handbook/glossary.md`
(the OSS glossary of record; the platform's `docs/GLOSSARY.md` is its twin),
the README's Nomenclature section, `interactions/README.md` (§ Whispers, with
the three rules every whisper inherits: only where it fits, at most one per
conversation, never penalized) and the handbook's the-loop page.

**2026-08-23, the timeline vocabulary is a NAMED SET** (owner-set).
**Landmarks** (the universal dating questions everyone gets — birth,
residences, schooling, partnerships, children, jobs; the skeleton that makes
everything placeable by arithmetic; `system/research/landmarks.md` is the
authority for the set, written in parallel and NOT created here),
**keystone** (the single highest-leverage unknown for this person right now,
from the dependency graph; starred, and it may become the day's question when
its value clears the bar) and **whisper** live together in the nomenclature,
with one line on how they relate: *landmarks are the universal skeleton;
keystones are the per-person gaps that skeleton leaves; whispers and keystone
questions are the two ways the loop asks.* Recorded as a `Timeline` section in
the README's Nomenclature, in `docs/handbook/glossary.md` (with
cross-references from the flat list) and in the handbook's timeline page.

## Binding facts

1. `placed` is a date record with a basis. **Ranges are first-class**: "about
   preschool, three to five" files as an interval (`granularity: "range"`,
   `earliest`/`latest`, `basis: "age"`), and an interval is a finding, not a
   failure (`system/research/chronology.md` §1). There is no `{"deferred":
   true}` any more — it leaves `_parse_placed`, `validate_placed`,
   `DEFERRED_PLACED`, the output contract and the goldens.
2. The `defer` playbook rung and the `timeline_gates.accepts_defer` lint
   **stay**: "I'll find out" still has to be received gracefully and never
   pressed. What goes is the state that remembered it.
3. `KEYSTONE_CAP = 2` and the group cap (1 timeline question per week) are the
   only volume controls. No frequency counters, no preference management, no
   quiet windows.
4. `question-bank.md` categories are single letters under an optional group
   section header; `category_group` passes through `main|project|focus` and
   otherwise falls back to letter ranges. `timeline` becomes the fourth group,
   recognized from a `## Timeline` section header exactly as `## Focus` and
   `## Project` are today.
5. A minted keystone question is an ordinary bank row (`- [ ] T1: …`) with a
   provenance comment. Everything downstream — coverage, rotation, sends,
   answer filing, "never re-asked" — is the existing mechanism, untouched.
6. The unknown that a keystone anchors **persists on the Timeline** after the
   question is answered; the placement is what removes it, via the next
   compile. Asking is not resolving.

## Scope

### 1. Reply routing (shared by whispers and keystone questions)

* `run_post_answer_turn` derives a timeline item for this turn from ONE
  definition, `timeline_interaction.timeline_item_for_session(session,
  question_id=…)`: the session's arc-card timeline intent, or the day's
  question when it is a minted keystone (`timeline_probe_index`).
* When an item exists the engine sets
  `shape.timeline_stage = timeline_stage_for_session(session,
  no_new_bound_streak=…)`, which is the only thing that puts the `placed` key
  in the output contract (`_output_contract_block`, byte-identical when the
  stage is `None` — existing test).
* The reply's `placed` goes through both layers (`_parse_placed` →
  `validate_placed(anchors=item["anchors"])`), is stored on the appended
  `lifehug_turn` as `placed` (which `precision_so_far` already expects to
  find), and is filed by running
  `place_invocation(placed, source=…, description=…, period=…)` →
  `lifehug.py timeline-place`. Filing failures are swallowed relative to the
  delivered message, like every other post-send step.
* A turn that raised a whisper is stamped `timeline_probe_id` on the same
  appended turn — session-document data, not a new state file. It is what
  makes "at most one per conversation" checkable.

### 2. Whispers

* `timeline.keystones()` rows gain `question_id: "tl:<anchor-slug>"` (slug
  sanitized: lowercase, `/` and whitespace → `-`), `unknown_keys[]` (the
  pre-existing `resolves` list, named for what it is) and `anchors` (the
  person's own landmarks, for `validate_placed`'s closed check).
* `arc_planner.collect_timeline_gaps` keeps its consumed-kind filter and gains
  a leverage per gap plus the vault's keystone rows;
  `_timeline_gap_intent` ranks **by leverage, era-affinity as the tiebreak**
  and emits
  `{kind: "timeline_gap", anchor, question_id, probe, anchors[],
    unknown_keys[], leverage, gap_kind, period, note}`.
  Caps are unchanged (≤1 per card, `DEFAULT_GAP_MAX` = 3 per week).
* Prompt rendering: `conversation._intent_label` and
  `_assemble_session_block` render the probe and the anchors for a timeline
  item; every other intent kind renders **byte-for-byte as today** (golden).
  `{arc_card_current_intent}` renders the same probe when the timeline item
  leads the card.
* `interactions/conversation/prompt/turn-instructions.md` gains the direction:
  raise it only where it fits, at most one per conversation, accept any
  precision (a range places things), never press, never open with a year.
* New lint `timeline_gates.one_per_conversation`, caller-informed
  (`timeline_asks_so_far`, the same shape as `no_new_bound_streak`).
* The lane's first goldens: **whisper-fits-and-files**,
  **whisper-does-not-fit-not-raised**, **whisper-partial-range**.

### 3. Keystones in the queue

* Pure minting in `timeline_interaction`: `keystone_question_id(anchor)`,
  `category_from_anchor(anchor)`, `mint_keystone_question(keystone, *,
  next_question_id, category_from_anchor=…)` → a bank row, and
  `insert_keystone_question(bank_text, row)` → new bank text (creates the
  `## Timeline` section on first use). The id comes from the bank's own
  allocator (`question_candidates.next_question_id`).
* ONE knob, `timeline_leverage_per_story` (default **6**), in
  `DEFAULT_LANE_POLICY`. It converts leverage into the queue's objective
  currency: `boost = leverage / timeline_leverage_per_story`, applied in
  `weighted_pick` exactly where `objective_boost` (2.5) is applied. The same
  number is the mint cutoff: **no mint below `leverage >= per_story`**, so a
  minted question is by construction worth at least one ordinary story answer.
  Reasoning for 6, conservative: the week is ~8 questions and the objective
  boost is 2.5, so a keystone reaches the strongest lane in the queue only at
  15 unknowns, ties an ordinary question at 6, and never appears at all below
  that; with `KEYSTONE_CAP` 2 and a group cap of 1 a vault can carry at most
  one timeline question per week no matter how leveraged its anchors are.
* Minting happens **at `planner-queue` time only** (`question_planner.main
  --write-queue` / `lifehug.py planner-queue`), guarded — a timeline failure
  must never break the weekly queue — and never re-mints a live keystone that
  already has an unanswered bank row.
* `GROUP_CAPS["timeline"] = 0.01` → `max_counts` yields exactly 1 for any
  weekly limit.
* **Deleted:** `leverage_boost`, `keystone_slugs`, `current_keystone_slugs`,
  the `question["keystone"]` adjacency mark and the
  `allocation.leverage.matched` block that advertised it. Adjacency is what
  starred a question that never asks for a date (#586).
* Byte-identity golden: with no keystone clearing the cutoff, `build_queue`'s
  output and the daily send are byte-identical to v195.

### 4. Delete the deferral machine

`state/timeline_deferred.json`, `timeline.DEFERRED_FILE`,
`DEFERRED_QUIET_DAYS`, `load_deferred`, `defer_unknown`, `is_deferred`, the
`deferred` field on unknowns and on `build_timeline_plan`,
`lifehug_core.TIMELINE_DEFERRED_FILE`, the `timeline_deferred`
`VAULT_ROOT_NAMES`/`vault_contract.json` entry, the `wiki_compile` and
`connectors/base` root wiring, and every handbook/glossary/README mention. A
remnant guard test fails the build if any of those names comes back.

### 5. Arc learning

`question_judgment` gains an **arc-yield pass** on the same weekly step, the
same ADR 0009 mechanism (cursor / no-op / compaction, one bounded
evidence-cited amendment per run):

* `arc_yield()` reads **existing vault data only** — `state/conversations/`
  session documents. For every intent kind on a session's arc card it counts
  the sessions that carried it, the filed answers (`answers/<qid>.md` for the
  session's own question ids), the placements (turns with `placed`) and the
  new entities (`extracted.entities`). A session with three intents attributes
  to all three (co-attribution, stated in the block).
* The amendment lands in `state/question_judgment/arc_learned.md` and is
  composed into `arc_planner.build_plan_prompt` as an
  `## Arc judgment signals` block, immediately after the verbatim
  `plan/arc-templates.md` — **not** written into that framework file:
  framework files are overwritten by `update.py` on every upgrade and pinned
  by `test_exact_file_git.py`, so an in-place amendment would be erased and
  would break the integrity gate. (Deviation from the ruling's letter, in
  service of its intent — the same composition split `load_judgment_rubric`
  already uses for the question rubric.)

### 6. Unknowns are concrete

* `UNKNOWN_KINDS` becomes `("moment", "period_bound", "place_span",
  "era_gap", "date_contradiction")`; `LEDGER_GAP_KINDS` holds the six
  aggregates `compute_gaps` still emits for the page's gap notes.
* `unknowns(data)` builds one row per subject (undated moments in a period,
  unplaced moments, undated eras, undated places, era gaps, contradictions);
  `unknown_ledger(data)` carries the counts; `offered_unknowns(rows, index,
  limit=UNKNOWNS_PAGE_CAP)` orders by leverage then probe cost and caps.
  `timeline_data()["unknowns"]` is the capped, ordered list;
  `counts.unknowns` stays the true total.
* `dependency_index` now indexes the concrete keys on both sides, so leverage
  counts real answerable things.
* `KIND_OPENERS` gives every non-moment kind its own opening question, bare
  and anchored; `PROBE_TEXTS` names `{label}` on every rung; `content` is
  skipped the moment an anchor exists. `keystone_probe(anchor_key, label=,
  anchors=)` is the star's own question, by anchor kind.

### 7. Docs

ADR 0024 amendment; `docs/handbook/glossary.md` (whisper, keystone, keystone
question); `docs/handbook/the-loop.md`; `docs/handbook/timeline.md`;
`interactions/README.md`; `interactions/timeline/README.md`; README.md module
table; `system/version.json` → 196; the Platform-twin table below.

## Platform twin (lifehug/lifehug-platform#586)

| Package name | Kind | Host action |
| --- | --- | --- |
| `timeline.load_deferred`, `defer_unknown`, `is_deferred`, `DEFERRED_FILE`, `DEFERRED_QUIET_DAYS` | **deleted** | delete `reflect/package_read.py`'s `timeline_deferred` bundle, `reflect/models.py:deferred`, `derive.py`'s deferred read, `actions.py`'s defer action |
| `state/timeline_deferred.json`, `vault_contract` `timeline_deferred` | **deleted** | drop `TIMELINE_DATA_KEYS` in `projected_file_texts.py` |
| the host-side defer action (`reflect/actions.py` calls `defer_unknown`) | **no package function to call** | delete the action and its UI |
| `unknowns()[…]["deferred"]`, `build_timeline_plan()["deferred"]` | **deleted fields** | drop from the projection + Review lane |
| `UNKNOWN_KINDS` (now `moment · period_bound · place_span · era_gap · date_contradiction`), `LEDGER_GAP_KINDS`, `unknown_ledger()`, `offered_unknowns()`, `UNKNOWNS_PAGE_CAP` | **changed vocabulary + new readers** | the Unknowns lane renders subjects and shows the ledger's counts as counts; drop any `unplaced_events`-style row |
| `keystone_probe()`; `keystones()[…]["probe"]` | **new / now a real question** | render the ★ row's probe as the question it is |
| `keystones()[…]["question_id"]` (`tl:<slug>`), `["unknown_keys"]`, `["anchors"]` | **new fields** | the ★ matches by exact `question_id`; `anchors` feed `validate_placed` |
| `question_planner.DEFAULT_LANE_POLICY["leverage_boost"]`, `keystone_slugs()`, `current_keystone_slugs()`, `allocation.leverage.matched`, `question["keystone"]` | **deleted** | stop passing `keystone_slugs=`; stop reading `allocation.leverage.matched` |
| `DEFAULT_LANE_POLICY["timeline_leverage_per_story"]` (6), `GROUP_CAPS["timeline"]` | **new knobs** | mirror in the hosted planner policy |
| `timeline_interaction.mint_keystone_question`, `insert_keystone_question`, `keystone_question_id`, `category_from_anchor`, `timeline_probe_index` | **new pure helpers** | REPLAY at hosted `planner-queue` time |
| bank tag `<!-- timeline_probe: tl:<slug>; … -->`, group `timeline`, category `T` | **new bank shape** | "today's question is a keystone" ★ = `timeline_probe_index` hit |
| `timeline_interaction.timeline_item_for_session`, `answer_timeline_probe`, `is_timeline_probe` | **new pure helpers** | REPLAY on the hosted turn path |
| `TurnShape.timeline_stage` set on the answer path; `turn["placed"]`, `turn["timeline_probe_id"]` | **new turn fields** | additive-with-default in the projected envelope |
| `timeline_gates.one_per_conversation` | **new lint class** | mirror in the hosted lint config |
| `{"deferred": true}` in `placed` | **removed from the contract** | reject it host-side too |

## Test plan

* `tests/test_timeline_unknowns.py` — deferral tests deleted; keystone identity
  fields; the minting helpers; the cutoff.
* `tests/test_timeline_interaction.py` — `validate_placed` rejects
  `{"deferred": true}`; range-with-basis survives; `one_per_conversation`.
* `tests/test_arc_planner.py` — leverage-ranked whispers with era tiebreak;
  the enriched intent payload; the two existing gap tests updated.
* `tests/test_conversation_delivery.py` — the answer path sets the stage,
  stores `placed`, and calls `timeline-place`; nothing changes without an item.
* **Goldens**: three whisper fixtures; a probe golden per unknown kind (bare
  and anchored) and per keystone anchor kind; the byte-identity queue golden;
  the intent-label byte-identity golden; the arc-yield amendment golden.
* `tests/test_timeline_whispers.py::DeferralRemnantTests` — the remnant guard.
* Gates: full suite, `make timeline-evals`, all interaction evals, handbook
  parity, `make ci`.

## Launch-and-verify

1. `python3 system/lifehug.py planner-queue --write-queue` on a synthetic vault
   with a 6+-leverage anchor → a `## Timeline` section and a `- [ ] T1:` row
   appear in the bank; the queue carries it; a second run does not re-mint.
2. `python3 system/timeline_interaction.py --json` → keystones carry
   `question_id`, `unknown_keys`, `anchors`; no `deferred` anywhere.
3. `python3 system/timeline_evals.py --json` → six gate classes pass,
   including `one_per_conversation`, over 13 goldens.
4. `python3 system/question_judgment.py --dry-run` → the delta carries the
   arc-yield table.

## Definition of done

Every scope item lands with its tests; the full suite, every eval, handbook
parity and CI are green; `version.json` reads 196; the twin table above is on
the platform issue.
