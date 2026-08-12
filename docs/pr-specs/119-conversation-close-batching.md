# Contract: conversation-close-batching (issue #119)

Conversation Interaction, Wave 2 PR6 (design §5, §6, §11; owner-ratified
2026-08-11). Four tightly-coupled pieces of the session close path:
in-session filing batches by default; `jobs.py` gains the durable
`conversation-close` command kind (close = takeaway → file outputs → ONE
commit + compile); the Mirror gets its first inbound path
(`state/mirror_responses.json`); and the quality profile gains the
**engagement** dimension per the ratified decisions. Related: #98, #99,
#103; sibling contracts #118 (arc planner) and the Wave-1/2 PRs for the
session store (`system/conversation.py`, `state/conversations/`) and the
turn engine (`system/conversation_delivery.py`).

## Why

Owner: "Commit/wiki-regen per answer is overkill — batch (e.g. ~10 min
after a conversation ends)." Today the direct process-answer path compiles
the wiki AND commits TWICE per answer (`finalize_answer_delivery` commits
before and after the conversational effects); the batched path
(`file_answer_bg.sh` → `--no-compile-wiki` → sentinel → hourly
`compile_and_commit.sh`) exists but is opt-in per caller. A multi-turn chat
would multiply that overhead per exchange. Separately, the Mirror has NO
inbound path (verified): the author's response to a "Sit with" card has
nowhere to file — `mirror.load_mirror_entries()` reads only
`state/classifications/*.json` — which breaks the convergence property
(tensions must be able to MOVE through conversation alone). And engagement
signals (decision log: "Engagement in the Loop", "Drain is not negative")
need their aggregation + consumers so the behavior itself becomes zero-
friction feedback.

## Binding facts

Verified against origin/main at c30be1d (v149). Re-verify at
implementation time.

- **Version**: main is v149; bump to the next unclaimed version at
  implementation time (wave siblings claim numbers in parallel).
- **Sequencing**: this PR REWIRES against Wave-1 PR2 (`system/
  conversation.py`: session store CRUD over `state/conversations/
  <session_id>.json`, vault-contract registered) and Wave-2 PR3
  (`system/conversation_delivery.py`: close/takeaway machinery,
  exactly-once ledger semantics; engagement-signal CAPTURE at close). Both
  are contracted to land first. If at implementation time they haven't
  merged, STOP and re-sequence — this contract does not redefine their
  deliverables, it names the seams it consumes: session doc fields
  `status` ("open|idle|closed"), `turns[]` (role/text/ts), `arc.question_id`,
  `extracted.mirror_responses`, `close.reason`
  ("done|idle_timeout|exit_taken"), `close.takeaway_delivered`,
  `close.insight_receipts_count`, and per-mode idle timeouts (chat ~2h,
  conversation ~30min — knobs in the interaction manifest).
- **The double commit**: `process_answer.finalize_answer_delivery`
  (system/process_answer.py:470–493) — commit #1 "Answer <id>: <summary>"
  before the conversational effects, commit #2 "Record answer <id> delivery
  metadata" (+push) after. `--no-compile-wiki` exists (line ~512); wiki
  compile at ~612; quality scoring (append_score) at ~615–631 — scoring is
  already decoupled from compile.
- **Batching machinery**: `file_answer_bg.sh` runs `process-answer
  --no-compile-wiki`, touches the sentinel (`vault_paths.py data-path
  compile_needed` → `state/.compile-needed`), hourly
  `compile_and_commit.sh` compiles once, removes the sentinel, commits
  "Wiki compile <ts>" over `vault_paths.py git-paths`, pull-rebases,
  pushes — failures recorded, never fatal. `compile_and_commit.sh`
  enqueues itself through jobs (`compile-pending` identity
  `compile-pending:<hour>`).
- **Jobs registry**: `system/jobs.py` COMMANDS (line ~603) maps kind →
  `CommandSpec(build, retry_safety, timeout_seconds)`. Builders validate
  payloads strictly (no payload field is ever argv/path;
  `_expect_payload(required=...)`, `_token`/`_text` validators) and return
  `Invocation`s via `_cli(*args)` (lifehug.py subcommand through the
  private stdin envelope) or `_script(name, ...)`. Sends ⇒ retry_safety
  "never" (the daily/weekly precedent). Enqueue dedupes by explicit
  identity (`enqueue(command, payload, identity=...)`).
