# Contract: eval-harness (issue #120)

Status: Draft implementation contract — contract stage only.

> This commit defines the work for issue #120. Do not merge it as spec-only.
> **Implementation gate**: start only after the conversation-interaction
> wave-1 PRs are merged (the `interactions/` scaffold PR and the session-store
> + `system/conversation.py` builders PR — verify live state with `gh pr
> list`/`gh issue list`; do not trust this paragraph's tense). Wave-2 (turn
> engine, story→conversation, arc planner) may land before or after this PR;
> this harness depends only on wave 1's artifacts.

## Why

The Conversation Interaction (owner-ratified design, 2026-08-11) is
model-agnostic by requirement: the behavior contract lives in portable files
under `interactions/conversation/`, and any qualified model — Anthropic,
OpenAI, Kimi, Qwen — can be seated in it **only after passing its eval
harness**. This contract builds that harness. It is the model contract: a
model change, a prompt-file change, or an overlay change is a PR that must
pass the harness in CI, exactly like code. Without it, "model-agnostic" is
hope; with it, the roster is whatever passes. Issue #120; platform twin
lifehug/lifehug-platform#417 (CI mirror + cross-model scheduled runs — the
live cross-model workflow deliberately lives THERE, where vendor keys can
exist; this repo's CI stays dependency-free and keyless). **Pin note**: the
platform twin (#417) requires the platform's framework pin to include this
PR's (lifehug#120's) release — #417's contract states explicitly that if the
Wave-3 step-0 pin bump ships before #120 merges, a SECOND pin bump is
required before #417 lands; this PR's own merge is the trigger that #417
gates on.

## Binding facts

- CI (`.github/workflows/ci.yml`) runs `python3 -m unittest discover -s
  tests -p "test_*.py"` on Python 3.11 and 3.14 with **no pip install**.
  Everything this contract adds must be stdlib-only and discoverable by that
  exact invocation. (The tests are also collectable by pytest for anyone who
  has it; unittest is the contract.)
- Eval assets live in `interactions/conversation/evals/` as landed by wave 1:
  `lints.yaml`, `goldens/*.json` (golden transcripts + router fixtures),
  `rubrics.md`, `personas/*.md`. Interface pins shared with the wave-1
  contract (if merged wave-1 reality differs, follow the merged reality and
  record the deviation in the evidence comment):
  - **`lints.yaml` format subset**: FLAT SCALAR DOTTED-KEY subset only — keys
    map to scalars or lists of strings; there is no one-level-mapping form.
    Anything that would otherwise be a nested mapping (e.g. per-class
    router gate thresholds) is instead expressed as flat dotted keys, e.g.
    `router_gates.answer.precision: 0.9`, `router_gates.answer.recall: 0.85`
    — one scalar per dotted key, never a nested block. No anchors, no
    nesting, no flow style. This repo is dependency-free — there is no
    PyYAML; the harness ships a minimal loader for exactly this subset (same
    spirit as `lifehug_core.load_config`'s flat `key: value` config
    parsing). `seam_ok` semantics (referenced below in the golden schema) are
    a GOLDEN-file field, not a `lints.yaml` key, so they are unaffected by
    this constraint; if a future PR needs seam-related config in
    `lints.yaml` itself, it must be expressed as a flat dotted key
    (e.g. `seam.ok_default: false`) under this same subset — it is not
    otherwise defined here.
  - **Golden transcript schema** (`goldens/*.json`, one session per file):
    `golden_id`, `mode` (`chat|conversation`), `register`
    (`celebration|hard|neutral`), `arc` (`question_id`, `opening`,
    `intents[]`), `turns[]` of `{role: user|lifehug, text, annotations?}`
    where lifehug-turn `annotations` carry `kind`
    (`opener|receipt|receipt_payout|closing|deflection`), `quoted_span`
    (exact substring of the prior user turn the receipt quotes), `topic`
    (slug), `seam_ok` (bool — permits a closed question at a seam per
    behavior.md rule 3), and `properties[]` — the closed assertion
    vocabulary: `receipt_quotes_user`, `no_new_topic_mid_arc`,
    `closing_has_takeaway_and_hook`, `deflects_off_scope`,
    `demonstrated_knowledge_opener_shape`.
  - **Router fixture schema** (`goldens/router_fixtures.json`): a list of
    `{text, session_open: bool, intent}` with `intent` ∈ `{answer,
    new_story, command, continue_session, out_of_scope}`; per-class
    precision/recall thresholds live in `lints.yaml` under `router_gates`.
