# Turn instructions — two task templates, assembled LAST

This file is assembled last in the per-turn context order (see
`context/manifest.md`), after identity, behavior, learned amendments,
examples, and the profile-distillate block. Everything durable — persona,
rules, priority/penalty vocabulary — lives in `prompt/identity.md` and
`prompt/behavior.md`, not here. `{placeholder}` slots are filled by the
runtime's builder — this PR ships the templates only; no filling logic
exists yet (the wiring PR implements the builder against these exact
placeholders).

There are exactly two modes (`interaction.yaml`'s `modes: judge|rubric_edit`).
A turn is always one or the other, never both.

---

## Mode: JUDGE (per-candidate, `role.worker`)

Runs once per generated candidate question, at capture time (the learning
architecture's "score once" step — see `README.md` §4).

**Input:**
- `{candidate_text}` — the candidate question's exact text.
- `{provenance}` — where it came from: source id(s), story_function, the
  scene-slot or gap it claims to target if any.
- `{profile_bucket}` — a short distillate of relevant profile signal (e.g.
  "Ohio period: 2 answers, no typical-day texture" or "no signal — profile
  below activation threshold"), never the whole quality profile.

**Task:** Apply `prompt/behavior.md` in full — the mission test first, then
hard rules 1–11, then (only for candidates that pass both) the priority
vocabulary. Output a single JSON object, no prose outside it:

```json
{
  "verdict": "accept|reject",
  "priority": 0.0,
  "evidence": "one or two sentences citing the specific band-justifying evidence per prompt/behavior.md's priority vocabulary",
  "flags": [],
  "purposes_served": []
}
```

- `verdict: "reject"` is required whenever the mission test fails OR any
  hard-rule penalty flag applies (rules 1, 3, 8, 10 have flag-bearing hard
  fails per the penalty vocabulary). A rejected verdict still names its
  `flags` but omits `priority` (or sets it `null` — the loader must not
  treat a rejected verdict's absent priority as a defect).
- `priority` is present and in-band (`knob.priority_floor`–
  `knob.priority_ceiling`) on every `"accept"` verdict, never on a
  `"reject"` one.
- `flags` uses the penalty vocabulary's exact names — see
  `prompt/behavior.md`'s penalty table. Empty list is the common case for
  an accepted candidate.
- `purposes_served` names which of the three mission purposes apply —
  `["understand_others"]`, `["tell_story"]`, `["understand_self"]`, or any
  combination — this is what the "serving more than one purpose" evidence
  (`prompt/behavior.md`) actually points at.

## Mode: RUBRIC-EDIT (weekly, `role.planner`)

Runs at most once per week, and only when there is a genuine, cited pattern
in the week's deltas — not on a fixed schedule regardless of signal.

**Input:**
- `{week_delta_summary}` — which judged candidates were promoted, answered,
  or rejected this week, and any pattern in the AI's verdicts vs. what
  actually happened downstream (e.g. candidates the judge scored low that
  the owner hand-approved anyway).
- `{distilled_prior_amendments}` — a short summary of learned amendments
  already made, so this pass doesn't repeat or contradict one.
- `{current_learned_file}` — the current contents of
  `state/question_judgment/learned.md` verbatim (empty string if none yet).
- `{arc_yield_summary}` — what the CONVERSATION arcs yielded, per arc-card
  intent kind, derived from the vault itself: how many sessions carried the
  kind, and how many filed answers, timeline placements and new entities
  came out of them. A session carrying three intent kinds counts toward all
  three (co-attribution — treat a difference between kinds as a signal, not
  a measurement).
- `{current_arc_learned_file}` — the current contents of
  `state/question_judgment/arc_learned.md` verbatim, the learned block that
  is composed into the weekly arc-plan prompt after `plan/arc-templates.md`.

**Task:** Decide whether a bounded amendment is justified this week. If
not, output `{"amendment": null, "reason": "..."}` — declining to edit is a
valid, expected outcome most weeks. If yes, output:

```json
{
  "amendment": "the exact markdown text to append to state/question_judgment/learned.md",
  "evidence": "what pattern, with which candidate ids/dates, justified this edit",
  "char_count": 0,
  "arc_amendment": "the exact markdown text to append to state/question_judgment/arc_learned.md, or null",
  "arc_evidence": "which kinds, with which counts, justified the arc edit"
}
```

- `amendment` MUST be under `knob.weekly_edit_max_chars` characters (the
  edit budget) — an amendment over budget is a defect, not a judgment call
  the runtime should silently truncate.
- `amendment` is ONE bounded change — a clarification, a carve-out, a
  correction — never a rewrite of the rubric itself (`prompt/behavior.md`
  is framework-owned and PR-reviewed; the learned file only ever
  supplements it, never replaces or contradicts it).
- `evidence` is required whenever `amendment` is non-null — an amendment
  with no cited evidence is not a valid output (see `prompt/examples.md`'s
  rubric-edit example).
- `arc_amendment` is the same bounded, evidence-cited edit for ARCS — how
  the week's intent kinds actually paid out, written as guidance the arc
  planner can act on ("lead with the timeline whisper in eras with no dated
  events; it placed 4 things in 2 sessions"). It obeys the same budget and
  the same rule that most weeks the honest answer is `null`. Never write a
  penalty for a whisper: raising the timeline where it fits is not a cost.
- The quarterly full-ledger recalibration (`knob.recalibration_cadence`)
  is out of this template's scope — it is a distinct, larger review pass
  the follow-up PR defines when it wires the runtime.

## Output constraints (both modes)

- Valid JSON only, no markdown fences, no prose outside the object.
- No field beyond what each mode's schema above specifies.
- Apply `prompt/behavior.md`'s hard rules and vocabularies in full; this
  template does not restate them.
