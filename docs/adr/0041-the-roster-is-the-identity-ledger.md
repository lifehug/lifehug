# ADR 0041: The roster is the identity ledger

Date: 2026-10-03
Status: ratified (owner, 2026-10-03)

## Context

On 2026-10-03 the owner's daily question read: *"Katie Ann Merrill appears in
your records only as a name under partnerships, with no story behind it yet —
what do you remember about the day you first met her?"* Katie is his wife; her
page cites 30 sources. The chain (lifehug-platform
`docs/pr-specs/roster/00-roster-identity.md` §2, read off the vault and both
repos): the wedding landmark promoted a one-line `partnerships` source naming
her in full; the classifier minted a candidate from it; and the name joined
nothing, because the roster row for his wife is `Katie Taylor` (aliases `wife`,
`my wife`, 0 answers) and **three defects** in the roster kept it that way:

1. `entity_roster.LANDMARK_RELATION_DOMAINS` read only `family` and
   `children` — `partnerships` reached no row — and where a landmark name WAS
   read, `known()` matched the existing row by first token and then **skipped**
   it instead of filing the new full name as an alias.
2. `entity-verdict`'s alias union (`--alias`, and `--maps-to`'s fold of the
   loser's names onto the survivor) wrote blindly. The package's collision
   rule, `roster_relations.alias_decision` (one alias claimed by two entities
   binds to NEITHER), was applied only to places.
3. A row's `unique_answers`/`score` moved only when the monthly `rosters` model
   call ran — which failed on budget on 2026-09-01 and 2026-10-01 — so a row
   without the alias people actually use never earned a mention, and a fold
   was invisible for a month.

The owner, seeing the roster: *"there are a lot of duplicates here. We could
combine them and say, 'This is that person.'"* (tracking lifehug-platform#978).

## Decision

**The roster is the owner-curated identity ledger** for people — and the same
rules bind the other four roster types. No second store, no second fold.

- **A fold is a pointer, never a deletion.** `entity-verdict <type> <loser>
  clear --maps-to <survivor>` (the fold that already existed, ADR 0012's
  "retire with a pointer" shape) keeps the loser's row with
  `maps_to_focus = <survivor>` and unions its name and aliases onto the
  survivor. The count fold (`recommend_focuses._roster_alias_fold_map`) reads a
  pointer row's spellings as the survivor's.
- **An alias is a decision under the collision rule.** Every alias
  `entity-verdict` writes goes through `roster_relations.alias_decision`. A
  collision refuses the WHOLE verdict (no partial union, the roster file
  untouched), prints the package's `identity_uncertain` result with both
  `candidates`, and exits 2. A row already folded INTO the target is the same
  identity, never a rival claimant. The host renders the two claimants and
  asks; it never picks.
- **Landmark names join the roster through aliases.** `partnerships` is a
  landmark relation domain (relationship `spouse`; its date is the wedding,
  never a birth). A landmark name the roster already answers to — by spelling,
  or by sharing its first token with exactly ONE row — is filed as an alias of
  that row through the same writer (`entity-roster --ensure-introduced`, the
  seat the platform's daily step already runs). Two such rows, or one row that
  states a different relationship, are reported as contested; nothing is
  guessed and nothing is written.
- **Counts are a deterministic join.** `entity-roster --type <t> --recount`
  recomputes `unique_answers`/`score` through `_build_entity_stats` →
  `_fold_stats_through_roster` → `_best_stats`, with no model call, writing
  only when a count moved (so it is byte-identical run twice). A successful
  `--maps-to`/`--alias` and an `--ensure-introduced` that filed or folded
  anything run it.

Considered and rejected: a separate merge ledger or "merge wizard" (two writers
for one roster file — the recurring-defect doctrine's failure shape); deleting
the loser row (loses the record of what was folded, and makes the fold
irreversible); folding on first token without a relationship check (a father
"James Taylor" is not the son "James Everett Taylor").

## Consequences

- Binds: every writer of a roster alias decides it through
  `roster_relations.alias_decision`; a future alias writer that unions blindly
  is a defect. A fold never removes a row.
- Binds: hosts treat `entity-verdict` exit 2 as a question for the owner (two
  named claimants), never as an error to retry or a choice to make.
- Recount changes counts only — never `qualifies`, `page_eligible`, an owner
  verdict or an identity fact. Its counts come from the full detector join;
  the monthly model refresh still derives its counts from the pending
  recommendations, so a monthly run can lower a recounted row until the next
  recount. Named here rather than silently reconciled; unifying the two count
  sources is a follow-up.
- Forecloses: cross-type folds (a person never folds into a place) and bulk
  folds through this verb.
- Delete-when: a durable, source-backed identity-decision record replaces the
  roster JSON as the authority (`roster_relations`' module docstring names that
  gap).