- **Vocabulary alignment with #114/#115 (consistency-audit amendment)**: the
  authoritative lint MODULE is `system/conversation_lints.py` (NOT
  `interaction_evals.py`) — recurring-defect doctrine: ONE importable
  authority; the wave-2/3 runtime turn validator in `conversation_delivery`
  imports the lint functions from `conversation_lints`, never re-implements
  them. This PR's own harness module for goldens/rubrics/personas MAY remain
  `system/interaction_evals.py` (the Layer 4 judge/persona runner and
  everything beyond deterministic lints), but that module IMPORTS the lint
  layer from `conversation_lints` rather than defining or duplicating lint
  logic. Lint ids are `one_question_per_turn` (not `max_questions_per_turn`)
  and `question_grammar_audit` (not `question_grammar`). Grammar
  classification classes per #115 are anchored on `cued` (the shared
  classifier's baseline classes); this contract ADDS a `presupposing` class
  to the SHARED classifier living in `conversation_lints` — it does not
  define its own separate presupposing check.
- Provider access for model-backed layers goes through
  `system/ai_provider.py::call_ai` only (fail-closed; keyless →
  agent-task/skip semantics). Judge/persona/live-router runs never bypass
  it.
- behavior.md's hard rules are numbered 1–13 (one question max;
  respond-before-ask with exact quoting; question grammar; zero pressure;
  register matching; payout anatomy with receipts; unnamed escalation ramp;
  closings takeaway+hook then stop; scope/deflection; voice preservation;
  session honesty; no AI autobiography; mid-thread rumination back-off).
  `rubrics.md` clauses key 1:1 to those numbers; the persona suite is:
  terse, rambler, topic-switcher, off-scope prober, grief-fresh (must
  observe deferral), ruminator (must observe mid-thread back-off),
  enthusiast (must not be hard-stopped).
- Version: this lands as the next `system/version.json` bump after the
  wave-1/2 PRs it follows (number determined at implementation; changelog
  sized to user impact — this is a framework-integrity feature, small-to-
  medium). If new distributable files are added (they are —
  `system/interaction_evals.py` at minimum), `framework_files` must list
  them; `interactions/**` entries in `framework_files` are wave 1's
  responsibility — verify they exist, add if missed (the platform vendors
  the pinned export and needs the eval assets in it).

## Scope

**In:**

1. **Layer 1 — deterministic lints** (always run, CI + runtime), in
   `system/conversation_lints.py` (the shared lint module — see the
   vocabulary-alignment binding fact above; `interaction_evals.py` imports
   from here, it does not define these), each mapping to a behavior.md rule:
   - `one_question_per_turn` — ≤1 interrogative per lifehug turn (rule 1).
   - `banned_phrases` — list-driven from `lints.yaml`: guilt/pressure
     ("you haven't told me much", streak language), unsolicited advice
     markers, "that must have been"-class presupposed-emotion phrasing,
     AI self-reference ("as an AI", "I'm just a language model") (rules 4,
     5, 12). Case-insensitive, curly-quote-normalized substring match.
   - `question_grammar_audit` — classify every interrogative as
     `cued | cued_invitation | closed | option_posing | presupposing`
     (deterministic pattern rules documented in the module docstring);
     `presupposing` is ADDED BY THIS CONTRACT to the shared classifier in
     `conversation_lints` (per #115, the classifier's baseline anchors on
     `cued`) — this PR extends the shared classifier rather than defining a
     separate one; `closed`/`option_posing`/`presupposing` fail unless the
     turn is annotated `seam_ok` (rule 3).
   - `length_caps` — per-turn character caps by mode/channel from
     `lints.yaml` (Telegram-native defaults).
   - `receipt_before_question` — structural: in a turn following a
     substantive user turn, no interrogative sentence may precede the
     receipt segment (deterministically: the first sentence of such a turn
     is not interrogative, and when `quoted_span` is annotated it appears
     before the first `?`) (rule 2).
   - `year_question_detector` — "what year / which year / in what year"
     class fails; landmark-anchor phrasing passes (rule 3 / research.md §4).
2. **Layer 2 — router fixtures + scorer**: schema validation of
   `router_fixtures.json` (always run) plus a per-class precision/recall
   scorer that consumes a predictions file (`[{text, predicted}]`) and
   enforces `router_gates.*` thresholds, expressed as the flat dotted keys
   defined above (e.g. `router_gates.answer.precision`,
   `router_gates.answer.recall`) — never a nested `router_gates:` mapping.
   Live prediction generation uses the
   `lifehug.py route` builder/delivery from the wave-2 router PR when
   present; until then the scorer + a committed sample predictions fixture
   prove the gate math deterministically.
