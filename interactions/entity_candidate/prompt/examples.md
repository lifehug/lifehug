# Examples — Entity Candidate extension

All names and events are synthetic.

## Good — ask the highest-value gap naturally

Candidate: Synthetic Harbor. User: “My grandmother taught me to wait for the
tide there.”

```json
{"reply":"Waiting for the tide with her made the harbor part of how you learned patience. What did the harbor feel like when you returned there?","action":"ask_gap","next_gap":"type_specific_context"}
```

The receipt comes first and the user sees one question, not a rubric.

## Good — readiness still asks for consent

“There is enough here to preserve the harbor as a place shaped by patience,
loss, and what you pass on. What would you change before I hold that research?”

This is a confirmation request, not confirmation and not approval.

## Bad — checklist interrogation

“Now provide a checklist item. Next provide tensions. Then provide open
questions.”

## Bad — model authors evidence or durability

“I inferred that the harbor symbolizes resilience and stored the new entity page.”

Inference is not exact user evidence, and the model has neither write nor
approval authority.
