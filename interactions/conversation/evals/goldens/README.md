# Goldens — golden transcripts and router fixtures (issue #120)

This directory holds two kinds of committed fixture, both loaded and
evaluated by `system/interaction_evals.py`:

## Golden transcripts (`*.json`, one session per file)

One committed session per file — `golden_id`, `mode` (`chat|conversation`),
`register` (`celebration|hard|neutral`), `arc` (`question_id`, `opening`,
`intents[]`, plus this harness's own `topics: [...]` extension — see
below), and `turns[]` of `{role: user|lifehug, text, annotations?}`.

Lifehug-turn `annotations` carry `kind`
(`opener|receipt|receipt_payout|closing|deflection`), `quoted_span` (exact
substring of the prior user turn the receipt quotes — same case, no
paraphrase), `topic` (slug), `seam_ok` (bool — permits a closed/
option-posing/presupposing question at a seam per behavior.md rule 3), and
`properties[]` — the closed assertion vocabulary: `receipt_quotes_user`,
`no_new_topic_mid_arc`, `closing_has_takeaway_and_hook`,
`deflects_off_scope`, `demonstrated_knowledge_opener_shape`. A `closing`-
kind turn asserting `closing_has_takeaway_and_hook` also carries `takeaway`
and `hook` (non-empty strings — the harness checks their presence
structurally; content quality is the judge layer's job, not this
deterministic one).

**Extension beyond the contract's schema sketch** (documented, additive
only): `arc.topics: [...]` names the arc's allowed topic set for the
`no_new_topic_mid_arc` property — the contract's golden schema paragraph
didn't specify where that set comes from, so this harness makes it
explicit rather than inferring it. A golden that declares
`no_new_topic_mid_arc` on any turn must set `arc.topics`. A `user`-role
turn MAY also carry a top-level `off_scope: true` flag (not nested in
`annotations`, since only lifehug turns have those) marking it as the
off-scope message a following `deflection`-kind turn must respond to for
`deflects_off_scope`.

Every lifehug turn in every committed golden must ALSO pass every Layer-1
lint (via `conversation_lints.lint_transcript`, seam_ok-aware) — a golden
is a *correct* reference transcript; deliberately-broken fixtures proving
each property checker's failure path live inline in
`tests/test_interaction_evals.py`, not here.

## Router fixtures (`router_fixtures.json`)

A flat JSON list of `{text, session_open, intent}`, `intent` one of
`answer|new_story|command|continue_session|out_of_scope`. Schema-validated
and scored by `interaction_evals.py`'s Layer-2 scorer against
`router_gates.*` (flat dotted keys in `evals/lints.yaml`).

## Sample router predictions (`router_sample_predictions.json`)

A flat JSON list of `{text, predicted}` — a committed, hand-authored
"what a good live model would say" fixture. It exists to prove the
scorer's precision/recall arithmetic and `router_gates.*` threshold
enforcement deterministically and keylessly (contract: "the scorer + a
committed sample predictions fixture prove the gate math deterministically"
until a live provider is available to generate real predictions via
`lifehug.py route`).
