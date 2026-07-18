# Dave — Lifehug

A private, compounding life story system. Daily questions build raw material; Focuses shape it toward deliverables; Artifacts turn that material into letters, posts, chapters, and other things Dave can actually send, publish, or keep.

## What this is

Lifehug is organized around **the Loop**: the self-improving flow where Dave answers one question by voice or text, the answer is saved as raw source material, the wiki compiles it into memory, classification and quality signals learn from it, and future questions get better. The artifact path takes that accumulated memory and turns it into finished pieces: letters to family, anniversary notes, posts, chapters, speeches, and future book material. Final artifacts can feed back into the same Loop as source material.

The wiki is the core memory layer — an AI-maintained knowledge graph connecting childhood, family, work, faith, Etherfuse, and the people who shaped the story. It is centered on **Dave himself** (the page **David James Taylor** — the self-portrait hub — leads the wiki, with his life-story arcs nested beneath). Everything stays owner-only. Sharing happens through reviewed artifacts: letters, essays, posts, chapters, and future published pages. When an artifact is final, its context and final text can be promoted back into `sources/artifacts/` so Lifehug learns from what Dave actually produced.

## Nomenclature

The wiki is a **graph of Dave's life**. The standard terms:

- **Node** — a graph vertex: a durable subject in Dave's life that can be compiled into a wiki page. People, places, periods, objects, themes, projects, and Dave himself are nodes.
- **Node Type** — graph vocabulary for the kind of node, such as person, place, period, object, theme, project, or life. Most current `Entity Type` values are node types; `relationship` is the exception because it represents an edge page.
- **Entity** — the current product/code term for a node-worthy subject; usually one wiki page. Keep using Entity in code and product flows where the system already does.
- **Entity Type** — the current product/code and frontmatter term for a wiki page kind: `person`, `place`, `period`, `object`, `theme`, `project`, `relationship`, and `life` (Dave himself). Most entity types are node types; `relationship` remains the compatibility page type for an edge page.
- **Edge** — a meaningful connection between nodes/entities. An edge can carry evidence, tension, change over time, and artifact relevance.
- **Relationship Edge** — a human bond edge, usually between Dave and another person. The page in `wiki/relationships/` is an edge page: it answers what the bond is, not merely who the other person is.
- **Focus** — an entity deliberately built toward a deliverable (book, letter, …) with a tier and target. **Dave is the primary Focus** — his life story is the biggest one and gets the largest share of questions. Self-knowledge (values, fears, contradictions, growth) is a built-in dimension of it, not a separate track.
- **Entity graduation / node graduation** — entities mentioned across answers are detected, AI-curated into a roster (`state/entity_rosters/<type>.json`), and graduated into node pages from their mentions. Places/periods graduate on a low bar (a few mentions); **objects** graduate on symbolic meaning (the cleats, the orange shorts), not frequency; people on score. Relationship edges use a dyadic path: Focus relationship pages can graduate from dedicated answers or enough cross-story mentions about the person. Rosters refresh monthly; compile graduates the current roster entries into pages, so the graph grows on its own.
- **The Loop** — the canonical continuous-learning cycle: capture source → compile wiki → lint/repair source truth → classify/score signals → promote candidates and plan the queue → ask a better question → create artifacts → feed final artifacts back as source.
- **In the Loop** — code, state, or docs reached by the daily, weekly, monthly, or artifact flows, and whose output can affect Dave's future questions, wiki pages, relationship understanding, or artifacts.
- **Loop-adjacent** — useful manual, dry-run, inspection, setup, or repair surfaces. They support the Loop but do not change future behavior until their output is promoted into a Loop surface.
- **Out of the Loop** — code or data that exists but is not called by Loop entrypoints and is not read downstream. Mission-critical features should not remain here.

## Focuses

Nine objectives on the roadmap, each with a tier, a target answer count, and a deliverable:

```bash
python3 system/lifehug.py roadmap     # current state
python3 system/lifehug.py progress    # readiness toward deliverables
```

Focuses drive the weekly question allocation. **David James Taylor** is the primary Focus (the biggest share); saturated Focuses fade to maintenance; empty ones get more weight. The planner balances variety, story-function coverage, and a reserved inner-story (self-knowledge) slot across the week.
- ⭐ **David James Taylor** — primary (life story; A–E)
- 🟡 **Mom** (15/24)
- 🟢 **Katie** (21/21)
- 🔴 **Dad** (1/13)
- 🔴 **Charlee Joy Taylor** (1/13)
- 🔴 **James Everett Taylor** (2/11)
- 🔴 **Dottie Ovelle Taylor** (1/12)
- 🔴 **Harvey Rex Taylor** (1/10)
- 🔴 **Anthon James Taylor** (1/10)

## Schedule

| Cadence | What happens | Cost |
|---|---|---|
| **Daily** 7:35 AM | Compile wiki → pick question → send + pin to Telegram | free |
| **Hourly** :00 | Compile wiki + commit if new answers pending (sentinel-gated) | free |
| **Weekly** Sun 8 PM | Compile → source lint/fix → classify capped batch → quality profile update → candidate auto-promotion → Focus-weighted queue → gap detection → progress | keyless/capped |
| **Monthly** 1st 9 PM | Compile → capped research neighborhoods → self-knowledge refresh → Focus recommendations → progress | API $ |

## The Loop