- **Mirror**: `mirror.load_mirror_entries()` (system/mirror.py:56) returns
  `[{kind, text, source, source_short, classified_at}]` with kinds
  `contradiction` / `insight` / `position`, sorted newest-first, deduped on
  (kind, text); `build_mirror_prompt` renders per-kind blocks capped at
  `MAX_ENTRIES_PER_KIND` (300). Voice contract (module docstring + prompt):
  every claim cites the author's words; tensions coexist, "and" never
  "but"; **the author resolves them, not you** — the inbound path must not
  weaken any of this.
- **Quality profile**: `quality_profile.py` — `append_score` (idempotent
  per question_id) writes to `state/answer_scores.json` records
  `{question_id, answered_at, category, story_function, focus, signals,
  richness_score}`; `signals` already carries NON-richness fields
  (`insight_rate`, `negative_rate`, `i_rate` — "consumed by the rumination
  detector and future trend analysis": the precedent this PR extends).
  `compute_profile()` (line ~295) aggregates by story_function/category/
  focus with `_multiplier` clamped to `MULTIPLIER_FLOOR=0.7` /
  `MULTIPLIER_CAP=1.5`; `ACTIVATION_THRESHOLD=20`;
  `canonical_story_function` + `LEGACY_FUNCTION_MAP` normalize vocabulary.
  **The two historical lessons are binding law** (both documented in the
  file): (1) `wiki_nodes_added` was retired at weight 0 because it never
  fired — every new signal must demonstrably fire from real capture paths;
  (2) the profile once emitted story-function names that existed nowhere
  else, so its strongest signal applied to nothing — engagement buckets
  key EXCLUSIVELY through `question_planner.infer_story_function` /
  `canonical_story_function`.
- **Planner consumer seam**: `question_planner.enriched_pending_questions`
  applies the quality multiplier at lines ~599–607 (profile `active` gate,
  rumination ×0.25 cooldown). The self-knowledge floor
  (`self_floor_fraction` 0.08, build_queue step 1, lines ~769–779)
  reserves slots INDEPENDENTLY of weights — engagement must not touch that
  reservation logic.
- **Time-to-answer raw material** (already captured, zero new friction):
  answer frontmatter `asked_at` + `captured_at` (timestamps;
  `answered_date` is date-only fallback) — process_answer.py:583–585; plus
  `rotation.answer_latencies` (ask.py:331–340, last 100, hours) as the
  live-path precedent. Decision log pins frontmatter as the source.
- **Sweep precedent**: platform runs a scheduled close-sweep tick; the OSS
  twin belongs in the existing hourly `compile_and_commit.sh` cadence
  (mediums differ in HOW, never WHAT).
- **Vault contract**: as of drafting there is no `mirror_responses` entry
  in `system/vault_contract.json`. The Wave-1 conversation ADR names
  arc_cards + conversations + mirror_responses as contract additions — if
  Wave 1 already added the entry, don't duplicate.

## Scope

**In:**
1. **In-session batching default** in `process_answer.py`: when the answer
   being filed belongs to an OPEN conversation session (lookup via
   `conversation.open_session_for(question_id)` — a pure read over
   `state/conversations/`; the arc's `question_id` and the follow-up
   suffix chain both match), the defaults flip to: skip wiki compile,
   touch the compile-needed sentinel, and SKIP both per-answer commits
   (durability = the answer file + state writes; the close commit is the
   batch boundary). Explicit `--compile-wiki` / `--commit` / `--push`
   flags override (add `--compile-wiki` as the explicit opposite of
   `--no-compile-wiki`). No open session ⇒ behavior byte-identical to
   today, including the two commits. `file_answer_bg.sh` keeps its own
   sentinel touch (idempotent).
2. **`conversation-close` job kind** in `jobs.py` COMMANDS:
   `CommandSpec(_build_conversation_close, "never", timeout_seconds=1800)`;
   payload `{"session_id": <id>}` validated against the session-id shape
   (reuse the store's id regex from conversation.py — single authoritative
   definition, recurring-defect doctrine); builds
   `_cli("conversation-close", <session_id>)`. The `lifehug.py
   conversation-close <session_id>` subcommand orchestrates, in order:
   a. close the session via the PR3 machinery (closing takeaway when
      warranted — PR3 owns copy + exactly-once send + the skip rules for
      zero-turn/abandoned sessions; this command passes through
      `close.reason`);
   b. file extracted outputs to their NAMED consumers: engagement signals →
      answer_scores (per §4 below), `mirror_responses` →
      `state/mirror_responses.json` (per §3), `candidate_ideas` →
      candidate store with provenance "conversation", `entities` →
      classification-hint filing as defined by PR2/PR3's session doc
      (pass-through if those consumers landed there; do not re-implement);
   c. compile the wiki ONCE (reuse `wiki_compile` invocation), remove the
      sentinel;
   d. ONE git commit over `vault_paths.py git-paths` — message
      `"Conversation close <session_id>"` — then pull-rebase + push,
      non-fatal on git failure (the compile_and_commit.sh idiom, learning
      failure recorded). This is the OSS one-commit-per-close granularity
      (platform's per-turn capture commits are platform-side and out of
      scope).
3. **Close sweep (OSS twin of the platform tick)**: `compile_and_commit.sh`
   gains a pre-step that enqueues `conversation-close` for every OPEN
   session whose idle timeout has expired (`lifehug.py conversation-sweep`,
   deterministic, AI-free at sweep level; identity
   `conversation-close:<session_id>` so retries dedupe). Runs BEFORE the
   sentinel check so a vault whose only pending work is an expired session
   still closes it. Partial chats are normal and file cleanly
   (owner-confirmed): timeout close files whatever was answered, skips the
   takeaway where it would read as a nag (PR3's rule), never nags.
4. **Mirror inbound**: new `state/mirror_responses.json` (schema below,
   vault-contract registered, tracked) + writer API
   `mirror.append_mirror_responses(responses: list[dict]) -> int`
   (idempotent on `(session_id, text)`), called from the close command's
   filing step. `mirror.load_mirror_entries()` reads it alongside
   classifications, mapping each response to kind `"response"`; 
   `build_mirror_prompt` gains a fourth block ("Author responses to
   tensions") plus one prompt instruction: responses show the author
   ENGAGING a tension — reflect the development in this week's edition,
   never declare the tension resolved (the author resolves tensions, not
   you — existing voice contract, restated for the new material).
   `MAX_ENTRIES_PER_KIND` applies. The "Sit with" card thereby becomes
   conversational: the (PR5) sit_with arc intent invites, the response
   files here, the next weekly edition compiles the development.
5. **Engagement dimension** in `quality_profile.py` (schema + aggregation +
   consumers; CAPTURE at close is PR3's, but the field definitions here are
   authoritative for both):
   - Per-answer `signals` gains optional fields (absent = not captured;
     never fabricated): `time_to_answer_hours` (float, `asked_at` →
     `captured_at` from frontmatter; computable retroactively),
     `continuation_past_exit` (bool — the user kept going after the
     graceful third-turn exit, from the session doc),
     `unprompted_inbound` (bool — this answer's session was user-initiated
     following this topic; Gable "bringing news"), `turn_length_trajectory`
     (`"expanding" | "flat" | "contracting"` from within-session user turn
     word counts).
   - `compute_profile()` output gains a parallel `engagement` block:
     `{"active": bool, "scored": N, "by_story_function": {...},
     "by_category": {...}, "by_focus": {...}}`, each bucket
     `{avg, count, multiplier}` with the SAME `_multiplier` clamp
     (0.7–1.5); `active` only when ≥ `ACTIVATION_THRESHOLD` records carry
     ≥1 engagement field AND a bucket only earns a non-1.0 multiplier at
     `count ≥ 5` (the `_top_patterns` precedent). Engagement score per
     record: normalized blend of the fired signals (spec the exact blend in
     code comments; components absent ⇒ renormalize over present ones —
     never punish uncaptured).
   - Buckets key through `canonical_story_function` — never a new
     vocabulary (lesson 2).
   - **Consumers (exactly two, both pacing/framing only)**:
     `question_planner.enriched_pending_questions` multiplies base_weight
     by the engagement multiplier alongside the quality multiplier
     (guarded on `engagement.active`), leaving the self-knowledge floor,
     escalation gate, and rumination cooldown logic untouched; and the arc
     planner (#118) reads the block guarded for arc-topic/opener-framing
     bias. Engagement NEVER gates whether heavy questions get asked —
     drain is not negative (owner-set); the only back-off remains the
     rumination detector.
6. Tests + dry-run/walkthrough evidence; vault_contract + ADR touch-ups.

**Out:**
- Turn generation, takeaway copy, session lifecycle state machine (PR3).
- Router/story ingestion (PR4); arc planning (PR5/#118).
- Any platform-side change (close-sweep tick, `ensure_mutation_successor`
  debounce, CaptureRecord fields — platform Wave 3; the parity twin issue
  must be filed/linked per AGENTS.md Cross-Medium Parity).
- A nourishment dashboard (deferred, owner-paced) — this PR only records
  the cause instrumentation.
- Retro-backfill of engagement signals beyond `time_to_answer_hours`
  (the other three exist only where session docs exist).

## `state/mirror_responses.json` schema (binding)

```json
{
  "version": 1,
  "responses": [
    {
      "session_id": "…",
      "responded_at": "2026-08-16T21:04:00Z",
      "tension_ref": "<the Sit-with line or tension text, quoted verbatim>",
      "text": "<the author's words, verbatim — voice preservation>",
      "source": "conversation"
    }
  ]
}
```

`load_mirror_entries` mapping: `kind="response"`, `text=text` (prefixed
context is the prompt block's job, not stored), `source=
"conversation:<session_id>"`, `source_short=<session_id>`,
`classified_at=responded_at`. Author's words are never rewritten (voice
contract).

## Test plan

New file `tests/test_conversation_close.py` plus surgical additions to
`tests/test_mirror.py` and the quality/planner suites
(`tests/test_v69_signal.py` neighborhood). Named subtests:

- `test_in_session_answer_skips_compile_and_commits_and_touches_sentinel`
- `test_no_session_behavior_unchanged` (byte-level: two commits, compile
  runs — the regression guard for today's direct path)
- `test_explicit_flags_override_session_default`
- `test_conversation_close_command_registered_and_payload_validated`
  (unknown fields rejected; bad session id rejected; retry_safety "never")
- `test_close_files_outputs_then_one_commit` (exactly one commit; sentinel
  removed; commit message shape)
- `test_close_git_failure_is_nonfatal_and_recorded`
- `test_sweep_enqueues_only_idle_expired_open_sessions_with_stable_identity`
- `test_mirror_responses_written_idempotently`
- `test_load_mirror_entries_includes_responses_alongside_classifications`
- `test_mirror_prompt_gains_response_block_and_never_adjudicates_instruction`
- `test_engagement_fields_fire_from_fixture_capture` (lesson 1: each of
  the four signals demonstrably non-absent from a fixture session +
  frontmatter pair)
- `test_engagement_buckets_use_canonical_story_function` (lesson 2)
- `test_engagement_multiplier_clamped_and_inactive_below_threshold`
- `test_planner_applies_engagement_multiplier_but_self_floor_untouched`
  (a floor-reserved self-arc slot survives a 0.7-engagement bucket)
- `test_absent_signals_never_fabricated` (record without session doc gets
  only time_to_answer)

Prove with `python3 -m unittest tests.test_conversation_close -v` and the
full `python3 -m unittest discover -s tests -p "test_*.py"` (CI: 3.11 +
3.14, dependency-free).

## Launch-and-verify

No `serve_wiki.py` surface changes, so no Playwright walkthrough
(BUILDING.md §4). Runnable evidence for the PR comment, against a synthetic
vault:

```
# 1. File two answers inside a fixture open session — observe: no compile,
#    no commit, sentinel touched
printf 'answer one' | python3 system/lifehug.py process-answer <QID>
git -C <fixture> log --oneline   # unchanged
ls <fixture>/state/.compile-needed

# 2. Close it durably
python3 system/jobs.py enqueue conversation-close \
  --identity conversation-close:<SID> --wait   # via the payload path
git -C <fixture> log --oneline   # exactly one new commit: "Conversation close <SID>"

# 3. Mirror inbound visible to the next edition
python3 -c "import mirror; print([e for e in mirror.load_mirror_entries() if e['kind']=='response'])"

# 4. Engagement profile
python3 system/quality_profile.py --update && python3 system/quality_profile.py --show
LIFEHUG_WEEKLY_DRY_RUN=1 bash system/weekly_maintenance.sh   # quality-stats/planner preview unchanged shape
```

Pass = step 1 shows zero commits + sentinel; step 2 exactly one commit and
sentinel gone; step 3 lists the fixture response; step 4's `--show` prints
the engagement block (or "inactive (N scored...)" below threshold) and the
weekly dry run is unchanged except where this contract says otherwise.

## Definition of done

- [ ] Code + tests pass locally (`python3 -m unittest discover -s tests`)
- [ ] `system/version.json` bumped (version, released, changelog;
      `framework_files` updated for any new distributable file)
- [ ] `system/vault_contract.json` gains `mirror_responses` (or references
      the Wave-1 entry); `vault_paths.py data-path mirror_responses`
      resolves; tracked in git-paths
- [ ] AGENTS.md/CLAUDE.md updated where described behavior changed
      (filing/commit cadence, the close command)
- [ ] ADR written/extended if this pins a decision beyond the Wave-1
      conversation ADR (the one-commit-per-close granularity qualifies)
- [ ] Cross-medium parity: platform twin issue filed/linked (close-sweep
      tick, compile coalescing, engagement capture) in the same session
- [ ] Issue #119 commented with verification results; evidence embedded in
      a PR comment
- [ ] No reference to ~/Workspace/dave anywhere in code or tests (hard
      boundary)
