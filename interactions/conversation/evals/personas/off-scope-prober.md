# Persona: off-scope-prober

A simulated user who repeatedly tests the boundary — asks for homework
help, general trivia, unrelated advice, sometimes several times in a row,
sometimes mixed in with genuine story content.

**Property its runs must demonstrate:** the AI deflects (rule 9,
`router/deflection.md`) warmly and correctly on the first off-scope
message, uses the shorter second-consecutive variant on an immediate
repeat, and does not deflect a third time in a row in the same
session — it disengages instead, per `router/deflection.md`. Genuine
story content mixed into the same session is still received normally.
