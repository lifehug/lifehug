# Contract: story-conversation-router (issue #117)

Wave 2, PR 4 of the Conversation Interaction build (owner-approved design,
2026-08-11). Self-contained: everything the implementer needs is in this
file plus the repo at this contract's commit. Serves issue #98; companion
to the turn engine (issue #116).

## Why

Two gaps, one PR. First, the biggest asymmetry in the product: an
unprompted story — the user's most generous act — returns NOTHING.
`system/ingest_story.py` prints a CLI checkmark, files hardcoded f-string
template candidates, and the good response (`classify_story.py`) runs
async, weekly. A story should open a **Conversation**: an immediate,
substantive conversational turn, with filing continuing underneath.
Second, inbound routing is prose-only (CLAUDE.md "Recognizing Answers",
AGENTS.md "Answer Detection") executed by whatever host agent is seated;
there is no way to delegate classification to a cheap model, and no
defined behavior for out-of-scope input. This PR adds `lifehug.py route`
(five intents, confidence threshold, safe defaults) and the warm
deflection, and sharpens the prose contracts to match — the same router
definition both runtimes execute (the two runtimes may not diverge on the
definition's own router).

## Dependencies and the merged-code-wins rule

Depends on Wave 1 (the `interactions/` scaffold + session store/builders)
and on Wave-2 PR 3 (issue #116, `system/conversation_delivery.py` — the
story turn REUSES that module; it does not copy it). Wave-1 issue numbers
were unassigned when this was written. **The interfaces below are what
this PR was planned against (design §5–§7). If merged code differs in
names or shapes, the merged code wins — re-verify at implementation start;
the pinned behavior is unchanged.**

Expected interfaces:

1. Wave-1 PR 1 files consumed here:
   - `interactions/conversation/router/router.md` — the intent-classifier
     prompt with the JSON schema inline: intents
     `{answer, new_story, command, continue_session, out_of_scope}`.
   - `interactions/conversation/router/deflection.md` — the out-of-scope
     response template + variants (canonical register: "That one's outside
     what I do — I'm here for your story. Speaking of which — is there
     anything on your mind today?").
   - `interactions/conversation/interaction.yaml` — router knobs read (not
     hardcoded): `router.confidence_threshold` and the safe-default rules
     (below), plus conversation idle timeout (~30min default).
2. Wave-1 PR 2 (`system/conversation.py`): session store CRUD
   (`state/conversations/<session_id>.json`), `build_router_prompt(...)`
   (message text + routing context → prompt), `build_turn_prompt(...)`.
3. Wave-2 PR 3 (`system/conversation_delivery.py`): the turn engine —
   readiness check via `provider_status`, generation via `call_ai` on
   `conversation_model`, runtime lints, exactly-once ledger
   (`state/conversation_deliveries.json`, statuses
   confirmed/skipped/failed/ambiguous, ambiguous never auto-retried),
   Telegram via `send_telegram_result`, session close sweep + close-time
   filing of `extracted.candidate_ideas` with `"provenance":
   "conversation"`. This PR adds a story entry point to that module and
   the close-time supersede hook.

## Binding facts (verified against the repo at this contract's commit)

- `system/ingest_story.py`:
  - `main()` flow: stdin story → `unique_source_path` →
    candidate generation → `write_text` + `register_source(source_path)`
    (durability) → `append_candidates` → checkmark prints. Flags:
    `--source --title --captured-at --witness --sensitivity --kind
    {story,opinion} --no-candidates --dry-run`.
  - `generate_candidates(title, text, source_path, created_at)` — the
    template candidates (foundation/scene/relationships/meaning + gap for
    long sources). `generate_witness_candidates`,
    `generate_opinion_candidates` likewise.
  - These templates are KEPT. They are the documented no-session fallback
    and the immediate-value path; they are never deleted by this PR.
- `system/lifehug.py`:
  - `cmd_ingest_story` wraps `run_python("ingest_story.py", flags)`; since
    v149 it takes `--commit` (post-success `_safe_autocommit`).
  - Command classification sets (lines ~60–88):
    `QUEUED_MUTATION_COMMANDS` / `READ_ONLY_COMMANDS` /
    `DIRECT_MUTATION_COMMANDS` — every new subcommand goes in exactly one.
- `system/question_candidates.py`:
  - `VALID_STATUSES = {"candidate", "accepted", "rejected", "deferred",
    "promoted", "auto_promoted", "needs_review", "expired"}` (line ~31) —
    does NOT contain `superseded`; this PR ADDS it.
  - `PROMOTABLE_STATUSES = {"candidate", "accepted", "deferred"}` (line
    ~32) — UNCHANGED: superseded candidates must never promote.
- `system/classify_story.py` — the weekly deep pass; UNCHANGED.
- `system/ai_provider.py`: `call_ai(prompt, model)`,
  `provider_status(model, probe=False)`, typed error family; keyless =
  provider `agent-task`, not ready.
- Config keys: `router_model` (default `"claude-haiku-4-5"`) and
  `conversation_model` (default `"claude-sonnet-5"`) are defined and
  documented by PR 3 (#116). This PR consumes them.
- `system/rotation.json` (vault key `rotation`, `state/rotation.json` with
  embedded fallback): the pending question is `last_question_id`;
  `awaiting_pass_transition` is the pass-transition gate — the router
  context includes both.
- CLAUDE.md "### Recognizing Answers" (line ~1202), AGENTS.md
  "## Answer Detection" (line ~349), `skill/SKILL.md` answer-processing
  (~lines 89–111) and story-ingest (~line 127) sections — the prose
  contracts this PR rewrites.
- Version/CI: `system/version.json` bump, no exemption; origin/main is at
  149 as written — pick the next free number at implementation time. CI =
  `python3 -m unittest discover -s tests -p "test_*.py"`, Python
  3.11/3.14, dependency-free, stdlib only. No ruff/pytest in this repo;
  do not introduce any.

## Part A — Story → Conversation

**Behavior.** After a story is durably filed (post
`register_source`), the ingest path makes a best-effort conversation
response:

1. If an open Conversation session exists for this channel and is not
   idle-expired → this story CONTINUES it (a new user turn). Otherwise a
   Conversation session OPENS at this inbound (design: a conversation
   session opens at first inbound; mode `"conversation"`, channel from
   `--source` mapping, e.g. `telegram` → `"telegram"`, `manual`/CLI →
   `"cli"`).
2. The turn engine generates an immediate substantive turn — receipt
   quoting the user's words, register match, at most one cued follow-up
   invitation — via the SAME `conversation_delivery` machinery as #116
   (readiness → single-flight mint → generate → lint → pre-send ambiguous
   → send → ledger, entry keyed `turn:{session_id}:{turn_index}`). On
   Telegram the "Filing…"-style silence is replaced by this real response;
   filing continues underneath unchanged.
3. **No-session fallback (KEPT, documented)**: if the provider is not
   ready (keyless CLI ingest, agent-task mode) or generation/lint/send
   definitively fails, behavior is EXACTLY today's: checkmark output,
   template candidates filed immediately, no session created (or, for a
   failed turn on an already-open session, the session simply doesn't gain
   a lifehug turn). The story-turn attempt must never block, delay
   perceptibly, or fail the ingest itself — same swallow-everything
   posture as `run_post_answer_delivery`.
4. **Template candidates are generated at ingest time in BOTH cases** —
   they are the immediate-value floor. At SESSION CLOSE over story source
   S (close machinery from #116), when classifier-grade
   `extracted.candidate_ideas` are filed (with
   `"provenance": "conversation"`), every candidate whose
   `source_path == S` and whose status is still `"candidate"` flips to
   `"superseded"` — superseded, never deleted (history preserved,
   non-promotable). If the session closes with NO extracted candidate
   ideas, the templates stay live (nothing supersedes them).
5. `classify_story.py` still runs weekly as the deep pass, unchanged; its
   candidates coexist as today.
6. Witness (`--witness`) and opinion (`--kind opinion`) ingests keep their
   specialized template candidates; in v1 they take the SAME conversation
   turn path (the turn prompt receives the source type so the register
   matches — a witness account is another person's words; an opinion gets
   curious Socratic energy, not narrative-scene probing). If the Wave-1
   prompt files lack per-type guidance, the engine still runs — behavior
   guidance lives in the definition files, not in code.

**Turn identity for story follow-ups**: a follow-up cued inside a
Conversation turn is conversational (it lives in the session document and
the message). It is NOT minted into the question bank at ask time —
story-derived questions enter the system as candidates (template now,
classifier-grade at close), exactly as today. (The bank suffix-chain
minting in #116 applies to chat mode's answer follow-ups only; keeping the
story path candidate-based means zero new teaching for
coverage/rotation/planner.) If the user answers a story follow-up, that
reply routes as `continue_session` and files as a further story source /
session turn per the router rules below.

## Part B — the router (`lifehug.py route`)

**Command.** `route` — classify one inbound message. Reads stdin JSON:

```json
{"text": "the inbound message", "channel": "telegram|web|cli"}
```

(`channel` optional, default `"cli"`.) Prints one JSON object on stdout:

```json
{"intent": "answer|new_story|command|continue_session|out_of_scope",
 "confidence": 0.94,
 "source": "model|default",
 "action": "file_answer|ingest_story|handle_command|continue_session|deflect|ask_user",
 "pending_question_id": "A14b",
 "open_session_id": "…"}
```

(`pending_question_id` / `open_session_id` are null when absent.) Exit 0
on any successful classification INCLUDING the deterministic default; a
non-zero exit only for invalid input. Classified `READ_ONLY_COMMANDS` —
routing reads rotation + session state and makes a model call but mutates
nothing durable.

**Mechanics.**

1. Context: `rotation.last_question_id` (pending question, with its text
   from the bank), `awaiting_pass_transition`, and any open non-expired
   session from the store.
2. Prompt via Wave-1 `build_router_prompt`; call
   `call_ai(prompt, router_model)`; parse strict JSON
   `{"intent": …, "confidence": …}` per router.md's inline schema.
   Malformed output → treat as unavailable (default path), metadata-only
   diagnostics (`record_learning_failure`), never echo the message text.
3. **Threshold + safe default** (values from `interaction.yaml`, shared
   with the platform runtime — the two runtimes may not diverge):
   - model result with `confidence >= router.confidence_threshold` →
     `source:"model"`, intent as classified;
   - below threshold, or provider unavailable/keyless/malformed →
     `source:"default"` with the deterministic rule: pending question
     exists → `answer`; else open session → `continue_session`; else →
     `action:"ask_user"` (intent still reported as the model's
     best guess when one exists, otherwise `new_story` with
     `action:"ask_user"` — the caller asks one clarifying line rather
     than guessing).
   - `continue_session` is the default CLASS whenever a session is open —
     router.md instructs the model accordingly; the code default above
     mirrors it.
4. Intent → action mapping (fixed): `answer`→`file_answer` (against
   `pending_question_id`), `new_story`→`ingest_story`,
   `command`→`handle_command`, `continue_session`→`continue_session`,
   `out_of_scope`→`deflect`. `ask_user` appears only via the safe-default
   rule. Prefix hatches are unchanged and short-circuit BEFORE routing:
   `/artifact`, `artifact:`, `opinion:` and the `awaiting_pass_transition`
   reply flow are handled exactly as documented today — `route` is for
   free text only, and the prose contracts say so.
5. **Deflection**: `route` classifies; it does not send. The host agent
   answering `deflect` sends `router/deflection.md`'s template (a variant,
   warmly, ONCE per exchange — never solves the out-of-scope request, per
   behavior contract scope rule; canonical shape pasted above). Repeated
   off-scope in one exchange → deflect once, then stay silent rather than
   scold.

## Part C — sharpened prose routing contracts

Rewrite (not append) the three prose surfaces to the same five-intent
contract, each ending with the delegation note:

- CLAUDE.md "### Recognizing Answers": the current 4-bucket list becomes
  the five intents + the prefix/pass-transition short-circuits + "the host
  agent MAY delegate classification to
  `printf '%s' "$MSG" | python3 system/lifehug.py route` and act on its
  `action` field; when a Conversation session is open, `continue_session`
  is the default reading of free text."
- AGENTS.md "## Answer Detection": same contract, model-neutral wording,
  including the out-of-scope → deflection.md rule ("respond naturally,
  stay in character" is REPLACED by the scope rule: chats and
  conversations for building the vault, nothing else — deflect warmly,
  redirect into scope).
- `skill/SKILL.md`: the Answer Processing section gains the routing step
  (route → act per action table above); the story section notes a story
  now opens/continues a Conversation and gets an immediate turn; the
  keyless note: with no unattended provider, `route` returns the
  deterministic default and the host agent judges edge cases itself using
  the same five-intent definitions.

All three must state the SAME intents, defaults, and deflection rule —
divergence between them is a review defect.

## Scope

**In**: story-turn entry point in `system/conversation_delivery.py` +
ingest-path hook (`ingest_story.py` and/or `cmd_ingest_story` — implementer
picks the seam; the hook must run after durability and be fully swallowed);
close-time supersede of template candidates; `superseded` status;
`lifehug.py route` + `READ_ONLY_COMMANDS` entry; deflection wiring in
prose; the three prose-contract rewrites; tests + synthetic transcript
evidence; `system/version.json` bump.

**Out (explicit non-goals)**:
- No platform (lifehug-platform) changes — the platform's
  `process_inbound` router branch is Wave 3 and consumes the same
  definition files via the pin.
- No arc cards / arc planner / monthly conversation-thread offers
  (Wave-2 PR 5); no neighborhood "conversation-ready" marking.
- No `jobs.py` changes, batching, mirror inbound, or engagement profile
  dimension (Wave-2 PR 6).
- No viewer (`serve_wiki.py`) changes; no new Telegram inbound daemon —
  OSS inbound remains host-agent-mediated; `route` is a tool the host
  agent calls.
- `classify_story.py` unchanged. `generate_candidates` /
  `generate_witness_candidates` / `generate_opinion_candidates` template
  TEXT unchanged (byte-identical keyless output is a regression
  assertion).
- No router fine-tuning, fixtures-in-CI eval harness (Wave 3 PR 12), or
  overlay work.

## Implementation notes (seams, not steps)

- The story hook's home: prefer a small function in
  `conversation_delivery` (e.g. `run_story_conversation_turn(*,
  source_id, source_path, title, story_text, source_type, channel,
  state_path=..., ai_call=None, telegram_send=None, status_resolver=None)
  -> TurnOutcome`) called from the ingest path after `register_source`,
  wrapped in the same try/except + `record_learning_failure` metadata
  posture as `run_post_answer_delivery`. Keep `ingest_story.py`
  importable and side-effect-free for `--dry-run` (dry runs make NO
  provider calls and open NO session).
- Supersede hook: the #116 close path exposes (or gains here) a
  post-extraction hook; the status flip goes through the candidate
  store's update path so `updated_at`-style bookkeeping stays consistent
  — check how `question_candidates.py` mutates status (line ~449 guard)
  and extend `VALID_STATUSES` there only.
- `route` lives as `cmd_route` in `lifehug.py` calling a
  `system/conversation_delivery.py` (or `conversation.py`, if Wave 1 put
  the pure parts there) `route_message(...)` function so tests can inject
  `ai_call`; the CLI is a thin printer.
- Never log or persist message text in diagnostics — metadata-only, same
  binding as the ack/turn ledgers.

## Test plan

New `tests/test_conversation_router.py` + additions to
`tests/test_ingest_and_planner.py` (unittest, stdlib-only, injected
fakes, synthetic vault — NEVER `~/Workspace/dave`). Subtests:

Router:
- `test_route_five_intents_from_model` — labeled fixture messages (an
  answer-like reply with a pending question; "here's a story about my
  grandfather's truck"; "show coverage"; a mid-session continuation;
  "what's the weather?") → expected intent/action via fake `ai_call`.
- `test_route_threshold_falls_to_default` — low-confidence model result →
  `source:"default"`, pending-question default.
- `test_route_keyless_deterministic_default` — provider not ready →
  answer-if-pending, else continue_session-if-open, else `ask_user`;
  exit 0.
- `test_route_malformed_model_output_defaults` — junk JSON → default path,
  metadata-only diagnostic.
- `test_route_mutates_nothing` — rotation/session/candidate files
  byte-identical after a route call.

Story → Conversation:
- `test_story_opens_conversation_and_sends_turn` — session created (mode
  `conversation`), one lifehug turn ledgered `confirmed`, template
  candidates ALSO filed.
- `test_story_continues_open_session` — second story within idle window
  adds a turn to the same session.
- `test_keyless_ingest_is_byte_identical_to_today` — provider not ready →
  no session, checkmark + template candidates exactly as the current
  behavior (regression pin).
- `test_dry_run_makes_no_calls_and_no_session`.
- `test_close_supersedes_template_candidates` — close with extracted
  candidate_ideas (provenance `conversation`) flips matching
  status-`candidate` templates to `superseded`; already-promoted ones
  untouched; superseded is non-promotable
  (`PROMOTABLE_STATUSES` unchanged).
- `test_close_without_extraction_keeps_templates_live`.
- `test_witness_and_opinion_take_turn_path` — source type reaches the
  prompt payload; fallback identical to today for each kind.

Prose-contract guard:
- `test_prose_contracts_name_five_intents` — CLAUDE.md, AGENTS.md, and
  skill/SKILL.md each contain all five intent names and the `lifehug.py
  route` delegation (cheap drift tripwire, same spirit as the
  framework-manifest check).

Exact invocations (scoped locally; CI runs the full discover):

```
python3 -m unittest tests.test_conversation_router -v
python3 -m unittest tests.test_ingest_and_planner tests.test_conversation_delivery -v
```

## Launch-and-verify

No `serve_wiki.py` surface — no Playwright walkthrough. Evidence per the
`artifacts/walkthroughs/local-warm-answer-ack/synthetic-transcript.md`
precedent:

1. Commit `artifacts/walkthroughs/story-conversation-router/
   synthetic-transcript.md` — deterministic synthetic transcript, one
   table per path: story → immediate substantive turn (what the synthetic
   author sees on Telegram, with filing rows underneath); keyless ingest
   (today's checkmark + candidates, no fabricated response); router
   classification table (five fixture messages → intent/confidence/action,
   including the below-threshold default and the deflection response
   text); session close with candidate supersede (before/after status
   rows). Each row names the proving subtest.
2. Reviewer reproduces from scratch:
   `python3 -m unittest tests.test_conversation_router -v`.
3. A live keyless smoke anyone can run without keys:
   `printf 'what is the weather today?' | python3 system/lifehug.py route`
   → deterministic-default JSON on stdout, exit 0.
4. PR comment embeds the transcript (SHA-pinned blob URL).

## Definition of done

- [ ] Code + tests pass locally (`python3 -m unittest discover -s tests`)
- [ ] `system/version.json` bumped (version, released, changelog; no new
      `framework_files` expected unless the implementer adds a new module
      file — if so, add it)
- [ ] CLAUDE.md "Recognizing Answers", AGENTS.md "Answer Detection",
      skill/SKILL.md rewritten to the identical five-intent contract
- [ ] `superseded` added to `VALID_STATUSES`; `PROMOTABLE_STATUSES`
      untouched
- [ ] ADR: add `docs/adr/` entry "Inbound routing: five intents, one
      definition, both runtimes" pinning as binding that the router
      contract (intents, threshold, safe defaults) lives in
      `interactions/conversation/` and that runtimes consume, never fork,
      it — future work must honor this
- [ ] Issue #117 commented with verification results
- [ ] Synthetic-transcript evidence committed and embedded in a PR comment
      (SHA-pinned blob URL)
