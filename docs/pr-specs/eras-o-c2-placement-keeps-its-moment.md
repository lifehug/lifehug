# Contract: eras-o-c2-placement-keeps-its-moment

A repair stacked on **O-C** (`docs/pr-specs/eras-o-c-stale-first-cursor.md`,
#256) inside Phase **E-C** of the Eras / Timeline program. Platform tracking:
lifehug-platform#686; the defect O-C fixes: lifehug-platform#685. Prior
authority this restores: **lifehug#224** (a placed date must actually file and
must be visible where the person looks) and **lifehug#228** / v215 (placement
identity is minted once and joined on one key).

## Why

O-C makes `classify_story.is_current` the one reader gate: a classification
carrying `stale: true` leaves every derived reader **immediately**. That is
the owner's ruling and it is right.

`timeline-place` — the one path that turns a date named in conversation into
a durable vault fact — files its durable half as a `source_correction`
(`system/lifehug.py:cmd_timeline_place` shells out to `source_integrity
correct --kind date`), and `create_linked_source` marked **every** corrected
source's classification stale. Composed, the two ruled behaviours produce:

> the person dates a moment → the moment's classification goes stale → the
> moment leaves the Timeline → it comes back only when a model re-derives the
> classification.

The person's own act of dating a moment is what makes it disappear. That is
the exact inverse of lifehug#224's stated guarantee — *"the proof ends where
the person looks: the moment, in its period, dated"* — and it broke seven of
lifehug#228's placement-identity tests, which O-C's first draft adapted with
a `reclassified()` stand-in and pinned as
`PlacementWithholdsItsOwnMomentTests`, reporting the collision rather than
papering over it. That pin listed three options: (a) accept it, with the
stale-first batch as the repair window; (b) place through the claim
substrate's `timeline-move` instead of a correction; (c) narrow `mark_stale`
so a correction that ADDS a date the classifier never had does not invalidate
the reading.

**The decision (option c), made by the orchestrator and flagged to the owner
for veto:** *a placement is a date DECISION about a moment, not a refutation
of the source's content, so it must not mark the classification stale.* A
content correction says "the text got this wrong" and the reading extracted
from that text is therefore known-wrong — stale, withheld, exactly as ruled.
A placement says "this moment, which I accept, happened then". Nothing about
the reading is refuted; the date is applied by the placement overlay on read.

**The owner-veto point.** If the owner prefers (a), revert this PR: the
collision returns, and the repair window is however long the stale-first
batch takes to reach that vault. If the owner prefers (b), this PR is
superseded rather than reverted — `timeline-move` would replace the
correction as the placement's durable half, which is a larger change to
`cmd_timeline_place` and to what a placement cites; the `correction_role`
vocabulary would then be deleted, not repurposed.

## Binding facts (as of `feat/eras-o-c-stale-first` `0b42726`)

* `system/lifehug.py:cmd_timeline_place` runs
  `source_integrity.py correct <source> --kind date --source fix` and stores
  the returned correction path on the placement row. It is the ONLY placement
  filing path: `jobs.py:611`, `timeline_interaction.place_invocation`,
  `conversation_delivery._file_placement`, `serve_wiki.py:3612` and
  `reading_room.py` all build argv for `lifehug.py timeline-place`, so a flag
  added inside the command reaches every host.
* `source_integrity.create_linked_source` (`:946`) is the one writer of a
  correction record and the one caller of `classify_story.mark_stale`
  (`:1025`), which is the one writer of `stale`/`stale_reason`/`stale_at`.
* `correction_kind` cannot carry this distinction: a placement and a person's
  own date correction are both `kind: date`, and the vocabulary is already
  shared with `temporal_store` (`supersede`, `retract`, `dispute`).
* `_linked_source_path` treats an existing file with the same
  `(type, target_id, payload)` as an idempotent retry.
* The placement overlay `state/timeline_placements.json` (`timeline.place_events`)
  already moves the date on read; nothing about the date needs the
  classification to be re-derived.
* `tests/test_timeline_place_filing.py` executes the real subprocess against a
  real temp vault — the seven lifehug#228 identity tests are the end-to-end
  proof either way.

## Scope

### 1. A correction says what it IS — `correction_role`

`system/lifehug_core.py` gains a **closed** vocabulary of exactly two values,
beside `DEFAULT_CORRECTION_ROLE` and the ONE predicate both hosts ask:

```
CORRECTION_ROLES = ("content", "placement")
DEFAULT_CORRECTION_ROLE = "content"
ROLES_THAT_MARK_STALE = frozenset({"content"})
normalize_correction_role(value) -> str          # raises on anything else
correction_role_marks_stale(value) -> bool
```

* `content` — the source's text got a fact wrong; the reading extracted from
  it is known-wrong. **Marks stale** (v103, unchanged).
* `placement` — a date decision about a moment the person accepts. **Does not
  mark stale**; the placement overlay moves the date.

Closed on purpose: `normalize_correction_role` raises `ValueError` for
anything outside the two, so a third correction shape has to be ruled on
rather than silently defaulting into either behaviour. Absent/empty means
`content`, which is what every correction filed before this PR was.

### 2. The record carries it durably

