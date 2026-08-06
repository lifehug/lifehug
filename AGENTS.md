# AGENTS.md — Lifehug Workspace

This is a Lifehug workspace. Read `CLAUDE.md` for the full operating instructions.

## Quick Start

**On every session**, check the state through the script wrapper:

```bash
python3 system/lifehug.py doctor
python3 system/lifehug.py status
```

The `system/` scripts are canonical. Skills, agents, and cron jobs should call scripts instead of duplicating workflow logic.

Use **the Loop** as the canonical operating term: capture source → compile wiki → lint/repair source truth → classify/score signals → promote candidates and plan the queue → ask a better question → create artifacts → feed final artifacts back as source. When auditing or designing, classify features as:
- **In the Loop**: reached by daily, weekly, monthly, or artifact flows and able to affect future questions, wiki pages, relationship understanding, or artifacts.
- **Loop-adjacent**: manual, dry-run, inspection, setup, or repair support that only changes future behavior when promoted into a Loop surface.
- **Out of the Loop**: code/data that exists but is not called by Loop entrypoints and is not read downstream. Mission-critical features should not remain here.

Use **Node** and **Edge** when reasoning about graph shape. A Node is a durable life subject that usually compiles into one wiki page; an Edge is a meaningful connection between nodes. Keep `Entity` and `Entity Type` as the current product/code and frontmatter terms: most entity types are node types, while `relationship` remains the compatibility page type for a **Relationship Edge**. `wiki/relationships/` describes the bond between two nodes, not a generic node page.

## Definition of Done (framework changes)

A code change is not done until its paper trail ships **in the same pass**:

1. **Docs** — update anything whose described behavior changed: `CLAUDE.md`,
   `system/research.md` (the central methodology guide — its opening feeds AI
   prompts, so staleness degrades the product), `README`/`README.template.md`,
   and `skills/*/SKILL.md`.
2. **GitHub issues** — comment progress on the covering issue with verification
   results; close it when delivered. If work surfaced a new gap, file it.
3. **Tests + version bump** — tests for new behavior, and **every PR bumps
   `system/version.json`** (owner rule, 2026-08-04): increment `version`,
   set `released`, write the changelog entry sized to user impact — a
   feature that changes behavior for the user gets a full changelog
   paragraph naming what they'll notice; a small fix gets a one-liner.
   Any new file the upgrade path should distribute goes into
   `framework_files` in the same bump (that manifest is what
   `system/update.py` ships to existing installs — a file missing from it
   never reaches upgraders). No PR ships without a bump.

"Done" = code + tests + docs + issue state — never code alone. The owner should
never have to ask whether the docs match the code.

Then decide:

1. **Fresh install?** → If `system/question-bank.md` has no project categories (only A-E), run the First Session setup flow from CLAUDE.md.
2. **Setup done but no cron?** → If `config.yaml` exists but no daily question delivery is configured, help the user set up their cron job.
3. **Normal session?** → Check if there's a pending question or incoming answer to process. Prefer `python3 system/lifehug.py process-answer` for answer saves.

## Cross-Medium Parity (owner-set, 2026-08-05)

