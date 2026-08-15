---
title: Focus Curation
parent: The Interaction Pattern
grand_parent: Handbook
nav_order: 3
---

# Focus Curation

## 1. What it does & what it's for

This is the seated interaction behind the smallest, most narrowly-scoped
judgment call of the three: given a pending Focus idea like "Betty Jo"
and another pending idea "Betty Jo Taylor," are these the same person
under two different surface names, or genuinely two different ideas? Read
[The Interaction Pattern](index.md) first for what "seated" means; this
page is the specific role definition for that one identity-resolution
call, described fully by [Focuses & the Autopilot](../focuses.md) §2/§3
as the third of three dedupe layers.

The main use case, told from the vault's own accumulating record: across
a few months, you've mentioned your Focus-worthy relative sometimes as
"Betty Jo" and sometimes, more fully, as "Betty Jo Taylor." Two
deterministic layers already run before this interaction ever sees
anything — door guards catch exact-name-modulo-case collisions, and the
monthly-curated entity roster's alias fold catches any variant the roster
has already settled. Neither of those can resolve "Betty Jo" vs. "Betty
Jo Taylor" on its own the first time it comes up, because there's no
settled roster alias for it yet — this is a *first-encounter* near-name
pair, and this interaction is the one place in the system a model is
asked to look at the evidence (the two labels, the settled roster
context, the existing Focus list) and decide: merge them into one, map
one onto an existing Focus, or keep them apart because there isn't
genuinely enough evidence yet. Whichever it decides, the record moves
forward without either idea sitting duplicated and diluted forever, and
without a human ever needing to notice the collision.

## 2. The nouns

**Merge / map_to_focus / keep** — the interaction's entire output
vocabulary: a partition of every handed pending-idea id into exactly one
of three buckets. `merge` — two or more ids are the same identity, listed
canonical-first (fullest, most complete name first — "Betty Jo Taylor,"
not "Betty Jo"). `map_to_focus` — an idea IS an existing Focus by another
name, not merely related to it. `keep` — genuinely distinct, or the
evidence for merge/map isn't there; this is the correct, cost-free
default when unsure, never treated as a lesser answer.

**The settled-decision ledger** — `state/focus_curation/settled.json`, a
per-id record of every id this interaction has ever decided on (in any of
the three buckets), so a correctly-kept-apart pair is never re-presented
to the model on a future run. This is a deliberate, documented
simplification: once an id is settled, it's settled permanently, even if
it would later form a genuinely new near-name pair with a different idea
— trading a theoretical missed re-judgment for guaranteed convergence.

