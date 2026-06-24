# Lifehug

**Capture, deepen, and connect your life story over time.**

Lifehug is a lifelong AI oral-history system. It asks one thoughtful question at a time, accepts voice or text answers, tracks what has been covered, and keeps returning to your story with better follow-up questions. The goal is not just journaling. The goal is a compounding, AI-assisted memory system that helps you articulate your life, discover patterns, and produce real artifacts: letters, essays, chapters, memoirs, family histories, founder stories, and eventually an evolving private wiki of your life.

The long-term model is inspired by the EKB / Karpathy-style "LLM Wiki" idea: raw sources are not only searched at query time. They are incrementally compiled into a living, interlinked knowledge base. For Lifehug, those sources are daily answers, voice transcripts, and eventually personal archives like email, chats, photos, social posts, documents, and calendars. The compiled wiki becomes the source of truth that helps an AI see relationships across people, places, time periods, projects, and themes that may not be obvious from any single answer.

---

## What You Can Create

### Focuses — the things you're building toward
A **Focus** is anything you want to capture and eventually produce something from: a person, a book, a blog, a theme, your life's work. Each Focus has an **objective** ("a founding-story book", "a letter to Mom") and a **tier** that sets how deep it goes:

| Tier | For | Depth |
|------|-----|-------|
| `basic` | a blog post, a tweet | ~8 answers |
| `standard` | an essay, a chapter, a person | ~20 answers |
| `extreme` | a book, your life's work | ~50+ answers |

Lifehug meters your daily questions across all your Focuses at once — heavy on the under-filled ones, easing off the ones that are already well-covered, and never letting any single Focus (even a 50-question book) take more than ~30% of a week. So you make real progress toward each deliverable without spending every day on the same thing. When you want to *finish* one, flag it `finishing` and it gets a bigger share until it's done.

**Adding one is one step.** Type `/focus` in Claude Code (or just tell your AI "add a focus on X" via Telegram) and it interviews you briefly, then `focus-new` scaffolds the category, registers the Focus, and auto-generates its first ~8–12 questions — answerable the next day.

### Understanding yourself and your relationships
Beyond telling stories, Lifehug helps you **understand yourself** and **the people in your life** — drawing on We're Not Really Strangers, the 36 Questions, and parts-work therapy. It asks escalating, honest self-knowledge questions (values, fears, contradictions, how others see you) and *relational* questions about specific people (what you see in them, what you'd want them to know, how they see you). These build the self and relationship layers of your wiki.

### A private life wiki — your relational database
This is the heart of the system. As you answer, Lifehug compiles your raw answers into an owner-only, cross-linked **wiki** — the source of truth an AI reads to understand you and help everything else work:

- **People** — who they are, how they shaped you
- **Relationships** — the bond between you and each person, from both sides
- **Places** — homes, cities, schools, offices, countries, rooms
- **Periods** — seasons of life, transitions, hardships, golden eras
- **Projects** / **Life's work** — companies, creative work, missions
- **Themes** — hunger, agency, faith, money, belonging, grief, ambition
- **Self** — patterns, values, fears, and contradictions in your own words

Every page cites the answers it's built from. The wiki is a living layer of understanding on top of the raw story — and the surface a future synthesizer will run AI across to tell you things about yourself you haven't noticed.

---

## How It Works

### Daily Questions
Every day, the system picks one question and delivers it to you. You answer whenever you want — voice or text, long or short. There's no pressure.

### The Roadmap (how questions get chosen)
Your **roadmap** is the durable plan: the list of all your Focuses with their targets and how full each one is. Once a week, the planner builds the coming week's questions from it using a simple idea — give the most attention to what's under-filled, ease off what's well-covered, keep variety, and always reserve a slot for a self-knowledge question. Research for brand-new topics only kicks in once your existing Focuses start filling up and you need fresh ground. The daily delivery just hands you the next question from that plan; if the week's plan runs out, it falls back to balanced rotation.

See where you stand any time:

```bash
python3 system/lifehug.py roadmap     # every Focus, its tier, and how full it is
python3 system/lifehug.py progress     # what's ready to draft, and the command to draft it
```

### The Four-Pass System

The question bank is a living document that grows with every answer. The named passes below describe the early shape, but Lifehug is designed to keep going indefinitely. Over a lifetime, the system keeps walking the story graph: finding thin spots, revisiting themes, connecting earlier and later experiences, and turning important people, places, periods, and projects into Spotlights.

