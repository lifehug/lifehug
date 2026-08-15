# ADR 0013: Entity owner verdicts — graduate-now and not-a-page as settled decisions

Date: 2026-08-15
Status: Accepted (owner-directed, 2026-08-15)

## Context

Entity graduation (`system/entity_roster.py`, `wiki_compile.plan_entities`) is
one of the system's fully automatic Loop stages: an AI-curated roster
resolves detected mentions into clean entities, `normalize()` computes
`page_eligible` from type-specific thresholds (`THRESHOLDS` — person
score/answers, place/period/theme a qualifies gate, object judged on
symbolic meaning alone), and compile graduates each page-eligible,
unmapped entity into a node page once it clears a real-mention bar
(`_ENTITY_MIN_MENTIONS`). This is the Convergence Principle's floor (ADR
0006) working exactly as designed — answering alone makes the wiki grow,
no human required.

The floor was never the gap. Two other lanes already pair their automatic
floor with an owner accelerator/veto: focus-duplicate-curation's
promote-override on a candidate (ADR 0010) and focus-autopilot's
dismiss-forever on a Focus idea (ADR 0011). Entities had neither. An owner
who already knows an entity matters — a name that will obviously matter to
the story but hasn't cleared the second-mention bar yet — has to wait. And
the AI keeps re-proposing the same junk class (a fragment, a wrong-type
detection, a role word the owner has already judged not worth a page) every
refresh, with no way to make that judgment stick.

## Decision

Roster entries (any type) gain an optional field, `owner_verdict:
"graduate" | "never"` — absent means "fully automatic," the pre-existing
behavior, completely unchanged. Both values are settled decisions: once
set, `system/entity_roster.py`'s `normalize()` and
`apply_previous_decisions()` enforce them as facts the AI can never remove,
overturn, or silently drop, on every subsequent refresh.

### The two verdicts

- **`graduate`** — `page_eligible` is forced true regardless of
  score/answer thresholds, with one absolute condition: the entity must be
  **unmapped**. `maps_to_focus` always wins — a mapped entity enriches its
  Focus, not a standalone page, and `graduate` cannot override that (the
  CLI refuses to *set* the verdict on a mapped entity; `normalize()` holds
  the same guard continuously, in case a later refresh maps an
  already-graduated one). Compile's real-mention bar
  (`_ENTITY_MIN_MENTIONS`) drops to **>= 1** for a graduated entity — the
  owner's accelerator shouldn't have to wait for a type's normal bar (2 for
  place/period) — but the floor under that is absolute: **zero real
  mentions still means no page**, for any entity, verdict or not. A page
  needs at least one source.
- **`never`** — `page_eligible` is forced false, permanently. This is
  entirely about the *page*, not the *identity*: the entity **remains on
  the roster** — attribution and alias folding continue exactly as before,
  so a later mention of the same person/place still resolves to the same
  canonical entry. It simply never gets a standalone page, and the
  candidates lane stops proposing it.

### The settled-decision mechanism

The verdict lives **on the roster record** — never a parallel store,
exactly like ADR 0012's framing of the roster as the settled-identity store
for entities. Two functions carry the whole guarantee:

- `normalize()` computes `page_eligible` from the AI's/deterministic
  judgment *first* (unchanged), then applies the verdict override
  (`apply_owner_verdict`) — `graduate`/`never` win regardless of what
  `qualifies`, score, or answers say.
- `apply_previous_decisions()` — the existing safety net that folds raw AI
  output back onto the previous roster's settled identity — now also folds
  a previous entry's `owner_verdict` onto its matched slot, *ignoring*
  whatever the raw entry says or omits. And because the AI's fresh
  candidate list is score/detector-driven, a low- or zero-score
  owner-graduated entity may not even reach the prompt on a given refresh
  — so a previous entry carrying an `owner_verdict` survives **even when no
  raw entry matches it at all**, including an entirely empty refresh. This
  is the one place this ADR changes shared derivation code, and it is
  deliberately narrow: only entries with a settled verdict get this
  survival guarantee: an *unverdicted* entity that an empty/omitting
  refresh drops still drops, exactly as before.

