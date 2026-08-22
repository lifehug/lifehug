---
title: Arc Walk
parent: The Interaction Pattern
nav_order: 6
---

# Arc Walk Interaction

## 1. What it does

Arc Walk is the conversation you get when you press Play on a **set** of
questions rather than one — a focus, a chapter, a book, or the week's queue. It
is the fourth child of Conversation, and its one goal is arc walking: work a
target's open questions casually, in resumable episodes (v193,
`docs/pr-specs/arc-walk-interaction.md`; platform issue #570 §3).

At Play, the package recomputes a **plan**: the target's open questions in the
weekly planner's own ranking, with the arc planner's intents attached wherever
this week's cards have one. The first reply **announces the agenda** in one warm
sentence — what today is about and roughly how much — and asks the first
question. After that the plan is a map, not a script: a tangent is followed
rather than corrected, a declined question is skipped silently and never
re-offered, and the order bends whenever the conversation is better for it.

An **episode** is one sitting, about four to eight questions by the target's
tier. It closes warmly with what was covered and the fact that the rest waits
for whenever you like. Nothing is ever counted out loud and nothing is ever
described as unfinished. Press Play again tomorrow and you get a new episode of
a freshly computed plan — whatever you answered today is simply gone from it.

**Passive users are untouched.** The daily single question works exactly as it
did; this Interaction runs only when a target carrying N questions is Played.
Mechanically the gate is `TurnShape.arc_stage`, which defaults to `None`, and
with it `None` the turn's output contract is byte-identical to v192.

## 2. The behavior authority

The contract below is the file the runtime sends to the model, verbatim — not a
description of it (see [the Interaction Pattern](index.md) §3).

<!-- embed: interactions/arc_walk/prompt/behavior.md -->
# Behavior contract — Arc Walk extension

The inherited Conversation contract governs every visible reply. These rules
add the Arc Walk responsibility.

1. **Announce once, then never again.** The first reply of an episode says
   what today is about and roughly how much — one sentence, warm, no list read
   aloud, no numbers. Every later reply behaves as if the agenda were simply
   the shape of the conversation, because it is.
2. **One question per reply.** Receive what they said first; ask the next
   thing second. Two questions in one reply turns an episode into an
   interview.
3. **The plan is a map, not a script.** Follow the person's energy. A tangent
   is not a detour to correct — go where they went, and come back to the
   agenda later if it still fits, or don't. A skipped question is skipped
   silently; a declined one is never re-offered in this episode.
4. **Never count, never keep score.** No "three of six", no "two more", no
   "you still have". Coverage is the system's business and never the
   conversation's.
5. **Close warm.** When the episode is done — or the person says they are
   going — name what was covered in their own terms and say the rest waits
   for whenever they like. Ask nothing. Nothing is unfinished; there is only
   what has been said and what has not been said yet.

## Episode doctrine

An episode is one sitting, not a marathon and not a habit to maintain. Its
size comes from the target's tier, not from the person's stamina, and it ends
before it drags. The next Play is a fresh episode of a freshly computed plan:
whatever they answered today is simply gone from tomorrow's map. Because of
that, leaving early costs nothing and is never described as leaving early.
<!-- /embed -->

## 3. The plan, the episode, and the stage