3. **Layer 3 — golden-transcript property assertions** (always run):
   execute every `properties[]` entry against every golden —
   `receipt_quotes_user` (the annotated `quoted_span` is a verbatim
   substring of both the prior user turn and the receipt turn),
   `no_new_topic_mid_arc` (no lifehug turn introduces a `topic` outside the
   arc's set while the arc is open), `closing_has_takeaway_and_hook`
   (closing turn present, non-recap takeaway + named hook, and NO trailing
   question after it), `deflects_off_scope` (off-scope user turn is met by a
   `deflection`-kind turn and no on-task answer), and
   `demonstrated_knowledge_opener_shape` (opener = summary-then-gap:
   record-summary sentence(s) then one gap invitation). All lifehug turns in
   every golden must also pass Layer 1.
4. **Layer 4 — judge rubrics + personas runner** (model-backed,
   keyless-skippable): `python3 system/lifehug.py conversation-evals`
   (new subcommand → `system/interaction_evals.py` main) runs, per seated
   model/overlay: live router predictions over the fixtures → Layer-2 gates;
   judge passes (strong judge model, randomized clause order, binary
   verdict per rubric clause) over goldens and/or freshly simulated persona
   sessions; the seven-persona suite with its three named behavioral
   observations (deferral, back-off, no hard stop). Keyless semantics:
   every model-backed step is SKIPPED loudly (named step + reason + count),
   exit 0, and `--emit-tasks` writes agent-task prompts under
   `state/agent_tasks/evals/` following the existing keyless emit idiom.
   Never red without keys; never silently green — the summary line always
   distinguishes `passed/failed/skipped`.
5. **Tests** (Layer-1–3 enforcement in CI): `tests/test_interaction_evals.py`
   — lint unit tests (each rule: passing + failing fixtures), lints.yaml
   loader subset tests, golden property assertions over ALL committed
   goldens, router schema + scorer gate math, keyless-skip semantics of the
   runner (no network in tests, ever — fake providers per repo convention).
6. **Docs, minimal**: `interactions/conversation/evals/README.md` (or the
   evals section of `interactions/conversation/README.md`, whichever wave 1
   created) gains the operating rule: *any PR touching
   `interactions/conversation/**`, a `conversation_model`/`router_model`
   config default, or `overlays/*` must include a harness run in its
   evidence (local live run or a platform interaction-evals workflow link).
   The roster (models that pass) is recorded in
   `interactions/conversation/evals/roster.md` with run links.* Full README
   trueing is #121's job, not this PR's.

**Out:** the cross-model scheduled workflow (platform #417 — keys live
there); any change to prompts/behavior.md content (wave 1/2 own those); the
runtime turn-validator wiring inside `conversation_delivery` (wave-2 PR —
it imports this module); CI workflow changes here (the existing `test`
matrix discovers the new tests; no new OSS workflow).

## Implementation notes

- `system/interaction_evals.py`: pure module + `main()`. Asset loading via
  `vault_paths`-safe framework paths (eval assets are framework files, not
  vault data — load relative to `system/`'s parent like other framework
  asset reads). No new dependencies.
- Deterministic grammar classification will be heuristic — that is fine and
  expected; the goldens are annotated so the heuristics are exact on the
  committed corpus, and the judge layer covers what heuristics cannot.
  Document each pattern rule inline.
- Provider calls: reuse `ai_provider.call_ai` with the config keys the
  wave-2 PR establishes (`router_model`, `conversation_model`; judge uses
  `judge_model` falling back to `classify_model`). Do not invent a second
  routing path.
- Follow the `build_prompt`/delivery split: judge/persona prompt builders
  are pure functions (stdin-JSON-friendly), the runner orchestrates.

## Test plan

New: `tests/test_interaction_evals.py` (subtests named per lint rule and
per golden property). Changed: none expected; if wave 1 landed
`tests/test_interaction_lints.py` or similar, fold/extend rather than
duplicate. Prove with:

```
python3 -m unittest tests.test_interaction_evals -v
python3 -m unittest discover -s tests -p "test_*.py"
```

## Launch-and-verify

No `serve_wiki.py` surface — no walkthrough. The viewable artifact is the
runner itself; a reviewer reproduces from scratch with:

```
python3 system/lifehug.py conversation-evals            # keyless: layers 1–3 pass, model layers SKIPPED loudly
python3 system/lifehug.py conversation-evals --emit-tasks  # writes judge/persona agent tasks
```

Expected keyless output: a summary table with every Layer-1 lint and
Layer-3 property listed as passed, router scorer proven on the committed
sample predictions, and each model-backed step listed as `SKIPPED (no
provider ready)` — exit 0. The evidence comment includes this output
verbatim plus, if the implementer has a provider configured, one live run.

## Definition of done

- [ ] Code + tests pass locally (`python3 -m unittest discover -s tests`)
- [ ] `system/version.json` bumped (version, released, changelog,
      `framework_files` += `system/interaction_evals.py` and any new eval
      asset files; verify `interactions/**` is already manifested)
- [ ] AGENTS.md/CLAUDE.md: one line added to the model-config guidance —
      prompt/model/overlay changes gate through `conversation-evals`
      (full doc trueing stays #121)
- [ ] No ADR needed (the interaction pattern ADR is wave 1's; this PR
      implements its eval clause) — record in the PR if implementation
      reveals a decision that does need one
- [ ] Issue #120 commented with verification results
- [ ] Evidence comment on the PR: runner output (keyless, and live if
      available), full unittest run, honest deviations from the wave-1
      interface pins if any

🤖 Generated with Claude Fable 5 via Claude Code
