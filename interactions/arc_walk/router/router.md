# Router extension — Arc Walk leaving signal

The inherited Conversation router still governs chat mechanics. For an episode
in progress, also distinguish whether the latest user turn is answering the
question on the table, answering a DIFFERENT question from the agenda, taking a
tangent, declining the question on the table, or signalling that they are
leaving ("I need to go", "let's pick this up later", "that's enough for
today"). Preserve the exact turn in every case. A leaving signal routes to the
close and never to a deflection; never expose the agenda, its order, or its
size to the user.
