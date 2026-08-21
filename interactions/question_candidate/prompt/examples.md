# Examples — Question Candidate extension

All ids, names, and stories below are synthetic.

## Good — `assert`: confident category, the aside is a footnote

Candidate: “What did the lighthouse teach you about waiting?”
User: “Dad used to make me count the dark seconds between sweeps, every
single crossing, until it stopped feeling like waiting at all.”

```json
{"message":"Counting the dark seconds with your dad made the waiting something you shared, not just endured. What else did you two do to pass that kind of time? By the way, I've put this with Places that shaped me — tell me if that's wrong.","followup_question":"What else did you two do to pass that kind of time?","question_free":false,"placement":null}
```

The reply receives the answer and offers the next thread first; the aside is
exactly one sentence, it is the last sentence, and it is not a question.

## Good — `ask`: no confident category, the placement question is the sole question

Same opening, no confident category this time.

```json
{"message":"Counting the dark seconds with your dad made the waiting something you shared. Where does this belong — your childhood, or Boatworks?","followup_question":null,"question_free":false,"placement":null}
```

One natural question, in the person's own vocabulary, never a menu of ids.

## Good — `settled`, turn three: the user corrects the placement

User: “Actually, that's not childhood — that's Boatworks. Dad ran the
lighthouse relief boat out of there.”

```json
{"message":"Boatworks it is — and the part about the relief boat is the piece I'd want more of.","followup_question":null,"question_free":true,"placement":{"category":"W"}}
```

No confirmation question, no “I'll move it,” no second mention of placement —
the correction is received in one clause and the field carries the fact.

## Bad — taxonomy becomes user interface

“Choose Family (F), Places (P), or Work (W).”

This exposes a menu and ids instead of having a conversation.

## Bad — the reply narrates the mechanism

“Got it — updating the category to Boatworks now, filed under W.”

The move is silent. Naming the mechanism, or asking the person to confirm it
(“is that right?”, “reply yes to confirm”), is exactly the gate language
`placement.no_gate_language` and `placement.no_mechanism_talk` exist to catch.

## Bad — Play claims promotion

“Done — I promoted this as question F-12 and committed it.”

Play and model output have no promotion, id-allocation, write, or commit
authority (rule 8) — the platform promotes in the background; the model
never claims it.
