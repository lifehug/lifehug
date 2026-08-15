# Examples — judged candidates, good and bad

Synthetic content only — no real vault data, no references to any real
person's story. Every candidate below is invented for this file. Each
example names the specific rule (or penalty flag) it demonstrates or
violates so a lint/rubric author, and a reviewer, can trace the connection.

## Priority band: 0.85–0.95 (critical gap — converges all three purposes)

**Candidate:** "You've mentioned your dad's workshop three times now
without ever describing what you actually built there together. Walk me
through one afternoon in that workshop, start to finish — what were you
working on, and what did it feel like to be trusted with the tools?"

**GOOD verdict:**
> `priority: 0.90`. Converges all three purposes: helps others understand
> the author (a concrete father-son scene), lets the author tell their
> story (fills the empty "what happened / who was there" scene slots per
> rule 6), and helps the author understand themselves (targets the unasked
> "what does it say about you" slot). Evidence: three prior mentions with
> zero scene detail — a genuine, specific gap, not a generic thematic
> guess. Rule 2 (two-sentence rule): one context sentence, one open
> question. Rule 6: explicitly reaches for the highest-value scene slot.

**BAD verdict — violates the priority vocabulary's evidence requirement:**
> `priority: 0.95`, no evidence line, notes: "great question."

(A bare number with no band-justifying evidence is not a valid verdict —
see `prompt/behavior.md`'s priority vocabulary section.)

## Priority band: 0.55–0.70 (solid — one purpose, concrete evidence)

**Candidate:** "What did a typical Tuesday look like during your first
year in Ohio — waking up to going to sleep?"

**GOOD verdict:**
> `priority: 0.62`. Serves one purpose (help others understand the
> author) with concrete evidence: the Ohio period has near-zero typical-day
> texture on record, and this is the highest-yield family for exactly that
> gap (era anchors / typical-day reconstruction). No convergence claimed —
> this is a solid, single-purpose candidate and that's fine.

## Hard fail: `penalty.yes_no_wording` (rule 1)

**Candidate:** "Did you enjoy living in Ohio?"

**GOOD verdict:**
> Rejected. `flags: [yes_no_wording]`. Opens with "Did you" — rule 1
> (open-ended, never yes/no) is a hard fail, not a scoring deduction to
> average away. No priority assigned.

**BAD verdict — treats a hard fail as a minor deduction:**
> `priority: 0.45`, notes: "slightly closed but still usable."

(Rule 1 candidates that trip `yes_no_wording` are out of scope for craft
polish, not merely down-scored — see `prompt/behavior.md`'s hard-rules
preamble.)

## Hard fail: `penalty.self_directed_why` (rule 8)

**Candidate:** "Why do you always avoid talking about money with your
family?"

**GOOD verdict:**
> Rejected. `flags: [self_directed_why]`. "Why do you always avoid…"
> targets the author's own recurring behavior with a why-question — rule 8
> flags this as confabulation-prone. Rewrite direction (not part of this
> verdict, offered as guidance): "What's one specific time money came up
> with your family that you remember clearly?" — a "what"-form, specific-
> moment candidate would pass.

## Hard fail: `penalty.too_broad` (rule 3)

**Candidate:** "How do you feel about your career?"

**GOOD verdict:**
> Rejected. `flags: [too_broad]`. Matches the too-broad shape exactly
> (generality, no specific moment) — rule 3 requires "think of one time
> when," not a generic feelings survey.

## Depth pass done right (rule 10 — new angle, not rehearsal)

**Candidate, targeting a topic already answered in detail:** "You've told
the story of your wedding day before — the ceremony, the reception, your
dad's toast. Is there a detail from that day you've never mentioned to
anyone — something small that's stayed with you but never made it into an
answer?"

**GOOD verdict:**
> `priority: 0.58`. Serves "help others understand me" with concrete
> evidence — the existing wedding-day material is thorough (ceremony,
> reception, the toast all on record), so this candidate correctly asks
> for what's never been told rather than re-asking the canonical version.
> Rule 10 satisfied; not a duplicate — `check_quality`'s dedup would not
> flag this (different normalized text, genuinely new angle).

**BAD candidate that should have been flagged `duplicate_of_*` instead of
scored:** "Tell me about your wedding day — the ceremony, who was there,
how it felt." (Near-identical normalized text to an existing accepted
question already on the ledger.)

## Rubric-edit example (weekly, `mode: rubric_edit`)

**GOOD amendment (bounded, evidence-cited, under
`knob.weekly_edit_max_chars`):**
> "This week 4/6 candidates flagged `too_broad` were era-anchor questions
> ('what things cost,' 'the house room by room') that check_quality's
> `TOO_BROAD_PATTERNS` doesn't actually match — false-positive pattern gap,
> not a craft failure. Recommend: add an explicit carve-out note to rule 4
> that era-anchor candidates are exempt from the broad-generality reading.
> Evidence: candidates c-2291, c-2304, c-2318, c-2340 (all rejected,
> all era-anchor family, all subsequently hand-approved by the owner)."

**BAD amendment — not bounded, not evidence-cited:**
> "Rewrote the whole priority section to be clearer."

(A rubric-edit amendment is ONE bounded, auditable edit backed by cited
evidence — a wholesale rewrite with no evidence line violates both the
edit-budget and the evidence-line requirement in
`prompt/turn-instructions.md`'s RUBRIC-EDIT template.)
