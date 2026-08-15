# Contract: focus-duplicate-curation

## Why

Owner-directed (2026-08-14). The owner's live vault carries duplicate
focuses/ideas: exact-name-modulo-case pairs (a "fear"/"Fear" class) and
token-variant pairs ("Betty Jo" vs "Betty Jo Taylor"). Mechanics: idea
extraction is regex with distinct raw keys; idea-level dedupe checks only
exact slug/alias against EXISTING focuses (two pending ideas never
compare to each other); no creation door checks normalized-name
collisions, so separately-scaffolded categories yield same-named
focuses. The roster's alias intelligence (monthly AI curation, settled
decisions) exists but is never consulted for pending ideas.

## Binding facts (as of origin/main v166)

- `system/recommend_focuses.py`: `recommend()`, `_build_entity_stats()`,
  `_score()`, `_existing_focus_names()`, `_focus_covered_aliases()`,
  `save_recommendations()`; records keyed `rec-<slug>`.
- `system/roadmap.py`: creation doors — `focus_new()`, `focus-add`
  path, `scaffold_category()`, `derive_focuses()`; focus ids are
  slugified labels.
- `system/entity_roster.py`: `_entity_keys()` (lowercase+slugify+"the "
  strip), `load_roster()`, `apply_previous_decisions()` — the merge
  authority to REUSE, not duplicate.
- `interactions/question_judgment/` (v164/v166): the interaction whose
  sibling-mode pattern the curation JUDGE follows (identity/behavior/
  turn-instructions/evals structure; `system/question_judgment.py`
  loader; keyless `--emit-task`/`--from-response` convention).
- Owner decision: dismiss reasons are NOT captured (field removed on the
  platform) — the JUDGE gets no reason context; it judges from names,
  roster aliases, and evidence overlap only.
- Version bumps to next free above origin/main at PR time (expect 167);
  changelog is a STRING. 21 pre-existing env failures on clean
  origin/main in this workspace — delta must be zero.

## Scope

1. **Creation-door guards (deterministic, kills the case class)**: one
   authoritative `normalized_focus_key(label)` (lowercase, slugify,
   strip leading "the ") in ONE importable place (recurring-defect
   doctrine — likely beside the roster's `_entity_keys`, shared);
   every door (`focus_new`, `focus-add`, approve-scaffold path,
   `derive_focuses`) refuses to create a focus whose key collides with
   an existing focus, pointing at it (derive: collide → attach the
   category to the existing focus instead of materializing a twin).
   Guard test per door.
2. **Roster fold at recommend-time (deterministic, catches settled
   variants)**: before scoring, fold `_build_entity_stats` keys through
   the roster alias map — stats for keys the roster says are one entity
   merge into the canonical name (union evidence, sum counts). Pending
   ideas whose keys fold into each other emerge as ONE idea. Existing
   duplicate PENDING records converge on the next recommend() run
   (regenerate + expiry machinery already replaces pending state).
3. **`focus-dupes --report` (the damage list)**: new CLI (thin
   `lifehug.py` wrapper) printing, read-only: (a) roadmap focuses whose
   normalized keys collide (certain duplicates), (b) near-name pairs
   (one key a token-subset of another, the Betty Jo shape) as
   flagged-for-judgment, (c) pending ideas that fold into existing
   focuses or each other. Deterministic, zero AI, zero writes — the
   detection half F4 (focus-merge) and the owner's cleanup will consume.
4. **Curation JUDGE (AI, first-encounter variants)**:
   `interactions/focus_curation/` per the interaction checklist —
   README, interaction.yaml (`role.worker: medium`; no router, no plan),
   identity/behavior/examples/turn-instructions (behavior contract: given
   the pending idea list + roster + existing focuses, emit merge/map
   verdicts ONLY — `{merge: [[ids]], map_to_focus: {id: slug},
   keep: [ids]}`; never invent entities; unsure → keep), context
   manifest, empty overlays, evals (lints + goldens README + one golden).
   Runtime: a curation step inside recommend() (or monthly wiring beside
   it) that applies verdicts deterministically after the roster fold;
   keyless → emit-task/from-response; NO deterministic fallback that
   merges (absent AI, path 2's fold is the floor). Settled-decision
   discipline: applied merges persist (the dismissed/alias records make
   re-splitting impossible next run).
5. **ADR 0010**: the three-layer dedupe (door guard / roster fold /
   JUDGE), the shared key definition, the no-reason-context decision and
   its conversational future (platform issue #469 referenced).
6. Version bump; framework_files for every new interaction file;
   vault_contract entry if any new state file (curation verdicts state).

Out: merging EXISTING duplicate focuses (F4's focus-merge verb — this PR
only detects and reports them) · platform surfaces (ride the next pin
bump) · reason capture of any kind.

## Test plan

`tests/test_focus_duplicate_curation.py`, subtests: normalized key
(case/the-/slug variants collide; distinct names don't) · each door
refuses/attaches on collision · roster fold merges settled pair stats
(one idea, summed counts, union evidence) and leaves unsettled pairs
apart · report output pins all three sections on a synthetic vault with
a fear/Fear focus pair + Betty Jo idea pair · JUDGE verdict application
(merge, map, keep; malformed verdict → no-op) · keyless emit-task shape.
Update existing recommend_focuses tests that pinned unfolded behavior.
Baseline 21 env failures — zero delta; CI arbiter. Walkthrough only if
serve_wiki rendering changes (not expected — evidence = the report
command's output on the synthetic vault, pasted in the PR comment).

## Definition of done

Per TEMPLATE.md: version bump, ADR 0010, CLAUDE.md updated where it
describes idea dedupe, evidence comment with real `focus-dupes --report`
output.

🤖 Contract authored by Claude Fable 5 via Claude Code