Lifehug is one product in multiple mediums: this local companion, the hosted
platform (lifehug/lifehug-platform), future mobile apps. Mediums differ in
HOW, never in WHAT — user-facing capabilities stay feature-equivalent,
adapted to each medium. The rule is bidirectional: **any session building a
user-facing feature here files the twin issue on lifehug-platform in the
same pass (and vice versa), or records in the PR why the feature doesn't
translate to the other medium.** Hosted infrastructure (sessions, invite
gates, durable stores) is not a feature and needs no twin. Design/theming
parity is deliberately deferred until the platform's design settles
(lifehug-platform#236 tracks the future shared design library).
First backfill wave from the platform's UI build: issues #51–#54 here.

## Git Conflict Resolution — State File Safety

**This section is the UPGRADE case**: pulling framework changes from the
upstream template, where remote is newer framework and local is the only copy
of this author's state. If instead you are pulling **the author's own vault**
shared across several machines or a hosted environment, the answer inverts —
remote is another operator's legitimate state and wins. See CLAUDE.md →
"Shared Vault: One Vault, Many Machines". Check which pull you are in first.

Lifehug state files track delivery history, coverage, and the question queue. During `git pull --rebase` or merge conflicts, **never blindly accept remote for state files** — doing so erases the record of what was asked, answered, and delivered, causing duplicate questions and lost answers.

### State files (keep LOCAL on conflict)
- `system/rotation.json` — delivery counts, last question sent, send-today tracking
- `system/coverage.json` — per-category answer counts
- `state/question_queue.json` — planned queue with sent/queued status
- `state/source_manifest.json` — answer and source registry
- `system/question-bank.md` — checked-off questions

### Framework files (accept REMOTE on conflict)
- `system/version.json`, `system/lifehug.py`, `system/*.sh` — upstream upgrades
- `wiki/` pages — recompiled from source on next answer filing

### Safe rebase procedure
```bash
# Back up state before pulling
cp system/rotation.json /tmp/rotation-backup.json
cp state/question_queue.json /tmp/queue-backup.json

# Pull
git pull --rebase origin main

# On conflict: keep local state, accept remote framework.
# DURING A REBASE THE LABELS ARE INVERTED: your commits are replayed onto the
# remote, so --theirs is YOUR local side and --ours is the REMOTE side.
git checkout --theirs system/rotation.json system/coverage.json state/question_queue.json  # local state
git checkout --ours system/version.json  # remote framework, if conflicted
git add -A && GIT_EDITOR=true git rebase --continue

# Verify delivery state survived
python3 -c "import json; print(json.load(open('system/rotation.json')).get('delivery_counts'))"
```

### If a rebase is stuck (started but never finished)
```bash
git rebase --abort    # get back to a clean state
git pull --rebase origin main   # try again cleanly
```

Never leave a rebase in progress overnight — it blocks all subsequent git operations including answer filing.

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
3. **Acknowledge warmly** — Thank them, share a brief reflection on their answer, mention what's coming next. `python3 system/lifehug.py answer-ack-prompt` builds the canonical prompt for this (stdin: question/answer JSON) — the same tone contract the hosted platform uses, so behavior stays consistent whichever surface answered.

## Unprompted Story Ingest

If the user shares a life story that is not an answer to the current daily question, save it as source material instead of forcing it into an answer file:

```bash
printf '%s\n' "$STORY_TEXT" | python3 system/lifehug.py ingest-story --source "telegram" --title "<short title>"
python3 system/lifehug.py compile
python3 system/lifehug.py planner-report
```

This stores the raw story under `sources/manual/` and parks suggested follow-up questions in `state/question_candidates.json`. Candidates should inform planning and future question-bank edits; they should not automatically dominate daily delivery.

If the user states an **opinion** — a philosophical position or lens on life, not an event account (messages starting `opinion:` are explicit) — ingest it with `--kind opinion` and offer to develop it as an essay artifact:

```bash
printf '%s\n' "$OPINION_TEXT" | python3 system/lifehug.py ingest-story --kind opinion --source "telegram" --title "<short title>"
python3 system/lifehug.py artifact new --format essay --seed sources/manual/<opinion-file>.md
```

Opinion ingest generates Socratic follow-up candidates (origin, counterexample, evolution, dissent, stakes) instead of scene prompts. The `--seed` puts the opinion verbatim at the top of the essay's context pack; iterate with `artifact save --feedback` until the author says done, then promote.

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

The weekly Loop segment compiles offline, lints sources, applies safe source fixes only when lint finds them, classifies capped new sources, updates the quality profile, auto-promotes candidates under caps, writes the next planned queue, scans gaps in dry-run mode, reports progress, and autocommits real changes.

Both loops run on any machine (v92). Check `python3 system/lifehug.py ai-status` first: keyed (gateway or API key) runs are fully unattended; keyless runs need the agent as the model — follow `skills/maintenance/SKILL.md` (pre-complete AI work via `--emit-prompts`/`--emit-task`/`--from-response` before the run; a keyless cron emits its AI work to `state/agent_tasks/` instead of failing).

Run the monthly growth loop with:

```bash
python3 system/lifehug.py monthly-research
LIFEHUG_MONTHLY_DRY_RUN=1 system/monthly_research.sh
```

The monthly Loop segment compiles, detects gaps, opens a small capped set of new research neighborhoods, refreshes the self-knowledge arc if needed, recommends Focuses, reports progress, and autocommits real changes.

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

## Artifact Creation

If the user asks to write/create/draft a letter, post, caption, essay, chapter,
speech, or milestone deliverable, use the artifact workflow instead of raw
compose. Telegram/OpenClaw messages beginning with `/artifact`, `artifact:`, or
`opinion:` are explicit artifact requests, not daily answers.

```bash
python3 system/lifehug.py artifact new \
  --subject "<subject>" --occasion "<occasion>" --format <letter|tweet|instagram|post|essay|chapter>
python3 system/lifehug.py artifact prompt outputs/<artifact>
printf '%s\n' "$CONTENT" | python3 system/lifehug.py artifact save outputs/<artifact> --final
python3 system/lifehug.py artifact promote-source outputs/<artifact> --kind all
python3 system/lifehug.py compile
```

Promotion is opt-in and writes immutable sources under `sources/artifacts/`.
Final artifacts are authored-expression sources; context packs are derived
context sources. Do not rewrite those source bodies later.

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
- **Monthly**: Run `monthly-research`; review new candidates and Focus recommendations
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
- Connector state (ledger, cursor, date evidence, calibrated weights): `state/connectors/`
- Planned queue: `state/question_queue.json`
- Planner state: `state/planner_state.json`
- Answers: `answers/`
- Wiki: `wiki/`
- Outputs: `outputs/`
- Config: `config.yaml`
