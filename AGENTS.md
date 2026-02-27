# AGENTS.md — Lifehug Workspace

This is a Lifehug workspace. Read `CLAUDE.md` for the full operating instructions.

## Quick Start

**On every session**, check the state:

1. **Fresh install?** → If `system/question-bank.md` has no project categories (only A-E), run the First Session setup flow from CLAUDE.md.
2. **Setup done but no cron?** → If `config.yaml` exists but no daily question delivery is configured, help the user set up their cron job.
3. **Normal session?** → Check if there's a pending question or incoming answer to process.

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

1. Run `python3 system/ask.py` to pick the next question
2. Send it to the user via their configured channel
3. Track what was sent

### OpenClaw Cron

Tell the user to run this (or do it for them if you have access):

```
openclaw cron add \
  --name "Lifehug Daily Question" \
  --cron "<MIN> <HOUR> * * *" \
  --tz "<TIMEZONE>" \
  --task "Run the Lifehug daily question. Execute: cd <WORKSPACE_PATH> && python3 system/ask.py Then send the output as a message to the user on their configured channel. Be warm and conversational — don't just paste the question ID. Frame it naturally, like: 'Good morning! Here's today's question: [question text]'. If there's a pending unanswered question from yesterday, gently remind them about it first." \
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
1. Run `python3 system/ask.py`
2. Capture stdout (the question)
3. Deliver it however they prefer

## Processing Answers

When the user replies to a daily question (via any channel):

1. **Identify the question** — Match to the last asked question from `system/rotation.json` (`last_question_id`)
2. **Follow the "Processing an Answer" flow** in CLAUDE.md:
   - Clean up the response
   - Save to `answers/{question_id}.md`
   - Generate 1-3 follow-up questions
   - Mark answered in question-bank.md
   - Update rotation.json and coverage.json
   - Commit and push
3. **Acknowledge warmly** — Thank them, share a brief reflection on their answer, mention what's coming next

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
- **Weekly**: Check coverage, nudge if quiet
- **Monthly**: Review for themes, offer Spotlights, report progress
- **Milestones**: Draft deliverables when categories hit GREEN

## File Paths

All paths are relative to this workspace root:
- Questions: `system/question-bank.md`
- Rotation state: `system/rotation.json`
- Coverage: `system/coverage.json`
- Answers: `answers/`
- Drafts: `drafts/`
- Spotlights: `spotlights/`
- Config: `config.yaml`
