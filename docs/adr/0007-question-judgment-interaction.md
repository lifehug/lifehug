# ADR 0007: The Question-Judgment Interaction

Date: 2026-08-14
Status: proposed

## Context

The judgment calls a model makes on which follow-up questions are worth
asking, and how urgently, had no designed Interaction — unlike the
conversation surface (ADR 0002). `system/classify_story.py`'s
classification prompt embedded `system/mission.md` plus
`system/research.md` sliced to `research[:3000]` — cut off mid-way through
§1's eleven numbered craft essentials — under the heading "Research
Background (condensed)," and a single unexplained sentence, "Set priority
between 0.4 (nice-to-have) and 0.95 (critical gap)," with no description
of what evidence justified either end. `system/research_expand.py`'s
neighborhood-expansion prompt independently read the same `research.md`
and sliced it to `research_notes[:800]`, which in practice held only the
document's header and its AI-privacy paragraph — none of §1's craft
methodology reached that generation path at all. Neither truncation was a
deliberate design choice; both were an accident of an f-string slice that
nobody revisited as `research.md` grew. The deterministic quality checker
(`question_candidates.check_quality`) had its own penalty vocabulary
(`yes_no_wording`, `self_directed_why`, `too_broad`, and others) that
neither prompt referenced, so a human reading a `check_quality` result and
a human reading a generated candidate's reasoning (when a model offered
any) were reading two unrelated vocabularies for the same judgment.

This is the same defect class ADR 0002 named for the conversation
surface — a judgment scattered across ad hoc prompt strings with no shared
research basis, no eval gate, and (here specifically) an actual bug
silently discarding most of the craft doctrine the prompts were supposed
to be built on. The 2026-08-14 owner design session ratified making this
judgment a designed Interaction, following the same pattern ADR 0002
established, rather than patching the two truncation sites in place.

## Decision

(a) **`interactions/question_judgment/` is added**, following
`interactions/README.md`'s pattern exactly (see ADR 0002 for the pattern
itself). `prompt/behavior.md` — the rubric — restates
`system/research.md` §1's eleven essentials in behavior-contract form,
numbered identically to §1 so the two documents read side by side, and
adds a priority vocabulary (four evidence-gated bands from 0.4 to 0.95,
per `knob.priority_floor`/`knob.priority_ceiling`) and a penalty
vocabulary that mirrors `question_candidates.check_quality`'s flags by
name — `check_quality` itself is unchanged by this PR; the rubric
documents it so judge and code speak one language. `research.md` remains
the scholarly source (citations, evidence strength); `prompt/behavior.md`
becomes the operational authority a model is actually graded against —
doc IS prompt, so the two cannot drift apart the way a prompt and a
separate description of it can.

(b) **`system/question_judgment.py`'s `load_judgment_rubric()` is the one
authoritative loader** (recurring-defect doctrine, `docs/BUILDING.md` §8).
`system/classify_story.py`'s `build_prompt` and
`system/research_expand.py`'s expansion prompt path both call it instead
of hand-reading `research.md` and slicing it — the `research[:3000]` and
`research_notes[:800]` truncations are deleted, not adjusted to a larger
number. The loader assembles `prompt/behavior.md` (never truncated) plus
`state/question_judgment/learned.md` (empty when absent), and degrades to
the pre-migration truncated-`research.md` behavior ONLY when
`interactions/question_judgment/`'s definition itself can't be read (a
vault mid-upgrade running against a framework snapshot that predates this
interaction) — a vault on-version never takes that path, since the
interaction ships in `system/version.json`'s `framework_files`.

(c) **Tier guide** (owner-ratified 2026-08-14): `role.worker`
(per-candidate judging — high-volume, low-stakes) is a **medium**
capability tier; `role.planner` (the weekly rubric edit and the rare
quarterly full-ledger recalibration — low-volume, high-stakes, changes
every future judgment) is a **high** capability tier. These name
capability tiers, not vendor products, per ADR 0002's model-agnosticism
rule. No `router/` — this interaction never receives free-form inbound;
it only ever judges a handed candidate or edits a handed rubric.

(d) **The learned-amendments data contract is declared, not wired.**
`state/question_judgment/learned.md` is registered in
`system/vault_contract.json` as vault data (`question_judgment_learned`),
never a framework file — a person's own accumulated judgment amendments
belong to their vault, not to something the framework ships on every
install. The loader treats a missing file as simply empty. **Learning
architecture** (owner-ratified 2026-08-14): score once, at capture (JUDGE
mode runs per generated candidate); a weekly pass reads that week's
deltas plus a distillation of prior amendments and makes exactly ONE
bounded edit (`knob.weekly_edit_max_chars`, currently 600 characters),
always with a cited evidence line — never a rewrite; a quarterly pass
(`knob.recalibration_cadence`) re-examines the full candidate ledger for
drift the weekly increments might have missed. **This is the concrete
shape of `system/mission.md`'s Convergence Principle (ADR 0006, v163,
landed the same day as this design session) for this interaction** — ADR
0006 names "the decisions-feed-the-loop and question-judgment interaction
work" outright as one of the mechanisms the principle binds: JUDGE mode is
the floor (autonomous, no human required, every candidate gets judged),
RUBRIC-EDIT mode is the accelerator (the owner's promote/dismiss/defer
decisions are optional, multiplicative signal, never a dependency). This
PR ships the slot and the RUBRIC-EDIT prompt template only; the runtime
that actually invokes `role.planner` and writes to the file is the
follow-up
"decisions-feed-the-loop" PR's job.

(e) **Alternative considered and rejected**: patching the two truncation
sites in place (raise `3000`/`800` to a larger number, or read the whole
file). Rejected for the same reason ADR 0002 rejected patching the three
conversation mechanisms independently — it would fix the immediate bug
without giving the judgment criteria a shared, versioned, eval-gated
home, and the next prompt this criteria needs to reach (a future
generation path) would face the identical scattering problem again.

## Consequences

- **Binds**: any future question-generation path reads its judgment
  criteria from `system/question_judgment.py`'s `load_judgment_rubric()`,
  never by hand-reading `research.md` or re-deriving a priority/penalty
  vocabulary locally — a new generation path that re-embeds its own
  truncated research slice is a design defect, not a legitimate shortcut.
  Changes to the judgment rubric go through
  `interactions/question_judgment/prompt/behavior.md` and its evals, not
  ad hoc edits to a generation path's prompt string.
- **Forecloses**: any generation path independently truncating
  `research.md` for its own prompt; model-specific tricks in the core
  `prompt/*.md` files (verified provider deltas belong in `overlays/`
  only, and only once actually verified, per ADR 0002's rule); the
  framework shipping a copy of any vault's `learned.md` (it is vault
  data, never framework data, by design).
- **Delete-when**: if a future PR unifies `question_judgment` and
  `conversation` (or any other interaction) into one shared judgment
  primitive, this ADR's Decision (a)–(d) would be superseded by whatever
  ADR ratifies that merge; nothing in this PR's scope proposes that.
