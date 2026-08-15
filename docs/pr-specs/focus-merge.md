# Contract: focus-merge

## Why

Owner-directed (2026-08-14). Duplicate-curation (ADR 0010, v168)
prevents NEW duplicate focuses and DETECTS existing ones
(`focus-dupes --report`), but nothing can HEAL them: the owner's live
vault carries same-name-modulo-case focus pairs and variant pairs, and
the long-standing "combine Ambition" ask has no mechanism. This PR adds
the one missing verb: `focus-merge` — a deliberate, auditable,
multi-file transaction that fuses two focuses into one.

## Binding facts (as of origin/main v168)

- Detection: `system/focus_dupes.py` (certain / near-name / folding
  sections) — this PR CONSUMES it, never re-derives detection.
- Normalization authority: `lifehug_core.normalized_focus_key()`.
- A focus = metadata over question-bank category letters
  (`state/roadmap.json` entry: id, label, type, tier, target_depth, cap,
  phase, categories[], wiki_node, neighborhoods[]; `_USER_FIELDS`
  preserved by derive). The bank (`system/question-bank.md`) owns
  `## <letter>: <name>` headers and question ids `<letter><n>`.
- Rosters: `state/entity_rosters/<type>.json` entries carry
  `maps_to_focus: <slug>`; settled-decisions fold
  (`apply_previous_decisions`) treats prior identities as stable.
- Curation ledger: `state/focus_curation/settled.json` (v168).
- Wiki: focus pages under `wiki/<type>/<slug>.md`;
  `cleanup_orphan_entity_pages` removes stale `origin: mention` pages at
  compile; focus-owned pages are `origin: focus`.
- Neighborhoods: `state/neighborhoods.json` records carry topic/slug
  ties; seeded focus questions live under `nbhd-<slug>` ids.
- Question ids are NEVER renumbered (bank doctrine: only grows;
  provenance comments reference ids). Therefore a merge NEVER rewrites
  question ids — the surviving focus claims the loser's category
  LETTERS as-is (a focus already supports multiple categories).
- Static themes: `recommend_focuses.THEME_KEYWORDS` includes Ambition —
  a static-theme identity can be a merge SURVIVOR or LOSER by name, but
  the static keyword entry itself is code, not vault state; merging two
  theme focuses does not edit code (the roster/theme overlay handles
  keyword identity — record the interaction in the ADR).
- "Ambition" is one of the owner's known duplicate/merge targets.
- Mutations converge through the single-writer job queue
  (`system/jobs.py`); `DIRECT_MUTATION_COMMANDS` registration in
  `lifehug.py` (see focus-autopilot's entry for the pattern).
- Version bumps to next free above origin/main at PR time (expect 169);
  changelog STRING; 21 pre-existing env failures in this workspace —
  zero delta; CI arbiter.

## Scope

1. **The verb** — `focus_merge(survivor_id, loser_id, *, dry_run)` in a
   new `system/focus_merge.py` (single authority; `lifehug.py
   focus-merge <survivor> <loser> [--dry-run]` thin wrapper, registered
   as a direct mutation command). The transaction, in order, all-or-
   nothing per step with a printed plan first:
   a. Validate: both exist, distinct, neither primary (`my-life` can
      absorb nothing and never dies — refuse), survivor ≠ loser after
      normalization sanity.
   b. Roadmap: union loser's `categories` into survivor's (order
      preserved, no duplicates); merge `neighborhoods` lists; survivor's
      user fields (tier/objective/deliverable/target_depth/cap/phase)
      UNCHANGED unless `--adopt-target` recomputes target_depth as
      max(survivor, loser); drop the loser's entry.
   c. Bank: the loser's category headers gain a provenance comment line
      (`<!-- merged into <survivor-id> by focus-merge YYYY-MM-DD -->`)
      and their display name is annotated, never renamed destructively;
      question ids untouched.
   d. Rosters: every entry whose `maps_to_focus == loser` re-points to
      survivor; the loser's name/slug join the survivor's roster
      aliases (find the survivor's roster entry by key; if none exists,
      record the alias pair in the curation settled ledger instead so
      the next roster resolve folds it).
   e. Curation ledger: record the merge as a settled identity decision
      (so recommend()/curation can never re-propose the loser).
   f. Wiki: delete the loser's `wiki_node` page file if it is
      focus-origin (`origin: focus` frontmatter) — the survivor's page
      absorbs at next compile; log to `wiki/log.md`; never touch
      hand-authored pages (missing/foreign origin → leave + warn).
   g. Emit a merge record to `state/focus_merges.json` (append-only
      audit: date, survivor, loser, categories moved, roster repoints,
      files touched) — new vault_contract entry.
   h. Trigger recompile flag (the existing compile-needed convention) —
      never compile inline.
   `--dry-run` prints the full plan (every step's concrete edits) and
   writes nothing.
2. **Detection wiring**: `focus-dupes --report` gains a closing hint
   line per certain-duplicate pair: the exact `focus-merge` command to
   run. No auto-merge — merging is owner-initiated in this PR
   (autopilot-adjacent auto-merge is a future decision; note in ADR).
3. **Viewer affordance (OSS)**: the Review lane's focus section (or the
   focuses workbench view if that's where focus management lives in the
   viewer — follow the existing action-form idiom of
   `_candidate_actions`) gains a "Combine…" action on certain-duplicate
   pairs surfaced from the dupes report: pick survivor, confirm,
   enqueue the merge through the job queue. Walkthrough REQUIRED
   (serve_wiki visible surface).
4. **ADR 0012**: the transaction order, refusal rules (primary,
   hand-authored wiki pages), the no-renumber doctrine, static-theme
   interaction, the owner-initiated-only posture and the auto-merge
   deferral, audit record shape.
5. Version bump + changelog + vault_contract (`focus_merges` +
   settled-ledger reuse) + framework_files for new shipped files.

Platform note (NOT this PR): allowlist entry, endpoint, and the
platform "Combine" UI ride the next pin bump; record as a follow-up
line in the ADR.

## Test plan

`tests/test_focus_merge.py`, subtests: happy merge (categories
unioned, loser gone, roster repointed, aliases recorded, ledger entry,
audit record, wiki page removed, bank annotated, ids untouched) ·
dry-run writes nothing and prints every planned step · refuse primary
(either side) · refuse unknown/self · hand-authored wiki page left with
warning · loser with no roster entry → settled-ledger alias path ·
merge is idempotent-safe (re-running errors cleanly on missing loser) ·
recompile flag set · derive_roadmap after merge does not resurrect the
loser (the door guard + fold from v168 make this hold — regression
subtest). Update dupes-report tests for the hint line. Viewer
walkthrough `tests/walkthrough_focus_merge.py` + make target: the
Combine flow on a synthetic fear/Fear vault, before/after stills both
viewports + GIF, SHA-pinned embed in the PR comment. Baseline 21 env
failures — zero delta.

## Definition of done

Per TEMPLATE.md: version bump, ADR 0012, CLAUDE.md merge-doctrine note,
walkthrough evidence embedded, and the platform follow-up recorded
(pin-bump rider: allowlist + endpoint + Combine UI).

🤖 Contract authored by Claude Fable 5 via Claude Code
