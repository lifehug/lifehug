# Contract: eras-o-e1b-view-block

Phase **E1b** of the Eras / Timeline program, OSS half (`O-E1b`) — the
platform findings against `O-E1` (merged, `docs/pr-specs/eras-o-e1-age-frames.md`,
v238). Platform tracking: lifehug-platform **#686**, findings recorded in
lifehug-platform **#691**'s body. Controlling authority: lifehug-platform
`docs/design/eras.md` §2.2, §3.3–3.5, §5.2, §7 row "Age frame node", §7.8.

## Why

`#691` built the platform's tolerant readers against committed fixtures per
§7.8 step (1) — "consumes data from" is not "depends on the merge of" — and
in doing so executed the E1 schema against a real reader for the first time.
Four gaps surfaced that only running code, not reading the design, could
have found:

1. **`memberships` had a guard that made §7.8 step (1) impossible as
   written.** The platform's `test_the_envelope_keys_are_the_pinned_views_own`
   asserts `served - keys == {"reason", "dates_rendered"}` against
   `calculated_view()`'s own key set — so a field the platform needs to read
   ahead of a pin bump has nowhere to declare itself except an allowlist that
   names the debt. `memberships`, `reached_frame_epoch` and
   `projection_schema_version` (renamed `schema_version` on read) all need to
   be visible in that key set, not only present in the published file the
   platform hasn't pinned to yet.
2. **The frame `label` carried only a bare name** ("Childhood"), and §3.3's
   display string ("Childhood · ages 0–12") would then have to be composed by
   a host — which is authoring a sentence about somebody's life, forbidden by
   the standing "the platform never writes a title" ruling. Landed in this
   branch's first commit, `1e5b286`; this contract's test plan confirms it.
3. **`chapter_overlays` is named by §5.2's rendering rule and declared
   nowhere** — not in §2.2's node field list, not as a top-level projection
   key. A chapter covers several frames; repeating its identity once per
   frame node it touches would be the parallel-definition shape ADR 0021
   exists to stop.
4. **`life_view: lived|future_plan` and the current frame's
   `definition_span.start`** needed confirming as the settled carriers for
   §2.6/§3.4's "was this lived or is it a plan" and "2021–present" rendering
   questions — both already exist from `O-E1`, so this phase proves them
   through the publication path rather than re-deciding anything.

## Binding facts (as of this branch's base, `origin/main` at v238)

- `system/temporal_publication.py`
  - `EMPTY_VIEW` `:565-580` — what `calculated_view()` returns when nothing
    is published; also, by construction, the served key set.
  - `calculated_view(vault_root)` `:648-` — reads the published file and
    reshapes it; a key absent here is unreadable to a host no matter what the
    file contains.
- `system/temporal_projection.py`
  - `NODE_KINDS`, `validate_calculated_membership` / `CalculatedMembership`
    (E1, empty rows) — the shape `ChapterOverlay` mirrors.
  - `LIFE_VIEWS = ("lived", "future_plan")` `:106`, checked as a closed
    vocabulary at `validate_calculated_timeline_node` (`unknown_life_view`).
  - `AgeFrame.to_dict()` (`system/cross_dating.py`) already emits
    `definition_span: {start, end}` and `life_clip_end` per node; the current
    frame's `life_clip_end == "present"` with a real `definition_span.start`.
- `system/temporal_timeline.py`
  - `CalculatedTimeline` dataclass carries `memberships` (E1) as a declared,
    empty-until-E2 field; the same phase discipline applies to
    `chapter_overlays` here (declared and empty; **E3** fills the rows).

## Scope

**In:**
- `PUBLISHED_KEYS_NOT_SERVED` (`temporal_publication.py`) — every top-level
  key the published file carries that `calculated_view()` deliberately does
  not serve under that name, each with a reason. `view_block_keys()` and
  `published_block_keys()` derive the served/declared key sets from source
  (`EMPTY_VIEW` and this table) rather than a hand-list, so a genuinely new
  top-level key that is neither served nor excused is caught by a guard test
  instead of shipping silently unreadable.
