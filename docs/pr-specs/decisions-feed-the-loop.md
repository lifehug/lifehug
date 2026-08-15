# Contract: decisions-feed-the-loop

## Why

Owner-directed (2026-08-14). The review surface collects exactly the
training signal that could tune question generation and judgment — the
owner's promote/dismiss/defer verdicts and free-text reasons — and then
archives it unread: no generation prompt sees it, no score consumes it,
and the reason field literally OVERWRITES the generator's own provenance.
Per the Convergence Principle (ADR 0006, accelerator clause): "every
explicit decision is signal the loop must actually consume." This PR
makes that true, and wires the question-judgment interaction's weekly
RUBRIC-EDIT (ADR 0007's declared-but-unwired half).

## Binding facts (as of origin/main after #145, v164)

- Field-overwrite defect: `system/question_candidates.py
  update_candidate()` — `if reason is not None: candidate["reason"] =
  reason` clobbers the generator's provenance `reason`. CLI
  `candidates-update --reason` and the hosted platform's defer/dismiss
  both route here.
- Decision provenance already on records: `status`
  (rejected/deferred/promoted/auto_promoted…), `promoted_by`
  ("auto" or absent for human), `updated_at`, and (post-this-PR)
  `decision_reason`.
- The interaction (merged #145): `interactions/question_judgment/` —
  `prompt/turn-instructions.md` already contains the weekly RUBRIC-EDIT
  task template; `context/manifest.md` orders identity → behavior →
  learned → …; `system/question_judgment.py load_judgment_rubric()`
  assembles behavior.md + `state/question_judgment/learned.md` (missing
  → empty); `interaction.yaml` knobs include `knob.weekly_edit_max_chars`
  and `knob.recalibration_cadence: quarterly`; `role.planner: high`.
  `evals/lints.yaml` includes an amendment-length lint.
- Vault contract: `question_judgment_learned` registered (vault data).
- Generation prompt seams (post-#145): `classify_story.build_prompt` and
  `research_expand`'s expansion path both consume the loader.
- Weekly rhythm: `system/weekly_maintenance.sh` — steps run via
  `run_step`/`run_learning_step`; quality-profile update precedes
  candidate auto-promotion. AI access via `system/ai_provider.py`; the
  keyless path emits agent tasks (`--emit-task`/`--from-response`
  convention, e.g. `entity_roster.py`); provider absence must never
  break the weekly run (README §"model providers are optional").
- Quality/engagement deltas: `state/answer_scores.json` +
  `state/quality_profile.json` (bucket multipliers) — the "distilled
  state" the weekly edit reads.
- Version bumps to next free above origin/main at PR time (expect 166 if
  the unified-score PR lands as 165 first — verify before push).

## Scope

In:
1. **Fix the overwrite** — `update_candidate()` writes owner text to a
   NEW `decision_reason` field; the generator's `reason` is never
   touched again. `candidates-update --reason` maps to it; every display
   path that showed `reason` for decided rows shows `decision_reason`
   where present (viewer history lane); records with the historical
   collision are left as-is (no migration — note in ADR).
2. **Decision context for generation** —
   `question_judgment.build_decision_context(limit=15)` (single
   authoritative assembly, lives in `system/question_judgment.py`):
   compact lines for the most recent owner decisions
   (`DISMISSED/DEFERRED/PROMOTED "<text ≤120 chars>" — <decision_reason
   or promoted_by note>`, newest first, humans only — `auto_promoted`
   rows excluded). Injected as an "Owner judgment signals" block into
   BOTH generation prompts (classifier + research expansion) via the
   loader seam, with an explicit instruction line: candidates matching
   the pattern of recent dismissals must not be re-proposed. Empty
   history → block omitted entirely.
3. **The weekly rubric edit (the accelerator engine)** — new
   `judgment-update` subcommand (`lifehug.py` thin wrapper →
   `question_judgment.py run_weekly_edit()`):
   - Assembles the DELTA: decisions since the last edit (tracked by a
     `state/question_judgment/last_edit.json` cursor: timestamp + counts),
     quality-profile bucket movements (current multipliers vs the
     snapshot stored in the cursor), and the current learned.md.
   - Calls the planner role through `ai_provider` with the interaction's
     assembled context (identity → behavior → learned → delta →
     RUBRIC-EDIT turn instructions). Keyless: `--emit-task` writes
     `state/agent_tasks/judgment/edit.json`, `--from-response` applies —
     same convention as entity_roster; NEVER a deterministic fallback
     that invents an amendment.
   - Applies ONE amendment: appends a dated entry to
     `state/question_judgment/learned.md` — `## YYYY-MM-DD` + the
     amendment + a mandatory `Evidence:` line — enforcing
     `knob.weekly_edit_max_chars` per entry; a response with no
     defensible amendment writes NOTHING (a "no change" verdict is
     valid and recorded only in the cursor). File cap
     `knob.learned_max_chars` (add to interaction.yaml, default 8000):
     on overflow, oldest entries drop with one `(compacted YYYY-MM-DD:
     N earlier amendments folded)` line — the rubric-edit prompt is told
     to fold, not the code to summarize.
   - `--dry-run` prints the delta + would-be prompt, writes nothing.
   - `--recalibrate` variant: full decision-ledger context instead of
     the delta (the quarterly deep pass) — MANUAL command only in this
     PR; no scheduler wiring (cadence knob documents intent).
4. **Weekly wiring** — `weekly_maintenance.sh` gains the
   `judgment_update` learning step immediately after the quality-profile
   update and before candidate auto-promotion (order matters: the week's
   answers inform the edit; the edit informs nothing this run — next
   run's generation reads it; document this one-run lag in the ADR).
   Dry-run mode previews. Keyless mode emits the task and continues.
5. **Evals** — `evals/goldens/` gains at least two fixtures: a JUDGE
   verdict golden and a RUBRIC-EDIT golden (delta in → bounded amendment
   out, evidence line present, length lint passes), wired to whatever
   golden-runner convention `interactions/conversation/evals` uses.
6. **ADR 0009** — decision signal consumption: the decision_reason
   split, the delta/distillate/one-edit weekly architecture, the no-op
   edit, compaction, the one-run lag, and the no-migration call.
7. Version bump + changelog (+ `framework_files` for any new shipped
   files; learned.md and cursor are vault data, NOT framework files).

Out: platform transport of decision_reason (post-pin-bump); scheduler
wiring for recalibration; consuming decision signal in numeric scoring
(the unified score may later calibrate on it — follow-up issue, file it
and link in the ADR); seating any model (evals gate).

## Implementation notes

- The cursor file makes the weekly step idempotent within a week
  (re-runs see an empty delta → no-op) — subtest it.
- Prompt-side dedupe guidance (scope 2) is instruction, not code — the
  near-duplicate Jaccard machinery already suppresses exact re-proposals;
  the block teaches the generator the PATTERN ("no more yes/no questions
  about work").
- `run_weekly_edit` must hold the same single-writer discipline as other
  vault mutations (route through the jobs/queue convention the other
  weekly steps use — inspect how quality_profile's update commits).
- Keep every new state file in `state/question_judgment/` (one
  directory, already contracted for learned.md — extend the
  vault_contract entry to the directory if needed).

## Test plan

`tests/test_decisions_feed_loop.py` (new), subtests: overwrite fix
(generator reason survives dismiss-with-reason; decision_reason lands);
decision-context assembly (ordering, human-only filter, truncation,
empty→omitted); both generation prompts contain the block when history
exists (and not when empty); weekly edit — delta cursor advance, no-op
verdict writes nothing but advances cursor, amendment append respects
per-entry cap, file-cap compaction, dry-run writes nothing, keyless
emit-task path produces a well-formed task file and --from-response
applies it; recalibrate uses full ledger. Update any existing tests
pinning the old reason-overwrite behavior. Baseline note: 21
pre-existing env failures on clean origin/main in this workspace — delta
must be zero; CI is the arbiter.

## Launch-and-verify

Viewer surface changes only if the history lane's reason display moves
to decision_reason — if the rendered HTML changes, extend an existing
walkthrough or ship `tests/walkthrough_decision_reason.py` showing a
dismissed row with BOTH provenance reason and owner reason visible;
otherwise the executable proof is `python3 system/lifehug.py
judgment-update --dry-run` output + the unittest invocation, pasted in
the evidence comment.

## Definition of done

Per TEMPLATE.md — version bump, ADR 0009, vault_contract updated,
follow-up issue filed for score-calibration-on-decisions, CLAUDE.md
weekly-rhythm description updated (it enumerates the weekly steps),
evidence comment with real command output.

🤖 Contract authored by Claude Fable 5 via Claude Code
