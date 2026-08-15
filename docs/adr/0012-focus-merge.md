# ADR 0012: focus-merge — the healing verb for duplicate Focuses

Date: 2026-08-14
Status: Accepted (owner-directed, 2026-08-14)

## Context

ADR 0010 (v168) built three layers that PREVENT new duplicate Focuses
(door guards), fold settled variants (the roster fold), and judge the
first-encounter residue (the focus_curation interaction) — plus
`focus-dupes --report`, a deterministic, zero-write damage list. It said,
explicitly, that merging *existing* duplicates was out of scope and named
this PR as its successor: "if a future PR builds the F4 focus-merge verb
… that PR consumes `focus-dupes --report`'s output, it doesn't supersede
this dedupe design."

That left a real vault in a state nothing could fix. The owner's live
vault carries same-name-modulo-case Focus pairs and "the "-prefix variant
pairs; the long-standing "combine Ambition" ask had no mechanism at all.
Detection without healing is a permanent damage list.

A Focus is not one file. It is a `state/roadmap.json` entry over
question-bank category letters, plus roster entries that point at it, plus
a curation ledger that remembers decisions about it, plus a compiled wiki
page. Merging two is therefore a multi-file transaction over durable user
data — the highest-failure-cost operation in the system, and the reason
this ADR fixes an order and a set of refusals rather than leaving them to
each call site.

## Decision

`system/focus_merge.py` is the single authority for the verb.
`lifehug.py focus-merge <survivor> <loser> [--dry-run] [--adopt-target]`
is a thin wrapper registered in `DIRECT_MUTATION_COMMANDS`, and
`jobs.py`'s `focus-merge` `CommandSpec` is the queue envelope the viewer's
Combine action uses. All three paths run the same function.

### The transaction order is fixed

Plan first, then apply, in this order — a. validate · b. roadmap ·
c. bank · d. rosters · e. curation ledger · f. wiki · g. audit ·
h. recompile sentinel.

Every step is **fully resolved before the first byte is written**:
`plan_merge()` computes each step's concrete edits (which header lines
change to what, which roster indexes re-point, which page is removable)
and raises on anything impossible. This is the guarantee the verb actually
offers, stated honestly: it is *validate-then-write*, not a journaled
transaction with rollback. A merge that cannot fully proceed never starts;
a merge that starts is not undone mid-flight. Because the plan is a pure
value, `--dry-run` prints the identical plan and writes nothing at all —
the dry run is not a simulation of the merge, it *is* the merge minus the
writes.

### Refusals

Two refusals are non-negotiable, both raised in validation, both leaving
the vault byte-for-byte unchanged:

1. **The primary life-story focus, on either side.** It can absorb
   nothing (its categories are the derived A–E main group, system-owned by
   `derive_roadmap`) and it never dies. Refused as survivor *and* as
   loser.
2. **A self-merge.** Distinctness is checked on the resolved *entry*, not
   the strings — `fear` and `Fear` slugify to the same id and therefore
   name the same entry. Merging a focus into itself is a bug, not a no-op.

A third refusal is structural rather than raised: **a hand-authored wiki
page is never removed.** Only a page whose frontmatter says
`origin: focus` is deletable; a missing or foreign `origin` leaves the
file in place and emits a warning, mirroring exactly how
`wiki_compile.cleanup_orphan_entity_pages` refuses to touch anything that
isn't `origin: mention`. The merge still completes everywhere else — a
kept page is a warning, not a failure.

Unknown focus ids also refuse, which makes re-running a completed merge
fail cleanly ("no such focus: the-fear") rather than double-applying.

### Question ids are never renumbered

The bank's doctrine (ids only ever grow; provenance comments elsewhere
reference them by id) is absolute, so a merge never rewrites a question
line. The surviving focus claims the loser's category **letters** as-is —
a Focus already supports multiple categories, so no question needs to
move.

What the bank *does* record is identity. Each of the loser's category
headers **adopts the survivor's own header text verbatim** (display name
and parenthetical), and gains a provenance comment beneath it:

```
## L: Focus — Fear
<!-- merged into fear by focus-merge 2026-08-14 (was "Focus — The Fear") -->
```

Adopting the survivor's header text — rather than inventing an annotation
string — is a correctness requirement, not cosmetics: `derive_focuses`
derives a Focus identity *from the header text*, so a header that still
reads as the loser derives the loser. Copying the survivor's text
verbatim guarantees identical derivation whichever section the category
sits in (focus-group labels come from the name, project-group labels from
the parenthetical — copying both makes the distinction moot), and
`_fold_focus_collisions` collapses the pair. The comment records the
previous name, which is what keeps the rename reversible by hand.

### derive_roadmap gains the settled-identity door