Nothing here touches automatic graduation's thresholds, its per-type rules,
or the AI-curation prompt. The floor is untouched; this is purely the
accelerator/veto half of the Convergence Principle (ADR 0006).

### The verb

`lifehug.py entity-verdict <type> <slug> graduate|never|clear` — one
command, three verdicts (`clear` returns to fully automatic, recomputed via
`entity_roster.base_page_eligible`, the same formula `normalize()` uses; a
`clear` on an entity with no verdict is a harmless no-op recompute).
`system/entity_verdict.py` is the runtime: a single-entity, single-file
roster mutation, atomic (`lifehug_core.write_json`), refusing before any
write on an unknown type/slug or `graduate` on a mapped entity. It is
registered in `lifehug.py`'s `DIRECT_MUTATION_COMMANDS` and as a `jobs.py`
`CommandSpec` (`entity-verdict`) — the viewer's actions enqueue through the
same durable single-writer queue every other mutation does. Retry safety is
`"never"`, matching every other direct roster/vault mutator (focus-merge,
focus-dismiss, ...) rather than `"idempotent"`: the registry reserves that
classification for `compile` alone, even though re-applying the same
verdict does converge to the same state — an ambiguous outcome here is not
auto-replayed.

### The viewer

The Review page's entity-candidates lane (previously pure FYI — "no action
needed") gains, per candidate row, the two actions via the existing
action-form/job-queue idiom (mirroring focus-dismiss's shape), and a
distance-to-graduation sort: an entity the AI has already marked
`qualifies` sorts by how close its score is to the type's threshold
(`min_score − score`, closest first); a `qualifies`-pending entity — the AI
hasn't judged it worthy yet, and no amount of extra evidence alone fixes
that — sorts after every qualifying one. A `never`-verdicted entity has no
further viewer affordance at all: it disappears from the candidates table
and does not reappear anywhere in the lane, matching the contract's
"suppressed entities disappear from the lane" precisely; `entity-verdict
... clear` by CLI is the only way to reconsider one. A `graduate`-verdicted
entity, by contrast, appears in a small **Owner-decided** roster-browser
table with a small `owner` tag and a Clear action — that table is
graduate-only by design, since a vetoed entity is meant to be invisible,
not merely unclickable.

## Consequences

- **Binds**: any future entity-graduation change (a new type, a changed
  threshold, a changed mention bar) must preserve `owner_verdict`'s
  override semantics — `graduate` forces eligibility (mapped always wins),
  `never` forces suppression without touching identity, and both survive
  every refresh including an empty one. Any future roster-level owner
  override reuses this settled-decision mechanism (verdict on the record,
  enforced in `normalize()`/`apply_previous_decisions()`) rather than a
  parallel ledger — the same "roster IS the settled-identity store" framing
  ADR 0012 established for merges.
- **Forecloses**: a reason/evidence field on the verdict (no reason capture
  anywhere in this system's curation surfaces, per ADR 0010's posture,
  itself consistent with the conversational future the owner has separately
  directed for dismiss reasons, platform issue lifehug-platform#469); a
  deterministic no-AI path that infers a verdict; changing automatic
  graduation's thresholds or per-type rules (explicitly out of scope).
- **Delete-when**: superseded if a future PR unifies every roster-level
  owner override (this one, focus-dismiss, candidate promote/dismiss) into
  one shared settled-decision primitive — that PR's ADR would supersede
  this one's Decision, not merely extend it.

## Follow-up (NOT this PR)

Cross-medium parity, riding the next framework pin bump in
`lifehug/lifehug-platform`: the `entity-verdict` allowlist entry, the API
endpoint, and the platform's own graduate-now/not-a-page UI on its entity
surface. The transaction itself stays here — the platform orchestrates the
package, it never forks it.

🤖 Generated with Claude Sonnet 5 via Claude Code
