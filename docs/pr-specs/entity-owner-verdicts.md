# Contract: entity-owner-verdicts

## Why

Owner-directed (2026-08-15): the entity-candidates lane gains its
accelerator. Graduation stays fully automatic (the convergence floor,
untouched); the owner gains two overrides mirroring the candidate lane's
promote-override and the focus lane's permanent dismiss: **graduate now**
(an entity the owner knows matters shouldn't wait for its second
mention) and **not a page** (a permanent veto for the junk class the
AI keeps re-considering). Both are settled decisions the monthly AI
refresh must never overturn.

## Binding facts (as of origin/main v172)

- Roster: `system/entity_roster.py` — `normalize()` computes
  `page_eligible` (person: qualifies AND unmapped AND score ≥ 8.0 AND
  answers ≥ 2 — `THRESHOLDS`; other types: qualifies AND unmapped);
  `apply_previous_decisions()` folds AI output onto settled identities;
  `JUNK` blocklist; roster files `state/entity_rosters/<type>.json`
  (envelope: version/type/resolved_at/entities[]).
- Compile: `system/wiki_compile.py` — `plan_entities()` skips
  `!page_eligible`; `_ENTITY_MIN_MENTIONS` (person 1, place 2, period 2,
  object 1) real-mention bar; `cleanup_orphan_entity_pages()` removes
  demoted `origin: mention` pages.
- Viewer: Review's entity lane is preview-only
  (`_entities_section_html`); actions idiom = `_candidate_actions`.
- Curation settled ledger precedent: `state/focus_curation/settled.json`
  (v168) — but entity verdicts belong ON the roster records (the roster
  IS the settled-identity store for entities).
- Single-writer/`DIRECT_MUTATION_COMMANDS` conventions per
  focus-autopilot/focus-merge.
- Version bumps to next free above origin/main at PR time (expect 173;
  a docs PR may race — the train renumbers). 21 pre-existing env
  failures in this workspace; zero delta; CI arbiter.

## Scope

1. **The field**: roster entries gain optional
   `owner_verdict: "graduate" | "never"` (absent = normal). Semantics,
   enforced in `normalize()` AFTER the AI's judgment and by
   `apply_previous_decisions()` as a settled fact the AI can never
   remove or change:
   - `graduate`: `page_eligible` forced true regardless of
     score/answer thresholds (the entity must still be unmapped —
     `maps_to_focus` wins, refuse the verdict on a mapped entity);
     compile's real-mention bar drops to ≥ 1 for it (a page needs at
     least one source; never zero-mention pages).
   - `never`: `page_eligible` forced false forever; the entity REMAINS
     on the roster (attribution/alias folding continues — suppression
     is about pages, not identity); the candidates lane and viewer
     exclude it from the preview.
2. **The verb**: `entity-verdict <type> <slug> graduate|never|clear`
   (one command, three verdicts; `clear` returns to automatic) — thin
   `lifehug.py` wrapper, `DIRECT_MUTATION_COMMANDS` registration, writes
   the roster file atomically, prints the resulting eligibility.
   Refusals: unknown type/slug, mapped entity for `graduate`.
3. **Viewer**: the entity lane's candidate rows gain the two actions
   (graduate-now / not-a-page) via the existing action-form idiom +
   job-queue enqueue; suppressed entities disappear from the lane;
   graduated-by-owner entities show a small `owner` tag in the roster
   browser. Sorting: candidates orderd by distance-to-graduation
   (threshold − score for scored types; qualifies-pending types after),
   closest first. Walkthrough REQUIRED (visible surface).
4. **ADR 0013**: the verdict field, its settled-decision semantics, the
   mention-bar exception for `graduate`, the pages-not-identity meaning
   of `never`, and the floor/accelerator framing.
5. Version bump; vault_contract unchanged (rosters already contracted);
   framework_files for any new shipped file.

Out: platform surfaces (pin-bump riders, next bump) · alias-editing UI
(conversational future, platform#469) · any change to automatic
graduation thresholds.

## Test plan

`tests/test_entity_owner_verdicts.py`: graduate forces eligibility below
thresholds; never forces ineligibility above them; both survive a
simulated AI refresh (apply_previous_decisions with contradicting raw
output); clear restores automatic; mapped-entity graduate refused;
compile honors the ≥1 mention bar for owner-graduated (0 mentions → no
page); cleanup never removes an owner-graduated page while the verdict
stands; suppressed entities vanish from the lane count; verdict CLI
refusals. Update existing roster/lane tests as needed. Viewer
walkthrough `tests/walkthrough_entity_verdicts.py` + make target: both
actions on a synthetic vault, stills both viewports + GIF, SHA-pinned
embeds. Zero delta vs the 21-failure baseline.

## Definition of done

Per TEMPLATE.md: version bump, ADR 0013, CLAUDE.md entity-graduation
glossary entry updated, walkthrough evidence embedded, platform riders
recorded in the ADR for the next pin bump.

🤖 Contract authored by Claude Fable 5 via Claude Code
