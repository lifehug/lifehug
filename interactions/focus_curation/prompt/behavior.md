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
