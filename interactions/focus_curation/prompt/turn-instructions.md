# Turn instructions — one task template, assembled LAST

This file is assembled last in the per-turn context order (see
`context/manifest.md`), after identity, behavior, and examples. Everything
durable — persona, rules — lives in `prompt/identity.md` and
`prompt/behavior.md`, not here. `{placeholder}` slots are filled by
`system/focus_curation.py`'s `build_curation_prompt()`.

There is exactly one mode (`interaction.yaml`'s `modes: curate`).

---

## Mode: CURATE (`role.worker`)

**Input:**
- `{pending_ideas}` — a JSON array of `{id, type, entity, evidence}` — the
  candidate ids needing a decision (already the residue of the door guards
  and the roster fold — see `prompt/behavior.md`'s "What you are handed").
- `{roster_context}` — a JSON array of settled roster entries
  (`{type, name, aliases, maps_to_focus}`) for identity signal.
- `{existing_focuses}` — a JSON object `{slug: label}` — the only valid
  `map_to_focus` targets.

**Task:** Apply `prompt/behavior.md` in full — partition every id in
`{pending_ideas}` into exactly one of three buckets. Output a single JSON
object, no prose outside it, no field beyond these three keys:

```json
{
  "merge": [["canonical_id", "variant_id"]],
  "map_to_focus": {"idea_id": "existing-focus-slug"},
  "keep": ["idea_id"]
}
```

- `merge` — a list of groups, each a list of 2+ ids, canonical id first
  (rule 4). Every id in a group is judged the same underlying identity.
- `map_to_focus` — `{idea_id: focus_slug}` pairs where the idea IS an
  existing Focus by another name. `focus_slug` must be a key in
  `{existing_focuses}`.
- `keep` — ids that are genuinely distinct, or where the evidence for merge
  or map isn't there. The default, expected bucket for most ids.
- Every id in `{pending_ideas}` appears in exactly one bucket (rule 2) —
  empty arrays/objects are valid when no ideas warrant that bucket.

## Output constraints

- Valid JSON only, no markdown fences, no prose outside the object.
- No field beyond `merge`, `map_to_focus`, `keep` — in particular, **no
  reason, evidence, or notes field** (owner decision — see
  `prompt/behavior.md`'s Output constraints).
- Apply `prompt/behavior.md`'s hard rules in full; this template does not
  restate them.
