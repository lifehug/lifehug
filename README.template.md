# Dave — Lifehug

A private, compounding life story system. Daily questions build raw material; Focuses shape it toward deliverables; the Studio turns that material into pieces (letters, posts, chapters) and projects like the book that Dave can actually send, publish, or keep.

## What this is

Lifehug is organized around **the Loop**: the self-improving flow where Dave answers one question by voice or text, the answer is saved as raw source material, the wiki compiles it into memory, classification and quality signals learn from it, and future questions get better. The Studio takes that accumulated memory and turns it into finished pieces — letters to family, anniversary notes, posts, chapters, speeches — and, over time, into projects like the book. Finished pieces can feed back into the same Loop as source material.

The wiki is the core memory layer — an AI-maintained knowledge graph connecting childhood, family, work, faith, Etherfuse, and the people who shaped the story. It is centered on **Dave himself** (the page **David James Taylor** — the self-portrait hub — leads the wiki, with his life-story arcs nested beneath). Everything stays owner-only. Sharing happens through reviewed pieces: letters, essays, posts, chapters, and future published pages. When a piece is final, its context and final text can be promoted back into `sources/artifacts/` (still the code-level term) so Lifehug learns from what Dave actually produced.

## Nomenclature

The wiki is a **graph of Dave's life**. The standard terms:

- **Node** — a graph vertex: a durable subject in Dave's life that can be compiled into a wiki page. People, places, periods, objects, themes, projects, and Dave himself are nodes.
- **Node Type** — graph vocabulary for the kind of node, such as person, place, period, object, theme, project, or life. Most current `Entity Type` values are node types; `relationship` is the exception because it represents an edge page.
- **Entity** — the current product/code term for a node-worthy subject; usually one wiki page. Keep using Entity in code and product flows where the system already does.
- **Entity Type** — the current product/code and frontmatter term for a wiki page kind: `person`, `place`, `period`, `object`, `theme`, `project`, `relationship`, and `life` (Dave himself). Most entity types are node types; `relationship` remains the compatibility page type for an edge page.
- **Edge** — a meaningful connection between nodes/entities. An edge can carry evidence, tension, change over time, and artifact relevance.
- **Relationship Edge** — a human bond edge, usually between Dave and another person. The page in `wiki/relationships/` is an edge page: it answers what the bond is, not merely who the other person is.
- **Focus** — an entity deliberately built toward a deliverable (book, letter, …) with a tier and target. **Dave is the primary Focus** — his life story is the biggest one and gets the largest share of questions. Self-knowledge (values, fears, contradictions, growth) is a built-in dimension of it, not a separate track.
- **Project** — a Focus whose deliverable is a composite piece built up over time. Today that's the book: the Focus's categories become chapters. A project is virtual while it's being planned — readiness is computed live from answered material — and becomes a concrete, versioned piece once `book-assemble` stitches the latest chapter drafts together.
- **Piece** — a single versioned work in the Studio: a letter, tweet, essay, or chapter draft. Lives under `outputs/<slug>/` as `v1.md`, `v2.md`, ... revisions, with AI revise, mark-final, and promote-back-to-source. The code/CLI term is unchanged: **artifact** (`system/lifehug.py artifact ...`).
- **Studio** — the one workspace for making pieces and projects: grouped by Focus, project cards expand into their chapter table, piece cards keep their version history, and a create form starts new pieces.
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
9. **Pieces get made** — when there is an occasion or deliverable, the Studio gathers the right context and helps produce the piece
10. **Finished pieces feed back** — approved final pieces and context packs become source material under `sources/artifacts/`

No ratings, no friction. The answer itself is the feedback.

## Studio: Projects & Pieces

The Studio is the product payoff — the reason the daily answers and wiki matter outside the system. Two kinds of work happen there:

- **Pieces** — single versioned works: a Mother's Day letter, an anniversary note, an Instagram caption, a post, a chapter, a speech.
- **Projects** — composite pieces built over time. Today that's the book: a Focus with a book-class deliverable whose chapters are its categories. A project is virtual while planning — its chapter verdicts are computed live — and becomes a concrete, versioned piece once `book-assemble` stitches the latest chapter drafts into one. (Per-format slot readiness like "4 of 5 letter slots covered for Mom" is the same idea applied to single pieces.)

