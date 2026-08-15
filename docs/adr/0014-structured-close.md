# ADR 0014: Structured close — {takeaway_prose, hook}, render only the prose

Date: 2026-08-15
Status: proposed

## Context

Issue #163, owner-hit live (staging, 2026-08-15): a conversation close
delivered the model's own scaffolding into the user's bubble — evaluation
commentary about the owner's conversational behavior ("I appreciated that
you pushed back… made this useful"), a continuity instruction addressed to
the *next session's model* ("Next time, pick up wherever things land — no
need to re-explain the setup"), and the hook rendered as a labeled
metadata field with unrendered markdown ("Hook for next time:
**"…"**"). The owner's read was exact: "it feels like a message to the
model" — parts of it literally were.

Three gaps, all at the interaction layer, made this possible even though
the close contract already asked for a takeaway plus a hook: (1) the
closing generation contract (`_closing_output_contract()`) asked for
`{"message": ..., "question_free": ...}` — a single free-text field with
no structural separation between what the USER reads and what the MACHINE
needs, so a weaker model could satisfy the letter of "include a hook" by
appending its own bookkeeping straight into the rendered message; (2)
`conversation_lints.py`'s closing checks banned exit-granting/narration
phrases (pure-chat wave, issue #139) but had no check for literal section
labels, second-person-model continuity instructions, or unrendered
markdown; (3) the goldens' `closing_has_takeaway_and_hook` /
`closing_is_declarative` properties asserted presence and declarative
shape, but nothing encoded "one statement, no labeled fields."

## Decision

**The close becomes structured output.** The closing generation contract
(`conversation_delivery._closing_output_contract()`, appended after
`conversation.build_closing_prompt()`'s behavior checklist) now asks for
exactly one JSON object: `{"takeaway_prose": str, "hook": str|null}`.
`takeaway_prose` is the complete, already-composed user-facing close — one
woven declarative statement (behavior.md rule 8: takeaway + specific
appreciation + continuity line + optional deposit-frame + hook, all woven
together, never labeled sections). `hook` is a separate, compact
next-thread label for MACHINE use only.

**The runtime renders ONLY `takeaway_prose`.** `parse_closing_output()`
(new, alongside the existing `parse_turn_output()` — the same
`_valid_message` structural-sanity check backs both, recurring-defect
doctrine) parses the object; `_deliver_closing()` sends `takeaway_prose` to
the channel and never touches `hook` for delivery. `hook` is instead
persisted additively on the session's close block (`close.hook`,
`conversation.close_session`'s existing schema is additive-only) — filed
only alongside an actually-delivered takeaway, ledgered alongside the
closing state-machine entry (`_write_outcome`'s new `hook` field) so a
replayed `close_session_now` call (the `already_confirmed` idempotency
path) reconstructs the identical close payload
`conversation.close_session`'s own idempotency check requires.

**Parse failure or lint failure on `takeaway_prose` degrades to the
existing silence path — never a raw-text fallback.** The pre-#163 code had
one: when `parse_turn_output()` failed to find valid JSON, it fell back to
treating the raw generation as the message via `_valid_message(generated)`
directly. That fallback is deleted for the closing path. A close that
isn't valid `{takeaway_prose, hook}` JSON is now, unconditionally, a
`malformed_generation` — the same silent-degradation status every other
closing failure path already returns. `takeaway_delivered` semantics are
unchanged: it is `True` only when a lint-clean `takeaway_prose` was
actually confirmed-sent.

**Four new lint classes, checked only on closing turns.**
`conversation_lints.lint_closing_phrases()` (already the sole closing-only
lint entry point, called by both `conversation_delivery
.lint_outgoing(is_closing=True)` and `interaction_evals
._check_closing_is_declarative`) gains, per issue #163's fix directions:

- `closing_label_leak` — literal labeled-field substrings ("Hook for next
  time:", "Takeaway:", "For next time:").
- `closing_meta_commentary` — case-insensitive regex patterns judging the
  conversation's own quality or the author's conversational behavior ("I
  appreciated that you…", "made this (actually )?(useful|productive)",
  "you pushed back"). Rule 8's required "specific appreciation" of what
  the person actually *shared* stays allowed and unflagged — the ban is on
  evaluating the *conversation*, not appreciating the *content*.
- `closing_future_turn` — instructions addressed to a future turn/session:
  a clause-initial "next time," + imperative shape (grammatical, so it's
  an engine constant — `_FUTURE_TURN_CLAUSE_RE`, same precedent as the
  existing `_PRESUPPOSING_RE`) plus literal phrases ("no need to
  re-explain") from `lints.yaml` data.
- `closing_markdown_leak` — a raw `**` emphasis marker; Telegram never
  renders markdown, so its presence is scaffolding, not formatting.

Patterns live in `evals/lints.yaml` (data); the engine stays generic —
same split as every other lint in this module.

**Goldens: one new PASS, one new (excluded) FAILURE fixture.**
`chat-porch-swing-closing.json` is a new, entirely synthetic PASS golden
demonstrating the woven form (both existing closing goldens already pass
the new checks unmodified — they never contained the leaked shape).
`closing-scaffold-leak-bad-01.json` reproduces the leaked SHAPE
(anonymized/synthesized — never the owner's real close or any vault
content) to prove the four lints actually trip; because it is deliberately
NOT a correct reference transcript, it is excluded from
`interaction_evals.load_goldens()`'s sweep via `NON_GOLDEN_FILENAMES`
(the same mechanism the router fixture files already use) rather than
required to pass `check_golden` — `tests/test_structured_close.py` loads
it directly.

**Platform riders (recorded, not implemented here).** The hosted runtime
executes this same definition (parity doctrine) — no platform-side patch
should re-implement these lints. At the next pin bump: the hosted close
path (`services/api/app/.../close.py`-equivalent) parses the same
`{takeaway_prose, hook}` structure and renders only the prose; Firestore's
`CloseInfo`-equivalent gains `hook` additively, mirroring
`close.hook` here.

## Consequences

- **Binds:** any future closing-generation caller uses
  `parse_closing_output()`, never `parse_turn_output()` — the two shapes
  are not interchangeable (`{takeaway_prose, hook}` vs. `{message,
  followup_question, ...}`), and a caller that mixes them would either
  silently drop the hook or misread ordinary-turn output as a close.
- **Binds:** any future writer of the closing ledger's `hook` field must
  go through `_write_outcome`'s `hook` parameter — the ledger entry is
  what makes a replayed `close_session_now` call idempotent.
- **Forecloses:** a closing generation ever satisfying "include a hook" by
  writing it into the rendered text as its own line, field, or paragraph —
  the hook has its own JSON slot now, and rendering it is itself banned by
  `closing_label_leak`.
- **Forecloses:** a malformed/unparseable closing generation ever reaching
  the user as raw text — the pre-#163 fallback is deleted, not narrowed.
- **Delete-when:** if the hosted platform's pin bump lands the
  `{takeaway_prose, hook}` parity rider and its own `close.hook` field,
  this ADR's "platform riders" paragraph should be marked implemented
  rather than recorded.

🤖 Generated with Claude Fable 5 via Claude Code
