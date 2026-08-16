# ADR 0015: Content-first close — the builder reads the conversation, starved closes refuse

Date: 2026-08-16
Status: proposed

## Context

Two owner-hit live incidents in two days, one audited root cause:
`system/conversation.py::build_closing_prompt()` had never seen the
conversation. Since the pure-chat wave (issue #139) it read only
`session["mode"]` and `session["rolling_summary"]` — a field the hosted
platform never writes at all, and that, even when written, never contains
the message actually being replied to. Every model-generated close was
therefore starved of the one thing it needed:

- **Issue #163 (2026-08-15)**: the starvation presented as confabulation.
  With nothing real to work with, the model invented claims about the
  author's own conversational behavior ("I appreciated that you pushed
  back a couple of times") plus assorted scaffolding leak. ADR 0014 fixed
  the *format* — the close became structured `{takeaway_prose, hook}`,
  rendering only the prose — and that fix held perfectly.
- **The platform incident (2026-08-16)**: post-#164's format fix, the same
  starved builder produced an honest, well-formed close — describing
  emptiness ("showing up with nothing yet to say") — delivered to a person
  who had, in the same session, just written a three-hundred-word memory.
  The format was clean; the content was a lie by omission, because the
  builder was never given the memory to respond to.

ADR 0014's format contract was necessary but not sufficient: it disciplined
*how* a close is shaped, but the builder still had nothing true to shape.
The actual defect was one level upstream, in what `build_closing_prompt`
was given to look at.

## Decision

**Fix A — the builder reads the conversation.** `build_closing_prompt`
now assembles a real transcript from `session["turns"]`:

- The **FINAL USER TURN** — the last turn with `role: user` — is included
  **verbatim, never truncated, regardless of length or any budget**. It is
  the reason a reply is owed, and truncating it away is exactly the defect
  this ADR closes.
- **Recent preceding turns** are included within a new manifest budget,
  `budget.closing_transcript` (`interaction.yaml`, flat dotted key,
  default 1200 tokens — sized like the turn prompt's own `budget.session`
  transcript allowance). When the window is tight, the **oldest** turns
  yield first; the most recent context survives.
- **`rolling_summary`, when non-empty**, is still included, as older
  context the recent-turns window dropped — additive, never a substitute.

The instruction hierarchy is rewritten in the same spirit as behavior.md
rule 8's existing "respond before you ask" doctrine: the close now
explicitly **responds to the final message first** — the same receipt and
payout an ordinary turn would give it — and lets that response settle into
the single woven takeaway. A close that ignores what was just said is
named, in the prompt itself, as a defect.

**Fix B — the starvation guard.** `build_closing_prompt` now **raises**
(`conversation.ConversationPromptError`, a new member of the existing
`ConversationError` family) when the session has no user turns **and** no
non-empty rolling summary. It never emits a prompt that asks a model to
appreciate nothing — the shape of failure both incidents actually took.

The engine (`conversation_delivery._deliver_closing`) degrades per a
two-class table, keyed on `close_session_now`'s own close `reason`
(`SWEEP_CLOSE_REASONS = {"idle_timeout", "day_rollover"}` vs. everything
else):

| Call class | Trigger | Degradation |
|---|---|---|
| **Live, budget-reached closing beat** (`reason` = `done` / `exit_taken`) | A present person; the close attempt found nothing to close on | Fall back to an **ordinary, question-free turn** via `conversation.build_turn_prompt` (`_deliver_starvation_fallback_turn`) — the person gets a real reply. The close itself is deferred; `close_session_now` leaves the session **open** rather than force-closing it. "The thread lands another day." |
| **Sweep / idle / day-rollover close** (`reason` = `idle_timeout` / `day_rollover`) | No person necessarily present | The existing **silence** path (no takeaway delivered) — the session still closes cleanly, nothing is sent. |

This table is defense-in-depth as much as it is a live path:
`close_session_now`'s own pre-existing `user_turns >= 2` gate means a
genuinely empty session cannot reach `_deliver_closing` through today's
call sites at all (two-or-more user turns already imply content). The
guard and its degradation table exist so that fact is enforced
structurally — by the builder refusing and the engine handling the
refusal correctly — rather than merely being true by accident of today's
call graph, which is exactly the kind of assumption that broke twice
already.

**Fix E — behavior.md rule 8 amendment.** Rule 8 gains a prime-directive
opening sentence and the respond-first clause, matched verbatim into
`build_closing_prompt`'s own instruction checklist: *"this surface speaks
only about the author's own content, to the author — a turn with no
content to speak about is silence, not invention, and a close earns no
exception."* The handbook's byte-exact embed
(`docs/handbook/interactions/conversation.md`,
`tests/test_handbook_parity.py`'s `EmbedParityTests`) moves in the same
commit.

**Fix D — evals.** One new golden PASS, `chat-seattle-ferry-closing.json`:
a several-hundred-word final user message (the incident's own shape) that
the closing turn visibly engages, declaring a **new** golden property id,
`closing_engages_final_message` (`system/interaction_evals.py`) — checked
via distinctive-token overlap between the closing turn's text and the
final user turn, a concrete and simple verifiable signal rather than a
judge-layer quality call. A new deterministic test (not a golden) proves
an empty-session close refuses at the builder and the engine goes silent.

## Consequences

- **Binds:** any future closing-generation call site goes through
  `build_closing_prompt`'s transcript assembly (never re-derives "what did
  the user just say" independently) and, if it wraps generation, must
  handle `conversation.ConversationPromptError` per this ADR's degradation
  table rather than letting a starved prompt reach a model.
- **Binds:** a new manifest `budget.*` key follows the same flat-scalar,
  `interaction.yaml`-documented convention as every other budget — see
  `context/manifest.md`'s new "Closing prompt assembly" section.
- **Forecloses:** a closing prompt ever being built from `mode` +
  `rolling_summary` alone — the exact shape that produced both incidents.
- **Forecloses:** a starved session ever reaching a model for a closing
  generation — the guard raises before any `call_ai` invocation happens.
- **New golden-property vocabulary — FLAGGED for the platform pin bump.**
  `closing_engages_final_message` is new as of this PR. The platform
  mirrors the property vocabulary in a closed set (contract, "Binding
  facts"); this id must be reconciled into the platform's copy at the next
  pin bump, alongside the ADR 0014 riders below that are still recorded
  and not yet implemented.

### Platform riders (recorded, not implemented here — out of scope)

The hosted platform executes `build_closing_prompt` **verbatim** via
subprocess REPLAY (`conversation_prompt.py`), passing a projection whose
`turns` are already populated — so Fix A and Fix B flow to hosted
automatically through the next pin bump, with **zero platform prompt
logic** required. Three riders remain platform-side work, all recorded
here rather than implemented in this OSS PR:

1. **Blocking posture for the close class.** The platform's lint posture
   for closing generations is currently ADVISORY (per the #163 audit); it
   should become BLOCKING for the close class specifically, mirroring the
   OSS engine's `lint_outgoing(..., is_closing=True)` gate — a rider
   carried since ADR 0014 and still open.
2. **Golden-vocabulary reconciliation.** `closing_engages_final_message`
   (this ADR) needs a matching platform-side property/check at the next
   pin bump, alongside anything still outstanding from ADR 0014's own
   rider list.
3. **A regression test from this incident's own reproduction** — the
   platform should carry a fixture derived from the 2026-08-16 incident
   shape (long final message, summary-only builder previously starved) so
   a future pin bump cannot silently reintroduce this defect class on the
   hosted side.

### Delete-when

This ADR's "platform riders" section should be marked implemented, not
merely recorded, once the next pin bump lands all three items above.

🤖 Generated with Claude Fable 5 via Claude Code