**This is a deliberate addition to ADR 0010's guard set, and the one place
this PR changes shared derivation code.** ADR 0010 placed guards on
`focus_new`, the `roadmap add` CLI, and `derive_focuses`. It did not place
one on `derive_roadmap`, whose "keep user-created focuses that don't map
to a derived category" tail re-appends any prior entry the current
derivation pass didn't produce.

That tail resurrected merged-away focuses. `_fold_focus_collisions` folds
only focuses derived within ONE pass, and it picks the first-seen id — the
one the *bank's category order* happens to yield. When the surviving id
was not that one (merging `fear` INTO `the-fear`), the next
`roadmap-rebuild` derived `fear`, failed to find it in the prior roadmap,
added it as new, and *then* re-appended the survivor — silently
re-splitting a healed vault. Verified empirically before the fix; pinned
in both orientations by `DeriveDoesNotResurrectTests`.

The door: **an existing roadmap entry owns its normalized key.** A newly
derived focus whose id is not already in the roadmap, but whose
`normalized_focus_key` an existing non-primary entry owns, attaches to
that entry instead of materializing beside it
(`roadmap._settled_key_owners` / `_settled_id_for`). The roadmap is the
record of settled Focus identity; derivation may add to it, never
contradict it. The key is still `lifehug_core.normalized_focus_key` — ADR
0010's single definition, not a second one.

### Owner-initiated only

Nothing merges on its own. `focus-dupes --report` gains a hint line per
certain-duplicate pair — the exact `focus-merge` command, with a
deterministic suggested survivor (most categories, ties broken by id) —
but printing a command is not running it. The viewer's Review page gains
a **Duplicate focuses** lane rendering the same detector's groups with a
survivor picker and a Combine button that enqueues the job; the handler
recomputes losers as (rendered group − chosen survivor), so a replayed
POST can only merge within a group the lane actually showed.

**Auto-merge is explicitly deferred.** Autopilot (ADR 0011) approves new
focuses without a human because creating one is additive and reversible
by dismissal. Merging is neither: it drops an entry, rewrites bank
headers, and deletes a page. A future PR may argue for auto-merging the
*certain* class (exact normalized-key collisions, where identity is not a
judgment call); it will need its own ADR, and it inherits this ADR's
order, refusals and audit record rather than replacing them.

### Static themes

`recommend_focuses.THEME_KEYWORDS` includes Ambition. A static-theme
identity can be a merge survivor or loser by name, but the keyword table
is **code, not vault state** — merging two theme focuses never edits it.
Keyword identity is carried by the roster/theme overlay, which the merge
does update: `maps_to_focus` re-points and the loser's name/slug join the
survivor's roster aliases. When no roster entry owns the survivor yet, the
alias pair is recorded in the curation settled ledger
(`state/focus_curation/settled.json`, a new `focus_aliases` key alongside
v168's `decisions`) so the next roster resolve folds it. One ledger, not
two.

### The audit record

`state/focus_merges.json` is **append-only** and a registered
`vault_contract.json` data path (`focus_merges`, tracked, version 1). Each
record carries date, survivor, loser, the loser's label, categories moved,
roster re-points, every file touched, and any warnings. A merge is
irreversible by command; the record is what makes it answerable — "where
did this focus go?" has a durable answer in the vault itself, not only in
git history.

`state/.compile-needed` is touched at the end. The verb never compiles
inline: compiling is the compile step's job, and a merge that also
compiled would make its own failure modes indistinguishable.

## Consequences

- **Binds**: any future Focus-destroying operation (a delete verb, an
  auto-merge, the platform's Combine UI) follows this step order, these
  refusals, the never-renumber doctrine, and writes a `focus_merges`
  record. Any future guard on Focus identity uses
  `normalized_focus_key` and, if it derives, respects the roadmap's
  settled-identity ownership.
- **Forecloses**: renumbering question ids to "tidy up" a merge;
  destructive edits to a merged-away category (its header and questions
  stay, annotated); removing a wiki page the owner wrote by hand;
  auto-merging without a further ADR; a second settled-identity ledger.
- **Delete-when**: superseded if a future PR replaces
  `state/roadmap.json`'s flat focus list with a model that carries
  identity history natively (at which point merging becomes a rename, not
  a transaction). ADR 0010 continues to hold unchanged — this verb
  consumes its detection, it does not supersede its prevention.

## Follow-up (NOT this PR)

Cross-medium parity, riding the next framework pin bump in
`lifehug/lifehug-platform`: the `focus-merge` allowlist entry, the API
endpoint, and the platform's own "Combine" UI. The transaction itself
stays here — the platform orchestrates the package, it never forks it.

🤖 Generated with Claude Opus 5 via Claude Code
