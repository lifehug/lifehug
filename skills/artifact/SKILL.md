---
name: artifact
description: "Create Lifehug artifacts — letters, posts, captions, chapters, speeches — from accumulated story material, then optionally promote the final work and context pack into immutable Lifehug sources. Use when the user says /artifact, artifact:, write/create/draft a letter/post/caption/chapter, or wants an occasion output like Mother's Day, birthday, anniversary, memorial, or milestone."
---

# Lifehug Artifact Creator

Artifacts are the pieces Lifehug is ultimately trying to help the author make:
letters, posts, captions, chapters, speeches, and other authored outputs. This
skill is script-first. Use `system/lifehug.py artifact ...`; do not hand-create
metadata or source files.

## Find The Workspace

Use the current repo if it has `system/lifehug.py`. Otherwise check
`~/Workspace/dave`, `~/Workspace/lifehug`, `~/lifehug`. Run commands from the
workspace root.

## Trigger / Keyword

Explicit triggers:
- `/artifact`
- `artifact:`
- "write/create/draft a letter/post/caption/chapter/speech"
- occasion language such as Mother's Day, birthday, anniversary, memorial, or milestone

On Telegram/OpenClaw, treat those messages as artifact requests, not daily
answers. If the user sends a long story without asking for an output, use
`ingest-story` instead.

## Workflow

Ask only for missing essentials:
- subject/person/topic
- occasion
- format: `letter`, `tweet`, `instagram`, `post`, or `chapter`
- date, if relevant
- audience/privacy, if relevant

Create the artifact task and context pack:

```bash
python3 system/lifehug.py artifact new \
  --subject "<subject>" \
  --occasion "<occasion>" \
  --format <letter|tweet|instagram|post|chapter> \
  --date <YYYY-MM-DD>
```

Print the generation prompt:

```bash
python3 system/lifehug.py artifact prompt outputs/<artifact>
```

You are the model on desktop. In Telegram/OpenClaw, the agent is the model.
Write only the artifact text, following the prompt.

Save the draft:

```bash
printf '%s\n' "$CONTENT" | python3 system/lifehug.py artifact save outputs/<artifact> --final
```

If the user wants revisions, edit from the saved draft and context, then save a
new version:

```bash
printf '%s\n' "$CONTENT" | python3 system/lifehug.py artifact save outputs/<artifact> \
  --feedback "<what changed>" --final
```

When the user approves it as final, promote it into the source layer:

```bash
python3 system/lifehug.py artifact promote-source outputs/<artifact> --kind all
python3 system/lifehug.py compile
```

`--kind all` stores both:
- `artifact_context`: the derived context pack that shaped the work
- `authored_artifact`: the final letter/post/chapter itself

## Source Contract

The final artifact is authoritative as the author's expression at that moment.
It is not independent proof of every underlying event. The context pack is
derived working material. The wiki compiler treats both as supporting,
attributed sources so the system learns from produced work without circularly
turning generated text into primary evidence.

Never rewrite promoted artifact source bodies. If the user changes their mind
later, create a new version or add a correction/reflection source.
