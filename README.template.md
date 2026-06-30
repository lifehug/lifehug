# {name} — Lifehug

{description}

## Nomenclature

This wiki is a **graph of {name}'s life**. Standard terms:

- **Entity** — a node in the graph; one wiki page (a person, place, period, object, theme, project, relationship, or {name}'s own life story).
- **Entity Type** — the kind of entity / index section: `person`, `place`, `period`, `object`, `theme`, `project`, `relationship`, and `life` ({name}).
- **Focus** — an entity deliberately built toward a deliverable (book, letter, …). **{name} is the primary Focus** — their life story is the biggest, with self-knowledge built in as a dimension of it.
- **Entity graduation** — entities mentioned across answers are detected, AI-curated into a roster, and graduated into pages automatically. Places/periods graduate on a low bar; objects on symbolic meaning; people on score. The graph grows without manual work.

## Focuses
{projects}

*Each Focus is something I'm building toward — a person, a book, a theme — with an objective and a tier. See the live roadmap with `python3 system/lifehug.py roadmap` and progress toward deliverables with `python3 system/lifehug.py progress`.*

## Focuses
*People and episodes discovered as I answer questions; each becomes a Focus on the roadmap.*

## Artifacts
*Artifacts are the product payoff: letters, tweets, Instagram captions, posts, chapters, speeches, and other pieces made from accumulated life material. Drafts live in `outputs/`. Create them with `python3 system/lifehug.py artifact ...`; when final, promote context/final versions into `sources/artifacts/` so the wiki can learn from what was produced.*

## Source Integrity
*Prompted answers in `answers/` and ingested stories in `sources/` are raw source-of-truth. Corrections and later reflections are added as new source files, not by rewriting old memories. Check with `python3 system/lifehug.py source-lint`.*

## Source Classification
*`classify_story.py` is the structured-understanding pass. It extracts people, places, periods, themes, contradictions, possible outputs, Focus opportunities, self-understanding insights, and follow-up candidates from answers/sources. Weekly maintenance works through unclassified files in capped batches using the OpenClaw-first AI path.*

## Weekly Maintenance
*Run `python3 system/lifehug.py weekly-maintenance` to compile, lint/fix safe source metadata, classify a capped batch of unclassified sources, update the quality profile, auto-promote good candidates, write the next queue, scan gaps, and report progress.*

## Monthly Research
*Run `python3 system/lifehug.py monthly-research` to open a capped set of new research neighborhoods, refresh self-knowledge candidates, recommend Focuses, and report progress.*

## Coverage
📊 0/0 questions answered

---

*Powered by [Lifehug](https://github.com/lifehug/lifehug)*
