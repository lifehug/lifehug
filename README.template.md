# {name} — Lifehug

{description}

## Nomenclature

This wiki is a **graph of {name}'s life**. Standard terms:

- **Node** — a graph vertex: a durable subject in {name}'s life that can be compiled into a wiki page.
- **Node Type** — graph vocabulary for the kind of node: person, place, period, object, theme, project, or life. Most current `Entity Type` values are node types; `relationship` is the exception because it represents an edge page.
- **Entity** — the current product/code term for a node-worthy subject; usually one wiki page (a person, place, period, object, theme, project, or {name}'s own life story).
- **Entity Type** — the current product/code and frontmatter term for a wiki page kind: `person`, `place`, `period`, `object`, `theme`, `project`, `relationship`, and `life` ({name}). Most entity types are node types; `relationship` remains the compatibility page type for an edge page.
- **Edge** — a meaningful connection between nodes. A **Relationship Edge** is a human bond edge, usually between {name} and another person; `wiki/relationships/` stores edge pages.
- **Focus** — an entity deliberately built toward a deliverable (book, letter, …). **{name} is the primary Focus** — their life story is the biggest, with self-knowledge built in as a dimension of it.
- **Entity graduation / node graduation** — entities mentioned across answers are detected, AI-curated into a roster, and graduated into node pages automatically. Places/periods graduate on a low bar; objects on symbolic meaning; people on score. Relationship edges use a dyadic path: Focus relationship pages can graduate from dedicated answers or enough cross-story mentions about the person. The graph grows without manual work.
- **The Loop** — the continuous-learning flow: capture source → compile wiki → lint/repair source truth → classify/score signals → promote candidates and plan the queue → ask a better question → create artifacts → feed final artifacts back as source. Features are **In the Loop** when daily, weekly, monthly, or artifact flows reach them and their output can improve future questions, wiki pages, relationship understanding, or artifacts.

## Focuses
{projects}

*Each Focus is something I'm building toward — a person, a book, a theme — with an objective and a tier. See the live roadmap with `python3 system/lifehug.py roadmap` and progress toward deliverables with `python3 system/lifehug.py progress`.*

## Focuses
*People and episodes discovered as I answer questions; each becomes a Focus on the roadmap.*

## Artifacts
*Artifacts are the product payoff: letters, tweets, Instagram captions, posts, essays, chapters, speeches, and other pieces made from accumulated life material. Drafts live in `outputs/`. Create them with `python3 system/lifehug.py artifact ...`; when final, promote context/final versions into `sources/artifacts/` so the wiki can learn from what was produced.*

*Opinions are a first-class lane (v95): a stated position/lens on life is captured with `ingest-story --kind opinion`, developed into an essay artifact seeded from that source (`artifact new --format essay --seed …`), and revised until done. Promoting the finished essay turns it into source material that influences the wiki — theme pages, the author hub — while the opinion itself gets Socratic follow-up questions that deepen it over time.*

## Source Integrity
*Prompted answers in `answers/` and ingested stories in `sources/` are raw source-of-truth. Corrections and later reflections are added as new source files, not by rewriting old memories. Check with `python3 system/lifehug.py source-lint`.*

## Source Classification
*`classify_story.py` is the structured-understanding pass. It extracts people, places, periods, themes, contradictions, possible outputs, Focus opportunities, self-understanding insights, and follow-up candidates from answers/sources. Weekly maintenance works through unclassified files in capped batches using the OpenClaw-first AI path.*

## Weekly Maintenance
*Run `python3 system/lifehug.py weekly-maintenance` to compile, lint/fix safe source metadata, classify a capped batch of unclassified sources, update the quality profile, auto-promote good candidates, write the next queue, scan gaps, and report progress. Dry-run previews candidate promotion before the real weekly job mutates the question bank.*

## Neighborhood Readiness
*Research neighborhoods track generated questions, promoted questions, and captured answers separately. A full candidate arc means the system knows what to ask; only an answer-ready arc is ready to become an artifact.*

## Monthly Research
*Run `python3 system/lifehug.py monthly-research` to open a capped set of new research neighborhoods, refresh self-knowledge candidates, recommend Focuses, and report progress.*

## Coverage
📊 0/0 questions answered

---

*Powered by [Lifehug](https://github.com/lifehug/lifehug)*
