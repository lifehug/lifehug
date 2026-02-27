# OpenClaw Cron Examples for Lifehug

Copy-paste these to set up your daily question delivery.

---

## Telegram (9 AM, US Eastern)

```bash
openclaw cron add \
  --name "Lifehug Daily Question" \
  --cron "0 9 * * *" \
  --tz "America/New_York" \
  --channel telegram \
  --announce \
  --task "You are the Lifehug interviewer. Run: cd ~/Workspace/lifehug && python3 system/ask.py
Send the output question to the user. Be warm and conversational — don't just paste the raw output. Frame it like: 'Good morning! Here is today's question: [question text]'. If rotation.json shows an unanswered question from yesterday, gently remind them first. End with: Reply here whenever you are ready — voice or text."
```

## WhatsApp (8:30 AM, US Pacific)

```bash
openclaw cron add \
  --name "Lifehug Daily Question" \
  --cron "30 8 * * *" \
  --tz "America/Los_Angeles" \
  --channel whatsapp \
  --announce \
  --task "You are the Lifehug interviewer. Run: cd ~/Workspace/lifehug && python3 system/ask.py
Send the output question to the user. Be warm and conversational — don't just paste the raw output. Frame it like: 'Good morning! Here is today's question: [question text]'. If rotation.json shows an unanswered question from yesterday, gently remind them first. End with: Reply here whenever you are ready — voice or text."
```

## Signal (9 AM, UK)

```bash
openclaw cron add \
  --name "Lifehug Daily Question" \
  --cron "0 9 * * *" \
  --tz "Europe/London" \
  --channel signal \
  --announce \
  --task "You are the Lifehug interviewer. Run: cd ~/Workspace/lifehug && python3 system/ask.py
Send the output question to the user. Be warm and conversational — don't just paste the raw output. Frame it like: 'Good morning! Here is today's question: [question text]'. If rotation.json shows an unanswered question from yesterday, gently remind them first. End with: Reply here whenever you are ready — voice or text."
```

## Discord (10 AM, any timezone)

```bash
openclaw cron add \
  --name "Lifehug Daily Question" \
  --cron "0 10 * * *" \
  --tz "America/Chicago" \
  --channel discord \
  --announce \
  --task "You are the Lifehug interviewer. Run: cd ~/Workspace/lifehug && python3 system/ask.py
Send the output question to the user. Be warm and conversational — don't just paste the raw output. Frame it like: 'Good morning! Here is today's question: [question text]'. If rotation.json shows an unanswered question from yesterday, gently remind them first. End with: Reply here whenever you are ready — voice or text."
```

---

## Customizing

- Change `--cron "0 9 * * *"` to your preferred time (minute hour)
- Change `--tz` to your IANA timezone
- Change `--channel` to your messaging platform
- Change `~/Workspace/lifehug` to wherever you cloned the repo

## After Setup

Your AI handles everything:
- Picks the next question based on coverage gaps
- Sends it at your configured time
- When you reply, it processes your answer, generates follow-ups, and updates state
- Over time, it drafts chapters, essays, and spotlight pieces from your accumulated answers
