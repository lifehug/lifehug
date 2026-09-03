# ADR 0025: The Reading Room — evidence-driven dating sessions

**Retired 2026-09-03 (owner ruling R4a, `lifehug-platform docs/decisions/2026-09-03-timeline-unification/decision-record.md`):** removed together with Go Dig and Go Deep; the interaction, `dig_plan`, research and CLI verbs are deleted in Cut 2c; Add Landmark (an `offer` mode of `landmarks`, Cut 6a) replaces this line of work. Body kept as history.

Date: 2026-08-24
Status: proposed

## Context

By v202 the timeline could rank *which* unknown was worth the most and had
nothing at all to say about the two facts that actually place a life.

The first is that **the person usually has the answer in a box**. Photographs,
report cards, passports, letters, deeds, immunisation records — a printed date
is exact to the day, a ZIP+4 means "not before October 1983" full stop, and a
passport's issue date brackets every stamp inside it for ten years. None of
that could be recorded honestly, because `chronology.BASES` had no way to say
"this came off paper". Every artifact-derived date had to lie about its
warrant and file as `stated`.

The second is that **some unknowns are not the person's to answer**, and this
is the owner's own framing: *"There are mysteries to my past that are relevant
now but once my mom dies who knows? There are mysteries about Grandma I could
resolve if I asked my uncle, who is still living, today."* Better probing will
never place that; one question to a relative will. It is the only unknown
class in the whole system with a clock on it.

The research (`system/research/go-deep.md`, v197) found a third thing on the
way, by running the real v196 code over a synthetic vault: **the keystone list
double-counted**. `entity:mom`'s resolve set was a strict subset of
`period:childhood-yucaipa`'s, so the second star's marginal gain was exactly
zero — two questions that place what one question places. v199 fixed the
keystone head by making it greedy over the residual; this ADR extends that
same greedy rather than forking a second copy of it.

A fourth thing turned up during the build and is worth recording as a defect
class: the output contract advertised the basis vocabulary as a hand-typed
literal in **two** places, so a basis added to `chronology.BASES` would have
silently never reached the model.

## Decision

**1. Three evidence bases, weighted flat.** `chronology.BASES` gains
`document`, `photo` and `relative`. Weights: `document 7.0 · stated 6.0 ·
relative 5.5 · age 5.0 · photo 4.5`. A printed date outranks a stated one
because it is not a reconstruction. A relative sits just under `stated`
because proxy report is meant to be used *with* the index report and not
instead of it (Straughen et al. 2013). A photograph sits under both because a
contextual date **bounds** rather than names — and `photo` and `relative` are
capped at `approximate` confidence, so the record says on itself that it is a
window. There is NO era-conditional weighting: the "relatives beat self for
childhood" nuance stays a research note, not a mechanism.

A witness is carried in provenance as `{"source": "witness:<slug>", …}`, which
reuses `claim_score`'s existing source-consilience identity — two relatives
corroborating one claim count as two independent origins for free, with no new
state.

**2. The plan is greedy over the residual, ranked on width, extended to `k`.**
`timeline.dig_plan` is `timeline.keystones` with `n = k`, a precision grade per
pick, and a witness partition. The scoring pass and the greedy loop were
extracted to `_scored_anchors` / `_greedy_plan` so there is exactly ONE greedy
definition. Ranking is on a continuous width-sum with the count displayed,
because a threshold metric ("how many become month-precise") is not submodular
and greedy stalls on it (Krause & Guestrin 2009); an unknown with no bounds
weighs 1.0, so today's vaults degenerate to marginal coverage exactly.

**3. Every pick names the precision grade that unlocks the derivations**
(owner emphasis, 2026-08-24). A school is a name until you have its address;
then it is a district, and a district keeps records with exact years in them.
A birthday guessed to the year dates nothing to the day. The grade vocabulary
is closed, and each grade carries the clause that says what it buys.

**4. The witness partition runs LAST, over what the plan does not reach.**
Considered and rejected: partitioning first, as the research's §8.3 sketch
suggests. On a real roster a living parent shares an era with the whole of a
childhood, so partitioning first takes almost every unknown off the in-session
table and empties the Reading Room of exactly the work it exists to do. What
the greedy plan *surfaces* is the unknown no anchor reaches at all, and that
is precisely §6's case.

Urgency is an ORDERING by generation, oldest first, and nothing else. Never a
label on a person, and never one word about anybody's mortality.

**5. The child interaction mints no output field.** `reading_room` reuses the
timeline lane's `placed` and the landmarks lane's `landmark`, both opened by
one `TurnShape.reading_room_stage` gate. Considered and rejected: a third
`evidence` field. Two lanes already own those shapes, their structural
parsers, and their closed validators; a third shape for the same fact is the
drift the "exactly ONE additive field" rule exists to prevent, read at its
intent rather than its letter.

**6. Homework is a page, not a queue.** The close names who would know what.
The dig list itself is re-derived on every compile and rendered into that
witness's existing `## Open Questions` section — no new page type, no new
state, no deferral machine, no inbox. "I'll find out" is an ordinary,
complete answer, and a lint class exists specifically to catch the deferral
machine growing back in voice form.

**7. The basis vocabulary the output contract advertises is DERIVED from
`chronology.BASES`.** One authoritative definition (recurring-defect
doctrine), so a basis added to the tuple cannot fail to reach the model.

## Consequences

- **Binds:** any surface rendering the Reading Room reads
  `timeline.timeline_data()["reading_room"]` and nothing else; the row shows
  at most two witness lines; the plan is `k = 3`. Any new date basis must be
  added to `chronology.BASES` *and* weighted in `BASIS_WEIGHT` — a test pins
  the two key sets equal. Any lane that can name a date runs
  `timeline_interaction.proposes_a_date`; that definition now has three
  callers and must never be copied.
- **Binds:** a dig-list row rendered onto a wiki page carries
  `timeline.DIG_LIST_MARKER`, and `question_candidates` skips those rows.
  A question addressed to a witness must never enter the vault owner's own
  daily queue.
- **Forecloses:** a deferral store, a homework inbox, an outstanding-item
  tracker, or any per-witness state file. Also forecloses making the Reading
  Room ambient — a scheduled send, a nudge, or a daily question version of it
  turns it into the interrogation whispers exist to avoid.
- **Forecloses:** era-conditional basis weighting, and any ranking on a
  threshold count.
- **Delete-when:** if unknowns ever carry real interval bounds,
  `timeline.unknown_width` stops being mostly 1.0 and the plan's ordering will
  genuinely diverge from marginal coverage. That is the intended end state,
  but it is a behavioural change and should be revisited here when it lands.
