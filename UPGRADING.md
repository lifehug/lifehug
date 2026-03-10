# Upgrading to Lifehug v3

## What changed

- **Daily cron now commits and pushes first** — Before sending the question, the cron runs `git add -A && git commit && git push` to ensure any pending answer files, state updates, or drafts are safely backed up to your repo. This prevents data loss and keeps your repo in sync automatically.

## What you need to do

Update your daily cron task to include the commit/push step at the start:

```
0. cd <WORKSPACE_PATH> && git add -A && git diff --cached --quiet || git commit -m "Daily update $(date +%Y-%m-%d)" && git push
```

Then continue with the update check and question delivery as before.

For OpenClaw users: say **"update lifehug"** to apply automatically, or run:

```bash
python3 system/update.py --apply
```

Then update your OpenClaw cron job payload to match the new template in `CLAUDE.md` (Step 9).

---

# Upgrading to Lifehug v1

If you cloned Lifehug before the update system was added, welcome to v1!

## What changed

- **`system/version.json`** — Tracks which version you're on
- **`system/update.py`** — Checks for and applies future updates
- Daily cron now checks for updates automatically

## What you need to do

Nothing. Your answers, drafts, question bank, and config are untouched.

Future updates: say **"update lifehug"** in any session, or run:

```bash
python3 system/update.py --check
python3 system/update.py --apply
```

## Setting up an upstream remote (fork users only)

If you forked Lifehug instead of cloning directly, add the upstream remote so updates can be fetched:

```bash
git remote add upstream https://github.com/lifehug/lifehug.git
```
