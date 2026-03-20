# OpenClaw Cron Examples for Lifehug

Copy-paste these to set up your daily question delivery.

The cron:
1. **Commits and pushes first** — preserves any state changes (coverage, rotation) before the day starts
2. **Checks for updates** — notifies you if a new Lifehug version is available
3. **Picks and sends today's question** — warmly, like a real interviewer

---

## Telegram DM (9 AM, US Eastern)

```bash
openclaw cron add \
  --name "Lifehug Daily Question" \
  --cron "0 9 * * *" \
  --tz "America/New_York" \
  --channel telegram \
  --announce \
  --task "Run the Lifehug daily routine:
0. Commit and push any pending changes:
   cd ~/Workspace/lifehug && git add -A && git diff --cached --quiet || git commit -m 'Daily update $(date +%Y-%m-%d)' && git push
   If nothing to commit, continue.
1. Check for updates: python3 system/update.py --check --quiet (exit code 1 = update available)
2. Pick today's question: python3 system/ask.py
3. Send the question warmly — don't just paste raw output. Frame it like a real interviewer.
4. If an update is available, mention it briefly after the question.
5. If rotation.json shows an unanswered question from yesterday, gently remind them first.
Reply here whenever you are ready — voice or text."
```

## Telegram Group (9 AM, US Eastern)

If you want questions delivered to a Telegram group (so others can follow along or you want them pinned for easy access):

```bash
openclaw cron add \
  --name "Lifehug Daily Question" \
  --cron "0 9 * * *" \
  --tz "America/New_York" \
  --task "Run the Lifehug daily routine:
0. Commit and push any pending changes:
   cd ~/Workspace/lifehug && git add -A && git diff --cached --quiet || git commit -m 'Daily update $(date +%Y-%m-%d)' && git push
   If nothing to commit, continue.
1. Check for updates: python3 system/update.py --check --quiet (exit code 1 = update available)
2. Pick today's question: python3 system/ask.py
3. Send the question ONLY to the Lifehug group (chat_id: <YOUR_GROUP_CHAT_ID>). Format:
   📖 Lifehug — Daily Question

   [the question text]

   (Answer whenever you want — voice or text)
4. Pin the message in the group so it's easy to find:
   TOKEN=$(python3 -c \"import json; c=json.load(open('/Users/<you>/.openclaw/openclaw.json')); print(c['channels']['telegram']['botToken'])\")
   curl -s -X POST \"https://api.telegram.org/bot\${TOKEN}/pinChatMessage\" -d \"chat_id=<YOUR_GROUP_CHAT_ID>&message_id=<returned_message_id>&disable_notification=true\"
5. If an update is available, mention it after the question.
6. If rotation.json shows an unanswered question from yesterday, gently remind them first."
```

To find your group chat ID: add your bot to the group, send a message, then check `https://api.telegram.org/bot<TOKEN>/getUpdates`.

## WhatsApp (8:30 AM, US Pacific)

```bash
openclaw cron add \
  --name "Lifehug Daily Question" \
  --cron "30 8 * * *" \
  --tz "America/Los_Angeles" \
  --channel whatsapp \
  --announce \
  --task "Run the Lifehug daily routine:
0. Commit and push any pending changes:
   cd ~/Workspace/lifehug && git add -A && git diff --cached --quiet || git commit -m 'Daily update $(date +%Y-%m-%d)' && git push
   If nothing to commit, continue.
1. Check for updates: python3 system/update.py --check --quiet (exit code 1 = update available)
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
0. Commit and push any pending changes:
   cd ~/Workspace/lifehug && git add -A && git diff --cached --quiet || git commit -m 'Daily update $(date +%Y-%m-%d)' && git push
   If nothing to commit, continue.
1. Check for updates: python3 system/update.py --check --quiet (exit code 1 = update available)
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
0. Commit and push any pending changes:
   cd ~/Workspace/lifehug && git add -A && git diff --cached --quiet || git commit -m 'Daily update $(date +%Y-%m-%d)' && git push
   If nothing to commit, continue.
1. Check for updates: python3 system/update.py --check --quiet (exit code 1 = update available)
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
- For group delivery: replace `<YOUR_GROUP_CHAT_ID>` with your group's chat ID (negative number for Telegram groups)

## What Happens After You Answer

When you reply to a question (voice or text), the AI:
1. Processes and saves your answer to `answers/`
2. Generates follow-up questions
3. Updates coverage tracking
4. Refreshes the README progress section
5. Commits and pushes to git
