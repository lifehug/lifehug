# Contract: arc-planner (issue #118)

Conversation Interaction, Wave 2 PR5 (design §4, §11; owner-ratified
2026-08-11). The daily Chat's ~3 exchanges become a coherent, pre-planned
mini-arc: the WEEKLY loop plans one **arc card** per queued question —
an opening framing plus 2–4 follow-up *intents* (not scripted text) —
and the daily loop merely ATTACHES the card. This is the owner-ratified
deviation from decision C: the daily loop is deliberately AI-free on both
mediums (OSS convention "daily = free"; the platform's delivery-selection
sandbox is keyless by construction), so arc GENERATION lives in the weekly
loop and daily stays attach-only. Related issues: #98, #99, #103.

## Why

Today's three chained daily questions are unrelated to each other — the
owner's named pain ("feels weird"). The planner queue already decides WHAT
to ask this week; nothing plans HOW an exchange around each question should
unfold. Meanwhile three verified gap seams sit unclaimed: (1)
`timeline.compute_gaps()` emits typed gaps that are display-only — no
question-generation consumer exists anywhere; (2) unfilled five-slot scene
probes are counted (book.py) but never planned against at exchange level;
(3) research neighborhoods are output-oriented arcs with no conversation
entry point. The arc planner claims all three and gives the (separately
contracted) turn engine a skeleton to execute live.

## Binding facts

Facts verified against origin/main at c30be1d (v149). Re-verify at
implementation time; sibling Wave-1/2 PRs may land first (see "Sequencing").

- **Version**: main is v149; bump `system/version.json` to the next
  unclaimed version at implementation time (check main then — wave siblings
  are claiming numbers in parallel).
- **Weekly seam**: `system/weekly_maintenance.sh` — the planner-queue step
  is `run_learning_step "planner_queue" python3 "$SCRIPT_DIR/lifehug.py"
  planner-queue --limit "$QUEUE_LIMIT" --arc-max "$ARC_MAX" --expires-days
  "$EXPIRES_DAYS"` (line ~273). The new arcs step goes DIRECTLY AFTER it
  (and after the `QUEUE_OUT` capture), so cards are planned against the
  queue that was just written. The script's existing idioms are binding:
  `run_learning_step` wrapping (failures recorded via
  `record_learning_failure`, never kill the flow), the `KEYLESS` variable
  (already computed at line ~180 via `lifehug.py ai-status`), the
  `$AGENT_TASKS_DIR` emit convention, the dry-run block (lines ~155–170)
  gaining a matching preview step, and the report-section table gaining an
  `Arc cards:ARCS_OUT` row.
- **Queue shape** (`state/question_queue.json`, written by
  `question_planner.build_queue`): items carry `question_id`, `category`,
  `group`, `focus`, `source`, `source_type`, `story_function`, `objective`,
  `status` ("queued"→"sent" via `ask.mark_queue_item_sent`), `reason`;
  top-level `generated_at`, `expires_at` (default 8 days,
  `future_timestamp(expires_days)`).
- **Daily seam**: `system/daily_question.sh` builds the Telegram TEXT at
  lines ~252–256 (`TEXT="📖 Lifehug — Daily Question\n\n${QUESTION_OUTPUT}\n\n
  (Answer whenever you want — voice or text)"`) after parsing QUESTION_ID
  from `ask.py --dry-run` output. `ask.py` picks via
  `pick_next_question` (reengagement pre-empts the queue at line ~104;
  planned queue head at ~109; rotation fallback below). The daily path must
  stay AI-FREE — attach is a pure file read.
- **Timeline gaps**: `timeline.compute_gaps(periods, entity_lineup,
  event_lineup, unplaced_entities, unplaced_events)` (system/timeline.py:581)
  returns `[{kind, period, message, hint?}]` with kinds `no_chrono`,
  `no_events`, `all_undated`, `thin_lineup`, `unplaced_events`,
  `unplaced_entities`. `timeline.timeline_data()` (line 619) assembles the
  inputs and calls it — the arc planner consumes gaps through that assembled
  payload (or by replicating its exact load sequence), it does NOT
  re-derive gap logic. This PR is the FIRST non-display consumer. Gap kinds
  consumed for intents: `no_events`, `all_undated`, `unplaced_events`.
  Phrasing rule (research.md §4, hard): landmark anchors, NEVER "what
  year" — the gap hints already model this.