The workflow creates a context pack from Dave's answers, wiki pages, prior pieces, and Focus material; drafts the piece; saves versioned drafts under `outputs/`; and can promote approved context/final versions back into immutable sources. A final piece is authoritative as Dave's authored expression at that moment. It is not treated as independent proof of every underlying event.

```bash
python3 system/lifehug.py artifact new --subject Mom --occasion "Mother's Day" --format letter
python3 system/lifehug.py artifact prompt outputs/<artifact>
printf '%s\n' "$CONTENT" | python3 system/lifehug.py artifact save outputs/<artifact> --final
python3 system/lifehug.py artifact promote-source outputs/<artifact> --kind all
```

Telegram/OpenClaw messages beginning with `/artifact` or `artifact:` should use this same flow. (`artifact` is the CLI/code-level name for a piece; the Studio is where you see and work them.)

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

## Connectors (external evidence)

Gmail connects as a **selective evidence and discovery source** — not a bulk import. A permanent metadata ledger (`state/connectors/gmail_ledger.jsonl`, no bodies) is re-scored in full on every `connector-excavate` run against the current wiki/rosters/sources — the ledger is permanent, relevance is recomputed, so old mail gains value as the story grows. Threads above the calibrated threshold promote automatically into immutable `sources/gmail/` external records (bounded by a per-run cap, `--dry-run`, and `connector-audit`); everything below stays metadata-only evidence. Institutional mail yields date evidence (which corroborates the timeline); unknown correspondents and untold threads surface as question candidates; an AI dossier pass can classify top unknowns (family auto-applies as VIPs — hand-declared `vip_correspondents` in `weights.json` always win). Threshold and weights are the owner's one-time, versioned call via `connector-calibrate`.

**New connectors** (Drive, Instagram/X exports, …) follow the same pattern: subclass `BaseConnector` in `system/connectors/<name>.py` (implement `fetch`, `extract_date_evidence`, `mine_discovery`), register it in `system/connector.py`, and scoring, threshold promotion, dossiers, and timeline corroboration come free. See *Connectors: calibrated external evidence ingestion* in the framework README.

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

# Create pieces (Studio)
python3 system/lifehug.py artifact new --subject Mom --occasion "Mother's Day" --format letter
python3 system/lifehug.py artifact prompt outputs/<artifact>
python3 system/lifehug.py artifact promote-source outputs/<artifact> --kind all

# Explore the wiki
python3 system/lifehug.py compile
python3 system/lifehug.py serve
# In the local viewer, Source Integrity opens each manifested raw source
# read-only and links to additive reflection/correction/retraction actions.

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

# Connectors (rare excavation — quarterly/yearly)
python3 system/lifehug.py connector-excavate gmail --dry-run   # preview promotions, write nothing
python3 system/lifehug.py connector-excavate gmail             # re-score whole ledger, delta-promote
python3 system/lifehug.py connector-report gmail               # ledger summary
python3 system/lifehug.py connector-audit gmail                # what got auto-promoted, with scores

# Full command list
python3 system/lifehug.py --help
```

## Local model (optional)

Every model-backed Loop surface can use an on-machine OpenAI-compatible server
such as Ollama, LM Studio, or llama.cpp. In gitignored `config.yaml`, set
`ai_provider: local`, `local_ai_base_url`, `local_ai_model`, and
`local_ai_timeout_seconds`, then run `python3 system/lifehug.py ai-status`.
Lifehug accepts loopback endpoints by default; an offline server returns to
keyless agent-task mode without sending source material to a cloud fallback.
The Anthropic SDK is optional. When it is absent, `ai-status` reports the
Anthropic route as not ready and the existing agent-task paths remain usable.

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

Local writes are serialized by `system/jobs.py`: viewer actions, answer
filing, artifact changes, compiles, and scheduled loops share one restart-safe
worker/kernel lock. Runtime records and private mode-0600 payload sidecars live
under gitignored `state/jobs/`; failed or ambiguous payloads are retained for
owner review and can be removed with `python3 system/jobs.py purge <job-id>`.
See `examples/launchd/README.md` for macOS worker and schedule examples.
Queue administration uses `system/jobs.py`; canonical vault mutations remain
commands of `system/lifehug.py`.

## Coverage
📊 182/343 questions answered · 8 focuses active

---

*Powered by [Lifehug](https://github.com/lifehug/lifehug)*
