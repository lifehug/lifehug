# Focus Candidate Interaction

`focus_candidate` is an independently registered, auditable Interaction for
one Focus recommendation. It exact-composes Conversation by reference and owns
only the candidate-specific onboarding, evidence, confirmation, and completion
contract.

**Play approves.** Platform ADR 0020 and contract review-loop/54 retired the
model this Interaction was designed against: pressing Play scaffolds the Focus
in a background job and opens this conversation immediately. This Interaction
is that conversation — the onboarding that establishes what the focus is about
and how far it reaches, so the questions seeded for it are worth asking. The
first reply receives the answer, says once that the focus has been started, and
asks at most one onboarding question; afterwards the focus's name, type, and
scope change only when the user signals a change. The model still writes
nothing, approves nothing, and claims nothing — the platform has already
scaffolded.

The Play path's surface:

| What | Where |
|---|---|
| The tab's opening line | `focus_candidate.opening_question(entity, focus_type)` |
| The `{focus_stage}` this turn is in | `focus_candidate.focus_stage_for_session(session)` |
| The one additive turn-output field | `conversation_delivery.parse_turn_output(...)["focus_setup"]`, enabled by `TurnShape(focus_stage=…)` |
| Closed validation of that field | `focus_candidate.validate_focus_setup(value)` |
| The six onboarding lints | `focus_candidate.lint_focus_setup_reply(text, stage=…, user_signaled=…)` |
| The leaf the caller REPLAYs verbatim | `prompt/turn-instructions.md`, substituting `{focus_stage}`, `{focus_label}`, `{focus_type}` |

**The research-mode assets are superseded for the Play path, not deleted.**
`prompt/behavior.md`'s evidence/readiness/completion rules, the eight-dimension
rubric, `action`/`next_gap`, `research_gates.*`, and
`focus_candidate.parse_focus_candidate_output` /
`validate_focus_candidate_decision` / `resolve_focus_candidate_completion` all
still serve the standalone CLI path
(`lifehug.py focus-candidate-prompt` / `focus-candidate-complete`), whose
structured-output contract now lives in
`focus_candidate._research_output_contract_block()` rather than in the leaf —
the leaf is appended to an ordinary Conversation prompt on the Play path, and
two competing output contracts in one prompt is a defect. Nothing about that
CLI path changed otherwise.

Run the deterministic seat gate with:

```bash
python3 system/lifehug.py focus-candidate-evals --json
```

See `docs/pr-specs/focus-onboarding-context.md` (v189) and
[ADR 0021](../../docs/adr/0021-focus-candidate-interaction.md), amended by it.