- **Five-slot probes**: classifier stamps `scene_slots` per source
  (classify_story.py schema); slot names are `book.FIVE_SLOTS =
  ("what_happened", "when_and_where", "who_was_there", "thought_and_felt",
  "what_it_says_about_me")` — NAMES MUST MATCH (the book.py header warns a
  mismatch reads as permanently-empty slots; contract test precedent
  tests/test_v75_book.py). Read via the same pattern as
  `book._load_scene_slots()` (classifications keyed by
  `source_path` "answers/<QID>.md"). "What it says about you" is the
  highest-value follow-up when empty (research.md §1).
- **Neighborhood siblings**: `state/question_candidates.json` candidates
  carry `neighborhood_id`, `status` (promotable statuses per
  question_candidates.py), `story_function`, `text`.
  `state/neighborhoods.json` (research_expand.py / neighborhoods.py):
  neighborhoods have `id`, `title`, `type`, `target_output`, `arc` slots
  (story_function + question_id + status), and derived readiness via
  `neighborhoods.apply_readiness` (`readiness_status`, `ready_to_draft`,
  `answered_completeness`).
- **Studio format slots**: `format_readiness.compute_readiness(framework,
  categories, format_readiness.load_bank_questions())` computes per-slot
  coverage for `templates/<format>.json` frameworks (slots keyed to story
  functions, same verdict vocabulary as book.py); `book.gap_question_ids()`
  already feeds the planner's chapter boost.
- **Sit-with tensions**: the Mirror's "## Sit with" section lives in the
  compiled page at `mirror.mirror_page_path()` (wiki/self/mirror.md),
  exactly 3 bullets by contract (`mirror.REQUIRED_SECTIONS`,
  `validate_mirror_body`). Self-arc questions are those whose queue
  `story_function` ∈ `question_planner.SELF_FUNCTIONS = ("self_image",
  "value", "fear", "contradiction", "perception_by_others", "growth_edge")`.
