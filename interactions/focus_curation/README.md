# The Focus-Curation Interaction — why it's built this way

Read `interactions/README.md` first for the Interaction pattern itself; this
file is the "why" for one specific interaction: the judgment call on
first-encounter Focus/idea duplicate *variants* — pairs the deterministic
layers below it cannot resolve on their own.

## 1. Mission tie-in

Duplicate Focuses and duplicate pending ideas dilute the record instead of
building it: two "Fear" categories split one theme's evidence in half, and a
"Betty Jo" idea sitting apart from a "Betty Jo Taylor" idea means neither
ever accumulates enough signal to become the Focus it should be. Curating
these variants down to one identity serves `system/mission.md`'s "help
others understand me" and "enable me to tell my story" purposes indirectly —
it is infrastructure for the wiki's node graph staying trustworthy, not a
judgment about the author's material itself.

**How this interaction honors `system/mission.md`'s Convergence Principle**
(ADR 0006 — the loop must work without us): three layers, in order, and this
interaction is the smallest, least-autonomous one on purpose.

1. **Door guards** (`roadmap.py`'s `focus_new`/`add`/`derive_focuses`) —
   deterministic, always on, kill the exact-name-modulo-case class before it
   is ever created.
2. **Roster fold** (`recommend_focuses.py`, at `recommend()` time) —
   deterministic, always on, catches settled variants the roster's monthly
   AI curation already resolved.
3. **This interaction** — AI, judgment-only, for the residue neither
   deterministic layer can decide: a *first-encounter* near-name pair (the
   "Betty Jo" shape) with no settled roster alias yet to fold through.

**There is no deterministic fallback that merges.** Absent AI (a keyless
machine with no completed agent task), layer 2's roster fold is the floor —
the near-name pair sits apart, correctly, rather than being merged on a
guess. This interaction is purely the Convergence Principle's *accelerator*
for this one narrow judgment call, never its floor; the floor is already
satisfied by the deterministic layers above it, which is also why this
interaction ships with `role.worker: medium` (a low-stakes, reversible call
on a pending idea, not a durable page or a rubric that reshapes future
judgments).

## 2. What this interaction judges

Given (a) the pending recommendation ideas the deterministic layers left
apart, (b) the settled roster context for identity-signal, and (c) the
existing Focus roster it could map into, this interaction emits exactly one
partition of the handed idea ids into three buckets — `merge` (variants of
one identity), `map_to_focus` (an idea that is actually an existing Focus by
another name), and `keep` (genuinely distinct, or not enough evidence to
say) — and nothing else. It never invents an entity, never talks to the
author, and never explains itself in prose: `prompt/turn-instructions.md`'s
output shape carries no reason or evidence field at all (see §4).

## 3. Research basis

This interaction has no `system/research.md` scholarly anchor the way
`question_judgment` does — it isn't a craft judgment about a question, it's
an identity-resolution judgment, the same shape `entity_roster.py`'s AI
roster-curation prompt (`build_prompt`) already makes for people/places/
periods/objects/themes, and the same shape `_entity_keys` /
`normalized_focus_key` already formalize deterministically for the exact-
match case. This interaction's rubric (`prompt/behavior.md`) is that
existing, already-battle-tested identity-resolution judgment, narrowed to
the specific first-encounter-duplicate-pending-idea case and stripped of
everything the deterministic layers already own (case-folding, "the "-
prefix folding, settled-alias folding).

## 4. Owner decisions (ratified 2026-08-14)

- **No reason capture, anywhere.** The platform removed the dismiss-reason
  field; this interaction's JUDGE gets no reason context from prior human
  decisions, and its own output carries no reason/evidence text field
  either — `{"merge": [[...]], "map_to_focus": {...}, "keep": [...]}` is the
  entire schema. A verdict is either a valid partition of the handed ids or
  it is malformed and gets applied as a no-op — see `evals/lints.yaml`.
- **Tier**: `role.worker: medium` — a low-volume, reversible, low-stakes
  call (the runtime never creates or deletes a Focus; it only relabels
  which pending-idea id(s) a merge/map targets). No `role.planner` — this
  interaction has no rubric-edit mode and no learning file; there is
  nothing here for a weekly pass to amend.
- **No router, no plan.** This interaction never receives free-form inbound
  and has no pre-planned turns — it only ever judges a handed idea list, per
  `interactions/README.md`'s "an interaction may omit `router/`/`plan/` if
  it doesn't need it."
- **Canonical-first ordering.** Within a `merge` group, the JUDGE lists the
  canonical (fullest, most complete) identity first — the rest are its
  variants. The runtime (`system/focus_curation.py`'s `apply_verdicts`)
  treats list order as the contract, not a second inference to make.
- **Settled-decision discipline.** An applied `merge` or `map_to_focus`
  dismisses the losing pending-idea record(s) with `dismissed_by:
  "curation"` (the same structured marker convention
  `recommend_focuses.py`'s "expiry"/"owner" markers already use) — so a
  regenerated `recommend()` run cannot silently re-split what this
  interaction already settled. No reason text is ever written to that
  record, per the decision above. A `keep` verdict has no record to
  dismiss, so every decided id (merge, map, AND keep) is additionally
  logged to `state/focus_curation/settled.json` — a per-id ledger so a
  correctly-kept-apart pair isn't re-presented to the JUDGE on every future
  run. Documented simplification: once an id is settled in ANY bucket it is
  never re-presented, even if it would later form a genuinely new near-name
  pair with a different idea — trading a theoretical missed re-judgment for
  guaranteed convergence (see `system/focus_curation.py`'s `SETTLED_FILE`
  comment).
- **Models are seated only after passing `evals/`.** No default seat ships
  with this PR — see §6.

## 5. How it's built

- **Behavior contract**: `prompt/behavior.md` — the load-bearing file, the
  identity-resolution rubric.
- **Context recipe**: `context/manifest.md` — `identity → behavior →
  examples → turn_instructions`, matching `interaction.yaml`'s `budget.*`
  keys. No `learned` block (no learning file exists for this interaction)
  and no `profile` block (quality-profile signal is irrelevant to an
  identity judgment).
- **The loader/runtime**: `system/focus_curation.py` —
  `build_pending_idea_list()` restricts the input to genuinely
  first-encounter near-name pairs (`focus_dupes.near_name_pairs`'s idea-vs-
  idea and idea-vs-focus participants, minus anything a settled roster
  alias would already fold — Scope 2's job, never re-done here);
  `build_curation_prompt()` assembles the call; `run_curation()` is the
  keyless-aware runtime (`--emit-task`/`--from-response`, the same
  convention `system/entity_roster.py` and `system/question_judgment.py`
  use — see their module docstrings); `apply_verdicts()` is the
  deterministic application step, called after Scope 2's roster fold, that
  actually dismisses merged/mapped pending-idea records. There is
  deliberately no code path in this module that invents a merge without a
  verdict to apply.

## 6. How to eval

`evals/` mirrors `interactions/question_judgment/evals/`'s shape:
`lints.yaml` (deterministic — the rubric carries numbered hard rules, a
verdict parses as the exact three-key JSON shape
`prompt/turn-instructions.md` specifies, every handed id appears in exactly
one bucket, no invented ids or slugs), `rubrics.md` (a binary yes/no judge
question per hard rule), `goldens/` (fixture format in `goldens/README.md`,
one committed golden landing with this PR), and `personas/` (a README stub —
the persona set is designed once real curated output exists to model
against, mirroring `question_judgment`'s own bootstrap).

No engine reads `evals/lints.yaml` yet — this PR ships the model contract as
data; a future harness run is what actually seats a model in `role.worker`.
Until then this interaction has no default seat, exactly as
`interactions/README.md`'s pattern requires.

🤖 README authored by Claude Fable 5 via Claude Code
