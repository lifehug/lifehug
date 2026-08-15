# Rubrics — judge questions for prompt/behavior.md's hard rules

Binary (yes/no) per-clause judge rubrics, keyed 1:1 to `prompt/behavior.md`'s
eleven craft hard rules plus the mission test and the two vocabularies. A
strong judge model answers each question over a batch of JUDGE verdicts
(not a single verdict in isolation, except where noted) — "Yes" means the
property held across the whole batch; a single violation is a "no" for that
question, even if every other verdict in the batch was clean.

1. **Open-ended, never yes/no.** Does every accepted candidate avoid
   yes/no phrasing, and does every yes/no-phrased candidate in the batch
   carry `flags: [yes_no_wording]` and no priority?
2. **Two-sentence rule.** Does every verdict's underlying candidate carry
   at most one sentence of context and exactly one question mark?
3. **Specific moment over generality.** Does every accepted candidate ask
   about a specific moment rather than a generality, and does every
   generic-shaped candidate carry `flags: [too_broad]`?
4. **Sensory / scene-or-stakes path.** Does every accepted candidate carry
   a scene path, an emotion path, or a basic interrogative, and does a
   candidate with none of these carry `flags: [no_scene_or_stakes_path]`?
5. **Emotional anchor, where applicable.** For candidates targeting a
   scene with felt weight, is an emotional anchor present or explicitly
   not required (era-anchor/factual-gap candidates)?
6. **Five-slot scene probe.** When a candidate targets an empty
   "what does it say about you" scene slot, does the verdict's evidence
   line say so explicitly (this is the highest-priority-weight slot)?
7. **Action↔identity ladder.** When the source material shows an
   ungrounded identity claim or an unreflected action, does the verdict
   correctly recognize a ladder candidate as high-value?
8. **What, not why, for the author's own feelings.** Does every
   self-directed why-candidate in the batch carry
   `flags: [self_directed_why]` and no priority?
9. **Never restate as fact.** Does every accepted candidate's framing
   sentence quote exactly or ask fresh, never asserting an unconfirmed
   detail as established?
10. **New angles on depth passes.** Does every candidate targeting an
    already-well-covered topic ask for new, never-told material rather
    than a rehearsal, and does a near-duplicate candidate carry
    `flags: [duplicate_of_<id>]`?
11. **One question, how/what openers, never leading.** Does every
    accepted candidate carry exactly one question mark, an open-form
    opener, and no presupposing frame?
12. **Priority vocabulary discipline.** Is every accepted verdict's
    priority within `[knob.priority_floor, knob.priority_ceiling]`, and
    does every priority carry a specific, band-justifying evidence line
    (never a bare number)?
13. **Penalty vocabulary discipline.** Does every `flags` entry across the
    batch use the penalty vocabulary's exact names (`prompt/behavior.md`'s
    penalty table), with no invented flag names?
14. **The mission test.** Does every accepted verdict's `purposes_served`
    name at least one real purpose, with the evidence line actually
    supporting that purpose (not just asserting it)?
15. **Rubric-edit discipline (RUBRIC-EDIT mode only).** Is every non-null
    amendment under `knob.weekly_edit_max_chars`, additive (not a rewrite
    or contradiction of a hard rule), and backed by a cited evidence line
    naming specific candidate ids/dates?
