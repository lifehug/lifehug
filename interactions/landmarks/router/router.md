# Router — Landmarks extension

Inherits Conversation's router. One addition: a message that names a place, a
school, a date, a spouse, a child, a job or a service period while a landmark
question is on the table is an ANSWER to that question, not a topic change —
route it to the worker with the landmark stage intact.

A message that declines ("skip", "no idea", "not now", "another time") is also
an answer. It ends that landmark for this conversation and never re-opens it
in the same session.
