# ADR 0038: Cornerstones

Date: 2026-09-25
Status: ratified (owner, 2026-09-25) — v360, `timeline-rules:20`

## Context

The Timeline had two words for its dating model. **Landmarks** are the
universal skeleton: the questions everyone gets, answered as spans and points,
by domain. **Keystones** are computed: the highest-leverage unknown right now
(ADR 0024, ADR 0026). Neither said which dates are worth asking to the DAY,
and the package answered that question three different ways. The
`PRECISION_TARGETS` table asked any birth, death or wedding for its day,
whoever it belonged to. The resolver's own sentence could ask for "the exact
date" of an anecdote because it would place other things. And a derived day,
such as an age frame's edge or a containment window opening on a birthday,
was shown to the owner as a day he never said.

The owner's rulings, 2026-09-25, in his words:

> "almost nothing needs precision of more than a month at this stage, other
> than what I'd say are landmark events like weddings, birthday dates, and
> deaths. Unless I specifically give it, I think the fidelity of a month is
> enough, or even less."

> "I think the precision I give you is enough to make a placement. If the
> system realizes that higher precision for a certain card or question would
> place a lot of other things, that should raise its likelihood of being
> asked. We almost never need more than month precision except for extremely
> important dates like birth, death, wedding, divorce."

> "I like Cornerstones … I agree with that set. If I happen to mention a
> cornerstone for someone else in a discussion, I think it's worth a
> question. For example, 'When did your sister get divorced?' You accept the
> precision I give you, which is probably not a date but more like a month or
> a year. And yes marriages should become spans and stay open while you're
> married." ("I'm still married to Katie and will be till I die.")

His vault showed each defect. His father's death was held as March–June 2020,
and no card asked for the day, because the ~12-month stakes gate drops a
`moment` held to three months with nothing waiting on it. His wedding to Katie
was drawn as seven nodes and no marriage: six tellings at the stated
2007-01-11, and one "Marriage to Katie" drawn at 2001-07/2008-07 from an age
("26 (Katie was 20)").

## Decision

1. **Cornerstones are a term and a fixed set** (`system/cornerstones.py`):
   the owner's birth; each child's birth; the births of his parents,
   siblings and spouse; each of his weddings and divorces; the deaths of his
   parents, spouse, siblings, children and grandparents; and his baptism,
   only once he mentions it. The set is written over the vocabulary that
   already exists. Its milestones are `temporal_claims.EVENT_KINDS` words
   (`birth`, `child_born`, `death`, `loss`, `married`, `divorced`,
   `baptism`). Whose a milestone is comes from the roster's relationship
   words plus `self`, and a landmark entry supplies the relationship where the
   roster lacks it. There is no second list.
2. **A day is asked only of a cornerstone**
   (`temporal_work_items.A_DAY_IS_ASKED_ONLY_OF_A_CORNERSTONE`). A missing
   cornerstone, or one held coarser than a day, is worth a card that asks for
   the day. That card keeps its stakes whatever the ~12-month gate says
   (`a_cornerstone_keeps_its_card`, a separate rule read before
   `date_card_changes_something`, which is unchanged). A cornerstone-type
   event for somebody outside the set is worth ONE card. It asks to the year,
   its answer is accepted at whatever grain he gives, and once placed it is
   never asked again. That holds even off his axis, where the 2026-09-23
   ruling would otherwise mint nothing. Every other card asks no finer than a
   month. Leverage raises a card's rank (`system_value`) and never its grain.
   Each date card carries `requested_grain`, which is additive and not part of
   its identity.
3. **A worked-out day is shown as its month**
   (`chronology.A_WORKED_OUT_DAY_IS_SHOWN_AS_ITS_MONTH`). `display_date`,
   the one renderer the platform replays, shows a day only when a person or a
   document stated it (`stated`, `document`, `relative`), or when the record is
   a certain definitional join to such a day. Every cornerstone the fold holds
   to a day is one of those. This changes the display only, and the stored
   interval keeps its day.