**Pass 1: Skeleton** (~3 months)
- Starter questions across all categories
- Goal: get the broad strokes down for every chapter
- After each answer, the AI generates 1-3 follow-up questions for the next pass

**Pass 2: Depth** (~2 months)
- Follow-up questions generated from your first-pass answers
- Go deeper into specific scenes, sensory detail, dialogue
- "You mentioned X — tell me more about that"

**Pass 3: Connections** (~1 month)
- Look across all answers for themes that connect across chapters
- Bridge questions that weave narrative threads through your story

**Pass 4: Polish** (ongoing)
- Read drafted chapters aloud
- Identify awkward transitions, missing context
- Final gap-filling questions

**Ongoing: Walk & Synthesize**
- Revisit older answers and wiki pages as new material arrives
- Add cross-links between people, places, periods, projects, and themes
- Flag contradictions, gaps, or sensitive areas before publishing
- Generate deeper questions from connections the author may not have noticed

### Coverage Tracking

After each pass, the system tracks progress per category:
- **🔴 RED** (0-30%) — needs skeleton answers
- **🟡 YELLOW** (30-70%) — needs depth
- **🟢 GREEN** (70%+) — ready for drafting

The rotation engine prioritizes RED categories, then YELLOW, then circles back to GREEN for polish.

### Spotlight Discovery

As you answer questions, the AI watches for significant people or events that come up repeatedly. It will offer to create a Spotlight:

> "You've mentioned [person] several times. Want to create a Spotlight to capture more about them?"

Spotlights get their own targeted questions and rotate at a lower frequency (roughly 1 Spotlight question per 3-4 main questions).

### Outputs

At any point — at milestones, on a Mother's Day, or whenever you ask — the AI composes outputs from your accumulated answers using `system/compose.py`:

- **Letters** — heartfelt, specific, written in your voice (`--format letter`)
- **Tweets** — one moment, condensed (`--format tweet`)
- **Instagram captions** — 2-4 short paragraphs, personal tone (`--format instagram`)
- **Chapter drafts** — literary nonfiction prose (`--format chapter`)

Each output lives in `outputs/{title}/`, with `v1.md`, `v2.md`, etc. for revisions. Ask the AI to revise with feedback ("make it more personal", "shorter") and it bumps to the next version. Interim outputs can ship before the full book is complete.

## Running It

Lifehug runs on three clocks plus the moment you answer. Set the cron jobs once (see [`examples/openclaw-cron.md`](examples/openclaw-cron.md) for copy-paste commands) and the system runs itself:

| When | What happens | Cost |
|------|--------------|------|
| **Every day** | `daily_question.sh` refreshes the wiki, then sends you today's question. You reply (voice or text); the answer is saved, the wiki recompiles, and progress updates. | free |
| **Weekly** (e.g. Sun evening) | Plans the coming week from your roadmap, detects thin spots, prints a progress report. | free |
| **Monthly** | Generates new question domains for areas you've filled up, refills the self-knowledge pool, and suggests new spotlights. | uses the AI API |

The only thing you do daily is **answer the question that arrives.** Everything else — picking the next question, keeping the wiki current, tracking progress toward your deliverables — is automatic. Check in whenever you like with `python3 system/lifehug.py progress`.

> **Why the wiki compiles before planning:** the wiki is the relational database the planner and research read from, so it's always rebuilt first. Keep it fresh, and everything downstream gets smarter.

## Architecture

Lifehug is git-backed, file-native, and script-first. Markdown is the durable source of truth; any search or database layer should be treated as a rebuildable index. The scripts in `system/` are the canonical behavior, while skills, agents, and cron jobs are thin operators that call those scripts.

```
lifehug/
├── answers/              # Daily question responses, one source file per answer
├── sources/              # Future imports: voice, email, chats, photos, social, docs
│   └── manual/           # Unprompted stories captured outside daily prompts
├── wiki/                 # Compiled private life wiki, AI-maintained with citations
│   ├── people/
│   ├── relationships/    # author↔person bonds (graph edges)
│   ├── self/             # self-knowledge surface
│   ├── places/
│   ├── periods/
│   ├── projects/
│   ├── lifes_work/
│   ├── themes/
│   └── objects/
├── outputs/              # Letters, posts, chapters, publishable artifacts
├── state/                # Rebuildable machine state
│   └── roadmap.json      # your Focuses (derived; manage via the CLI)
└── system/               # Framework scripts
```

