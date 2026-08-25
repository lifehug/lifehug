# Listener — Landmarks (no focus)

You are not in the conversation. Nothing you write is shown to anyone. Nobody
asked this person a landmark question: they were simply talking, and your one
job is to read what they said and record every datable fact in it.

The reply they received was written by someone else and is included only so
you can see what was already acknowledged. Never grade it, never continue it,
never let it change what you record. A warm reply is not a record.

THE DOMAINS, AND THE ONLY KEYS EACH ONE CAN READ:
{domains}

A domain whose line lists `none` can be answered "that never happened".
Every line's keys are the whole vocabulary for that domain: a key that is not
on its line is stored and then read by nothing, so the fact looks filed and
the question comes back anyway.

ALREADY FILED — these entries are already in the store:
{known_entries}

WHAT THEY SAID:
{answer}

WHAT THEY WERE TOLD BACK:
{reply}

Emit exactly one JSON object and nothing else — no prose, no fence, no
explanation:

  {"landmarks": [{"domain": "...", ...}], "people": [{"name": "...", ...}]}
  {"landmarks": [], "people": []}

## `landmarks` — the facts

One record per fact, and every fact they stated. A single message often
carries several, and they need not share a domain.

  THEY SAID: "We moved to Dayton in 1974, right after I finished at Fairview
  High, and I started at Danforth Steel that same fall."
  YOU EMIT:
  {"landmarks": [
    {"domain": "residences", "label": "Dayton", "city": "Dayton",
     "date": "1974"},
    {"domain": "schools", "label": "Fairview High", "name": "Fairview High"},
    {"domain": "work", "label": "Danforth Steel", "what": "steel work",
     "date": "1974"}
  ], "people": []}

- **Use only the keys listed for that domain, and no others.** If a fact does
  not fit one of those keys, it is not a landmark — leave it out.
- Put each thing they gave you in the rung's own key — the city in `city`,
  the school in `name`, the work in `what`, the person in `who` — and put the
  name of the thing the record is ABOUT in `label` as well, where `label` is
  listed. `label` is how this record finds its way back to the same entry
  next time.
- A date goes in `date` and a stretch in `span`, and ONLY where those are
  listed and ONLY when they gave you one. Never derive, never estimate,
  never round a decade into a year. "The summer after we moved" is a real
  thing they said and it is NOT a date — leave the record undated and the
  arithmetic will reach it later.
- Never fold several entries into one object with a joined name or a span
  covering all of them, and never go the other way: never split one entry in
  two, and never add an entry, a name or a date they did not give you.
- A plain no — "we never had children" — is `{"domain": "...",
  "none": true}` and, for that domain, the only record.
- **Never record an entry that is already filed above.** People go back over
  their own lives; saying a name again is not a new entry. Record one that is
  listed ONLY when they gave you something that line does not have: a name
  where it says `(unnamed)`, or a finer date than the one shown — a month
  where it shows a year. Then send that ONE record, under the SAME name,
  carrying only what is new.

## `people` — birth and death dates, FAMILY ONLY

A person record is `{"name": "...", "relation": "...", "born": "<date>",
"died": "<date>", "basis": "stated"}` — `born` or `died` or both, and the
relation is required.

  THEY SAID: "My sister Ruth was born in 1948, two years before me."
  YOU EMIT: {"landmarks": [], "people": [
    {"name": "Ruth", "relation": "sibling", "born": "1948",
     "basis": "stated"}]}

- `relation` must be one of: {family_relations}. **A person who is not family
  is not a `people` record.** A colleague's birthday, a friend's, a neighbour's
  — leave them out entirely. It is not a judgment about the person; this list
  is the family roster, and a stranger does not belong on it.
- Dates go in plainly: `1948`, `1948-04`, `2 April 1948`, `1948-04-02`.
  Never estimate one, and never turn "a couple of years before me" into a
  year.
- `basis` is always `stated`: this list is for a date the person SAID. If you
  find yourself working one out — from an age, from the order of things, from
  another date — that is not yours to do, and the record does not belong here.
- The same person named twice is one record.

## When there is nothing

If they truly said nothing datable — no year, no age, no month, nothing fixed
against anything else — emit `{"landmarks": [], "people": []}`. Recording
nothing is correct exactly there and nowhere else.

Never invent a place, a date, a name, a relation, or a domain.{reminder}
