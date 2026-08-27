# Contract: eras-o-c-stale-first-cursor

Phase **E-C** (OSS half, `O-C`) of the Eras / Timeline program. Platform
tracking: lifehug-platform#686; the defect: lifehug-platform#685; platform
contract: `docs/pr-specs/eras/e-c-hosted-classification.md` there; viewer
parity twin: #254. Controlling authority: the platform's `docs/design/eras.md`
§6 and ADR 0030 (in flight on `docs/adr-0030-eras`).

## Why

A classification carrying `stale: true` — filed by a correction through
`source_integrity.create_linked_source` → `classify_story.mark_stale`
(`system/source_integrity.py:1025`) — **keeps feeding the Timeline, Mirror,
the Book, focus recommendations and the wiki until a fresh one overwrites
it**. `is_classified`'s own docstring records the leak
(`system/classify_story.py:184-193`): stale counts as "unclassified" for the
batch, and *"the stale classification stays on disk (and keeps feeding the
timeline/wiki) until the fresh one overwrites it"*. Eight readers glob
`state/classifications/*.json` and none checks `stale`.

The batch that is supposed to regenerate it cannot reach it in bounded time:
`cmd_classify_all` (`:879-887`) is `sorted(all_source_files())` → `not
is_classified` → `[:limit]`, alphabetical first-N with no memory between runs.
On the founder vault the five stale files sit at positions 18–197 of a
268-entry unclassified list; at the weekly `--limit 5` (`weekly_maintenance.sh:187,199`)
the same five heads re-run every week and the stale tail is never reached.
`all_source_files` (`:217-226`) also walks `sources/corrections/`, so a
correction document is itself a classification target — the auditor's
response 3 §4.5: *"A correction source should cause reclassification of the
corrected target, not accidental classification of the correction document
itself."*

The owner's ruling (platform decision 13, the auditor's wording): a
classification explicitly marked stale is excluded from derived readers
**immediately**; reclassification is queued promptly, stale-first; compile
proceeds zero-model; a model outage never restores a known-stale
interpretation.

## Binding facts (as of `origin/main` v234, `235eea91…`)

* `system/classify_story.py`: `classification_path` / `legacy_classification_path`
  / `classification_paths` (`:170-181`); `is_classified` `:184-193`;
  `_is_stale` `:196-197`; `mark_stale` `:200-213` (sets `stale`,
  `stale_reason`, `stale_at`); `all_source_files` `:217-226`; `corrections_for`
  `:262-280` (matches `corrects_path` or `corrects == answer:<stem>`,
  `type: source_correction`); `build_classification` returns a dict with no
  `stale` key, so a successful write clears staleness by overwrite;
  `cmd_classify_all` `:879-923`; parser `:936-995` — modes `--classify`,
  `--prompt`, `--classify-all`, `--from-response`; options `--unclassified`,
  `--emit-prompts`, `--limit`, `--dry-run`, `--model`, `--source`,
  `--no-candidates`. **There is no `--stale-first`, no cursor, no `is_current`.**
* Readers that glob `CLASSIFICATIONS_DIR` with no staleness check:
  `timeline.py:474` (`load_events` — the Timeline and, through it,
  `wiki_compile.py:1546-1574`'s datable-moments section), `mirror.py:96`,
  `book.py:101`, `progress.py:38`, `research_expand.py:648`,
  `recommend_focuses.py:304`, `serve_wiki.py:1391`; `question_planner.py:306-320`
  (`_count_classified`, existence only); `lifehug.py:2193` (a count).
* `weekly_maintenance.sh:177-206`: keyless → `--classify-all --unclassified
  --limit $CLASSIFY_LIMIT --emit-prompts $AGENT_TASKS_DIR/classify`; keyed →
  the same without `--emit-prompts`. The platform's weekly step
  (`services/api/app/maintenance/program.py:555-640`) is a line-for-line port
  and will pass the new flag once this lands in its pin.
* `state/` files are declared in `system/vault_contract.json`; a new state
  file is a contract entry and a `framework_files`/manifest consideration.
* `skills/maintenance/SKILL.md:67-68` teaches that "unclassified" includes
  stale (v103); the wording moves with `is_classified`.

## Scope

### 1. `is_current(source_path) -> bool` — the one reader gate

Classified AND not stale. Every reader in *Binding facts* consults it (or the
equivalent per-file predicate `classification_is_current(path)` when the
reader already holds the JSON path) and **skips a stale file**. The file stays
on disk — it is the batch's target and the person's history — but it is not
an input to anything derived. `is_classified` keeps exactly its batch meaning
("this source needs a run") and its docstring drops the sentence that admits
the leak; the two predicates are documented side by side so nobody re-derives
a third.

`question_planner._count_classified` counts current classifications only;
`lifehug.py:2193`'s status count reports `current / stale / unclassified`
separately so the number the owner reads names the hole.

### 2. `--stale-first` and the durable cursor

`cmd_classify_all` gains:

* `--stale-first`: the candidate list is ordered stale (oldest `stale_at`
  first) → never-classified, **newest source first** (so the answer filed
  yesterday reaches the Timeline before a 2011 email; the cursor below is
  what guarantees the tail is still reached) → then the rest.
  Deterministic given the same tree.
* A durable cursor `state/classify_cursor.json`
  `{"version": 1, "last_source_key": "<stem>", "updated_at": "<iso>", "run_id": "<optional>"}`,
  advanced after each successfully filed source and consulted at the start of
  a `--classify-all` run so the never-classified sweep resumes AFTER the last
  key it filed instead of restarting at `a`. It is `state/` because it is
  derived operational memory (rebuildable, deletable, never authority) — the
  same class as `state/timeline_deferred.json` was; declared in
  `vault_contract.json` as a state file. Stale-first ordering does not consult
  the cursor: a stale file is always at the head, however many times the
  sweep has passed it — being passed means it failed, and a failed target is
  not a served one.
* `--limit` semantics unchanged (a cap on this run). With `--stale-first` the
  cap is spent on stale files first.

### 3. Corrections are never targets

`all_source_files` excludes `sources/corrections/` (and any file whose
frontmatter `type` is `source_correction` wherever it sits). A new helper
`classify_target_for(path) -> Path | None` maps a correction document to the
source it corrects (the same `corrects_path` / `corrects` join
`corrections_for` uses, `:262-280`) and returns `None` for a non-correction;
the platform's enqueuer calls the same helper through the pin (one
definition, two hosts). `--classify <correction path>` exits non-zero with
`classify_target_is_correction` and names the target it would have taken.