Privacy model for the first pass: everything is owner-only. Lifehug prepares for future sharing with `visibility` and `sensitivity` metadata, but publishing should happen through reviewed outputs rather than broad access tiers inside the core wiki.

### Script-First Workflows

Use the workflow wrapper for manual, AI-agent, and cron operations:

```bash
python3 system/lifehug.py doctor
python3 system/lifehug.py status
python3 system/lifehug.py next
python3 system/lifehug.py progress          # progress toward deliverables (readiness)
python3 system/lifehug.py roadmap           # Focuses, tiers, saturation
python3 system/lifehug.py roadmap-rebuild   # re-derive the roadmap from the bank
python3 system/lifehug.py focus-add "Etherfuse" --type project --tier extreme --category F --category G
python3 system/lifehug.py focus-finish etherfuse
python3 system/lifehug.py rebuild
python3 system/lifehug.py compile
python3 system/lifehug.py ingest-story
python3 system/lifehug.py candidates-list
python3 system/lifehug.py candidates-promote
python3 system/lifehug.py planner-report
python3 system/lifehug.py planner-queue
python3 system/lifehug.py serve
python3 system/lifehug.py daily-dry-run
```

The wrapper delegates to the underlying scripts. Cron should call the same scripts as a human or skill-driven agent; it should not implement its own question picker, state editor, or wiki compiler.

Answer processing compiles the private wiki by default, so every saved daily response immediately updates the owner-only synthesis layer:

```bash
printf '%s\n' "$ANSWER_TEXT" | python3 system/lifehug.py process-answer A14 --source "voice (transcribed)"
```

Unprompted stories use the same source-first model without pretending they answered today's prompt:

```bash
printf '%s\n' "$STORY_TEXT" | python3 system/lifehug.py ingest-story --source "telegram" --title "Arizona memory"
python3 system/lifehug.py compile
python3 system/lifehug.py planner-report
```

This writes raw material to `sources/manual/`, creates suggested follow-up questions in `state/question_candidates.json`, and lets the planner show how new material should influence future questions. Candidates are a parking lot, not an automatic takeover of the daily queue.

Candidate questions can be reviewed, filtered, accepted, deferred, rejected, or promoted into the question bank with source provenance:

```bash
python3 system/lifehug.py candidates-review --status candidate
python3 system/lifehug.py candidates-update cand-2026-06-22-arizona-memory-1 --status accepted --target-category A
python3 system/lifehug.py candidates-promote cand-2026-06-22-arizona-memory-1 --category A
```

When you want a more intentional sequence, write an opt-in planned queue:

```bash
python3 system/lifehug.py planner-report --limit 10
python3 system/lifehug.py planner-objective-add "Prepare Mom letter" --category K --keyword mom
python3 system/lifehug.py planner-queue --limit 14 --arc-max 2 --expires-days 7
```

`planner-report` is read-only. It now shows group coverage, stale categories, overrepresented areas, story-function balance, recent ingest, open candidates, active objectives, and a recommended next queue preview. `ask.py` honors `state/question_queue.json` only when it exists, is not expired, and contains valid unanswered question-bank items. The planner reports candidates, but candidates are not asked until promoted into `system/question-bank.md`.

---

## Getting Started

### With OpenClaw (recommended)

1. **Clone and run setup:**
   ```bash
   git clone https://github.com/lifehug/lifehug.git ~/Workspace/lifehug
   cd ~/Workspace/lifehug && ./setup.sh
   ```
   Setup checks your environment, installs the Lifehug skill, and configures git remotes:
   - **upstream** → `lifehug/lifehug` (for receiving framework updates)
   - **origin** → your own repo (for saving your answers and progress)
   
   If you don't have a repo yet, no problem — skip it and set one up later. Your work saves locally via git commits. When you're ready: `git remote add origin <your-repo-url> && git push -u origin main`

2. **Tell your AI to set you up.** In your OpenClaw chat (Telegram, WhatsApp, Signal, Discord — whatever you use), say:
   ```
   Set up Lifehug in ~/Workspace/lifehug
   ```

