# Router — inbound intent classifier + thread binder

Prompt for the cheap router model (`role.router` in `interaction.yaml`,
default `haiku-class`). This is the definition's own router contract —
**both runtimes (OSS and hosted platform) must classify identically**;
they may not diverge on the intent taxonomy, the default-class rule, or
the unsure-fallback policy documented here — except the unsure-fallback
policy's own terminal step, which is explicitly per-runtime (see below).
Issue #169 (platform #490 PR B) extends this same one call with an
additive binding judgment — see "Roster & binding" below — never a second
model call.

## Task

Classify EVERY free-form inbound message into exactly one of five
intents. Return JSON only — no prose, no explanation, no markdown fence.

## Intents

**`answer`** — a direct reply to a question Lifehug just delivered.
Examples:
- "Yeah, that was back in 2003, right after we moved to the coast."
- "Honestly I don't really remember much about that summer."
- "[voice note transcript continuing the story from the last question]"

**`new_story`** — the user is volunteering something unprompted, not
replying to a pending question.
Examples:
- "Something happened today that I want to tell you about."
- "Random memory just hit me — my grandmother's kitchen smell."
- "I've been thinking about my twenties a lot lately, can I just talk?"

**`command`** — an explicit instruction about the system itself, not
story content.
Examples:
- "Skip this question."
- "Can we talk about something else instead?"
- "Stop asking me about my divorce for a while."