| Concern | Where |
|---|---|
| What a Play points at | `arc_walk.normalize_target(value)` → `{kind, ref, label, categories}`; kinds are `arc_walk.ARC_TARGET_KINDS` — focus, chapter, book, category, queue |
| The plan | `arc_walk.build_arc_plan(...)` → `{target, focus_label, questions[{id,text,category,intent}], episode_size, plan_n, answered_k}`. Pure, no writes, never persisted — recomputed at every Play, so answered questions fall out on their own |
| The order | `question_planner.enriched_pending_questions` (the one ranking authority — focus weighting, quality multiplier, rumination cooldown, the escalation gate, love-map staleness), sorted by `build_queue`'s own weight expression, with `build_queue`'s `arc_max` streak cap applied as a re-order. Two AST pins fail the build if either drifts |
| The bridge notes | `arc_walk.intent_note(card)` — the first intent of this week's arc card for that question, using `conversation.ARC_INTENT_KINDS`. No card, no intent |
| "k of N" | `plan_n` counts every question in the target; `answered_k` how many are answered. Both are bank facts, so `len(questions) == plan_n - answered_k` always holds |
| Episode size | `arc_walk.episode_size_for(tier, override=…)` — basic 4, standard 6, extreme 8, capped at 12, also `knob.episode_size_*` in the manifest <!-- parity: arc_walk.DEFAULT_EPISODE_SIZE = 6 --> <!-- parity: arc_walk.MAX_EPISODE_SIZE = 12 --> |
| Which stage this turn is in | `arc_walk.arc_stage_for_session(session, plan, user_leaving=…)` → `open` before the first assistant turn, `close` once the episode is full or the person says they are going, `walk` otherwise. Derived from the transcript; no new state |
| The prompt the caller replays verbatim | `interactions/arc_walk/prompt/turn-instructions.md`, substituting `{arc_stage}`, `{agenda}`, `{focus_label}`, `{episode_size}`, `{answered_k}`, `{plan_n}` |
| The seven lints | `arc_walk.lint_arc_reply` → `arc_walk_gates.*`: the agenda is announced once and never again; at most one question; no counting; no mechanism talk; no pressure; the close names what was covered and says the rest waits |

## 4. Filing: which question did that answer answer?

The qid the previous assistant turn asked already had a name in this system —
it is `question_id` on a `role: "lifehug"` turn, which the model calls
`held_question_id` and the hosted platform calls `stamped_question_id`.
`arc_walk.asked_question_id` is the one reader of it; v193 added no second
concept. `arc_walk.question_on_the_table(session, plan)` is therefore the
default answer to "what is this reply answering": the last asked plan question,
else the first one this session has not answered yet.

One additive output field overrides that default when the person answered
something else: `answered_question_id`, a single qid, validated by
`arc_walk.validate_answered_question_id` against exact membership in the
episode's plan. A qid the plan does not carry drops to null rather than filing
somewhere wrong. **Primary only** — an answer that covers two questions names
one, and the compiler cross-links the rest by content.

## 5. Where it lives

| Concern | Location |
|---|---|
| Registration | `interactions/registry.json` (`arc_walk`) |
| Definition | `interactions/arc_walk/` |
| Runtime authority | `system/arc_walk.py` |
| Ranking authority (unchanged) | `system/question_planner.py` |
| Bridge intents | `system/arc_planner.py`, `state/arc_cards.json` |
| Plan a target (read-only) | `lifehug.py arc-plan-target (--focus\|--category\|--chapter\|--book\|--queue) [--episode-size N] [--json]` |
| Goldens | `interactions/arc_walk/evals/goldens/arc_*.json` |
| Independent evals | `lifehug.py arc-walk-evals --json` |
| Guard tests | `tests/test_arc_walk.py`, `tests/test_arc_walk_evals.py`, `tests/test_interaction_registry.py` |

The package declares role tiers but no default concrete seat. The seven
`arc_walk_gates.*` compliance classes require perfect scores over nine
recorded goldens, which are deterministic and score with or without a live
provider; an unavailable provider skips loudly and never seats by default.

## 6. Decisions

- [ADR 0023 — Arc walking: episodes of a recomputed plan](../../adr/0023-arc-walking.md) — the plan/episode model, the not-persisted rule, primary-only filing, and "passive users are untouched".
- [ADR 0018](../../adr/0018-candidate-placement.md), fourth amendment — `answered_question_id` as the fourth instance of the additive-field discipline.
- [ADR 0016](../../adr/0016-asking-supply.md) — the quieter sibling mechanism an episode does not replace: `asking_supply` still offers held questions inside an ordinary chat.
