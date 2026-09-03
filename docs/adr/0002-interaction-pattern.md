# ADR 0002: The Interaction pattern for AI-driven surfaces

Date: 2026-08-11
Status: proposed

## Context

The conversation surface — the exchange where a person tells their life to
the system — was three disconnected mechanisms with no shared design: a
warm acknowledgment that, in its earlier form, returned literally "No
questions back" with no follow-up logic behind it; follow-up generation
unrelated to what came before it in the same thread (issue lifehug#99
records the owner's words on this — follow-ups need to read as
conversation, not as three unrelated prompts stapled together); and story
ingest (`ingest_story.py`) that returned nothing back to the user at all.
None of the three shared a behavior contract, a research basis, or an eval
gate, so improving one did nothing for the others and there was no single
place a reviewer or a future contributor could go to see "why does the
system talk this way."

The 2026-08-11 owner-approved design (four research phases: what makes
conversations great, the payout turn, elicitation craft, and the
interaction architecture itself — all committed under
`interactions/conversation/research/`) makes the conversation surface a
designed **Interaction** instead: a portable, versioned, eval-gated role
definition, rather than three ad hoc mechanisms sharing no research or
rules.

## Decision

(a) **`interactions/` is a new top-level framework-owned directory**
holding model-agnostic role definitions. Each interaction is split into
Definition (the files, OSS, versioned, PR-reviewed — the behavior
authority), Runtime (loader code per side: the OSS single-user runtime and
the hosted platform's vendored equivalent), and Seat (which concrete model
plays which role, decided by config and gated by an eval harness). The
behavior contract lives entirely in portable prompt and context files; any
verified provider-specific delta goes in `overlays/<provider>.md` only,
never in the core files. A model is seated only after its outputs pass the
interaction's `evals/` harness.

(b) **The code reflects the ratified nomenclature**: Interaction, Chat,
Conversation, Arc card, Session (defined in `interactions/README.md`,
`interactions/conversation/README.md`, and the top-level `README.md`
Nomenclature section). Alternative shapes considered and rejected: keeping
the three mechanisms separate and improving each independently (rejected —
this is exactly the shape that produced the disconnected behavior in the
first place, since nothing forced them to share rules); building a single
monolithic prompt file instead of the definition/runtime/seat split
(rejected — it would re-couple the prompt to one runtime's mechanics and
make the eventual multi-model, multi-runtime requirement a rewrite instead
of an extension).

(c) **Planned vault-contract additions**, landing in issue #115 (not this
PR): data paths `arc_cards` (`state/arc_cards.json`), `conversations`
(`state/conversations/`, a directory of session documents), and
`mirror_responses` (`state/mirror_responses.json`); and a framework path,
`interactions`, so the interaction definition itself ships to existing
vaults on upgrade like any other framework-owned file.

(d) **The daily loop remains AI-free.** Arc generation lives in the weekly
loop (`plan/arc-templates.md`); the daily loop only attaches an
already-planned card to the outgoing question. This is the ratified
deviation from the design's original decision C, which would have allowed
daily-loop arc generation — the owner reversed that in favor of keeping
the free, no-API-key daily run exactly as free as it is today.

## Consequences

