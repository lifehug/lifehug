# Lifehug

**Capture your life story, one question at a time.**

Lifehug is an AI-guided storytelling system that helps you write your life story through daily questions. You tell the AI what you want to create — a memoir, a founder's story, a family history — and it generates questions, manages rotation, tracks coverage, and helps you produce real deliverables over time.

---

## What You Can Create

### Books
Long-form narrative projects organized into chapters and acts. A memoir, a company founding story, a creative journey — whatever story you want to tell. Each book gets its own set of question categories, and the system rotates through them to build complete coverage.

### Spotlights
Focused collections about important life episodes. A turning point, a season of your life, a project that changed everything — Spotlights let you zoom in on moments that deserve their own space. They produce standalone essays, short stories, and narrative pieces.

### People
Every story is really about people. As you answer daily questions, the people who shaped your life naturally surface — a parent, a mentor, a co-founder, a friend who showed up at the right moment. Lifehug lets you deepen those threads. Write down your feelings, thoughts, and experiences with the people who matter. Capture what they taught you, how they changed you, what you wish you'd said. These become standalone essays, letters, character profiles — pieces that can live on their own or weave into a larger book.

---

## How It Works

### Daily Questions
Every day, the system picks one question and delivers it to you. You answer whenever you want — voice or text, long or short. There's no pressure. The questions are chosen by a rotation engine that ensures balanced coverage across all your projects.

### The Four-Pass System

The question bank is a living document that grows with every answer.

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

### Deliverables

At milestones, the AI drafts content from your accumulated answers:
- **Books**: Chapter drafts, standalone essays, full manuscripts
- **Spotlights**: Character profiles, letters, short stories, essays

Interim deliverables (essays, letters) can ship before the full book is complete.

---

## Getting Started

### With OpenClaw (recommended)

1. **Clone and run setup:**
   ```bash
   git clone https://github.com/lifehug/lifehug.git ~/Workspace/lifehug
   cd ~/Workspace/lifehug && ./setup.sh
   ```
   This checks your environment, installs the Lifehug skill, and tells you what to do next.

2. **Tell your AI to set you up.** In your OpenClaw chat (Telegram, WhatsApp, Signal, Discord — whatever you use), say:
   ```
   Set up Lifehug in ~/Workspace/lifehug
   ```

3. **The AI walks you through setup:**
   - What do you want to write? (memoir, founder story, family history, etc.)
   - Who are the important people in your story?
   - What episodes do you already know you want to capture?

4. **It creates your custom question bank** and sets up a daily cron job to send you one question per day on your preferred channel.

5. **Answer one question per day** — just reply in the same chat, voice or text. The Lifehug skill automatically detects your answer, processes it, generates follow-ups, and tracks your progress.

That's it. The system handles rotation, coverage tracking, follow-up generation, and deliverable drafting.

### With Other AI Tools

1. **Clone this repo**
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
├── spotlights/               # Spotlight deliverables
│   └── {name}/               # Profiles, letters, stories per spotlight
├── drafts/                   # Chapter drafts, essays, deliverables
├── examples/
│   └── openclaw-cron.md      # Cron job examples for every channel
├── skill/
│   └── SKILL.md              # OpenClaw skill (auto-installed by setup.sh)
└── system/
    ├── question-bank.md      # All questions + status (grows over time)
    ├── ask.py                # Rotation engine (CLI tool)
    ├── update.py             # Update manager (check, apply, rollback)
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

The `system/ask.py` script manages question selection:

```bash
python3 system/ask.py              # Pick next question, update state
python3 system/ask.py --dry-run    # Pick but don't update state
python3 system/ask.py --status     # Show coverage report
python3 system/ask.py --mark-answered A1  # Mark a question as answered
```

### Selection Logic
1. Check which categories have the lowest coverage ratio
2. Alternate between project groups (if multiple books) to balance coverage
3. Interleave Spotlight questions at configured frequency
4. Pick the first unanswered question in the chosen category
5. Update rotation and coverage state

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

During setup, the AI adds **project-specific categories** (F-J) based on what you want to write about. Spotlight categories (K+) are added as you discover people and episodes worth focusing on.

---

*Lifehug — because every life is a story worth telling.*
