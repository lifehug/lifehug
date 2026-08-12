# Contract: day-rollover-close (issue #136)

PR 1 of the **Chats-per-Focus reshape** (owner ideation 2026-08-12, ratified
direction) — the OSS-first day-rollover close, written here as the
platform's parity spec. Design scope: §D (Day-scoped session policy +
transitions) + the relevant §G item 1 text of the Chats-per-Focus design
draft. This document is self-contained; the platform-side sibling PR (design
§G item 2) transports the same shell step verbatim into `workflow.py`.

## Context (from the design)

Owner ideation (2026-08-12, ratified direction): the product's surfaces
reorganize around the chat metaphor the conversation build made real. Three
unifying moves:

1. **The day owns the surface** — today's chat lives on the Today page until
   the daily loop replaces it. No invented timers (2h idle / 15-min sweep
   demote to janitor duty). Endings are conversational events (exit door,
   transition), never silent timeouts.
2. **The Focus owns the thread** — a Focus is a contact. James is a thread;
   Dottie is a thread; the Seattle years are a thread. A new question about
   James RESUMES the James thread. The `/answers` page becomes **Chats**:
   scroll past threads, click one, read the whole history — including
   pre-conversation-era answers rendered as chat turns.
3. **The user owns transitions** — "Something else" tab starts an off-topic
   conversation; starting a new conversation ends the previous one (its
   takeaway lands in-thread, visible on return — the peak-end payout gets
   witnessed because closes happen at moments the user caused).

Owner's explicit ask: "I can go back and scroll through the chats, click on
them, and open up a chat for a past answer."

Principles applied (from the interaction doctrine): conversation is the
product's voice, the archive whispers; prove memory ambiently; autonomy-by-
default; honest surfaces, no unwitnessed endings; one owner of identity — the
session owns the box, the Focus owns the thread, **the day owns the
surface**.

This PR is scoped to the last of those: the day-scoped session policy that
makes "the day owns the surface" true in the delivery flow, so downstream
UI work (the sibling platform PRs) can build the Chats page against a close
lifecycle that is event-driven, not timer-driven.

## Design §D — Day-scoped session policy + transitions

- **Closes become events, never timers**: (1) user transition — Rest, or
  starting a new conversation while one is open (previous closes with
  takeaway appended in-thread); (2) **day rollover** — the daily delivery
  flow closes the vault's open sessions (reason `day_rollover`, takeaway
  appended, visible later in the thread) BEFORE minting the day's question.
  OSS-first per parity: the shell (`daily_question.sh`) gains the close step
  as the spec; the platform transports it in the delivery workflow
  (`workflow.py`) exactly as cadence steps are transported today.
- **The 15-min sweep demotes to janitor**: policy constant change only — it
  closes sessions idle > 36h (safety net for abandoned conversation-mode
  sessions), no user-facing role. Terraform/scheduler untouched.
- `interaction.yaml` knobs updated (OSS): chat/conversation idle knobs
  raised to day-scale with a doc note that the day rollover + user
  transitions are the real lifecycle.
- Dots/pending semantics unchanged (dots only between send and reply —
  decided previously).

## Design §G item 1 — this PR's work item, verbatim

> **PR 1 — OSS: day-rollover close (the parity spec)** [Sonnet]:
> `daily_question.sh` gains a pre-question step closing open sessions via
> the existing `conversation-close --expired` machinery generalized to
> `--day-rollover` (closes ALL open sessions with reason `day_rollover` +
> takeaway); `interaction.yaml` knob updates; version bump; the shell step
> is written as the platform's transport spec per doctrine.

Sequencing note (from the design's §G closing paragraph): "PR 1 → (release +
pin bump rides the next routine bump — the day-rollover transport in PR 2 is
gated on the pin carrying PR 1; the body reversal + chats UI are NOT
pin-gated and can land first) → PR 2 → PR 3."

## Binding facts (origin/main at implementation time = cb4dfb2, v160)

Re-verify at implementation time if this contract is ever replayed.

