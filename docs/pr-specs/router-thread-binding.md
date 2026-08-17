# Contract: router-thread-binding (the binder model — PR B of platform #490's Thread Binder)

## Why

Owner-designed (2026-08-17, platform issue #490 + its ratified design
comment — read both first). When a channel user has MULTIPLE live
question threads in one undifferentiated stream (Telegram), the router
must decide not only WHAT an inbound message is (intent) but WHERE it
belongs (which thread). The 2026-08-16 platform incident scattered one
conversation across five sessions. The platform's deterministic ladder
(platform PR #492) handles zero-or-one-thread days and native replies;
THIS PR gives the router the binding judgment for genuine multi-thread
ambiguity — one low-tier structured call, classify+bind unified, never
a second model call.

## Binding facts (verify against origin/main, v179 f12c6a8)

- The router interaction: `interactions/conversation/router/router.md`
  (Intents / Default-class rule / Output schema / Unsure-fallback) —
  the rubric IS the prompt.
- The prompt builder: `system/conversation.py` `router-prompt` mode —
  stdin JSON `{message, session_open, pending_question_id}`; the
  platform replays it via a scrubbed subprocess (pinned seam) and
  parses strict JSON `{intent, confidence}` against the closed intent
  vocabulary (5 intents) and `knob.router_confidence_threshold`
  (default 0.7).
- Evals: `interactions/conversation/evals/goldens/router_fixtures.json`
  (20 × `{"text","session_open","intent"}`),
  `router_sample_predictions.json` (parallel), gates as flat keys
  `router_gates.*.{precision,recall}` in `evals/lints.yaml`; the
  keyless harness (`system/lifehug.py conversation-evals`) skips
  live-model layers; `evals/roster.md` seats no model yet. The
  platform mirrors these assets by path
  (tests/llm/test_interaction_evals_parity.py) — additive changes
  only, keep every existing path/shape valid.
- interaction.yaml is flat-scalar-only; conversation BEHAVIOR rule
  numbers 1–13 are frozen and OUT of scope here (router.md is a
  separate document with its own structure).
- Version = next free (expect 180); changelog is a STRING; ADR = next
  free number; handbook embeds are byte-locked (EmbedParityTests) — if
  any embedded file changes, update the handbook page in lockstep.
- Owner privacy rule: goldens are SYNTHETIC — no real vault content.

## Scope

1. **Roster input (additive, backward-compatible).** `router-prompt`
   stdin gains optional `threads`: a bounded list (top-K small; new
   knob `router_roster_max`, default 6) of compact candidates
   `{"id", "question", "last_exchange", "awaiting_ask"}` — id is an
   opaque thread id, question is the thread's current question text,
   last_exchange is a short tail snippet, awaiting_ask marks a thread
   whose last turn is an unanswered ask. Absent/empty `threads` ⇒
   prompt and output BYTE-IDENTICAL to today (the platform's
   deterministic ladder only invokes the model rung with ≥2
   candidates; every existing caller keeps working unchanged).
2. **Binding output (additive).** The output schema gains
   `target`: one of the roster ids, `"new"`, or null (null = no
   binding judgment / no roster given). Intent vocabulary UNCHANGED.
3. **router.md rubric — the binding doctrine**, in the owner's design
   terms: binding says WHERE the message lands, intent says WHAT it
   is; the roster is the CLOSED set of targets; continuity is the
   default — when unsure, target the most recently active thread;
   NEVER invent a thread ("new" only for a message that plainly starts
   something none of the threads contain); a message engaging a
   thread's awaiting ask targets that thread even when a newer thread
   exists; meta-messages ("anything else?", "next question") target
   the thread the user is currently in, with intent carrying the
   request.
4. **Parse/validation + local honoring.** The output parser accepts
   the additive field (strict: target must be a roster id, "new", or
   null; invalid target ⇒ treat as null, never discard the intent).
   OSS local channel routing honors `target` where it routes inbound
   channel messages to sessions (find the routing site; if OSS's
   single-open-session model makes it a no-op today, wire it
   pass-through and record that in the ADR — the platform is the
   first full consumer).
5. **Goldens + gates.** Extend `router_fixtures.json` (additive; keep
   all 20 existing rows valid) with roster-bearing synthetic cases:
   (a) the incident replay as stepwise fixtures — delivered-question
   thread, answer, "next question" meta-message, held-ask reply that
   redefines a term, clarification, "do you not remember?" — each
   asserting the single correct target; (b) a genuine bounce back to
   an older thread by content; (c) awaiting-ask precedence over
   recency; (d) unsure ⇒ most-recent; (e) no-roster back-compat row.
   `router_sample_predictions.json` extended in parallel. New flat
   gate keys for binding accuracy alongside the existing
   `router_gates.*` style. The keyless harness must validate the new
   shapes and still skip live layers cleanly.
6. **ADR** (next free number): the Thread Binder — sessions are
   threads, binding≠intent, the closed-roster contract, continuity
   default, the platform ladder relationship (deterministic rungs
   first, model rung only on real ambiguity), and the tier decision
   (routing-class work on the low tier per the owner's model-tier
   guide).
7. Version bump + changelog; tests for prompt construction both ways
   (with/without threads), parser strictness, fixture schema; zero
   delta vs the environment's pre-existing failure baseline; flag any
   new platform-reconciliation surfaces (fixtures paths, knob, output
   field) prominently in the evidence comment for the pin bump.

Out: any conversation behavior-rule change · intent vocabulary
changes · platform wiring (rides the next pin bump, platform PR C) ·
seating a model in roster.md · threaded/reply-to SENDS.

## Owner closeout template

Judge: (1) the continuity-default rubric wording; (2) "never invent a
thread"; (3) the roster size knob default (6).

🤖 Contract authored by Claude Fable 5 via Claude Code
