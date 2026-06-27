---
name: lifehug
description: "Operate a Lifehug workspace: daily life-story questions, answer processing, Focus/roadmap management (add a focus, show roadmap, progress toward deliverables, mark a focus finishing), private wiki compile/serve, state repair, pass transitions, and local/cron workflows. Use when the user mentions Lifehug, a daily Lifehug answer, adding or managing a focus, their roadmap or progress, compiling/viewing the Lifehug wiki, or maintaining a Lifehug/Dave workspace."
---

# Lifehug Skill

Lifehug is script-first. The scripts in `system/` are the source of truth; this skill is an operator wrapper. Prefer commands over manual edits.

## Find The Workspace

Use the current repo if it has `system/question-bank.md` and `system/lifehug.py`. Otherwise check:

```bash
~/Workspace/dave
~/Workspace/lifehug
~/lifehug
```

Run commands from the workspace root.

## First Checks

For maintenance or unclear state:

```bash
python3 system/lifehug.py doctor
python3 system/lifehug.py status
```

For scheduled-delivery checks, use:

```bash
python3 system/lifehug.py doctor --daily
```

`doctor --daily` must not send a message; it uses the daily dry-run path.

## Canonical Commands

Use these workflows. Do not duplicate their logic in the skill.

```bash
python3 system/lifehug.py status            # coverage and pass status
python3 system/lifehug.py roadmap           # Focuses, tiers, saturation
python3 system/lifehug.py progress          # progress toward deliverables (readiness)
python3 system/lifehug.py focus-new "<label>" --type <type> --tier <tier>  # add a focus end-to-end
python3 system/lifehug.py focus-finish <id> # push a deliverable to done (lifts its cap)
python3 system/lifehug.py next              # preview next question without mutation
python3 system/lifehug.py rebuild           # rebuild coverage/README/rotation counters
python3 system/lifehug.py compile           # compile private wiki
python3 system/lifehug.py compile --dry-run # check compile without writing
python3 system/lifehug.py source-scan       # summarize raw source files
python3 system/lifehug.py source-lint       # lint source integrity and queue findings
python3 system/lifehug.py source-lint --fix # safe metadata/manifest repairs only
python3 system/lifehug.py source-findings   # review persisted repair findings
python3 system/lifehug.py ingest-story      # save unprompted story source from stdin
python3 system/lifehug.py candidates-list   # list candidate questions
python3 system/lifehug.py candidates-review # review candidates before promotion
python3 system/lifehug.py candidates-promote # promote a candidate to question-bank.md
python3 system/lifehug.py planner-report    # show balance, candidates, active queue
python3 system/lifehug.py planner-queue     # write opt-in planned queue with caps/arcs
python3 system/lifehug.py planner-clear     # clear planned queue
python3 system/lifehug.py planner-state     # show/init planner state
python3 system/lifehug.py serve             # local wiki at 127.0.0.1:8765
python3 system/lifehug.py daily-dry-run     # validate daily delivery without sending
python3 system/lifehug.py followups-status  # pass-transition state
python3 system/lifehug.py followups-prompt  # prompt context for AI-generated depth questions
```

Process an answer from stdin:

```bash
printf '%s\n' "$ANSWER_TEXT" | python3 system/lifehug.py process-answer A14a --source "voice (transcribed)"
```

If the user does not provide an ID, `process-answer` uses `rotation.last_question_id`.

## Answer Processing

When a user message is a Lifehug answer:

1. Identify the question ID from the message or `system/rotation.json`.
2. Transcribe voice if needed and lightly clean transcription artifacts.
3. Save through the script:

```bash
printf '%s\n' "$ANSWER_TEXT" | python3 system/lifehug.py process-answer <ID> --source "text"
```

4. If useful, add 1-3 specific follow-ups:

```bash
printf '%s\n' "$ANSWER_TEXT" | python3 system/lifehug.py process-answer <ID> \
  --source "voice (transcribed)" \
  --followup "What did the room look like in that moment?"
```

5. `process-answer` compiles the wiki automatically by default. Use `--no-compile-wiki` only for tests or emergency repairs.
6. Commit only when the user asks, or when operating an explicit daily/cron workflow.

Never manually edit `coverage.json` or `rotation.json` unless repairing a failed script run with a clear reason.

Never rewrite old source bodies to improve history. `answers/` and `sources/` are raw source-of-truth; the wiki and planner state are derived. If a memory is wrong or later understanding changes, create an additive source:

```bash
printf '%s\n' "$CORRECTION" | python3 system/lifehug.py correct-source answers/A1.md --kind factual
printf '%s\n' "$REFLECTION" | python3 system/lifehug.py reflect-source answers/A1.md
```

Use `source-lint --fix` only for safe metadata/manifest repairs. See `system/source_contract.md`.

## Unprompted Story Ingest

When the user shares a story that is not an answer to the current daily question, ingest it as source material:

