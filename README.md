# Lifehug

Capture, deepen, and connect your life story — one question at a time.

## What this is

Lifehug is a lifelong AI oral-history system. It asks one thoughtful question a day, accepts voice or text answers, and keeps returning to your story with better follow-up questions. Over time it compiles your answers into a private wiki — a cross-linked knowledge graph of the people, places, periods, projects, and themes that shaped your life.

The goal isn't journaling. It's a compounding system that helps you articulate your life and produce real artifacts: letters, essays, chapters, memoirs, family histories, founder stories.

## How it works

**You answer one question a day.** That's the only thing you do.

Everything else is automatic:

1. **Question arrives** — drawn from a weekly queue, balanced across your Focuses
2. **You answer** — voice or text, whenever you're ready
3. **Answer is processed** — saved, wiki recompiled, richness scored silently
4. **Quality profile updates weekly** — learns which question types open you up
5. **Better questions next week** — planner weights and AI prompts shift toward what works

No ratings, no friction. The answer itself is the feedback.

### Focuses — what you're building toward

A **Focus** is anything you want to capture and produce something from. Each has an objective and a tier that sets depth:

| Tier | For | Depth |
|------|-----|-------|
| `basic` | a blog post, a short piece | ~8 answers |
| `standard` | an essay, a letter, a person | ~20 answers |
| `extreme` | a book, your life's work | ~50+ answers |

The planner balances attention across all Focuses — heavy on under-filled ones, easing off what's well-covered, never letting any single Focus dominate. When you want to finish one, flag it `finishing` and it gets a bigger share until it's done.

Adding a Focus is one step:

```bash
python3 system/lifehug.py focus-new   # guided: interviews you, scaffolds category + questions
python3 system/lifehug.py focus-add "Mom" --type person --tier standard --deliverable letter
```

### The private wiki

As you answer, Lifehug compiles your raw answers into an owner-only, cross-linked wiki:

- **people/** — who they are, how they shaped you
- **relationships/** — the bond between you and each person
- **places/** — homes, cities, schools, countries
- **periods/** — seasons of life, transitions, hardships
- **projects/** — companies, creative work, missions
- **themes/** — recurring threads (hunger, agency, faith, belonging)
- **self/** — patterns, values, fears, contradictions in your own words

Every page cites the answers it's built from. The wiki is a living layer of understanding on top of the raw story.

### Outputs

At any milestone — Mother's Day, a birthday, or whenever you ask — compose from your accumulated answers:

```bash
python3 system/compose.py --prompt --format letter --subject katie --title mothers-day-2026
```

Formats: `letter`, `tweet`, `instagram`, `chapter`. Each output lives in `outputs/` with versioned revisions.

## Schedule

| Cadence | What happens | Cost |
|---|---|---|
| **Daily** | Compile wiki → pick question → deliver via Telegram/WhatsApp/etc | free |
| **Weekly** | Plan the coming week (Focus-weighted) → update quality profile → detect gaps | free |
| **Monthly** | Generate new research neighborhoods → recommend new Focuses | API $ |

See [`examples/openclaw-cron.md`](examples/openclaw-cron.md) for copy-paste cron setup.

## Getting started

### With OpenClaw (recommended)

```bash
git clone https://github.com/lifehug/lifehug.git ~/Workspace/lifehug
cd ~/Workspace/lifehug && ./setup.sh
```

Then tell your AI: **"Set up Lifehug in ~/Workspace/lifehug"** — it walks you through setup, creates your question bank, and configures daily delivery.

### With other AI tools

Clone, run `./setup.sh`, and open the repo with any AI that reads `CLAUDE.md` (Claude Code, Cursor, etc). The AI guides you through the same setup flow.

## Key commands

```bash
# See where things stand
python3 system/lifehug.py status
python3 system/lifehug.py roadmap
python3 system/lifehug.py progress
python3 system/lifehug.py quality-stats

# Process an answer
printf '%s\n' "$ANSWER" | python3 system/lifehug.py process-answer A14 --source "voice (transcribed)"

# Capture unprompted stories
printf '%s\n' "$STORY" | python3 system/lifehug.py ingest-story --source "telegram" --title "memory"

# Question management
python3 system/lifehug.py candidates-review
python3 system/lifehug.py candidates-promote <id> --category A
python3 system/lifehug.py planner-report
python3 system/lifehug.py planner-queue

# Wiki
python3 system/lifehug.py compile
python3 system/lifehug.py serve

# Full list
python3 system/lifehug.py --help
```

## Updating

```bash
python3 system/update.py --check
python3 system/update.py --apply
```

Updates only touch framework files. Your answers, question bank, config, and wiki are never modified.

## Structure

```
lifehug/
├── answers/          # one file per answered question
├── sources/manual/   # unprompted stories and ingested material
├── wiki/             # compiled private wiki (people, places, themes, etc)
├── outputs/          # composed artifacts (letters, essays, chapters)
├── state/            # roadmap, queue, quality profile, candidates
├── system/           # all scripts (the system is script-first)
├── templates/        # output format templates
├── skill/            # OpenClaw skill
├── config.yaml       # your config
└── CLAUDE.md         # AI operating instructions
```

## Methodology

Lifehug draws from StoryCorps oral history, professional ghostwriting frameworks, We're Not Really Strangers, the 36 Questions, and narrative therapy. The key insight: the best stories aren't told chronologically — they're organized around turning points and themes, built through multiple passes from skeleton to polish. See `system/research.md` for the full methodology.

---

*Lifehug — because every life is a story worth telling.*
