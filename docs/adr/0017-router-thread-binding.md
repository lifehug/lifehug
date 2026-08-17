# ADR 0017: Router thread binding — the binder model

Date: 2026-08-17
Status: proposed

## Context

Issue #169 is PR B of the Thread Binder design ratified on platform issue
#490 (design comment, 2026-08-17). The 2026-08-16 platform incident
scattered one conversation across five sessions: on a channel like
Telegram, a user can have MULTIPLE live question threads open in one
undifferentiated message stream, and the pre-#490 router only ever
decided WHAT an inbound message was (`intent`) — never WHERE it belonged.
Platform PR A (the deterministic ladder: same-day roster, native-reply
binding via `provider_msg_id`, the single-thread fast path) resolves the
overwhelming majority of days without a model call at all; this PR gives
the router the judgment for the genuine multi-thread ambiguity that's
left — one low-tier structured call, classify+bind unified, never a
second model call (owner ruling: routing-class work stays on the low
tier per the model-tier guide).

## Decision

`interactions/conversation/router/router.md` — the one definition both
runtimes already share for intent classification (ADR 0004) — gains an
ADDITIVE binding extension, never a fork: an optional `threads` roster in
the runtime INPUT (bounded by the new `knob.router_roster_max`, default
6) and an additive `target` field in the output schema (a roster id,
`"new"`, or `null`). Binding rules live in the SAME file as the intent
taxonomy, in priority order: awaiting-ask precedence beats recency,
content match beats roster position (the genuine bounce), meta-messages
target the thread the user is currently in, continuity is the default
whenever binding is unsure, and `"new"` is a last resort — never a hedge
for "unsure." The roster is a CLOSED set: the model may never invent a
thread id outside it.

Absent or empty `threads`, the rendered prompt and the parsed output are
BYTE-IDENTICAL to pre-#169 behavior (`conversation.build_router_prompt`'s
roster block only renders when `threads` is non-empty; `target` is
always `null` with no roster). `conversation_delivery._parse_router_output`
validates `target` strictly against the CALLER's own roster ids (passed
per-call, since the valid set is per-request, not a fixed vocabulary like
the five intents) — an invalid or hallucinated target degrades to `null`
and NEVER discards the classified `intent`; a below-threshold or
provider-unavailable fallback also reports `target: null` (an honest "no
binding judgment," never a guess bolted onto the deterministic default
path, which OSS's `route_message` never attempts to resolve on its own).

`route_message` accepts `threads` and returns `target` as a pure
pass-through — OSS's single-open-session-per-channel model
(`find_open_session_for_channel`) has nothing to bind MULTIPLE candidates
INTO today, so there is no OSS-side routing behavior change; the value is
reported for a caller to use, never consumed internally to redirect which
session an inbound message appends to. The hosted platform (PR C, rides
the next pin bump) is the first full consumer — it has the multi-thread
day model this binds against.

The eval harness extends in the same additive shape: `router_fixtures.json`
and `router_sample_predictions.json` gain an optional `threads`/`target`
(fixtures) and `predicted_target` (predictions) pair, all synthetic
(invented people/topics — a lighthouse, a garden, a porch, a bakery, a
road trip — never anything resembling the owner's real vault); a new
`interaction_evals.score_binding_predictions` scores binding accuracy
over ONLY the threads-bearing rows, shaped identically to
`score_predictions`'s per-class dict so the existing generic
`check_router_gates` enforces the new `router_gates.binding.accuracy`
gate (lints.yaml) unchanged — no second gate-checking function
(recurring-defect doctrine).

Alternatives considered. *A second model call dedicated to binding*:
rejected — the design comment is explicit that this is one structured
call, classify+bind unified; a second call doubles latency and cost for
a judgment cheap enough to fold into the first. *A separate binding
vocabulary/gate file*: rejected — reusing `router_gates.*`'s flat-key
mechanism and `check_router_gates`'s generic class/metric matching avoids
inventing parallel machinery for what is structurally the same kind of
threshold gate. *Resolving "unsure" binding inside OSS's own
`route_message` (picking a fallback target when the model doesn't)*:
rejected for this PR — OSS has no multi-thread roster of its own to
resolve INTO, so inventing that resolution logic here would be dead code
until the platform is the consumer; the model's own continuity-default
instruction (rule 4 in router.md) is the doctrine, and the runtime that
actually has multiple candidates (the platform) is where a fallback
resolution belongs.

## Consequences

- **Binds:** any change to the binding rules, the roster shape
  (`{id, question, last_exchange, awaiting_ask}`), or the closed-target
  contract (`target` ∈ roster ids ∪ `{"new", null}`) is made in
  `router.md` + `interaction.yaml`, never independently in
  `conversation.py`, `conversation_delivery.py`, or a runtime's own
  prose — the same non-divergence rule ADR 0004 already established for
  intent classification.
- **Binds:** `build_router_prompt` must keep the byte-identical guarantee
  for absent/empty `threads` — this is the mechanism that makes the
  extension genuinely additive for every existing caller, tested directly
  (`test_absent_threads_is_byte_identical_to_no_threads_key_at_all`).
- **Binds:** `_parse_router_output`'s target validation is always
  per-call against the CALLER's roster, never a fixed global vocabulary —
  a caller must pass its own `threads` (or the roster ids derived from
  them) to get correct strictness; there is no way to validate `target`
  without knowing what roster produced it.
- **Forecloses:** OSS route_message silently picking a "most recent"
  fallback target on its own — that resolution logic belongs to whichever
  runtime actually holds a multi-thread roster (the platform), not to
  this pass-through.
- **Delete-when:** if the platform's PR C wiring (the next pin bump)
  surfaces a shape mismatch in `threads`/`target`/`knob.router_roster_max`
  against what it actually needs, this ADR is amended — the closed-set
  contract and the additive-only guarantee are the load-bearing parts,
  not the exact field names.

## Platform pin-bump reconciliation surfaces

Flagged for the platform's next pin bump (contract, Scope 7):

- New knob: `knob.router_roster_max` (`interaction.yaml`, default 6).
- New output field: `target` (`router_output` schema — roster id, `"new"`,
  or `null`).
- New optional input field: `threads` (`router-prompt` stdin JSON — list
  of `{id, question, last_exchange, awaiting_ask}`).
- New golden-fixture fields: `threads` + `target`
  (`router_fixtures.json`), `predicted_target`
  (`router_sample_predictions.json`) — additive, existing rows unchanged.
- New gate key: `router_gates.binding.accuracy` (`evals/lints.yaml`).
- `route_message`'s return dict gains `target` (always present, `null`
  when no binding judgment applies).

🤖 Generated with Claude Fable 5 via Claude Code
