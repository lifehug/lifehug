# Local warm answer acknowledgment — synthetic interaction evidence

This is a deterministic transcript for issue #52. It uses synthetic names and
memories. No real Telegram bot, private vault, model endpoint, or API key was
used or claimed.

## Confirmed path

| Order | Durable/system event | What the synthetic author sees |
|---:|---|---|
| 1 | `answer:A1` is atomically filed, registered, and (when requested) committed locally | — |
| 2 | The canonical `answer-ack-prompt` is completed through shared `ai_provider`; Telegram returns `ok: true`; metadata ledger records `confirmed` | “Thank you for sharing that. The blue porch swing and your sister’s red rain boots make the memory feel close.” |
| 3 | Adaptive cadence sends and marks the chosen follow-up | “📖 Lifehug — since you’re on a roll … What came next? … (Totally optional — tomorrow’s question comes either way)” |

Replay of `answer:A1` reads `confirmed` and performs neither a second model
call nor a second Telegram send.

## Provider-unavailable path

| Order | Durable/system event | What the synthetic author sees |
|---:|---|---|
| 1 | `answer:A1` is filed normally | — |
| 2 | Shared provider reports `agent-task` / unavailable; ledger records `skipped: no_unattended_provider` | No fabricated acknowledgment |
| 3 | Adaptive cadence still evaluates and sends the optional follow-up normally | The same optional follow-up framing as above |

## Ambiguous Telegram path

| Order | Durable/system event | What the synthetic author sees |
|---:|---|---|
| 1 | `answer:A1` is filed normally | — |
| 2 | The send begins from a persisted `ambiguous: send_in_progress` replay position; the Telegram response is lost | The acknowledgment may or may not be present |
| 3 | The optional follow-up still runs | Follow-up, if otherwise eligible |

`doctor` and `answer-ack-status A1` keep the ambiguous outcome visible. Lifehug
does not repeat it automatically. An operator must check Telegram first and
use `answer-ack-retry A1 --confirm-not-sent` only when absence is confirmed.
