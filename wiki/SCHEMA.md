# Lifehug Wiki Schema

This wiki is an owner-only, AI-maintained memory layer. It compiles raw story sources into structured pages so the author and future AI sessions can understand a life as an evolving graph of people, places, periods, projects, themes, objects, and relationships.

The wiki is not the raw diary. Raw sources stay in `answers/` and `sources/`. Wiki pages synthesize those sources, cite them, cross-link related pages, and improve over time.

Corrections, reflections, and promoted artifacts are also sources. If a memory was wrong or the author's understanding changed, the wiki should show the original source and the later correction/reflection together instead of erasing the earlier record. If a letter, post, or chapter is promoted, treat it as the author's expression at that moment, not as independent proof of every event inside it.

## First-Pass Privacy Model

Everything is private and owner-only. Do not build access tiers into the first pass.

Each page still carries simple metadata so future sharing can be built without rewriting the corpus:

```yaml
visibility: owner_only
sensitivity: personal
```

Publishing should happen through reviewed `outputs/` or a future `published/` tree, not by exposing the private wiki directly.

## Artifact Sources

Artifact drafts live in `outputs/<artifact>/`. When the author approves one, the workflow can promote its context pack and final version into `sources/artifacts/`.

Artifact source frontmatter includes:

```yaml
type: authored_artifact | artifact_context
source_trust: authored_expression | derived_context
authority: first_person_expression | derived_working_context
artifact_id: mothers-day-2026
artifact_format: letter
generated_from:
  - answers/K1.md
output_path: outputs/mothers-day-2026/v1.md
privacy: owner_only
```

The compiler may use artifact sources as supporting/attributed material. It should not upgrade derived context or generated prose into primary evidence.

## Page Types

| Type | Folder | Purpose |
|------|--------|---------|
| `person` | `wiki/people/` | One page per person who matters in the author's life. |
| `place` | `wiki/places/` | Homes, cities, schools, churches, offices, rooms, countries. |
| `period` | `wiki/periods/` | Seasons of life, transitions, hardships, golden eras. |
| `project` | `wiki/projects/` | Companies, creative work, missions, family projects, major efforts. |
| `theme` | `wiki/themes/` | Recurring emotional or narrative threads. |
| `object` | `wiki/objects/` | Objects with story weight: cars, homes, letters, clothes, artifacts. |
| `relationship` | `wiki/relationships/` | A focused page about how two or more entities connect. |

## Frontmatter

Every page must start with frontmatter:

```yaml
---
title: "Page Title"
type: person | place | period | project | theme | object | relationship
status: active
visibility: owner_only
sensitivity: personal
created: YYYY-MM-DD
last_updated: YYYY-MM-DD
sources:
  - answers/A1.md
sources_count: 1
related:
  - "[[other-page]]"
---
```

## Page Structure

Use only sections supported by source material. Do not add placeholder filler.

```markdown
# Page Title

> One-line summary grounded in cited source material. [answers/A1.md]

## What We Know
Specific, cited synthesis.

## Story Threads
How this person/place/theme appears across the author's life.

## Open Questions
Questions worth asking in future Lifehug passes.

## Related Pages
- [[related-page]] — why it connects
```

## Citation Rules

Every factual or interpretive claim should cite source files using inline square brackets:

```markdown
Dave remembers Redlands through financial stress and movement [answers/A3.md].
```

If a useful insight is not yet strongly supported, phrase it as a hypothesis and cite the source:

```markdown
Hypothesis: the later Etherfuse urgency may echo early financial instability [answers/A3.md, answers/H6.md].
```

## Compiler Rules

1. Always read existing pages before rewriting them.
2. Preserve useful existing material unless the source evidence has changed.
3. Add cross-links when a page mentions another known page.
4. Keep raw emotional detail grounded in citations.
5. Flag contradictions or sensitive publishing risks instead of hiding them.
6. Improve pages incrementally; a page should get better or stay unchanged.
7. Treat changed memories and contradictions as story signals. They may deserve a question candidate, relationship note, or self-knowledge page.

## Good Lifehug Wiki Pages

A good page helps the author see their life more clearly. It should answer:

- What is this person/place/period/project/theme?
- Where does it appear in the source material?
- Why does it matter to the author's larger story?
- What does it connect to?
- What should Lifehug ask next?