```bash
printf '%s\n' "$STORY_TEXT" | python3 system/lifehug.py ingest-story --source "telegram" --title "Arizona memory"
```

This writes to `sources/manual/` and stores suggested follow-up questions in `state/question_candidates.json`. Candidates are a parking lot; they are not asked automatically until promoted into the question bank or explicitly planned.

Review and promote candidates through scripts:

```bash
python3 system/lifehug.py candidates-review --status candidate
python3 system/lifehug.py candidates-update <candidate-id> --status accepted --target-category A
python3 system/lifehug.py candidates-promote <candidate-id> --category A
```

Promotion appends to `system/question-bank.md`, preserves source provenance, and marks the candidate as promoted. Do not manually copy candidate text into the question bank unless repairing a failed script run.

Refresh/report after ingest:

```bash
python3 system/lifehug.py compile
python3 system/lifehug.py planner-report
```

Planner queues are opt-in and expire:

```bash
python3 system/lifehug.py planner-report --limit 10
python3 system/lifehug.py planner-objective-add "Prepare Mom letter" --category K --keyword mom
python3 system/lifehug.py planner-queue --limit 14 --arc-max 2 --expires-days 7
```

`planner-report` is read-only. `ask.py` uses a planned queue only while it is valid and unexpired.

## Private Wiki

The wiki is local-first. It does not require hosting.

Compile:

```bash
python3 system/lifehug.py compile
```

Serve locally:

```bash
python3 system/lifehug.py serve
```

Open:

```text
http://127.0.0.1:8765
```

Generated wiki pages must cite source answers or ingested source files. The current privacy default is owner-only.

## Daily Delivery And Cron

Cron/LaunchAgent/OpenClaw should call the same scripts as manual use.

Daily delivery:

```bash
cd <workspace>
system/daily_question.sh
```

Dry-run:

```bash
cd <workspace>
LIFEHUG_DAILY_DRY_RUN=1 system/daily_question.sh
```

Do not make a cron path that independently picks questions or edits state.

## Pass Transitions

If all questions in the current pass are answered:

```bash
python3 system/lifehug.py followups-status
python3 system/lifehug.py followups-prompt
```

The AI should generate valid JSON for `system/gen_followups.py --append`. Generated questions must deepen existing answers with specific scenes, sensory detail, emotion, dialogue, before/after, or contrast.

## Add Or Manage A Focus

A **Focus** is anything the user is building toward — a person, a book, a blog, a theme, their life's work (it unifies the old "spotlight" and "project" split). Each has an objective and a tier (`basic` ≈ blog/~8, `standard` ≈ essay/chapter/person/~20, `extreme` ≈ book/life's work/~50+).

When the user says "add a focus" (or names something they want to build toward), interview briefly — **(1)** what they want to build (label + objective + deliverable), **(2)** how big (tier), **(3)** what kind (type) — then run one command:

```bash
python3 system/lifehug.py focus-new "<label>" \
  --type <person|relationship|project|theme|place|period|event|lifes_work|self> \
  --tier <basic|standard|extreme> \
  --objective "<objective>" --deliverable <book|chapter|essay|letter|post>
```

`focus-new` scaffolds a new question-bank category, registers the Focus on the roadmap, and auto-generates ~8–12 starter questions toward the objective (uses the OpenClaw gateway when running — no key needed — or `ANTHROPIC_API_KEY` as fallback; without either, the Focus is still created and it prints how to seed later). It never touches existing answers. Then show `python3 system/lifehug.py progress` and confirm warmly.

Other management:

```bash
python3 system/lifehug.py roadmap            # show Focuses + saturation
python3 system/lifehug.py focus-finish <id>  # push a deliverable to done
python3 system/lifehug.py focus-set <id> --tier <t> --target <N> --objective "<...>"
```

Don't create a Focus from a weak signal — confirm the objective first.

## Spotlights

> Spotlights and projects are now **Focuses** (see *Add Or Manage A Focus*). Adding a question category here automatically becomes a Focus on the next `roadmap` rebuild.

Use spotlights for important people, places, periods, projects, objects, or themes that deserve their own question arc.

Current safe implementation: person spotlights in `system/question-bank.md`.

For a new person spotlight:

1. Scan `answers/` and `wiki/` for existing mentions.
2. Choose the next available category letter after the current last `## X:` category.
3. Add 10-14 questions using a baseline-first arc:
   - identity and physical presence
   - day-to-day relationship
   - character in action
   - friction or complexity
   - turning points
   - legacy and meaning
4. Run:

```bash
python3 system/lifehug.py status
python3 system/lifehug.py compile --dry-run
```

5. Commit only if requested.

Do not auto-create spotlights from weak signals; recommend them with evidence first.

## Local-First Roadmap Hooks

Future workflows should follow this same script-first pattern:

```bash
python3 system/lifehug.py recommend-spotlights
```

Until those commands exist, track them as roadmap issues rather than inventing ad hoc state changes.
