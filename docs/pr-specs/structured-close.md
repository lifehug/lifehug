# Contract: structured-close

## Why

Issue #163, owner-hit live: a conversation close shipped the model's
scaffolding into the user's bubble — evaluation commentary about the
owner's conversational behavior, a continuity instruction addressed to
the next session's model, and the hook rendered as a labeled field with
raw `**` markdown. Three gaps: the close contract asks for
takeaway + hook without forbidding labeled rendering; the closing lints
police phrases, not structure; the goldens assert property presence,
not weave. Fix: the close becomes STRUCTURED — the model emits
`{takeaway_prose, hook}`, the runtime renders ONLY the prose and files
the hook into session state — with lints and a golden failure case so
no seated model can ship scaffolding again.

## Binding facts (as of origin/main v176)

- Close doctrine: v162 pure-chat close (ADR 0005-conversation-close /
  behavior.md rule 8): ONE declarative statement; never exit-granting,
  trailing questions, or meta-framing. Golden properties:
  `closing_has_takeaway_and_hook`, `closing_is_declarative` (v166).
- Prompt builders: `system/conversation.py` (the four builders incl.
  closing; `parse_ai_json` convention lives in research_expand).
- Close engine: `system/conversation_delivery.py` —
  `close_session_now()` (takeaway-or-silence; user_turns >= 2 criterion;
  `takeaway_delivered`; Mirror inbound filing; coalesced compile/commit),
  degrade paths never worse than silence.
- Lints: `system/conversation_lints.py` reading
  `interactions/conversation/evals/lints.yaml` (never locally pinned
  numbers); enforced by the turn engine AND the eval harness
  (`system/interaction_evals.py`, `conversation-evals`).
- Session docs: `state/conversations/<id>.json`, `CloseInfo`-equivalent
  close block (schema additive).
- The handbook embeds behavior.md byte-exact
  (tests/test_handbook_parity.py EmbedParityTests) — editing behavior.md
  REQUIRES updating the handbook page's embed block in the same PR or
  the embed test fails (this is by design).
- Version bumps to next free above origin/main at PR time (expect 177).
  21 pre-existing env failures in this workspace; zero delta; CI
  arbiter.

## Scope

1. **Structured close output**: the closing turn-instructions template
   instructs the model to emit ONLY a JSON object
   `{"takeaway_prose": str, "hook": str|null}` — takeaway_prose is the
   complete user-facing close (1–3 declarative sentences, hook woven in
   naturally when one exists), hook is the compact next-thread label for
   MACHINE use. Runtime (`close_session_now` + any other close path):
   parse via the existing JSON-parsing convention; deliver ONLY
   takeaway_prose; persist hook additively on the session's close block
   (`close.hook`). Parse failure or lint failure on takeaway_prose →
   existing silence degradation (never deliver unparsed text; never
   worse than the pre-existing failure behavior). `takeaway_delivered`
   semantics unchanged.
2. **behavior.md close rule amendment** (rule 8 extension): the close
   is one woven statement; NEVER labeled fields ("Hook for next time:",
   "Takeaway:"), NEVER commentary on the conversation's quality or the
   author's conversational behavior ("I appreciated that you…", "that
   made this useful"), NEVER instructions to a future turn or session
   ("next time, pick up…", "no need to re-explain"). Continuity is the
   machine's job via the structured hook. UPDATE THE HANDBOOK EMBED
   (docs/handbook/interactions/conversation.md) in lockstep.
3. **New lints** (conversation_lints.py + evals/lints.yaml, applied to
   the DELIVERED takeaway_prose and to closing goldens): (a)
   label-pattern ban (case-insensitive: "hook for next time",
   "takeaway:", "for next time:"); (b) meta-commentary patterns ("i
   appreciated that you", "made this (actually )?(useful|productive)",
   "you pushed back"); (c) future-turn instruction shapes
   (clause-initial "next time," + imperative; "no need to re-explain");
   (d) raw markdown emphasis leak (`**`) in channel-delivered text.
   Patterns live in lints.yaml (data), the engine stays generic.
4. **Goldens**: one new golden FAILURE case — an ENTIRELY SYNTHETIC
   close reproducing the leaked SHAPE (labeled hook field, eval
   commentary, self-instruction, `**`) — asserted to trip the new lints;
   one new golden PASS case showing the woven form with a structured
   hook in the session doc. NEVER copy the owner's real close text or
   any vault content — synthesize.
5. **ADR 0014**: structured close output — the {takeaway_prose, hook}
   contract, the render-only-prose rule, degradation, the lint classes,
   and the platform riders (the hosted close path in
   services' close.py parses the same structure; Firestore CloseInfo
   gains `hook` additively; rides the next pin bump — record, don't
   implement).
6. Version bump + changelog; framework_files for any new shipped file;
   `conversation-evals` lints layer green with the new rules; the
   handbook embed updated so EmbedParityTests stays green.

Out: platform implementation (pin-bump riders per ADR) · reseating
models (the updated harness decides at next seating) · any change to
turn (non-close) behavior.

## Test plan

`tests/test_structured_close.py` (new): closing prompt requests the
JSON shape; parse+deliver renders only prose; hook persists on the
close block; parse-failure → silence (nothing delivered, session still
closes, compile/commit coalescing unaffected); lint-failure on prose →
silence; each new lint pattern trips on the synthetic bad close and
passes on the woven good close; `**` leak caught; existing
close-behavior tests updated where they pinned free-text closes.
`conversation-evals` run (keyless layers) green. Full suite zero delta
vs the 21-failure baseline. Walkthrough not required (no serve_wiki
visible-surface change) — evidence = the closing prompt excerpt + a
real keyless close run's session doc showing close.hook, pasted.

## Definition of done

Per TEMPLATE.md: version bump, ADR 0014, behavior.md + handbook embed
in lockstep, lints.yaml data-driven, goldens both ways, evidence
comment, platform riders recorded. Closes #163.

🤖 Contract authored by Claude Fable 5 via Claude Code
