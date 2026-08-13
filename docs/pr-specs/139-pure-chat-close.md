# Contract: pure-chat close (issue #139)

Pure-chat wave, OSS half (PR A). Owner-ratified design: `chats-per-focus-design.md`
§K (scratchpad, Fable, 2026-08-12); full ruling log:
`interaction-decisions.md`, entries "2026-08-12 (evening) — Pure-chat rulings",
"2026-08-12/13 — Close-message refinement", "2026-08-13 — Cross-day thread
model confirmed" (owner, verbatim). Twin PRs land in `lifehug-platform`
(PR B: API/engine; PR C: web) — out of scope here, noted for cross-medium
parity per CLAUDE.md.

## Owner rulings (source of truth — quoted verbatim where load-bearing)

1. **Exit affordance removed everywhere.** "If the person wants to stop,
   they just stop... If they want to keep going they just keep typing so
   it's unnecessary." No keep-going/rest-here buttons, no distinct
   exit-offer turn. Reply-is-consent.
2. **Closes are declarative — the statement IS the out.** No open
   question, no invitation, no meta-framing ("leave it here", "for now",
   "that's a good place to rest/leave", "we'll…", any announced ending).
   Owner's edited worked example (Whidbey Island): struck "That's a good
   one to leave sitting here for now —"; kept the settled witness/filing
   line **"I'll keep it filed next to the rowboat and the ducks."** as the
   exemplary close shape. "The user feels it's a closing statement" —
   closure is a felt quality of prose, never an announced state. Reopen →
   converse → closes the same way again — "the hard out at some point":
   every engagement eventually gets its own settling statement.
3. **No special styling on close messages** — platform-side rendering
   concern (kill the green highlight); noted here because behavior.md's
   rule 8 rewrite must not imply any code-side signal either.
4. **Reply-after-close routing.** "They're talking about this question" —
   a reply to a closed chat/thread, same day or later, is about that
   subject, never unrelated `new_story`. Consistent with the
   threads-keyed-by-subject model: the thread IS the subject.

## Binding facts (verified against the repo at this contract's commit,
`3ad49c1`, PR #137 day-rollover merged)

