# Rubrics — judge questions for prompt/behavior.md's hard rules

Binary (yes/no) per-clause judge rubrics, keyed 1:1 to `prompt/behavior.md`'s
eight hard rules. A strong judge model answers each question over a batch of
CURATE verdicts (not a single verdict in isolation) — "Yes" means the
property held across the whole batch; a single violation is a "no".

1. **Never invent an entity, id, or slug.** Does every id and slug in every
   verdict in the batch appear in that call's `pending_ideas` /
   `existing_focuses`?
2. **Partition, don't select.** Does every id handed to the model in each
   call appear in exactly one of `merge` / `map_to_focus` / `keep` in that
   call's verdict?
3. **Merge groups need 2+ ids.** Does every `merge` group in the batch have
   at least two ids?
4. **Canonical-first ordering.** Is the first id in every `merge` group the
   fuller/more-complete identity, per the batch's `roster_context`?
5. **Merge requires identity evidence, not topical overlap.** Does every
   `merge` group in the batch have genuine identity evidence (shared proper
   name, documented alias, token-subset relationship) rather than mere
   subject-matter relatedness?
6. **`map_to_focus` requires actual identity.** Does every `map_to_focus`
   pair in the batch represent the idea genuinely BEING the existing Focus,
   not merely related to it?
7. **Respects settled roster aliases.** Does the batch never propose
   re-splitting an identity `roster_context` already shows as merged?
8. **Unsure → keep.** Across the batch, is `keep` used whenever the
   evidence for merge/map isn't genuinely there (no forced merges)?
9. **Output-shape discipline.** Does every verdict in the batch carry
   exactly the three keys `merge` / `map_to_focus` / `keep`, with no reason,
   evidence, or notes field?