- The merged `conversation-close` machinery lives across three layers, all
  three touched by this contract:
  - `system/conversation.py` — `VALID_CLOSE_REASONS` (currently
    `{"done", "idle_timeout", "exit_taken"}`), the store's `close_session`.
  - `system/conversation_delivery.py` — the engine: `is_idle_expired`/
    `idle_timeout_minutes` (continuation checks, e.g.
    `find_open_session_for_channel`), `find_expired_open_sessions`/
    `close_expired_sessions` (the `--expired` sweep's discovery/close pair,
    also run inline at the top of every post-answer turn), `close_session_now`
    (the >=2-user-turns takeaway rule, silent below), and the module's own
    `close` CLI subcommand (`--expired`/`--reason`).
  - `system/lifehug.py` — the operational CLI wrapper
    (`conversation-close`, in `DIRECT_MUTATION_COMMANDS`): `--expired`
    branches to `_enqueue_expired_conversation_closes`, which uses
    `conversation_delivery.find_expired_open_sessions` for AI-free discovery
    and enqueues one durable `conversation-close` job per session
    (`jobs.py`, identity `conversation-close:<session_id>` dedupes retries),
    waiting via `_queue_and_wait`/`wait_for_job_embedded_safe` (embedded-safe:
    drains inline when called from inside an already-running job, so this is
    safe to call from `daily_question.sh`, which itself runs inside the
    `daily` job).
  - `system/jobs.py` — `_build_conversation_close` mirrors
    `VALID_CLOSE_REASONS` in a hardcoded set (documented reason: it can't
    import `conversation.py` — see `_SESSION_ID_RE`'s comment) and must stay
    in lockstep.
- `system/compile_and_commit.sh` is the existing precedent for this exact
  shape: it calls `lifehug.py conversation-close --expired --vault-root
  "$WORKSPACE"` as a pre-step, non-fatal, before its own sentinel-gated
  compile. This PR's `daily_question.sh` step mirrors that precedent with
  `--day-rollover` in place of `--expired`.
- `interactions/conversation/interaction.yaml` is the flat-scalar-only
  config (`lifehug_core._parse_simple_yaml`; no nesting, no lists — comments
  after `#` on any line, blank lines and full-line comments skipped).
  `conversation.load_interaction_manifest` casts every `knob.*`/`budget.*`
  value to numeric. Current lifecycle knobs: `chat_idle_timeout_minutes:
  120`, `conversation_idle_timeout_minutes: 30` (owner-accepted defaults,
  2026-08-11).
- Test seams: `tests/test_conversation_delivery.py` (`EngineTestCase`,
  in-process, injected collaborators, synthetic temp vault via
  `tempdirs.root_parent_tmp`) already asserts the pre-change knob values
  (`test_idle_timeout_knobs_come_from_interaction_yaml`) and a 5-hour idle
  sweep close (`test_idle_timeout_files_partial_chat_silently`) — both need
  updating to the new day-scale/janitor semantics, not just extending.
  `tests/test_conversation_close.py` (`VaultSubprocessTestCase`, real
  subprocess against a synthetic on-disk vault with a real local git repo)
  has the CLI-level enqueue precedent
  (`test_sweep_enqueues_only_idle_expired_open_sessions_with_stable_identity`).

## Deliverables

1. **`system/daily_question.sh`**: a pre-question step, placed after the
   wiki-compile step and before the pass-transition/`ask.py` pick, that
   calls `python3 "$SCRIPT_DIR/lifehug.py" conversation-close
   --day-rollover` (non-fatal, `record_learning_failure` on nonzero exit —
   same idiom as the compile step immediately above it). This exact
   invocation (flag, placement) is THE PLATFORM'S TRANSPORT SPEC — the
   sibling platform PR mirrors it verbatim in `workflow.py`. The
   `LIFEHUG_DAILY_DRY_RUN=1` preview branch gains one added line
   (`conversation-close --day-rollover --dry-run`, a pure read) — every
   other line in that branch is unchanged.
2. **`conversation-close --day-rollover`** (generalizes the merged
   machinery, all three layers):
   - `conversation.VALID_CLOSE_REASONS` gains `"day_rollover"`; `jobs.py`'s
     mirrored validation set follows.
   - `conversation_delivery.py` gains pure discovery
     (`find_open_sessions` — every OPEN session id, no idle filter) and a
     synchronous engine entry point (`close_all_open_sessions` — mirrors
     `close_expired_sessions` minus the janitor filter, reason
     `"day_rollover"`); its own `close` CLI gains `--day-rollover`.
   - `lifehug.py`'s `conversation-close` CLI gains `--day-rollover` (+
     `--dry-run`, meaningful only alongside it) and
     `_enqueue_day_rollover_conversation_closes`, the enqueue-durable-job
     twin of `_enqueue_expired_conversation_closes` — same per-session job,
     same identity (`conversation-close:<session_id>`, deliberately shared
     dedup key with the janitor sweep), reason `"day_rollover"` instead of
     `"idle_timeout"`.
   - The takeaway criterion is NOT re-decided: `close_session_now`'s
     existing >=2-user-turns rule governs every reason equally — a
     day-rollover close earns a takeaway (appended in-thread, per design
     §D) under the same rule an idle-timeout or explicit close does; fewer
     turns close silently.