1. **Question arrives** — drawn from the weekly queue (Focus-weighted, variety-capped)
2. **Dave answers** — voice or text, whenever he wants
3. **Answer is processed** — saved as source material, richness scored silently. Wiki compile is decoupled and runs hourly (or at daily question time), so batch answers never conflict
4. **Weekly source integrity checks run** — metadata, citations, and repair findings stay visible; safe metadata/manifest fixes apply automatically
5. **New sources are classified** — a capped weekly pass extracts structured meaning and adds reviewable follow-up candidates without rewriting the raw file
6. **Profile updates weekly** — aggregates scores by story function and category
7. **Profile feeds back** — planner weights and AI prompts shift toward what works
8. **Better questions** — high-quality candidates promote under caps, and next week's queue plus next month's research reflect the signal
9. **Artifacts get made** — when there is an occasion or deliverable, Lifehug gathers the right context and helps produce the piece
10. **Finished artifacts feed back** — approved final pieces and context packs become source material under `sources/artifacts/`

No ratings, no friction. The answer itself is the feedback.

## Artifacts

Artifacts are the product payoff. They are the reason the daily answers and wiki matter outside the system: a Mother's Day letter, an anniversary note, an Instagram caption, a post, a chapter, or a speech.

The workflow creates a context pack from Dave's answers, wiki pages, prior artifacts, and Focus material; drafts the piece; saves versioned drafts under `outputs/`; and can promote approved context/final versions back into immutable sources. A final artifact is authoritative as Dave's authored expression at that moment. It is not treated as independent proof of every underlying event.

```bash
python3 system/lifehug.py artifact new --subject Mom --occasion "Mother's Day" --format letter
python3 system/lifehug.py artifact prompt outputs/<artifact>
printf '%s\n' "$CONTENT" | python3 system/lifehug.py artifact save outputs/<artifact> --final
python3 system/lifehug.py artifact promote-source outputs/<artifact> --kind all
```

Telegram/OpenClaw messages beginning with `/artifact` or `artifact:` should use this same flow.

## Source integrity

`answers/` and `sources/` are Dave's raw source-of-truth layer. The wiki, planner queue, question candidates, and output drafts are derived from those files.

If an old memory was wrong, Dave adds a correction. If his understanding changed, he adds a reflection. Both become new source files under `sources/corrections/`, so the wiki can preserve the original memory and the later understanding together.

The source-integrity segment of the Loop is:

```text
capture source → compile wiki → weekly lint/fix → classify new sources → update quality → re-plan questions → ask better questions
```

## Source classification

`classify_story.py` is the structured-understanding pass. It reads immutable answer/source files and writes derived records under `state/classifications/`: people, places, periods, themes, contradictions, possible outputs, Focus opportunities, self-understanding insights, and candidate follow-up questions. Weekly maintenance classifies a capped batch (`LIFEHUG_WEEKLY_CLASSIFY_LIMIT`, default `5`) before candidate promotion, so a large archive import cannot dominate Dave's future questions. Weekly dry-run previews the candidate promotion gate before the real job mutates the candidate store or question bank.

## Neighborhood readiness

Research neighborhoods track three different stages: questions generated, questions promoted into the bank, and answers captured. A full candidate arc means Lifehug knows what to ask next; it does **not** mean Dave has enough source material to draft an artifact. `progress` only labels a neighborhood ready to draft when the answered-material score crosses the readiness threshold.

## Key commands

```bash
# See where things stand
python3 system/lifehug.py status
python3 system/lifehug.py roadmap
python3 system/lifehug.py progress
python3 system/lifehug.py quality-stats
LIFEHUG_WEEKLY_DRY_RUN=1 system/weekly_maintenance.sh  # previews candidate auto-promotion too
LIFEHUG_MONTHLY_DRY_RUN=1 system/monthly_research.sh

# Process an answer
printf '%s\n' "$ANSWER" | python3 system/lifehug.py process-answer A14a --source "voice (transcribed)"

# Manage Focuses
python3 system/lifehug.py focus-add "Name" --type person --tier standard --deliverable letter
python3 system/lifehug.py focus-new    # guided scaffolding for a new Focus + category

# Create artifacts
python3 system/lifehug.py artifact new --subject Mom --occasion "Mother's Day" --format letter
python3 system/lifehug.py artifact prompt outputs/<artifact>
python3 system/lifehug.py artifact promote-source outputs/<artifact> --kind all

# Explore the wiki
python3 system/lifehug.py compile
python3 system/lifehug.py serve

# Grow the story graph
python3 system/lifehug.py weekly-maintenance
python3 system/lifehug.py monthly-research
python3 system/lifehug.py classify-story --classify-all --unclassified --limit 5
python3 system/lifehug.py candidates-list --status needs_review
python3 system/lifehug.py candidates-review --status needs_review
python3 system/lifehug.py candidates-update <candidate-id> --status deferred --reason "wait for more context"

# Source integrity
python3 system/lifehug.py source-scan
python3 system/lifehug.py source-lint
python3 system/lifehug.py source-lint --fix
python3 system/lifehug.py source-findings
printf '%s\n' "$CORRECTION" | python3 system/lifehug.py correct-source answers/A14a.md --kind factual
printf '%s\n' "$REFLECTION" | python3 system/lifehug.py reflect-source answers/A14a.md

# Full command list
python3 system/lifehug.py --help
```

## Structure

```
answers/          prompted answers; raw source-of-truth
sources/          unprompted stories, imports, corrections, reflections, promoted artifacts
outputs/          artifact tasks and drafts
wiki/             compiled private wiki, centered on David James Taylor (life/ hub + arcs;
                  people, places, periods, objects, themes, projects, relationships)
state/            roadmap, queue, quality profile, candidates, classifications, entity_rosters/, source manifest
profile.yaml      committed identity/prefs (name, full_name, timezone); secrets stay in .env/config.yaml
system/           all scripts — the system is script-first
```

## Coverage
📊 182/343 questions answered · 8 focuses active

---

*Powered by [Lifehug](https://github.com/lifehug/lifehug)*