- **Binds**: new interactions follow this pattern (see
  `interactions/README.md`'s new-interaction checklist) — a future
  AI-driven surface that skips the definition/runtime/seat split or ships
  without an eval harness is a design defect, not a valid shortcut.
  Behavior changes to the conversation surface go through
  `interactions/conversation/` and its evals, not through ad hoc edits to
  a runtime's prompt strings. Both runtimes load the same definition and
  may not diverge on router classification, knob values, or hard rules —
  a runtime-side divergence from the definition is a runtime bug, not a
  legitimate platform variant.
- **Forecloses**: platform-side forks of conversation behavior (the
  hosted platform consumes the definition via the framework pin, per
  design §11 item 0 — it does not maintain its own copy of the behavior
  contract); model-specific tricks in core prompt/context files (verified
  provider deltas belong in `overlays/` only, and only once actually
  verified — not speculative).
- **No delete-when condition**: the pattern is expected to be reused for
  every future AI-driven surface, not just this one; it would only need
  revisiting if the definition/runtime/seat split itself proved
  unworkable in practice, which nothing in this PR's scope tests.

## Amendment (2026-08-11, issue #118): the arc-card contract

The vault-contract addition above ((c), landed in #115) reserved
`state/arc_cards.json`; the weekly arc planner (#118) fills it, and this
amendment ratifies the DATA contract everything downstream inherits, so
there is one findable answer rather than a second ADR.

- **The intent vocabulary is CLOSED** — exactly seven kinds (six until
  v200): `scene_slot`, `neighborhood_sibling`, `timeline_gap`,
  `studio_slot`, `sit_with`, `demonstrated_knowledge_summary`,
  `place_no_stories`. `conversation.ARC_INTENT_KINDS` is the
  single definition; the turn engine, the evals, and the platform's
  transport all read it from there. Adding a kind is a schema bump, not an
  additive change (per the recurring-defect doctrine: one importable
  definition, guarded by a test, rather than a vocabulary retyped at four
  call sites).
- **Intents are intents, not scripts.** A card carries 2–4 typed objects
  naming what the exchange should reach for; the turn engine phrases them
  live. The card never contains scripted follow-up text.
- **Cards live and die with the question queue.** `queue_generated_at` and
  `expires_at` are copied verbatim from `state/question_queue.json`, and a
  card is live only while unexpired AND its question is still queued or
  sent. Staleness therefore needs no expiry code of its own: nothing
  attaches, and the day degrades to the pre-arc message format.
- **Openings are receipted or null.** An opening cites `opening_receipts`
  that must resolve to real answers/sources; an unresolvable receipt costs
  the card its opening, never its intents. No card text may contain "what
  year" (research.md §4's landmark-anchor rule, enforced as a validation
  lint).
- **The OSS weekly shell step is the parity SPEC** for the platform's
  `StepSpec("arcs", "arc_plan", llm=True)`. A cap, gate, or fallback that
  the platform needs must appear in `system/weekly_maintenance.sh` and the
  CLI first; a platform-side gate absent from the OSS step is a parity
  merge-blocker on the platform PR.
- **Ratified deviation (d) is now load-bearing, not aspirational**: the
  daily attach is a pure file read (`lifehug.py arc-card <QID>
  --daily-text`) that prints the assembled message or nothing at all, so
  the daily loop's AI-free property is enforced by the seam's SHAPE, not
  by convention.

## Amendment (2026-08-23, v200): the seventh kind, `place_no_stories`

The bump is taken deliberately, with its rationale recorded here so a later
reader does not have to reconstruct it. v199's landmark set is the first
thing that can tell us about a place *nothing in the vault happened in* — "I
lived in Costa Mesa" with a known span and no moments attached. The owner's
ruling (lifehug/lifehug-platform#590) is that this is new information the
system could not see before the landmark, and therefore a gap the loop
should ask about.

It has no other lane. It is not a `timeline.UNKNOWN_KINDS` member — it asks
WHAT, not WHEN, and the dating ledger must not count it — and it is never
minted as a bank question, because an open landmark is a resting state, not
a debt. Reusing `timeline_gap` was rejected: one kind meaning two different
asks would make `question_judgment.arc_yield()` unable to tell the two
apart, which is precisely the signal the weekly rubric edit reads.

Two bounds keep it from becoming a second machine: it takes the SAME
`arc_planner.DEFAULT_GAP_MAX` budget as the timeline whisper (no second
dial), and it is ranked after `timeline_gap` for the card's single gap slot
— a conversation carries at most one second agenda.

## Amendment 2026-09-03 (owner ruling R2): landmarks may enter the queue by value

**Amendment 2026-09-03.** The clause above — a `place_no_stories` aside, like
any landmark question, "is never minted as a bank question" — is superseded
on queue eligibility only. Owner ruling R2 (`lifehug-platform docs/decisions/2026-09-03-timeline-unification/decision-record.md`)
rules that landmark and timeline questions may enter the daily queue, and may
surface as whispers, when they pass the shared value threshold; they are
evaluated by value, not by ladder completion. What stays: an open landmark is
a resting state, not a debt; it never nags, never sends a reminder, and never
appears as a count. The `DEFAULT_GAP_MAX` budget and the single gap slot per
card are unchanged. Lands in Cut 5b (tracking #573/#586). The text above is
kept as history.
