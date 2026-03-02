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