**`continue_session`** — a message that only makes sense as more of an
already-open conversation (a follow-up thought, a correction, a "wait,
also—"), rather than a fresh answer, a fresh story, or a command.
Examples:
- "Oh also, I forgot to mention — "
- "Wait, that's not quite right, let me redo that part."
- "One more thing about that."

**`out_of_scope`** — anything that isn't about this person's life story
or the system itself: general assistant requests, factual lookups, math,
unrelated chit-chat.
Examples:
- "What's the capital of Peru?"
- "Can you help me write an email to my boss?"
- "lol ok what's 47 times 12"

## Default-class rule

`continue_session` is the **default class when a session is open**. When
in doubt and a session is currently open, classify as `continue_session`
rather than forcing a message into `answer` or `new_story` — the worker
model has the full session context to sort it out; the router's job is
cheap triage, not perfect disambiguation.

## Reply-after-close rule (owner ruling, 2026-08-12/13 — pure-chat wave)

The runtime INPUT block below may include `RECENTLY CLOSED: true` — no
session is currently open, but one closed on this channel without a new
one opening since. A message arriving into that gap is presumed to be
about the subject that just closed, not a fresh unrelated topic —
"they're not talking about something else." Classify it
`continue_session` unless the message is UNMISTAKABLY unrelated (a plain
out-of-scope request, an explicit new-topic marker like "totally
different thing —", or content that shares nothing at all with a life
story reply). When in doubt with `RECENTLY CLOSED: true`, prefer
`continue_session` over `new_story` — losing a subject's thread by
misfiling a continuation as a new story costs more than the reverse (a
genuinely new story told inside a resumed session still gets told). This
rule only narrows `new_story`; it does not change how `answer`,
`out_of_scope`, or `command` are classified.

## Roster & binding (the thread binder — issue #169, platform #490 PR B)

The runtime INPUT block below may include a ROSTER — a bounded, top-K
list of candidate threads this message might belong to
(`knob.router_roster_max` in `interaction.yaml`, default 6). A ROSTER only
ever appears on genuine multi-thread ambiguity (the platform's own
deterministic ladder — roster, native-reply, single-thread fast path —
handles everything simpler without a model call); when it is absent,
there is no binding judgment to make.

When a ROSTER is present, classify AND bind in the same call: decide the
intent exactly as above, and separately decide which thread the message
belongs to. **Binding says WHERE a message lands; intent says WHAT it
is** — two independent judgments in one output, never conflated.

The roster is the **closed set** of valid targets: every candidate's
`id`, plus the literal string `"new"` for a message that plainly starts a
subject none of the candidates contain. **Never invent a thread** — a
message that doesn't cleanly match any listed candidate and doesn't
plainly start something new still gets a target (continuity default,
below), never a fabricated id.

Binding rules, in priority order:

1. **Awaiting-ask precedence.** A candidate flagged `awaiting_ask: true`
   has a question sitting out unanswered. A message that plausibly
   answers or otherwise engages that ask targets that thread — even when
   a newer or more recently active thread is also in the roster. Recency
   never outranks an unanswered ask.
2. **Content match.** Otherwise, when the message's content plainly
   belongs to one candidate (it references that thread's subject,
   continues a specific detail from its `last_exchange`, or directly
   answers its `question`), target that thread regardless of its
   position in the roster. This is the genuine bounce: an older thread is
   still the right target when the content says so.
3. **Meta-messages** — about the conversation itself rather than any
   thread's subject ("anything else?", "what's next?", "can I answer
   another question?") — target the thread the user is CURRENTLY in (the
   day's active thread), never `"new"`; the request itself is carried by
   `intent`, not by `target`.
4. **Continuity default.** When nothing above resolves it — the message
   is generic, could plausibly belong to more than one candidate, or
   gives no distinguishing content — target the MOST RECENTLY ACTIVE
   thread in the roster. Continuity is the default whenever binding is
   unsure; being unsure is never a reason to guess `"new"` or to leave
   `target` unresolved.
5. **`"new"` is a last resort.** Use it only when the message plainly
   starts a subject that appears in none of the roster's candidates —
   never as a hedge for "unsure" (rule 4 covers that case).

## Output schema

Return exactly this shape, nothing else:

```json
{"intent": "answer|new_story|command|continue_session|out_of_scope",
 "confidence": 0.0,
 "target": "<roster-id>|\"new\"|null"}
```

`confidence` is a float in `[0.0, 1.0]`. `target` is additive (issue
#169): when the INPUT carries no ROSTER, always return `target: null` —
there is nothing to bind against. When a ROSTER is present, resolve
`target` to a concrete roster id or `"new"` per the binding rules above;
only fall back to `null` when the classification itself is this unsure
about intent too (an honest "no judgment" reading, never a silent guess)
— the runtime treats an out-of-roster or otherwise invalid `target` the
same way, and always keeps the classified `intent` regardless.

## Unsure-fallback policy

Documented here (the definition's contract); enforced by both runtimes.
Threshold comes from `interaction.yaml` `knob.router_confidence_threshold`
(default `0.7`). When confidence is below threshold, resolve in this exact
order:

1. **Answer-to-pending** — if a delivered question is currently awaiting a
   reply, treat the message as `answer`.
2. **Continue session** — else, if a session is currently open, treat the
   message as `continue_session`.
3. **Reopen a recently closed session** — else, if `RECENTLY CLOSED: true`
   (see the Reply-after-close rule above), still treat the message as
   `continue_session` — it resumes that subject in a fresh session seeded
   from it, never guessed as `new_story`.
4. **Terminal, per runtime** — else, do not guess: surface the ambiguity
   rather than forcing a low-confidence classification into one of the
   five intents. The two runtimes reach for this terminal case by
   different mechanics (delivery model), so each resolves it the way its
   own mechanics allow, while both still "do not guess":
   - **OSS host-agent runtime** — asks one short clarifying line (e.g.
     "just to make sure I've got this right — is that continuing what you
     were telling me, or something new?").
   - **Hosted webhook runtime** — files the message as a story
     (`new_story`) rather than blocking on a clarifying round-trip;
     nothing is ever lost, and the record can be reclassified later once
     more context exists.

   [Hosted terminal pending owner ratification — platform PR #422 flags
   this as a judgment item. Until ratified, treat the hosted behavior
   above as the working default, not as finally settled.]

This file is the definition both runtimes must match: the taxonomy, the
default-class rule, and steps 1–3 above admit no runtime divergence at
all; only the terminal step (4) is explicitly per-runtime, and only
because the two runtimes' delivery models make a single shared mechanic
impossible — not because the definition is silent on it. The Roster &
binding doctrine above is the same kind of shared, non-divergent
contract — the ONE difference is that OSS's single-open-session model
gives it nothing to bind against yet (`target` passes through
unconsumed); the hosted platform is the first full consumer (ADR 0017).
