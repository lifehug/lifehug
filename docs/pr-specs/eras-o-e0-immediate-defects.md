# Contract: eras-o-e0-immediate-defects

Phase **E0** of the Eras / Timeline program, OSS half (`O-E0a`…`O-E0d`).
Platform tracking: lifehug-platform **#686**; hosted-classification gap
lifehug-platform **#685**; OSS viewer parity twin **#254**. Controlling
authority: lifehug-platform `docs/design/eras.md` (v3.1) §1, §3.1, §5.4,
§8 step 1, §10 and ADR 0030 (this repo) — owner rulings there are closed and
are not reopened here. Platform sibling contract:
`docs/pr-specs/eras/e0-immediate-defects.md` (`P-E0`, the pin that carries
this release).

## Why

Four defects the planning diagnosis executed against the founder's own vault
(`eras.md` §1 items 3–5 and the E7a prerequisite), each small, each blocking
the later phases, none of them a redesign:

1. **"Were you living in Mexico before or after when you were born?"** —
   `choose_probe` hands every anchored opener `anchor_rows[0]`, and the anchor
   order puts `birth` first, so any vault with a birth landmark asks a
   residence unknown to sort itself against the person's own birth.
2. **The owner's birth is minted with subject `"birth"`, not `self`.** With
   one child's birth filed the fold's "the only birth" fallback no longer
   holds, the owner's age claims lose their anchor, and a `missing_anchor
   birth_date self` work item opens against a vault that has the birthday
   (executed: `birth_anchor_probe`, below).
3. **An era's own bounds have no writer.** A `period_bound` Play answer files
   through `timeline-place` onto whatever undated moment happens to sit in
   that era's lineup — a wrong join, which ADR 0026 ranks above a miss.
4. **A correction cannot be corrected.** `source_correction` records are
   immutable and `corrections_for` returns every one targeting a source, so
   the 2026-08-25 correction pinning Charlee's letter into Childhood cannot be
   superseded — only piled on. The founder repair (E7a) starts the day this
   lands.

## Binding facts (as of `origin/main` v234, `235eea91`)

- `system/timeline_interaction.py`
  - `_anchor_rows` `:162-184` — normalizes and sorts anchors by
    `order = {"birth": 0, "residence": 1, "period": 2, "landmark": 3}`, then
    year, then key. Birth is always row 0 when present.
  - `choose_probe` `:274-330` — `anchor_label = anchor_rows[0]["label"]`
    (`:292`); every `KIND_OPENERS[kind]["anchored"]` template (`:96-135`)
    interpolates that one label; `PLAYBOOK_STEPS` probes take the same label.
  - `KIND_OPENERS["place_span"]["anchored"]` = *"Were you living in {label}
    before or after {anchor}?"*; `KIND_OPENERS["period_bound"]["anchored"]` =
    *"When did {label} end — before or after {anchor}?"*.
  - `anchors_for_person` `:187-` — birthday first "because it dates everything
    else by arithmetic" — true for the ARITHMETIC of `cross_dating`, not for
    the QUESTION a residence unknown should be asked.
- `system/landmark_projection.py::entry_subject_mention` `:254-274` — falls
  back to `collapsed_text(domain)`; for `birth` that mints
  `subject_mention = "birth"`.
- `system/temporal_timeline.py`
  - `_resolve_subjects` `:459-` — a claim with `subject_ref` is left alone;
    otherwise a supplied `ResolutionRecord`, else `identity_resolution`.
  - seeding `:1451-1466` — `births = [g for g in groups if event_kind ==
    "birth" and normalized_mention_key(g["subject"]) == owner]`; if that is
    not exactly one, `births = [every birth group]`; a birth anchor is seeded
    only when exactly one remains. `owner = collapsed_text(owner_ref) or
    DEFAULT_OWNER_REF` (`:1425`).
  - `DEFAULT_OWNER_REF` (`:220-`) is the owner's handle in relationship
    edges — the value `self` resolves to.
- `system/timeline.py` — `period_bound` rows: `UNKNOWN_KINDS` `:1359`,
  `_unknown_years` `:1565`, minted at `:1616`/`:2090`, anchor key
  `period:<slug>` at `:1741`, `PRECISION_TARGET_BY_RUNG`/kind map `:2424`.
- `system/conversation_delivery.py::_file_placement` `:1740-1790` — runs
  `timeline-place` via `timeline_interaction.place_invocation(placed,
  source=item.source or answers/<qid>.md, description=item.label,
  period=item.period or anchor_slug(item.anchor), placement_key=…)`. For a
  `period_bound` item this is the wrong writer: the "moment" is the era.
- `system/source_integrity.py`
  - `cmd_correct` `:1317-1332`; parser `:1447-1452` — args `target`,
    `--kind`, `--source`, `--title`; body on stdin.
  - `create_linked_source` `:985-1030` — writes `corrects`, `corrects_path`,
    `correction_kind` frontmatter, and ALREADY calls
    `classify_story.mark_stale(target_path, reason="correction filed: …")`.
- `system/classify_story.py`
  - `corrections_for` `:261-280` — every `type: source_correction` whose
    `corrects_path`/`corrects` matches, sorted by filename, no supersession.
  - `is_classified` `:184-193`, `_is_stale` `:196`, `mark_stale` `:200-215`.
- `tests/test_framework_shapes.py` (platform) pins `VALID_TIMELINE_STAGES`,
  `UNKNOWN_KINDS` and the probe openers' closed vocabularies — any
  vocabulary change here moves a platform parity constant at the pin.
- Version slot: **assigned at green by readiness** (the v219→v234 train's
  rule). This contract commit does NOT bump `system/version.json`; the
  implementing commit bumps to the next free slot when the branch is green.
  **v235 obligation:** whichever executable OSS PR takes slot v235 deletes the
  `mirror_item` read alias (`mirror_work.is_play_target_kind` /
  `PLAY_TARGET_KINDS`, v234 changelog) — if this PR takes v235, it carries
  that deletion and the two pinned tests that name it.

## Scope

### O-E0a — honest probe selection (anchors by relationship, not by rank)

**Rule (deterministic, one definition):** `timeline_interaction.anchor_for_probe(unknown, anchor_rows) -> dict | None`:

| unknown kind | eligible anchors | order |
|---|---|---|
| `place_span` (a residence) | `residence`, `period`, `landmark` — **never `birth`** | nearest by year to the unknown's own `years` hint if present, else residence → period → landmark, then year, then key |
| `period_bound` (an era) | `residence`, `landmark`, another `period` — never `birth`, never the era itself | same |
| `era_gap`, `residence_gap` | the two dated neighbours the row already names (`between`) | as named |
| `moment` | any anchor including `birth` — a moment MAY legitimately sort against the birthday ("was that before you were born" is only absurd for the person's own residences and eras) | existing order |
| `date_contradiction` | the row's own two accounts; anchors only as today | existing |

When no eligible anchor exists the opener uses the UNANCHORED template
(`KIND_OPENERS[kind]["text"]`): *"When did you live in Mexico — moving in to
moving out?"*. The anchored text never falls back to birth. `keystone_probe`
gets the same rule through the same function. `choose_probe`'s signature is
unchanged; `anchor_label` is derived from `anchor_for_probe` instead of
`anchor_rows[0]`.

Out of scope: rewording the opener templates; the ladder's step order;
anything under `PLAYBOOK_STEPS`.

### O-E0b — the owner's birth binds to `self` (design §3.1)

1. **Extractor rule.** `landmark_projection.entry_subject_mention` mints
   `"self"` for `domain == "birth"` (the ONE domain whose subject is the
   person). Every other domain is unchanged.
2. **Fold seeding accepts both spellings.** `temporal_timeline` seeding
   (`:1451-1466`) treats a group as the owner's birth when `event_kind ==
   "birth"` and its resolved subject is the owner (`self`) **or** its raw
   mention is the legacy domain word `"birth"`. The "exactly one birth of any
   subject" fallback is DELETED — with a child's birth filed it picked
   nothing, and with none filed it silently promoted whatever birth existed.
3. **Legacy mention resolves to `self`.** `_resolve_subjects` maps a claim
   with `subject_mention == "birth"` and `event_kind == "birth"` and no
   `subject_ref` to `subject_ref = DEFAULT_OWNER_REF` through a
   deterministic rule recorded as a `ResolutionRecord` with
   `rule: "owner-birth-domain-word:1"` — provenance-bearing and reversible
   like every other resolution, never a silent rewrite of the receipt.
4. **One owner birth node.** A legacy `"birth"`-mention receipt and a new
   `"self"`-mention receipt for the same owner birth group into ONE node
   (`_mint_node_id` on the resolved subject), their dates reconciled by
   `chronology.reconcile`; two receipts never mint two contradictory owner
   births because the extraction rule changed. No re-harvest is required and
   none is run.
5. The `missing_anchor birth_date self` work item closes on a vault that has
   the birthday under either spelling.

Out of scope: the calculated birth origin (E-BO); `profile.yaml` birth
field (non-goal).

### O-E0c — `period_bound` has no wrong writer (posture, not the final writer)

Until E3's `era-record` exists an era's bounds have no legitimate writer, so
the package REFUSES to file one anywhere else:

- `timeline_interaction.place_invocation` returns `None` — with a typed
  reason `PLACE_REFUSED_NO_ERA_WRITER` on a new `place_refusal(placed, item)
  -> str | None` helper the hosts can log — when the item's kind is
  `period_bound` (or the `placed` record's target is a `period:` anchor with
  no moment). `_file_placement` records the diagnostic
  `("timeline_place", "place_refused_no_era_writer", session_id)` and
  returns `False`; the answer text still lands as an ordinary capture and the
  conversation is unaffected.
- The `period_bound` row keeps rendering with its probe (ruling 20 moves Play
  to the era in E3; this PR does not remove the row).
- The refusal is visible: `timeline_data()["diagnostics"]` gains one
  counter `place_refused_no_era_writer` so a host can prove the posture held.

Out of scope: `era-record`, `event_mention`, the `era` stage (E3).

### O-E0d — `source_integrity correct --supersedes <correction source_id>`

- `correct` gains `--supersedes <source_id | path>`; the target MUST be an
  existing `type: source_correction` whose `corrects` names the SAME target
  source as the new correction — anything else exits 1 with a typed error
  (`supersedes_target_mismatch`, `supersedes_not_a_correction`,
  `supersedes_missing`). Frontmatter written: `supersedes: <source_id>`,
  `supersedes_path: <rel path>`. The predecessor is NOT edited.
- `classify_story.corrections_for` builds the supersession graph over the
  matching corrections and returns only the LEAVES (corrections no active
  correction supersedes), in filename order — **never recency**. A cycle or a
  `supersedes` pointing outside the target's set is a loud `ValueError` at
  read time (a corrupt edge must not quietly restore a superseded text).
- One authoritative definition: `source_integrity.active_corrections_for(
  source_path) -> list[CorrectionRecord]`; `classify_story.corrections_for`
  and every other reader of corrections (`compile`'s correction injection,
  `wiki` page rendering of "Corrections") call it. Guard test: no other
  module globs `sources/corrections/*.md` and filters on
  `type == "source_correction"` itself.
- `create_linked_source` already marks the target's classification stale;
  a superseding correction goes through the same path, so the stale mark is
  inherited, not re-implemented (the test asserts it fired).

Out of scope: `source_integrity retract` semantics (unchanged); the
classification regeneration itself (E-C / the E7a local keyed run).

## Eight-part answers (design §7 discipline)

| Output | 1 input | 2 writer | 3 identity | 4 correction | 5 derivation | 6 aliases | 7 test | 8 rollout |
|---|---|---|---|---|---|---|---|---|
| Probe text | the unknown row + anchor index | `choose_probe`/`keystone_probe` via `anchor_for_probe` | n/a (pure) | n/a | deterministic table above | none | T-E0-01…04 | pure function; rollback = revert |
| Owner birth node | birth landmark entry → claim receipt | landmark recorder (`entry_subject_mention`) | `_mint_node_id(birth, self)` | birth claim supersession | seeding rule 2 + resolution rule 3 | legacy mention `"birth"` → `self` (rule record) | T-BO-01, T-BO-01b, T-E0-05 | additive; old receipts untouched |
| Place refusal | `placed` + item kind | `place_invocation` | n/a | n/a | rule above | none | T-E0-06…07 | posture; replaced by E3 |
| Superseding correction | predecessor correction + new text | `correct --supersedes` | content-addressed source id | a further supersession | leaves of the supersession graph | none | T-E0-08…12 | additive frontmatter; old readers ignore it (state that as a known window closed by this PR's reader change) |

## Test plan (every negative test is SEEN failing on unmodified main first)

New `tests/test_eras_e0.py` (unittest), subtests named:

- **T-E0-01** residence unknown + birth anchor + a residence anchor → probe
  names the residence, never the birthday.
- **T-E0-02** residence unknown + ONLY a birth anchor → unanchored template
  ("When did you live in Mexico — moving in to moving out?").
- **T-E0-03** `period_bound` unknown never anchors on birth or on itself.
- **T-E0-04** a `moment` unknown may still anchor on birth (regression
  guard against over-correction).
- **T-BO-01** the executed probe (`birth_anchor_probe.py`, adapted to
  `tmp_path`/in-memory index, both claim orderings): owner birth (`"birth"`
  mention) + child birth + owner age claim → the age claim resolves to a date,
  `age_without_birth_anchor` absent, exactly ONE `missing_anchor birth_date`
  work item is NOT emitted.
- **T-BO-01b** legacy `"birth"` receipt + new `"self"` receipt, same owner
  birth → ONE node, reconciled date, no contradiction row.
- **T-E0-05** `entry_subject_mention` mints `self` for `birth` and is
  byte-identical for every other domain (parametrized over
  `LANDMARK_DOMAINS`).
- **T-E0-06** `place_invocation` for a `period_bound` item → `None` +
  `place_refusal` reason; `_file_placement` returns False, writes no
  `state/timeline_placements.json` entry, records the diagnostic.
- **T-E0-07** `moment` items still file exactly as before (golden argv).
- **T-E0-08** `correct --supersedes` writes `supersedes`/`supersedes_path`;
  predecessor bytes unchanged; target classification marked stale.
- **T-E0-09** `corrections_for` returns only leaves; predecessor text absent
  from the classify prompt.
- **T-E0-10** `--supersedes` naming a correction of a DIFFERENT target → exit
  1 `supersedes_target_mismatch`; naming a non-correction → exit 1.
- **T-E0-11** a cycle → loud `ValueError`, nothing restored.
- **T-E0-12** guard: exactly one module reads `sources/corrections/*.md`
  with a `source_correction` filter (`active_corrections_for`).

Run: `python3 -m unittest tests.test_eras_e0 -v` plus the full suite
`python3 -m unittest discover -s tests`. Temp vaults via `tmp_path`-style
`tempfile` — never a literal `/private/tmp` path.

## Launch-and-verify

No viewer surface changes in this PR (the probe text changes on the
Timeline's Unknowns rows; the OSS viewer's Timeline evidence is the platform
walkthrough re-pin named in `P-E0`). Reviewer command:

```bash
python3 system/lifehug.py timeline-data --json | python3 -c 'import json,sys; d=json.load(sys.stdin); print([u["probe"]["text"] for u in d["unknowns"] if u["kind"]=="place_span"])'
```
against the certification fixture vault — no probe contains "you were born".

## Definition of done

- [ ] Code + tests pass locally (`python3 -m unittest discover -s tests`)
- [ ] `system/version.json` bumped to the NEXT FREE slot at green (not in the contract commit); if v235, the `mirror_item` alias deletion rides here
- [ ] ADR 0030 referenced; no new ADR (posture decisions are recorded in `eras.md`)
- [ ] `AGENTS.md`/`CLAUDE.md` thread updated (E0 landed; E7a unblocked)
- [ ] lifehug-platform #686 commented with the release number so `P-E0` can pin it

🤖 Generated with Claude Fable 5 via Claude Code
