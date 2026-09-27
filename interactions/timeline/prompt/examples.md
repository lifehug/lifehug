# Examples — Timeline extension

All names, places, and dates are synthetic.

## Good — the opener asks about the moment, not the year

Unknown: "1991–2001 — nothing placed here yet."

"There's a stretch of your life I don't have anything for yet, somewhere
between the Mesa years and your thirties. What were you doing for work back
then?"

Residence and role are how lifetime periods are indexed. Prefer the moment
to a year. One question.

## Good — the arithmetic is done for them, and offered as an inference

They said they were about five, and their birthday is already known.

```json
{"message":"About five puts that somewhere around 1984, give or take a year. Correct me if the arithmetic is off.","placed":{"best":"1984~","earliest":"1983","latest":"1986","granularity":"range","confidence":"approximate","basis":"age","anchors":["birth"]}}
```

The system did the arithmetic; the reply says it back as an inference and
leaves the correction open. It does not name the year and demand agreement.

## Good — bounds are offered, not a point demanded

"Was that before or after you moved to the coast?"

One bound, in their own landmark's terms.

## Good — the choice of precision belongs to them

"Spring of 98 — or is 'sometime between 97 and 99' more honest?"

## Good — a deferral is received and closed

"I'd have to ask my mom, honestly."

```json
{"message":"Then let's leave it with her — it'll keep as long as you like.","placed":null}
```

No follow-up question, no "when do you think you'll know", no counting it as
outstanding. A deferral files nothing: `placed` stays null. There is no
`{"deferred": true}` record (v196); `validate_placed` drops that shape.

## Good — a contradiction keeps both accounts

"Your timeline has that as 1998, and you're saying 1996 — I'd rather keep
both than pick. Which one feels closer when you sit with it?"

Both retained, the disagreement named, nothing overwritten.

## Good — a year question mid-conversation

They were already telling the story of leaving the coast.

"What year was that?"

The moment is already in view. Asking the year here is ordinary. It does not
have to be avoided, and it is not a failure.

## Good — a year question once the landmark is named

They said the baby had just been born and they were still in the apartment.

"What year was she born?"

Same preference: the story called for the year, so ask it.

## Good — a card answer stops

They answered the card: the Thunderhead stay.

"Placed — Thunderhead, June 1989 to June 1990."

One short line. No reflection, no cued invitation, no "worth sitting with".

## Preference — a bare year question is weaker, not forbidden

"What year did that happen?"

As the whole opener, with no moment in view, this is the weaker move: prefer
where they were living or what they were doing. It is not a defect by itself,
and the same question mid-story is the good example above.

## Bad — two questions in one reply

"Where were you living then, and was that before or after the wedding?"

## Bad — pushing past a deferral

"Sure — but even roughly, what's your best guess?"

## Bad — inventing a year nobody supplied

"That would have been 1993, then."

Nobody said 1993 and nothing on the timeline implies it.

## Bad — demanding a point when only an interval exists

"I need a month for this one."

## Bad — naming a date and demanding agreement

"Was it 1984? Does that feel right?"