- **No `exit_offer` turn kind exists anywhere in this repo.** Repo-wide
  grep for `exit_offer`, `exit-offer`, `at_exit_offer`, `ExitOffer`,
  `EXIT_OFFER` returns zero hits. Session-document turns
  (`conversation.append_turn`) carry no `kind` field at all — only
  `role`/`text`/`ts`/`channel`/`router`/`model`/`question_id`/
  `source_path`. **Consequence**: the task's backward-compatibility
  requirement ("render/treat historical exit_offer turns as plain
  messages, never crash on history") is satisfied trivially — there is no
  such historical shape to guard against, and no rendering code branches
  on turn kind. This is recorded here rather than silently skipped so a
  future reader doesn't wonder why no compat shim exists.
- The actual mechanic the design calls "exit_offer"/"at_exit_offer" is
  `system/conversation_delivery.py`'s **chat-mode turn shape**:
  `decide_turn_shape` assigns position `third_exchange_exit_friendly` to
  the exchange at `knob.chat_target_exchanges` (default 3) — a turn that
  pays out and asks NOTHING, with `_output_contract_block` instructing the
  model: *"This is the exit-friendly turn: make stopping here feel like a
  good place to rest."* That instruction is itself banned meta-framing
  under ruling 2 once the doctrine is stated precisely, and it duplicates
  signaling: a LATER, separate close (idle-timeout sweep / day rollover /
  explicit `done`) generates a full closing takeaway
  (`conversation.build_closing_prompt` → `_deliver_closing`) with its own
  anatomy (takeaway, appreciation, continuity, hook). Two different
  "we're wrapping up" messages could land near each other — the double
  signal the owner's challenge ("why are we trying to signal the chat's
  over?") points at.
- `interactions/conversation/plan/arc-templates.md`'s `thread_offers` /
  `plan_thread_offers` (monthly conversation-thread outreach, "I've been
  wanting to ask about X — shall we?") is an UNRELATED mechanism —
  proactive re-engagement, not an in-session exit ceremony. Out of scope,
  untouched.
- No Telegram/CLI inline-keyboard or button code exists anywhere in this
  repo (`grep -rn "inline_keyboard\|callback_data\|reply_markup"` — zero
  hits). The "keep-going/rest-here button emission" the task names as a
  shell affordance to remove does not exist in OSS as literal UI; the
  equivalent surface here is purely textual (the exit-friendly turn's
  copy, above). Recorded so review doesn't look for buttons that were
  never built.
- The router (`system/conversation_delivery.route_message`,
  `interactions/conversation/router/router.md`) only ever looks at OPEN
  sessions (`find_open_session_for_channel`, `status="open"`). There is no
  existing lookup for the most-recently-CLOSED session on a channel, so a
  message that lands after a close, once `rotation.last_question_id` has
  moved on (multi-day case) or when the model classifies confidently
  against a stale read, has no structural rung above the terminal
  `ask_user`/`new_story` fallback. This is the gap ruling 4 closes.
- `conversation.close_session` writes no `closed_at` timestamp on the
  `close` block (only `reason`/`takeaway`/`takeaway_delivered`/
  `insight_receipts_count`/`filed`/`entity_hints`); its idempotency check
  compares the close payload for exact equality
  (`doc.get("close") == close`), so adding a call-time timestamp there
  would break replay-idempotency for existing callers. This spec uses the
  session's LAST TURN timestamp (`conversation_delivery._last_activity`,
  already used by the idle/janitor sweeps) as the proxy for "when did this
  channel go quiet" instead of touching `close_session`'s contract.
- `conversation_delivery.lint_outgoing(message, question_allowed=False,
  ...)` already blocks ANY question in a closing message via its
  `question_not_permitted` check (`_question_sentences` scanning), wired
  through `_deliver_closing`. The "no open question" half of ruling 2 is
  therefore ALREADY enforced at runtime; this PR adds the missing half —
  banned meta-phrases — as a new deterministic lint, not a new
  no-question check.

## Design

### 1. behavior.md — close-style doctrine (replaces rule 8's exit-offer
framing)