4. **A marriage is a span** (`temporal_timeline.A_MARRIAGE_IS_A_SPAN`,
   `timeline-rules:20`). The wedding stays a point cornerstone. The marriage
   is drawn as its own episode node, which opens on the wedding and stays open
   (`"<wedding>/.."`, the way an ongoing stay already is). It closes only at a
   divorce cornerstone or a death, his or his spouse's.
5. **A telling of his wedding is the cornerstone**
   (`episode_binder.A_TELLING_OF_HIS_WEDDING_IS_THE_CORNERSTONE`).
   "Marriage to <someone>" names the wedding, while "Marriage became hard" is
   still the stretch. The owner's couple key alone buckets a telling for
   R2b, without a second person token. The age such a telling carries then
   folds onto the wedding as evidence (v19's
   `AN_ANSWER_IS_THE_PLACEMENT`), and it is never a node of its own.

Alternatives that lost. Leaving `PRECISION_TARGETS` as the gate would have
asked a friend's wedding for its day. Letting leverage unlock a finer grain
would contradict "the only time I would bring it up again is if it is hot".
He was speaking of rank, and the grain of a hot card was never in question.
Collapsing the marriage onto the wedding node would lose one of the two
things: either the point or the span.

## Consequences

- Binds: a new asking surface that wants a DAY must go through
  `precision_card_grain`. A new cornerstone kind must be seeded in
  `temporal_claims.EVENT_KINDS` first.
- Binds: the platform shows the grain the package renders. It must not
  format dates itself (this was already the rule). The platform glossary gets
  the same **Cornerstone** entry at pin time.
- Forecloses: a sub-month card about anything outside the set, however much
  it would place.
- Open: a cornerstone owed but never told has no node to ask on. An example
  is a child the roster names whose birth nobody has mentioned. The
  family/children ladder's birth rung asks for it today, at its own grain
  (`year|month`). Whether that ladder should add a `day` rung for
  cornerstones is the owner's call.
- Delete-when: the owner changes the set, or rules that some other date
  warrants a day.

## Amendment (v360 follow-up, owner 2026-09-25, `timeline-rules:23`)

- **A cornerstone is titled by its own name**
  (`cornerstones.A_CORNERSTONE_IS_TITLED_BY_ITS_OWN_NAME`). The folded wedding
  was titled by its longest telling, "Wedding reception in mother-in-law's
  backyard". A cornerstone's title is, in order, a landmark entry's words for
  it, a telling filed under the milestone's own kind ("Married Katie Ann
  Merrill"), or a telling titled as nothing but the milestone and who
  ("Married Katie", "Father's death"); only when none exists is the longest
  telling kept. A node whose own title is not the milestone ("Father's
  near-death and death") is read through the one milestone its tellings name.
- **A cornerstone is asked in its own words**
  (`temporal_timeline.A_CORNERSTONE_IS_ASKED_IN_ITS_OWN_WORDS`): a cornerstone
  filed under the `moment` wildcard is asked in its milestone's sentence, of
  its person, by the relation word the title uses — "Do you know the day of
  your father's death?", never "Do you know the day for Father dies of COVID?".
- **A handle naming a cornerstone binds to it**
  (`temporal_timeline.A_HANDLE_NAMING_A_CORNERSTONE_BINDS_TO_IT`): "after Dad's
  death" names the one node that is his father's death — "Dad" read through
  what he calls person/james-taylor — instead of standing as the keystone
  "When was Dad's death?".
- **The binder reads a milestone title strictly**
  (`episode_binder.A_TELLING_TITLED_AS_A_MILESTONE_IS_THAT_MILESTONE`,
  `A_MILESTONE_NEVER_JOINS_TWO_ROSTER_PEOPLE`). R2b now reads "Father dies of
  COVID" as a death (the verb table knew "die"/"died", not "dies"), reads the
  NOUNS "death"/"birth" only in a title that is the milestone itself (so
  "Begins processing father's death years later" is not a death), and never
  joins two tellings that resolve to different roster people (a grandfather's
  death is not a father's, however their names nest). On the owner's rig the
  father's death tellings fold to one node whose 2022 reading ("right before
  we started Etherfuse") is an alternate beside the stated 2020 one, with one
  contradiction card.