### 4. Out of scope

The targeted hosted job, the live adapter, the backfill runbook (platform
`P-C1..P-C3`); `--supersedes` on corrections (`O-E0d`, its own contract); any
change to the classification prompt or output shape; the `mirror_item` read
alias deletion owed by v235 (see the version note below).

## Implementation notes

* `classify_story.is_current` beside `is_classified`; `_is_stale` becomes
  `classification_is_current(path)`'s negation, one definition.
* Readers: wrap the glob in one generator
  `classify_story.current_classification_files()` yielding `(path, data)` for
  current files only, and switch each reader to it — eight call sites, one
  iterator, so a ninth reader cannot re-glob by accident (a test greps
  `CLASSIFICATIONS_DIR.glob` outside `classify_story.py` and fails on any hit).
* `cmd_classify_all`: build the ordered candidate list in a pure function
  `order_targets(sources, *, stale_first, cursor) -> list[Path]` so the
  ordering is unit-tested without a model.
* Cursor read/write through `lifehug_core.read_json/write_json`; missing or
  malformed cursor = start from the head (never an error).
* `weekly_maintenance.sh` passes `--stale-first` on both branches.
* `skills/maintenance/SKILL.md:67-68` and `AGENTS.md`'s classification
  paragraph updated to name `is_current` and the cursor.

## Test plan

`tests/test_classify_story_current.py` (new), `python3 -m unittest
tests.test_classify_story_current -v`; every negative subtest is first run
against the pre-change code and seen failing (pasted in the PR body):

* `test_stale_classification_is_excluded_from_every_reader` — a vault with one
  current and one `stale: true` classification: `timeline.load_events`,
  `mirror`'s classification pass, `book`, `progress`, `research_expand`,
  `recommend_focuses`, `serve_wiki`'s reader each yield ONLY the current
  file's rows; the stale file still exists on disk. (Platform T-C-05, layer 1.)
* `test_wiki_compile_datable_moments_skip_stale` — the compiled period page
  carries no moment from the stale file.
* `test_no_reader_globs_classifications_directly` — source sweep: no
  `CLASSIFICATIONS_DIR.glob` outside `classify_story.py`.
* `test_stale_first_orders_stale_before_unclassified` and
  `test_stale_first_is_deterministic` — `order_targets` on a fixture tree.
* `test_cursor_resumes_after_last_filed_key` — two runs at `--limit 2` over
  five unclassified sources cover all five; a third run at the tail wraps.
* `test_stale_ignores_cursor` — a stale file behind the cursor is still first.
* `test_missing_or_malformed_cursor_starts_at_head`.
* `test_corrections_are_never_targets` — `all_source_files` omits
  `sources/corrections/*`; `--classify <correction>` exits non-zero naming the
  corrected source; `classify_target_for` maps correction → target and
  non-correction → `None`. (Platform T-C-08's package half.)
* `test_is_classified_meaning_unchanged` — stale still counts as
  needs-a-run for the batch.
* `tests/test_vault_contract.py` (existing) — `state/classify_cursor.json`
  declared.

## Launch-and-verify

No viewer surface changes. Command evidence in the PR body:

```bash
python3 system/lifehug.py classify-story --classify-all --unclassified --stale-first --limit 3 --dry-run
# → lists the stale files first, then newest unclassified, never a sources/corrections/ path
cat state/classify_cursor.json   # after a keyed run: last_source_key advanced
```

## Definition of done

- [ ] `is_current` + `current_classification_files()`; eight readers rewired;
      the no-direct-glob guard.
- [ ] `--stale-first`, `order_targets`, `state/classify_cursor.json` (declared
      in `vault_contract.json`).
- [ ] Corrections excluded; `classify_target_for`.
- [ ] `weekly_maintenance.sh` passes `--stale-first`; SKILL/AGENTS wording.
- [ ] Tests above green; negatives seen red first.
- [ ] `system/version.json`: **slot assigned by readiness at green, not in
      this contract commit.** Whichever executable OSS PR takes **v235** also
      deletes the `mirror_item` read alias in `system/mirror_work.py`
      (v234's stated one-version obligation) — if this PR is that PR, the
      deletion rides here with its own test; if not, it is not this PR's.
- [ ] AGENTS.md/CLAUDE.md classification paragraph updated.
- [ ] #254's Timeline note unaffected (no viewer change); lifehug-platform#685
      references this PR.

🤖 Generated with Claude Fable 5 via Claude Code
