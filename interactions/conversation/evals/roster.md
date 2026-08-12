# Roster — models that pass the Conversation Interaction eval harness

The model roster for `role.router`, `role.worker`, and `role.planner` is
whatever has passed `system/interaction_evals.py` (issue #120) — not a
fixed vendor choice. Each row records a run link; this file is what makes
"model-agnostic" a fact rather than a hope.

| Model | Role(s) | Layers passed | Run link | Date |
|---|---|---|---|---|
| _(none seated yet)_ | — | — | — | — |

**Empty is expected at this PR.** This harness (issue #120) is
infrastructure — the deterministic layers (1–3) are keyless-green in CI on
every PR from here forward; a model is added to this table only after a
full live run (Layer 4, judge + personas, keyless-skippable in CI but
required for a roster entry) against it, per this file's own row format.
The cross-model scheduled workflow that produces those live run links lives
on the platform repo (`lifehug/lifehug-platform#417`), where vendor keys
can exist — this repo's own CI stays dependency-free and keyless.

Row format once a model is seated: `model id | roles it's seated for |
"1-4" once Layer 4 has a real run | link to that run's evidence (a
platform workflow run, or a committed `state/agent_tasks/evals/` response
set reviewed by hand) | ISO date`.
