---
title: Glossary
parent: Handbook
nav_order: 99
---

# Glossary

Every standard term, defined once. Feature pages link here instead of
re-defining. Seeded verbatim from the README's Nomenclature section at
v171; as feature pages land, terms they own move here as the single
definition and the README slims to a pointer.

The wiki is a **graph of your life**, and these are the standard terms used throughout:

- **Node** — a graph vertex: a durable subject in your life that can be compiled into a wiki page. People, places, periods, objects, themes, projects, and *you* are nodes.
- **Node Type** — graph vocabulary for the kind of node, such as person, place, period, object, theme, project, or life. Most current `Entity Type` values are node types; `relationship` is the exception because it represents an edge page.
- **Entity** — the current product/code term for a node-worthy subject; usually one wiki page. Keep using Entity in code and product flows where the system already does.
- **Entity Type** — the current product/code and frontmatter term for a wiki page kind: `person`, `place`, `period`, `object`, `theme`, `project`, `relationship`, and `life` (you). Most entity types are node types; `relationship` remains the compatibility page type for an edge page.
- **Edge** — a meaningful connection between nodes/entities. An edge can carry evidence, tension, change over time, and artifact relevance.
- **Relationship Edge** — a human bond edge, usually between you and another person. The page in `wiki/relationships/` is an edge page: it answers what the bond is, not merely who the other person is.
- **Focus** — an entity you're deliberately building toward a deliverable (book, letter, …), with a tier and target. **You are the primary Focus** — your own life story is the biggest one and gets the largest share of questions; self-knowledge (values, fears, contradictions, growth) is a built-in dimension of it, not a separate track.
- **Project** — a Focus whose deliverable is a composite piece built up over time. Today that's the book: your categories become chapters. A project is virtual while you're planning it — readiness is computed live from the roadmap and answered material — and becomes a concrete, versioned piece once `book-assemble` stitches the latest chapter drafts together.
- **Piece** — a single versioned work in the Studio: a letter, tweet, essay, or chapter draft. Lives under `outputs/<slug>/` as `v1.md`, `v2.md`, ... revisions, with AI-assisted revise, mark-final, and promote-back-to-source. The code/CLI term is unchanged: **artifact** (`system/lifehug.py artifact ...`, `sources/artifacts/`).
- **Studio** — the single workspace for making pieces and projects: grouped by Focus, project cards expand into a chapter table, piece cards keep their version/revision history, and a create form starts new pieces.
- **Entity graduation / node graduation** — the wiki grows itself: entities mentioned across your answers are detected, **AI-curated** into a roster (`lifehug.py entity-roster --type <t>`), and graduated into node pages built from those mentions. Places and periods graduate on a low bar (a few mentions); **objects** graduate on AI-judged symbolic meaning (e.g. *The Cleats*), not frequency; people on score; **themes** via an AI-curated keyword roster (v97) — new themes like *Parenting* emerge from opinions, essays, and classifier extractions. Relationship edges use a dyadic path: Focus relationships can graduate from dedicated answers or enough cross-story mentions about the person. Rosters refresh monthly; compile graduates the current roster entries into pages — no manual work.
- **The Loop** — the canonical continuous-learning cycle: capture source → compile wiki → lint/repair source truth → classify/score signals → promote candidates and plan the queue → ask a better question → create artifacts → feed final artifacts back as source. When we ask whether a feature "works in the Loop," we mean this path.
- **In the Loop** — code, state, or docs reached by the daily, weekly, monthly, or artifact flows without a human manually stitching it together, and whose output can affect future questions, wiki pages, relationship understanding, or artifacts.
- **Loop-adjacent** — useful manual, dry-run, inspection, setup, or repair surfaces. They support the Loop but do not change future behavior until their output is promoted into a Loop surface.
- **Out of the Loop** — code or data that exists but is not called by scheduled/manual Loop entrypoints and is not read by downstream Loop state. Mission-critical work should not stay here; wire it in or document it as experimental.
- **Interaction** — a role definition for the AI in one situation: purpose, behavior contract, context recipe, scope, and evals, packaged as files any qualified model can execute. The definition lives in the framework (`interactions/<name>/`); each runtime loads it; a model is "seated" in it only after passing its eval harness. Out-of-scope input is politely deflected. Three today: **conversation** (chats + longer sessions), **question judgment** (which follow-up candidates deserve to exist, and how urgently — ADR 0007), and **focus curation** (judging first-encounter Focus/idea duplicate name variants the deterministic layers can't resolve — ADR 0010).
- **Chat** — the short exchange around the daily question: system-initiated, ~3 exchanges, arc-carded, graceful third-turn exit, closing takeaway.
- **Conversation** — a long user-initiated session (a story, "something on your mind", or a thread the system offered); runs the full interviewer arc; closes with a narrative takeaway.
- **Arc card** — the pre-planned skeleton for a chat/conversation: opening framing + 2–4 follow-up *intents* (not scripted text), planned by the loops, executed live per turn.
- **Session** — one bounded run: open → turns → close; the durable record is the session document.

---
