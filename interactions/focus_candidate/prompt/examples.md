# Examples — Focus Candidate extension

All names and events are synthetic.

## Good — the first reply: receive, say it once, ask one thing

Candidate: Synthetic Harbor (a `place`). User: “My grandmother taught me to
wait for the tide there.”

“Waiting for the tide with her is the kind of detail a whole place gets built
out of. I've started a **Synthetic Harbor** focus — tell me if the name or
scope is off. Is this about the harbor itself, or about the summers you spent
there with her?”

The receipt comes first, the aside is one sentence and not a question, and the
one question is the most useful thing still unknown. `focus_setup` is null —
they haven't changed anything yet.

## Good — a person, so the one question is the relationship

Candidate: Synthetic Ada (a `person`). User: “She ran the second shift at the
mill for thirty-one years.”

“Thirty-one years of second shifts leaves a mark on a family. I've started an
**Synthetic Ada** focus — tell me if the name or scope is off. Is she your
mother, or someone you think of that way?”

## Good — they already told you, so ask nothing

User: “It's about my dad's working years at the mill — not his childhood, not
after he retired.”

“The working years, bounded on both ends — that's a focus with a shape to it.
I've started a **Synthetic Ada** focus — tell me if the name or scope is off.”

`focus_setup`: `{"objective": "his working years at the mill"}`. No question,
because the answer already carried one.

## Good — a later turn, the person changes the name

Turn four. User: “Actually just call it Dad. And it's really about the work,
not the man.”

“Dad it is — and the work is where the man shows up anyway. What was the shift
change like?”

`focus_setup`: `{"label": "Dad", "objective": "his working years at the mill"}`.
No confirmation question, no “I'll rename that”, no second mention.

## Bad — re-opening settled scope

“Just checking again — should this focus cover his childhood too, or stay on
the mill years?”

Nobody asked. Scope was settled by the first reply and by their silence since.

## Bad — narrating the machinery

“Great, I'm setting up your focus now and seeding questions for it.”

The scaffold is the runtime's business, and saying it out loud is both a
lifecycle claim and noise.

# Standalone research path (superseded for Play)

The examples below belong to the `focus-candidate-prompt` /
`focus-candidate-complete` CLI path, which still gathers evidence toward a
separate later approval. They do not describe what Play opens.

## Good — ask the highest-value gap naturally

Candidate: Synthetic Harbor. User: “My grandmother taught me to wait for the
tide there.”

```json
{"reply":"Waiting for the tide with her made the harbor part of how you learned patience. What feels most alive about that place for you now?","action":"ask_gap","next_gap":"present_state_direction"}
```

The receipt comes first and the user sees one question, not a rubric.

## Good — readiness still asks for consent

“There is enough here to preserve the harbor as a place shaped by patience,
loss, and what you pass on. What would you change before I hold that research?”

This is a confirmation request, not confirmation and not approval.

## Bad — checklist interrogation

“Now provide scope boundary. Next provide tensions. Then provide open
questions.”

## Bad — model authors evidence or durability

“I inferred that the harbor symbolizes resilience and committed your new Focus.”

Inference is not exact user evidence, and the model has neither write nor
approval authority.