3. **`--expired` re-reads a new janitor knob**: `is_janitor_expired`
   (mode-independent, `knob.janitor_idle_hours`, default 36) replaces
   `is_idle_expired` inside `find_expired_open_sessions`/
   `close_expired_sessions` only — `is_idle_expired`/`idle_timeout_minutes`
   stay exactly as they are for continuation checks (`find_open_session_for_channel`
   and the inline per-turn sweep call site are unaffected by the rename;
   only the *values* they read change, per point 4). The `--expired` flag
   itself, its CLI surface, and its job-enqueue shape are unchanged — only
   its threshold source changes, per design §D ("The 15-min sweep demotes
   to janitor").
4. **`interaction.yaml`**: `chat_idle_timeout_minutes` and
   `conversation_idle_timeout_minutes` raised to `1440` (day-scale); new
   `knob.janitor_idle_hours: 36`; a doc comment recording that day rollover
   + user transitions are the real lifecycle and the sweep is a janitor.
   Flat scalar keys only, per the parser's documented subset — no nesting,
   no lists.
5. **Tests** (scoped unittest, synthetic vaults only):
   - Day rollover closes every open session regardless of idle age, and is
     idempotent (a second pass closes nothing).
   - The takeaway rule (>=2 user turns) is honored identically under
     `day_rollover` as under any other reason.
   - `--expired`/the janitor sweep reads `knob.janitor_idle_hours` (a
     5-hour-idle session — which used to trip the old 120-minute chat
     knob — must NOT close under the new 36h janitor; a 37-hour-idle
     session must).
   - The existing knob-value test
     (`test_idle_timeout_knobs_come_from_interaction_yaml`) updated to the
     new 1440-minute values.
   - `daily_question.sh`'s dry-run preview gains exactly the one new line
     (text-level assertion, matching this repo's established convention for
     shell "parity SPEC" tests — see `tests/test_arc_planner.py`'s
     `CommandSurfaceTests`).
6. **Version bump**: `system/version.json`, next free integer, changelog
   entry naming this issue.

## Out of scope (sibling PRs)

- The platform transport of this shell step into `workflow.py` (design §G
  item 2, platform PR 2) — gated on the OSS pin carrying this PR.
- The body-reversal endpoint, `focus_context` fold, and janitor-constant
  transport on the platform side (also PR 2).
- The Chats list/thread-view UI (design §B/§C, platform PR 3).
- The Today box's `[Today] [＋]` tab strip (design §E) — a platform/web
  concern, not this repo's.

## Launch-and-verify

```bash
cd system
python3 -m unittest tests.test_conversation_delivery tests.test_conversation_close -v
python3 ../scripts/ci/check_framework_files.py
python3 ../scripts/ci/check_version_bump.py --base <base-sha> --head <head-sha>
bash -n daily_question.sh
LIFEHUG_DAILY_DRY_RUN=1 LIFEHUG_VAULT_ROOT=<synthetic-vault> bash daily_question.sh
```

The dry-run transcript's shape is unchanged except for one new
`conversation-close --day-rollover --dry-run` line between the "would use
configured Telegram delivery target" line and the `ask.py --dry-run` output.
