# Overlay — Landmarks (anthropic)

Inherits Conversation's anthropic overlay unchanged. The Landmarks extension adds no
provider-specific instruction: the one additive output field is declared in
the runtime output contract, and the five landmark lints are evaluated by the
caller, not by the model.
