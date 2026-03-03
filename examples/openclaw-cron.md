# OpenClaw Cron Examples for Lifehug

Copy-paste these to set up your daily question delivery.

The cron handles **asking** only — check for updates, pick a question, send it. The commit/push happens after you answer (the AI handles that in the answer processing flow).

---

## Telegram (9 AM, US Eastern)

```bash
openclaw cron add \
  --name "Lifehug Daily Question" \
  --cron "0 9 * * *" \
  --tz "America/New_York" \
  --channel telegram \
  --announce \
  --task "Run the Lifehug daily routine:
1. Check for updates: cd ~/Workspace/lifehug && python3 system/update.py --check --quiet (exit code 1 = update available)
2. Pick today's question: python3 system/ask.py
3. Send the question warmly — don't just paste raw output. Frame it like a real interviewer.
4. If an update is available, mention it briefly after the question.
5. If rotation.json shows an unanswered question from yesterday, gently remind them first.
Reply here whenever you are ready — voice or text."
```

## WhatsApp (8:30 AM, US Pacific)

```bash
openclaw cron add \
  --name "Lifehug Daily Question" \
  --cron "30 8 * * *" \
  --tz "America/Los_Angeles" \
  --channel whatsapp \
  --announce \
  --task "Run the Lifehug daily routine:
1. Check for updates: cd ~/Workspace/lifehug && python3 system/update.py --check --quiet (exit code 1 = update available)
2. Pick today's question: python3 system/ask.py
3. Send the question warmly — don't just paste raw output. Frame it like a real interviewer.
4. If an update is available, mention it briefly after the question.
5. If rotation.json shows an unanswered question from yesterday, gently remind them first.
Reply here whenever you are ready — voice or text."
```

## Signal (9 AM, UK)

```bash
openclaw cron add \
  --name "Lifehug Daily Question" \
  --cron "0 9 * * *" \
  --tz "Europe/London" \
  --channel signal \
  --announce \
  --task "Run the Lifehug daily routine:
1. Check for updates: cd ~/Workspace/lifehug && python3 system/update.py --check --quiet (exit code 1 = update available)
2. Pick today's question: python3 system/ask.py
3. Send the question warmly — don't just paste raw output. Frame it like a real interviewer.
4. If an update is available, mention it briefly after the question.
5. If rotation.json shows an unanswered question from yesterday, gently remind them first.
Reply here whenever you are ready — voice or text."
```

## Discord (10 AM, US Central)

```bash
openclaw cron add \
  --name "Lifehug Daily Question" \
  --cron "0 10 * * *" \
  --tz "America/Chicago" \
  --channel discord \
  --announce \
  --task "Run the Lifehug daily routine:
1. Check for updates: cd ~/Workspace/lifehug && python3 system/update.py --check --quiet (exit code 1 = update available)
2. Pick today's question: python3 system/ask.py
3. Send the question warmly — don't just paste raw output. Frame it like a real interviewer.
4. If an update is available, mention it briefly after the question.
5. If rotation.json shows an unanswered question from yesterday, gently remind them first.
Reply here whenever you are ready — voice or text."
```

---

## Customizing

- Change `--cron "0 9 * * *"` to your preferred time (minute hour)
- Change `--tz` to your IANA timezone
- Change `--channel` to your messaging platform
- Change `~/Workspace/lifehug` to wherever you cloned the repo

## What Happens After You Answer

When you reply to a question (voice or text), the AI:
1. Processes and saves your answer to `answers/`
2. Generates follow-up questions
3. Updates coverage tracking
4. Refreshes the README progress section
5. Commits and pushes to git

This all happens in the main session — not in the cron.
