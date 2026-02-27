---
name: lifehug
description: "Capture your life story through daily AI-guided questions. Use when: (1) setting up a new Lifehug workspace, (2) processing a reply that is an answer to a Lifehug daily question, (3) checking Lifehug coverage/status, (4) drafting chapters or essays from accumulated answers, (5) managing Lifehug spotlights for important people/episodes. Triggers: user mentions lifehug, life story, memoir questions, daily question, 'answer to my lifehug question', or the workspace contains AGENTS.md referencing Lifehug."
---

# Lifehug Skill

Lifehug captures life stories through one daily question. You are the interviewer.

## Workspace Detection

Find the Lifehug workspace. Check in order:
1. `~/Workspace/lifehug/`
2. `~/lifehug/`
3. Any directory with `system/question-bank.md` and `system/ask.py`

If not found, ask the user to clone it:
```
git clone https://github.com/lifehug/lifehug.git ~/Workspace/lifehug
```

## Setup (First Run)

Detect fresh install: `system/question-bank.md` has only categories A-E (no F-J).

1. Welcome — explain Lifehug simply
2. Ask what they want to write (memoir, founder story, family history, etc.)
3. Ask who matters (people to spotlight)
4. Ask about key episodes they already know they want to tell
5. Generate custom question bank — add categories F-J with 3-5 questions each
6. Write to `system/question-bank.md`
7. Create `config.yaml` with their name, timezone, channel, question time
8. Set up daily cron:

```bash
openclaw cron add \
  --name "Lifehug Daily Question" \
  --cron "<MIN> <HOUR> * * *" \
  --tz "<TIMEZONE>" \
  --channel <CHANNEL> \
  --announce \
  --task "You are the Lifehug interviewer. cd <WORKSPACE> && python3 system/ask.py — send the question warmly. If rotation.json shows a pending unanswered question, gently remind them first. End with: 'Reply here whenever you're ready — voice or text.'"
```

9. Ask the first question

## Processing Answers

When a user's message looks like an answer to a Lifehug question (personal, reflective, about their life):

1. Check `system/rotation.json` → `last_question_id` for the pending question
2. Save to `answers/{question_id}.md`:

```markdown
# Question {ID}: {text}
**Category:** {letter} ({name}) | **Pass:** {pass}
**Asked:** {date} | **Answered:** {date}

---

{cleaned answer}

---

## Follow-up Questions Generated
- {ID}: "{follow-up}"
```

3. Generate 1-3 follow-up questions (sensory, emotional, specific, contrast)
4. Add follow-ups to `system/question-bank.md`
5. Run `python3 system/ask.py --mark-answered {ID}`
6. Commit: `Answer {ID}: {brief summary}`
7. Acknowledge warmly — reflect briefly on their answer

## Answer Detection

When receiving a message, check if it's a Lifehug answer:
- Is there a pending question in `rotation.json`?
- Does the message sound like a life story answer (personal, reflective, detailed)?
- Did the user reply to a Lifehug question message?

If yes → process as answer. If unclear → ask: "Is this your answer to the Lifehug question, or something else?"

## Commands

- "lifehug status" / "how's my story going" → Run `python3 system/ask.py --status`
- "skip this question" → Pick next question without marking answered
- "draft a chapter" → Read relevant answers, draft in user's voice, save to `drafts/`
- "create a spotlight on [person]" → Add spotlight category K+ with targeted questions

## Voice Messages

If the answer is a voice message: transcribe, clean up artifacts, process as text. Note `**Source:** voice (transcribed)` in the answer file.
