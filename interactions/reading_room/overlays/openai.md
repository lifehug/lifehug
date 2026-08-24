# Overlay — Reading Room (openai)

Inherits Conversation's openai overlay unchanged. The Reading Room extension adds no
provider-specific instruction: it declares no new output field at all — it
reuses the Timeline lane's `placed` and the Landmarks lane's `landmark` — and
the six reading-room lints are evaluated by the caller, not by the model.
