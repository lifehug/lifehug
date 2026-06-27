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

## The three-tier schedule

Lifehug runs on three clocks plus per-answer events. The guiding rule:
**detect/report jobs are cheap and frequent; generate jobs cost API money and
run rarely.** The wiki is the relational database everything reads, so it is
compiled *before* any planning or research.

| Cadence | Job | Cost |
|---|---|---|
| **Daily** | `daily_question.sh` (compiles the wiki, then delivers today's question) | free |
| **Weekly** | `weekly_maintenance.sh` (compile → source lint/fix → quality update → planner queue → gap scan → progress) | free |
| **Monthly** | `monthly_research.sh` (compile → capped new neighborhoods → self-knowledge → spotlight recommendations → progress) | API $ |
| **Event** | you answer → `process-answer` (saves, recompiles wiki, updates state) | small |

### Daily (already set up above)

`daily_question.sh` now compiles the wiki first, so the relational graph is
fresh every morning before the question goes out. Nothing extra to schedule.

### Weekly — self-improve, plan the coming week, and surface gaps (free)

```bash
openclaw cron add \
  --name "Lifehug Weekly Maintenance" \
  --cron "0 20 * * 0" \
  --tz "America/Los_Angeles" \
  --task "cd ~/Workspace/lifehug && system/weekly_maintenance.sh"
```

`weekly_maintenance.sh` is the continuous-improvement loop. It compiles the
wiki offline, runs source lint, applies safe metadata/manifest fixes only when
lint finds fixable issues, updates the quality profile, builds the coming week
from the roadmap, scans for gaps without generating paid questions, prints
progress, and commits real state/wiki/source changes. `ask.py` consumes the
queue daily and falls back to rotation if it expires, so a missed week degrades
gracefully.

### Monthly — generate new domains + self-knowledge (uses the API)

Needs `ANTHROPIC_API_KEY` in the cron environment (or `anthropic_api_key` in
`config.yaml`). The daily/weekly jobs do not.

```bash
openclaw cron add \
  --name "Lifehug Monthly Research" \
  --cron "0 21 1 * *" \
  --tz "America/Los_Angeles" \
  --task "cd ~/Workspace/lifehug && system/monthly_research.sh"
```

`monthly_research.sh` is the growth loop. It compiles the wiki, reports gaps,
opens only a small capped set of new neighborhoods, refreshes the self-knowledge
pool if that arc is missing, recommends new Spotlights, prints progress, and
commits real state/wiki changes. The new candidates stay reviewable; the weekly
planner decides what to do with accepted/promoted material later.

### Manual / on-demand

```bash
python3 system/lifehug.py progress         # are we graduating toward deliverables?
python3 system/lifehug.py roadmap          # Focuses, tiers, saturation
python3 system/lifehug.py compile          # rebuild the wiki now
python3 system/lifehug.py serve            # browse the wiki locally
python3 system/research_expand.py --topic "Dad" --type relationship --output letter
```

## What Happens After You Answer

When you reply to a question, the AI should use the skill workflow:

```bash
printf '%s\n' "$ANSWER_TEXT" | python3 system/lifehug.py process-answer <ID> --source "voice (transcribed)"
python3 system/lifehug.py compile
```
