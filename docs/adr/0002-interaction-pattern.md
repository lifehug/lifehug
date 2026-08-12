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