- `ChapterOverlay` / `validate_chapter_overlay` / `chapter_overlay_from_dict`
  / `derive_chapter_overlay_id` (`temporal_projection.py`) — the schema,
  keyed on the chapter alone (a chapter that grows to cover a fourth frame is
  the same overlay, not a new one). `chapter_overlays` lands on `EMPTY_VIEW`,
  `calculated_view()`, `CalculatedTimeline` and `structural_signature`,
  always empty at this phase.
- The frame label change (`system/cross_dating.py`, commit `1e5b286`) —
  covered by new confirmation tests here since it shipped without its own.
- Confirmation tests (not new mechanism) that `life_view` and the current
  frame's `definition_span.start` survive the publish → `calculated_view()`
  round trip.

**Out:** filing `chapter_overlays` rows (E3); the platform-side allowlist and
wire-contract changes (`lifehug-platform#691`, already merged); `future_plan`
as a `temporal_state` member (settled instead as the separate `life_view`
field, already true as of `O-E1`).

## Implementation notes

- `temporal_publication.py:calculated_view` / `EMPTY_VIEW` / new
  `PUBLISHED_KEYS_NOT_SERVED`, `view_block_keys`, `published_block_keys`.
- `temporal_projection.py`: new `ChapterOverlay` dataclass block, mirroring
  `CalculatedMembership`'s shape and phase discipline.
- `temporal_timeline.py:CalculatedTimeline` — `chapter_overlays` field,
  `to_dict`, `structural_signature`.
- `cross_dating.py:age_frame_label` / `age_frame_name` / `age_frame_ages` /
  `AGE_FRAME_LADDER_CEILING` (already landed, `1e5b286`).

## Test plan

New file `tests/test_eras_e1b.py`:
- `ViewBlockKeySetTests` — every top-level key a real `publish()` writes is
  accounted for by `published_block_keys()`; `memberships`,
  `reached_frame_epoch` and `schema_version` (renamed from
  `projection_schema_version`) are in the SERVED set; an unnamed synthetic
  key is caught (proves the guard fires, not just that it exists).
- `ChapterOverlayTests` — validate/refuse/round-trip
  (`overlay_not_a_mapping`, `overlay_needs_chapter`, `overlay_without_frames`);
  the id is keyed on the chapter alone (same chapter + a wider frame set ⇒
  same `overlay_id`); `chapter_overlays` rides `EMPTY_VIEW`,
  `calculated_view()` and a real publish as `()` / `[]`; publishing twice
  with unchanged claims is still a semantic no-op with the new key present.
- `FrameLabelConfirmationTests` — §3.3's exact display strings for a named
  band and a decade, through `cross_dating.age_frame_label`.
- `LifeViewAndDefinitionSpanConfirmationTests` — through `publish()` +
  `calculated_view()` (not the bare fold): the current frame's `life_view`,
  `life_clip_end == "present"` and `definition_span.start.best` are all
  present on the served node; `unknown_life_view` still refuses a bogus
  value.

Every negative above was run against the base commit (`main`, before the
`ChapterOverlay`/guard functions existed) first and seen failing —
`AttributeError` / `ImportError`, since the functions this phase adds did not
exist yet.

Invocation:
```
python3 -m unittest tests.test_eras_e1b -v
```

## Definition of done

- [ ] Code + new tests pass; scoped suite
      (`tests/test_eras_e1.py tests/test_temporal_*.py
      tests/test_projection_publication.py tests/test_handbook_parity.py
      tests/test_eras_e1b.py`) green.
- [ ] `system/version.json` bumped, `framework_files` includes
      `tests/test_eras_e1b.py`.
- [ ] No ADR — this phase settles reader-side gaps against an already-ratified
      design (ADR 0030), it does not make a new standing decision.