3. **The AI walks you through setup:**
   - What do you want to write? (memoir, founder story, family history, etc.)
   - Who are the important people in your story?
   - What episodes do you already know you want to capture?

4. **It creates your custom question bank**, generates a personalized README for your repo, and sets up a daily cron job to send you one question per day on your preferred channel.

5. **Answer one question per day** — just reply in the same chat, voice or text. The Lifehug skill automatically detects your answer, processes it, generates follow-ups, updates your README progress, and pushes to git.

That's it. The system handles rotation, coverage tracking, follow-up generation, and deliverable drafting.

### With Other AI Tools

1. **Clone this repo** and run `./setup.sh`
2. **Open it with your AI assistant** (Claude Code, Cursor, or any AI that reads CLAUDE.md)
3. **The AI will guide you through setup** — same flow as above
4. **Set up your own daily delivery** — the AI will help you configure a scheduler for daily questions
5. **Answer one question per day** — the AI picks the question, you just respond

---

## Delivery

Lifehug works with whatever messaging channel you already use:

- **Telegram** — Get your daily question as a Telegram message, reply right there
- **WhatsApp** — Same flow, via WhatsApp
- **Signal, Discord, Slack** — Any channel your AI platform supports
- **Email** — Daily question email, reply to answer
- **CLI** — For terminal-first people
- **Voice** — Send a voice message as your answer; the AI transcribes and processes it

During setup, the AI configures a daily cron job that picks a question and sends it to you at your preferred time. You reply whenever you're ready — there's no timer.

### Installing the Skill Manually (OpenClaw)

If you didn't use `setup.sh`, install the skill manually so your AI can detect and process your answers:

```bash
ln -s ~/Workspace/lifehug/skill ~/.openclaw/skills/lifehug
```

---

## Keeping Up to Date

Lifehug includes a built-in update system. When new versions are released, your AI will let you know:

> *Lifehug v2 is available with spotlight improvements. Say "update lifehug" when you're ready.*

Updates only touch framework files (CLAUDE.md, system scripts, etc.). Your answers, question bank, config, and drafts are never modified.

You can also check manually:

```bash
python3 system/update.py --check
python3 system/update.py --apply
```

If you forked Lifehug, add the upstream remote so updates can be fetched:

```bash
git remote add upstream https://github.com/lifehug/lifehug.git
```

See [UPGRADING.md](UPGRADING.md) for details on migrating from a pre-update-system clone.

---

## File Structure

```
lifehug/
├── README.md                 # This file
├── CLAUDE.md                 # AI operating instructions (the skill)
├── AGENTS.md                 # OpenClaw workspace entry point
├── setup.sh                  # First-run setup helper
├── config.yaml.example       # Configuration template
├── config.yaml               # Your config (created during setup)
├── .gitignore
├── answers/                  # Your stored responses
│   └── {question_id}.md      # One file per answer, with metadata
├── sources/                  # Raw imported or manually captured source material
│   └── manual/               # Unprompted stories from chat, voice, notes, etc.
├── wiki/                     # Compiled private life wiki
│   ├── SCHEMA.md             # Wiki governance and page contracts
│   ├── people/
│   ├── places/
│   ├── periods/
│   ├── projects/
│   ├── themes/
│   ├── objects/
│   └── relationships/
├── outputs/                  # Composed outputs (letters, tweets, IG, chapters)
│   └── {title}/
│       ├── meta.yaml         # Format, subject, source categories, versions
│       └── v{N}.md           # Each revision lives as a versioned file
├── state/                    # Rebuildable planner/candidate state
│   ├── question_candidates.json
│   ├── question_queue.json
│   └── planner_state.json
├── templates/                # Format instructions used by compose.py
│   ├── letter.md
│   ├── tweet.md
│   ├── instagram.md
│   └── chapter.md
├── examples/
│   └── openclaw-cron.md      # Cron job examples for every channel
├── skill/
│   └── SKILL.md              # OpenClaw skill (auto-installed by setup.sh)
└── system/
    ├── question-bank.md      # All questions + status (grows over time)
    ├── lifehug.py            # Script-first workflow wrapper + doctor checks
    ├── ask.py                # Rotation engine (consumes the weekly queue)
    ├── roadmap.py            # Focus model + roadmap derivation/management
    ├── progress.py           # Deliverable-readiness dashboard
    ├── process_answer.py     # Atomic answer save + state update helper
    ├── ingest_story.py       # Unprompted story source ingest
    ├── question_candidates.py # Candidate review, update, and promotion
    ├── question_planner.py   # Planner report + opt-in queue generation
    ├── rebuild_state.py      # Recomputes derived coverage/README state
    ├── wiki_compile.py       # Compiles answers into the private Lifehug wiki
    ├── serve_wiki.py         # Owner-only local wiki viewer
    ├── compose.py            # Output composer (letters, tweets, IG, chapters)
    ├── gen_followups.py      # Pass transition / depth question generator
    ├── update.py             # Update manager (check, apply, rollback)
    ├── update_readme.py      # Refreshes Coverage section in README.md
    ├── version.json          # Current version tracking
    ├── rotation.json         # Current rotation state
    ├── coverage.json         # Gap tracking per category
    └── research.md           # Methodology reference
```

