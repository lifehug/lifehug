# AGENTS.md — Lifehug Workspace

This is a Lifehug workspace. Read `CLAUDE.md` for the full operating instructions.

## Quick Start

**On every session**, check the state through the script wrapper:

```bash
python3 system/lifehug.py doctor
python3 system/lifehug.py status
```

The `system/` scripts are canonical. Skills, agents, and cron jobs should call scripts instead of duplicating workflow logic.

Then decide:

1. **Fresh install?** → If `system/question-bank.md` has no project categories (only A-E), run the First Session setup flow from CLAUDE.md.
2. **Setup done but no cron?** → If `config.yaml` exists but no daily question delivery is configured, help the user set up their cron job.
3. **Normal session?** → Check if there's a pending question or incoming answer to process. Prefer `python3 system/lifehug.py process-answer` for answer saves.

## Detecting State

```
No config.yaml           → Brand new. Start setup.
config.yaml exists       → Setup done. Check for pending work.
  + no cron configured   → Help set up daily delivery.
  + cron active          → System running. Process answers, check coverage.
```

## First Session: Setup

When someone opens this workspace for the first time:

1. Read `CLAUDE.md` Section "First Session: Setup" — follow Steps 1-7
2. After generating their question bank, create `config.yaml` from their answers:

```yaml
# Lifehug — Your Configuration
name: ""                    # Your first name
timezone: "America/New_York"  # Your timezone (for question delivery)
question_time: "09:00"      # When to receive your daily question
channel: "telegram"         # telegram | whatsapp | signal | discord | email | cli
```

3. Set up the daily question cron job (see "Cron Setup" below)
4. Ask the first question

## Cron Setup

After setup, create a cron job for daily question delivery. The cron task should:

1. Run `system/daily_question.sh`
2. Let that script pick, send, pin when supported, and mark sent only after delivery succeeds
3. Avoid custom state mutation outside the script

### OpenClaw Cron

Tell the user to run this (or do it for them if you have access):

```
openclaw cron add \
  --name "Lifehug Daily Question" \
  --cron "<MIN> <HOUR> * * *" \
  --tz "<TIMEZONE>" \
  --task "cd <WORKSPACE_PATH> && system/daily_question.sh" \
  --announce \
  --channel <CHANNEL>
```

Replace:
- `<MIN> <HOUR>` with their preferred time (e.g., `0 9` for 9:00 AM)
- `<TIMEZONE>` with their timezone
- `<WORKSPACE_PATH>` with the absolute path to this repo
- `<CHANNEL>` with their delivery channel

### Other Platforms

For non-OpenClaw setups, the user needs to configure their own scheduler (cron, systemd timer, etc.) to:
1. Run `system/daily_question.sh`
2. Configure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, or config values supported by that script
3. Use `LIFEHUG_DAILY_DRY_RUN=1 system/daily_question.sh` to test without sending

## Processing Answers

When the user replies to a daily question (via any channel):

1. **Identify the question** — Match to the last asked question from `system/rotation.json` (`last_question_id`)
2. **Follow the "Processing an Answer" flow** in CLAUDE.md:
   - Clean up the response
   - Generate 1-3 follow-up questions when useful
   - Pipe the answer through `python3 system/lifehug.py process-answer {question_id}`
   - Let `process-answer` compile the private wiki automatically unless there is a clear repair reason to pass `--no-compile-wiki`
   - Commit and push if requested or part of the configured daily workflow
3. **Acknowledge warmly** — Thank them, share a brief reflection on their answer, mention what's coming next

## Unprompted Story Ingest

If the user shares a life story that is not an answer to the current daily question, save it as source material instead of forcing it into an answer file:

```bash
printf '%s\n' "$STORY_TEXT" | python3 system/lifehug.py ingest-story --source "telegram" --title "<short title>"
python3 system/lifehug.py compile
python3 system/lifehug.py planner-report
```

This stores the raw story under `sources/manual/` and parks suggested follow-up questions in `state/question_candidates.json`. Candidates should inform planning and future question-bank edits; they should not automatically dominate daily delivery.

## Source Integrity

Treat `answers/` and `sources/` as raw source-of-truth. Do not rewrite old answers or stories to improve history. If a memory was wrong, add a correction source; if understanding changed, add a reflection source:

```bash
python3 system/lifehug.py source-lint
python3 system/lifehug.py source-lint --fix
printf '%s\n' "$CORRECTION" | python3 system/lifehug.py correct-source answers/A1.md --kind factual
printf '%s\n' "$REFLECTION" | python3 system/lifehug.py reflect-source answers/A1.md
```

`source-lint --fix` is only for safe metadata and manifest repairs. Story meaning is repaired additively through `correct-source` or `reflect-source`. See `system/source_contract.md`.

Run the full weekly self-improvement loop with:

```bash
python3 system/lifehug.py weekly-maintenance
LIFEHUG_WEEKLY_DRY_RUN=1 system/weekly_maintenance.sh
```

The weekly loop compiles offline, lints sources, applies safe source fixes only when lint finds them, updates the quality profile, writes the next planned queue, scans gaps in dry-run mode, reports progress, and autocommits real changes.

Review candidate questions before they enter the daily flow:

```bash
python3 system/lifehug.py candidates-review --status candidate
python3 system/lifehug.py candidates-update <candidate-id> --status accepted --target-category A
python3 system/lifehug.py candidates-promote <candidate-id> --category A
```

Candidate promotion appends to `system/question-bank.md` and preserves source provenance. Do not manually copy candidate text into the question bank unless repairing a failed script run.

Use a planned queue only when the user asks for one or the workflow explicitly calls for it:

```bash
python3 system/lifehug.py planner-report --limit 10
python3 system/lifehug.py planner-objective-add "Prepare Mom letter" --category K --keyword mom
python3 system/lifehug.py planner-queue --limit 14 --arc-max 2 --expires-days 7
```

`planner-report` is read-only. `ask.py` uses `state/question_queue.json` only while it is valid and unexpired, then falls back to normal rotation logic.

### Voice Messages

If the user sends a voice message as their answer:
- Transcribe it (use Whisper or platform transcription)
- Clean up transcription artifacts
- Process as normal text answer
- Note in the answer file that it was originally voice

## Answer Detection

When you receive a message in this workspace context, determine if it's:
- **An answer to the pending question** → Process it (see above)
- **A request** ("show me coverage", "draft a chapter", "skip this question") → Handle it
- **A new setup conversation** → Continue setup flow
- **Casual chat** → Respond naturally, stay in character as their interviewer

The pending question is always in `system/rotation.json` → `last_question_id`. If the user's message seems like a life story answer (personal, reflective, detailed), it's probably an answer.

## Weekly/Monthly Rhythms

Follow the rhythms in CLAUDE.md:
- **Weekly**: Run `weekly-maintenance`; review any manual source findings, queue balance, and progress
- **Monthly**: Review for themes, offer Spotlights, report progress
- **Milestones**: Draft deliverables when categories hit GREEN

## File Paths

All paths are relative to this workspace root:
- Questions: `system/question-bank.md`
- Rotation state: `system/rotation.json`
- Coverage: `system/coverage.json`
- Story sources: `sources/manual/`
- Source corrections/reflections: `sources/corrections/`
- Source manifest: `state/source_manifest.json`
- Source lint findings: `state/source_lint_findings.json`
- Question candidates: `state/question_candidates.json`
- Planned queue: `state/question_queue.json`
- Planner state: `state/planner_state.json`
- Answers: `answers/`
- Wiki: `wiki/`
- Outputs: `outputs/`
- Config: `config.yaml`
