# Personas — stub (real personas land with a future wiring PR)

`interactions/conversation/evals/personas/` simulates USERS — this
interaction never talks to a user, so a persona here means something
different, the same reframe `interactions/question_judgment/evals/
personas/README.md` makes for its own interaction: a simulated *curation
context* (a batch of pending ideas, roster entries, and existing focuses
with a known-good or known-bad shape) the CURATE call is run against, to
prove specific rubric properties hold across a realistic mix rather than
only on hand-picked single goldens.

This PR ships the declaration only, per the contract's Scope ("`personas/`
(README stub)"). A future pass designs the actual persona set once real
curated output exists to model against — the examples in
`prompt/examples.md` are the starting material, but a real persona needs a
batch large and varied enough to exercise merge/map/keep together, which a
handful of illustrative examples isn't meant to do.

Expected shape once written: one file per persona, a short description of
the curation context it simulates, and the specific property its runs must
demonstrate — e.g. a "settled-roster-heavy" persona whose runs must never
propose re-splitting an already-merged identity (rule 7), or a "topical-
overlap-cluster" persona whose runs must show every pair kept apart absent
real identity evidence (rule 5).
