# Examples — Question Candidate extension

All ids and stories below are synthetic.

## Good — substantive answer first, placement resolves during it

Candidate: “What did the lighthouse teach you about waiting?”
User: “Dad used to make me count the dark seconds between sweeps.”

```json
{"reply":"Counting the dark seconds with your dad made the waiting something you shared.","turn_kind":"answer","placement_action":"resolved","category_id":"F","confidence":0.94,"placement_question":null}
```

The reply receives the answer; placement stays invisible.

## Good — association deferred while the story is moving

```json
{"reply":"You can still picture the beam crossing the kitchen wall.","turn_kind":"answer","placement_action":"defer","category_id":null,"confidence":0.55,"placement_question":null}
```

Uncertainty does not interrupt the person.

## Good — one natural placement question after a receipt

```json
{"reply":"The waiting changed how you approached the whole season. Who were you going through it with?","turn_kind":"mixed","placement_action":"ask_now","category_id":null,"confidence":0.48,"placement_question":"Who were you going through it with?"}
```

## Bad — taxonomy becomes user interface

“Choose Family (F), Places (P), or Work (W).”

This exposes a menu and ids instead of having a conversation.

## Bad — Play claims promotion

“Done—I promoted this as question F-12 and committed it.”

Play and model output have no promotion, id-allocation, write, or commit
authority.
