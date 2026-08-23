# Arc templates — how arc cards are planned

This is the spec the Wave-2 arc-planner PR implements (design §4). It
documents how arc cards come to exist before a chat or conversation ever
runs — turns are executed live, but the shape they run inside is planned
ahead of time.

## What an arc card is

An **arc card** is DATA — one entry in `state/arc_cards.json` (registered
in `system/vault_contract.json` by PR 2, issue #115) — planned by
thresholds, not by the user doing anything. This is the autonomy-by-default
property: the user never has to request a plan for one to exist.

**Input ranking (owner decision):** healthy-conversation quality comes
first, coverage objectives come second. A card that would make a
technically-uncovered topic feel forced is the wrong card, even if it
scores well on coverage.

## Weekly

A new step after `planner-queue` in `weekly_maintenance.sh` — **the OSS
shell script is the parity spec for the platform's equivalent step**: for
each question queued that week, plan one arc card:

- **Opening framing** obeys research.md §1's two-sentence rule: one
  context sentence drawn from the user's own record, even for a cold-start
  coverage question — the framing must still prove memory, not open
  generically.
- **2–4 follow-up intents**, chosen from:
  - unfilled five-slot scene probes for the question's Focus,
  - sibling candidates in the same neighborhood arc,
  - timeline gaps touching that era — this is the
    `timeline.compute_gaps()` consumer, and the first non-display consumer
    of that function,
  - a **place with no stories** — a place they NAMED as a landmark, with a
    known span and nothing in the vault that happened there. A story gap,
    never a dating one: ask what life was like there, never when it was.
    Ranked after the timeline gap, at most one per card, and counted within
    the same weekly cap — a conversation carries at most one second agenda,
    and the two kinds share that one slot,
  - studio format slots the eventual answer could fill,
  - a "sit with" tension, if the question belongs to the self-arc,
  - a `demonstrated_knowledge_summary` intent, for threads that already
    have record to summarize from.
- **Keyless mode:** emit to `state/agent_tasks/arcs`. Deterministic
  fallback (no model call needed): intents drawn straight from the
  five-slot probe plus neighborhood siblings.

## Monthly

Research neighborhoods that already have target outputs get multi-session
**conversation** threads. A neighborhood can mark itself
"conversation-ready," so an inbound "I want to talk" (classified
`new_story` or `command` by the router) can offer it as a starting point.
Perennials and echo-resurfacing questions become conversation openers with
last year's answer attached, so the opener can reference it directly.

## Daily

**Unchanged and still AI-free.** The daily loop attaches the day's
pre-made card to the outgoing question: the delivered message text is the
card's opening framing when a card is present, or the current
non-arc-carded format otherwise. This is the ratified deviation from
decision C — arc *generation* moved to the weekly loop specifically so the
daily loop stays AI-free by construction; daily only *attaches* a card
that already exists, it never plans one live.

## Reengagement

Reengagement pre-empts arcs, exactly as it does today: 4+ silent days
triggers one short, gentle, gift-framed question. Its card is intentionally
minimal — no planned depth, no follow-up intents beyond the single
question — because the point of reengagement is a low-friction door back
in, not a deep arc.

## Convergence property (owner-set)

Every detectable gap type has a named consumer that turns it into a
conversation input, so a user who only ever talks converges the whole
system with zero administration:

- Timeline `unplaced_events` / `all_undated` → landmark-anchor arc
  intents → answers → classification places the event →
  `timeline-retire` clears it, existing behavior.
- Mirror tensions / "Sit with" items → self-arc intents → responses file
  via the mirror inbound path → the next weekly edition compiles the
  development. The conversation *invites* toward a tension; it never
  adjudicates it.
- Coverage gaps, scene-slot gaps, format gaps → the arc planner, via the
  weekly step above.

## Staleness

Arc cards carry an expiry alongside the queue's own expiry. A
queue-expired fallback (a rotation pick with a minimal card) keeps chats
working even against a stale plan — a missed week degrades gracefully,
the same property the top-level README already documents for the question
queue itself.
