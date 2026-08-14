# Personas — stub (real personas land with the wiring PR)

`interactions/conversation/evals/personas/` simulates USERS — this
interaction never talks to a user, so a persona here means something
different: a simulated *generation context* (a batch of candidates with a
known-good or known-bad shape) the judge is run against, to prove specific
rubric properties hold across a realistic mix rather than only on
hand-picked single goldens.

This PR ships the declaration only, per the contract's Scope ("`personas/`
(README stub)"). The wiring PR designs the actual persona set once real
judged output exists to model against — candidates from this PR's
`prompt/examples.md` are the starting material, but a real persona needs a
batch large and varied enough to exercise the priority bands and penalty
vocabulary together, which a handful of illustrative examples isn't meant
to do.

Expected shape once written (matching `interactions/conversation/evals/
personas/*.md`'s own convention): one file per persona, a short
description of the generation context it simulates, and the specific
property its runs must demonstrate — e.g. a "backlog-heavy" persona whose
runs must show priority bands staying well-separated even under a large
batch, or a "near-duplicate-cluster" persona whose runs must show
`penalty.duplicate_of_*` catching every near-dupe in the cluster, not just
the first.