**No reason capture, anywhere** — the interaction's schema carries no
reason, evidence, or notes field of any kind; a verdict with a fourth key
is malformed, not more thorough. This is a direct owner ruling
([ADR 0010](https://github.com/lifehug/lifehug/blob/main/docs/adr/0010-focus-duplicate-curation.md),
"No reason context, anywhere"), narrower than but consistent with [ADR
0007](https://github.com/lifehug/lifehug/blob/main/docs/adr/0007-question-judgment-interaction.md)/[ADR
0009](https://github.com/lifehug/lifehug/blob/main/docs/adr/0009-decisions-feed-the-loop.md)'s
own no-reason-capture posture for `question_judgment`'s learned-amendments
file — here there is no learning file at all to amend, only the settled
ledger above. [Decisions & Learning](../decisions-and-learning.md) covers
this ruling's fuller context, since it's the same owner decision that
shaped what this page's sibling interaction is and isn't allowed to
learn from.

**The three-layer dedupe** this interaction is the third of — **door
guards** (deterministic, always on, kill the exact-name-modulo-case
class) and the **roster fold** (deterministic, always on, catches
settled variants the monthly entity-roster curation already resolved) —
are [Focuses & the Autopilot](../focuses.md)'s vocabulary, not
re-defined here; this page covers only the third layer.

Shared vocabulary this page relies on without redefining:
**[Interaction](index.md)**, **[Focus](../glossary.md)**, and
**[Entity](../glossary.md)** are defined on their own pages.

## 3–4. The behavior contract

> **This IS the prompt** — the file below is simultaneously what gets
> sent to the seated model and the documentation a person reads (per
> [The Interaction Pattern](index.md) §3's doc-drift guarantee). Embedded
> verbatim from `interactions/focus_curation/prompt/behavior.md` at
> v174 — `tests/test_handbook_parity.py`'s `FocusCurationEmbedTests`
> asserts this block byte-matches the source file, so it cannot drift
> from what the model actually reads.

<!-- embed: interactions/focus_curation/prompt/behavior.md -->
# Behavior contract — the curation rubric

This is the load-bearing file: what a model curating Focus/idea duplicate
variants is graded against. Applies to `mode: curate` (the only mode this
interaction has — see `prompt/turn-instructions.md`).

## What you are handed

Every call hands you exactly three things (see
`prompt/turn-instructions.md`'s `{placeholder}` slots):

- `pending_ideas` — the candidate ids and labels needing a decision. These
  are ALREADY the residue of two deterministic layers (door guards, the
  roster fold) — never re-decide an exact-name-modulo-case pair; if you see
  one, it means a settled roster alias doesn't exist for it yet, not that
  the deterministic layer failed.
- `roster_context` — settled entity-roster identity signal (names, aliases,
  `maps_to_focus`) for the same types, so you have real identity evidence to
  reason from, not just string shape.
- `existing_focuses` — `{slug: label}` of every current Focus, the only
  valid targets for `map_to_focus`.

## Hard rules

1. **Never invent an entity, an id, or a slug.** Every id in your output
   must be one you were handed in `pending_ideas`; every `map_to_focus`
   value must be one of the slugs in `existing_focuses`. An id or slug that
   doesn't appear in what you were handed is a hard fail — the runtime
   treats the whole verdict as malformed (see `evals/lints.yaml`), not a
   partial success.
2. **Partition, don't select.** Every id handed to you in `pending_ideas`
   must appear in EXACTLY ONE of `merge`, `map_to_focus`, or `keep` — never
   omitted, never duplicated across buckets. A verdict that drops an id or
   places it twice is malformed.
3. **A `merge` group needs at least two ids.** A single-id "group" is not a
   merge — put that id in `keep` instead.
4. **Canonical-first ordering inside a `merge` group.** List the fullest,
   most complete identity first ("Betty Jo Taylor", not "Betty Jo", when
   both name the same person) — the runtime treats the first id as
   canonical and the rest as its variants, without a second inference to
   make.
5. **Merge requires identity evidence, not topical overlap.** Two ideas
   about the same subject are not automatically the same identity — "Fear"
   and "Anxiety" might be two different themes, or one theme under two
   names; look at `roster_context` and the labels themselves for genuine
   identity signal (a shared proper name, a documented alias, a token
   subset like "Betty Jo" ⊂ "Betty Jo Taylor") before merging.
6. **`map_to_focus` requires the idea to BE the existing Focus, not merely
   related to it.** An idea about "Dad's Workshop" is not automatically the
   same as a "Dad" Focus — map only when the idea and the Focus are
   evidently the same identity by another name.
7. **Respect what the deterministic layers already settled.** Anything
   present in `roster_context` as an already-merged alias is settled — never
   propose re-splitting it, even if the handed ideas' surface text looks
   separable.
8. **Unsure → `keep`.** When the evidence for merge or map isn't genuinely
   there, `keep` is the correct, default verdict — it costs nothing (the
   idea simply stays pending for a future pass with more evidence) and is
   never treated as a lesser or incomplete answer.

## Output constraints

No field beyond the three buckets — `merge`, `map_to_focus`, `keep` — see
`prompt/turn-instructions.md`. In particular: **no reason, evidence, or
notes field of any kind** (owner decision, `README.md` §4) — a verdict that
adds one is not more thorough, it is malformed. Valid JSON only, no markdown
fences, no prose outside the object.
<!-- /embed -->

## 5. In the loop

**What feeds it:** `build_pending_idea_list()` — genuinely
first-encounter near-name pairs (`focus_dupes.near_name_pairs`'s idea-vs-
idea and idea-vs-focus participants), minus anything already settled in a
prior run, minus anything the roster fold already resolved before this
interaction is ever consulted. **What it feeds:** `apply_verdicts()`
deterministically applies a validated partition — a `merge` dismisses the
losing pending-idea record(s) with `dismissed_by: "curation"`, a `map`
dismisses with a structured `mapped_to_focus` fact, a `keep` is a no-op —
so a regenerated `recommend()` run can never silently re-split what this
interaction already settled; every decided id (any bucket) is additionally
logged to the settled ledger (§2). **How it self-improves:** it doesn't,
by design — there is no `role.planner`, no rubric-edit mode, and no
learning file, because there is nothing here for a weekly pass to amend
(§2's "no reason capture" note). This is a deliberate, owner-ratified
scope limit, not an oversight: a low-stakes, fully reversible relabeling
call has no rubric worth calibrating.

**Classification (Convergence Principle):** this interaction is
explicitly the smallest, least-autonomous of the three by design — it is
purely the Convergence Principle's **accelerator** for one narrow
judgment call, never its floor. The floor is already satisfied by the two
deterministic layers beneath it (door guards, the roster fold): absent
AI (a keyless machine with no completed agent task), the roster fold is
where dedupe stops — a near-name pair simply sits apart, correctly,
rather than being merged on a guess. **There is no deterministic merge
fallback**, unlike every other interaction's keyless path in this system
— a deliberate difference [ADR 0010](https://github.com/lifehug/lifehug/blob/main/docs/adr/0010-focus-duplicate-curation.md)
states outright, because a wrong guess here (two different people merged
into one) is a worse failure mode than two genuinely-the-same ideas
sitting apart a little longer.

## 6. Where it lives

| Concern | Location |
|---|---|
| Definition | `interactions/focus_curation/` |
| Behavior contract (embedded above) | `interactions/focus_curation/prompt/behavior.md` |
| The loader/runtime | `system/focus_curation.py` — `build_pending_idea_list()`, `build_roster_context()`, `build_existing_focuses()`, `build_curation_prompt()`, `run_curation()`, `apply_verdicts()` |
| Shared identity key (used by every dedupe layer, not just this one) | `lifehug_core.normalized_focus_key()`, `entity_roster._entity_keys()` |
| Near-name pair detector (shared with `focus-dupes --report`) | `focus_dupes.near_name_pairs()` |
| Settled-decision ledger | `state/focus_curation/settled.json` |
| CLI | `lifehug.py focus-curate [--dry-run \| --emit-task PATH \| --from-response PATH]` |
| Guard tests | `tests/test_focus_duplicate_curation.py` (repo-verify exact name before citing in a PR) |

**Change-safely notes.** `apply_verdicts()` is the only place a merge or
map is ever actually applied — a future caller that dismisses a pending
idea based on this interaction's output without going through it would
bypass the settled-ledger logging §5 depends on to guarantee
convergence. No engine reads `evals/lints.yaml` yet as of this page — see
[The Interaction Pattern](index.md) §3 — so this interaction has no
seated model today; its behavior contract is nonetheless already
load-bearing documentation, which is exactly the doc-drift guarantee the
pattern provides independent of whether a model has been seated.

## 7. Decisions

- [ADR 0010 — Focus Duplicate Curation](https://github.com/lifehug/lifehug/blob/main/docs/adr/0010-focus-duplicate-curation.md) — this interaction's founding decision: the three-layer dedupe, the "no reason context, anywhere" ruling, and the no-deterministic-fallback posture.
- `interactions/focus_curation/README.md` — the full mission tie-in and owner decisions this page's §1/§2 summarize.
- [Focuses & the Autopilot](../focuses.md) §2/§3 — the two deterministic layers beneath this interaction, and where this interaction sits in that dedupe sequence.
- [The Interaction Pattern](index.md) — the shared pattern this page is one instance of.