`create_linked_source(..., correction_role=...)` validates the role **before
writing anything**, writes `correction_role` into the correction's own
frontmatter (`FRONTMATTER_ORDER` after `correction_kind`), and passes the role
to `mark_stale`. The role also participates in linked-source *identity* —
not in the digest, so no existing correction's filename moves, but in what
counts as an idempotent retry: byte-identical text filed as a placement and
as a content correction are two different acts, and aliasing the second onto
the first leaves a record whose frontmatter describes the other one.

### 3. `mark_stale` refuses on its own

`classify_story.mark_stale(source, reason, *, correction_role=...)` returns
False and writes nothing for a role that does not mark stale. The guard is in
the seam, not only in today's single caller, so a second caller cannot re-file
a placement as a refutation by forgetting it.

### 4. `timeline-place` files `--role placement`

One line, inside `cmd_timeline_place`, so every host that builds
`timeline-place` argv inherits it. `correct`, `fix`, `reflect`, `retract` and
the platform's correction endpoints are untouched: a person's date correction
is still `content`, still stale.

**Not in scope:** the claim substrate's `timeline-move` (option b), any change
to what a placement cites, and any change to `is_current`, the stale-first
ordering, or the cursor — all of O-C stands as written.

## Implementation notes

* The vocabulary lives in `lifehug_core` because both hosts already import it
  (`source_integrity` writes the record, `classify_story` marks staleness) and
  a role rule that lived in either would drift from the other — ADR 0021, one
  definition, many hosts.
* `build_source_metadata` copies existing frontmatter wholesale, so
  `apply_metadata_fix` preserves `correction_role`.
* `system/version.json` is **not** bumped here; the slot is assigned by
  readiness at green, with #256.

## Test plan

Every negative run against a state where it must fail, and seen failing.

* `tests/test_timeline_place_filing.py` is **restored to its pre-O-C form** —
  the `reclassified()` stand-in deleted, no test adapted. Seen failing first:
  with `--role placement` removed from `cmd_timeline_place`, exactly the seven
  lifehug#228 identity tests fail (`0 != 1`, the moment gone from the read);
  with it, 20 pass.
* `PlacementWithholdsItsOwnMomentTests` becomes
  **`PlacementKeepsItsOwnMomentTests`** in
  `tests/test_classify_story_current.py`:
  * `test_a_placement_correction_keeps_the_moment_it_placed` — the real
    `create_linked_source` in the placement role: not stale, `is_current`
    True, the moment still in `timeline.load_events()`.
  * `test_a_content_correction_still_withholds_its_moment` — the positive
    control, the SAME call in the other role: stale, withheld. The moment is
    absent because the reading was refuted, not because the fixture never
    reached the reader.
  * `test_an_unstated_role_is_a_content_correction` — `correct`/`fix`
    unchanged.
  * `test_the_correction_records_its_role_durably` — the frontmatter field.
  * `test_the_same_words_in_two_roles_are_two_records` — the identity guard,
    plus a genuine retry still being one record.
  * `test_an_unknown_role_refuses_and_writes_nothing`.
  * `test_mark_stale_itself_refuses_the_placement_role` — the seam.
  * `test_the_role_vocabulary_is_closed`.
  * `test_timeline_place_files_in_the_placement_role` — the one line, pinned.
* `tests/test_v103_placement_loop.py::CorrectionMarksStaleTests` passes
  **unchanged**: a `kind: date` correction with no role still marks stale.
* Determinism (the CI instability O-C's pin hit): every classification path in
  the new class is derived through `cs.classification_path`, never spelled by
  hand. `classify_stem` slugifies, which lowercases — a literal
  `answers-A1.json` matches on macOS's case-insensitive filesystem and NOT on
  Linux, which is exactly why the old pin passed locally and failed on CI.
  No test reads a shared cursor file or depends on glob order.

## Launch-and-verify

No viewer surface changes. Command evidence in the PR body:

```bash
python3 -m pytest tests/test_timeline_place_filing.py -q            # 20 passed
python3 -m pytest tests/test_classify_story_current.py -q           # 33 passed
python3 -m pytest tests/test_v103_placement_loop.py -q              # unchanged
# the negative, seen failing: drop `--role placement` from cmd_timeline_place
python3 -m pytest tests/test_timeline_place_filing.py -q            # 7 failed
```

In a vault: place a date on a moment, then read the Timeline in the same
breath — the moment is still there, at its placed date, with no model call.
`sources/corrections/*-correction-*.md` for that placement carries
`correction_role: "placement"`; a `lifehug fix` correction carries
`correction_role: "content"` and its target's classification is stale.

## Definition of done

- [ ] `CORRECTION_ROLES` closed vocabulary + one predicate in `lifehug_core`.
- [ ] `create_linked_source` validates, records, and passes the role;
      `mark_stale` refuses on its own; role in linked-source identity.
- [ ] `timeline-place` files `--role placement`; every other correction path
      unchanged.
- [ ] `tests/test_timeline_place_filing.py` restored; the seven lifehug#228
      identity tests pass unadapted; the pin becomes its negation.
- [ ] Negatives seen failing first, both directions.
- [ ] O-C's contract amended where it says a correction marks its target
      stale.
- [ ] `system/version.json`: **slot assigned by readiness at green, with
      #256** — not bumped here.
- [ ] Owner has the veto point above stated on the PR.

🤖 Generated with Claude Opus 5 via Claude Code
