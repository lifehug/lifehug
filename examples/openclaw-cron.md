# OpenClaw Cron Examples for Lifehug

Lifehug is script-first. Cron should call the same scripts a human or skill-driven agent would call.

## Daily Question

Use `system/daily_question.sh` for scheduled delivery. It:

1. Safely commits pending Lifehug data paths.
2. Picks the next question with `ask.py --dry-run`.
3. Sends the message.
4. Marks the question sent only after delivery succeeds.
5. Pins the message when Telegram supports it.

Telegram delivery needs one target:

```yaml
telegram_chat_id: "-1001234567890"
```

or an environment variable:

```bash
TELEGRAM_CHAT_ID="-1001234567890"
```

The bot token can come from `TELEGRAM_BOT_TOKEN` or `~/.openclaw/openclaw.json`.

## Telegram DM Or Group

```bash
openclaw cron add \
  --name "Lifehug Daily Question" \
  --cron "0 9 * * *" \
  --tz "America/New_York" \
  --task "cd ~/Workspace/lifehug && system/daily_question.sh"
```

For groups, add your bot to the group, send any message, then open:

```text
https://api.telegram.org/bot<TOKEN>/getUpdates
```

Look for `"chat": { "id": -1001234567890 }`, then save that as `telegram_chat_id` or `group_chat_id` in `config.yaml`.

## Local Dry Run

Before enabling the schedule:

```bash
cd ~/Workspace/lifehug
LIFEHUG_DAILY_DRY_RUN=1 system/daily_question.sh
```

Or through the wrapper:

```bash
python3 system/lifehug.py daily-dry-run
python3 system/lifehug.py doctor --daily
```

## Nightly Wiki Compile

Optional local-only maintenance job:

```bash
openclaw cron add \
  --name "Lifehug Nightly Compile" \
  --cron "55 23 * * *" \
  --tz "America/New_York" \
  --task "cd ~/Workspace/lifehug && python3 system/lifehug.py rebuild && python3 system/lifehug.py compile && git add README.md system/coverage.json system/rotation.json wiki && git diff --cached --quiet || git commit -m 'Nightly wiki compile' && git push"
```

The same compile can be run manually at any time:

```bash
python3 system/lifehug.py compile
python3 system/lifehug.py serve
```

## What Happens After You Answer

When you reply to a question, the AI should use the skill workflow:

```bash
printf '%s\n' "$ANSWER_TEXT" | python3 system/lifehug.py process-answer <ID> --source "voice (transcribed)"
python3 system/lifehug.py compile
```
