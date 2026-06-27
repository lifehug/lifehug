# Lifehug Source Contract

Lifehug separates raw life evidence from generated understanding.

## Source Of Truth

The source-of-truth layer is:

- `answers/` for prompted daily answers
- `sources/` for unprompted stories, imports, corrections, reflections, and
  promoted artifacts

The generated layer is:

- `wiki/`
- `outputs/`
- planner queues, reports, candidate stores, and other files under `state/`

## Rules

1. Source files are append-oriented records of what was captured.
2. Do not rewrite old source files to improve the story or change history.
3. If a memory was wrong, create a correction source.
4. If feelings or understanding changed, create a reflection source.
5. The wiki may be deleted and rebuilt because it is compiled from sources.
6. Generated claims should cite source paths.
7. Lint findings are repair work, not shame; some findings become better questions.
8. Finished artifacts can become sources, but they must preserve provenance:
   the final letter/post/chapter is an authored expression, while its context
   pack is derived working material.

## Artifact Sources

Drafting happens under `outputs/<artifact>/`. When an artifact is final enough
to become part of the lifetime record, promote it through the script:

```bash
python3 system/lifehug.py artifact promote-source outputs/<artifact> --kind all
```

This writes immutable source files under `sources/artifacts/` with metadata such
as `type`, `source_trust`, `authority`, `generated_from`, `output_path`, and
`privacy`.

The final artifact is authoritative as the author's expression at that moment.
It is not independent proof of every factual claim inside it. The wiki compiler
treats artifact and context sources as supporting/attributed material so the
system can learn from the produced work without circularly upgrading generated
text into primary evidence.

## Repair Model

Safe mechanical repairs may update metadata or the manifest without changing the
captured body. Story repairs should be additive:

```bash
python3 system/lifehug.py correct-source answers/A1.md --kind factual
python3 system/lifehug.py reflect-source answers/A1.md
```

Corrections and reflections are themselves source files, so the wiki can compile
the original memory and the later understanding together.
