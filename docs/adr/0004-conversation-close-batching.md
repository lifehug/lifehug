# ADR 0004: One commit, one compile, per conversation close

Date: 2026-08-12
Status: proposed

## Context

`process_answer.finalize_answer_delivery` commits twice and compiles the
wiki once per answer (`system/process_answer.py:470-493` as merged at
v154). A single-question day never felt this; a multi-turn chat — the whole
point of the conversation build (#114-#118) — multiplies that per-exchange
overhead by however many turns the exchange runs. The owner's words: "Commit/
wiki-regen per answer is overkill — batch (e.g. ~10 min after a conversation
ends)." A batched path already existed for the single-answer case
(`file_answer_bg.sh` → `--no-compile-wiki` → sentinel → hourly
`compile_and_commit.sh`), but it was opt-in per caller, not the default for
an in-session answer, and it had no analog for a conversational session's
own close.

Separately, two structural gaps existed alongside the overhead problem: the
Mirror (`system/mirror.py`) had no inbound path — `load_mirror_entries()`
read only classifier output, so the "Sit with" card's tensions had nowhere
for the author's own engagement with them to land, breaking the design's
convergence property (a tension must be able to move through conversation
alone). And `quality_profile.py`'s richness-only scoring had no signal for
whether an exchange kept the author engaged, even though the decision log
("Engagement in the Loop", "Drain is not negative") already named this as a
first-class dimension the planner should read.

Issue #119 (Conversation Interaction, Wave 2 PR 6) closes all three gaps in
one pass because they share one seam: the conversation session's close is
the natural point where in-session batching resolves into a single durable
commit, where the session's `extracted.mirror_responses` has somewhere to
file, and where engagement signals accumulated over the session become
answerable.

## Decision

**In-session filing batches by default.** When the answer being filed
belongs to an OPEN conversation session (`conversation_delivery
.find_open_session_for_question`, a pure read), `process_answer.py` flips
its defaults: skip the wiki compile, touch the compile-needed sentinel, skip
both per-answer commits. No open session leaves behavior byte-identical to
before this ADR. `--compile-wiki` (new) / `--no-compile-wiki` /
`--commit` / `--push` are explicit overrides and always win over the
session-derived default.

**The session's close is the batch boundary — ONE commit, ONE compile.**
`lifehug.py conversation-close <session_id>` now runs, in order: (a) PR3's
close machinery (closing takeaway when the session earned one, silence
otherwise — unchanged); (b) this PR's own filing steps — the Mirror inbound
write (`mirror.append_mirror_responses`, the one writer of
`state/mirror_responses.json`) and the engagement fields this PR owns
(`time_to_answer_hours` at answer time, `unprompted_inbound` at close —
PR3's own `continuation_past_exit` / `turn_length_trajectory` are
pass-through, unchanged); (c) exactly one wiki compile; (d) exactly one git
commit, message `"Conversation close <session_id>"`, over
`vault_paths.py git-paths`, pull-rebase then push — non-fatal on any git
failure, recorded to the learning-failure log (`compile_and_commit.sh`'s own
idiom). This is a platform-per-turn-capture-commit alternative, not a
regression of it: the platform's own Wave 3 (lifehug-platform#414) commits
per capture record on its own durable store; this repo's granularity is one
commit per close because there is no equivalent durable intermediate store
here — the answer file and state writes ARE the durable record, and the
close commit is bookkeeping on top of already-safe data.

**The idle-sweep discovery step is deterministic and AI-free; the actual
close is not.** `conversation-close --expired` no longer closes sessions
synchronously in the calling process (typically the hourly
`compile_and_commit.sh` cron). It finds every open session past its idle
timeout (`conversation_delivery.find_expired_open_sessions` — pure,
no AI) and ENQUEUES one durable `conversation-close` job per session
(`jobs.py`, identity `conversation-close:<session_id>` dedupes retries).
The job, when it runs, performs the full close above — including, where
warranted, an AI-generated closing takeaway. This decouples "is anything
due" (cheap, always safe to run inline) from "generate and send a closing
message" (potentially slow, potentially AI-calling) — the same shape
`compile-pending`'s own self-enqueue already established for compiles.
`conversation_delivery.close_expired_sessions` — the SYNCHRONOUS close used
by the automatic per-turn sweep inside `run_post_answer_turn` — is
unchanged; only the standalone `--expired` CLI entry point moved to
enqueue-and-wait.

**Engagement buckets key exclusively through `canonical_story_function`;
richness and engagement are structurally parallel, never merged.**
`compute_profile()['engagement']` mirrors `by_story_function` /
`by_category` / `by_focus`, the same `_multiplier` clamp (0.7-1.5), the same
`ACTIVATION_THRESHOLD` (20), and the same count-of-5 floor before a bucket's
multiplier moves off 1.0. Two lessons already paid for in this file are
binding here too: every engagement field must demonstrably fire from a real
capture path (the retired `wiki_nodes_added` precedent), and no new
vocabulary may exist outside `canonical_story_function` (the profile's
pre-v69 orphaned-function-name incident). Consumers — `question_planner
.enriched_pending_questions` and the arc planner (#118, already wired
awaiting this dimension) — apply the engagement multiplier as pacing/framing
ONLY, guarded on `engagement.active`, alongside the quality multiplier.
Neither the self-knowledge floor, the escalation gate, nor the rumination
cooldown reads it: drain is not negative, and the only sanctioned back-off
stays the rumination detector.

Alternatives considered. *Gate commit skipping on session mode ("chat" vs
"conversation") rather than "any open session"*: rejected — the batching
principle is about exchange cadence, not mode; a `conversation`-mode session
overheads the same per-turn cost a `chat`-mode one does. *Have
`--expired` keep closing synchronously and just move the AI call behind a
timeout*: rejected — a slow/hung provider would then block the hourly cron
that also owns the wiki compile everyone else's batched answers are waiting
on; enqueuing decouples the two failure domains entirely. *Store
`time_to_answer_hours` only at close, alongside the other three engagement
fields*: rejected — it is derivable from frontmatter for every answer,
session or not, and computing it retroactively-safe at filing time means a
record never touched by a conversation still carries partial engagement
signal (test-named lesson: "absent signals never fabricated" — the fields
that CAN fire, do).

## Consequences

- **Binds:** any future writer of `state/mirror_responses.json` must go
  through `mirror.append_mirror_responses` — it is the ONE writer
  (contract-restated by this PR's own consistency-audit amendment,
  superseding an earlier duplicate helper named in #115's original
  contract).
- **Binds:** `conversation_delivery.append_engagement` MERGES into a
  record's `engagement` dict rather than replacing it — a second writer
  (this PR's `time_to_answer_hours` at answer time, `unprompted_inbound` at
  close) must compose with whatever the first writer already stored, never
  clobber it. Any future third writer of an `engagement` field inherits this
  obligation.
- **Binds:** `jobs.py`'s `conversation-close` command kind is the only
  sanctioned way to enqueue a durable close; its payload is `{session_id,
  reason}`, validated against the session-store's own id shape and the
  store's own `VALID_CLOSE_REASONS` (duplicated locally in `jobs.py` by
  necessity — that module may not import `conversation.py` at all,
  per Wave-1 PR2's own NoBehaviorChangeGuardTests; see the `_SESSION_ID_RE`
  comment for why).
- **Forecloses:** a `process-answer` caller silently getting two commits and
  a full compile inside an open session without asking for it via an
  explicit flag.
- **Forecloses:** the hourly cron's idle-sweep pre-step blocking on an AI
  call — discovery is now provably synchronous-safe and AI-free.
- **Delete-when:** if `process_answer.py`'s hardcoded git-commit path tuple
  is ever unified with `vault_paths.git-paths` (a separate, smaller,
  pre-existing set — see the seam note in `tests/test_conversation_close.py
  ::ProcessAnswerBatchingTests`), the "byte-identical, including the two
  commits" regression guard should be re-verified against the wider path
  set.