- **Two-sentence rule** (research.md §1, hard): opening framing = ONE
  context sentence quoting/referencing the author's own record + the
  question. Never paraphrase the author's account back with altered
  details — quote exactly (reconsolidation rule). A cold-start coverage
  question may still prove memory in framing ("You've told me about X;
  this is somewhere we haven't been yet —") without faking continuity.
- **AI provider**: `ai_provider.call_ai(prompt: str, model: str) -> str`
  (fail-closed; raises `AIUnavailableError` in agent-task mode). Model
  resolution for this surface: config `arc_plan_model` → config
  `classify_model` → `classify_story.DEFAULT_MODEL` ("claude-sonnet-5").
  Document the new key in `config.yaml.example` next to `classify_model`.
- **Keyless emit pattern**: mirror.py `emit_task` / classify-story
  `--emit-prompts` — write prompt file(s) + `manifest.json` with an
  `ingest_command` naming the `--from-response` completion path, under
  `$AGENT_TASKS_DIR/arcs`.
- **Vault contract**: new durable state file ⇒ entry in
  `system/vault_contract.json` `data_paths` + resolvable via
  `vault_paths.py data-path <name>` and included in `git-paths` (tracked).
  As of drafting there is NO `arc_cards` entry. The Wave-1 conversation ADR
  (interaction pattern + vault-contract additions) may have landed first —
  if the entry already exists on main, do not duplicate it; this PR's ADR
  duty is then only to reference it.
- **Engagement profile hook** (cross-contract, #119): PR6 adds an
  `engagement` block to `state/quality_profile.json`. The arc planner reads
  it GUARDED (`load_profile().get("engagement")`, absent → no-op) for
  arc-topic/opener-framing bias only. Do not block on PR6; do not invent
  the block's schema here beyond "by_story_function/by_category buckets with
  a clamped `multiplier`" (PR6's contract owns it).
- **Parity (BINDING, platform merge-blocker)**: the weekly shell step IS
  the parity SPEC. The platform transports it verbatim as
  `StepSpec("arcs", "arc_plan", llm=True)` + `LlmPurpose "arc_plan"`; any
  cap, limit, gate, or fallback the platform needs MUST appear in the OSS
  shell step / CLI first — a platform-side gate not present here is a
  parity merge-blocker on the platform PR. Write the shell step (env-var
  knobs, exit behavior, keyless branch) knowing it will be read as spec.

## Scope

**In:**
1. `state/arc_cards.json` — the arc-card store, schema below, registered in
   `system/vault_contract.json` (tracked) so weekly/daily autocommit and
   the platform selection layer can carry it.
2. `system/arc_planner.py` — pure planning module (no Telegram, no direct
   provider import at module scope): card store read/write, deterministic
   intent derivation, AI prompt builder, response validation/ingest, expiry
   logic. CLI via new `lifehug.py` subcommands (repo pattern:
   `cmd_arc_plan` thin wrapper):
   - `lifehug.py arc-plan [--limit N] [--dry-run] [--emit-tasks DIR]
     [--from-response PATH] [--model M]`
   - `lifehug.py arc-card <QUESTION_ID> [--daily-text]` — pure read; with
     `--daily-text` prints the assembled daily message text when a live
     (unexpired, current-queue) card with an opening exists, else prints
     nothing and exits 0 (the shell attach hinges on empty-vs-nonempty).
3. Weekly step in `weekly_maintenance.sh` (after planner_queue; keyed +
   keyless branches; dry-run preview; report section; summary counts).
4. Daily attach in `daily_question.sh` + `ask.py` (AI-free, read-only).
5. Monthly conversation-thread offers + resurfacing/perennial copy shift in
   `monthly_research.sh` (details below).
6. ADR (docs/adr/) for the arc-card contract IF the Wave-1 ADR hasn't
   already ratified the vault-contract addition — otherwise extend/reference.
7. Tests + dry-run walkthrough evidence.

**Out** (explicitly deferred / owned elsewhere):
- Executing intents live (turn engine — Wave-2 PR3) and session documents
  (Wave-1 PR2). This PR produces DATA the turn engine consumes; if PR3 has
  not merged yet, cards simply improve the daily message text and wait.
- Router, deflection, story→conversation (PR4).
- Engagement profile computation (PR6, issue #119).
- Platform transport step + `_SELECTION_DATA_KEYS`/SELECTION_VAULT_PATHS
  additions (platform Wave-3 PR10; parity note above binds its shape).
- Reengagement redesign: reengagement (silent ≥4 days) PRE-EMPTS the queue
  exactly as today; its question has no planned card by design (minimal arc
  is synthesized at session-open by PR3, not here).

## The arc-card schema (binding)

`state/arc_cards.json`:

```json
{
  "version": 1,
  "generated_at": "2026-08-16T09:00:00Z",
  "queue_generated_at": "<question_queue.json generated_at verbatim>",
  "expires_at": "<question_queue.json expires_at verbatim>",
  "source": "model | deterministic | mixed",
  "cards": [
    {
      "question_id": "A14",
      "opening": "one context sentence from the record + the question, or null",
      "opening_receipts": ["A7", "sources/manual/2026-03-01-ghana.md"],
      "intents": [
        {"kind": "scene_slot", "slot": "who_was_there", "note": "…"},
        {"kind": "neighborhood_sibling", "candidate_id": "…", "neighborhood_id": "…", "note": "…"},
        {"kind": "timeline_gap", "gap_kind": "unplaced_events", "period": "denver-years", "note": "landmark-anchor phrasing"},
        {"kind": "studio_slot", "format": "letter", "slot": "…", "note": "…"},
        {"kind": "sit_with", "text": "<the Sit-with line, quoted>"},
        {"kind": "demonstrated_knowledge_summary", "receipts": ["A7", "A22"], "note": "…"}
      ],
      "planned_at": "…",
      "planner": "model | deterministic"
    }
  ]
}
```

Rules:
- Exactly the six intent `kind` values above — this is the shared
  vocabulary the turn engine, evals, and the platform inherit; adding a
  kind later is a schema bump.
- 2–4 intents per card (design §1). Deterministic fallback may emit fewer
  (minimum 1) but never zero cards for a queued question.
- `opening` is nullable: null ⇒ daily uses today's message format
  unchanged. When present it must satisfy the two-sentence rule and cite
  `opening_receipts` (answer ids / source paths actually on record —
  validation rejects openings whose receipts don't resolve; session honesty
  rule: never fabricate memory).
- No intent note, opening, or any card text may contain the phrase "what
  year" (case-insensitive) — a validation lint, mirroring research.md §4.
- Expiry: cards live and die WITH the queue (`expires_at` copied verbatim).
  A card is "live" only if unexpired AND its `question_id` appears in the
  current queue (status queued or sent). `arc-card` returns nothing for
  dead cards. Stale-plan fallback is therefore automatic: when the queue
  expires, `ask.py` already falls back to the rotation pick, no card
  attaches, and the (future) session opens with a minimal arc — chats keep
  working with a stale plan, degraded not broken.
- Idempotent regeneration: re-running arc-plan for the same queue
  (`queue_generated_at` match) replaces the file wholesale; a model-planned
  card is not clobbered by a later deterministic re-run in the same week
  unless `--force` (keyless completion via `--from-response` UPGRADES
  deterministic cards in place, `planner` flips to "model").

## Implementation notes (seams, not diffs)

- **Deterministic fallback** (always computed first; the model pass, when
  available, replaces/enriches): for each queued item —
  scene_slot intents from unfilled `FIVE_SLOTS` of the answered material in
  the item's category (empty-classification ⇒ all five unfilled ⇒ prefer
  `what_it_says_about_me` + one concrete slot); neighborhood_sibling
  intents from same-`neighborhood_id` candidates (promotable statuses)
  when the queued question or its category maps into a neighborhood arc;
  timeline_gap intent when a consumed-kind gap touches the item's
  category/focus era or global `unplaced_events` exist (cap: at most one
  timeline_gap intent per card, at most `LIFEHUG_WEEKLY_ARC_GAP_MAX`
  (default 3) across the week's cards — the timeline whispers, per the
  wiki-harvest precedent); sit_with intent ONLY for self-arc items
  (`SELF_FUNCTIONS`), quoting one current Sit-with line; studio_slot from
  the focus's format framework's unfilled slots (guarded import, silent
  no-op when unavailable — the book/chapter-boost precedent);
  demonstrated_knowledge_summary only when the item's category has ≥2
  answered questions (gradual introduction, phase-3 A: small summaries
  before dossiers), receipts = up to 3 real answer ids. Deterministic
  openings: permitted without a model ONLY as verbatim-quote framings
  ("You wrote: \"…\" — " + question) built from an on-record answer in the
  same category; otherwise null.
- **Model pass**: one prompt per run (not per card — bounded cost, weekly
  cadence) carrying the queue, the deterministic intent material, mission
  excerpt, and the craft rules (two-sentence rule, landmark anchors, no
  "what year", quote-exactly); response = strict JSON matching the card
  schema; `validate_cards()` rejects schema/lint violations and falls back
  to the deterministic cards (never a broken file, never a lost week).
  Keyed weekly branch mirrors the classify branch; keyless branch writes
  deterministic cards AND emits the prompt + manifest to
  `$AGENT_TASKS_DIR/arcs` (`ingest_command: lifehug.py arc-plan
  --from-response <path>`), reported with the "⏸ keyless — task emitted,
  not a failure" convention.
- **Daily attach**: in `daily_question.sh`, after QUESTION_ID is parsed,
  `ARC_TEXT=$(python3 "$SCRIPT_DIR/lifehug.py" arc-card "$QUESTION_ID"
  --daily-text || true)`; non-empty ⇒ TEXT uses it (still prefixed
  "📖 Lifehug — Daily Question" and suffixed with the answer-hint line);
  empty ⇒ today's TEXT unchanged. `--daily-text` composes: opening framing
  (which embeds or is followed by the question text) — it must include the
  `[QID]` marker exactly as `format_question` does, because
  daily_question.sh's ID parse and the answer-filing flow key on it.
  Dry-run daily (`LIFEHUG_DAILY_DRY_RUN=1`) prints the would-be attach.
- **Monthly** (`monthly_research.sh`):
  1. Conversation-thread offers: a new deterministic step marks
     neighborhoods "conversation-ready" (derived, computed like
     `apply_readiness`: status active/draft with unanswered arc slots and
     ≥1 answered or promoted slot — i.e., there is somewhere to go AND
     record to open from) and writes at most
     `LIFEHUG_MONTHLY_THREAD_OFFERS` (default 1) offer line(s) into the
     monthly Telegram summary ("I've been wanting to ask about the Ghana
     years — shall we?" register), recording offered neighborhood ids in
     `state/arc_cards.json` under a top-level `thread_offers` list
     (`{neighborhood_id, offered_at, month}`) so offers never repeat within
     a quarter (the second-voice never-repeat precedent, scoped lighter).
  2. Perennial/echo copy shift: the existing resurfacing message (lines
     ~350–391) and perennial re-asks keep their mechanisms (last year's
     answer attached — already built) but their closing line becomes a
     conversation opener ("Reply and we'll talk it through — it saves as a
     reflection on <id>") — copy-only change, reply handling stays whatever
     is live (ingest path today; sessions once PR3/PR4 land).
- **Where quality/engagement bias applies**: arc-topic choice among
  OPTIONAL intents (siblings, studio slots) may be ordered by
  `quality_profile` multipliers (guarded, and engagement per the
  cross-contract note). Never drops scene_slot/timeline_gap/sit_with
  intents — behavioral signals tune pacing/framing, never whether hard
  questions get asked (owner: drain is not negative).
- **Convergence property (owner-set) — acceptance criteria**: on a
  synthetic fixture vault containing each gap type, assert the named
  consumer fires:
  - timeline `unplaced_events` / `all_undated` ⇒ ≥1 `timeline_gap` intent
    exists across the week's cards, phrased without "what year";
  - unfilled five-slot scenes ⇒ `scene_slot` intents naming exact
    `FIVE_SLOTS` members;
  - a self-arc queued item + a Mirror page with Sit-with bullets ⇒
    `sit_with` intent quoting one;
  - a neighborhood with pending siblings ⇒ `neighborhood_sibling` intent;
  - an unfilled format-framework slot for the item's focus ⇒ `studio_slot`
    intent (or documented silent no-op when framework absent);
  - a category with ≥2 answers ⇒ `demonstrated_knowledge_summary` with
    resolvable receipts.
  Downstream halves of the loop (answers → classification →
  timeline-retire; mirror responses → weekly edition) are owned by existing
  mechanisms and PR6 — this PR's convergence duty ends at "every detectable
  gap type emits a conversation input."

## Test plan

New file `tests/test_arc_planner.py` (unittest, repo standard; synthetic
fixture vault via the tempdirs/tempdir conventions — NEVER
~/Workspace/dave). Named subtests:

- `test_deterministic_cards_for_every_queued_item` (cards ≥ queue length
  match, ≥1 intent each, 2–4 cap respected when material allows)
- `test_intent_vocabulary_closed` (unknown kind rejected by validator)
- `test_scene_slot_names_match_book_five_slots` (parity with
  `book.FIVE_SLOTS` — the v75 contract-test pattern)
- `test_timeline_gap_consumer_fires_and_never_says_what_year`
- `test_sit_with_only_for_self_arc_items`
- `test_demonstrated_knowledge_requires_two_answers_and_real_receipts`
- `test_opening_receipts_must_resolve` (fabricated receipt ⇒ opening
  rejected ⇒ null opening, card survives)
- `test_expiry_follows_queue_and_dead_cards_never_attach`
- `test_daily_text_contains_qid_marker_and_is_empty_without_live_card`
- `test_from_response_upgrades_deterministic_cards`
- `test_model_failure_falls_back_to_deterministic` (call_ai raising ⇒
  cards still written, learning failure recorded)
- `test_thread_offers_never_repeat_within_quarter`
- convergence-property subtests per the acceptance list above

Prove with: `python3 -m unittest tests.test_arc_planner -v` and the full
`python3 -m unittest discover -s tests -p "test_*.py"` (CI runs 3.11 + 3.14;
no new dependencies — the repo is deliberately dependency-free).

## Launch-and-verify

No `serve_wiki.py` surface is touched, so no Playwright walkthrough is
required (BUILDING.md §4). The runnable evidence is the three dry-runs, to
be pasted into a PR comment:

```
LIFEHUG_WEEKLY_DRY_RUN=1  bash system/weekly_maintenance.sh   # shows the arc-plan preview step after planner-report
LIFEHUG_DAILY_DRY_RUN=1   bash system/daily_question.sh       # shows the would-be attach (or its absence) for today's pick
LIFEHUG_MONTHLY_DRY_RUN=1 bash system/monthly_research.sh     # shows the thread-offer preview
python3 system/lifehug.py arc-plan --dry-run                  # prints planned cards, writes nothing
python3 system/lifehug.py arc-card <QID> --daily-text         # prints the attach text for a live card
```

Pass = the weekly dry run previews one card per queued question with typed
intents; the daily dry run shows the opening-framing message for a carded
question and today's unchanged format otherwise; nothing in any preview
contains "what year"; no state file is written by any dry run.

## Definition of done

- [ ] Code + tests pass locally (`python3 -m unittest discover -s tests`)
- [ ] `system/version.json` bumped (version, released, changelog sized to
      user impact; `framework_files` gains `system/arc_planner.py`)
- [ ] `system/vault_contract.json` gains `arc_cards` (or references the
      Wave-1 entry if already landed) and `config.yaml.example` documents
      `arc_plan_model`
- [ ] AGENTS.md/CLAUDE.md updated where described behavior changed (daily
      message composition, weekly steps)
- [ ] ADR written/extended for the arc-card contract (coordinates with the
      Wave-1 conversation ADR — one findable answer, not two)
- [ ] Parity note honored: the shell step readable as the platform spec;
      twin transport tracked on lifehug-platform (Wave-3 PR10) — file or
      link the twin issue in the same session per AGENTS.md Cross-Medium
      Parity
- [ ] Issue #118 commented with verification results; dry-run evidence
      embedded in a PR comment
- [ ] No reference to ~/Workspace/dave anywhere in code or tests (hard
      boundary)