Rule 8 ("Closings") is rewritten in place (rule numbers stay pinned per
the file's own header contract):

- A close is: a takeaway (not a recap) + specific appreciation + a
  continuity line + an optional deposit-frame (unchanged knob) + a named
  hook — **declarative throughout, ending on the peak, with no trailing
  question and no sentence that grants an exit.** The statement itself IS
  the user's out; nothing announces that it is one.
- Banned shapes (explicit, lintable where mechanical): "leave it here",
  "for now" (as a hedge softening the ending), "a good place to
  rest"/"a good place to stop", "we'll…" future-tense hand-offs, and any
  other sentence whose job is to narrate that the conversation is ending
  rather than simply ending it.
- The exemplary shape is a **concrete witness/filing line** — cited
  verbatim (owner's ratified worked example): *"I'll keep it filed next to
  the rowboat and the ducks."* — declarative, specific, and settled
  without saying so.
- Reopening after a close is normal, not a special case: the next
  engagement converses and closes the same way. Every engagement earns its
  own settling statement — nothing is ever left announced-open, and
  nothing is ever told to the user about stopping or continuing.

### 2. Turn engine — remove the exit-friendly position

`decide_turn_shape` (chat mode) currently returns four positions
(`opening` / `mid_arc` / `third_exchange_exit_friendly` /
`past_target`); the third is removed and folded into `past_target`'s
plain "ask no question, keep receiving" shape (question-allowed math is
unchanged: `question_allowed = planned_question is not None and
user_turns < target`, so the target-th exchange was ALREADY
question-free — only the special copy and position label are removed).
`_output_contract_block`'s exit-friendly branch (the "make stopping here
feel like a good place to rest" instruction) is deleted; that turn now
gets the same plain question-free instruction every other question-free
turn gets. `turn-instructions.md`'s documented position enum drops
`third_exchange_exit_friendly`. The exchange budget itself is UNCHANGED
(still governs OUR initiative only, still never hard-stops a user who
keeps going) — it now operates with no turn dedicated to announcing it.

The actual close — the one message that legitimately signals an ending —
stays exactly where it already lived: `close_session_now` /
`_deliver_closing`, triggered by idle-timeout sweep, day rollover, or an
explicit close command. That path is untouched structurally; only its
lint gains the banned-meta-phrase check (below).

### 3. Closing-declarative lint (new deterministic check)

`interactions/conversation/evals/lints.yaml` gains a `closing_banned.*`
list (parallel to `banned.*`) and `lint.closing_declarative: on`.
`system/conversation_lints.py` gains `lint_closing_phrases(text, *,
config=None)` — checked ONLY against closing-turn text (these phrases are
often fine mid-conversation; only closing-turn narration is banned, so
they are never folded into the turn-wide `banned_phrases` lint).
`conversation_delivery.lint_outgoing` gains `is_closing: bool = False`;
`_deliver_closing` passes `is_closing=True`. The existing
`question_not_permitted` check (already active on `question_allowed=False`
closing calls) continues to enforce "no question at all."
`system/interaction_evals.py` gains golden property id
`closing_is_declarative` (checker: `kind == "closing"`, no `?` anywhere in
the text after echoed-question stripping, no `closing_banned` phrase) —
reusing `conversation_lints.lint_closing_phrases` as the single authority
(recurring-defect doctrine), not a re-implementation.

### 4. Reply-after-close routing

`conversation_delivery.py` gains `find_last_closed_session_for_channel`
(mirrors `find_open_session_for_channel`'s shape, filters
`status="closed"`, "newest" by `_last_activity`). `route_message` computes
this only when no open session exists, and:

- **Deterministic default-fallback** gains a new rung between "open
  session → `continue_session`" and the terminal `ask_user`/`new_story`
  fallback: a recently-closed session on this channel → `continue_session`
  (any age — "same day or later" is unconditional here, since this branch
  only fires when there is no live classifier to ask, and resuming a known
  subject is always safer than guessing `new_story`).
- **Model-classified branch**: the router prompt (`router.md`,
  `conversation.build_router_prompt`) gains a `RECENTLY CLOSED` signal so
  the model can weigh it like `SESSION OPEN`/`PENDING QUESTION`; router.md
  is updated to instruct the model to prefer `continue_session` over
  `new_story` when this signal is true, unless the message is
  unmistakably unrelated. **Same-day is a hard, structural override, not
  a model judgment call**: if the closed session's last activity is on
  the SAME calendar day as the inbound message, a `new_story`
  classification is overridden to `continue_session` regardless of model
  confidence — this is the unambiguous case the owner's ruling admits no
  exception for ("they're not talking about something else"). Multi-day
  ("or later") relies on the now-informed model's judgment plus the
  deterministic fallback rung above (which fires whenever no live
  classifier is available, at any age) — collapsing EVERY multi-day reply
  ever, forever, into forced `continue_session` would make `new_story`
  structurally unreachable on any channel that has ever once closed a
  session, which is a materially larger behavior change than the ruling's
  "reply to A closed chat/thread" framing supports. This distinction (hard
  same-day override vs. informed-model judgment for later) is a scoping
  judgment call made under "implement per the existing router structure";
  flagged here for owner visibility.
- `route_message`'s return dict gains `reopen_session_id` (the
  most-recently-closed session id to seed a NEW continuation from — never
  an append target; `conversation.append_turn` already raises
  `SessionClosedError` on a closed session by design, so "continuing" a
  closed subject always means opening a fresh session seeded with that
  subject's context, exactly like the platform's thread-composer pattern
  for a closed thread). `action` stays `"continue_session"` for this case
  — the router's job is classification; a new session's actual opening
  (seeded from the closed session's arc/question chain) is the same
  downstream mechanic that already opens a session when
  `find_open_session_for_channel` returns `None` for a story turn.
- CLAUDE.md / AGENTS.md / skill/SKILL.md's routing prose gains one line
  documenting `reopen_session_id`'s meaning for the host agent.

### 5. Research note (append-only)

`interactions/conversation/research/phase1-conversation-research.md` §2.4
("Endings are broken in human conversation") is the origin of "offer a
graceful exit" — the finding the exit-offer ceremony traced back to. A
dated addendum is appended immediately after §2.4 (before §2.5), recording
the owner's 2026-08-12 decision that reply-is-consent supersedes explicit
exit offers in a chat medium (the exit already exists as the absence of a
reply — explicit offers are ceremony that makes the surface narrate
itself) without altering a word of the original 2026-08-11 research text.

### 6. Docs trueing

`README.md` (two mentions: the engagement-multiplier paragraph's "chat's
exit-friendly turn" and the `conversation_delivery.py` table row's
"graceful third-exchange exit for Chats") reworded to the budget-silent
framing. `examples.md`'s closing example gains the owner's exemplary
witness/filing shape (paraphrased as a NEW synthetic example per the
file's own synthetic-only rule — the file already states "no references
to any real person's story"; behavior.md quotes the owner's real line
verbatim as the ratified rule text, which is a different, allowed context)
plus a BAD example demonstrating the banned meta-framing shape.

## Scope

**In**: behavior.md rule 8 rewrite; turn-instructions.md position enum;
`decide_turn_shape`/`_output_contract_block` exit-friendly removal;
closing-declarative lint (lints.yaml + conversation_lints.py +
conversation_delivery.py + interaction_evals.py); reply-after-close
routing (conversation_delivery.py + conversation.py's
`build_router_prompt` + router.md); research note; README/CLAUDE.md/
AGENTS.md/skill/SKILL.md doc trueing; goldens (declarative-close property
on the existing closing golden + one new synthetic witness/filing golden);
tests; version bump.

**Out**: platform PRs B/C (twin work, lifehug-platform); the monthly
`thread_offers` mechanism (unrelated); `exit_taken` as a `VALID_CLOSE_REASONS`
value (an explicit-stop close reason via a text command, e.g. a `command`
intent like "stop for today," is orthogonal to the removed visual/ceremonial
exit-offer step — it stays); any change to `close_session`'s payload shape
or idempotency contract; OSS wiki-viewer Chats-view rendering (issue #138,
separate).

## Test plan

- `tests/test_conversation_delivery.py`: replace
  `test_third_exchange_exit_shape_and_cap`'s exit-friendly assertions with
  assertions that the target-th and every later exchange share the same
  `past_target`-style question-free shape (no distinct position, no
  special copy); add `test_closing_with_a_banned_meta_phrase_is_never_sent`
  (mirrors the existing trailing-question test).
- `tests/test_conversation_router.py`: new `ReplyAfterCloseTests` —
  same-day reply after a close overrides a confident model `new_story`
  call to `continue_session` with `reopen_session_id` set; a later
  (multi-day) reply with no live provider resolves via the deterministic
  fallback rung to `continue_session`/`reopen_session_id` rather than
  `new_story`/`ask_user`; an unrelated `out_of_scope`/`command`
  classification is NOT overridden by a recently-closed session; a
  reopen-then-close-again integration scenario (open → close with a
  declarative takeaway → route a same-day reply → open the seeded
  continuation → close it again with its own declarative takeaway) —
  every generated close passes the new lint.
- `tests/test_interaction_evals.py` (existing suite; extended if the
  property vocabulary constant is asserted there) — confirmed at
  implementation time.
- Repo checks: `check_framework_files`, `check_version_bump`, scoped unit
  suites touched by this PR, `python3 -m unittest` targets — exit-code
  checked with `set -o pipefail`. No full-suite local run (sibling-agent
  rule).

🤖 Generated with Claude Sonnet 5 via Claude Code
