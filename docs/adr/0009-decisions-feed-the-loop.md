# ADR 0009: Decisions Feed The Loop

Date: 2026-08-14
Status: proposed

## Context

The review surface collected exactly the training signal that could tune
question generation and judgment — the owner's promote/dismiss/defer
verdicts and their free-text reasons — and then archived it unread: no
generation prompt ever saw it, no score ever consumed it, and
`question_candidates.py update_candidate()`'s `reason` kwarg actively
**destroyed** it, overwriting the generator's own provenance `reason`
(the "why was this proposed" text set at candidate-creation time in
`classify_story.py`, `research_expand.py`, and `harvest_wiki_questions`)
with the owner's decision text the moment a dismiss/defer/reason update
ran. A dismissed candidate's history could show *either* why it was
proposed *or* why it was rejected, never both, and the field literally
couldn't distinguish the two kinds of information after the fact.

Separately, ADR 0007 (the question-judgment interaction, v164) shipped
`interactions/question_judgment/prompt/turn-instructions.md`'s
RUBRIC-EDIT mode template — the weekly, `role.planner`-tier pass that
reads the week's decisions and makes one bounded amendment to
`state/question_judgment/learned.md` — as a **declared but unwired**
slot: the prompt template existed, the learned-file data contract existed
(vault_contract.json's `question_judgment_learned`), but nothing ever
called `role.planner` or wrote to the file. ADR 0006 (the Convergence
Principle, same design session) named this outright as one of the
mechanisms its accelerator clause binds: "every explicit decision is
signal the loop must actually consume."

## Decision

**(a) The field-overwrite fix.** `update_candidate()` gains a
`decision_reason` parameter that writes to a NEW `candidate["decision_reason"]`
field; the generator's `reason` field is never touched again after
candidate creation. The CLI flag stays named `--reason` (unchanged for
`candidates-update` callers and the hosted platform's jobs.py-routed
defer/dismiss actions) — only the field it writes to changed. Both
`print_candidate` (CLI) and `serve_wiki.py`'s Review-lane history groups
now render BOTH fields on a decided row, labeled distinctly ("proposed: …"
/ "owner: …"), where before neither was shown in the viewer at all.
**No migration**: candidate records where the historical collision
already happened (a decision's text sitting in `reason`, the true
provenance text lost) are left exactly as they are — there is nothing to
recover, and back-filling a plausible-looking provenance string would be
worse than an honest gap.

**(b) Owner Judgment Signals in both generation prompts.**
`question_judgment.build_decision_context(limit=15)` is the one
authoritative assembly (recurring-defect doctrine) of the most recent
human decisions — `DISMISSED`/`DEFERRED`/`PROMOTED` lines, newest first,
`auto_promoted` rows excluded by construction (a different status value,
not an extra filter). `owner_judgment_signals_block()` renders it into an
"Owner Judgment Signals" prompt block, injected into BOTH
`classify_story.build_prompt` and `research_expand.build_expansion_prompt`
via the same loader seam ADR 0007 established for the judgment rubric
itself. Empty history omits the block entirely — never an empty heading.
The instruction is deliberately about the PATTERN ("candidates matching
the pattern of recent dismissals must not be re-proposed"), not a literal
blocklist — the existing near-duplicate Jaccard machinery already
suppresses exact re-proposals; this teaches the generator the shape of
what the owner doesn't want, which the deterministic check cannot.

**(c) The weekly RUBRIC-EDIT runtime.** `question_judgment.run_weekly_edit()`
is the accelerator engine ADR 0007 declared and deferred:

- A cursor file, `state/question_judgment/last_edit.json` (timestamp +
  counts + the quality-profile bucket-multiplier snapshot at the last
  edit), makes each run's DELTA well-defined: decisions with
  `updated_at` after the cursor's `last_seen_at`, plus how far
  `state/quality_profile.json`'s `by_story_function` multipliers moved
  since the snapshot. A **distillate** of prior amendments (one short
  bullet per dated `learned.md` entry, not the raw file) is assembled
  separately from the raw file itself — `turn-instructions.md`'s
  RUBRIC-EDIT template takes both as distinct inputs
  (`{distilled_prior_amendments}` vs `{current_learned_file}`).
- The call goes through `role.planner` (ADR 0007c's high capability
  tier) via `ai_provider.call_ai`, or — keyless — `--emit-task` writes
  the assembled prompt + context to `state/agent_tasks/judgment/edit.json`
  and `--from-response` applies a completed one back, the exact
  `system/entity_roster.py` convention. There is **no deterministic
  fallback that invents an amendment** — a keyless machine with no agent
  available simply carries an open task forward, same as every other
  keyless learning step.
- **The no-op edit is a first-class, expected outcome, not a failure
  mode.** A response of `{"amendment": null, "reason": "..."}`, or a
  genuinely empty delta (no new decisions, no bucket movement), writes
  nothing to `learned.md` and is recorded ONLY as a cursor advance — most
  weeks should produce no amendment, exactly as `turn-instructions.md`
  already specified. An empty delta short-circuits before any model call
  is made at all, which is also what makes a same-week re-run idempotent:
  the cursor's `last_seen_at` has already absorbed everything, so the
  second run sees nothing new and advances the cursor again with no
  side effect.
- **One amendment, one entry, one hard cap.** A non-null response MUST
  carry an `evidence` line and MUST fit `knob.weekly_edit_max_chars`
  (600) — either failure is an INVALID response (nothing is written,
  nothing is silently truncated), never a judgment call the runtime
  resolves on the model's behalf. An accepted amendment appends
  `## YYYY-MM-DD\n\n<amendment>\n\nEvidence: <evidence>\n` to
  `learned.md`.
- **File-cap compaction stays mechanical.** `knob.learned_max_chars`
  (new, default 8000) bounds `learned.md`'s total size. On overflow the
  runtime drops the OLDEST dated entries and writes one bare
  `## YYYY-MM-DD (compacted YYYY-MM-DD: N earlier amendments folded)`
  marker in their place — it never tries to summarize what it dropped.
  The RUBRIC-EDIT prompt is told to fold going forward (via the
  distillate seeing the compaction marker like any other entry); the code
  only ever mechanically drops.
- **`--recalibrate`** swaps the delta for the FULL decision ledger (the
  quarterly deep pass `knob.recalibration_cadence` names) but is
  otherwise the identical apply/validate/compact path — a manual command
  only in this PR; no scheduler wiring for the quarterly cadence.

**(d) Weekly wiring and the one-run lag.** `weekly_maintenance.sh` runs
`judgment-update` immediately after `quality_update` (so the delta's
bucket-movement half reflects THIS week's freshest profile) and before
candidate auto-promotion. **This run's edit does not affect this run** —
`classify-story` and `research-expand` already ran earlier in the same
weekly pass (or independently, mid-week, via manual/keyless ingest); the
amendment they'd see is next week's `learned.md`, not today's. This is an
accepted one-run lag, not a defect: making the edit apply retroactively
within the same run would mean re-running classification after the edit,
which is out of scope and not what the weekly rhythm is for.

**(e) Two committed evals fixtures**, `interactions/question_judgment/evals/goldens/`:
a JUDGE-mode structural/lint fixture (no JUDGE runtime exists yet — this
PR doesn't add one) and a RUBRIC-EDIT fixture that `tests/test_decisions_feed_loop.py`
exercises end-to-end through `run_weekly_edit(from_response=...)`, proving
the bounded-amendment/evidence-line/compaction contract against a real
call, not just a schema check.

**Deferred, not decided here**: consuming the decision signal in
`unified_quality_score()`'s NUMERIC scoring (ADR 0008) — the prose
RUBRIC-EDIT amendment this PR ships is a different mechanism (it changes
what a model reads, not what a formula computes), and folding decision
history into the numeric score risks double-counting the same signal
without a design pass. Follow-up filed: lifehug/lifehug#148.

## Consequences

- **Binds**: any future write to a candidate's decision text goes through
  `decision_reason`, never `reason` — a PR that re-introduces a write to
  `reason` after candidate creation is a regression of this ADR, not a
  legitimate shortcut. Any future generation path that wants owner
  decision signal calls `question_judgment.build_decision_context()` —
  one authoritative assembly, not a re-derived query against
  `question_candidates.json`. Any future writer to
  `state/question_judgment/learned.md` goes through
  `run_weekly_edit()`'s validate/compact path, not a direct append.
- **Forecloses**: a deterministic fallback that invents a rubric
  amendment when no model is available (the keyless path is
  emit-task/from-response only, permanently); a numeric decision-signal
  term inside `unified_quality_score()` without a dedicated design pass
  (tracked, not decided — lifehug/lifehug#148); retroactively migrating
  pre-this-PR records where a decision's reason clobbered provenance text
  (there is nothing there to recover).
- **Delete-when**: if lifehug/lifehug#148 lands a numeric calibration
  term, this ADR's "Deferred, not decided here" note should be struck or
  superseded as resolved.
