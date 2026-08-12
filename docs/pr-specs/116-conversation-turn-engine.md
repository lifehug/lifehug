# Contract: conversation-turn-engine (issue #116)

Wave 2, PR 3 of the Conversation Interaction build (owner-approved design,
2026-08-11). This contract is self-contained: everything the implementer
needs is in this file plus the repo at the commit this contract ships on.
Serves issues #98 (the Conversation primitive) and #99 (owner's words:
"follow-ups must read as conversation").

## Why

The post-answer moment is Lifehug's most important surface, and today it is
two disconnected messages: a warm acknowledgment that is contractually
forbidden from asking anything ("No questions back" —
`system/answer_ack.py:79`), followed by an adaptive follow-up question picked
by rotation that is usually UNRELATED to what the user just said ("📖 Lifehug
— since you're on a roll"). The owner's stated pain: today's chained
questions don't relate like a real conversation. `system/research.md` §2e
already names the fix: "The fix is conversation, not cadence — immediate
acknowledgment + one listening follow-up."

This PR makes the post-answer pipeline run a **conversation turn**: one
message that receives the answer, pays it out, and cues the next question —
a short, coherent Chat (~3 exchanges) with a graceful exit and a closing
takeaway — while degrading to today's exact behavior on any failure.

## Dependencies (Wave 1) and the merged-code-wins rule

This PR builds on the two Wave-1 PRs (the `interactions/` scaffold and the
session store + builders). Their contracts were drafted in the same session
as this one; issue numbers were not yet assigned when this contract was
written. **The interfaces below are what this PR was planned against (design
§5/§6). If the merged Wave-1 code differs in names or shapes, the merged
code wins — re-verify these at implementation start and follow the merged
interfaces; the behavior pinned in this contract is unchanged either way.**

Expected from Wave 1:

1. `interactions/conversation/` definition files (Wave-1 PR 1):
   - `interaction.yaml` — lifecycle knobs this engine must read (not
     hardcode): chat idle timeout (default ~2h), conversation idle timeout
     (default ~30min), chat exchange target (default 3), max message length,
     deposit-framing on/off.
   - `prompt/identity.md`, `prompt/behavior.md`, `prompt/examples.md`,
     `prompt/turn-instructions.md` — consumed via the Wave-1 builders, never
     read ad hoc.
   - `evals/lints.yaml` — the deterministic lint definitions; the runtime
     lints in this PR must be the same checks (single source, imported or
     loaded from this file — do not fork the list into code constants that
     can drift).
2. `system/conversation.py` (Wave-1 PR 2) — pure, no provider calls:
   - Session store CRUD over `state/conversations/<session_id>.json`
     (vault-contract-registered by Wave 1), including a compare-and-set
     field for single-flight turn minting.
   - `build_turn_prompt(...)` — per-turn prompt assembly per
     `interactions/conversation/context/manifest.md` (stable blocks first,
     turn instructions last).
   - `build_closing_prompt(...)` — the closing-takeaway prompt.
   - Session document schema (the shape this PR reads/writes):

```json
{"session_id":"…","mode":"chat|conversation","channel":"telegram|web|cli",
 "interaction_version":"1.0.0","status":"open|idle|closed",
 "arc":{"question_id":"A14","opening":"…","intents":["scene_sensory","who_else","meaning"]},
 "turns":[{"role":"user|lifehug","text":"…","ts":"…","model":"provider/model",
           "question_id":"A14"}],
 "rolling_summary":"…",
 "extracted":{"facts":[],"entities":[],"candidate_ideas":[],"mirror_responses":[]},
 "close":{"reason":"done|idle_timeout|exit_taken","takeaway":"…",
          "takeaway_delivered":true,"insight_receipts_count":0,"filed":["A14","A14b"]}}
```

## Binding facts (verified against the repo at this contract's commit)

- `system/process_answer.py`:
  - `run_post_answer_delivery(*, source_id, question_id, question_text,
    question_category, answer_text)` (line ~409) — plans the adaptive
    follow-up, calls `answer_ack_delivery.acknowledge_answer(...)`
    (swallowing all failures), then `maybe_send_followup_question(...)`.
    This is the function this PR rewires.
  - `finalize_answer_delivery(...)` (line ~470) — the durability boundary:
    commit → post-answer delivery → chapter offer → bookkeeping commit.
    Its ordering guarantee (durable answer FIRST, conversational effects
    second, all conversational failures swallowed) is inherited unchanged.
  - `plan_adaptive_followup(answered_question_id)` — returns the planned
    bank question or None (respects `adaptive_cadence` config, the 20:00
    curfew, `awaiting_pass_transition`, and `ask.sends_today(rotation) >=
    ask.max_sends_per_day()`).
  - `maybe_send_followup_question(answered_question_id, planned_question)` —
    sends `FOLLOWUP_HEADER` / question / `FOLLOWUP_FOOTER` and calls
    `ask.mark_question_sent(rotation, id)` + `rebuild_coverage()`.
  - `next_followup_id(md_text, source_id)` / `append_followups(question_id,
    followups)` — the ONLY way to mint follow-up questions (suffix chain
    A14 → A14b; appends to `system/question-bank.md`).
- `system/answer_ack_delivery.py` — the pattern this PR generalizes:
  - `acknowledge_answer(*, source_id, question_id, question_text,
    question_category, answer_text, followup_pending, state_path=...,
    allow_ambiguous_retry=False, prompt_builder=..., ai_call=None,
    status_resolver=None, telegram_send=None) -> AcknowledgmentOutcome`.
  - Ledger `state/answer_acknowledgments.json`; statuses
    `confirmed/skipped/failed/ambiguous`; `ambiguous` is written with reason
    `send_in_progress` BEFORE the Telegram call (crash-safe replay
    position); confirmed replays return `already_confirmed` with no second
    model call or send; ambiguous is never auto-retried
    (`allow_ambiguous_retry` requires operator confirmation).
  - `_valid_completion`: rejects non-string, empty, >`ACK_MAX_CHARS` (1200),
    NUL bytes, leading ``` `{` `[`, and prompt-echo markers.
  - `DEFAULT_ACK_MODEL = "claude-sonnet-5"`; model key `answer_ack_model`.
  - Injectable collaborators for tests (`ai_call`, `telegram_send`,
    `status_resolver`, `prompt_builder`, `state_path`) — this PR's engine
    MUST expose the same injectability (precedent:
    `tests/test_v121_answer_ack_delivery.py`).
- `system/ai_provider.py`: `call_ai(prompt, model)`, `provider_status(model,
  probe=False) -> ProviderStatus(provider, model, ready, detail)`, error
  family `AIProviderError` / `AIConfigurationError` / `AIUnavailableError` /
  `AIResponseError`; keyless mode surfaces as provider `agent-task`,
  not-ready.
- `system/lifehug_core.py`: `send_telegram_result(text) ->
  TelegramSendResult` (statuses `confirmed` / `ambiguous` / `not_attempted`
  / rejection), `load_config()`, `record_learning_failure(...)` (metadata
  only — never answer/prompt/generated text), `STATE_DIR`, `read_json` /
  `write_json`.
- `system/lifehug.py`: command classification sets at lines ~60–88 —
  `QUEUED_MUTATION_COMMANDS` / `READ_ONLY_COMMANDS` /
  `DIRECT_MUTATION_COMMANDS`. Every new subcommand must be classified in
  exactly one.
- `system/jobs.py::COMMANDS` — NOT touched by this PR (the
  `conversation-close` job kind and batching-default change are Wave-2
  PR 6).
- `system/quality_profile.py::append_score(...)` — appends per-answer
  records to `state/answer_scores.json` (vault-contract key
  `answer_scores`, tracked; `unknown_fields: allow` family). Engagement
  fields are ADDED to these records; precedent for non-richness signals
  living there already exists (insight/negative/i_rate).
- `system/vault_contract.json` `data_paths`: Wave 1 registers
  `conversations` (`state/conversations`, directory, tracked). THIS PR
  registers `conversation_deliveries`
  (`state/conversation_deliveries.json`, file, tracked, json, version 1) —
  and mirrors it in `system/vault_paths.py` git-paths, same as
  `answer_scores`.
- Config keys today: `answer_ack_model` (default `claude-sonnet-5`),
  `classify_model`, `followup_model`, `adaptive_cadence` — documented in
  `config.yaml.example`.
- Version/CI: every PR bumps `system/version.json` (version, released,
  changelog, `framework_files` for new distributable files) — no exemption.
  origin/main is at version 149 as this contract is written; Wave-1 and
  sibling Wave-2 PRs land in owner-decided order, so pick the next free
  number at implementation time, not now. CI is `python3 -m unittest
  discover -s tests -p "test_*.py"` on Python 3.11 + 3.14, dependency-free
  — no pip installs, stdlib only. This repo has NO ruff/pytest tooling;
  do not introduce any.

## New config keys (this PR)

Documented in `config.yaml.example`, read via `load_config()`:

- `conversation_model` — the seated turn/closing model. Default
  `"claude-sonnet-5"` (sonnet-class, same default constant style as
  `DEFAULT_ACK_MODEL`).
- `router_model` — the cheap intent router. Default `"claude-haiku-4-5"`
  (haiku-class). Defined here so the key set ships once; its consumer is
  Wave-2 PR 4 (`lifehug.py route`).
- `arc_plan_model` — weekly arc planning; resolution order
  `arc_plan_model` → `classify_model` → `classify_story.DEFAULT_MODEL`
  (`"claude-sonnet-5"`) as the terminal fallback (matching #118). Defined
  here; consumer is Wave-2 PR 5.

## The behavior this engine enforces (pasted; the implementer does not
re-derive this from the design docs)

The seated model's full behavior contract lives in
`interactions/conversation/prompt/behavior.md` (Wave 1) and reaches the
model through the Wave-1 prompt builders. What THIS module owns is the
**turn-shape decisions and the deterministic enforcement**:

1. **One message per turn.** Receipt + payout + cued follow-up are ONE
   Telegram message, never two or three.
2. **Turn anatomy** (chat exchanges 1–2, substantive answer): receipt that
   quotes the user's own words exactly (never paraphrased facts) → register
   (celebration/savoring for good news, cognitive-empathy for hard stories)
   → at most ONE contribution the user didn't have → cued follow-up
   invitation quoting the user's phrase. At most one question per message.
3. **Question-free turns are legal and planned**: when the turn instructions
   say to receive without asking (heavy register, user declined the last
   door), the message ends after the receipt/contribution with no question.
4. **Third exchange is exit-friendly**: phrased so stopping is graceful
   ("that's a good place to rest" energy). The ~3-exchange target governs
   OUR initiative only — if the user keeps going, keep receiving; never
   hard-stop a continuing user.
5. **Closing takeaway** (session close, when warranted): takeaway (not
   recap — composes the user's words, never rewrites), specific
   appreciation, continuity line, optional deposit-frame (knob from
   `interaction.yaml`), named hook for next time — then STOP, no trailing
   question.
6. **No-nag rule** (owner-confirmed): zero-turn sessions and chats
   abandoned mid-exchange close SILENTLY at idle timeout — whatever was
   answered is already durably filed per-turn; no closing message, no
   "you didn't finish", nothing.
7. **Zero pressure, ever**: no guilt, streaks, length evaluation, repeated
   asks of a declined question. A skip is signal: file it, move on warmly.

**Runtime lints** (deterministic, enforced in `conversation_delivery` on
every generated message BEFORE send; definitions sourced from
`interactions/conversation/evals/lints.yaml`, not forked into code):

- ≤ 1 question mark's worth of questions per message (one-question lint).
- Length ≤ the turn-length cap sourced from the shared lint config
  `evals/lints.yaml` key `cap.turn_chars` (value 1200, matching
  `ACK_MAX_CHARS`) — read from that one file; this module does NOT pin an
  independent 1200 constant.
- Banned-phrase list (from lints.yaml; includes at minimum: "that must have
  been", guilt/streak phrasing, "as an AI" / AI self-reference,
  "you haven't told me much").
- Structural sanity, same class as `_valid_completion`: non-empty string, no
  NUL, no leading ``` `{` `[`, no prompt-echo markers.

A lint failure is treated exactly like `malformed_generation`: ledger
`failed`, then the fallback path below. Never send a message that fails a
lint; never retry generation in a loop (one attempt, like the ack).

## The turn engine (`system/conversation_delivery.py`)

Orchestration only — prompts come from `conversation.py` builders, provider
calls via `ai_provider.call_ai`, sends via `lifehug_core`
`send_telegram_result`. Ledger and diagnostics carry METADATA ONLY (source
ids, session ids, fixed reason codes, timestamps, attempt counts — never
answer, prompt, or generated text), exactly like `answer_ack_delivery`.

Entry point (called from `run_post_answer_delivery` in place of the
ack-then-followup pair):

```
run_post_answer_turn(*, source_id, question_id, question_text,
                     question_category, answer_text,
                     planned_question,  # from plan_adaptive_followup, may be None
                     state_path=..., ai_call=None, telegram_send=None,
                     status_resolver=None) -> TurnOutcome
```

Flow:

1. **Sweep**: lazily close idle-expired sessions (see Lifecycle) before
   anything else.
2. **Session**: find the open chat session whose pending question chain
   contains `question_id` (root or suffix-chain member); if none, OPEN one
   now — a chat session opens at first answer, not at delivery. Record the
   user turn (`role: "user"`) in the session document. Arc card lookup by
   `question_id`: in this PR arc cards do not exist yet — the engine MUST
   run **arc-card-absent minimal behavior** (below) whenever
   `session["arc"]` is missing/empty, which in this PR is always.
3. **Single-flight**: mint the lifehug turn via the store's compare-and-set
   before generation; a concurrent second entry for the same session mints
   exactly one turn (the loser returns `skipped/turn_already_minted`).
4. **Readiness**: `provider_status(conversation_model, probe=False)`; not
   ready → ledger `skipped` (`no_unattended_provider` for agent-task, else
   `provider_unavailable`) → FALLBACK path.
5. **Decide turn shape** from the session (exchange count, register signals
   in the turn instructions) per the behavior rules above:
   - exchanges 1–2 → receipt+payout+cued follow-up (or question-free when
     instructed);
   - exchange 3 → exit-friendly phrasing;
   - past the target with the user still going → keep receiving
     (receipt+payout, question optional, never hard-stop).
6. **Follow-up identity** (what the cued question IS, arc-card-absent):
   - The cued follow-up is a SPONTANEOUS follow-up about this answer,
     minted through `append_followups(question_id, [text])` /
     `next_followup_id` (files as the A14 → A14b suffix chain — durable,
     lineage-preserving, bank-visible). The model proposes the follow-up
     text inside its structured turn output; the engine mints the id and
     records it as the session's pending question.
   - After a CONFIRMED send of a turn carrying a cued follow-up, update
     rotation exactly as `ask.mark_question_sent(rotation, new_id)` does
     (so `rotation.last_question_id` targets the follow-up and the host
     agent files the next inbound against it) and call
     `rebuild_coverage()` — cadence accounting (`sends_today`) still
     counts this send; the 3/day cap keeps governing our initiative.
   - `planned_question` (the bank/rotation pick) is NOT sent mid-session;
     it stays for tomorrow. It exists in the signature because the
     FALLBACK path needs it.
   - Turn-shape gating: if `plan_adaptive_followup` returned None because
     of the curfew/cap/pass-transition gates, the turn is question-free
     (our initiative is spent) — the gates transfer, not disappear.
7. **Generate**: `build_turn_prompt(...)` → `ai_call(prompt,
   conversation_model)`. The turn output is structured (message text +
   proposed follow-up text + question-free flag + extracted
   facts/entities/candidate_ideas deltas); the exact JSON shape is pinned
   by the Wave-1 builder contract — merged code wins.
8. **Lint** (above). Failure → ledger `failed/malformed_generation` →
   FALLBACK.
9. **Send**: persist ledger `ambiguous/send_in_progress` BEFORE the
   external effect, then `send_telegram_result(message)`; map results
   exactly as the ack does (`confirmed`/`ambiguous`/`not_attempted`→
   `skipped`/else `failed`). Record the lifehug turn in the session
   document only on `confirmed`.
10. **Ledger**: `state/conversation_deliveries.json`, same file shape as
    the ack ledger (`{"version":1,"entries":{...}}`), entries keyed
    `turn:{session_id}:{turn_index}` with fields `session_id`,
    `turn_index`, `question_id`, `status`, `reason`, `attempts`,
    `updated_at` (+`confirmed_at` / `operator_action` like the ack).
    Exactly-once semantics copied verbatim: confirmed replays are no-ops;
    ambiguous is NEVER auto-retried and requires operator confirmation to
    retry.

**FALLBACK (design §12 risk 1 — non-negotiable):** on ledger outcomes
`skipped` (provider not ready) or `failed` (provider error, malformed/lint
failure, definitive send rejection), the pipeline degrades to TODAY'S
behavior in the same invocation: `acknowledge_answer(...)` with
`followup_pending=planned_question is not None`, then
`maybe_send_followup_question(question_id, planned_question)`. Never
silence, never worse than today. **Exception:** an `ambiguous` turn send
does NOT trigger the fallback ack (the turn may have reached Telegram; a
fallback would risk a duplicate voice) — ledger it, surface it via status,
stop. All failures remain swallowed relative to answer durability, exactly
as `run_post_answer_delivery` swallows ack failures today.

## Lifecycle, close, engagement capture

- **Idle timeouts** (knobs from `interaction.yaml`; defaults chat ~2h,
  conversation ~30min) count from the last turn. The arc card waiting with
  a delivered question burns nothing — the session doesn't exist until the
  first answer.
- **Close triggers**: (a) turn-cap-reached + next answer never arrives →
  idle timeout; (b) idle timeout generally; (c) exit taken (in this PR,
  detectable only as silence after the exit-friendly third exchange —
  router-based explicit exits arrive with PR 4). Closes run in the lazy
  sweep (step 1 above) and via the CLI below. No daemon, no cron change in
  this PR.
- **Close behavior**: the closing-takeaway criterion is the deterministic
  cross-runtime rule (platform #414 confirms the same rule): a template/
  model close message is sent only when the session has **≥2 user turns**;
  zero-turn or single-answer chats close SILENTLY (no nag), regardless of
  whether an exchange target was nominally reached. Sessions meeting the
  ≥2-user-turns bar get the closing takeaway message — generated via
  `build_closing_prompt` +
  `conversation_model`, linted, sent and ledgered exactly like a turn
  (entry key `close:{session_id}`). Sessions below the ≥2-user-turns bar
  (zero-turn or abandoned-mid-chat) close SILENTLY (no-nag rule). Either
  way the close block is written: `reason`, `takeaway` (empty if silent),
  `takeaway_delivered`,
  `insight_receipts_count` (count of receipt-citing insight contributions
  delivered this session, taken from the structured turn outputs),
  `filed` (question ids answered in-session).
- **Partial chats are normal and file cleanly** (owner-confirmed): answers
  are durable per-turn through `process-answer` as today; a timeout close
  files whatever was answered; next day starts a fresh chat; nothing nags.
- **Engagement capture at close** (decision-D cause instrumentation): for
  each question id in `close.filed`, append to its existing
  `state/answer_scores.json` record an `engagement` object using #119's
  AUTHORITATIVE field names for the shared fields:
  `{"session_id", "session_turns", "continuation_past_exit": bool,
  "turn_length_trajectory": "expanding|flat|contracting", "close_reason"}`
  (NOT `continued_past_exit`/`turn_length_trend` — #119 defines the
  canonical names for the fields shared across producers; `session_id`,
  `session_turns`, and `close_reason` are extra fields this PR contributes
  freely). Leave room for #119's `time_to_answer_hours` and
  `unprompted_inbound` fields, which are computed elsewhere and are not
  this PR's responsibility to populate. Never overwrite richness fields.
  Named consumers (doctrine): the arc planner (Wave-2 PR 5, arc-topic/
  opener choice) and `compute_profile()`'s engagement dimension (Wave-2
  PR 6). Recorded now so the nourishment dashboard can be built any time
  from recorded data.
- **Extracted-field filing at close** (consumers named per doctrine):
  `extracted.candidate_ideas` → candidate store via the
  `question_candidates` append path with `"provenance": "conversation"`;
  `extracted.entities` → filed as classification hints for the weekly
  classify pass (write into the session close block AND the agent-tasks
  hint surface the weekly pass already reads — follow the Wave-1 store
  contract's filing helpers if it provides them). `extracted.facts` are
  in-session only (rolling-summary re-assertion — the 39%-degradation
  mitigation) and are NOT filed anywhere at close.
  `extracted.mirror_responses` are RECORDED in the session document but
  their consumer (`state/mirror_responses.json` + mirror inbound) is
  Wave-2 PR 6 — do not build it here.
- **Wiki/commit batching is NOT this PR**: in-session `process-answer`
  keeps today's compile/commit behavior; the one-commit-per-close collapse
  and the `conversation-close` job kind are Wave-2 PR 6.

## CLI additions (`system/lifehug.py`)

- `conversation-status [session_id]` — metadata-only session + delivery
  ledger status (mirrors `answer-ack-status`). Classify in
  `READ_ONLY_COMMANDS`.
- `conversation-close --expired | <session_id>` — run the idle sweep, or
  close one session now (operator door; also what a cron line could call).
  Classify in `DIRECT_MUTATION_COMMANDS`. This PR's `conversation-close`
  work UPGRADES #115's minimal subcommand IN PLACE (same name — this is
  not a new/rival subcommand) and this PR OWNS the `--expired` sweep flag
  on it. #119's jobs builder calls this exact subcommand/flag to enqueue
  the sweep — do not introduce a separate `conversation-sweep` command.
- `conversation-turn-retry <session_id> <turn_index> [--confirm-not-sent]`
  — retry a definitively unsent turn; ambiguous requires the flag, exactly
  like `answer-ack-retry`. Classify in `DIRECT_MUTATION_COMMANDS`.

## Scope

**In**: `system/conversation_delivery.py`; the `run_post_answer_delivery`
rewire in `system/process_answer.py`; config keys + `config.yaml.example`
docs; `state/conversation_deliveries.json` + vault-contract/vault-paths
registration; the three CLI subcommands; engagement capture; close sweep;
skill/SKILL.md + CLAUDE.md/AGENTS.md answer-processing steps updated to
describe the turn (the ack step description changes — keep the "do not add
a second acknowledgment" rule, now phrased for turns); tests + synthetic
transcript evidence; `system/version.json` bump (changelog sized to user
impact — this is a headline change); `framework_files` gains
`system/conversation_delivery.py`.

**Out (explicit non-goals)**:
- No platform (lifehug-platform) changes — parity twin is tracked on the
  platform side by the design's Wave 3.
- No arc cards, no arc planner, no `timeline.compute_gaps` consumer
  (Wave-2 PR 5). The engine ships arc-card-absent minimal behavior and
  must keep working unchanged when PR 5 starts attaching cards.
- No router, no story-path change, no deflection (Wave-2 PR 4 —
  issue #117).
- No `jobs.py` changes, no batching-default change, no mirror inbound, no
  `compute_profile` engagement dimension (Wave-2 PR 6).
- No viewer (`serve_wiki.py`) changes — Today-card copy changes ride a
  later PR.
- `answer_ack.py` / `answer_ack_delivery.py` are NOT deleted or reworded —
  they are the live fallback and keyless path. The "No questions back"
  line stays: it is correct for the fallback ack.
- Keyless mode: the host agent remains the seated model per the Wave-1
  skill contract; this PR's engine simply reports `skipped/
  no_unattended_provider` and falls back, exactly like the ack today.

## Implementation notes (seams, not steps)

- `process_answer.py:409` `run_post_answer_delivery` — replace the
  ack+followup pair with `run_post_answer_turn`, keeping the
  plan-first structure (`plan_adaptive_followup` result passed in) and the
  per-step exception swallowing + `record_learning_failure` metadata.
- Copy the ledger/state-machine skeleton from `answer_ack_delivery.py`
  (`_state`, `_write_outcome`, `_fixed_provider_reason`,
  `_valid_completion`, the pre-send ambiguous write) rather than importing
  its privates; the recurring-defect doctrine extraction of a shared
  delivery-ledger module is deliberately deferred until a third copy
  appears (twice is the trigger, and PR 4's story turn will reuse THIS
  module, not copy it — build `conversation_delivery` so the story path
  can call it).
- Session store access only through the Wave-1 `conversation.py` CRUD —
  never raw `read_json`/`write_json` against `state/conversations/`.
- `datetime.now()` / clock access must be injectable or monkeypatchable
  for the timeout tests (module-level `_now()` hook like `jobs.py`).
- Telegram formatting: plain text like the ack; no header/footer branding
  on turn messages (the "📖 Lifehug — since you're on a roll" framing
  remains ONLY on the fallback path's separate follow-up message).

## Test plan

New `tests/test_conversation_delivery.py` (unittest, stdlib-only, injected
fakes for `ai_call` / `telegram_send` / `status_resolver` / clock /
`state_path`, synthetic vault via `tests/tempdirs.py` conventions —
NEVER `~/Workspace/dave`), following `tests/test_v121_answer_ack_delivery.py`.
Subtests (state-machine-shaped change → named explicitly, v130/v131
precedent):

- `test_confirmed_turn_is_one_message` — receipt+cued follow-up in one
  send; follow-up minted via the suffix chain; rotation updated; ledger
  `confirmed`.
- `test_confirmed_replay_is_noop` — no second model call, no second send.
- `test_ambiguous_never_auto_retried_and_no_fallback_ack` — pre-send
  ambiguous position honored; fallback ack NOT fired.
- `test_provider_unavailable_falls_back_to_todays_behavior` — ack sent with
  `followup_pending` honest, separate follow-up message sent, ledger
  `skipped`.
- `test_lint_reject_falls_back` — two-question / overlong / banned-phrase
  outputs each → `failed/malformed_generation` → fallback.
- `test_question_free_turn` — no follow-up minted, no rotation change.
- `test_third_exchange_exit_shape_and_cap` — cap governs initiative;
  user-keeps-going path still receives.
- `test_idle_timeout_files_partial_chat_silently` — no closing send for
  abandoned-mid-chat; close block written; answers remain filed.
- `test_completed_chat_closing_takeaway` — closing linted/ledgered
  (`close:{session_id}`), `takeaway_delivered` true.
- `test_engagement_appended_to_answer_scores` — engagement object on each
  filed question's record; richness untouched.
- `test_curfew_and_cap_gates_transfer` — planned-question None for gate
  reasons → question-free turn.
- `test_single_flight_mint` — concurrent second entry mints no second turn.
- `test_metadata_only_ledger_and_diagnostics` — no answer/prompt/generated
  text in ledger or learning-failure records.

Plus: extend `tests/test_answer_ack.py`-adjacent coverage only if the
`process_answer` rewire changes an existing assertion (the ack module
itself is unchanged).

Exact invocations (scoped locally; CI runs the full discover):

```
python3 -m unittest tests.test_conversation_delivery -v
python3 -m unittest tests.test_v121_answer_ack_delivery tests.test_ingest_and_planner -v
```

## Launch-and-verify

This PR does not touch `serve_wiki.py`, so no Playwright walkthrough is
required. Evidence follows the `artifacts/walkthroughs/local-warm-answer-ack/
synthetic-transcript.md` precedent (issue #52 / PR #67):

1. Commit `artifacts/walkthroughs/conversation-turn-engine/
   synthetic-transcript.md` — a deterministic, synthetic-data transcript
   (no real vault, bot, or key claimed) with one table per path:
   confirmed chat (answer → ONE receipt+payout+cued-follow-up message →
   second exchange → exit-friendly third → closing takeaway), fallback
   path (provider down → today's ack + separate follow-up, byte-shape
   identical to the current behavior), ambiguous path (no auto-retry, no
   fallback ack), and timeout path (partial chat files silently). Each
   table row names the subtest above that proves it.
2. The reviewer reproduces from scratch with:
   `python3 -m unittest tests.test_conversation_delivery -v` (all subtests
   green) — the transcript is the human-readable projection of those
   assertions, not extra claims.
3. PR comment embeds the transcript (SHA-pinned blob URL) per the evidence
   convention.

## Definition of done

- [ ] Code + tests pass locally (`python3 -m unittest discover -s tests`)
- [ ] `system/version.json` bumped (version, released, changelog,
      `framework_files` += `system/conversation_delivery.py`)
- [ ] `system/vault_contract.json` + `system/vault_paths.py` register
      `conversation_deliveries`
- [ ] AGENTS.md / CLAUDE.md / skill/SKILL.md answer-processing steps
      updated (turn replaces ack+follow-up; fallback documented; "do not
      add a second acknowledgment" preserved for turns)
- [ ] ADR: this PR implements decisions already ratified by the owner
      (2026-08-11 design session); add
      `docs/adr/` entry "Conversation turn engine replaces post-answer
      ack+follow-up" (Context/Decision/Consequences) pinning the fallback
      guarantee and the exactly-once ledger as binding — future work must
      honor both
- [ ] Issue #116 commented with verification results
- [ ] Synthetic-transcript evidence committed and embedded in a PR comment
      (SHA-pinned blob URL)
