# Contract: question-judgment-interaction

## Why

Owner-directed (2026-08-14 design session). The AI's judgment calls on
question quality/priority have no designed Interaction: the classifier
prompt embeds `mission.md` + `research.md[:3000]` (truncated mid-§1) and
says "set priority 0.4–0.95"; `research_expand` injects
`research_notes[:800]`, which contains ONLY the doc header and the
AI-privacy paragraph — zero craft methodology reaches question
generation. The criteria the models judge by must become one reviewable,
versioned Interaction definition (ADR 0002 pattern), consumed everywhere,
with a declared vault-side slot for weekly learned amendments (wired by
the follow-up decisions-feed-the-loop PR, not this one).

## Binding facts

- Pattern authority: `interactions/README.md` (ratified 2026-08-11).
  Checklist steps 1–12 apply; `interactions/conversation/` is the
  reference implementation. Flat scalar YAML only
  (`lifehug_core._parse_simple_yaml`).
- Truncation sites: `system/classify_story.py` `build_prompt()`
  (RESEARCH_FILE read + `{research[:3000]}` interpolation;
  `load_mission()` at the same seam) and `system/research_expand.py`
  main flow (`research_notes[:800]` into `build_expansion_prompt`).
- Craft doctrine source: `system/research.md` §1 (the 11 question-design
  essentials) — the rubric RESTATES these in behavior-contract form; the
  research doc remains the scholarly source, the interaction file
  becomes the operational authority (doc = prompt, drift impossible).
- Deterministic quality checker: `question_candidates.py check_quality`
  — UNCHANGED by this PR (the unified-score PR owns scoring); the rubric
  documents the penalty vocabulary so judge and code speak one language.
- Tier guide (owner-ratified 2026-08-14): `role.worker` (per-candidate
  judging) = medium capability tier; `role.planner` (weekly rubric edit +
  rare full-ledger recalibration) = high tier. No router (no free-form
  inbound). Models are seated only after passing `evals/`.
- Learning architecture (owner-ratified 2026-08-14): score once at
  capture; weekly pass reads deltas + distilled state; ONE bounded,
  auditable edit per week to the learned file; quarterly full-ledger
  recalibration. This PR declares the slots; the follow-up PR wires the
  writer.
- Version/manifest: every new file under `interactions/question_judgment/`
  joins `framework_files` in `system/version.json`; new vault data path
  registered in `system/vault_contract.json`. Version bumps to the next
  free number above origin/main's (verify at PR time; the merge train
  renumbers on rebase if needed).

## Scope

In:
1. **`interactions/question_judgment/`** per the checklist:
   - `README.md` — mission tie-in (the three purposes + the Convergence
     Principle), research pointers (research.md §1, the quality-profile
     loop), the owner decisions above, how it's built, how to eval.
   - `interaction.yaml` — modes (`judge`, `rubric_edit`), load order,
     `role.worker: medium` / `role.planner: high` (capability tiers, not
     vendor names), lifecycle knobs (`knob.weekly_edit_max_chars`,
     `knob.recalibration_cadence: quarterly`), `budget.*` per context
     block. Flat dotted keys only.
   - `prompt/identity.md` — the curator of the author's asking supply:
     calm, evidence-first, never invents facts about the author.
   - `prompt/behavior.md` — THE RUBRIC. Numbered hard rules restating
     research.md §1 (open-ended never yes/no; two-sentence rule; specific
     moment over generality; sensory instance; emotional anchor;
     five-slot scene probe; action↔identity ladder; what-not-why for own
     feelings; never restate as fact; new angles on depth passes; one
     question, how/what openers), the priority vocabulary (0.4
     nice-to-have … 0.95 critical gap, and what evidence justifies each
     band), the penalty vocabulary mirroring `check_quality`'s flags, and
     the mission test ("serves at least one of the three purposes or it
     is the wrong question").
   - `prompt/examples.md` — good/bad judged candidates, each naming the
     rule it demonstrates.
   - `prompt/turn-instructions.md` — two task templates: per-candidate
     JUDGE (input: candidate + provenance + profile bucket; output:
     compact JSON verdict) and weekly RUBRIC-EDIT (input: week's delta +
     distilled state + current learned file; output: ONE bounded
     amendment; the template states the edit-budget and the
     evidence-line requirement).
   - `context/manifest.md` — assembly order identity → behavior →
     learned → examples → profile-distillate → turn_instructions, with
     budgets matching `interaction.yaml`.
   - `overlays/` — empty convention-headed files matching the
     conversation interaction's provider set.
   - `evals/` — `lints.yaml` (deterministic: behavior.md has numbered
     rules; judge output parses; amendment length ≤ knob), `rubrics.md`
     (binary per-rule judge questions), `goldens/README.md` (fixture
     format; goldens land with the wiring PR), `personas/` (README
     stub).
   - NO `router/`, NO `plan/`.
2. **Learned-amendments slot (declared, not wired)**:
   `state/question_judgment/learned.md` registered in
   `vault_contract.json`; loader treats missing file as empty; the
   rubric-edit template writes it ONLY via the follow-up PR.
3. **One authoritative loader** (recurring-defect doctrine):
   `system/question_judgment.py` — `load_judgment_rubric()` returns the
   assembled judgment context (behavior.md + learned.md when present),
   with an explicit fallback to the legacy truncated-research injection
   when the interaction files are absent (external vault mid-upgrade).
   `classify_story.build_prompt` and `research_expand`'s prompt path
   switch to it — the `[:3000]` / `[:800]` truncations die.
4. **ADR** (`docs/adr/0007-question-judgment-interaction.md`): the
   interaction, the tier guide, the learned-slot data contract, the
   learning cadence.
5. Version bump + `framework_files` additions + changelog.

Out: the weekly rubric-edit RUNTIME (decisions-feed-the-loop PR); any
scoring change (unified-score PR); seating any model (evals gate;
goldens arrive with the wiring PR); platform transport (post-pin-bump).

## Test plan

- `tests/test_question_judgment.py` (new): loader assembles behavior +
  learned; missing learned → behavior only; missing interaction dir →
  legacy fallback text; classifier prompt contains the numbered rules
  UN-truncated (regression for the [:3000] bug); research_expand prompt
  contains them (regression for the [:800] bug); yaml parses via
  `_parse_simple_yaml`; lints in `evals/lints.yaml` pass against the
  shipped files.
- Full suite via `python3 -m unittest discover -s tests` (note: this
  workspace shows 21 pre-existing environment failures on clean
  origin/main — your delta must be zero; CI is the arbiter).

## Launch-and-verify

Not a `serve_wiki.py` surface change — no walkthrough required. The
executable proof: `python3 -m unittest tests.test_question_judgment -v`
plus a printed sample prompt (`python3 system/classify_story.py
--show-prompt <fixture>` if a show path exists, else the test asserts).

## Definition of done

Per `docs/pr-specs/TEMPLATE.md` — version bumped, framework_files
complete (CI `framework-manifest` gate proves it), vault_contract entry,
ADR committed, AGENTS.md/CLAUDE.md untouched unless described behavior
changed (the prompt-source change IS described behavior — add one line
to the classifier/research description if those docs describe the old
injection).

🤖 Contract authored by Claude Fable 5 via Claude Code
