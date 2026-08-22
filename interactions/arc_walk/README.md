# Arc Walk Interaction

`arc_walk` is an independently registered, auditable Interaction for walking a
SET of open questions in one sitting. It exact-composes Conversation by
reference and owns only the one goal Conversation cannot carry: **work a
target's open questions casually, in resumable episodes.**

**A plan, not a script.** Pressing Play on a focus, a chapter, or a book builds
a plan — the target's open questions in the planner's own ranking, with the
arc planner's intents attached where cards exist — and the episode walks a
slice of it. The opener ANNOUNCES what today is about, once, and then the
model follows the person: tangents are followed rather than corrected, declines
are skipped silently, and the order bends whenever the conversation is better
for it (owner ruling 2).

**Episodes, not marathons.** One session walks about four to eight questions,
sized by the target's tier, and closes warmly with what was covered and the
fact that the rest waits. There is no checklist, no streak, and nothing is
ever "unfinished" (owner ruling 3).

**Nothing is persisted.** The plan is recomputed from the bank at every Play,
so answered questions simply fall out and resuming is a fresh episode of a
fresh plan. The only durable memory an episode leans on is the one that already
existed: `session["declined_question_ids"]` (ADR 0016) (owner ruling 4).

**Passive users are untouched.** The daily single question keeps working
exactly as it did; this Interaction runs only when a target carrying N
questions is Played — by a person today, by the scheduler later (owner ruling
6). Mechanically: `TurnShape.arc_stage` defaults to `None` and the output
contract is then byte-identical to v192.

**Filing is by question, and the concept already existed.** The qid the
previous assistant turn asked is `turn["question_id"]` on a `role: "lifehug"`
turn — what the model calls `held_question_id` and what the hosted platform
calls `stamped_question_id`. `arc_walk.asked_question_id` is the one reader of
it; no second field was added. The single additive output field,
`answered_question_id`, lets an answer that landed on a DIFFERENT agenda
question say so. Primary only: an answer covering two names one (owner ruling
5).

**Platform twin.** A host REPLAYs this package and reads exactly these —
nothing else is a contract (the shared shape: `interactions/README.md`
§ "The child-interaction paradigm"):

| What | Where |
|---|---|
| Normalize a Play target | `arc_walk.normalize_target(value)` → `{kind, ref, label, categories}` |
| Closed target kinds | `arc_walk.ARC_TARGET_KINDS` |
| Build the plan (pure) | `arc_walk.build_arc_plan(target, questions=…, categories=…, coverage=…, tier=…, episode_size=None, focus_index=None, objectives=(), cards=(), declined_question_ids=())` |
| The episode slice and `{agenda}` | `arc_walk.episode_questions(plan)`, `arc_walk.render_agenda(plan)` |
| Episode size by tier | `arc_walk.episode_size_for(tier, override=…)`; knobs `knob.episode_size_basic\|standard\|extreme` |
| The `{arc_stage}` this turn is in | `arc_walk.arc_stage_for_session(session, plan, user_leaving=…)` |
| Episode progress (a transcript fact) | `arc_walk.answered_plan_question_ids(session, plan)` |
| The asked qid (the EXISTING concept) | `arc_walk.asked_question_id(turn)` |
| The question on the table | `arc_walk.question_on_the_table(session, plan)` |
| The one additive turn-output field | `conversation_delivery.parse_turn_output(...)["answered_question_id"]`, enabled by `TurnShape(arc_stage=…)` |
| Closed validation of that field | `arc_walk.validate_answered_question_id(value, plan=…)` |
| The seven arc-walking lints | `arc_walk.lint_arc_reply(text, stage=…, agenda_announced=…)` |
| The leaf the caller REPLAYs verbatim | `prompt/turn-instructions.md`, substituting `{arc_stage}`, `{agenda}`, `{focus_label}`, `{episode_size}`, `{answered_k}`, `{plan_n}` |
| The read-only plan verb | `lifehug.py arc-plan-target (--focus\|--category\|--chapter\|--book\|--queue) [--episode-size N] [--json]` |

The FILING of an answer to `answered_question_id` is entirely host-side: the
package names the question, the host writes the file.

Run the deterministic seat gate with:

```bash
python3 system/lifehug.py arc-walk-evals --json
```

See `docs/pr-specs/arc-walk-interaction.md` (v193) and
[ADR 0023](../../docs/adr/0023-arc-walking.md).
