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
`closing_is_declarative`, `closing_engages_final_message`,
`deflects_off_scope`, `demonstrated_knowledge_opener_shape`. A `closing`-kind turn asserting
`closing_has_takeaway_and_hook` also carries `takeaway` and `hook`
(non-empty strings — the harness checks their presence structurally;
content quality is the judge layer's job, not this deterministic one).
`closing_is_declarative` (issue #139, pure-chat wave) requires `kind ==
"closing"`, zero question marks anywhere in the text (stricter than the
ordinary one-question-per-turn lint — a close permits none), and no
`closing_banned.*` phrase from `evals/lints.yaml` — see
`chat-witness-filing-close.json` for the exemplary shape (a concrete
witness/filing line, behavior.md rule 8's ratified worked example).

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

**ADR 0014 (issue #163) amendment**: `closing_is_declarative` now also
enforces the structured-close scaffolding-leak checks —
`closing_label_leak`, `closing_meta_commentary`, `closing_future_turn`,
`closing_markdown_leak` (all in `conversation_lints.lint_closing_phrases`,
data in `evals/lints.yaml`) — since it already runs that function over the
closing turn's text. `chat-porch-swing-closing.json` is the new committed
PASS example demonstrating the woven, un-scaffolded shape.

**ADR 0015 (issue #167, content-first close) amendment**:
`closing_engages_final_message` is a NEW property id as of this PR — a
closing turn asserting it must demonstrably respond to the final user
turn's actual content (checked via distinctive-token overlap between the
closing text and the immediately preceding user turn — a concrete,
verifiable signal, not a judge-layer quality call). FLAGGED for the
platform's closed-vocabulary reconciliation at the next pin bump.
`chat-seattle-ferry-closing.json` is the new committed PASS example: a
long final user message (the incident's own shape — a several-hundred-word
memory) that the closing turn visibly engages.

One exception to "every committed golden must pass every Layer-1 lint":
`closing-scaffold-leak-bad-01.json` is a deliberately-broken fixture
reproducing issue #163's leaked-scaffolding SHAPE (labeled hook field,
meta-commentary, a future-turn self-instruction, raw `**` markdown) —
entirely synthetic, never the owner's real close or any vault content. It
exists to prove the four new lints actually trip, so it is excluded from
`interaction_evals.load_goldens()`'s sweep via `NON_GOLDEN_FILENAMES`
(same mechanism as the router fixture files below) rather than required to
pass `check_golden` — `tests/test_structured_close.py` loads it directly.

## Router fixtures (`router_fixtures.json`)

A flat JSON list of `{text, session_open, intent}`, `intent` one of
`answer|new_story|command|continue_session|out_of_scope`. Schema-validated
and scored by `interaction_evals.py`'s Layer-2 scorer against
`router_gates.*` (flat dotted keys in `evals/lints.yaml`).

**Issue #169 / ADR 0017 (the thread binder, platform #490 PR B) —
additive extension**: a fixture MAY also carry `threads` (a non-empty
bounded roster of `{id, question, last_exchange, awaiting_ask}` candidate
threads — mirrors the runtime ROSTER block `conversation
.build_router_prompt` renders) and, only when `threads` is present,
`target` — the fixture's ground-truth binding: one of the roster's `id`s
or the literal string `"new"`. Fixtures with no `threads` are entirely
unaffected (schema, scoring, and gating all unchanged for them) — this is
how the pre-#169 20 fixtures stay valid untouched. The roster-bearing
rows near the end of the file are ALL synthetic (invented people/topics,
e.g. an invented lighthouse/garden/porch/bakery/road-trip) — a stepwise
shape-replay of the kind of same-day multi-thread ambiguity the binder
exists for (delivered question → answer → a "what's next?" meta-message
→ a held-ask reply that redefines a term → a clarification → "do you not
remember?", each asserting the single correct `target`), plus a genuine
content-driven bounce back to an older thread, an awaiting-ask-beats-
recency case, and an unsure-defaults-to-most-recent case — never anything
resembling the owner's real vault.

## Sample router predictions (`router_sample_predictions.json`)

A flat JSON list of `{text, predicted}` — a committed, hand-authored
"what a good live model would say" fixture. It exists to prove the
scorer's precision/recall arithmetic and `router_gates.*` threshold
enforcement deterministically and keylessly (contract: "the scorer + a
committed sample predictions fixture prove the gate math deterministically"
until a live provider is available to generate real predictions via
`lifehug.py route`).

**Issue #169 / ADR 0017 amendment**: rows matching a `threads`-bearing
fixture also carry `predicted_target` (parallel to `target`) so
`interaction_evals.score_binding_predictions` can prove
`router_gates.binding.accuracy` the same keyless way. Rows matching a
fixture with no `threads` never carry `predicted_target`.