### Answer File Format
```markdown
# Question A1: What's your earliest memory?
**Category:** A (Origins) | **Pass:** 1
**Asked:** 2026-03-01 | **Answered:** 2026-03-01

---

[Your full answer here]

---

## Follow-up Questions Generated
- A11: "You mentioned [X] — can you describe that in more detail?"
- A12: "How old were you? Who else was there?"
```

---

## The Rotation Engine

Use the workflow wrapper for normal operation:

```bash
python3 system/lifehug.py next      # Pick but do not update state
python3 system/lifehug.py status    # Show coverage report
python3 system/lifehug.py rebuild   # Repair derived state
```

The lower-level `system/ask.py` script still manages question selection, but agents and cron should prefer `system/lifehug.py` or `system/daily_question.sh`.

### Selection Logic
1. Check which categories have the lowest coverage ratio
2. Alternate between project groups (if multiple books) to balance coverage
3. Interleave Spotlight questions at configured frequency
4. Pick the first unanswered question in the chosen category
5. Update rotation and coverage state

---

## Composing Outputs

`system/compose.py` builds versioned outputs from your accumulated answers. The script doesn't call AI itself — it assembles a prompt your AI processes, then saves the result.

```bash
# Generate a Mother's Day letter from the Katie spotlight
python3 system/compose.py --prompt --format letter --subject katie --title mothers-day-2026

# AI processes prompt → save the result
echo "$content" | python3 system/compose.py --save outputs/mothers-day-2026 \
    --format letter --subject katie --model anthropic/claude-opus-4-6

# Revise based on feedback
python3 system/compose.py --revise outputs/mothers-day-2026 --feedback 'make it more personal'

# Browse
python3 system/compose.py --list
python3 system/compose.py --info outputs/mothers-day-2026
```

Formats: `letter`, `tweet`, `instagram`, `chapter`. Each has its own template in `templates/`.

---

## Methodology

Lifehug's approach is based on established oral history and memoir-writing practices. See `system/research.md` for the full methodology, including:

- **StoryCorps** oral history techniques (open-ended questions, sensory anchors, emotional depth)
- **Professional ghostwriting** frameworks (discovery → outline → draft → revise → polish)
- **Memoir structure** analysis (hybrid chronological/thematic approach)
- **Founder story** patterns (problem → struggle → breakthrough arc)
- **Interview methodology** (specific moments over generalizations, follow-up depth, contrast questions)

The key insight: the best stories aren't told chronologically. They're organized around **turning points and themes**, built through multiple passes from skeleton to polish.

---

## Question Categories

Lifehug starts with five generic categories that work for any life story:

| Cat | Name | Focus |
|-----|------|-------|
| A | Origins | Childhood, family, early life, formative moments |
| B | Becoming | Growing up, finding direction, early career, pivotal moments |
| C | Relationships & People | Important people, friendships, mentors, how you connect |
| D | Purpose & Calling | What drives you, key decisions, turning points |
| E | Reflection & Wisdom | Lessons learned, values, advice, what matters |

During setup, the AI adds **project categories** (F-J) for what you want to write, and **spotlight categories** (K+) as important people and episodes surface. In v15 these all become **Focuses** on your roadmap automatically — each with an objective, a tier, and a target depth — so the planner can balance attention across them and track your progress toward each deliverable. Manage them with `lifehug.py roadmap` / `focus-add` / `focus-finish`.

---

*Lifehug — because every life is a story worth telling.*
